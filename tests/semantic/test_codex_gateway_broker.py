from __future__ import annotations

import hashlib
import itertools
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

from tests.support.platform_filesystem import (
    create_symlink_or_skip,
    native_absolute_test_path,
)
from tests.support.platform_process import run_model_argv
from .support import codex_gateway_broker as broker_module  # pyright: ignore[reportMissingImports]
from .support import codex_typed_draft_evidence_v3 as typed_evidence_module  # pyright: ignore[reportMissingImports]
from .support.codex_harness import (  # pyright: ignore[reportMissingImports]
    WindowsPowerShellCoreHost,
    parse_command_argv,
)
from .support.codex_gateway_broker import (  # pyright: ignore[reportMissingImports]
    BASH_ENV_NAME,
    BROKER_TOKEN_ENV,
    BoundedIntegerArgument,
    CodexGatewayBroker,
    DraftTypedActionBatchArgument,
    DraftTypedActionArgument,
    DraftActionMetadataBinding,
    DraftActionResponseBinding,
    ExactArgumentAlternatives,
    ExpectedGatewayStep,
    GATEWAY_REQUIRED_ENV,
    GatewayDerivedReferenceActivationAllowance,
    GatewayBrokerError,
    GatewayInvocationError,
    InlineTypedOperationArgument,
    MetadataBoundJsonArgument,
    MetadataQueryArgument,
    MetadataTokenProjection,
    ResponseBinding,
    ResponseBindingOrExactArgument,
    SemanticJsonArgument,
    SHIM_TRUSTED_PYTHON_ENV,
    SUBSCRIPTION_ACK_CONTRACT,
    SUBSCRIPTION_ACK_NONCE_ENV,
    SUBSCRIPTION_ACK_PATH_ENV,
    SUBSCRIPTION_ACK_STEP_ENV,
    SUBSCRIPTION_ACK_TOPIC_ENV,
    TrustedSubscriptionAckExpectation,
    TrustedSubscriptionAckSpec,
    WINDOWS_COMMAND_SHIM_NAMES,
    WINDOWS_SHIM_SCRIPT_NAME,
    gateway_step_prefix_matches,
    gateway_step_sequence_matches,
    reconcile_gateway_command_prefix,
    reconcile_gateway_commands,
    project_required_metadata_tokens,
    resolve_gateway_invocation,
)
from .support.codex_gateway_contracts import (
    TASK_LOCAL_RUNNER_POSIX,
    TASK_LOCAL_RUNNER_WINDOWS,
    task_local_runner_matches_normalized,
)
from .support.codex_eval_protocol_v3 import (  # pyright: ignore[reportMissingImports]
    CompoundUndoChildExpectation,
    build_audio_convert_business_transaction_steps,
    build_audio_import_composer_transaction_steps,
    build_compound_undo_business_transaction_steps,
    build_core_business_transaction_steps,
    build_object_graph_business_transaction_steps,
    build_object_set_composer_transaction_steps,
    build_soundengine_business_transaction_steps,
    build_transaction_protocol,
    media_pool_business_call_step,
    typed_read_draft_steps,
)
from wwise_waapi.operation_composer import (
    apply_composer_action,
    composition_projection,
    materialize_operation_request,
    new_composition,
    operation_composer_digest,
    operation_draft_public_projection,
    typed_action_cli_arguments,
)


@pytest.mark.parametrize(
    ("subcommand", "arguments", "index", "supplied", "expected"),
    (
        (
            "draft-discover-fields",
            ("--meaning", "pitch"),
            1,
            "Pitch",
            "pitch",
        ),
        (
            "draft-discover-fields",
            ("--meaning", "FadeTime"),
            1,
            "Play Action Fade Time",
            "FadeTime",
        ),
        (
            "draft-discover-fields",
            ("--meaning", "Delay"),
            1,
            "Play Action delay time in seconds",
            "Delay",
        ),
    ),
)
def test_closed_business_literal_equivalence_is_broker_owned(
    subcommand: str,
    arguments: tuple[str, ...],
    index: int,
    supplied: str,
    expected: str,
) -> None:
    step = ExpectedGatewayStep("step", subcommand, arguments)

    assert broker_module._closed_business_literal_equivalent(
        step,
        index,
        supplied,
        expected,
    ) is True


def test_closed_business_literal_equivalence_rejects_native_path_type_prefix() -> None:
    step = ExpectedGatewayStep(
        "step",
        "draft-bind-object",
        (
            "--object-path-segment",
            "Actor-Mixer Hierarchy",
            "--object-path-segment",
            "Weapons",
        ),
    )

    assert broker_module._closed_business_literal_equivalent(
        step,
        3,
        "<Virtual Folder>Weapons",
        "Weapons",
    ) is False


def test_closed_business_meaning_equivalence_rejects_semantic_negation() -> None:
    step = ExpectedGatewayStep(
        "step",
        "draft-discover-fields",
        ("--meaning", "FadeTime"),
    )

    assert broker_module._closed_business_literal_equivalent(
        step,
        1,
        "not Play Action Fade Time",
        "FadeTime",
    ) is False


@pytest.mark.parametrize(
    ("subcommand", "arguments", "supplied", "expected"),
    (
        (
            "query-object",
            ("--path-segment", "Actor-Mixer Hierarchy"),
            r"\Actor-Mixer Hierarchy",
            "Actor-Mixer Hierarchy",
        ),
        (
            "draft-bind-object",
            ("--object-path-segment", "Actor-Mixer Hierarchy"),
            r"\Actor-Mixer Hierarchy",
            "Actor-Mixer Hierarchy",
        ),
        (
            "draft-declare-new",
            ("--kind", "sound-sfx"),
            "Sound SFX",
            "sound-sfx",
        ),
    ),
)
def test_closed_business_literal_equivalence_rejects_native_spellings(
    subcommand: str,
    arguments: tuple[str, ...],
    supplied: str,
    expected: str,
) -> None:
    step = ExpectedGatewayStep("step", subcommand, arguments)

    assert broker_module._closed_business_literal_equivalent(
        step,
        1,
        supplied,
        expected,
    ) is False


@pytest.mark.parametrize(
    ("platform_name", "copy_family"),
    (("posix", "posix"), ("nt", "model"), ("nt", "powershell")),
)
def test_business_draft_runner_projects_a_compact_copy_only_prefix(
    tmp_path: Path,
    platform_name: str,
    copy_family: str,
) -> None:
    candidate = tmp_path / "candidate" / "scripts" / "run.py"
    invocation = tmp_path / "task" / "scripts" / "run.py"
    candidate.parent.mkdir(parents=True)
    invocation.parent.mkdir(parents=True)
    candidate.write_text("candidate", encoding="utf-8")
    invocation.write_text("task", encoding="utf-8")
    argv = [
        "python",
        str(candidate),
        "gateway.py",
        "draft-bind-object",
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "2",
    ]
    if copy_family == "powershell":
        argv.extend(("--opaque-long-value", "x" * 1_100))
    binding = {
        "contract": "waapi-skill.business-draft-next-action/v1",
        "required_next_phase": "bind_next_object",
        "shell_tool_timeout_ms": 30_000,
        "route": {
            "fixed_argv_prefix_copy": (
                broker_module.encode_windows_powershell_argv(argv)
                if copy_family == "powershell"
                else (
                    broker_module.encode_windows_model_argv(argv)
                    if copy_family == "model"
                    else shlex.join(argv)
                )
            ),
            "fixed_argv_prefix_copy_instruction": {
                "contract": (
                    "waapi-skill.operation-draft-command-copy-instruction/v1"
                ),
                "source_field": "fixed_argv_prefix_copy",
                "action": (
                    "copy_verbatim_then_append_complete_typed_action_groups"
                ),
            },
        },
    }

    projected = broker_module._project_operation_draft_runner(  # noqa: SLF001
        binding,
        candidate_runner=candidate,
        invocation_runner=invocation,
        platform_name=platform_name,
    )

    projected_argv = broker_module._decode_draft_copy_command(  # noqa: SLF001
        projected["route"]["fixed_argv_prefix_copy"],
        platform_name=platform_name,
    )
    assert projected_argv[1] == (
        TASK_LOCAL_RUNNER_WINDOWS
        if platform_name == "nt"
        else TASK_LOCAL_RUNNER_POSIX
    )
    assert "fixed_argv_prefix" not in projected["route"]

    tampered = json.loads(json.dumps(binding))
    tampered_argv = [*argv]
    tampered_argv[1] = str(tmp_path / "other" / "scripts" / "run.py")
    tampered["route"]["fixed_argv_prefix_copy"] = (
        broker_module.encode_windows_powershell_argv(tampered_argv)
        if copy_family == "powershell"
        else (
            broker_module.encode_windows_model_argv(tampered_argv)
            if copy_family == "model"
            else shlex.join(tampered_argv)
        )
    )
    with pytest.raises(
        GatewayInvocationError,
        match="business Draft copy-ready prefix is not exact",
    ):
        broker_module._project_operation_draft_runner(  # noqa: SLF001
            tampered,
            candidate_runner=candidate,
            invocation_runner=invocation,
            platform_name=platform_name,
        )


def test_broker_accepts_media_pool_business_aliases_in_any_flag_order(
    tmp_path: Path,
) -> None:
    step = media_pool_business_call_step(
        "media.get",
        scenario_id="VS25-F-MEDIAPOOL-GET-01",
        args={
            "databases": [r"\Databases\Project Originals"],
            "filters": [
                {
                    "type": "field",
                    "field": "Filename",
                    "operator": "contains",
                    "value": "footstep",
                },
                {
                    "type": "field",
                    "field": "WAV/Duration",
                    "operator": "lessThan",
                    "value": 0.8,
                },
            ],
            "maxResults": 200,
        },
        options={"return": ["Path", "FileId", "Db", "Filename", "WAV/Duration"]},
        post_filter={
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": "footstep",
            "limit": 20,
        },
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(step,),
        expected_wwise_version="2025.1",
    )
    actual = (
        "core-call",
        "ak.wwise.core.mediaPool.get",
        "--max-results",
        "200",
        "--final-limit",
        "20",
        "--database-scope",
        "Project Originals",
        "--text-filter",
        "name",
        "contains",
        "footstep",
        "--number-filter",
        "duration",
        "lessThan",
        "0.8",
        "--exact-name-contains",
        "footstep",
        "--sort-by",
        "duration",
        "ascending",
        "--sort-by",
        "path",
        "ascending",
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        step,
        actual,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == actual


def test_broker_accepts_redundant_default_media_pool_projection_fields(
    tmp_path: Path,
) -> None:
    """Canonical fields are always returned, so naming them again is harmless."""

    step = media_pool_business_call_step(
        "media.get",
        scenario_id="VS25-F-MEDIAPOOL-GET-01",
        args={
            "databases": [r"\Databases\Project Originals"],
            "filters": [
                {
                    "type": "field",
                    "field": "Filename",
                    "operator": "contains",
                    "value": "footstep",
                },
                {
                    "type": "field",
                    "field": "WAV/Duration",
                    "operator": "lessThan",
                    "value": 0.8,
                },
            ],
            "maxResults": 200,
        },
        options={"return": ["Path", "FileId", "Db", "Filename", "WAV/Duration"]},
        post_filter={
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": "footstep",
            "limit": 20,
        },
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(step,),
        expected_wwise_version="2025.1",
    )
    actual = (
        "core-call",
        "ak.wwise.core.mediaPool.get",
        "--max-results",
        "200",
        "--database-scope",
        r"\Databases\Project Originals",
        "--text-filter",
        "Filename",
        "contains",
        "footstep",
        "--number-filter",
        "WAV/Duration",
        "lessThan",
        "0.8",
        "--include-field",
        "Filename",
        "--include-field",
        "WAV/Duration",
        "--exact-name-contains",
        "footstep",
        "--final-limit",
        "20",
        "--sort-by",
        "WAV/Duration",
        "ascending",
        "--sort-by",
        "Path",
        "ascending",
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        step,
        actual,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == actual
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.builders.debug_lua import LUA_SOURCE_AUTHORITY
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.operation_registry import operation_request_schema_digest
from wwise_waapi.transactions import confirmation_token_for
from wwise_waapi.platform_commands import (
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    decode_windows_model_argv,
    decode_windows_powershell_argv,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)
from wwise_waapi.typed_requests import request_contract
from wwise_waapi.typed_operations import inline_operation_cli_arguments


FAKE_ARTIFACT_HASH = "a" * 64
FAKE_LAST_EVENT_HASH = "b" * 64
FAKE_EVENT_SEQUENCE = 2


def _typed_draft_argv(action: dict[str, object]) -> tuple[str, ...]:
    return ("--compact", "--facts", *typed_action_cli_arguments(action))


def _compact_next_action_binding(
    *, shell_tool_timeout_ms: object = 30_000
) -> dict[str, object]:
    completion_argv = [
        "python",
        "/owned/run.py",
        "gateway.py",
        "draft-check",
        "od1-0123456789abcdef0123456789abcdef",
        "--task-authority",
        "da1-0123456789abcdef0123456789abcdef01234567",
        "--expected-revision",
        "2",
    ]
    return {
        "shell_tool_timeout_ms": shell_tool_timeout_ms,
        "completion_candidate": {
            "condition": (
                "all_current_business_request_facts_and_disclosures_submitted"
            ),
            "business_completion_check": {
                "source": "current_user_business_request",
                "schema_required_fields_complete_is_insufficient": True,
                "all_user_present_optional_map_and_constant_facts_required": True,
                "exact_values_and_object_types_required": True,
            },
            "is_next_command_when_condition_true": True,
            "fixed_argv_prefix": completion_argv,
            "copy_exactly": True,
            "copy_instruction": {
                "contract": (
                    "waapi-skill.operation-draft-command-copy-instruction/v1"
                ),
                "source_field": "copy_command",
                "action": "execute_verbatim_as_one_shell_tool_call",
                "forbidden_transformations": [
                    "reconstruct",
                    "shorten",
                    "normalize",
                    "substitute_path_segments",
                    "select_another_field",
                ],
            },
            "copy_command": shlex.join(completion_argv),
            "allowed_suffix_source": "request_schema_terminal_arguments_only",
            "draft_apply_action_check": "invalid",
            "when_condition_false": (
                "continue_with_one_atomic_typed_action_batch_or_dynamic_disclosure"
            ),
        },
    }


def test_compact_generic_typed_fact_receipt_accepts_its_real_fact_handle_family() -> None:
    action, created, affected, summary = broker_module._draft_compact_action_result(
        {
            "action_result": {
                "contract": "waapi-skill.operation-draft-action-result/v1",
                "action": "add_typed_fact",
                "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
                "affected_handles": ["trh1-4dedc2c7c0aea1301b0d773f"],
            },
            "current_facts_summary": {
                "contract": "waapi-skill.operation-draft-facts-summary/v1",
                "target_count": 1,
                "handle_count": 1,
                "canonical_sha256": "1" * 64,
            },
            "next_action_binding": _compact_next_action_binding(),
        }
    )

    assert action == "add_typed_fact"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {"trh1-4dedc2c7c0aea1301b0d773f"}
    assert summary["target_count"] == 1


def test_compact_required_incomplete_receipt_omits_completion_candidate() -> None:
    payload = {
        "schema_required_fields_status": "incomplete",
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trh1-4dedc2c7c0aea1301b0d773f"],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": {
            "shell_tool_timeout_ms": 30_000,
        },
    }

    action, created, affected, summary = broker_module._draft_compact_action_result(
        payload
    )

    assert action == "add_typed_fact"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {"trh1-4dedc2c7c0aea1301b0d773f"}
    assert summary["canonical_sha256"] == "1" * 64


def test_compact_required_incomplete_receipt_rejects_completion_candidate() -> None:
    payload = {
        "schema_required_fields_status": "incomplete",
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trh1-4dedc2c7c0aea1301b0d773f"],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": _compact_next_action_binding(),
    }

    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


def test_compact_generic_typed_fact_receipt_accepts_closed_required_followups() -> None:
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trh1-4dedc2c7c0aea1301b0d773f"],
            "required_followup_facts": [
                {
                    "reason": "selected_branch_constant",
                    "is_next_command": True,
                    "literal_copy_policy": {
                        "copy_fixed_full_argv_exactly": True,
                        "business_value_substitution": "invalid",
                    },
                    "fixed_full_argv": [
                        "python",
                        "/owned/run.py",
                        "gateway.py",
                        "draft-apply",
                        "od1-0123456789abcdef0123456789abcdef",
                        "--task-authority",
                        "da1-0123456789abcdef0123456789abcdef01234567",
                        "--expected-revision",
                        "2",
                        "--compact",
                        "--facts",
                        "--action",
                        "add_typed_fact",
                        "--fact-action",
                        "set",
                        "--field-handle",
                        "trh1-4dedc2c7c0aea1301b0d773f",
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
                        "trh1-4dedc2c7c0aea1301b0d773f",
                        "--value-type",
                        "string",
                        "--fact-value",
                        "path",
                    ],
                }
            ],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": _compact_next_action_binding(),
    }

    action, created, affected, summary = broker_module._draft_compact_action_result(
        payload
    )

    assert action == "add_typed_fact"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {"trh1-4dedc2c7c0aea1301b0d773f"}
    assert summary["canonical_sha256"] == "1" * 64


def test_compact_generic_typed_fact_receipt_accepts_closed_construction_continuation() -> None:
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trm1-4dedc2c7c0aea1301b0d773f"],
            "construction_continuation": {
                "source": "most_recent_typed_container_handle_response",
                "response_was_complete_not_truncated": True,
                "current_handle": "trm1-4dedc2c7c0aea1301b0d773f",
                "completed_fact_action": "map-put",
                "next_rule": (
                    "continue_with_the_next_business_present_child_contract_"
                    "fact_in_queue_index_order"
                ),
                "stop_cancel_or_claim_truncation_before_current_root_is_complete": (
                    "invalid"
                ),
                "current_key": "children",
            },
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": {
            "shell_tool_timeout_ms": 30_000,
        },
    }

    action, created, affected, summary = broker_module._draft_compact_action_result(
        payload
    )

    assert action == "add_typed_fact"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {"trm1-4dedc2c7c0aea1301b0d773f"}
    assert summary["target_count"] == 1


def test_compact_generic_typed_fact_receipt_accepts_exact_container_resume() -> None:
    resume = {
        "contract": "waapi-skill.typed-container-handle/v1",
        "response_handle": "trm1-111111111111111111111111",
        "completed_candidate": "deferred_fact_queue",
        "decision_pointer": "/continuation/next_command_decision/evaluate_in_order",
        "selection": "first_remaining_business_present_candidate_in_order",
        "continue_in_same_turn": True,
        "after_exhausted": "resume_ancestor_response_stack",
        "ancestor_resume_gate": (
            "current_response_and_all_descendant_business_candidates_exhausted"
        ),
        "ancestor_next_item_source": (
            "ancestor_next_item_disclosure.copy_command_by_shape"
        ),
        "ancestor_next_item_disclosure": {
            "condition": "current_business_request_contains_next_complex_item",
            "business_cardinality_authority": "current_business_request",
            "index": 2,
            "copy_command_by_shape": {
                "object": (
                    "python /owned/run.py gateway.py request-array-item "
                    "soundbank.setInclusions --schema-digest "
                    f"{'1' * 64} --array-handle "
                    "trh1-111111111111111111111111 --index 2 --shape object"
                )
            },
        },
        "retype_schema_digest": "invalid",
    }
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trm1-4dedc2c7c0aea1301b0d773f"],
            "construction_continuation": {
                "source": "most_recent_typed_container_handle_response",
                "response_was_complete_not_truncated": True,
                "current_handle": "trm1-4dedc2c7c0aea1301b0d773f",
                "completed_fact_action": "map-put",
                "next_rule": (
                    "resume_previous_container_response_after_deferred_fact_queue"
                ),
                "stop_cancel_or_claim_truncation_before_current_root_is_complete": (
                    "invalid"
                ),
                "current_key": "children",
                "resume_previous_container_response": resume,
            },
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": {
            "contract": "waapi-skill.operation-draft-next-action/v1",
            "shell_tool_timeout_ms": 30_000,
            "fixed_argv_prefix": [
                "python", "/owned/run.py", "gateway.py", "draft-apply",
                "od1-0123456789abcdef0123456789abcdef",
                "--task-authority",
                "da1-0123456789abcdef0123456789abcdef01234567",
                "--expected-revision", "2", "--compact", "--facts",
            ],
            "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency": [
                "--action", "<action-name>", "<typed-fact-arguments>",
            ],
            "replace_only": ["<action-name>", "<typed-fact-arguments>"],
            "resume_previous_container_response": resume,
            "prompt_fact_completion_guard": {
                "schema_optional_is_not_evidence_of_prompt_absence": True,
                "account_for_every_prompt_present_scalar_array_item_and_map_entry": True,
                "copy_boolean_values_exactly": True,
                "infer_or_replace_prompt_values": "invalid",
            },
        },
    }

    action, created, affected, summary = broker_module._draft_compact_action_result(
        payload
    )

    assert action == "add_typed_fact"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {"trm1-4dedc2c7c0aea1301b0d773f"}
    assert summary["canonical_sha256"] == "1" * 64

    tampered = json.loads(json.dumps(payload))
    disclosure = tampered["action_result"]["construction_continuation"][
        "resume_previous_container_response"
    ]["ancestor_next_item_disclosure"]
    disclosure["copy_command_by_shape"]["object"] = disclosure[
        "copy_command_by_shape"
    ]["object"].replace("--index 2", "--index 3")
    tampered["next_action_binding"]["resume_previous_container_response"] = (
        tampered["action_result"]["construction_continuation"][
            "resume_previous_container_response"
        ]
    )
    with pytest.raises(
        GatewayInvocationError,
        match="invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(tampered)


def test_compact_generic_typed_fact_batch_accepts_exact_node_resume() -> None:
    response_handle = "trm1-4dedc2c7c0aea1301b0d773f"
    resume = {
        "contract": "waapi-skill.typed-container-handle/v1",
        "response_handle": response_handle,
        "completed_candidate": "current_node_fact_batch",
        "decision_pointer": "/business_sibling_transition",
        "selection": "business_present_sibling_before_ancestor_item",
        "continue_in_same_turn": True,
        "after_exhausted": "resume_ancestor_response_stack",
        "ancestor_resume_gate": (
            "current_response_and_all_descendant_business_candidates_exhausted"
        ),
        "ancestor_next_item_source": "next_item_disclosure.copy_command_by_shape",
        "business_sibling_transition": {
            "condition": "current_business_request_contains_next_complex_member",
            "business_value_pointer": "/args/inclusions/0/filters",
            "key": "filters",
            "after": "current_branch_descendant_disclosures",
            "after_current_node_facts": True,
            "absent_member_forbidden": True,
            "is_next_command": False,
            "argv_by_shape": {
                "array": [
                    "request-map-container",
                    "soundbank.setInclusions",
                    "--map-handle",
                    response_handle,
                    "--key",
                    "filters",
                    "--shape",
                    "array",
                    "--parent-schema-token",
                    "trl2-WyJ0cmgxLTExMTExMTExMTExMTExMTExMTExMTExMSIsIjAiLCJvYmplY3QiLG51bGxd",
                ]
            },
            "copy_command_by_shape": {
                "array": (
                    "python /owned/run.py gateway.py request-map-container "
                    "soundbank.setInclusions --map-handle "
                    f"{response_handle} --key filters --shape array "
                    "--parent-schema-token "
                    "trl2-WyJ0cmgxLTExMTExMTExMTExMTExMTExMTExMTExMSIsIjAiLCJvYmplY3QiLG51bGxd"
                )
            },
        },
        "retype_schema_digest": "invalid",
    }
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "batch",
            "last_action": "add_typed_fact",
            "action_count": 3,
            "applied_atomically": True,
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": [response_handle],
            "construction_continuation": {
                "source": "most_recent_typed_container_handle_response",
                "response_was_complete_not_truncated": True,
                "current_handle": response_handle,
                "completed_fact_action": "batch",
                "next_rule": (
                    "resume_previous_container_response_after_current_node_fact_batch"
                ),
                "stop_cancel_or_claim_truncation_before_current_root_is_complete": (
                    "invalid"
                ),
                "resume_previous_container_response": resume,
            },
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 3,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": {
            "contract": "waapi-skill.operation-draft-next-action/v1",
            "shell_tool_timeout_ms": 30_000,
            "fixed_argv_prefix": [
                "python", "/owned/run.py", "gateway.py", "draft-apply",
                "od1-0123456789abcdef0123456789abcdef",
                "--task-authority",
                "da1-0123456789abcdef0123456789abcdef01234567",
                "--expected-revision", "4", "--compact", "--facts",
            ],
            "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency": [
                "--action", "<action-name>", "<typed-fact-arguments>",
            ],
            "replace_only": ["<action-name>", "<typed-fact-arguments>"],
            "resume_previous_container_response": resume,
            "prompt_fact_completion_guard": {
                "schema_optional_is_not_evidence_of_prompt_absence": True,
                "account_for_every_prompt_present_scalar_array_item_and_map_entry": True,
                "copy_boolean_values_exactly": True,
                "infer_or_replace_prompt_values": "invalid",
            },
        },
    }

    action, created, affected, summary = broker_module._draft_compact_action_result(
        payload
    )

    assert action == "batch"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {response_handle}
    assert summary["target_count"] == 3

    tampered = json.loads(json.dumps(payload))
    tampered_resume = tampered["action_result"]["construction_continuation"][
        "resume_previous_container_response"
    ]
    tampered_resume["business_sibling_transition"]["copy_command_by_shape"][
        "array"
    ] = tampered_resume["business_sibling_transition"]["copy_command_by_shape"][
        "array"
    ].replace("--key filters", "--key Debug")
    tampered["next_action_binding"]["resume_previous_container_response"] = (
        tampered_resume
    )
    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(tampered)

    payload["schema_required_fields_status"] = "complete"
    payload["next_action_binding"]["completion_candidate"] = (
        _compact_next_action_binding()["completion_candidate"]
    )
    action, created, affected, summary = (
        broker_module._draft_compact_action_result(payload)
    )
    assert action == "batch"
    assert created == {"tdh1-c12aa1ea49a4d727357b105b"}
    assert affected == {response_handle}
    assert summary["target_count"] == 3

    payload["next_action_binding"].pop("completion_candidate")
    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


def test_compact_generic_typed_fact_receipt_rejects_misbound_container_resume() -> None:
    resume = {
        "contract": "waapi-skill.typed-container-handle/v1",
        "response_handle": "trm1-111111111111111111111111",
        "completed_candidate": "deferred_fact_queue",
        "decision_pointer": "/continuation/next_command_decision/evaluate_in_order",
        "selection": "first_remaining_business_present_candidate_in_order",
        "continue_in_same_turn": True,
        "after_exhausted": "resume_ancestor_response_stack",
        "ancestor_resume_gate": (
            "current_response_and_all_descendant_business_candidates_exhausted"
        ),
        "ancestor_next_item_source": "next_item_disclosure.copy_command_by_shape",
        "retype_schema_digest": "invalid",
    }
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trm1-4dedc2c7c0aea1301b0d773f"],
            "construction_continuation": {
                "source": "most_recent_typed_container_handle_response",
                "response_was_complete_not_truncated": True,
                "current_handle": "trm1-4dedc2c7c0aea1301b0d773f",
                "completed_fact_action": "map-put",
                "next_rule": (
                    "resume_previous_container_response_after_deferred_fact_queue"
                ),
                "stop_cancel_or_claim_truncation_before_current_root_is_complete": (
                    "invalid"
                ),
                "current_key": "children",
                "resume_previous_container_response": resume,
            },
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": {
            "contract": "waapi-skill.operation-draft-next-action/v1",
            "shell_tool_timeout_ms": 30_000,
            "fixed_argv_prefix": [
                "python", "/owned/run.py", "gateway.py", "draft-apply",
                "od1-0123456789abcdef0123456789abcdef",
                "--task-authority",
                "da1-0123456789abcdef0123456789abcdef01234567",
                "--expected-revision", "2", "--compact", "--facts",
            ],
            "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency": [
                "--action", "<action-name>", "<typed-fact-arguments>",
            ],
            "replace_only": ["<action-name>", "<typed-fact-arguments>"],
            "resume_previous_container_response": {
                **resume,
                "response_handle": "trm1-222222222222222222222222",
            },
        },
    }

    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("source", "caller_supplied"),
        ("response_was_complete_not_truncated", False),
        ("current_handle", "trm1-000000000000000000000000"),
        ("completed_fact_action", "map-remove"),
        ("next_rule", "skip_remaining_facts"),
        ("stop_cancel_or_claim_truncation_before_current_root_is_complete", "ok"),
    ),
)
def test_compact_generic_typed_fact_receipt_rejects_tampered_construction_continuation(
    key: str,
    value: object,
) -> None:
    continuation = {
        "source": "most_recent_typed_container_handle_response",
        "response_was_complete_not_truncated": True,
        "current_handle": "trm1-4dedc2c7c0aea1301b0d773f",
        "completed_fact_action": "map-put",
        "next_rule": (
            "continue_with_the_next_business_present_child_contract_"
            "fact_in_queue_index_order"
        ),
        "stop_cancel_or_claim_truncation_before_current_root_is_complete": "invalid",
        "current_key": "children",
    }
    continuation[key] = value
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": ["tdh1-c12aa1ea49a4d727357b105b"],
            "affected_handles": ["trm1-4dedc2c7c0aea1301b0d773f"],
            "construction_continuation": continuation,
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": {"shell_tool_timeout_ms": 30_000},
    }

    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


@pytest.mark.parametrize("timeout_ms", (None, 10_000, "30000"))
def test_compact_receipt_rejects_missing_or_tampered_shell_tool_timeout(
    timeout_ms: object,
) -> None:
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": [],
            "affected_handles": [],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": _compact_next_action_binding(
            shell_tool_timeout_ms=timeout_ms
        ),
    }

    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


@pytest.mark.parametrize(
    "candidate",
    (
        None,
        {
            **_compact_next_action_binding()["completion_candidate"],
            "draft_apply_action_check": "allowed",
        },
        {
            **_compact_next_action_binding()["completion_candidate"],
            "copy_command": "python reconstructed-draft-check.py",
        },
        {
            **_compact_next_action_binding()["completion_candidate"],
            "business_completion_check": {
                "source": "schema_required_fields",
                "schema_required_fields_complete_is_insufficient": False,
                "all_user_present_optional_map_and_constant_facts_required": False,
                "exact_values_and_object_types_required": False,
            },
        },
    ),
)
def test_compact_receipt_rejects_missing_or_tampered_completion_candidate(
    candidate: object,
) -> None:
    binding = _compact_next_action_binding()
    binding["completion_candidate"] = candidate
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": [],
            "affected_handles": [],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": binding,
    }

    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


def test_compact_completion_candidate_binds_copy_command_to_runner_path_flavor() -> None:
    candidate = dict(_compact_next_action_binding()["completion_candidate"])
    windows_prefix = list(candidate["fixed_argv_prefix"])
    windows_prefix[1] = (
        r"C:\Agent Workspace\.agents\skills\waapi-skill\scripts\run.py"
    )
    candidate["fixed_argv_prefix"] = windows_prefix
    candidate["copy_command"] = shlex.join(windows_prefix)

    assert broker_module._valid_draft_completion_candidate(candidate) is False

    candidate["copy_command"] = encode_windows_model_argv(windows_prefix)
    assert broker_module._valid_draft_completion_candidate(candidate) is True


def test_compact_completion_candidate_binds_exact_request_schema_terminal_arguments() -> None:
    candidate = dict(_compact_next_action_binding()["completion_candidate"])
    result_filter = request_contract(
        "2025.1",
        "ak.wwise.core.mediaPool.get",
    ).as_gateway_payload()["result_filter"]
    candidate["request_schema_terminal_arguments"] = {
        "source_pointer": "/request-schema/result_filter",
        "append_before_execute": True,
        "contract": result_filter,
    }

    assert broker_module._valid_draft_completion_candidate(candidate) is True

    tampered = dict(candidate)
    tampered["request_schema_terminal_arguments"] = {
        **candidate["request_schema_terminal_arguments"],
        "source_pointer": "/invented",
    }
    assert broker_module._valid_draft_completion_candidate(tampered) is False


def test_current_evidence_accepts_and_binds_closed_required_followups() -> None:
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": [],
            "affected_handles": ["trh1-4dedc2c7c0aea1301b0d773f"],
            "required_followup_facts": [
                {
                    "reason": "selected_branch_constant",
                    "is_next_command": True,
                    "literal_copy_policy": {
                        "copy_fixed_full_argv_exactly": True,
                        "business_value_substitution": "invalid",
                    },
                    "fixed_full_argv": [
                        "python",
                        "/owned/run.py",
                        "gateway.py",
                        "draft-apply",
                        "od1-0123456789abcdef0123456789abcdef",
                        "--task-authority",
                        "da1-0123456789abcdef0123456789abcdef01234567",
                        "--expected-revision",
                        "2",
                        "--compact",
                        "--facts",
                        "--action",
                        "add_typed_fact",
                        "--fact-action",
                        "set",
                        "--field-handle",
                        "trh1-4dedc2c7c0aea1301b0d773f",
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
                        "trh1-4dedc2c7c0aea1301b0d773f",
                        "--value-type",
                        "string",
                        "--fact-value",
                        "path",
                    ],
                }
            ],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
        "next_action_binding": _compact_next_action_binding(),
        "response_integrity": {
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
        },
    }

    action, created, affected, _summary = (
        typed_evidence_module._compact_action_projection(payload)  # noqa: SLF001
    )

    assert action == "add_typed_fact"
    assert created == set()
    assert affected == {"trh1-4dedc2c7c0aea1301b0d773f"}


@pytest.mark.parametrize(
    "followup",
    (
        {"reason": "invented", "typed_fact_arguments": []},
        {
            "reason": "selected_branch_constant",
            "typed_fact_arguments": [
                "--action",
                "add_typed_fact",
                "--fact-action",
                "append",
                "--field-handle",
                "trh1-4dedc2c7c0aea1301b0d773f",
                "--value-type",
                "string",
                "--fact-value",
                "path",
            ],
        },
        {
            "reason": "selected_branch_constant",
            "typed_fact_arguments": [
                "--action",
                "add_typed_fact",
                "--fact-action",
                "set",
                "--field-handle",
                "not-a-handle",
                "--value-type",
                "string",
                "--fact-value",
                "path",
            ],
        },
    ),
)
def test_compact_generic_typed_fact_receipt_rejects_open_followups(
    followup: dict[str, object],
) -> None:
    payload = {
        "action_result": {
            "contract": "waapi-skill.operation-draft-action-result/v1",
            "action": "add_typed_fact",
            "created_handles": [],
            "affected_handles": [],
            "required_followup_facts": [followup],
        },
        "current_facts_summary": {
            "contract": "waapi-skill.operation-draft-facts-summary/v1",
            "target_count": 1,
            "handle_count": 1,
            "canonical_sha256": "1" * 64,
        },
    }

    with pytest.raises(
        GatewayInvocationError,
        match="compact Draft action response has an invalid bounded projection",
    ):
        broker_module._draft_compact_action_result(payload)


@pytest.mark.parametrize(
    ("subcommand", "contracts"),
    (
        (
            "request-map-container",
            {
                "waapi-skill.typed-container-handle/v1",
                "waapi-skill.typed-map-container-choices/v1",
            },
        ),
        (
            "request-array-item",
            {
                "waapi-skill.typed-container-handle/v1",
                "waapi-skill.typed-array-item-choices/v1",
            },
        ),
        (
            "request-schema",
            {
                "waapi-skill.typed-request-schema/v1",
                "waapi-skill.fixed-command-route/v1",
                "waapi-skill.core-business-route/v1",
            },
        ),
        ("operation-schema", {"waapi-skill.gateway-result/v1"}),
    ),
)
def test_broker_binds_each_typed_disclosure_to_its_public_response_contract(
    subcommand: str,
    contracts: set[str],
) -> None:
    step = ExpectedGatewayStep("typed-disclosure", subcommand)

    assert broker_module._gateway_payload_contracts(step) == frozenset(contracts)


@pytest.mark.parametrize("prefix", ("odh1", "odn1", "trh1", "trm1", "trc1"))
def test_broker_accepts_every_gateway_issued_draft_handle_family(prefix: str) -> None:
    assert broker_module._DRAFT_HANDLE_RE.fullmatch(prefix + "-" + "a" * 24)


def test_current_broker_rejects_historical_draft_action_json_protocol() -> None:
    start = ExpectedGatewayStep("draft.start", "draft-start", ("object.set",))
    historical = ExpectedGatewayStep(
        "draft.apply",
        "draft-apply",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(start.name, "/draft/revision"),
            "--action-json",
            DraftTypedActionArgument(
                {
                    "contract": "waapi-skill.operation-draft-action/v1",
                    "action": "add_target",
                    "selector": {"kind": "id", "value": 1},
                }
            ),
        ),
    )
    with pytest.raises(ValueError, match="typed Draft action"):
        broker_module.validate_operation_draft_protocol_steps((start, historical))


def _metadata_discovery_payload(
    *,
    object_type: str = "ActorMixer",
    candidate_names: tuple[str, ...] = ("Volume", "OutputBus"),
    dependency_names: tuple[str, ...] = ("OverrideOutput",),
) -> dict[str, object]:
    def row(name: str) -> dict[str, object]:
        output_bus_activation = (
            [
                {
                    "action": "Enable",
                    "context": "Self",
                    "property": "OverrideOutput",
                    "required_values": [True],
                    "type": "override",
                }
            ]
            if name == "OutputBus" and "OverrideOutput" in dependency_names
            else []
        )
        return {
            "name": name,
            "kind": "reference" if name == "OutputBus" else "property",
            "matched_queries": ["requested field"],
            "same_object_dependencies": (
                ["OverrideOutput"] if output_bus_activation else []
            ),
            "dependency_requirements": output_bus_activation,
            "metadata": {
                "name": name,
                "type": (
                    ""
                    if name == "OutputBus"
                    else "Real32"
                    if name == "Volume"
                    else "Boolean"
                ),
                "default": None,
                "display": {"name": name},
                "restriction": {},
            },
        }

    return {
        "agent_result": {
            "contract": "waapi-skill.metadata-discovery/v2",
            "authority": "live-waapi",
            "result_detail": "compact",
            "scope": {
                "kind": "object_type",
                "requested": object_type,
                "resolved": {
                    "classId": 1,
                    "name": object_type,
                    "type": object_type,
                },
            },
            "candidates": [
                row(name)
                for name in candidate_names
            ],
            "dependency_candidates": [
                row(name)
                for name in dependency_names
            ],
            "dependency_closure_complete": True,
            "unresolved_dependencies": [],
            "selection_required": True,
            "exact_live_name_required_for_mutation": True,
        }
    }


def test_broker_projection_accepts_compact_default_metadata_rows() -> None:
    payload = _metadata_discovery_payload(
        candidate_names=("OutputBus",),
        dependency_names=(),
    )

    assert project_required_metadata_tokens(
        payload,
        object_type="ActorMixer",
        required_tokens=("OutputBus",),
    ) == (
        MetadataTokenProjection("OutputBus", "reference", ""),
    )
    with pytest.raises(ValueError, match="only live references"):
        MetadataTokenProjection("Volume", "property", "")


def test_inline_operation_metadata_binding_accepts_exact_object_scope(
    tmp_path: Path,
) -> None:
    object_id = "{11111111-1111-1111-1111-111111111111}"
    metadata = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object",
            object_id,
            "--query",
            MetadataQueryArgument("output bus"),
            "--limit",
            "8",
        ),
    )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setReference",
        "arguments": {
            "object": {"kind": "id", "value": object_id},
            "reference": "OutputBus",
            "target": {
                "kind": "id",
                "value": "{22222222-2222-2222-2222-222222222222}",
            },
        },
    }
    inline_argv = inline_operation_cli_arguments(request)
    preview = ExpectedGatewayStep(
        "tx01.preview",
        "typed-operation",
        (
            inline_argv[0],
            InlineTypedOperationArgument(
                request,
                operation="object.setReference",
            ),
        ),
        metadata_binding=DraftActionMetadataBinding(
            step=metadata.name,
            object_type="Sound",
            required_tokens=("OutputBus",),
            expected_projection=(
                MetadataTokenProjection("OutputBus", "reference", ""),
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(metadata, preview),
        expected_wwise_version="2022.1",
    )
    payload = _metadata_discovery_payload(
        object_type="Sound",
        candidate_names=("OutputBus",),
        dependency_names=(),
    )
    agent_result = payload["agent_result"]
    assert isinstance(agent_result, dict)
    agent_result["scope"] = {"kind": "object", "object": object_id}
    broker._payloads_by_step[metadata.name] = payload  # noqa: SLF001

    broker._validate_step(  # noqa: SLF001
        preview,
        ("typed-operation", *inline_argv),
    )
    target_first_argv = (*inline_argv[:4], *inline_argv[9:12], *inline_argv[4:9])
    broker._validate_step(  # noqa: SLF001
        preview,
        ("typed-operation", *target_first_argv),
    )

    agent_result["scope"]["object"] = (
        "{33333333-3333-3333-3333-333333333333}"
    )
    with pytest.raises(
        GatewayInvocationError,
        match="exact configured live object scope",
    ):
        broker._validate_step(  # noqa: SLF001
            preview,
            ("typed-operation", *inline_argv),
        )


def test_broker_projection_rejects_legacy_full_contract_as_compact() -> None:
    payload = _metadata_discovery_payload()
    agent_result = payload["agent_result"]
    assert isinstance(agent_result, dict)
    agent_result["contract"] = "waapi-skill.metadata-discovery/v1"
    agent_result.pop("result_detail")

    with pytest.raises(
        GatewayInvocationError,
        match="complete live discovery payload",
    ):
        project_required_metadata_tokens(
            payload,
            object_type="ActorMixer",
            required_tokens=("Volume",),
        )


@pytest.mark.parametrize(
    "identity",
    (
        {"kind": "id", "value": "{11111111-1111-1111-1111-111111111111}"},
        {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
        {
            "kind": "exact-type-name",
            "type": "AuxBus",
            "name": "Gameplay Bus",
        },
        {
            "kind": "direct-child",
            "parent": {
                "kind": "path",
                "value": r"\Events\Default Work Unit\Play_Weather",
            },
            "type": "Action",
        },
        {
            "kind": "scoped-name",
            "name": "Outdoor",
            "type": "Attenuation",
            "parent": {
                "kind": "path",
                "value": r"\Attenuations\Default Work Unit",
            },
        },
    ),
)
def test_audio_import_semantic_broker_accepts_all_closed_identity_selectors(
    identity: dict[str, object],
) -> None:
    assert broker_module._is_audio_import_identity(identity) is True  # noqa: SLF001


@pytest.mark.parametrize(
    "identity",
    (
        {"kind": "waql", "value": "from type AuxBus take 2"},
        {
            "kind": "exact-type-name",
            "type": 'AuxBus where name = "Other"',
            "name": "Gameplay Bus",
        },
        {
            "kind": "exact-type-name",
            "type": "AuxBus",
            "name": 'Gameplay "Bus"',
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "waql", "value": "from type Event take 2"},
            "type": "Action",
        },
        {
            "kind": "direct-child",
            "parent": {
                "kind": "path",
                "value": r"\Events\Default Work Unit\Play_Weather",
            },
            "type": 'Action" or type = "Event',
        },
        {
            "kind": "scoped-name",
            "name": "x" * 256,
            "type": "Attenuation",
            "parent": {
                "kind": "path",
                "value": r"\Attenuations\Default Work Unit",
            },
        },
        {
            "kind": "scoped-name",
            "name": "Outdoor",
            "type": "Attenuation",
            "parent": {
                "kind": "path",
                "value": '\\Attenuations\\Bad"Parent',
            },
        },
    ),
)
def test_audio_import_semantic_broker_rejects_raw_or_open_identity_selectors(
    identity: dict[str, object],
) -> None:
    assert broker_module._is_audio_import_identity(identity) is False  # noqa: SLF001


def fake_confirmation_token(transaction_id: str) -> str:
    return confirmation_token_for(
        transaction_id=transaction_id,
        artifact_hash=FAKE_ARTIFACT_HASH,
        state="awaiting_confirmation",
        event_sequence=FAKE_EVENT_SEQUENCE,
        last_event_hash=FAKE_LAST_EVENT_HASH,
    )


def expected_fake_confirmation_next_command(
    runner_path: Path,
    transaction_id: str,
    *,
    platform_name: str | None = None,
) -> dict[str, object]:
    token = fake_confirmation_token(transaction_id)
    gateway_argv = (
        "confirm",
        transaction_id,
        "--confirmation-token",
        token,
    )
    full_argv = (
        "python",
        str(runner_path.resolve()),
        "gateway.py",
        *gateway_argv,
    )
    result: dict[str, object] = {
        "contract": "waapi-skill.gateway-next-command/v2",
        "command": "confirm",
        "gateway_argv": list(gateway_argv),
        "full_argv": list(full_argv),
        "copy_exactly": True,
        "shell_tool_timeout_ms": 30_000,
        "requires_explicit_user_confirmation": True,
    }
    model_command: str | None = None
    active_platform = os.name if platform_name is None else platform_name
    if active_platform == "nt":
        result["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        shell_command = encode_windows_powershell_argv(full_argv)
        try:
            model_command = encode_windows_model_argv(full_argv)
        except PlatformCommandError:
            model_command = None
    else:
        result["shell_family"] = "posix-sh"
        shell_command = shlex.join(full_argv)
    if model_command is not None:
        result["shell_command"] = shell_command
        result["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
    result["copy_instruction"] = {
        "contract": "waapi-skill.gateway-command-copy-instruction/v2",
        "source_field": (
            "model_command" if model_command is not None else "shell_command"
        ),
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    if model_command is not None:
        result["model_command"] = model_command
    else:
        result["shell_command"] = shell_command
    return result


def test_response_bound_windows_continuation_selects_the_named_model_source(
    tmp_path: Path,
) -> None:
    next_command = expected_fake_confirmation_next_command(
        tmp_path / "Skill with spaces" / "scripts" / "run.py",
        "tx-response-binding",
        platform_name="nt",
    )

    source_field = next_command["copy_instruction"]["source_field"]
    assert source_field == "model_command"
    assert next_command[source_field] == next_command["model_command"]
    assert next_command[source_field] != next_command["shell_command"]
    assert tuple(next_command)[-4:] == (
        "shell_command",
        "model_shell_family",
        "copy_instruction",
        "model_command",
    )


def test_response_bound_windows_continuation_keeps_the_named_legacy_fallback(
    tmp_path: Path,
) -> None:
    runner = tmp_path.joinpath(*(("long-segment",) * 100), "run.py")
    next_command = expected_fake_confirmation_next_command(
        runner,
        "tx-response-binding",
        platform_name="nt",
    )

    source_field = next_command["copy_instruction"]["source_field"]
    assert source_field == "shell_command"
    assert next_command[source_field] == next_command["shell_command"]
    assert "model_command" not in next_command
    assert "model_shell_family" not in next_command
    assert tuple(next_command)[-2:] == ("copy_instruction", "shell_command")


@pytest.mark.parametrize("platform_name", ("posix", "nt"))
def test_broker_projects_only_exact_candidate_continuation_to_task_install(
    tmp_path: Path,
    platform_name: str,
) -> None:
    candidate_runner = (
        tmp_path
        / "waapi-skills"
        / "skills"
        / "waapi-skill"
        / "scripts"
        / "run.py"
    )
    candidate_runner.parent.mkdir(parents=True)
    candidate_runner.write_text("# candidate\n", encoding="utf-8")
    invocation_runner = (
        tmp_path
        / "agent workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
        / "scripts"
        / "run.py"
    )
    original = expected_fake_confirmation_next_command(
        candidate_runner,
        "tx-projected",
        platform_name=platform_name,
    )

    projected = broker_module._project_next_command_runner(  # noqa: SLF001
        original,
        candidate_runner=candidate_runner,
        invocation_runner=invocation_runner,
        platform_name=platform_name,
    )

    expected = expected_fake_confirmation_next_command(
        invocation_runner,
        "tx-projected",
        platform_name=platform_name,
    )
    if platform_name == "nt":
        assert projected["full_argv"] == expected["full_argv"]
        assert decode_windows_powershell_argv(projected["shell_command"]) == tuple(
            expected["full_argv"]
        )
        assert decode_windows_model_argv(projected["model_command"]) == tuple(
            [
                "python",
                TASK_LOCAL_RUNNER_WINDOWS,
                "gateway.py",
                *expected["gateway_argv"],
            ]
        )
        expected["model_command"] = projected["model_command"]
        assert projected == expected
    else:
        assert projected == expected

    tampered = dict(original)
    tampered["shell_command"] = str(original["shell_command"]) + " --extra"
    with pytest.raises(GatewayInvocationError, match="representation is not exact"):
        broker_module._project_next_command_runner(  # noqa: SLF001
            tampered,
            candidate_runner=candidate_runner,
            invocation_runner=invocation_runner,
            platform_name=platform_name,
        )


@pytest.mark.parametrize("platform_name", ("posix", "nt"))
def test_broker_projects_draft_action_and_completion_prefixes_to_task_install(
    tmp_path: Path,
    platform_name: str,
) -> None:
    candidate_runner = tmp_path / "candidate" / "scripts" / "run.py"
    candidate_runner.parent.mkdir(parents=True)
    candidate_runner.write_text("# candidate\n", encoding="utf-8")
    invocation_runner = (
        tmp_path
        / "agent workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
        / "scripts"
        / "run.py"
    )
    action_prefix = [
        "python",
        str(candidate_runner.resolve(strict=True)),
        "gateway.py",
        "draft-apply",
        "od1-0123456789abcdef0123456789abcdef",
        "--task-authority",
        "da1-0123456789abcdef0123456789abcdef01234567",
        "--expected-revision",
        "1",
        "--compact",
        "--facts",
    ]
    completion_prefix = [
        "python",
        str(candidate_runner.resolve(strict=True)),
        "gateway.py",
        "draft-check",
        "od1-0123456789abcdef0123456789abcdef",
        "--task-authority",
        "da1-0123456789abcdef0123456789abcdef01234567",
        "--expected-revision",
        "2",
    ]
    disclosure_argv = [
        "request-array-item",
        "object.create",
        "--array-handle",
        "trh1-0123456789abcdef01234567",
        "--index",
        "1",
        "--shape",
        "object",
    ]
    disclosure_full_argv = [
        "python",
        str(candidate_runner.resolve(strict=True)),
        "gateway.py",
        *disclosure_argv,
    ]
    payload = {
        "contract": "waapi-skill.operation-draft-next-action/v1",
        "shell_tool_timeout_ms": 30_000,
        "fixed_argv_prefix": action_prefix,
        "fixed_argv_prefix_copy": (
            encode_windows_model_argv(action_prefix)
            if platform_name == "nt"
            else shlex.join(action_prefix)
        ),
        "root_dynamic_disclosure_commands": {
            "rows": [
                {
                    "argv_by_shape": {"object": disclosure_argv},
                    "copy_command_by_shape": {
                        "object": (
                            encode_windows_model_argv(disclosure_full_argv)
                            if platform_name == "nt"
                            else shlex.join(disclosure_full_argv)
                        )
                    },
                    "copy_instruction": {
                        "contract": (
                            "waapi-skill.operation-draft-command-copy-instruction/v1"
                        ),
                        "source_field": "copy_command_by_shape.object",
                        "action": "execute_verbatim_as_one_shell_tool_call",
                        "forbidden_transformations": [
                            "reconstruct",
                            "shorten",
                            "normalize",
                            "substitute_path_segments",
                            "select_another_field",
                        ],
                    },
                },
                {
                    "copy_command_by_shape": {
                        "object": (
                            encode_windows_model_argv(disclosure_full_argv)
                            if platform_name == "nt"
                            else shlex.join(disclosure_full_argv)
                        )
                    }
                },
            ]
        },
        "completion_candidate": {
            "fixed_argv_prefix": completion_prefix,
            "copy_command": (
                encode_windows_model_argv(completion_prefix)
                if platform_name == "nt"
                else shlex.join(completion_prefix)
            ),
        },
    }

    projected = broker_module._project_model_visible_runner(  # noqa: SLF001
        payload,
        candidate_runner=candidate_runner,
        invocation_runner=invocation_runner,
        platform_name=platform_name,
    )

    assert projected["fixed_argv_prefix"][1] == str(invocation_runner)
    assert projected["fixed_argv_prefix_copy"] == (
        encode_windows_model_argv(projected["fixed_argv_prefix"])
        if platform_name == "nt"
        else shlex.join(projected["fixed_argv_prefix"])
    )
    disclosure = projected["root_dynamic_disclosure_commands"]["rows"][0]
    projected_disclosure_argv = [
        "python",
        str(invocation_runner),
        "gateway.py",
        *disclosure["argv_by_shape"]["object"],
    ]
    assert disclosure["copy_command_by_shape"]["object"] == (
        encode_windows_model_argv(projected_disclosure_argv)
        if platform_name == "nt"
        else shlex.join(projected_disclosure_argv)
    )
    copy_only_disclosure = projected["root_dynamic_disclosure_commands"]["rows"][1]
    assert copy_only_disclosure["copy_command_by_shape"] == disclosure[
        "copy_command_by_shape"
    ]
    completion = projected["completion_candidate"]
    assert completion["fixed_argv_prefix"][1] == str(invocation_runner)
    assert completion["copy_command"] == (
        encode_windows_model_argv(completion["fixed_argv_prefix"])
        if platform_name == "nt"
        else shlex.join(completion["fixed_argv_prefix"])
    )

    resume = {
        "copy_command_by_shape": {
            "object": (
                encode_windows_model_argv(disclosure_full_argv)
                if platform_name == "nt"
                else shlex.join(disclosure_full_argv)
            )
        }
    }
    projected_draft = broker_module._project_model_visible_runner(  # noqa: SLF001
        {
            "contract": "waapi-skill.operation-draft/v1",
            "next_action_binding": {
                "contract": "waapi-skill.operation-draft-next-action/v1",
                "resume_previous_container_response": resume,
            },
            "action_result": {
                "construction_continuation": {
                    "resume_previous_container_response": resume,
                }
            },
        },
        candidate_runner=candidate_runner,
        invocation_runner=invocation_runner,
        platform_name=platform_name,
    )
    assert projected_draft["action_result"]["construction_continuation"][
        "resume_previous_container_response"
    ] == projected_draft["next_action_binding"][
        "resume_previous_container_response"
    ]

    tampered = json.loads(json.dumps(payload))
    del tampered["root_dynamic_disclosure_commands"]["rows"][0][
        "copy_command_by_shape"
    ]
    with pytest.raises(
        GatewayInvocationError,
        match="Draft disclosure copy commands are incomplete",
    ):
        broker_module._project_model_visible_runner(  # noqa: SLF001
            tampered,
            candidate_runner=candidate_runner,
            invocation_runner=invocation_runner,
            platform_name=platform_name,
        )


@pytest.mark.parametrize("platform_name", ("posix", "nt"))
def test_broker_projects_every_business_draft_command_to_task_install(
    tmp_path: Path,
    platform_name: str,
) -> None:
    candidate_runner = tmp_path / "candidate" / "scripts" / "run.py"
    candidate_runner.parent.mkdir(parents=True)
    candidate_runner.write_text("# candidate\n", encoding="utf-8")
    invocation_runner = (
        tmp_path
        / "agent workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
        / "scripts"
        / "run.py"
    )
    candidate = str(candidate_runner.resolve(strict=True))

    def command(subcommand: str, *suffix: str) -> list[str]:
        return ["python", candidate, "gateway.py", subcommand, *suffix]

    def copy_ready_prefix(subcommand: str, *suffix: str) -> dict[str, object]:
        argv = command(subcommand, *suffix)
        return {
            "fixed_argv_prefix": argv,
            "fixed_argv_prefix_copy": (
                encode_windows_model_argv(argv)
                if platform_name == "nt"
                else shlex.join(argv)
            ),
            "fixed_argv_prefix_copy_instruction": {
                "source_field": "fixed_argv_prefix_copy",
            },
        }

    completion = command(
        "draft-check",
        "od1-0123456789abcdef0123456789abcdef",
        "--task-authority",
        "da1-0123456789abcdef0123456789abcdef01234567",
        "--expected-revision",
        "1",
    )
    binding = {
        "contract": "waapi-skill.business-draft-next-action/v1",
        "shell_tool_timeout_ms": 30_000,
        "object_binding": {
            "by_id": copy_ready_prefix("draft-bind-object", "<draft>"),
            "by_path_segments": copy_ready_prefix(
                "draft-bind-object", "<draft>"
            ),
        },
        "field_binding": {
            "class_scope": command(
                "draft-bind-field", "<draft>", "--class-name", "<class>"
            ),
            "object_scope": command(
                "draft-bind-field", "<draft>", "--object-handle", "<handle>"
            ),
        },
        "configure": {"fixed_argv_prefix": command("draft-business-configure")},
        "declare_new": {"fixed_argv_prefix": command("draft-declare-new")},
        "declare_existing": {"fixed_argv_prefix": command("draft-declare-existing")},
        "revise": {"fixed_argv_prefix": command("draft-revise-declaration")},
        "remove": {"fixed_argv_prefix": command("draft-remove-declaration")},
        "completion_candidate": {
            "fixed_full_argv": completion,
            "copy_command": (
                encode_windows_model_argv(completion)
                if platform_name == "nt"
                else shlex.join(completion)
            ),
        },
    }

    projected = broker_module._project_model_visible_runner(  # noqa: SLF001
        {
            "contract": "waapi-skill.operation-draft/v1",
            "next_action_binding": binding,
        },
        candidate_runner=candidate_runner,
        invocation_runner=invocation_runner,
        platform_name=platform_name,
    )["next_action_binding"]

    def runner_paths(value: object) -> list[str]:
        if isinstance(value, dict):
            return [path for item in value.values() for path in runner_paths(item)]
        if isinstance(value, list) and len(value) >= 3 and value[0] == "python":
            return [value[1]]
        if isinstance(value, list):
            return [path for item in value for path in runner_paths(item)]
        return []

    assert runner_paths(projected)
    assert set(runner_paths(projected)) == {str(invocation_runner)}
    projected_completion = projected["completion_candidate"]["fixed_full_argv"]
    assert projected["completion_candidate"]["copy_command"] == (
        encode_windows_model_argv(projected_completion)
        if platform_name == "nt"
        else shlex.join(projected_completion)
    )
    projected_binding = projected["object_binding"]["by_id"]
    assert projected_binding["fixed_argv_prefix_copy"] == (
        encode_windows_model_argv(projected_binding["fixed_argv_prefix"])
        if platform_name == "nt"
        else shlex.join(projected_binding["fixed_argv_prefix"])
    )

    tampered = json.loads(json.dumps(binding))
    tampered["object_binding"]["by_id"]["fixed_argv_prefix"][1] = str(
        tmp_path / "other.py"
    )
    with pytest.raises(
        GatewayInvocationError,
        match="business Draft continuation is not bound",
    ):
        broker_module._project_model_visible_runner(  # noqa: SLF001
            {
                "contract": "waapi-skill.operation-draft/v1",
                "next_action_binding": tampered,
            },
            candidate_runner=candidate_runner,
            invocation_runner=invocation_runner,
            platform_name=platform_name,
        )


FAKE_RUNNER = r'''from __future__ import annotations
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

def windows_gateway_command(argv):
    encoded_argv = [
        base64.b64encode(argument.encode("utf-8")).decode("ascii")
        for argument in argv
    ]
    argument_prefix = (
        "[System.Text.Encoding]::UTF8.GetString("
        "[System.Convert]::FromBase64String('"
    )
    inner = ",".join(argument_prefix + encoded + "'))" for encoded in encoded_argv)
    script = (
        "$ErrorActionPreference='Stop';"
        "$waapiArgv=@(" + inner + ");"
        "$waapiExecutable=$waapiArgv[0];"
        "$waapiArgs=@($waapiArgv | Select-Object -Skip 1);"
        "& $waapiExecutable @waapiArgs;"
        "exit $LASTEXITCODE"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded

def windows_model_command(argv):
    if isinstance(argv, (str, bytes)) or not argv or argv[0] != "python":
        raise ValueError("Windows model command requires the fixed python executable")
    smart_quotes = {chr(value) for value in range(0x2018, 0x2020)}
    for argument in argv:
        if type(argument) is not str:
            raise ValueError("Windows model argv items must be strings")
        if any(
            ord(character) < 32 or 0x7F <= ord(character) <= 0x9F
            for character in argument
        ):
            raise ValueError("Windows model argv contains a control character")
        if any(character in smart_quotes for character in argument):
            raise ValueError("Windows model argv contains a smart quote")
        argument.encode("utf-8", errors="strict")
    command = "python"
    if len(argv) > 1:
        command += " " + " ".join(
            "'" + argument.replace("'", "''") + "'"
            for argument in argv[1:]
        )
    if len(command.encode("utf-8", errors="strict")) > 1024:
        raise ValueError("Windows model command exceeds its byte bound")
    return command

state = Path(os.environ["WAAPI_SKILL_STATE_DIR"])
state.mkdir(parents=True, exist_ok=True)
calls = state / "fake-runner-calls.jsonl"
with calls.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")

arguments = sys.argv[1:]
assert arguments[0] == "gateway.py"
global_options_with_values = {
    "--host", "--port", "--version", "--wwise-version", "--timeout",
    "--evidence-dir", "--state-dir",
}
command_index = 1
while command_index < len(arguments):
    value = arguments[command_index]
    if any(value.startswith(option + "=") for option in global_options_with_values):
        command_index += 1
        continue
    if value in global_options_with_values:
        command_index += 2
        continue
    break
command = arguments[command_index]
command_arguments = arguments[command_index + 1:]
mode = os.environ.get("FAKE_GATEWAY_MODE", "")
if mode == "hang-ignore-term":
    import signal
    import time

    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (state / "fake-runner-pid").write_text(str(os.getpid()), encoding="utf-8")
    while True:
        time.sleep(1)
ack_path = os.environ.get("WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_PATH", "")
if ack_path and mode != "subscription-ack-missing":
    ack_writer = """
import json
import os
import time

ack_path = os.environ["WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_PATH"]
mode = os.environ.get("FAKE_GATEWAY_MODE", "")
ack_payload = {
    "contract": "waapi-skill.broker-subscription-ack/v2",
    "step_name": os.environ["WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_STEP"],
    "topic": os.environ["WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_TOPIC"],
    "nonce": os.environ["WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_NONCE"],
    "runner_parent_process_id": os.getppid(),
    "gateway_process_id": os.getpid(),
    "subscribed_at_unix_ns": time.time_ns(),
    "subscribed_at_monotonic_ns": time.monotonic_ns(),
}
if mode == "subscription-ack-wrong-topic":
    ack_payload["topic"] = "ak.wwise.core.object.created"
encoded_ack = (
    json.dumps(ack_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    + "\\n"
).encode("utf-8")
descriptor = os.open(ack_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "wb") as stream:
    stream.write(encoded_ack)
    stream.flush()
    os.fsync(stream.fileno())
if mode == "" and os.name == "nt":
    # Keep the fake writer and both venv redirector layers alive while the
    # broker takes its native process snapshot.  The real wait-topic gateway
    # naturally remains alive after publishing its ACK.
    time.sleep(1.0)
if mode == "subscription-ack-duplicate":
    os.open(ack_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
"""
    completed_ack = subprocess.run([sys.executable, "-c", ack_writer], check=False)
    if completed_ack.returncode != 0:
        raise SystemExit(completed_ack.returncode)
payload = {
    "contract": "waapi-skill.gateway-result/v1",
    "ok": True,
    "status": "ok",
    "command": command,
    "runner_python": sys.executable,
    "state_dir": os.environ.get("WAAPI_SKILL_STATE_DIR"),
    "evidence_dir": os.environ.get("WWISE_EVIDENCE_DIR"),
    "config_path": os.environ.get("WAAPI_SKILL_CONFIG_PATH"),
    "broker_token_visible": "WAAPI_CODEX_GATEWAY_BROKER_TOKEN" in os.environ,
    "bash_env_visible": "BASH_ENV" in os.environ,
    "shim_trusted_python_visible": "WAAPI_CODEX_GATEWAY_SHIM_TRUSTED_PYTHON" in os.environ,
    "gateway_required_visible": "WAAPI_CODEX_GATEWAY_REQUIRED" in os.environ,
}
if mode == "report-python-bytecode-policy":
    payload["python_dont_write_bytecode"] = os.environ.get(
        "PYTHONDONTWRITEBYTECODE"
    )
if mode.startswith("topic-stream") and command == "stream-topic":
    topic = command_arguments[0]
    records = [
        {
            "contract": "waapi-skill.topic-stream/v1",
            "command": "stream-topic",
            "record_type": "started",
            "ok": True,
            "status": "streaming",
            "topic": topic,
            "topic_contract_digest": "a" * 64,
            "match": None,
            "subscription_timeout": {
                "mode": "finite",
                "seconds": 30.0,
                "source": "explicit",
            },
            "buffer_limit_events": 64,
            "event_result_limit_bytes": 65536,
        },
        {
            "contract": "waapi-skill.topic-stream/v1",
            "record_type": "event",
            "sequence": 1,
            "topic": topic,
            "event": {"soundbank": {"name": "Weapons_Core"}},
            "event_validation": {"valid": True},
        },
        {
            "contract": "waapi-skill.topic-stream/v1",
            "command": "stream-topic",
            "record_type": "terminal",
            "ok": True,
            "status": "completed",
            "completion_reason": "duration_elapsed",
            "topic": topic,
            "topic_contract_digest": "a" * 64,
            "match": None,
            "subscription_timeout": {
                "mode": "finite",
                "seconds": 30.0,
                "source": "explicit",
            },
            "event_count": 1,
            "elapsed_seconds": 30.0,
            "cleanup": "unsubscribed",
        },
    ]
    if mode == "topic-stream-bad-sequence":
        records[1]["sequence"] = 2
    elif mode == "topic-stream-bad-cleanup":
        records[-1]["cleanup"] = "failed"
    for record in records:
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(0)
transaction_id = os.environ.get("FAKE_GATEWAY_TRANSACTION_ID", "tx-dynamic-123")
artifact_hash = "a" * 64
event_sequence = 2
last_event_hash = "b" * 64
confirmation_material = {
    "contract": "waapi-skill.confirmation-token-material/v1",
    "transaction_id": transaction_id,
    "artifact_hash": artifact_hash,
    "state": "awaiting_confirmation",
    "event_sequence": event_sequence,
    "last_event_hash": last_event_hash,
}
digest_prefix = hashlib.sha256(
    json.dumps(
        confirmation_material,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()[:30]
alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
token_value = int(digest_prefix, 16)
token_characters = ["0"] * 24
for token_index in range(23, -1, -1):
    token_characters[token_index] = alphabet[token_value & 0x1F]
    token_value >>= 5
confirmation_token = "ct1-" + "".join(token_characters)
if command == "draft-start":
    draft_marker = {
        "draft_id": "od1-11111111111111111111111111111111",
        "task_authority": "da1-2222222222222222222222222222222222222222",
        "revision": 1,
        "current_facts": [],
    }
    (state / "draft-marker.json").write_text(
        json.dumps(draft_marker),
        encoding="utf-8",
    )
    payload["task_authority"] = draft_marker["task_authority"]
    payload["draft"] = {
        "draft_id": draft_marker["draft_id"],
        "revision": draft_marker["revision"],
        "lifecycle_state": "editable",
        "binding": {"operation": command_arguments[0], "version": "2022.1"},
        "current_facts": [],
    }
    if mode == "draft-wrong-binding":
        payload["draft"]["binding"]["operation"] = "object.setRTPC"
elif command == "draft-apply":
    marker_path = state / "draft-marker.json"
    draft_marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert command_arguments[:5] == [
        draft_marker["draft_id"],
        "--task-authority",
        draft_marker["task_authority"],
        "--expected-revision",
        str(draft_marker["revision"]),
    ]
    assert command_arguments[5:7] == ["--compact", "--facts"]
    fact_argv = command_arguments[7:]
    assert fact_argv[:2] == ["--action", fact_argv[1]]
    action_name = fact_argv[1]
    draft_action = {
        "contract": "waapi-skill.operation-draft-action/v1",
        "action": action_name,
    }
    if action_name == "add_target":
        target_index = fact_argv.index("--target")
        selector_kind = fact_argv[target_index + 1]
        selector_value = fact_argv[target_index + 2]
        draft_action["selector"] = {
            "kind": "id" if selector_kind.startswith("id-") else selector_kind,
            "value": int(selector_value) if selector_kind == "id-integer" else selector_value,
        }
    elif action_name == "set_target_field":
        handle_index = fact_argv.index("--target-handle")
        field_index = fact_argv.index("--field")
        draft_action.update(
            target_handle=fact_argv[handle_index + 1],
            name=fact_argv[field_index + 1],
            value=fact_argv[field_index + 3],
        )
    if draft_action["action"] == "add_target":
        draft_marker["current_facts"] = [
            {
                "handle": "odh1-333333333333333333333333",
                "selector": draft_action["selector"],
                "properties": [],
                "references": [],
                "children": [],
                "lists": [],
                "import": None,
            }
        ]
        draft_marker["missing_fields"] = [
            "targets[odh1-333333333333333333333333].change"
        ]
        draft_marker["missing_fields_status"] = "incomplete"
        draft_marker["allowed_actions"] = [
            "set_request_option", "clear_request_option", "add_target",
            "set_property", "set_reference", "remove_reference",
            "set_target_field", "clear_target_field", "add_child",
            "set_node_field", "clear_node_field", "set_node_property",
            "remove_node_property", "remove_node", "add_list", "remove_list",
            "add_list_member", "remove_target", "inspect", "cancel",
        ]
    elif draft_action["action"] == "set_target_field":
        target_handle = draft_action["target_handle"]
        target = next(
            row
            for row in draft_marker["current_facts"]
            if row["handle"] == target_handle
        )
        target[draft_action["name"]] = draft_action["value"]
        draft_marker["missing_fields"] = []
        draft_marker["missing_fields_status"] = "complete"
        draft_marker["allowed_actions"] = [
            "set_request_option", "clear_request_option", "add_target",
            "set_property", "set_reference", "remove_reference",
            "set_target_field", "clear_target_field", "add_child",
            "set_node_field", "clear_node_field", "set_node_property",
            "remove_node_property", "remove_node", "add_list", "remove_list",
            "add_list_member", "remove_property", "remove_target", "check",
            "inspect", "cancel",
        ]
    draft_marker["revision"] += 1
    marker_path.write_text(json.dumps(draft_marker), encoding="utf-8")
    payload["draft"] = {
        "draft_id": draft_marker["draft_id"],
        "revision": draft_marker["revision"],
        "lifecycle_state": "editable",
        "binding": {"operation": "object.set", "version": "2022.1"},
        "request_options": {},
        "current_facts": draft_marker["current_facts"],
        "missing_fields": draft_marker["missing_fields"],
        "missing_fields_status": draft_marker["missing_fields_status"],
        "allowed_actions": [
            action
            for action in draft_marker["allowed_actions"]
            if action not in {"check", "inspect", "cancel", "preview-from-draft"}
        ],
        "allowed_lifecycle_commands": [
            {
                "check": "draft-check",
                "inspect": "draft-inspect",
                "cancel": "draft-cancel",
                "preview-from-draft": "preview-from-draft",
            }[action]
            for action in draft_marker["allowed_actions"]
            if action in {"check", "inspect", "cancel", "preview-from-draft"}
        ],
    }
elif command == "draft-inspect":
    draft_marker = json.loads(
        (state / "draft-marker.json").read_text(encoding="utf-8")
    )
    assert command_arguments == [
        draft_marker["draft_id"],
        "--task-authority",
        draft_marker["task_authority"],
    ]
    payload["draft"] = {
        "draft_id": draft_marker["draft_id"],
        "revision": draft_marker["revision"],
        "lifecycle_state": "editable",
        "binding": {"operation": "object.set", "version": "2022.1"},
        "current_facts": draft_marker["current_facts"],
    }
elif command == "draft-check":
    marker_path = state / "draft-marker.json"
    draft_marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert command_arguments == [
        draft_marker["draft_id"],
        "--task-authority",
        draft_marker["task_authority"],
        "--expected-revision",
        str(draft_marker["revision"]),
    ]
    draft_marker["revision"] += 1
    marker_path.write_text(json.dumps(draft_marker), encoding="utf-8")
    payload["draft"] = {
        "draft_id": draft_marker["draft_id"],
        "revision": draft_marker["revision"],
        "lifecycle_state": "editable",
        "binding": {"operation": "object.set", "version": "2022.1"},
        "current_facts": draft_marker["current_facts"],
    }
elif command == "draft-cancel":
    marker_path = state / "draft-marker.json"
    draft_marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert command_arguments == [
        draft_marker["draft_id"],
        "--task-authority",
        draft_marker["task_authority"],
        "--expected-revision",
        str(draft_marker["revision"]),
    ]
    draft_marker["revision"] += 1
    marker_path.write_text(json.dumps(draft_marker), encoding="utf-8")
    payload["draft"] = {
        "draft_id": draft_marker["draft_id"],
        "revision": draft_marker["revision"],
        "lifecycle_state": "cancelled",
        "binding": {"operation": "object.set", "version": "2022.1"},
        "current_facts": [],
    }
elif command == "preview-from-draft":
    draft_marker = json.loads(
        (state / "draft-marker.json").read_text(encoding="utf-8")
    )
    assert command_arguments[:5] == [
        draft_marker["draft_id"],
        "--task-authority",
        draft_marker["task_authority"],
        "--expected-revision",
        str(draft_marker["revision"]),
    ]
    payload.update({
        "status": "awaiting_confirmation",
        "state": "awaiting_confirmation",
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
    })
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": row["selector"],
                    **{
                        key: value
                        for key, value in row.items()
                        if key
                        in {
                            "name", "notes", "platform", "list_mode",
                            "on_name_conflict",
                        }
                    },
                    **{
                        key: row[key]
                        for key in ("properties", "references")
                        if row.get(key)
                    },
                }
                for row in draft_marker["current_facts"]
            ]
        },
    }
    payload["agent_result"] = {
        "request": request,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
    }
elif command == "preview":
    (state / "preview-marker.json").write_text(
        json.dumps(
            {
                "transaction_id": transaction_id,
                "artifact_hash": artifact_hash,
                "event_sequence": event_sequence,
                "last_event_hash": last_event_hash,
            }
        ),
        encoding="utf-8",
    )
    payload.update({
        "status": "awaiting_confirmation",
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "request": json.loads(command_arguments[1]),
    })
elif command == "confirm":
    marker = json.loads((state / "preview-marker.json").read_text(encoding="utf-8"))
    assert command_arguments == [
        marker["transaction_id"],
        "--confirmation-token",
        confirmation_token,
    ]
    payload.update({
        "status": "confirmed",
        "transaction_id": command_arguments[0],
        "artifact_hash": marker["artifact_hash"],
    })
elif command == "transaction-show":
    marker = json.loads((state / "preview-marker.json").read_text(encoding="utf-8"))
    payload.update(marker)
    payload["state"] = "awaiting_confirmation"
    payload["confirmation"] = {
        "contract": "waapi-skill.confirmation-binding/v1",
        "token": confirmation_token,
        "binding": {
            "material_contract": "waapi-skill.confirmation-token-material/v1",
            "transaction_id": marker["transaction_id"],
            "artifact_hash": marker["artifact_hash"],
            "state": "awaiting_confirmation",
            "event_sequence": marker["event_sequence"],
            "last_event_hash": marker["last_event_hash"],
        },
    }
    gateway_argv = [
        "confirm",
        marker["transaction_id"],
        "--confirmation-token",
        confirmation_token,
    ]
    full_argv = [
        "python",
        str(Path(__file__).resolve()),
        "gateway.py",
        *gateway_argv,
    ]
    next_command = {
        "contract": "waapi-skill.gateway-next-command/v2",
        "command": "confirm",
        "gateway_argv": gateway_argv,
        "full_argv": full_argv,
        "copy_exactly": True,
        "shell_tool_timeout_ms": 30000,
        "requires_explicit_user_confirmation": True,
        "shell_family": "windows-powershell-encoded" if os.name == "nt" else "posix-sh",
    }
    model_command = None
    if os.name == "nt":
        shell_command = windows_gateway_command(full_argv)
        try:
            model_command = windows_model_command(full_argv)
        except ValueError:
            model_command = None
    else:
        shell_command = shlex.join(full_argv)
    if model_command is not None:
        next_command["shell_command"] = shell_command
        next_command["model_shell_family"] = "windows-pwsh-literal-v1"
    next_command["copy_instruction"] = {
        "contract": "waapi-skill.gateway-command-copy-instruction/v2",
        "source_field": "model_command" if model_command is not None else "shell_command",
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    if model_command is not None:
        next_command["model_command"] = model_command
    else:
        next_command["shell_command"] = shell_command
    payload["next_command"] = next_command
    if mode == "confirmation-token-only":
        payload["confirmation"] = {"token": confirmation_token}
    elif mode == "confirmation-wrong-journal-head":
        payload["confirmation"]["binding"]["last_event_hash"] = "c" * 64
    elif mode == "status-show-confirmed":
        payload["status"] = "ok"
        payload["state"] = "confirmed"
        payload.pop("confirmation")
        payload.pop("next_command")
elif command == "execute":
    marker_path = state / "preview-marker.json"
    marker = (
        json.loads(marker_path.read_text(encoding="utf-8"))
        if marker_path.is_file()
        else {
            "transaction_id": command_arguments[0],
            "artifact_hash": artifact_hash,
        }
    )
    (state / "mutation-executed").write_text("yes", encoding="utf-8")
    payload.update(marker)
    if mode in {"terminal-success", "terminal-success-exit2"}:
        payload.update({
            "status": "executed_unverified",
            "state": "executed_unverified",
            "executed": True,
            "verified": False,
            "automatic_retry": False,
        })
    elif mode == "terminal-indeterminate":
        payload.update({
            "ok": False,
            "status": "indeterminate",
            "state": "indeterminate",
            "automatic_retry": False,
        })
    elif mode == "terminal-generic-error":
        payload.update({
            "ok": False,
            "status": "error",
            "error_code": "CONNECTION_FAILED",
            "automatic_retry": False,
        })
elif command == "verify":
    marker_path = state / "preview-marker.json"
    marker = (
        json.loads(marker_path.read_text(encoding="utf-8"))
        if marker_path.is_file()
        else {
            "transaction_id": command_arguments[0],
            "artifact_hash": artifact_hash,
        }
    )
    payload.update(marker)
if mode == "bad-ok":
    payload["ok"] = False
elif mode == "bad-command":
    payload["command"] = "buses"
elif mode == "bad-contract":
    payload["contract"] = "forged/v1"
elif mode == "typed-schema":
    payload["contract"] = "waapi-skill.typed-request-schema/v1"
elif mode == "topic-business" and command == "topic-schema":
    payload["contract"] = "waapi-skill.topic-business-envelope/v1"
elif mode in {"expected-error", "expected-error-exact-output"}:
    payload["ok"] = os.environ.get("FAKE_GATEWAY_ERROR_OK", "false") == "true"
    payload["error_code"] = os.environ.get(
        "FAKE_GATEWAY_ERROR_CODE",
        "PACKAGED_PREVIEW_UNAVAILABLE",
    )
    payload["command"] = os.environ.get("FAKE_GATEWAY_ERROR_COMMAND", command)
    payload["contract"] = os.environ.get(
        "FAKE_GATEWAY_ERROR_CONTRACT",
        "waapi-skill.gateway-result/v1",
    )
if mode not in {"exact-output", "expected-error-exact-output"}:
    print("fake setup log before payload")
print(
    json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=command != "preview-from-draft",
    )
)
if mode == "bad-exit":
    raise SystemExit(7)
if mode in {"expected-error", "expected-error-exact-output"}:
    raise SystemExit(int(os.environ.get("FAKE_GATEWAY_ERROR_EXIT", "2")))
if mode in {"terminal-success-exit2", "terminal-indeterminate", "terminal-generic-error"}:
    raise SystemExit(2)
'''


def make_fake_skill(tmp_path: Path) -> Path:
    skill = tmp_path / "waapi-skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text(FAKE_RUNNER, encoding="utf-8")
    return skill


def run_model_command(
    broker: CodexGatewayBroker,
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
    runner_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = environment or broker.model_environment(os.environ)
    command = [
        "python",
        str(runner_path or broker.invocation_runner_path),
        "gateway.py",
        *arguments,
    ]
    return run_model_argv(
        command,
        environment=env,
        windows_interpreter=(
            Path(env[SHIM_TRUSTED_PYTHON_ENV])
            if os.name == "nt"
            else None
        ),
        windows_command_directory=broker.shim_directory,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "discovery_arguments",
    ((), (("operations",),)),
    ids=("direct-schema", "one-operations-discovery"),
)
def test_broker_accepts_one_optional_initial_operations_discovery(
    tmp_path: Path,
    discovery_arguments: tuple[tuple[str, ...], ...],
) -> None:
    """The Skill permits one bounded catalog read before an exact schema read."""

    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep(
            "tx03.operation-schema",
            "operation-schema",
            ("waapi.undoGroup",),
        ),
    )
    observed: list[list[str]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_initial_operations_discovery_operation="waapi.undoGroup",
        transport="tcp",
    ) as broker:
        for arguments in (*discovery_arguments, ("operation-schema", "waapi.undoGroup")):
            result = run_model_command(broker, list(arguments))
            assert result.returncode == 0, result.stderr
            observed.append(
                [
                    "python",
                    str(broker.invocation_runner_path),
                    "gateway.py",
                    *arguments,
                ]
            )
        evidence = broker.evidence()
        reconciliation = broker.reconcile(observed)

    assert evidence.passed
    assert reconciliation.passed
    assert evidence.expected_step_names == (
        *(("tx03.operations",) if discovery_arguments else ()),
        "tx03.operation-schema",
    )


def test_broker_allows_optional_initial_operations_before_request_schema(
    tmp_path: Path,
) -> None:
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(
            ExpectedGatewayStep(
                "tx01.request-schema",
                "request-schema",
                ("ak.wwise.core.project.save",),
            ),
        ),
        optional_initial_operations_discovery_operation=(
            "ak.wwise.core.project.save"
        ),
        transport="tcp",
    )

    assert broker._optional_initial_operations_step == ExpectedGatewayStep(  # noqa: SLF001
        "tx01.operations",
        "operations",
    )


@pytest.mark.parametrize(
    "preflight",
    ((), (("query-object", "--path-segment", "Weather"),)),
    ids=("direct-schema", "one-exact-root-preflight"),
)
def test_broker_accepts_one_optional_exact_root_preflight(
    tmp_path: Path,
    preflight: tuple[tuple[str, ...], ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep(
            "tx01.operation-schema",
            "operation-schema",
            ("object.create",),
        ),
    )
    observed: list[list[str]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_initial_query_object_arguments=(
            "--path-segment",
            "Weather",
        ),
        transport="tcp",
    ) as broker:
        for arguments in (*preflight, ("operation-schema", "object.create")):
            result = run_model_command(broker, list(arguments))
            assert result.returncode == 0, result.stderr
            observed.append(
                [
                    "python",
                    str(broker.invocation_runner_path),
                    "gateway.py",
                    *arguments,
                ]
            )
        evidence = broker.evidence()
        reconciliation = broker.reconcile(observed)

    assert evidence.passed
    assert reconciliation.passed
    assert evidence.expected_step_names == (
        *(("tx01.query-object-preflight",) if preflight else ()),
        "tx01.operation-schema",
    )


def test_broker_accepts_exact_root_preflight_after_required_operations(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("tx01.operations", "operations"),
        ExpectedGatewayStep(
            "tx01.operation-schema",
            "operation-schema",
            ("object.create",),
        ),
    )
    commands = (
        ("operations",),
        ("query-object", "--path-segment", "Weather"),
        ("operation-schema", "object.create"),
    )
    observed: list[list[str]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_initial_query_object_arguments=("--path-segment", "Weather"),
        transport="tcp",
    ) as broker:
        for arguments in commands:
            result = run_model_command(broker, list(arguments))
            assert result.returncode == 0, result.stderr
            observed.append(
                ["python", str(broker.invocation_runner_path), "gateway.py", *arguments]
            )
        evidence = broker.evidence()
        reconciliation = broker.reconcile(observed)

    assert evidence.passed
    assert reconciliation.passed
    assert evidence.expected_step_names == (
        "tx01.operations",
        "tx01.query-object-preflight",
        "tx01.operation-schema",
    )


@pytest.mark.parametrize(
    "commands",
    (
        (("operation-schema", "waapi.undoGroup"),),
        (("operations",), ("operation-schema", "waapi.undoGroup")),
    ),
    ids=("direct-schema", "catalog-then-schema"),
)
def test_broker_can_skip_one_expected_leading_operations_step(
    tmp_path: Path,
    commands: tuple[tuple[str, ...], ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("tx03.operations", "operations"),
        ExpectedGatewayStep(
            "tx03.operation-schema",
            "operation-schema",
            ("waapi.undoGroup",),
        ),
    )
    observed: list[list[str]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_expected_initial_operations_discovery=True,
        transport="tcp",
    ) as broker:
        for arguments in commands:
            result = run_model_command(broker, list(arguments))
            assert result.returncode == 0, result.stderr
            observed.append(
                [
                    "python",
                    str(broker.invocation_runner_path),
                    "gateway.py",
                    *arguments,
                ]
            )
        evidence = broker.evidence()
        reconciliation = broker.reconcile(observed)

    assert evidence.passed
    assert reconciliation.passed
    assert evidence.expected_step_names == tuple(
        step.name for step in (steps if len(commands) == 2 else steps[1:])
    )


def test_broker_accepts_selected_workflow_operations_discovery_steps(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("routing.operations", "operations"),
        ExpectedGatewayStep("diag.query", "query-object", ("--exact-id", "one")),
        ExpectedGatewayStep(
            "routing.operations.tx01.operation-schema",
            "operations",
        ),
        ExpectedGatewayStep(
            "tx01.operation-schema",
            "operation-schema",
            ("object.setReference",),
        ),
        ExpectedGatewayStep("tx01.verify", "verify", ("tx-one",)),
        ExpectedGatewayStep(
            "routing.operations.tx02.operation-schema",
            "operations",
        ),
        ExpectedGatewayStep(
            "tx02.operation-schema",
            "operation-schema",
            ("switchContainer.removeAssignment",),
        ),
    )
    selected_operations = {
        "routing.operations.tx01.operation-schema",
        "routing.operations.tx02.operation-schema",
    }
    commands = (
        ("query-object", "--exact-id", "one"),
        ("operations",),
        ("operation-schema", "object.setReference"),
        ("verify", "tx-one"),
        ("operations",),
        ("operation-schema", "switchContainer.removeAssignment"),
    )
    observed: list[list[str]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_expected_operations_discovery_step_names=tuple(
            step.name for step in steps if step.name.startswith("routing.operations")
        ),
        transport="tcp",
    ) as broker:
        for arguments in commands:
            result = run_model_command(broker, list(arguments))
            assert result.returncode == 0, result.stderr
            observed.append(
                ["python", str(broker.invocation_runner_path), "gateway.py", *arguments]
            )
        evidence = broker.evidence()
        reconciliation = broker.reconcile(observed)

    assert evidence.passed
    assert reconciliation.passed
    assert set(evidence.expected_step_names) & {
        step.name for step in steps if step.name.startswith("routing.operations")
    } == selected_operations


@pytest.mark.parametrize(
    "commands",
    (
        (("operations",), ("operations",)),
        (("operation-schema", "waapi.undoGroup"), ("operations",)),
        (("operation-schema", "waapi.notUndoGroup"),),
    ),
    ids=("repeated-discovery", "discovery-after-schema", "wrong-operation"),
)
def test_broker_optional_initial_operations_discovery_stays_fail_closed(
    tmp_path: Path,
    commands: tuple[tuple[str, ...], ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep(
            "tx03.operation-schema",
            "operation-schema",
            ("waapi.undoGroup",),
        ),
        ExpectedGatewayStep("tx03.next", "capabilities"),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_initial_operations_discovery_operation="waapi.undoGroup",
        transport="tcp",
    ) as broker:
        results = [run_model_command(broker, list(arguments)) for arguments in commands]

    assert results[-1].returncode == 126
    assert broker.evidence().terminal_state == "FAILED"


def test_broker_optional_initial_operations_discovery_binds_one_exact_operation(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    with pytest.raises(ValueError, match="bind the exact first schema"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(
                ExpectedGatewayStep(
                    "tx03.operation-schema",
                    "operation-schema",
                    ("object.setName",),
                ),
            ),
            optional_initial_operations_discovery_operation="waapi.undoGroup",
            transport="tcp",
        )


@pytest.mark.parametrize(
    "disclosures",
    (
        (),
        (("topic-schema", "ak.test.topic", "--match-group", "soundbank"),),
        (
            ("topic-schema", "ak.test.topic", "--match-group", "soundbank"),
            ("topic-schema", "ak.test.topic", "--entry", "soundbank"),
            ("topic-schema", "ak.test.topic", "--entry", "platform"),
        ),
    ),
    ids=("none", "one", "all"),
)
def test_broker_accepts_only_selected_optional_topic_disclosures(
    tmp_path: Path,
    disclosures: tuple[tuple[str, ...], ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.test.topic"
    steps = (
        ExpectedGatewayStep("schema", "topic-schema", (topic,)),
        ExpectedGatewayStep(
            "soundbank-match",
            "topic-schema",
            (topic, "--match-group", "soundbank"),
        ),
        ExpectedGatewayStep(
            "soundbank-entry",
            "topic-schema",
            (topic, "--entry", "soundbank"),
        ),
        ExpectedGatewayStep(
            "platform-entry",
            "topic-schema",
            (topic, "--entry", "platform"),
        ),
        ExpectedGatewayStep("wait", "wait-topic", (topic,)),
    )
    commands = (
        ("topic-schema", topic),
        *disclosures,
        ("wait-topic", topic),
    )
    observed: list[list[str]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_topic_schema_step_groups=(
            ("soundbank-match", "soundbank-entry", "platform-entry"),
        ),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "topic-business"},
        transport="tcp",
    ) as broker:
        for command in commands:
            result = run_model_command(broker, list(command))
            assert result.returncode == 0, result.stderr
            observed.append(
                [
                    "python",
                    str(broker.invocation_runner_path),
                    "gateway.py",
                    *command,
                ]
            )
        evidence = broker.evidence()
        reconciliation = broker.reconcile(observed)

    selected = {
        ("--match-group", "soundbank"): "soundbank-match",
        ("--entry", "soundbank"): "soundbank-entry",
        ("--entry", "platform"): "platform-entry",
    }
    assert evidence.expected_step_names == (
        "schema",
        *(selected[command[-2:]] for command in disclosures),
        "wait",
    )
    assert evidence.passed is True
    assert reconciliation.passed is True


def test_broker_rejects_unsealed_optional_topic_disclosure(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.test.topic"
    steps = (
        ExpectedGatewayStep("schema", "topic-schema", (topic,)),
        ExpectedGatewayStep(
            "platform-entry",
            "topic-schema",
            (topic, "--entry", "platform"),
        ),
        ExpectedGatewayStep("wait", "wait-topic", (topic,)),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_topic_schema_step_groups=(("platform-entry",),),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "topic-business"},
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["topic-schema", topic]).returncode == 0
        result = run_model_command(
            broker,
            ["topic-schema", topic, "--entry", "language"],
        )

    assert result.returncode == 126
    assert broker.evidence().terminal_state == "FAILED"


def test_compound_parent_revision_binding_ignores_later_child_draft_receipts(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    object_id = "{11111111-2222-3333-4444-555555555555}"
    children = tuple(
        CompoundUndoChildExpectation(
            request={
                "contract": "waapi-skill.operation-request/v1",
                "version": "2022.1",
                "operation": operation,
                "arguments": {
                    "object": {"kind": "id", "value": object_id},
                    "value": value,
                },
            },
            selector={"kind": "id", "value": object_id},
        )
        for operation, value in (
            ("object.setNotes", "Exterior rain loop"),
            ("object.setName", "Rain_Exterior"),
        )
    )
    steps = build_compound_undo_business_transaction_steps(
        children,
        display_name="Weather rain cleanup",
        label="tx03",
    )
    declaration_index = next(
        index
        for index, step in enumerate(steps)
        if step.name == "tx03.declare-undo-plan"
    )
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    )
    broker._next_step = declaration_index  # noqa: SLF001
    parent_draft = "od1-" + "a" * 32
    child_one = "od1-" + "b" * 32
    child_two = "od1-" + "c" * 32
    broker._payloads_by_step.update(  # noqa: SLF001
        {
            "tx03.draft-start": {
                "draft": {"draft_id": parent_draft, "revision": 1},
                "task_authority": "parent-authority",
            },
            "tx01.draft-start": {
                "draft": {"draft_id": child_one, "revision": 1},
                "task_authority": "child-one-authority",
            },
            "tx02.draft-start": {
                "draft": {"draft_id": child_two, "revision": 1},
                "task_authority": "child-two-authority",
            },
            "tx02.check": {"draft": {"draft_id": child_two, "revision": 4}},
        }
    )
    correct = (
        "draft-declare-undo-plan",
        parent_draft,
        "--task-authority",
        "parent-authority",
        "--expected-revision",
        "1",
        "--display-name",
        "Weather rain cleanup",
        "--child-draft",
        child_one,
        "child-one-authority",
        "--child-draft",
        child_two,
        "child-two-authority",
    )

    broker._validate_step(steps[declaration_index], correct)  # noqa: SLF001
    broker._validate_operation_draft_payload(  # noqa: SLF001
        steps[declaration_index],
        {
            "draft": {
                "draft_id": parent_draft,
                "revision": 2,
                "lifecycle_state": "editable",
                "binding": {
                    "operation": "waapi.undoGroup",
                    "version": "2022.1",
                },
            }
        },
    )
    with pytest.raises(GatewayInvocationError, match="tx03.draft-start/draft/revision"):
        broker._validate_step(  # noqa: SLF001
            steps[declaration_index],
            (*correct[:5], "4", *correct[6:]),
        )
    with pytest.raises(GatewayInvocationError, match="ID does not match draft-start"):
        broker._validate_operation_draft_payload(  # noqa: SLF001
            steps[declaration_index],
            {
                "draft": {
                    "draft_id": child_two,
                    "revision": 2,
                    "lifecycle_state": "editable",
                    "binding": {
                        "operation": "waapi.undoGroup",
                        "version": "2022.1",
                    },
                }
            },
        )


def native_pwsh_73_or_skip() -> str:
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")
    version_probe = subprocess.run(
        [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert version_probe.returncode == 0, version_probe.stderr
    version_parts = version_probe.stdout.strip().split(".")
    if len(version_parts) < 2 or tuple(map(int, version_parts[:2])) < (7, 3):
        pytest.skip("PowerShell 7.3 or newer is required")
    return pwsh


@pytest.mark.parametrize(
    "transport",
    ["tcp", pytest.param("unix", marks=pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX"))],
)
def test_broker_executes_exact_order_with_semantic_json_and_response_bindings(
    tmp_path: Path,
    transport: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    invocation = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    invocation_runner = invocation / "scripts" / "run.py"
    invocation_runner.parent.mkdir(parents=True)
    invocation_runner.write_text(
        'raise RuntimeError("model-facing Skill copy must never execute")\n',
        encoding="utf-8",
    )
    request = {
        "operation": "ak.wwise.core.object.setNotes",
        "target": {"path": r"\Actor-Mixer Hierarchy\Default Work Unit\Sound"},
        "value": "broker test",
    }
    steps = (
        ExpectedGatewayStep("schema", "operation-schema", ("ak.wwise.core.object.setNotes",)),
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("show", "/transaction_id"),
                "--confirmation-token",
                ResponseBinding("show", "/confirmation/token"),
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        invocation_skill_source=invocation,
        expected_steps=steps,
        transport=transport,
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "BROKER_TEST": "1",
            "WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "caller-controlled-config.json"),
        },
    ) as broker:
        observed = [
            ["python", str(broker.invocation_runner_path), "gateway.py", "operation-schema", "ak.wwise.core.object.setNotes"],
            [
                "python",
                str(broker.invocation_runner_path),
                "gateway.py",
                "preview",
                "--request-json",
                json.dumps(request, ensure_ascii=False, sort_keys=False, indent=1),
            ],
            [
                "python",
                str(broker.invocation_runner_path),
                "gateway.py",
                "transaction-show",
                "tx-dynamic-123",
                "--summary-only",
            ],
            [
                "python",
                str(broker.invocation_runner_path),
                "gateway.py",
                "confirm",
                "tx-dynamic-123",
                "--confirmation-token",
                fake_confirmation_token("tx-dynamic-123"),
            ],
        ]
        results = [run_model_command(broker, command[3:]) for command in observed]

        assert [result.returncode for result in results] == [0, 0, 0, 0]
        preview = json.loads(results[1].stdout[results[1].stdout.index("{") :])
        shown = json.loads(results[2].stdout[results[2].stdout.index("{") :])
        shown_document = results[2].stdout[results[2].stdout.index("{") :].strip()
        assert shown_document == json.dumps(
            shown,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        confirm_output = results[3].stdout
        assert confirm_output
        confirm = json.loads(confirm_output[confirm_output.index("{") :])
        assert confirm["command"] == "confirm"
        assert confirm["status"] == "confirmed"
        assert confirm["transaction_id"] == "tx-dynamic-123"
        assert confirm["artifact_hash"] == FAKE_ARTIFACT_HASH
        assert shown["confirmation"] == {
            "contract": "waapi-skill.confirmation-binding/v1",
            "token": fake_confirmation_token("tx-dynamic-123"),
            "binding": {
                "material_contract": "waapi-skill.confirmation-token-material/v1",
                "transaction_id": "tx-dynamic-123",
                "artifact_hash": FAKE_ARTIFACT_HASH,
                "state": "awaiting_confirmation",
                "event_sequence": FAKE_EVENT_SEQUENCE,
                "last_event_hash": FAKE_LAST_EVENT_HASH,
            },
        }
        assert shown["next_command"] == expected_fake_confirmation_next_command(
            invocation_runner,
            "tx-dynamic-123",
        )
        assert results[3].stderr == ""
        assert preview["request"] == request
        assert preview["broker_token_visible"] is False
        assert preview["bash_env_visible"] is False
        assert preview["state_dir"] == str(broker.state_directory)
        assert preview["evidence_dir"] == str(broker.evidence_directory)
        assert preview["config_path"] == str(broker.config_path)
        assert preview["shim_trusted_python_visible"] is False
        assert broker.config_path.is_file()

        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.complete is True
        assert evidence.consumed_step_names == ("schema", "preview", "show", "confirm")
        assert len(evidence.records) == 4
        assert all(record.accepted and record.succeeded for record in evidence.records)
        assert all(record.argv_sha256 and record.payload_sha256 for record in evidence.records)
        assert all(record.runner_command_sha256 for record in evidence.records)
        assert all(record.duration_seconds >= 0 for record in evidence.records)
        assert evidence.records[1].payload == preview
        assert evidence.records[2].payload == shown
        assert evidence.records[3].payload == confirm
        assert evidence.records[3].stdout == confirm_output
        assert broker.reconcile(observed).passed is True

        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(calls) == 4


@pytest.mark.parametrize("use_exact_literal", (False, True))
def test_broker_accepts_bound_or_sealed_exact_argument_without_a_third_form(
    tmp_path: Path,
    use_exact_literal: bool,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "test.seed"}
    sealed_path = r"\Events\Default Work Unit\Alarm\Play"
    steps = (
        ExpectedGatewayStep(
            "seed",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "children",
            "query-object",
            (
                ExactArgumentAlternatives(("--object-id", "--path")),
                ResponseBindingOrExactArgument(
                    binding=ResponseBinding("seed", "/transaction_id"),
                    exact_values=(sealed_path,),
                ),
                "--select",
                "children",
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        seeded = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(request)],
        )
        assert seeded.returncode == 0
        selected = sealed_path if use_exact_literal else "tx-dynamic-123"
        selected_flag = "--path" if use_exact_literal else "--object-id"
        accepted = run_model_command(
            broker,
            ["query-object", selected_flag, selected, "--select", "children"],
        )
        assert accepted.returncode == 0
        assert broker.evidence().passed is True


def test_broker_rejects_unsealed_third_argument_form_for_bound_or_exact_value(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "test.seed"}
    steps = (
        ExpectedGatewayStep(
            "seed",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "children",
            "query-object",
            (
                ExactArgumentAlternatives(("--object-id", "--path")),
                ResponseBindingOrExactArgument(
                    binding=ResponseBinding("seed", "/transaction_id"),
                    exact_values=(r"\Events\Default Work Unit\Alarm\Play",),
                ),
                "--select",
                "children",
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        assert run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(request)],
        ).returncode == 0
        rejected = run_model_command(
            broker,
            [
                "query-object",
                "--object-id",
                r"\Events\Default Work Unit\Alarm\Decoy",
                "--select",
                "children",
            ],
        )
        assert rejected.returncode == 126
        assert broker.evidence().passed is False


def _archive_test_broker_executes_typed_draft_actions_with_gateway_response_bindings(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    hostile_notes = '雪 Field "A" \\ path; $(leave-as-data) & done'
    action_contract = "waapi-skill.operation-draft-action/v1"
    steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "draft.target",
            "draft-apply",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.start", "/draft/revision"),
                "--compact",
                "--facts",
                DraftTypedActionArgument(
                    {
                        "contract": action_contract,
                        "action": "add_target",
                        "selector": {
                            "kind": "id",
                            "value": "{11111111-1111-1111-1111-111111111111}",
                        },
                    }
                ),
            ),
        ),
        ExpectedGatewayStep(
            "draft.notes",
            "draft-apply",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.target", "/draft/revision"),
                "--compact",
                "--facts",
                DraftTypedActionArgument(
                    {
                        "contract": action_contract,
                        "action": "set_target_field",
                        "name": "notes",
                        "value": hostile_notes,
                    },
                    response_bindings=(
                        DraftActionResponseBinding(
                            "/target_handle",
                            "draft.target",
                            "/draft/current_facts/0/handle",
                        ),
                    ),
                ),
            ),
        ),
        ExpectedGatewayStep(
            "draft.check",
            "draft-check",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.notes", "/draft/revision"),
            ),
        ),
        ExpectedGatewayStep(
            "draft.preview",
            "preview-from-draft",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.check", "/draft/revision"),
                "--apply",
                "--ttl",
                "300",
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        started_result = run_model_command(broker, ["draft-start", "object.set"])
        started = json.loads(started_result.stdout[started_result.stdout.index("{") :])
        draft_id = started["draft"]["draft_id"]
        authority = started["task_authority"]

        target_result = run_model_command(
            broker,
            [
                "draft-apply",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                "1",
                "--compact",
                "--facts",
                *typed_action_cli_arguments(steps[1].arguments[-1].expected),
            ],
        )
        assert target_result.returncode == 0, target_result.stderr
        targeted = json.loads(target_result.stdout[target_result.stdout.index("{") :])
        handle = targeted["draft"]["current_facts"][0]["handle"]
        notes_action = {
            **steps[2].arguments[-1].expected,
            "target_handle": handle,
        }
        notes_result = run_model_command(
            broker,
            [
                "draft-apply",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                "2",
                "--compact",
                "--facts",
                *typed_action_cli_arguments(notes_action),
            ],
        )
        assert notes_result.returncode == 0, notes_result.stderr
        check_result = run_model_command(
            broker,
            [
                "draft-check",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                "3",
            ],
        )
        preview_result = run_model_command(
            broker,
            [
                "preview-from-draft",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                "4",
                "--apply",
                "--ttl",
                "300",
            ],
        )

        assert [
            result.returncode
            for result in (
                started_result,
                target_result,
                notes_result,
                check_result,
                preview_result,
            )
            ] == [0, 0, 0, 0, 0], preview_result.stderr
        assert broker.evidence().complete is True
        assert broker.evidence().consumed_step_names == tuple(step.name for step in steps)
        assert not (broker.state_directory / "mutation-executed").exists()

        preview_payload = json.loads(
            preview_result.stdout[preview_result.stdout.index("{") :]
        )
        drifted_preview = json.loads(json.dumps(preview_payload))
        drifted_preview["agent_result"]["request"]["arguments"]["objects"][0][
            "notes"
        ] = "different"
        with pytest.raises(
            GatewayInvocationError,
            match="does not replay from the reviewed typed actions",
        ):
            broker._validate_operation_draft_payload(  # noqa: SLF001
                steps[-1],
                drifted_preview,
            )


def _archive_test_broker_executes_one_atomic_generic_typed_draft_batch(
    tmp_path: Path,
) -> None:
    skill = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.create",
        "arguments": {
            "parent": {"kind": "path", "value": r"\Root"},
            "name": "BatchChild",
            "type": "Sound",
        },
    }
    protocol = build_transaction_protocol((request,))
    final_action_index = max(
        index
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "draft-apply"
    )
    steps = protocol.steps[: final_action_index + 1]
    batches = tuple(
        step.arguments[-1]
        for step in steps
        if step.subcommand == "draft-apply"
    )
    assert len(batches) == 1
    assert isinstance(batches[0], DraftTypedActionBatchArgument)

    payloads: dict[str, Mapping[str, object]] = {}

    def pointer(payload: object, value: str) -> object:
        current = payload
        for token in value.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=protocol.steps,
        expected_wwise_version="2022.1",
        transport="tcp",
        working_root=tmp_path / "broker-root",
    ) as broker:
        for step in steps:
            argv: list[str] = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                elif isinstance(argument, DraftTypedActionBatchArgument):
                    for action_argument in argument.actions:
                        action = dict(action_argument.expected)
                        for binding in action_argument.response_bindings:
                            action[binding.pointer.removeprefix("/")] = pointer(
                                payloads[binding.step],
                                binding.response_pointer,
                            )
                        argv.extend(typed_action_cli_arguments(action))
                elif isinstance(argument, DraftTypedActionArgument):
                    argv.extend(typed_action_cli_arguments(argument.expected))
                else:
                    assert isinstance(argument, str)
                    argv.append(argument)
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(
                result.stdout[result.stdout.index("{") :]
            )
        preview = next(
            step
            for step in protocol.steps
            if step.subcommand == "preview-from-draft"
        )
        assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
            preview
        ) == request

    action_payload = payloads[steps[-1].name]
    draft = action_payload["draft"]
    assert isinstance(draft, Mapping)
    assert draft["revision"] == 1 + len(batches[0].actions)
    assert draft["action_result"] == {
        **draft["action_result"],
        "action": "batch",
        "action_count": len(batches[0].actions),
        "applied_atomically": True,
    }


# Archived with the retired generic Lua Composer ingress.  The remaining
# Composer operations do not expose one public, handle-free multi-batch shape;
# keeping Lua draft-apply callable only for this harness test would violate the
# exact-artifact Business Adapter boundary.
@pytest.mark.parametrize(
    "first_indexes,second_indexes",
    (
        ((0, 1, 2, 3, 4, 5), (6, 7, 8, 9, 10)),
        ((0, 1, 2, 3, 4), (5, 6, 7, 8, 9, 10)),
    ),
)
def _archive_test_broker_accepts_dependency_free_draft_facts_rebatched_across_adjacent_steps(
    tmp_path: Path,
    first_indexes: tuple[int, ...],
    second_indexes: tuple[int, ...],
) -> None:
    skill = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    io_root = tmp_path / "owned"
    io_root.mkdir()
    protocol = _dependency_free_rebatch_protocol(str(io_root))
    action_steps = tuple(
        step for step in protocol.steps if step.subcommand == "draft-apply"
    )
    assert len(action_steps) >= 2
    first, second = action_steps[:2]
    assert protocol.steps.index(second) == protocol.steps.index(first) + 1
    original_actions = tuple(
        action
        for step in (first, second)
        for action in (
            step.arguments[-1].actions
            if isinstance(step.arguments[-1], DraftTypedActionBatchArgument)
            else (step.arguments[-1],)
        )
    )
    assert len(original_actions) == 11
    assert not any(action.response_bindings for action in original_actions)

    payloads: dict[str, Mapping[str, object]] = {}

    def pointer(payload: object, value: str) -> object:
        current = payload
        for token in value.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    def fixed_argv(step: ExpectedGatewayStep) -> list[str]:
        argv = [step.subcommand]
        for argument in step.arguments[:-1]:
            if isinstance(argument, ResponseBinding):
                argv.append(str(pointer(payloads[argument.step], argument.pointer)))
            else:
                assert isinstance(argument, str)
                argv.append(argument)
        return argv

    first_index = protocol.steps.index(first)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=protocol.steps,
        expected_wwise_version="2025.1",
        transport="tcp",
        working_root=tmp_path / "broker-root",
    ) as broker:
        for step in protocol.steps[:first_index]:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                else:
                    assert isinstance(argument, str)
                    argv.append(argument)
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{") :])

        for step, indexes in ((first, first_indexes), (second, second_indexes)):
            argv = fixed_argv(step)
            for index in indexes:
                argv.extend(typed_action_cli_arguments(original_actions[index].expected))
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{") :])

        assert broker.evidence().consumed_step_names[-2:] == (
            first.name,
            second.name,
        )


@pytest.mark.parametrize(
    "submitted_indexes",
    (
        (0, 1, 2, 3, 4, 4),
        (0, 1, 2, 3, 4, 6),
    ),
)
def _archive_test_broker_rejects_unsafe_fact_order_while_rebatching_adjacent_steps(
    tmp_path: Path,
    submitted_indexes: tuple[int, ...],
) -> None:
    skill = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    io_root = tmp_path / "owned"
    io_root.mkdir()
    protocol = _dependency_free_rebatch_protocol(str(io_root))
    action_steps = tuple(
        step for step in protocol.steps if step.subcommand == "draft-apply"
    )
    first, second = action_steps[:2]
    assert protocol.steps.index(second) == protocol.steps.index(first) + 1
    original_actions = tuple(
        action
        for step in (first, second)
        for action in (
            step.arguments[-1].actions
            if isinstance(step.arguments[-1], DraftTypedActionBatchArgument)
            else (step.arguments[-1],)
        )
    )
    assert original_actions[0].expected.get("fact_action") == "set"
    payloads: dict[str, Mapping[str, object]] = {}

    def pointer(payload: object, value: str) -> object:
        current = payload
        for token in value.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    first_index = protocol.steps.index(first)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=protocol.steps,
        expected_wwise_version="2025.1",
        transport="tcp",
        working_root=tmp_path / "broker-root",
    ) as broker:
        for step in protocol.steps[:first_index]:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                else:
                    assert isinstance(argument, str)
                    argv.append(argument)
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{") :])

        argv = [first.subcommand]
        for argument in first.arguments[:-1]:
            if isinstance(argument, ResponseBinding):
                argv.append(str(pointer(payloads[argument.step], argument.pointer)))
            else:
                assert isinstance(argument, str)
                argv.append(argument)
        for index in submitted_indexes:
            argv.extend(typed_action_cli_arguments(original_actions[index].expected))
        result = run_model_command(broker, argv)

        assert result.returncode == 126
        assert "typed Draft" in result.stderr
        assert broker.evidence().terminal_state == "FAILED"


def _archive_test_rebatched_dependency_free_draft_replays_the_exact_canonical_request(
    tmp_path: Path,
) -> None:
    skill = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.create",
        "arguments": {
            "parent": {"kind": "path", "value": r"\Root"},
            "name": "RebatchedChild",
            "type": "Sound",
            "on_name_conflict": "fail",
            "notes": "sealed-note",
        },
    }
    protocol = build_transaction_protocol((request,))
    action_steps = tuple(
        step for step in protocol.steps if step.subcommand == "draft-apply"
    )
    assert len(action_steps) == 2
    first, second = action_steps
    assert protocol.steps.index(second) == protocol.steps.index(first) + 1
    original_actions = tuple(
        action
        for step in action_steps
        for action in (
            step.arguments[-1].actions
            if isinstance(step.arguments[-1], DraftTypedActionBatchArgument)
            else (step.arguments[-1],)
        )
    )
    assert len(original_actions) == 7
    payloads: dict[str, Mapping[str, object]] = {}

    def pointer(payload: object, value: str) -> object:
        current = payload
        for token in value.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    first_index = protocol.steps.index(first)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=protocol.steps,
        expected_wwise_version="2022.1",
        transport="tcp",
        working_root=tmp_path / "broker-root",
    ) as broker:
        for step in protocol.steps[:first_index]:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                else:
                    assert isinstance(argument, str)
                    argv.append(argument)
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{") :])

        for step, indexes in ((first, (0, 1, 2, 3)), (second, (4, 5, 6))):
            argv = [step.subcommand]
            for argument in step.arguments[:-1]:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                else:
                    assert isinstance(argument, str)
                    argv.append(argument)
            for index in indexes:
                argv.extend(typed_action_cli_arguments(original_actions[index].expected))
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{") :])

        preview = next(
            step for step in protocol.steps if step.subcommand == "preview-from-draft"
        )
        assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
            preview
        ) == request


def test_soundbank_business_plan_witness_replays_the_exact_canonical_request(
    tmp_path: Path,
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "soundbank.setInclusions",
        "arguments": {
            "soundbank": {"kind": "path", "value": r"\SoundBanks\Harbor"},
            "mode": "replace",
            "inclusions": [
                {
                    "object": {
                        "kind": "path",
                        "value": r"\Events\Harbor\Play_Waves",
                    },
                    "filters": ["events", "structures", "media"],
                }
            ],
        },
    }
    protocol = build_transaction_protocol((request,))
    assert all(step.subcommand != "draft-apply" for step in protocol.steps)
    assert any(
        step.subcommand == "draft-declare-soundbank-plan"
        for step in protocol.steps
    )
    preview = next(
        step for step in protocol.steps if step.subcommand == "preview-from-draft"
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "detached-skill-witness",
        expected_steps=protocol.steps,
        expected_wwise_version="2025.1",
    )

    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == request


def test_soundbank_generation_plan_accepts_independent_flag_groups_in_any_order(
    tmp_path: Path,
) -> None:
    fixed = (
        "od1-draft",
        "--task-authority",
        "da1-" + "1" * 40,
        "--expected-revision",
        "3",
    )
    expected = (
        *fixed,
        "--soundbank",
        "boh1-main",
        "nonlocalized",
        "--soundbank-rebuild",
        "boh1-main",
        "false",
        "--soundbank",
        "boh1-gameplay",
        "nonlocalized",
        "--soundbank-rebuild",
        "boh1-gameplay",
        "false",
        "--platform",
        "Windows",
        "--rebuild-soundbanks",
        "false",
        "--clear-audio-file-cache",
        "false",
        "--rebuild-init-bank",
        "false",
        "--io-root",
        r"C:\owned",
    )
    supplied = (
        *fixed,
        "--clear-audio-file-cache",
        "false",
        "--io-root",
        r"C:\owned",
        "--rebuild-init-bank",
        "false",
        "--rebuild-soundbanks",
        "false",
        "--platform",
        "Windows",
        "--soundbank",
        "boh1-main",
        "nonlocalized",
        "--soundbank-rebuild",
        "boh1-main",
        "false",
        "--soundbank",
        "boh1-gameplay",
        "nonlocalized",
        "--soundbank-rebuild",
        "boh1-gameplay",
        "false",
    )
    step = ExpectedGatewayStep(
        "declare",
        "draft-declare-soundbank-plan",
        expected,
    )
    broker = object.__new__(CodexGatewayBroker)
    broker._payloads_by_step = {}  # noqa: SLF001

    assert broker._normalize_soundbank_plan_fact_order(  # noqa: SLF001
        step,
        supplied,
    ) == expected


def test_soundbank_generation_plan_preserves_repeated_source_row_order() -> None:
    fixed = (
        "od1-draft",
        "--task-authority",
        "da1-" + "1" * 40,
        "--expected-revision",
        "3",
    )
    expected = (
        *fixed,
        "--source",
        "a.json",
        "Main",
        "nonlocalized",
        "--source",
        "b.json",
        "Gameplay",
        "nonlocalized",
        "--platform",
        "Windows",
    )
    supplied = (
        *fixed,
        "--platform",
        "Windows",
        "--source",
        "b.json",
        "Gameplay",
        "nonlocalized",
        "--source",
        "a.json",
        "Main",
        "nonlocalized",
    )
    step = ExpectedGatewayStep(
        "declare",
        "draft-declare-soundbank-plan",
        expected,
    )
    broker = object.__new__(CodexGatewayBroker)
    broker._payloads_by_step = {}  # noqa: SLF001

    assert broker._normalize_soundbank_plan_fact_order(  # noqa: SLF001
        step,
        supplied,
    ) == supplied


def test_soundbank_exact_type_name_witness_normalizes_to_bound_guid() -> None:
    expected = {
        "kind": "exact-type-name",
        "type": "SoundBank",
        "name": "Harbor_Release",
    }

    assert broker_module._normalize_bound_business_reference_paths(  # noqa: SLF001
        expected,
        path_to_id={},
        type_name_to_id={
            ("SoundBank", "Harbor_Release"): (
                "{00000000-0000-0000-0000-000000000001}"
            )
        },
    ) == {
        "kind": "id",
        "value": "{00000000-0000-0000-0000-000000000001}",
    }


def _archive_test_object_set_protocol_batches_independent_targets_through_public_gateway(
    tmp_path: Path,
) -> None:
    skill = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "path", "value": rf"\Root\Target{index}"},
                    "notes": f"note-{index}",
                }
                for index in range(3)
            ]
        },
    }
    protocol = build_transaction_protocol((request,))
    action_steps = tuple(
        step for step in protocol.steps if step.subcommand == "draft-apply"
    )
    assert len(action_steps) == 1
    batch = action_steps[0].arguments[-1]
    assert isinstance(batch, DraftTypedActionBatchArgument)
    assert [action.expected["action"] for action in batch.actions] == [
        "add_target",
        "add_target",
        "add_target",
    ]
    assert broker_module.dependency_free_draft_action_block(
        protocol.steps,
        protocol.steps.index(action_steps[0]),
    ) is None

    payloads: dict[str, Mapping[str, object]] = {}

    def pointer(payload: object, value: str) -> object:
        current = payload
        for token in value.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    last_action_index = protocol.steps.index(action_steps[0])
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=protocol.steps,
        expected_wwise_version="2022.1",
        transport="tcp",
        working_root=tmp_path / "broker-root",
    ) as broker:
        for step in protocol.steps[: last_action_index + 1]:
            argv: list[str] = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                elif isinstance(argument, DraftTypedActionBatchArgument):
                    for action_argument in argument.actions:
                        argv.extend(typed_action_cli_arguments(action_argument.expected))
                else:
                    assert isinstance(argument, str)
                    argv.append(argument)
            result = run_model_command(broker, argv)
            assert result.returncode == 0, result.stderr
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{") :])

    draft = payloads[action_steps[0].name]["draft"]
    assert isinstance(draft, Mapping)
    assert draft["revision"] == 4


def test_object_set_protocol_batches_query_bound_targets_as_one_revision(
    tmp_path: Path,
) -> None:
    bus_id = "{11111111-1111-1111-1111-111111111111}"
    bus_path = r"\Master-Mixer Hierarchy\Default Work Unit\Weapons"
    query = ExpectedGatewayStep(
        "relationship.output_bus",
        "query-object",
        (
            "--object-id",
            bus_id,
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        ),
    )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "path",
                        "value": rf"\Root\Target{index}",
                    },
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {"kind": "path", "value": bus_path},
                        }
                    ],
                }
                for index in range(3)
            ]
        },
    }
    transaction_steps = build_object_set_composer_transaction_steps(
        request,
        label="tx01",
        reference_identity_sources={bus_path: query.name},
    )
    start = next(
        step for step in transaction_steps if step.subcommand == "draft-start"
    )
    action = next(
        step for step in transaction_steps if step.subcommand == "draft-apply"
    )
    batch = action.arguments[-1]
    assert isinstance(batch, DraftTypedActionBatchArgument)
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(query, *transaction_steps),
        expected_wwise_version="2022.1",
    )
    draft_id = "od1-" + "1" * 32
    authority = "da1-" + "2" * 40
    broker._payloads_by_step[query.name] = {  # noqa: SLF001
        "ok": True,
        "command": "query-object",
        "count": 1,
        "objects": [
            {
                "id": bus_id,
                "name": "Weapons",
                "type": "Bus",
                "path": bus_path,
            }
        ],
    }
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": authority,
        "draft": {"draft_id": draft_id, "revision": 1},
    }
    actual_actions = []
    for expected in batch.actions:
        actual = json.loads(json.dumps(expected.expected))
        actual["references"][0]["target"] = {"kind": "id", "value": bus_id}
        actual_actions.append(actual)
    argv = (
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--compact",
        "--facts",
        *tuple(
            token
            for actual in actual_actions
            for token in typed_action_cli_arguments(actual)
        ),
    )

    broker._validate_step(action, argv)  # noqa: SLF001

    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": authority,
        "draft": {"draft_id": draft_id, "revision": 1},
    }
    broker._validate_operation_draft_payload(  # noqa: SLF001
        action,
        {
            "draft": {
                "draft_id": draft_id,
                "revision": 4,
                "lifecycle_state": "editable",
                "binding": {"operation": "object.set", "version": "2022.1"},
            },
        },
    )


def _archive_test_generic_typed_draft_batch_compares_number_values_semantically(
    tmp_path: Path,
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setRTPC",
        "arguments": {
            "object": {"kind": "path", "value": r"\Root\Rain"},
            "property": "Volume",
            "control_input": {
                "kind": "path",
                "value": r"\Game Parameters\Rain",
            },
            "points": [{"x": 0.0, "y": -48.0, "shape": "Linear"}],
            "mode": "add_or_replace",
        },
    }
    protocol = build_transaction_protocol((request,))
    start = next(step for step in protocol.steps if step.subcommand == "draft-start")
    disclosure = next(
        step for step in protocol.steps if step.subcommand == "request-array-item"
    )
    action = next(
        step for step in protocol.steps if step.name == "tx01.action.003"
    )
    batch = action.arguments[-1]
    assert isinstance(batch, DraftTypedActionBatchArgument)
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=protocol.steps,
        expected_wwise_version="2022.1",
    )
    draft_id = "od1-" + "1" * 32
    authority = "da1-" + "2" * 40
    child_handle = "trm1-" + "3" * 24
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": authority,
        "draft": {"draft_id": draft_id, "revision": 1},
    }
    broker._payloads_by_step["tx01.action.002"] = {  # noqa: SLF001
        "draft": {"draft_id": draft_id, "revision": 9},
    }
    broker._payloads_by_step[disclosure.name] = {  # noqa: SLF001
        "handle": child_handle,
    }

    actual_actions = []
    for expected in batch.actions:
        actual = json.loads(json.dumps(expected.expected))
        for binding in expected.response_bindings:
            actual[binding.pointer.removeprefix("/")] = child_handle
        if actual.get("value_type") == "number":
            actual["value"] = str(int(float(actual["value"])))
        actual_actions.append(actual)
    argv = (
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "9",
        "--compact",
        "--facts",
        *tuple(
            token
            for actual in actual_actions
            for token in typed_action_cli_arguments(actual)
        ),
    )

    broker._validate_step(action, argv)  # noqa: SLF001

    wrong_actions = json.loads(json.dumps(actual_actions))
    next(
        item
        for item in wrong_actions
        if item.get("value_type") == "number" and item.get("key") == "y"
    )["value"] = "-47"
    wrong_argv = (
        *argv[:8],
        *tuple(
            token
            for actual in wrong_actions
            for token in typed_action_cli_arguments(actual)
        ),
    )
    with pytest.raises(GatewayInvocationError, match="typed Draft batch"):
        broker._validate_step(action, wrong_argv)  # noqa: SLF001


def test_numbered_draft_actions_follow_handle_dependencies_not_fixture_order(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    contract = "waapi-skill.operation-draft-action/v1"
    start = ExpectedGatewayStep(
        "tx01.draft-start",
        "draft-start",
        ("object.set",),
    )
    first_target = ExpectedGatewayStep(
        "tx01.action.001",
        "draft-apply",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(start.name, "/draft/revision"),
            "--compact",
            "--facts",
            DraftTypedActionArgument(
                {
                    "contract": contract,
                    "action": "add_target",
                    "selector": {
                        "kind": "id",
                        "value": "{11111111-1111-1111-1111-111111111111}",
                    },
                }
            ),
        ),
    )
    first_notes = ExpectedGatewayStep(
        "tx01.action.002",
        "draft-apply",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(first_target.name, "/draft/revision"),
            "--compact",
            "--facts",
            DraftTypedActionArgument(
                {
                    "contract": contract,
                    "action": "set_target_field",
                    "name": "notes",
                    "value": "first",
                },
                response_bindings=(
                    DraftActionResponseBinding(
                        "/target_handle",
                        first_target.name,
                        "/draft/action_result/created_handles/0",
                    ),
                ),
            ),
        ),
    )
    second_target = ExpectedGatewayStep(
        "tx01.action.003",
        "draft-apply",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(first_notes.name, "/draft/revision"),
            "--compact",
            "--facts",
            DraftTypedActionArgument(
                {
                    "contract": contract,
                    "action": "add_target",
                    "selector": {
                        "kind": "id",
                        "value": "{22222222-2222-2222-2222-222222222222}",
                    },
                }
            ),
        ),
    )
    second_notes = ExpectedGatewayStep(
        "tx01.action.004",
        "draft-apply",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(second_target.name, "/draft/revision"),
            "--compact",
            "--facts",
            DraftTypedActionArgument(
                {
                    "contract": contract,
                    "action": "set_target_field",
                    "name": "notes",
                    "value": "second",
                },
                response_bindings=(
                    DraftActionResponseBinding(
                        "/target_handle",
                        second_target.name,
                        "/draft/action_result/created_handles/0",
                    ),
                ),
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(start, first_target, first_notes, second_target, second_notes),
        expected_wwise_version="2022.1",
    )
    draft_id = "od1-" + "1" * 32
    authority = "da1-" + "2" * 40
    first_handle = "odh1-" + "3" * 24
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": authority,
        "draft": {"draft_id": draft_id, "revision": 1},
    }
    broker._payloads_by_step[first_target.name] = {  # noqa: SLF001
        "draft": {
            "draft_id": draft_id,
            "revision": 2,
            "action_result": {"created_handles": [first_handle]},
        }
    }
    broker._next_step = 2  # noqa: SLF001

    def argv(action: dict[str, object]) -> tuple[str, ...]:
        return (
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--compact",
            "--facts",
            *typed_action_cli_arguments(action),
        )

    second_notes_action = {
        **dict(second_notes.arguments[-1].expected),
        "target_handle": "odh1-" + "4" * 24,
    }
    assert broker._match_dependency_ready_draft_action(  # noqa: SLF001
        argv(second_notes_action)
    ) is None
    broker._payloads_by_step[second_target.name] = {  # noqa: SLF001
        "draft": {
            "draft_id": draft_id,
            "revision": 2,
            "action_result": {"created_handles": ["odh1-" + "4" * 24]},
        }
    }
    assert broker._match_dependency_ready_draft_action(  # noqa: SLF001
        argv(second_notes_action)
    ) is None

    selected = broker._match_dependency_ready_draft_action(  # noqa: SLF001
        argv(dict(second_target.arguments[-1].expected))
    )
    assert selected is not None
    assert selected[0].name == second_target.name
    assert [step.name for step in broker._execution_steps[2:]] == [  # noqa: SLF001
        second_target.name,
        first_notes.name,
        second_notes.name,
    ]


def test_audio_import_numbered_declarations_remain_strictly_ordered(
    tmp_path: Path,
) -> None:
    del tmp_path
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "import_operation": "createNew",
            "imports": [
                {
                    "audio_file": native_absolute_test_path("inputs", f"{name}.wav"),
                    "object_path": rf"\Actor-Mixer Hierarchy\Default Work Unit\{name}",
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                }
                for name in ("A", "B")
            ],
        },
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")
    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )

    assert declaration.name == "tx01.declare-batch"
    assert [
        declaration.arguments[index + 1]
        for index, value in enumerate(declaration.arguments)
        if value == "--row-order"
    ] == ["row-001", "row-002"]
    assert declaration.arguments.count("--new-row") == 2
    assert "--new-root-row" not in declaration.arguments
    assert "--new-child-row" not in declaration.arguments
    assert all(step.subcommand != "draft-apply" for step in steps)


def test_audio_import_business_protocol_uses_stable_fields_and_strict_revision_order() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": rf"\Actor-Mixer Hierarchy\Default Work Unit\Weather\{name}",
                    "object_type": "Sound SFX",
                    "audio_file": native_absolute_test_path("inputs", f"{name}.wav"),
                    "import_language": "SFX",
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "Volume", "value": -4.0},
                    ],
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
                for name in ("Rain", "Wind")
            ],
            "import_operation": "createNew",
        },
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")
    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )

    assert sum(step.subcommand == "draft-bind-field" for step in steps) == 1
    assert declaration.arguments.count("volume_db") == 2
    assert declaration.arguments.count("--field-value") == 2
    assert "--object-type" not in declaration.arguments
    assert "--object-path" not in declaration.arguments
    assert all(step.subcommand != "draft-apply" for step in steps)
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    assert request["arguments"]["import_operation"] == "createNew"
    assert preview.expected_operation_request is not None
    assert (
        "import_operation"
        not in preview.expected_operation_request["arguments"]
    )
    broker_module.validate_operation_draft_protocol_steps(steps)

    first_index = steps.index(declaration)
    second_index = first_index + 1
    reordered = list(steps)
    reordered[first_index], reordered[second_index] = (
        reordered[second_index],
        reordered[first_index],
    )
    with pytest.raises(ValueError, match="expected revision"):
        broker_module.validate_operation_draft_protocol_steps(tuple(reordered))


def test_audio_import_nested_declaration_binds_compact_parent_receipt() -> None:
    parent = r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": parent,
                    "object_type": "RandomSequenceContainer",
                },
                {
                    "object_path": parent + r"\Snow_Step_01",
                    "object_type": "Sound SFX",
                    "audio_file": native_absolute_test_path(
                        "inputs", "snow_step_01.wav"
                    ),
                    "import_language": "SFX",
                },
            ]
        },
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")
    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )
    bindings = tuple(
        argument
        for argument in declaration.arguments
        if isinstance(argument, ResponseBinding)
    )

    new_row_indexes = [
        index
        for index, value in enumerate(declaration.arguments)
        if value == "--new-row"
    ]
    assert len(new_row_indexes) == 2
    child_index = new_row_indexes[1]
    assert declaration.arguments[child_index + 2] == "row-001"
    assert all(
        "/draft/declaration_receipt/" not in binding.pointer
        for binding in bindings
    )


def test_audio_import_witness_normalizes_only_gateway_owned_type_path_segments() -> None:
    expected = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Containers\Default Work Unit\Player_Footsteps\Snow"
                    ),
                    "object_type": "RandomSequenceContainer",
                    "switch_assignment": "Snow",
                },
                {
                    "object_path": (
                        r"\Containers\Default Work Unit\Player_Footsteps"
                        r"\Snow\Snow_Step_01"
                    ),
                    "object_type": "Sound SFX",
                    "audio_file": "/tmp/snow.wav",
                    "import_language": "SFX",
                },
            ]
        },
    }
    actual = {
        **expected,
        "arguments": {
            "imports": [
                {
                    **expected["arguments"]["imports"][0],
                    "object_path": (
                        r"\Containers\Default Work Unit\Player_Footsteps"
                        r"\<Random Container>Snow"
                    ),
                },
                {
                    **expected["arguments"]["imports"][1],
                    "object_path": (
                        r"\Containers\Default Work Unit\Player_Footsteps"
                        r"\<Random Container>Snow\<Sound SFX>Snow_Step_01"
                    ),
                },
            ]
        },
    }

    normalize = broker_module._normalize_audio_import_request_named_fields  # noqa: SLF001
    assert normalize(actual) == normalize(expected)
    wrong_type = json.loads(json.dumps(actual))
    wrong_type["arguments"]["imports"][1]["object_type"] = "Sound Voice"
    assert normalize(wrong_type) != normalize(expected)


def test_audio_import_witness_accepts_topological_structure_reordering_only() -> None:
    structure_root = {
        "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
        "object_type": "ActorMixer",
    }
    structure_rain = {
        "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain",
        "object_type": "ActorMixer",
    }
    structure_wind = {
        "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Wind",
        "object_type": "ActorMixer",
    }
    rain = {
        "object_path": (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain\Rain_Bed"
        ),
        "object_type": "Sound SFX",
        "audio_file": "/tmp/rain.wav",
    }
    wind = {
        "object_path": (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Wind\Wind_Bed"
        ),
        "object_type": "Sound SFX",
        "audio_file": "/tmp/wind.wav",
    }

    def request(imports: list[dict[str, object]]) -> dict[str, object]:
        return {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {"imports": imports},
        }

    expected = request(
        [structure_root, structure_rain, rain, structure_wind, wind]
    )
    structure_first = request(
        [structure_root, structure_rain, structure_wind, rain, wind]
    )
    media_reversed = request(
        [structure_root, structure_rain, structure_wind, wind, rain]
    )
    normalize = broker_module._normalize_audio_import_request_named_fields  # noqa: SLF001

    assert normalize(structure_first) == normalize(expected)
    assert normalize(media_reversed) != normalize(expected)


def test_numbered_draft_action_sequence_matches_any_exact_permutation() -> None:
    expected = (
        "tx01.draft-start",
        "tx01.action.001",
        "tx01.action.002",
        "tx01.action.003",
        "tx01.draft-check",
    )
    assert gateway_step_sequence_matches(
        expected,
        (
            "tx01.draft-start",
            "tx01.action.003",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.draft-check",
        ),
    )
    assert not gateway_step_sequence_matches(
        expected,
        (
            "tx01.draft-start",
            "tx01.action.003",
            "tx01.action.003",
            "tx01.action.002",
            "tx01.draft-check",
        ),
    )
    assert gateway_step_prefix_matches(
        expected,
        (
            "tx01.draft-start",
            "tx01.action.003",
            "tx01.action.001",
        ),
    )
    assert not gateway_step_prefix_matches(
        expected,
        (
            "tx01.draft-start",
            "tx01.action.003",
            "tx01.draft-check",
        ),
    )


def test_business_draft_setup_sequence_matches_any_exact_dependency_ready_order() -> None:
    expected = (
        "tx01.operation-schema",
        "tx01.draft-start",
        "tx01.bind-object.001",
        "tx01.bind-object.002",
        "tx01.bind-field.001",
        "tx01.configure",
        "tx01.declare.001",
    )
    actual = (
        "tx01.operation-schema",
        "tx01.draft-start",
        "tx01.bind-object.002",
        "tx01.configure",
        "tx01.bind-object.001",
        "tx01.bind-field.001",
        "tx01.declare.001",
    )

    assert gateway_step_sequence_matches(expected, actual)
    assert gateway_step_prefix_matches(expected, actual[:4])
    assert not gateway_step_sequence_matches(
        expected,
        (*actual[:5], "tx01.bind-object.001", *actual[6:]),
    )


def test_business_declaration_field_order_is_semantic_but_duplicates_stay_invalid() -> None:
    fixed = (
        "draft-id",
        "--task-authority",
        "authority",
        "--expected-revision",
        "5",
        "--declaration-id",
        "rain",
        "--parent-handle",
        "parent",
        "--name",
        "Rain",
        "--kind",
        "sound-sfx",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare.001",
        subcommand="draft-declare-new",
        arguments=(
            *fixed,
            "--field",
            "media_file",
            "/tmp/rain.wav",
            "--field",
            "volume_db",
            "-4",
            "--field",
            "loop",
            "infinite",
            "--field-value",
            "field-a",
            "0.75",
            "--field-value",
            "field-b",
            "target-handle",
        ),
    )
    reordered = (
        *fixed,
        "--field",
        "loop",
        "infinite",
        "--field-value",
        "field-b",
        "target-handle",
        "--field",
        "media_file",
        "/tmp/rain.wav",
        "--field-value",
        "field-a",
        "0.75",
        "--field",
        "volume_db",
        "-4",
    )
    broker = SimpleNamespace(_payloads_by_step={})

    normalized = CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reordered,
    )

    assert normalized == step.arguments
    duplicated = (*reordered, "--field", "volume_db", "-4")
    assert (
        CodexGatewayBroker._normalize_business_declaration_fact_order(
            broker,
            step,
            duplicated,
        )
        == duplicated
    )


def test_business_declaration_accepts_only_exact_explicit_derived_sfx_language() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "2",
        "--declaration-id",
        "rifle",
        "--object-handle",
        "boh1-" + "3" * 32,
        "--field",
        "media_file",
        "/tmp/rifle.wav",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare.001",
        subcommand="draft-declare-existing",
        arguments=fixed,
        allow_explicit_derived_sfx_language=True,
    )
    broker = SimpleNamespace(_payloads_by_step={})
    explicit_sfx = (*fixed, "--field", "language", "SFX")

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        explicit_sfx,
    ) == fixed
    for invalid in (
        (*fixed, "--field", "language", "English(US)"),
        (*explicit_sfx, "--field", "language", "SFX"),
    ):
        assert CodexGatewayBroker._normalize_business_declaration_fact_order(
            broker,
            step,
            invalid,
        ) == invalid


def test_import_batch_group_order_is_transport_but_row_order_is_business_meaning() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "2",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare-batch",
        subcommand="draft-declare-import-batch",
        arguments=(
            *fixed,
            "--expected-declaration-count",
            "2",
            "--expected-switch-assignment-count",
            "1",
            "--media-directory",
            "/tmp/incoming",
            "--row-order",
            "snow",
            "--new-row",
            "snow",
            "parent",
            "Snow",
            "random-container",
            "--switch-value",
            "snow",
            "Snow",
            "--row-order",
            "snow-step-01",
            "--new-row",
            "snow-step-01",
            "snow",
            "Snow_Step_01",
            "sound-sfx",
            "--media-file",
            "snow-step-01",
            "snow.wav",
            "--field",
            "snow-step-01",
            "volume_db",
            "-4.0",
        ),
    )
    reordered = (
        *fixed,
        "--row-order",
        "snow",
        "--row-order",
        "snow-step-01",
        "--media-file",
        "snow-step-01",
        "snow.wav",
        "--field",
        "snow-step-01",
        "volume_db",
        "-4",
        "--switch-value",
        "snow",
        "Snow",
        "--new-row",
        "snow-step-01",
        "snow",
        "Snow_Step_01",
        "sound-sfx",
        "--new-row",
        "snow",
        "parent",
        "Snow",
        "random-container",
        "--expected-switch-assignment-count",
        "1",
        "--media-directory",
        "/tmp/incoming",
        "--expected-declaration-count",
        "2",
    )
    broker = SimpleNamespace(_payloads_by_step={})

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reordered,
    ) == step.arguments
    renamed = tuple(
        {
            "snow": "container-snow",
            "snow-step-01": "sound-snow-01",
        }.get(value, value)
        for value in reordered
    )
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        renamed,
    ) == step.arguments
    wrong_order = list(reordered)
    first = wrong_order.index("snow", len(fixed))
    second = wrong_order.index("snow-step-01", first + 1)
    wrong_order[first], wrong_order[second] = (
        wrong_order[second],
        wrong_order[first],
    )
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        tuple(wrong_order),
    ) == tuple(wrong_order)
    duplicate = (*reordered, "--switch-value", "snow", "Snow")
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        duplicate,
    ) == duplicate
    broken_parent = list(renamed)
    parent_index = broken_parent.index("--new-row") + 2
    assert broken_parent[parent_index] == "container-snow"
    broken_parent[parent_index] = "another-container"
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        tuple(broken_parent),
    ) != step.arguments


def test_import_batch_accepts_topological_structure_reordering_but_keeps_media_order() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "3",
    )
    expected_rows = (
        ("root", "external-parent", "Weather", "actor-mixer", None),
        ("rain", "root", "Rain", "actor-mixer", None),
        ("rain-bed", "rain", "Rain_Bed", "sound-sfx", "rain.wav"),
        ("wind", "root", "Wind", "actor-mixer", None),
        ("wind-bed", "wind", "Wind_Bed", "sound-sfx", "wind.wav"),
    )

    def groups(
        rows: tuple[tuple[str, str, str, str, str | None], ...],
    ) -> tuple[str, ...]:
        values: list[str] = []
        for row_id, parent, name, kind, _media in rows:
            values.extend(("--row-order", row_id))
        for row_id, parent, name, kind, _media in rows:
            values.extend(("--new-row", row_id, parent, name, kind))
        for row_id, _parent, _name, _kind, media in rows:
            if media is not None:
                values.extend(("--media-file", row_id, media))
        return tuple(values)

    step = ExpectedGatewayStep(
        name="tx01.declare-batch",
        subcommand="draft-declare-import-batch",
        arguments=(*fixed, *groups(expected_rows)),
    )
    structure_first = (
        expected_rows[0],
        expected_rows[1],
        expected_rows[3],
        expected_rows[2],
        expected_rows[4],
    )
    actual = (*fixed, *groups(structure_first))
    broker = SimpleNamespace(_payloads_by_step={})

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        actual,
    ) == step.arguments

    media_reversed = (
        expected_rows[0],
        expected_rows[1],
        expected_rows[3],
        expected_rows[4],
        expected_rows[2],
    )
    reversed_actual = (*fixed, *groups(media_reversed))
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reversed_actual,
    ) != step.arguments


def test_import_batch_accepts_one_exact_derived_sfx_language_per_row() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "2",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare-batch",
        subcommand="draft-declare-import-batch",
        arguments=(
            *fixed,
            "--expected-declaration-count",
            "2",
            "--expected-switch-assignment-count",
            "0",
            "--row-order",
            "rifle",
            "--existing-row",
            "rifle",
            "boh1-" + "3" * 32,
            "--row-order",
            "tail",
            "--new-row",
            "tail",
            "boh1-" + "4" * 32,
            "Rifle_Tail",
            "sound-sfx",
        ),
        allow_explicit_derived_sfx_language=True,
    )
    broker = SimpleNamespace(_payloads_by_step={})
    explicit = (
        *step.arguments,
        "--field",
        "rifle",
        "language",
        "SFX",
        "--field",
        "tail",
        "language",
        "SFX",
    )

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        explicit,
    ) == step.arguments
    for invalid in (
        (*step.arguments, "--field", "rifle", "language", "English(US)"),
        (*explicit, "--field", "rifle", "language", "SFX"),
    ):
        assert CodexGatewayBroker._normalize_business_declaration_fact_order(
            broker,
            step,
            invalid,
        ) == invalid


def test_cli_console_plan_group_order_is_transport_not_business_meaning() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "1",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare-cli-console-plan",
        subcommand="draft-declare-cli-console-plan",
        arguments=(
            *fixed,
            "--value",
            "project_file",
            "/tmp/SemanticProject.wproj",
            "--item",
            "platforms",
            "Windows",
            "--toggle",
            "skip_languages",
            "enable",
            "--value",
            "source_control",
            "disabled",
            "--mapping",
            "soundbank_directories_by_platform",
            "Windows",
            "GeneratedSoundBanks/FreshAgent",
            "--value",
            "verbosity",
            "quiet",
        ),
    )
    reordered = (
        *fixed,
        "--value",
        "project_file",
        "/tmp/SemanticProject.wproj",
        "--item",
        "platforms",
        "Windows",
        "--toggle",
        "skip_languages",
        "enable",
        "--mapping",
        "soundbank_directories_by_platform",
        "Windows",
        "GeneratedSoundBanks/FreshAgent",
        "--value",
        "source_control",
        "disabled",
        "--value",
        "verbosity",
        "quiet",
    )
    broker = SimpleNamespace(_payloads_by_step={})

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reordered,
    ) == step.arguments
    changed = list(reordered)
    changed[changed.index("disabled")] = "enabled"
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        tuple(changed),
    ) != step.arguments


@pytest.mark.parametrize(
    ("subcommand", "expected_groups", "reordered_groups"),
    (
        (
            "draft-declare-project-setting-plan",
            (
                ("--game-parameter-handle", "boh1-game-parameter"),
                ("--minimum", "-10"),
                ("--maximum", "100"),
                ("--curve-update-outcome", "stretch"),
            ),
            (
                ("--minimum", "-10"),
                ("--maximum", "100"),
                ("--curve-update-outcome", "stretch"),
                ("--game-parameter-handle", "boh1-game-parameter"),
            ),
        ),
        (
            "draft-declare-soundengine-plan",
            (
                ("--event-handle", "boh1-event"),
                ("--action", "Stop"),
                ("--fade-duration-ms", "250"),
                ("--fade-curve", "Linear"),
            ),
            (
                ("--action", "Stop"),
                ("--fade-duration-ms", "250"),
                ("--fade-curve", "Linear"),
                ("--event-handle", "boh1-event"),
            ),
        ),
    ),
)
def test_closed_business_plan_named_argument_order_is_transport(
    subcommand: str,
    expected_groups: tuple[tuple[str, str], ...],
    reordered_groups: tuple[tuple[str, str], ...],
) -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "2",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare-plan",
        subcommand=subcommand,
        arguments=(*fixed, *(token for group in expected_groups for token in group)),
    )
    actual = (*fixed, *(token for group in reordered_groups for token in group))
    broker = SimpleNamespace(_payloads_by_step={})

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        actual,
    ) == step.arguments


def test_core_plan_group_order_is_transport_not_business_meaning() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "5",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare-core-plan",
        subcommand="draft-declare-core-plan",
        arguments=(
            *fixed,
            "--role",
            "audio_object_handles",
            "object-a",
            "--role",
            "audio_object_handles",
            "object-b",
            "--item",
            "platform_names",
            "Windows",
            "--item",
            "languages",
            "SFX",
            "--value",
            "io_root",
            "/tmp/io",
        ),
    )
    reordered = (
        *fixed,
        "--value",
        "io_root",
        "/tmp/io",
        "--role",
        "audio_object_handles",
        "object-a",
        "--role",
        "audio_object_handles",
        "object-b",
        "--item",
        "platform_names",
        "Windows",
        "--item",
        "languages",
        "SFX",
    )
    broker = SimpleNamespace(_payloads_by_step={})

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reordered,
    ) == step.arguments


def test_audio_convert_core_plan_reorders_resolved_role_handles() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2024.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.audio.convert",
            "args": {
                "objects": [
                    r"\Actor-Mixer Hierarchy\Weapons\Rifle",
                    r"\Actor-Mixer Hierarchy\Weapons\Shotgun",
                ],
                "platforms": ["Windows"],
                "languages": ["SFX"],
            },
            "options": {},
            "io_root": "/tmp/audio-convert",
        },
    }
    steps = build_audio_convert_business_transaction_steps(request, label="tx01")
    step = next(item for item in steps if item.subcommand == "draft-declare-core-plan")
    payloads = {
        "tx01.draft-start": {
            "draft": {"draft_id": "od1-" + "1" * 32, "revision": 3},
            "task_authority": "da1-" + "2" * 40,
        },
        "tx01.bind-audio-object-01": {
            "bound_object": {"handle": "object-a"},
            "draft": {"revision": 2},
        },
        "tx01.bind-audio-object-02": {
            "bound_object": {"handle": "object-b"},
            "draft": {"revision": 3},
        },
    }

    def resolve(value: object) -> str:
        if not isinstance(value, ResponseBinding):
            return str(value)
        source = payloads[value.step]
        current: object = source
        for token in value.pointer.lstrip("/").split("/"):
            assert isinstance(current, Mapping)
            current = current[token]
        return str(current)

    resolved = tuple(resolve(value) for value in step.arguments)
    io_root_index = resolved.index("--value")
    reordered = (
        *resolved[:5],
        *resolved[io_root_index:],
        *resolved[5:io_root_index],
    )
    broker = SimpleNamespace(_payloads_by_step=payloads)

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reordered,
    ) == resolved


def test_host_plan_group_order_is_transport_not_business_meaning() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "1",
    )
    step = ExpectedGatewayStep(
        name="tx01.declare-host-plan",
        subcommand="draft-declare-host-plan",
        arguments=(
            *fixed,
            "--value",
            "output_file",
            "/tmp/FreshAgentTone.wav",
            "--value",
            "waveform",
            "sine",
            "--value",
            "frequency_hz",
            "440",
            "--value",
            "sustain_seconds",
            "1.0",
            "--item",
            "waveform_channels",
            "0",
            "--toggle",
            "anonymous_channels",
            "enable",
        ),
    )
    reordered = (
        *fixed,
        "--value",
        "output_file",
        "/tmp/FreshAgentTone.wav",
        "--toggle",
        "anonymous_channels",
        "enable",
        "--item",
        "waveform_channels",
        "0",
        "--value",
        "frequency_hz",
        "440",
        "--value",
        "sustain_seconds",
        "1",
        "--value",
        "waveform",
        "sine",
    )
    broker = SimpleNamespace(_payloads_by_step={})

    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        reordered,
    ) == step.arguments
    changed = list(reordered)
    changed[changed.index("440")] = "880"
    assert CodexGatewayBroker._normalize_business_declaration_fact_order(
        broker,
        step,
        tuple(changed),
    ) != step.arguments


def test_business_request_normalizes_only_exact_live_bound_reference_paths() -> None:
    bound_path = r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus"
    unknown_path = r"\Master-Mixer Hierarchy\Default Work Unit\Unknown"
    value = {
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": bound_path,
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {"kind": "path", "value": bound_path},
                        },
                        {
                            "name": "Unknown",
                            "target": {"kind": "path", "value": unknown_path},
                        },
                    ],
                }
            ]
        },
    }

    normalized = broker_module._normalize_bound_business_reference_paths(  # noqa: SLF001
        value,
        path_to_id={bound_path: "{11111111-1111-1111-1111-111111111111}"},
    )

    row = normalized["arguments"]["imports"][0]
    assert row["object_path"] == bound_path
    assert row["references"][0]["target"] == {
        "kind": "id",
        "value": "{11111111-1111-1111-1111-111111111111}",
    }
    assert row["references"][1]["target"] == {
        "kind": "path",
        "value": unknown_path,
    }


def test_audio_convert_witness_normalizes_only_its_bound_object_paths() -> None:
    bound_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2024.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.audio.convert",
            "args": {
                "objects": [bound_path, r"\Unknown"],
                "platforms": ["Windows"],
                "languages": ["SFX"],
            },
            "options": {},
            "io_root": "/tmp/io",
        },
    }

    normalized = broker_module._normalize_bound_business_reference_paths(  # noqa: SLF001
        request,
        path_to_id={bound_path: "{11111111-1111-1111-1111-111111111111}"},
    )

    assert normalized["arguments"]["args"]["objects"] == [
        "{11111111-1111-1111-1111-111111111111}",
        r"\Unknown",
    ]
    assert normalized["arguments"]["args"]["platforms"] == ["Windows"]


def test_business_draft_setup_broker_selects_unique_binding_and_configuration(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "import_operation": "createNew",
            "auto_add_to_source_control": True,
            "imports": [
                {
                    "audio_file": native_absolute_test_path("inputs", "rain.wav"),
                    "object_path": r"\Actor-Mixer Hierarchy\Weather\Rain",
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                    "event": {
                        "path": r"\Events\Play_Rain",
                        "action": "Play",
                    },
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": r"\Master-Mixer Hierarchy\Weather",
                            },
                        }
                    ],
                }
            ],
        },
    }
    steps = build_audio_import_composer_transaction_steps(request, label="tx01")
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    draft_id = "od1-" + "1" * 32
    authority = "da1-" + "2" * 40
    start = next(step for step in steps if step.name == "tx01.draft-start")
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": authority,
        "draft": {"draft_id": draft_id, "revision": 1},
    }
    broker._next_step = 2  # noqa: SLF001

    selected = broker._match_dependency_ready_business_setup_step(  # noqa: SLF001
        (
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--object-path-segment",
            "Events",
        )
    )
    assert selected is not None
    assert selected[0].name == "tx01.bind-object.003"

    first_binding = broker._execution_steps[2]  # noqa: SLF001
    broker._payloads_by_step[first_binding.name] = {  # noqa: SLF001
        "draft": {"draft_id": draft_id, "revision": 2},
    }
    broker._next_step = 3  # noqa: SLF001
    configured = broker._match_dependency_ready_business_setup_step(  # noqa: SLF001
        (
            "draft-business-configure",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--add-to-source-control",
        )
    )
    assert configured is not None
    assert configured[0].name == "tx01.configure"

    declaration_index = next(
        index
        for index, step in enumerate(broker._execution_steps)  # noqa: SLF001
        if step.name == "tx01.declare-batch"
    )
    previous = broker._execution_steps[declaration_index - 1]  # noqa: SLF001
    broker._payloads_by_step[previous.name] = {  # noqa: SLF001
        "draft": {"draft_id": draft_id, "revision": 5},
    }
    broker._next_step = declaration_index  # noqa: SLF001
    declaration = broker._rebase_business_draft_revision(  # noqa: SLF001
        broker._execution_steps[declaration_index]  # noqa: SLF001
    )
    assert isinstance(declaration.arguments[4], ResponseBinding)
    assert declaration.arguments[4].step == previous.name


def _two_target_object_set_request() -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "path",
                        "value": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit\A"
                        ),
                    },
                    "properties": [{"name": "Pitch", "value": 100}],
                },
                {
                    "object": {
                        "kind": "path",
                        "value": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit\B"
                        ),
                    },
                    "properties": [{"name": "Volume", "value": -3.0}],
                },
            ],
            "on_name_conflict": "fail",
        },
    }


def test_object_set_field_discovery_can_follow_its_bound_target_early(
    tmp_path: Path,
) -> None:
    request = _two_target_object_set_request()
    arguments = request["arguments"]
    assert isinstance(arguments, dict)
    objects = arguments["objects"]
    assert isinstance(objects, list) and isinstance(objects[0], dict)
    properties = objects[0]["properties"]
    assert isinstance(properties, list)
    assert isinstance(properties[0], dict)
    properties[0]["name"] = "FadeTime"
    properties.append({"name": "Delay", "value": 0.25})
    steps = build_object_graph_business_transaction_steps(
        request,
        label="tx01",
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    start = next(step for step in steps if step.name == "tx01.draft-start")
    first = next(step for step in steps if step.name == "tx01.bind-target-01-01")
    discovery = next(step for step in steps if step.name == "tx01.discover-field-01")
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "2" * 40,
        "draft": {"draft_id": "od1-" + "1" * 32, "revision": 1},
    }
    broker._payloads_by_step[first.name] = {  # noqa: SLF001
        "draft": {"draft_id": "od1-" + "1" * 32, "revision": 2},
        "bound_object": {"handle": "boh1-" + "3" * 32},
    }
    broker._next_step = steps.index(first) + 1  # noqa: SLF001
    rebased = broker._rebase_business_draft_revision(discovery)  # noqa: SLF001

    def resolve(argument: object) -> str:
        if isinstance(argument, ResponseBinding):
            current: object = broker._payloads_by_step[argument.step]  # noqa: SLF001
            for token in argument.pointer.removeprefix("/").split("/"):
                assert isinstance(current, dict)
                current = current[token]
            return str(current)
        assert isinstance(argument, str)
        return argument

    actual_values = [resolve(argument) for argument in rebased.arguments]
    first_meaning = actual_values.index("--meaning") + 1
    assert actual_values[first_meaning] == "fadetime"
    second_meaning = actual_values.index("--meaning", first_meaning + 1) + 1
    actual_values[first_meaning] = "Play Action Fade Time"
    actual_values[second_meaning] = "Play Action delay time in seconds"
    actual = tuple(actual_values)
    assert actual.count("--meaning") == 2

    selected = broker._match_dependency_ready_business_setup_step(  # noqa: SLF001
        (discovery.subcommand, *actual)
    )

    assert selected is not None
    assert selected[0].name == discovery.name


def test_object_set_declaration_can_follow_its_ready_bindings_early(
    tmp_path: Path,
) -> None:
    steps = build_object_graph_business_transaction_steps(
        _two_target_object_set_request(),
        label="tx01",
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    start = next(step for step in steps if step.name == "tx01.draft-start")
    first = next(step for step in steps if step.name == "tx01.bind-target-01-01")
    discovery = next(step for step in steps if step.name == "tx01.discover-field-01")
    declaration = next(
        step for step in steps if step.name == "tx01.declare-existing-01"
    )
    draft_id = "od1-" + "1" * 32
    authority = "da1-" + "2" * 40
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": authority,
        "draft": {"draft_id": draft_id, "revision": 1},
    }
    broker._payloads_by_step[first.name] = {  # noqa: SLF001
        "draft": {"draft_id": draft_id, "revision": 2},
        "bound_object": {"handle": "boh1-" + "3" * 32},
    }
    broker._next_step = steps.index(first) + 1  # noqa: SLF001

    def resolve(step: ExpectedGatewayStep) -> tuple[str, ...]:
        values: list[str] = []
        for argument in step.arguments:
            if isinstance(argument, ResponseBinding):
                current: object = broker._payloads_by_step[argument.step]  # noqa: SLF001
                for token in argument.pointer.removeprefix("/").split("/"):
                    if isinstance(current, dict):
                        current = current[token]
                    else:
                        assert isinstance(current, list)
                        current = current[int(token)]
                values.append(str(current))
            else:
                assert isinstance(argument, str)
                values.append(argument)
        return tuple(values)

    early_discovery = broker._match_dependency_ready_business_setup_step(  # noqa: SLF001
        (discovery.subcommand, *resolve(broker._rebase_business_draft_revision(discovery)))  # noqa: SLF001
    )
    assert early_discovery is not None
    broker._payloads_by_step[discovery.name] = {  # noqa: SLF001
        "draft": {"draft_id": draft_id, "revision": 3},
        "field_candidates": [{"handle": "bfh1-" + "4" * 32}],
        "meaning_results": [
            {"candidates": [{"handle": "bfh1-" + "4" * 32}]}
        ],
    }
    broker._next_step += 1  # noqa: SLF001

    rebased = broker._rebase_business_draft_revision(declaration)  # noqa: SLF001
    actual = list(resolve(rebased))
    declaration_id = actual.index("--declaration-id") + 1
    actual[declaration_id] = "first-target"
    selected = broker._match_dependency_ready_business_setup_step(  # noqa: SLF001
        (declaration.subcommand, *actual)
    )

    assert selected is not None
    assert selected[0].name == declaration.name


def test_business_draft_normalizes_live_bound_ids_to_reviewed_paths(
    tmp_path: Path,
) -> None:
    request = _two_target_object_set_request()
    steps = build_object_graph_business_transaction_steps(request, label="tx01")
    preview = next(step for step in steps if step.subcommand == "preview-from-draft")
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    ids = (
        "{11111111-1111-1111-1111-111111111111}",
        "{22222222-2222-2222-2222-222222222222}",
    )
    for step, object_id, path in zip(
        (item for item in steps if item.subcommand == "draft-bind-object"),
        ids,
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\A",
            r"\Actor-Mixer Hierarchy\Default Work Unit\B",
        ),
        strict=True,
    ):
        broker._payloads_by_step[step.name] = {  # noqa: SLF001
            "bound_object": {"id": object_id, "path": path}
        }
    actual = json.loads(json.dumps(request))
    actual["arguments"].pop("on_name_conflict")
    for row, object_id in zip(actual["arguments"]["objects"], ids, strict=True):
        row["object"] = {"kind": "id", "value": object_id}

    normalized = broker._normalize_operation_draft_query_identities(  # noqa: SLF001
        actual,
        preview_step=preview,
    )

    assert broker_module._object_operation_json_equal(  # noqa: SLF001
        normalized,
        request,
    )


def test_business_declaration_ids_are_task_local_but_bounded_and_unique(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)

    start = ExpectedGatewayStep(
        "tx01.draft-start",
        "draft-start",
        ("audio.import",),
    )

    def declaration(
        name: str,
        canonical_id: str,
        revision_source: str,
    ) -> ExpectedGatewayStep:
        return ExpectedGatewayStep(
            name,
            "draft-declare-new",
            (
                ResponseBinding(start.name, "/draft/draft_id"),
                "--task-authority",
                ResponseBinding(start.name, "/task_authority"),
                "--expected-revision",
                ResponseBinding(revision_source, "/draft/revision"),
                "--declaration-id",
                canonical_id,
                "--parent-handle",
                "boh1-" + "3" * 32,
                "--name",
                "Weather",
                "--kind",
                "actor-mixer",
            ),
        )

    first = declaration("tx01.declare.001", "row-001", start.name)
    second = declaration("tx01.declare.002", "row-002", first.name)
    check = ExpectedGatewayStep(
        "tx01.check",
        "draft-check",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(second.name, "/draft/revision"),
        ),
    )
    preview = ExpectedGatewayStep(
        "tx01.preview",
        "preview-from-draft",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(check.name, "/draft/revision"),
            "--apply",
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(start, first, second, check, preview),
        expected_wwise_version="2022.1",
    )

    def argv(declaration_id: str) -> tuple[str, ...]:
        return (
            "draft-declare-new",
            "od1-" + "1" * 32,
            "--task-authority",
            "da1-" + "2" * 40,
            "--expected-revision",
            "1",
            "--declaration-id",
            declaration_id,
            "--parent-handle",
            "boh1-" + "3" * 32,
            "--name",
            "Weather",
            "--kind",
            "actor-mixer",
        )

    rebound = broker._bind_task_local_declaration_id(  # noqa: SLF001
        first,
        argv("weather_interactive"),
    )
    assert rebound.arguments[6] == "weather_interactive"
    broker._execution_steps[1] = rebound  # noqa: SLF001
    broker._next_step = 2  # noqa: SLF001

    with pytest.raises(GatewayInvocationError, match="unique"):
        broker._bind_task_local_declaration_id(  # noqa: SLF001
            second,
            argv("weather_interactive"),
        )
    with pytest.raises(GatewayInvocationError, match="bounded"):
        broker._bind_task_local_declaration_id(  # noqa: SLF001
            second,
            argv("../not-local"),
        )


def _read_only_draft_evidence_fixture(
    tmp_path: Path,
) -> tuple[
    CodexGatewayBroker,
    tuple[ExpectedGatewayStep, ...],
    list[dict[str, object]],
    Path,
]:
    operation = "ak.wwise.core.mediaPool.get"
    version = "2025.1"
    steps = typed_read_draft_steps(
        "tx01",
        operation,
        version=version,
        args={"maxResults": 200},
        options={"return": ["Filename"]},
        post_filter={
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": "footstep",
            "limit": 20,
        },
    )
    state_directory = tmp_path / "state"
    store = OperationDraftStore(state_directory)
    schema_digest = request_contract(version, operation).schema_digest
    composer_digest = operation_composer_digest(operation, version)
    started = store.start(
        operation=operation,
        version=version,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    draft_id = started.record.draft_id
    authority = started.task_authority
    composition = new_composition(operation, version)
    start_payload: dict[str, object] = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "status": "ok",
        "command": "draft-start",
        "task_authority": authority,
        "draft": {
            "draft_id": draft_id,
            "revision": 1,
            "lifecycle_state": "editable",
            "binding": {
                "operation": operation,
                "version": version,
                "schema_digest": schema_digest,
            },
            **operation_draft_public_projection(
                composition_projection(operation, version, composition)
            ),
        },
    }
    records: list[dict[str, object]] = [
        {
            "succeeded": True,
            "gateway_arguments": ["gateway.py", "request-schema", operation],
            "payload": {
                "contract": "waapi-skill.typed-request-schema/v1",
                "ok": True,
                "command": "request-schema",
            },
        },
        {
            "succeeded": True,
            "gateway_arguments": ["gateway.py", "draft-start", operation],
            "payload": start_payload,
        },
    ]
    revision = 1
    action_payloads: dict[str, Mapping[str, object]] = {}
    for step in (row for row in steps if row.subcommand == "draft-apply"):
        argument = step.arguments[-1]
        action_arguments = (
            (argument,)
            if isinstance(argument, DraftTypedActionArgument)
            else argument.actions
            if isinstance(argument, DraftTypedActionBatchArgument)
            else ()
        )
        assert action_arguments
        actions = tuple(dict(item.expected) for item in action_arguments)
        prior_revision = revision
        record = store.apply_actions(
            draft_id,
            task_authority=authority,
            expected_revision=revision,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            actions=actions,
        )
        assert record.composition is not None
        composition = record.composition
        revision = record.revision
        payload = {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": True,
            "status": "ok",
            "command": "draft-apply",
            "draft": {
                "draft_id": draft_id,
                "revision": revision,
                "lifecycle_state": "editable",
                "binding": {
                    "operation": operation,
                    "version": version,
                    "schema_digest": schema_digest,
                },
                **operation_draft_public_projection(
                    composition_projection(operation, version, composition)
                ),
            },
        }
        action_payloads[step.name] = payload
        records.append(
            {
                "succeeded": True,
                "gateway_arguments": [
                    "gateway.py",
                    "draft-apply",
                    draft_id,
                    "--task-authority",
                    authority,
                    "--expected-revision",
                    str(prior_revision),
                    "--compact",
                    "--facts",
                    *(
                        token
                        for action in actions
                        for token in typed_action_cli_arguments(action)
                    ),
                ],
                "payload": payload,
            }
        )
    check_payload: dict[str, object] = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "status": "ok",
        "command": "draft-check",
        "offline": False,
        "api_attempted": operation,
        "typed_request": {
            "contract": "waapi-skill.typed-request/v1",
            "schema_digest": schema_digest,
        },
        "call": {
            "api": operation,
            "version": version,
            "ok": True,
            "dry_run": False,
            "evidence_path": str(tmp_path / "call-evidence.json"),
        },
        "schema_validation": {
            "request": {"uri": operation, "version": version},
            "result": {"uri": operation, "version": version},
        },
        "post_filter": {
            "contract": "waapi-skill.media-pool-post-filter/v1",
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "status": "applied",
        },
        "agent_result": {"return": [{"Filename": "footstep.wav"}]},
    }
    records.append(
        {
            "succeeded": True,
            "gateway_arguments": [
                "gateway.py",
                "draft-check",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(revision),
                "--post-filter-value",
                "footstep",
                "--post-filter-limit",
                "20",
            ],
            "payload": check_payload,
        }
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=steps,
        expected_wwise_version=version,
    )
    broker._payloads_by_step[steps[1].name] = start_payload  # noqa: SLF001
    broker._payloads_by_step.update(action_payloads)  # noqa: SLF001
    for step, record in zip(steps, records, strict=True):
        record["step_name"] = step.name
    return broker, steps, records, state_directory


def test_business_draft_start_seals_business_evidence_without_generic_facts(
    tmp_path: Path,
) -> None:
    operation = "audio.import"
    version = "2025.1"
    state_directory = tmp_path / "state"
    store = OperationDraftStore(state_directory)
    schema_digest = operation_request_schema_digest(operation, version)
    composer_digest = operation_composer_digest(operation, version)
    started = store.start(
        operation=operation,
        version=version,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    composition = started.record.composition
    assert isinstance(composition, Mapping)
    start_payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "status": "editable",
        "command": "draft-start",
        "task_authority": started.task_authority,
        "draft": {
            "contract": "waapi-skill.operation-draft/v1",
            "draft_id": started.draft_id,
            "revision": 1,
            "lifecycle_state": "editable",
            "binding": {
                "operation": operation,
                "version": version,
                "schema_digest": schema_digest,
            },
            **operation_draft_public_projection(
                composition_projection(operation, version, composition)
            ),
        },
    }
    step = ExpectedGatewayStep(
        name="tx01.draft-start",
        subcommand="draft-start",
        arguments=(operation,),
    )
    record = {
        "step_name": step.name,
        "succeeded": True,
        "gateway_arguments": ["gateway.py", "draft-start", operation],
        "payload": start_payload,
    }

    evidence = typed_evidence_module.validate_typed_draft_evidence(
        state_directory=state_directory,
        steps=(step,),
        broker_records=(record,),
    )

    assert evidence is not None
    assert evidence["contract"] == (
        "waapi-skill.codex-business-draft-evidence/v1"
    )
    assert evidence["operation"] == operation
    assert evidence["business_session"] is None
    assert evidence["canonical_request"] is None


def test_read_only_draft_check_binds_direct_result_without_draft_projection(
    tmp_path: Path,
) -> None:
    broker, steps, records, state_directory = _read_only_draft_evidence_fixture(
        tmp_path
    )
    check = steps[-1]
    payload = records[-1]["payload"]
    assert isinstance(payload, dict)

    broker._validate_operation_draft_payload(check, payload)  # noqa: SLF001
    records[-1]["payload"] = json.loads(json.dumps(payload, sort_keys=True))
    evidence = typed_evidence_module.validate_typed_draft_evidence(
        state_directory=state_directory,
        steps=steps,
        broker_records=records,
    )

    assert evidence is not None
    assert evidence["lifecycle_state"] == "editable"
    assert evidence["check"] is None
    assert evidence["preview_binding"] is None
    assert evidence["canonical_request"]["arguments"] == {
        "api": "ak.wwise.core.mediaPool.get",
        "args": {"maxResults": 200},
        "options": {"return": ["Filename"]},
    }
    assert evidence["direct_read_binding"]["agent_result_sha256"] == canonical_sha256(
        payload["agent_result"]
    )


def test_read_only_draft_check_rejects_schema_binding_tamper(tmp_path: Path) -> None:
    broker, steps, records, state_directory = _read_only_draft_evidence_fixture(
        tmp_path
    )
    payload = json.loads(json.dumps(records[-1]["payload"]))
    payload["typed_request"]["schema_digest"] = "0" * 64

    with pytest.raises(GatewayInvocationError, match="typed request binding"):
        broker._validate_operation_draft_payload(steps[-1], payload)  # noqa: SLF001

    records[-1]["payload"] = payload
    with pytest.raises(
        typed_evidence_module.TypedDraftEvidenceError,
        match="typed request binding",
    ):
        typed_evidence_module.validate_typed_draft_evidence(
            state_directory=state_directory,
            steps=steps,
            broker_records=records,
        )


def test_read_only_draft_check_rejects_mutation_style_draft_projection(
    tmp_path: Path,
) -> None:
    broker, steps, records, _state_directory = _read_only_draft_evidence_fixture(
        tmp_path
    )
    start_payload = records[1]["payload"]
    assert isinstance(start_payload, dict)
    start_draft = start_payload["draft"]
    assert isinstance(start_draft, dict)
    mutation_style = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "status": "ok",
        "command": "draft-check",
        "draft": {
            **start_draft,
            "revision": 4,
        },
    }

    with pytest.raises(GatewayInvocationError, match="typed request binding"):
        broker._validate_operation_draft_payload(  # noqa: SLF001
            steps[-1],
            mutation_style,
        )


def _archive_test_draft_replay_uses_the_validated_submitted_numeric_spelling(
    tmp_path: Path,
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "id",
                        "value": "{11111111-1111-1111-1111-111111111111}",
                    },
                    "properties": [{"name": "Volume", "value": 0.0}],
                }
            ]
        },
    }
    steps = build_object_set_composer_transaction_steps(request, label="tx01")
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    start = next(step for step in steps if step.subcommand == "draft-start")
    actions = [step for step in steps if step.subcommand == "draft-apply"]
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    handle = "odh1-" + "3" * 24
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "2" * 40,
        "draft": {
            "draft_id": "od1-" + "1" * 32,
            "revision": 1,
            "binding": {"operation": "object.set", "version": "2022.1"},
        },
    }
    composition = new_composition("object.set", "2022.1")
    submitted_actions = (
        {
            **dict(actions[0].arguments[-1].expected),
            # JSON 0 is semantically equal to the reviewed 0.0, but its
            # deterministic composition digest is intentionally different.
            "properties": [{"name": "Volume", "value": 0}],
        },
    )
    for revision, (step, action) in enumerate(
        zip(actions, submitted_actions, strict=True),
        start=2,
    ):
        created = [handle] if action["action"] == "add_target" else []

        def handle_factory() -> str:
            return created.pop(0)

        composition, action_name = apply_composer_action(
            "object.set",
            "2022.1",
            composition,
            action,
            handle_factory=handle_factory,
        )
        facts = composition_projection(
            "object.set", "2022.1", composition
        )["current_facts"]
        broker._payloads_by_step[step.name] = {  # noqa: SLF001
            "draft": {
                "revision": revision,
                "current_facts_summary": {
                    "contract": (
                        "waapi-skill.operation-draft-facts-summary/v1"
                    ),
                    "target_count": len(facts),
                    "handle_count": len(
                        broker_module._draft_projection_handles(facts)  # noqa: SLF001
                    ),
                    "canonical_sha256": broker_module._sha256_bytes(  # noqa: SLF001
                        broker_module._canonical_json_bytes(facts)  # noqa: SLF001
                    ),
                },
                "action_result": {
                    "contract": (
                        "waapi-skill.operation-draft-action-result/v1"
                    ),
                    "action": action_name,
                    "created_handles": (
                        [handle] if action_name == "add_target" else []
                    ),
                    "affected_handles": (
                        [handle] if action_name == "set_property" else []
                    ),
                },
                "next_action_binding": _compact_next_action_binding(),
            }
        }
        broker._submitted_draft_actions_by_step = {  # noqa: SLF001
            step.name: (action,)
            for step, action in zip(actions, submitted_actions, strict=True)
        }

    replayed = broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    )

    assert replayed["arguments"]["objects"][0]["properties"][0]["value"] == 0.0


def test_draft_replay_is_scoped_to_the_preview_flow_in_multi_transaction_protocol(
    tmp_path: Path,
) -> None:
    object_set = _object_set_metadata_request()
    audio_import = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "import_operation": "createNew",
            "imports": [
                {
                    "audio_file": str(tmp_path / "雪.wav"),
                    "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\雪",
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                }
            ],
        },
    }
    object_steps = build_object_set_composer_transaction_steps(
        object_set,
        label="tx01",
    )
    audio_steps = build_audio_import_composer_transaction_steps(
        audio_import,
        label="tx02",
    )
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(*object_steps, *audio_steps),
        expected_wwise_version="2022.1",
    )
    preview = next(
        step for step in audio_steps if step.subcommand == "preview-from-draft"
    )

    expected_audio_witness = {
        **audio_import,
        "arguments": dict(audio_import["arguments"]),
    }
    expected_audio_witness["arguments"].pop("import_operation")
    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == expected_audio_witness


def test_raw_core_draft_replay_accepts_canonical_waapi_call_identity(
    tmp_path: Path,
) -> None:
    steps = build_core_business_transaction_steps(
        api="ak.wwise.core.project.save",
        version="2025.1",
        label="tx01",
    )
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    expected = preview.expected_operation_request
    assert expected is not None
    broker = CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=steps,
        expected_wwise_version="2025.1",
        runner_environment={},
        offline_replay_preview_requests={preview.name: expected},
    )

    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == expected


def test_raw_core_durable_replay_selects_the_exact_api_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps = build_core_business_transaction_steps(
        api="ak.wwise.core.project.save",
        version="2025.1",
        label="tx01",
    )
    start = next(step for step in steps if step.subcommand == "draft-start")
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    expected = preview.expected_operation_request
    assert expected is not None
    skill = make_fake_skill(tmp_path)
    (skill / "wwise_waapi").mkdir()
    state = tmp_path / "state"
    state.mkdir()
    selected: list[str] = []
    session = SimpleNamespace(
        handles=SimpleNamespace(as_dict=lambda: {"objects": []})
    )
    monkeypatch.setattr(
        broker_module,
        "OperationDraftStore",
        lambda _state: SimpleNamespace(
            inspect=lambda *_args, **_kwargs: SimpleNamespace(
                composition={"business_session": {}}
            )
        ),
    )
    monkeypatch.setattr(
        broker_module.BusinessDeclarationSession,
        "from_dict",
        lambda _value: session,
    )

    def select_adapter(operation: str) -> SimpleNamespace:
        selected.append(operation)
        return SimpleNamespace(
            supports_cleaned_file_evidence=False,
            materialize=lambda *_args, **_kwargs: expected,
        )

    monkeypatch.setattr(broker_module, "business_adapter", select_adapter)
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2025.1",
    )
    broker._state_directory = state  # noqa: SLF001
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "2" * 40,
        "draft": {"draft_id": "od1-" + "1" * 32},
    }

    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == expected
    assert selected == ["ak.wwise.core.project.save"]


def test_object_set_durable_replay_accepts_bound_ids_and_omitted_fail_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _two_target_object_set_request()
    steps = build_object_graph_business_transaction_steps(
        request,
        label="tx01",
    )
    start = next(step for step in steps if step.subcommand == "draft-start")
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    paths = tuple(
        row["object"]["value"] for row in request["arguments"]["objects"]
    )
    ids = (
        "{11111111-1111-1111-1111-111111111111}",
        "{22222222-2222-2222-2222-222222222222}",
    )
    replayed = json.loads(json.dumps(request))
    replayed["arguments"].pop("on_name_conflict")
    for row, object_id in zip(
        replayed["arguments"]["objects"],
        ids,
        strict=True,
    ):
        row["object"] = {"kind": "id", "value": object_id}
    session = SimpleNamespace(
        handles=SimpleNamespace(
            as_dict=lambda: {
                "objects": [
                    {
                        "path": path,
                        "object_id": object_id,
                        "object_type": "ActorMixer",
                        "name": path.rsplit("\\", 1)[-1],
                    }
                    for path, object_id in zip(paths, ids, strict=True)
                ]
            }
        )
    )
    skill = make_fake_skill(tmp_path)
    (skill / "wwise_waapi").mkdir()
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(
        broker_module,
        "OperationDraftStore",
        lambda _state: SimpleNamespace(
            inspect=lambda *_args, **_kwargs: SimpleNamespace(
                composition={"business_session": {}}
            )
        ),
    )
    monkeypatch.setattr(
        broker_module.BusinessDeclarationSession,
        "from_dict",
        lambda _value: session,
    )
    monkeypatch.setattr(
        broker_module,
        "business_adapter",
        lambda _operation: SimpleNamespace(
            supports_cleaned_file_evidence=False,
            materialize=lambda *_args, **_kwargs: replayed,
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    broker._state_directory = state  # noqa: SLF001
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "2" * 40,
        "draft": {"draft_id": "od1-" + "1" * 32},
    }

    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == replayed


def test_dynamic_soundengine_request_replays_its_durable_business_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps = build_soundengine_business_transaction_steps(
        version="2022.1",
        label="tx01",
        operation="ak.soundengine.registerGameObj",
        game_object_name="Fresh Weather Listener",
    )
    start = next(step for step in steps if step.subcommand == "draft-start")
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    assert preview.expected_operation_request is None
    skill = make_fake_skill(tmp_path)
    (skill / "wwise_waapi").mkdir()
    state = tmp_path / "state"
    state.mkdir()
    dynamic_request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.soundengine.registerGameObj",
            "args": {
                "gameObject": 4092176131199699083,
                "name": "Fresh Weather Listener",
            },
            "options": {},
        },
    }
    session = SimpleNamespace()
    monkeypatch.setattr(
        broker_module,
        "OperationDraftStore",
        lambda _state: SimpleNamespace(
            inspect=lambda *_args, **_kwargs: SimpleNamespace(
                composition={"business_session": {}}
            )
        ),
    )
    monkeypatch.setattr(
        broker_module.BusinessDeclarationSession,
        "from_dict",
        lambda _value: session,
    )
    selected: list[str] = []

    def select_adapter(operation: str) -> SimpleNamespace:
        selected.append(operation)
        return SimpleNamespace(
            supports_cleaned_file_evidence=False,
            materialize=lambda *_args, **_kwargs: dynamic_request,
        )

    monkeypatch.setattr(broker_module, "business_adapter", select_adapter)
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2022.1",
    )
    broker._state_directory = state  # noqa: SLF001
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "2" * 40,
        "draft": {
            "draft_id": "od1-" + "1" * 32,
            "binding": {"version": "2022.1"},
        },
    }

    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == dynamic_request
    assert selected == ["ak.soundengine.registerGameObj"]


def test_sealed_business_draft_replay_survives_successful_media_cleanup(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "import_operation": "createNew",
            "imports": [
                {
                    "audio_file": str(media),
                    "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                }
            ],
        },
    }
    steps = build_audio_import_composer_transaction_steps(request, label="tx01")
    start = next(step for step in steps if step.subcommand == "draft-start")
    preview = next(
        step for step in steps if step.subcommand == "preview-from-draft"
    )
    expected = preview.expected_operation_request
    assert expected is not None
    expected = dict(expected)
    media.unlink()
    broker = CodexGatewayBroker(
        skill_source=Path(__file__).resolve().parents[2] / "skills" / "waapi-skill",
        expected_steps=steps,
        expected_wwise_version="2022.1",
        runner_environment={},
        offline_replay_preview_requests={preview.name: expected},
    )
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "2" * 40,
        "draft": {"draft_id": "od1-" + "1" * 32},
    }

    assert broker._replay_expected_operation_draft_request(  # noqa: SLF001
        preview
    ) == expected


def test_broker_rejects_stale_draft_revision_before_runner_dispatch(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "draft.target",
            "draft-apply",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.start", "/draft/revision"),
                "--compact",
                "--facts",
                DraftTypedActionArgument(
                    {
                        "contract": "waapi-skill.operation-draft-action/v1",
                        "action": "add_target",
                        "selector": {"kind": "id", "value": 1},
                    }
                ),
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        started_result = run_model_command(broker, ["draft-start", "object.set"])
        started = json.loads(started_result.stdout[started_result.stdout.index("{") :])
        rejected = run_model_command(
            broker,
            [
                "draft-apply",
                started["draft"]["draft_id"],
                "--task-authority",
                started["task_authority"],
                "--expected-revision",
                "2",
                "--compact",
                "--facts",
                *typed_action_cli_arguments(steps[1].arguments[-1].expected),
            ],
        )

        assert started_result.returncode == 0
        assert rejected.returncode == 126
        assert "does not match draft.start/draft/revision" in rejected.stderr
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert len(calls) == 1


def test_broker_rejects_gateway_draft_binding_drift(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ),
        expected_wwise_version="2022.1",
        runner_environment={
            **os.environ,
            "FAKE_GATEWAY_MODE": "draft-wrong-binding",
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["draft-start", "object.set"])

        assert result.returncode == 125
        assert "operation does not match draft-start" in result.stderr
        evidence = broker.evidence()
        assert evidence.terminal_state == "FAILED"
        assert evidence.consumed_step_names == ()


def test_broker_does_not_replace_wrong_typed_draft_business_values(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    action_contract = "waapi-skill.operation-draft-action/v1"
    expected_notes = "release-ready | close"
    steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "draft.target",
            "draft-apply",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.start", "/draft/revision"),
                "--compact",
                "--facts",
                DraftTypedActionArgument(
                    {
                        "contract": action_contract,
                        "action": "add_target",
                        "selector": {"kind": "id", "value": 1},
                    }
                ),
            ),
        ),
        ExpectedGatewayStep(
            "draft.notes",
            "draft-apply",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.target", "/draft/revision"),
                "--compact",
                "--facts",
                DraftTypedActionArgument(
                    {
                        "contract": action_contract,
                        "action": "set_target_field",
                        "name": "notes",
                        "value": expected_notes,
                    },
                    response_bindings=(
                        DraftActionResponseBinding(
                            "/target_handle",
                            "draft.target",
                            "/draft/current_facts/0/handle",
                        ),
                    ),
                ),
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        started_result = run_model_command(broker, ["draft-start", "object.set"])
        started = json.loads(started_result.stdout[started_result.stdout.index("{") :])
        target_result = run_model_command(
            broker,
            [
                "draft-apply",
                started["draft"]["draft_id"],
                "--task-authority",
                started["task_authority"],
                "--expected-revision",
                "1",
                "--compact",
                "--facts",
                *typed_action_cli_arguments(steps[1].arguments[-1].expected),
            ],
        )
        targeted = json.loads(target_result.stdout[target_result.stdout.index("{") :])
        wrong_action = {
            **steps[2].arguments[-1].expected,
            "target_handle": targeted["draft"]["current_facts"][0]["handle"],
            "value": "release-ready | wrong",
        }
        rejected = run_model_command(
            broker,
            [
                "draft-apply",
                started["draft"]["draft_id"],
                "--task-authority",
                started["task_authority"],
                "--expected-revision",
                "2",
                "--compact",
                "--facts",
                *typed_action_cli_arguments(wrong_action),
            ],
        )

        assert started_result.returncode == 0
        assert target_result.returncode == 0
        assert rejected.returncode == 126
        assert "not exactly equal to its business facts" in rejected.stderr
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert len(calls) == 2


def test_broker_binds_draft_inspect_and_cancel_to_start_authority(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "draft.inspect",
            "draft-inspect",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
            ),
        ),
        ExpectedGatewayStep(
            "draft.cancel",
            "draft-cancel",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.inspect", "/draft/revision"),
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        started_result = run_model_command(broker, ["draft-start", "object.set"])
        started = json.loads(started_result.stdout[started_result.stdout.index("{") :])
        inspected_result = run_model_command(
            broker,
            [
                "draft-inspect",
                started["draft"]["draft_id"],
                "--task-authority",
                started["task_authority"],
            ],
        )
        cancelled_result = run_model_command(
            broker,
            [
                "draft-cancel",
                started["draft"]["draft_id"],
                "--task-authority",
                started["task_authority"],
                "--expected-revision",
                "1",
            ],
        )

        assert [
            started_result.returncode,
            inspected_result.returncode,
            cancelled_result.returncode,
        ] == [0, 0, 0]
        cancelled = json.loads(
            cancelled_result.stdout[cancelled_result.stdout.index("{") :]
        )
        assert cancelled["draft"]["lifecycle_state"] == "cancelled"
        assert broker.evidence().complete is True


def test_typed_draft_protocol_rejects_prefilled_handles_and_json_bypass(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="model-authored handle"):
        DraftTypedActionArgument(
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                "action": "set_property",
                "target_handle": "odh1-guessed",
                "name": "Volume",
                "value": -3,
            }
        )
    with pytest.raises(ValueError, match="complete request"):
        DraftTypedActionArgument(
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                "action": "set_property",
                "request": {"operation": "object.set"},
            }
        )

    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "raw.preview",
            "preview",
            ("--request-json", SemanticJsonArgument({"operation": "object.set"})),
        ),
    )
    with pytest.raises(ValueError, match="same operation"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=steps,
            transport="tcp",
        )

    mixed_steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "legacy.import",
            "preview",
            (
                "--request-json",
                SemanticJsonArgument({"operation": "audio.import"}),
            ),
        ),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=mixed_steps,
        transport="tcp",
    ):
        pass

    terminal_steps = (
        ExpectedGatewayStep("draft.start", "draft-start", ("object.set",)),
        ExpectedGatewayStep(
            "draft.cancel",
            "draft-cancel",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
                "--expected-revision",
                ResponseBinding("draft.start", "/draft/revision"),
            ),
        ),
        ExpectedGatewayStep(
            "draft.inspect-after-cancel",
            "draft-inspect",
            (
                ResponseBinding("draft.start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding("draft.start", "/task_authority"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="follow its terminal command"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=terminal_steps,
            transport="tcp",
        )


def test_broker_accepts_non_awaiting_status_show_without_confirmation(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "object.setNotes", "value": "status-only"}
    steps = (
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "status-show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "status-show-confirmed",
        },
    ) as broker:
        preview = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(request, separators=(",", ":"))],
        )
        assert preview.returncode == 0

        shown_result = run_model_command(
            broker,
            ["transaction-show", "tx-dynamic-123", "--summary-only"],
        )

        assert shown_result.returncode == 0
        shown = json.loads(
            shown_result.stdout[shown_result.stdout.index("{") :]
        )
        assert shown["command"] == "transaction-show"
        assert shown["state"] == "confirmed"
        assert shown["status"] == "ok"
        assert "confirmation" not in shown
        assert "next_command" not in shown
        assert broker.evidence().passed is True


def test_broker_accepts_model_visible_skill_copy_but_executes_candidate(
    tmp_path: Path,
) -> None:
    candidate = make_fake_skill(tmp_path / "candidate")
    invocation = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    invocation_runner = invocation / "scripts" / "run.py"
    invocation_runner.parent.mkdir(parents=True)
    invocation_runner.write_text(
        'raise RuntimeError("writable invocation copy must never execute")\n',
        encoding="utf-8",
    )
    steps = (
        ExpectedGatewayStep("copy-path", "status"),
        ExpectedGatewayStep("candidate-path", "status"),
    )

    with CodexGatewayBroker(
        skill_source=candidate,
        invocation_skill_source=invocation,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        from_copy = run_model_command(broker, ["status"])
        from_candidate = run_model_command(
            broker,
            ["status"],
            runner_path=broker.runner_path,
        )

        assert from_copy.returncode == 0
        assert from_candidate.returncode == 0
        records = broker.evidence().records
        assert [record.normalized_model_argv[1] for record in records] == [
            str(invocation_runner),
            str(broker.runner_path),
        ]
        observed = (
            ("python", str(invocation_runner), "gateway.py", "status"),
            ("python", str(broker.runner_path), "gateway.py", "status"),
        )
        assert broker.reconcile(observed).passed is True
        calls = (
            broker.state_directory / "fake-runner-calls.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        assert len(calls) == 2


def test_query_object_accepts_a_permutation_of_unique_return_fields(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected_arguments = (
        "--path",
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
        "--select",
        "descendants",
        "--take",
        "24",
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
        "--return-field",
        "parent",
        "--return-field",
        "audioSource:language",
        "--return-field",
        "@Volume",
        "--return-field",
        "notes",
    )
    supplied_arguments = (
        *expected_arguments[:7],
        "path",
        "--return-field",
        "parent",
        "--return-field",
        "@Volume",
        "--return-field",
        "id",
        "--return-field",
        "notes",
        "--return-field",
        "type",
        "--return-field",
        "audioSource:language",
        "--return-field",
        "name",
    )
    step = ExpectedGatewayStep(
        "query-object",
        "query-object",
        expected_arguments,
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["query-object", *supplied_arguments],
        )

        assert result.returncode == 0
        assert broker.evidence().passed is True


def test_query_object_accepts_gateway_owned_default_identity_projection(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "query-object",
        "query-object",
        (
            "--path",
            r"\Events\Default Work Unit\IntegrationLab\Alarm\Play_Generator_Alarm",
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            [
                "query-object",
                "--path-segment",
                "Events",
                "--path-segment",
                "Default Work Unit",
                "--path-segment",
                "IntegrationLab",
                "--path-segment",
                "Alarm",
                "--path-segment",
                "Play_Generator_Alarm",
            ],
        )

        assert result.returncode == 0
        assert broker.evidence().passed is True


def test_query_object_does_not_omit_a_custom_projection(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "query-object",
        "query-object",
        (
            "--path",
            r"\Events\Default Work Unit\Play",
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "notes",
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            [
                "query-object",
                "--path-segment",
                "Events",
                "--path-segment",
                "Default Work Unit",
                "--path-segment",
                "Play",
            ],
        )

        assert result.returncode == 126
        assert "expected step 'query-object'" in result.stderr
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_query_object_event_actions_preset_expands_to_sealed_action_hop() -> None:
    event_id = "{11111111-1111-1111-1111-111111111111}"
    tail = (
        "--select",
        "children",
        "--take",
        "100",
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
        "--return-field",
        "ActionType",
        "--return-field",
        "Target",
    )
    step = ExpectedGatewayStep(
        "diag.action",
        "query-object",
        (
            ExactArgumentAlternatives(("--object-id", "--path")),
            ResponseBindingOrExactArgument(
                ResponseBinding("diag.event", "/objects/0/id"),
                (r"\Events\Default Work Unit\Play_Rain",),
            ),
            *tail,
        ),
    )

    normalized = broker_module._normalize_query_object_event_actions(  # noqa: SLF001
        step,
        ("--exact-id", event_id, "--relationship", "event-actions"),
    )

    assert normalized == ("--object-id", event_id, *tail)
    incomplete = (
        "--exact-id",
        event_id,
        "--relationship",
        "children",
        "--include",
        "target",
    )
    assert broker_module._normalize_query_object_event_actions(  # noqa: SLF001
        step,
        incomplete,
    ) == incomplete


def test_sound_routing_view_expands_to_complete_legacy_projection() -> None:
    sound_id = "{33333333-3333-3333-3333-333333333333}"
    tail = (
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
        "--return-field",
        "OverrideOutput",
        "--return-field",
        "activeSource",
        "--return-field",
        "OutputBus",
    )
    step = ExpectedGatewayStep(
        "diag.sound",
        "query-object",
        (
            "--object-id",
            ResponseBinding("diag.action", "/objects/0/target/id"),
            *tail,
        ),
    )

    normalized = broker_module._normalize_query_object_sound_routing_view(  # noqa: SLF001
        step,
        ("--exact-id", sound_id, "--view", "sound-routing-diagnostics"),
    )

    assert normalized == ("--object-id", sound_id, *tail)
    partial = ("--exact-id", sound_id, "--include", "output-bus")
    assert broker_module._normalize_query_object_sound_routing_view(  # noqa: SLF001
        step,
        partial,
    ) == partial


@pytest.mark.parametrize(
    ("fields", "includes"),
    (
        (
            (
                "id",
                "name",
                "type",
                "path",
                "originalFilePath",
                "audioSource:language",
            ),
            ("source-language", "original-file-path"),
        ),
        (
            ("id", "name", "type", "path", "@Volume"),
            ("volume-db",),
        ),
    ),
)
def test_business_query_includes_expand_to_complete_legacy_projection(
    fields: tuple[str, ...],
    includes: tuple[str, ...],
) -> None:
    object_id = "{33333333-3333-3333-3333-333333333333}"
    tail = tuple(
        item
        for field in fields
        for item in ("--return-field", field)
    )
    step = ExpectedGatewayStep(
        "diag.business",
        "query-object",
        ("--object-id", ResponseBinding("prior", "/objects/0/id"), *tail),
    )
    actual = (
        "--exact-id",
        object_id,
        *(item for include in includes for item in ("--include", include)),
    )

    normalized = broker_module._normalize_query_object_business_projection(  # noqa: SLF001
        step,
        actual,
    )

    assert normalized == ("--object-id", object_id, *tail)


def test_business_query_path_segments_expand_to_complete_legacy_projection() -> None:
    path = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\SFX_Machinery"
    tail = tuple(
        item
        for field in ("id", "name", "type", "path", "@Volume")
        for item in ("--return-field", field)
    )
    step = ExpectedGatewayStep(
        "diag.target_bus",
        "query-object",
        ("--path", path, *tail),
    )
    actual = (
        "--path-segment",
        "Master-Mixer Hierarchy",
        "--path-segment",
        "Default Work Unit",
        "--path-segment",
        "Master Audio Bus",
        "--path-segment",
        "SFX_Machinery",
        "--include",
        "volume-db",
    )

    normalized = broker_module._normalize_query_object_business_projection(  # noqa: SLF001
        step,
        actual,
    )

    assert normalized == ("--path", path, *tail)


def test_event_action_draft_binding_expands_to_direct_child_selector() -> None:
    fixed = (
        "od1-" + "1" * 32,
        "--task-authority",
        "da1-" + "2" * 40,
        "--expected-revision",
        "1",
    )
    expected_tail = (
        "--direct-child-type",
        "Action",
        "--parent-path-segment",
        "Events",
        "--parent-path-segment",
        "Default Work Unit",
        "--parent-path-segment",
        "Play_Rain",
    )
    step = ExpectedGatewayStep(
        "tx01.bind-action",
        "draft-bind-object",
        (*fixed, *expected_tail),
    )
    supplied = (
        *fixed,
        "--event-action-of-path-segment",
        "Events",
        "--event-action-of-path-segment",
        "Default Work Unit",
        "--event-action-of-path-segment",
        "Play_Rain",
    )

    assert broker_module._normalize_event_action_draft_binding(  # noqa: SLF001
        step,
        supplied,
    ) == step.arguments


@pytest.mark.parametrize(
    ("supplied_arguments", "error_fragment"),
    (
        (
            (
                "--path",
                r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
                "--take",
                "24",
                "--return-field",
                "id",
                "--return-field",
                "id",
                "--return-field",
                "type",
            ),
            "must not contain duplicates",
        ),
        (
            (
                "--path",
                r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
                "--take",
                "24",
                "--return-field",
                "id",
                "--return-field",
                "",
                "--return-field",
                "type",
            ),
            "must be non-empty strings",
        ),
        (
            (
                "--path",
                r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
                "--take",
                "24",
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "notes",
            ),
            "set must match",
        ),
        (
            (
                "--path",
                r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
                "--take",
                "25",
                "--return-field",
                "type",
                "--return-field",
                "id",
                "--return-field",
                "name",
            ),
            "must be exactly '24'",
        ),
    ),
)
def test_query_object_return_field_equivalence_remains_closed(
    tmp_path: Path,
    supplied_arguments: tuple[str, ...],
    error_fragment: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "query-object",
        "query-object",
        (
            "--path",
            r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
            "--take",
            "24",
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["query-object", *supplied_arguments],
        )

        assert result.returncode == 126
        assert error_fragment in result.stderr
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_return_field_order_remains_exact_for_non_query_object_steps(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "call",
        "call",
        (
            "ak.wwise.test",
            "--return-field",
            "id",
            "--return-field",
            "name",
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            [
                "call",
                "ak.wwise.test",
                "--return-field",
                "name",
                "--return-field",
                "id",
            ],
        )

        assert result.returncode == 126
        assert "argument 2 must be exactly 'id'" in result.stderr
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_broker_keeps_json_number_wire_types_exact_before_execution(
    tmp_path: Path,
) -> None:
    """The real Media Pool endpoint can distinguish integer and float values."""

    skill = make_fake_skill(tmp_path)
    expected = {
        "filters": [
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "lessThanOrEqual",
                "value": 8.0,
            }
        ],
        "maxResults": 40,
    }
    observed = {
        **expected,
        "filters": [{**expected["filters"][0], "value": 8}],
    }
    step = ExpectedGatewayStep(
        "media.get",
        "preview",
        ("--request-json", SemanticJsonArgument(expected)),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(observed)],
        )

        assert result.returncode == 126
        assert "not semantically equal" in result.stderr
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def _soundbank_generate_request() -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [
                {
                    "name": "Main_UI",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                },
                {
                    "name": "Gameplay",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                },
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": "/owned",
            "rebuild_soundbanks": False,
            "clear_audio_file_cache": False,
            "rebuild_init_bank": False,
        },
    }


def _dependency_free_rebatch_request(io_root: str) -> dict[str, object]:
    del io_root
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "ui.commands.unregister",
        "arguments": {
            "command_ids": [
                f"example.command{index}"
                for index in range(10)
            ],
            "acknowledgement": (
                "unregister_existing_commands_without_definition"
            ),
        },
    }


def _dependency_free_rebatch_protocol(io_root: str):
    """Build two adjacent public Composer batches with no response handles."""

    return build_transaction_protocol(
        (_dependency_free_rebatch_request(io_root),)
    )


def _without_soundbank_generate_false_defaults(
    request: dict[str, object],
) -> dict[str, object]:
    result = json.loads(json.dumps(request))
    arguments = result["arguments"]
    for field in (
        "rebuild_soundbanks",
        "clear_audio_file_cache",
        "rebuild_init_bank",
    ):
        arguments.pop(field)
    for row in arguments["soundbanks"]:
        row.pop("rebuild")
    return result


def _soundbank_generate_broker_step(
    expected: dict[str, object],
) -> ExpectedGatewayStep:
    return ExpectedGatewayStep(
        "preview",
        "preview",
        (
            "--request-json",
            SemanticJsonArgument(
                expected,
                equivalence="soundbank_generate_v1",
            ),
        ),
    )


@pytest.mark.parametrize("expected_has_defaults", (False, True))
def test_soundbank_generate_equivalence_accepts_false_defaults_bidirectionally(
    tmp_path: Path,
    expected_has_defaults: bool,
) -> None:
    explicit = _soundbank_generate_request()
    omitted = _without_soundbank_generate_false_defaults(explicit)
    expected, actual = (
        (explicit, omitted)
        if expected_has_defaults
        else (omitted, explicit)
    )
    step = _soundbank_generate_broker_step(expected)
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(step,),
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        step,
        (
            "preview",
            "--request-json",
            json.dumps(actual, separators=(",", ":")),
        ),
    )

    assert len(semantic_hash) == 64
    assert execution_arguments[0] == "preview"


def test_soundbank_generate_equivalence_preserves_mixed_per_bank_values(
    tmp_path: Path,
) -> None:
    expected = _soundbank_generate_request()
    expected["arguments"]["soundbanks"][0]["rebuild"] = True
    actual = _without_soundbank_generate_false_defaults(expected)
    actual["arguments"]["soundbanks"][0]["rebuild"] = True
    step = _soundbank_generate_broker_step(expected)
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(step,),
    )

    broker._validate_step(  # noqa: SLF001
        step,
        (
            "preview",
            "--request-json",
            json.dumps(actual, separators=(",", ":")),
        ),
    )


@pytest.mark.parametrize(
    "difference",
    (
        "omit-true-row",
        "move-row-true-to-root",
        "row-int-zero",
        "root-string-false",
        "different-platform",
        "different-bank-order",
        "unknown-field",
    ),
)
def test_soundbank_generate_equivalence_rejects_every_other_difference(
    tmp_path: Path,
    difference: str,
) -> None:
    expected = _soundbank_generate_request()
    expected["arguments"]["soundbanks"][0]["rebuild"] = True
    actual = json.loads(json.dumps(expected))
    arguments = actual["arguments"]
    if difference == "omit-true-row":
        arguments["soundbanks"][0].pop("rebuild")
    elif difference == "move-row-true-to-root":
        arguments["soundbanks"][0].pop("rebuild")
        arguments["rebuild_soundbanks"] = True
    elif difference == "row-int-zero":
        arguments["soundbanks"][1]["rebuild"] = 0
    elif difference == "root-string-false":
        arguments["clear_audio_file_cache"] = "false"
    elif difference == "different-platform":
        arguments["platforms"] = ["Mac"]
    elif difference == "different-bank-order":
        arguments["soundbanks"].reverse()
    else:
        arguments["unreviewed"] = False
    step = _soundbank_generate_broker_step(expected)
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(step,),
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            step,
            (
                "preview",
                "--request-json",
                json.dumps(actual, separators=(",", ":")),
            ),
        )


def test_soundbank_generate_equivalence_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    expected = _soundbank_generate_request()
    serialized = json.dumps(expected, separators=(",", ":"))
    duplicate = serialized.replace(
        '"rebuild":false',
        '"rebuild":false,"rebuild":false',
        1,
    )
    step = _soundbank_generate_broker_step(expected)
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(step,),
    )

    with pytest.raises(GatewayInvocationError, match="duplicate JSON"):
        broker._validate_step(  # noqa: SLF001
            step,
            ("preview", "--request-json", duplicate),
        )


@pytest.mark.parametrize(
    "observed_arguments",
    (
        {
            "parent": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
            "type": "ActorMixer",
            "name": "Player_Foley",
            "properties": [{"name": "Volume", "value": -2.0}],
            "on_name_conflict": "fail",
        },
        {
            "parent": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
            "type": "ActorMixer",
            "name": "Player_Foley",
            "properties": [{"name": "Volume", "value": -2.0}],
        },
        {
            "parent": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
            "type": "ActorMixer",
            "name": "Player_Foley",
            "properties": [{"name": "Volume", "value": -2}],
            "on_name_conflict": "fail",
        },
        {
            "parent": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
            "type": "ActorMixer",
            "name": "Player_Foley",
            "properties": [{"name": "Volume", "value": -2}],
            "children": [],
        },
    ),
)
def test_broker_accepts_only_closed_object_operation_equivalences(
    tmp_path: Path,
    observed_arguments: dict[str, object],
) -> None:
    skill = make_fake_skill(tmp_path)
    expected_arguments = {
        "parent": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
        "type": "ActorMixer",
        "name": "Player_Foley",
        "properties": [{"name": "Volume", "value": -2.0}],
        "on_name_conflict": "fail",
    }
    expected = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.create",
        "arguments": expected_arguments,
    }
    observed = {**expected, "arguments": observed_arguments}
    step = ExpectedGatewayStep(
        "preview",
        "preview",
        (
            "--request-json",
            SemanticJsonArgument(expected, equivalence="object_operation_v1"),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(observed)],
        )

        assert result.returncode == 0
        assert broker.evidence().passed


def test_object_operation_equivalence_accepts_integral_float_for_reviewed_pitch_int(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit\Target"},
                    "properties": [{"name": "Pitch", "value": 100}],
                }
            ],
            "on_name_conflict": "fail",
        },
    }
    observed = json.loads(json.dumps(expected))
    observed["arguments"]["objects"][0]["properties"][0]["value"] = 100.0
    observed["arguments"].pop("on_name_conflict")
    step = ExpectedGatewayStep(
        "preview",
        "preview",
        (
            "--request-json",
            SemanticJsonArgument(expected, equivalence="object_operation_v1"),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(observed)],
        )

        assert result.returncode == 0
        assert broker.evidence().passed


@pytest.mark.parametrize(
    "mutation",
    ("wrong_value", "boolean_value", "extra_field", "omit_nondefault_conflict"),
)
def test_broker_rejects_values_outside_closed_object_operation_equivalence(
    tmp_path: Path,
    mutation: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    arguments = {
        "objects": [
            {
                "object": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit\Target"},
                "properties": [{"name": "Volume", "value": -2.0}],
            }
        ],
        "on_name_conflict": "merge",
    }
    observed_arguments = json.loads(json.dumps(arguments))
    if mutation == "wrong_value":
        observed_arguments["objects"][0]["properties"][0]["value"] = -3
    elif mutation == "boolean_value":
        observed_arguments["objects"][0]["properties"][0]["value"] = True
    elif mutation == "extra_field":
        observed_arguments["objects"][0]["unreviewed"] = True
    else:
        observed_arguments.pop("on_name_conflict")
    expected = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": arguments,
    }
    observed = {**expected, "arguments": observed_arguments}
    step = ExpectedGatewayStep(
        "preview",
        "preview",
        (
            "--request-json",
            SemanticJsonArgument(expected, equivalence="object_operation_v1"),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(observed)],
        )

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"


def test_broker_reconciles_only_an_exact_running_prefix_then_full_completion(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "object.setNotes", "arguments": {"value": "prefix"}}
    steps = (
        ExpectedGatewayStep("schema", "operation-schema", ("object.setNotes",)),
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("show", "/transaction_id"),
                "--confirmation-token",
                ResponseBinding("show", "/confirmation/token"),
            ),
        ),
    )
    observed = [
        ["python", str(skill / "scripts" / "run.py"), "gateway.py", "operation-schema", "object.setNotes"],
        [
            "python",
            str(skill / "scripts" / "run.py"),
            "gateway.py",
            "preview",
            "--request-json",
            json.dumps(request),
        ],
        [
            "python",
            str(skill / "scripts" / "run.py"),
            "gateway.py",
            "transaction-show",
            "tx-dynamic-123",
            "--summary-only",
        ],
        [
            "python",
            str(skill / "scripts" / "run.py"),
            "gateway.py",
            "confirm",
            "tx-dynamic-123",
            "--confirmation-token",
            fake_confirmation_token("tx-dynamic-123"),
        ],
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, observed[0][3:]).returncode == 0
        assert run_model_command(broker, observed[1][3:]).returncode == 0

        evidence = broker.evidence()
        checkpoint = broker.reconcile_prefix(observed[:2], expected_step_count=2)
        standalone = reconcile_gateway_command_prefix(
            observed[:2],
            evidence,
            expected_step_count=2,
            skill_source=skill,
            shim_directory=broker.shim_directory,
        )
        assert evidence.terminal_state == "RUNNING"
        assert evidence.complete is False
        assert checkpoint.passed is True
        assert standalone.passed is True
        assert broker.reconcile(observed[:2]).passed is False
        assert broker.reconcile_prefix(observed[:1], expected_step_count=2).passed is False
        assert broker.reconcile_prefix(observed, expected_step_count=2).passed is False
        assert broker.reconcile_prefix(observed[:2], expected_step_count=1).passed is False
        with pytest.raises(ValueError, match="between 1 and 4"):
            broker.reconcile_prefix((), expected_step_count=0)
        with pytest.raises(ValueError, match="between 1 and 4"):
            broker.reconcile_prefix(observed, expected_step_count=5)
        with pytest.raises(ValueError, match="integer"):
            broker.reconcile_prefix(observed[:1], expected_step_count=True)  # type: ignore[arg-type]

        assert run_model_command(broker, observed[2][3:]).returncode == 0
        assert run_model_command(broker, observed[3][3:]).returncode == 0
        assert broker.reconcile_prefix(observed, expected_step_count=4).passed is True
        assert broker.reconcile(observed).passed is True
        assert broker.reconcile_prefix(observed[:2], expected_step_count=2).passed is False


def test_broker_prefix_checkpoint_rejects_terminal_rejection_record(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("schema", "operation-schema", ("object.setNotes",)),
            ExpectedGatewayStep("preview", "preview", ("--request-json", SemanticJsonArgument({}))),
        ),
        transport="tcp",
    ) as broker:
        wrong = ["python", str(broker.runner_path), "gateway.py", "buses"]
        assert run_model_command(broker, wrong[3:]).returncode == 126

        checkpoint = broker.reconcile_prefix((wrong,), expected_step_count=1)
        assert checkpoint.passed is False
        assert any("rejected" in error for error in checkpoint.errors)
        assert broker.evidence().terminal_state == "FAILED"


def test_broker_accepts_only_explicit_structured_gateway_exit_2_step(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "audio.importTabDelimited", "arguments": {"path": "fixture.tsv"}}
    step = ExpectedGatewayStep(
        "preview-error",
        "preview",
        ("--request-json", SemanticJsonArgument(request)),
        allowed_exit_codes=(2,),
        expected_error_code="PACKAGED_PREVIEW_UNAVAILABLE",
        expected_result_command="preview",
    )
    observed = [
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        "preview",
        "--request-json",
        json.dumps(request),
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "expected-error",
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, observed[3:])

        assert result.returncode == 2
        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.complete is True
        assert len(evidence.records) == 1
        record = evidence.records[0]
        assert record.succeeded is True
        assert record.exit_code == 2
        assert record.runner_exit_code == 2
        assert record.allowed_exit_codes == (2,)
        assert record.payload is not None
        assert record.payload["contract"] == "waapi-skill.gateway-result/v1"
        assert record.payload["ok"] is False
        assert record.payload["error_code"] == "PACKAGED_PREVIEW_UNAVAILABLE"
        assert record.payload["command"] == "preview"
        assert broker.reconcile((observed,)).passed is True


@pytest.mark.parametrize(
    ("mode", "expected_exit", "expected_ok", "expected_status"),
    (
        ("terminal-success", 0, True, "executed_unverified"),
        ("terminal-success-exit2", 2, True, "executed_unverified"),
        ("terminal-indeterminate", 2, False, "indeterminate"),
    ),
)
def test_broker_accepts_only_closed_terminal_execute_shapes(
    tmp_path: Path,
    mode: str,
    expected_exit: int,
    expected_ok: bool,
    expected_status: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "migrate.execute",
        "execute",
        ("tx-migrate",),
        allowed_exit_codes=(0, 2),
        terminal_execute=True,
    )
    observed = [
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        "execute",
        "tx-migrate",
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": mode,
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, observed[3:])
        evidence = broker.evidence()

    assert result.returncode == expected_exit
    assert evidence.passed is True
    assert evidence.records[0].runner_exit_code == expected_exit
    assert evidence.records[0].payload is not None
    assert evidence.records[0].payload["ok"] is expected_ok
    assert evidence.records[0].payload["status"] == expected_status


def test_ordinary_execute_success_still_requires_the_allow_listed_verify(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep(
            "execute",
            "execute",
            ("tx",),
            allowed_exit_codes=(0, 2),
        ),
        ExpectedGatewayStep("verify", "verify", ("tx",)),
    )
    execute_argv = [
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        "execute",
        "tx",
    ]
    verify_argv = [
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        "verify",
        "tx",
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "terminal-success",
        },
        transport="tcp",
    ) as broker:
        execute = run_model_command(broker, ["execute", "tx"])
        checkpoint = broker.evidence()

        assert execute.returncode == 0
        assert checkpoint.terminal_state == "RUNNING"
        assert checkpoint.complete is False
        assert checkpoint.terminal_indeterminate is False
        assert broker.reconcile_prefix(
            (execute_argv,), expected_step_count=1
        ).passed is True

        verify = run_model_command(broker, ["verify", "tx"])
        assert verify.returncode == 0
        assert broker.evidence().passed is True
        assert broker.reconcile((execute_argv, verify_argv)).passed is True


def test_ordinary_execute_exact_indeterminate_is_a_terminal_nonpassing_prefix(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    execute_argv = [
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        "execute",
        "tx",
    ]
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "execute",
                "execute",
                ("tx",),
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep("verify", "verify", ("tx",)),
        ),
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "terminal-indeterminate",
        },
        transport="tcp",
    ) as broker:
        execute = run_model_command(broker, ["execute", "tx"])
        evidence = broker.evidence()

        assert execute.returncode == 2
        assert evidence.terminal_state == "INDETERMINATE"
        assert evidence.complete is False
        assert evidence.passed is False
        assert evidence.terminal_indeterminate is True
        assert evidence.consumed_step_names == ("execute",)
        assert evidence.records[0].succeeded is True
        assert broker.reconcile_prefix(
            (execute_argv,), expected_step_count=1
        ).passed is True

        rejected = run_model_command(broker, ["verify", "tx"])
        assert rejected.returncode == 126
        assert "terminal INDETERMINATE" in rejected.stderr
        assert broker.evidence().terminal_state == "FAILED"


def test_exact_indeterminate_execute_survives_trusted_observer_without_rewrite(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    observed: list[tuple[str, dict[str, object]]] = []

    def observer(step, payload, _state_directory, _evidence_directory) -> None:
        observed.append((step.name, dict(payload)))

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "execute",
                "execute",
                ("tx",),
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep("verify", "verify", ("tx",)),
        ),
        trusted_step_observer=observer,
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "terminal-indeterminate",
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["execute", "tx"])
        evidence = broker.evidence()
        record = evidence.records[0]

        assert result.returncode == 2
        assert evidence.terminal_state == "INDETERMINATE"
        assert evidence.terminal_indeterminate is True
        assert evidence.consumed_step_names == ("execute",)
        assert record.succeeded is True
        assert record.runner_exit_code == 2
        assert record.exit_code == 2
        assert record.payload_error == ""
        assert observed == [("execute", dict(record.payload or {}))]


def test_ordinary_execute_rejects_non_exact_exit_two_error(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "execute",
                "execute",
                ("tx",),
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep("verify", "verify", ("tx",)),
        ),
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "terminal-generic-error",
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["execute", "tx"])
        evidence = broker.evidence()

    assert result.returncode == 125
    assert "must be exactly non-retryable indeterminate" in result.stderr
    assert evidence.terminal_state == "FAILED"
    assert evidence.terminal_indeterminate is False
    assert evidence.records[0].succeeded is False


def test_broker_rejects_generic_exit_two_as_terminal_execute(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "migrate.execute",
        "execute",
        ("tx-migrate",),
        allowed_exit_codes=(0, 2),
        terminal_execute=True,
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "terminal-generic-error",
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["execute", "tx-migrate"])
        evidence = broker.evidence()

    assert result.returncode == 125
    assert evidence.passed is False
    assert "exactly indeterminate" in evidence.records[0].payload_error


@pytest.mark.parametrize(
    ("runner_overrides", "error_fragment"),
    (
        ({"FAKE_GATEWAY_ERROR_CODE": "WRONG"}, "error_code"),
        ({"FAKE_GATEWAY_ERROR_COMMAND": "execute"}, "command"),
        ({"FAKE_GATEWAY_ERROR_OK": "true"}, "ok"),
        ({"FAKE_GATEWAY_ERROR_CONTRACT": "forged/v1"}, "contract"),
        ({"FAKE_GATEWAY_ERROR_EXIT": "3"}, "runner exit"),
    ),
)
def test_broker_rejects_non_exact_or_arbitrary_nonzero_structured_error(
    tmp_path: Path,
    runner_overrides: dict[str, str],
    error_fragment: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "soundbank.processDefinitionFiles", "arguments": {}}
    runner_environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "FAKE_GATEWAY_MODE": "expected-error",
        **runner_overrides,
    }
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "preview-error",
                "preview",
                ("--request-json", SemanticJsonArgument(request)),
                allowed_exit_codes=(2,),
                expected_error_code="PACKAGED_PREVIEW_UNAVAILABLE",
                expected_result_command="preview",
            ),
        ),
        runner_environment=runner_environment,
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(request)],
        )

        assert result.returncode == 125
        evidence = broker.evidence()
        assert evidence.passed is False
        assert evidence.terminal_state == "FAILED"
        assert evidence.records[0].succeeded is False
        assert error_fragment in evidence.records[0].payload_error


@pytest.mark.parametrize(
    "selector",
    ((), ("--version", "2022.1"), ("--wwise-version=2022.1",)),
)
def test_broker_accepts_canonical_step_global_timeout_before_wait_topic(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.object.created"
    step = ExpectedGatewayStep(
        "wait-topic",
        "wait-topic",
        (
            topic,
            "--options-json",
            SemanticJsonArgument({"return": ["id", "name", "type", "path"]}),
            "--match-json",
            SemanticJsonArgument({"object": {"type": "ActorMixer"}}),
        ),
        gateway_global_arguments=("--timeout", "10"),
    )
    arguments = [
        *selector,
        "--timeout",
        "10",
        "wait-topic",
        topic,
        "--options-json",
        '{"return":["id","name","type","path"]}',
        "--match-json",
        '{"object":{"type":"ActorMixer"}}',
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, arguments)
        assert result.returncode == 0, result.stderr

        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.records[0].gateway_arguments == tuple(arguments)
        observed = [
            "python",
            str(broker.runner_path),
            "gateway.py",
            *arguments,
        ]
        resolved = resolve_gateway_invocation(observed, skill_source=skill)
        assert resolved.subcommand == "wait-topic"
        assert resolved.normalized_model_argv == tuple(observed)
        assert broker.reconcile((observed,)).passed is True

        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert json.loads(calls[0]) == ["gateway.py", *arguments[len(selector) :]]


@pytest.mark.parametrize(
    "arguments",
    (
        ("wait-topic", "ak.wwise.core.object.created"),
        ("--timeout", "9", "wait-topic", "ak.wwise.core.object.created"),
        ("--timeout=10", "wait-topic", "ak.wwise.core.object.created"),
        ("wait-topic", "--timeout", "10", "ak.wwise.core.object.created"),
    ),
)
def test_broker_rejects_noncanonical_wait_topic_timeout_prefix(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "wait-topic",
        "wait-topic",
        ("ak.wwise.core.object.created",),
        gateway_global_arguments=("--timeout", "10"),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, list(arguments))

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_empty_call_json_objects_accept_omission_and_explicit_pair_as_one_semantics(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    uri = "ak.wwise.waapi.getFunctions"
    variants = (
        (uri,),
        (uri, "--args-json", "{}", "--options-json", "{}"),
        (uri, "--args-json", "{ }", "--options-json", "{\n}"),
    )
    semantic_hashes: list[str] = []

    for index, arguments in enumerate(variants):
        step = ExpectedGatewayStep(
            "call",
            "call",
            (
                uri,
                "--args-json",
                SemanticJsonArgument({}),
                "--options-json",
                SemanticJsonArgument({}),
            ),
            allow_omitted_empty_json_objects=True,
        )
        with CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(step,),
            working_root=tmp_path / f"broker-{index}",
            transport="tcp",
        ) as broker:
            result = run_model_command(broker, ["call", *arguments])
            assert result.returncode == 0, result.stderr

            evidence = broker.evidence()
            assert evidence.passed is True
            semantic_hashes.append(evidence.records[0].semantic_argv_sha256)
            observed = [
                "python",
                str(broker.runner_path),
                "gateway.py",
                "call",
                *arguments,
            ]
            assert broker.reconcile((observed,)).passed is True

    assert len(set(semantic_hashes)) == 1


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            '{"unexpected":true}',
            "--options-json",
            "{}",
        ),
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            "{}",
            "--options-json",
            '{"return":["uri"]}',
        ),
        ("ak.wwise.waapi.getFunctions", "--args-json", "{}"),
        ("ak.wwise.waapi.getFunctions", "--options-json", "{}"),
        (
            "ak.wwise.waapi.getFunctions",
            "--options-json",
            "{}",
            "--args-json",
            "{}",
        ),
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json={}",
            "--options-json={}",
        ),
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            "[]",
            "--options-json",
            "{}",
        ),
    ),
)
def test_empty_call_json_equivalence_rejects_partial_reordered_or_nonempty_forms(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "call",
        "call",
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            SemanticJsonArgument({}),
            "--options-json",
            SemanticJsonArgument({}),
        ),
        allow_omitted_empty_json_objects=True,
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["call", *arguments])

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_wait_topic_default_event_count_omission_executes_canonical_one_and_preserves_evidence(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    canonical_arguments = (
        topic,
        "--event-count",
        "1",
        "--match-json",
        SemanticJsonArgument({"platform": "Windows"}),
    )
    variants = (
        (
            topic,
            "--event-count",
            "1",
            "--match-json",
            '{"platform":"Windows"}',
        ),
        (
            topic,
            "--match-json",
            '{"platform": "Windows"}',
        ),
    )
    semantic_hashes: list[str] = []

    for index, arguments in enumerate(variants):
        step = ExpectedGatewayStep(
            "soundbank.generated.wait",
            "wait-topic",
            canonical_arguments,
            allow_omitted_default_event_count_one=True,
        )
        with CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(step,),
            working_root=tmp_path / f"broker-{index}",
            transport="tcp",
        ) as broker:
            result = run_model_command(broker, ["wait-topic", *arguments])
            assert result.returncode == 0, result.stderr

            evidence = broker.evidence()
            assert evidence.passed is True
            record = evidence.records[0]
            semantic_hashes.append(record.semantic_argv_sha256)
            assert record.gateway_arguments == ("wait-topic", *arguments)

            executed = json.loads(
                (
                    broker.state_directory / "fake-runner-calls.jsonl"
                ).read_text(encoding="utf-8")
            )
            assert executed == [
                "gateway.py",
                "wait-topic",
                topic,
                "--event-count",
                "1",
                "--match-json",
                arguments[-1],
            ]
            observed = (
                "python",
                str(broker.runner_path),
                "gateway.py",
                "wait-topic",
                *arguments,
            )
            assert broker.reconcile((observed,)).passed is True

    assert len(set(semantic_hashes)) == 1


def test_topic_event_count_ceiling_accepts_only_one_canonical_bounded_integer(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep(
        "soundbank.generated.stream",
        "stream-topic",
        (topic, "--event-count", BoundedIntegerArgument(3, 64)),
        gateway_global_arguments=("--timeout", "30"),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        working_root=tmp_path / "accepted",
        trusted_subscription_ack=TrustedSubscriptionAckSpec(step.name, topic),
        trusted_subscription_ack_observer=lambda _expectation: None,
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "topic-stream"},
        transport="tcp",
    ) as broker:
        accepted = run_model_command(
            broker,
            ["--timeout", "30", "stream-topic", topic, "--event-count", "6"],
        )
        assert accepted.returncode == 0, accepted.stderr
        assert broker.evidence().passed is True

    for value in ("2", "65", "03", "six"):
        with CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(step,),
            working_root=tmp_path / f"rejected-{value}",
            transport="tcp",
        ) as broker:
            rejected = run_model_command(
                broker,
                ["--timeout", "30", "stream-topic", topic, "--event-count", value],
            )
            assert rejected.returncode == 126
            assert broker.evidence().terminal_state == "FAILED"


def test_wait_topic_event_count_greater_than_one_cannot_be_omitted(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep(
        "soundbank.generated.wait",
        "wait-topic",
        (topic, "--event-count", "2"),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["wait-topic", topic])

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_wait_topic_shorthand_cannot_invent_an_opaque_value_choice(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    expected = (
        topic,
        "--event-count",
        "1",
        "--event-entry-as",
        "platform",
        "-",
        "name",
        "tvc1-0123456789abcdef0123456789abcdef",
        "Windows",
    )
    supplied = (
        topic,
        "--event-count",
        "1",
        "--event-entry",
        "platform",
        "-",
        "name",
        "Windows",
    )
    step = ExpectedGatewayStep("wait", "wait-topic", expected)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["wait-topic", *supplied])

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_wait_topic_commutes_only_independent_selected_match_facts(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    fixed = (
        topic,
        "--event-count",
        "3",
    )
    options = (
        "--topic-option",
        "include",
        "id",
        "--topic-option",
        "include",
        "name",
    )
    platform = (
        "--event-match",
        "soundbank-type",
        "SoundBank",
    )
    soundbank = (
        "--event-match",
        "soundbank-name",
        "Dialogue_Chapter14",
    )
    step = ExpectedGatewayStep(
        "soundbank.generated.wait",
        "wait-topic",
        (*fixed, *options, *platform, *soundbank),
    )
    semantic_hashes: list[str] = []

    for index, facts in enumerate(((*platform, *soundbank), (*soundbank, *platform))):
        with CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(step,),
            working_root=tmp_path / f"broker-{index}",
            transport="tcp",
        ) as broker:
            result = run_model_command(
                broker,
                ["wait-topic", *fixed, *options, *facts],
            )

            assert result.returncode == 0, result.stderr
            evidence = broker.evidence()
            assert evidence.passed is True
            semantic_hashes.append(evidence.records[0].semantic_argv_sha256)

    assert len(set(semantic_hashes)) == 1


def test_wait_topic_does_not_commute_ordered_option_appends(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    fixed = (
        topic,
        "--event-count",
        "3",
    )
    first = (
        "--topic-option",
        "include",
        "id",
    )
    second = (
        "--topic-option",
        "include",
        "name",
    )
    step = ExpectedGatewayStep(
        "soundbank.generated.wait",
        "wait-topic",
        (*fixed, *first, *second),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["wait-topic", *fixed, *second, *first],
        )

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "ak.wwise.core.soundbank.generated",
            "--event-count",
            "1",
        ),
        (
            "ak.wwise.core.soundbank.generated",
            "--match-json",
            "{}",
        ),
        (
            "ak.wwise.core.soundbank.generated",
            "--event-count",
            "2",
            "--match-json",
            "{}",
        ),
    ),
)
def test_wait_topic_event_count_equivalence_rejects_unrelated_omissions_or_wrong_values(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "soundbank.generated.wait",
        "wait-topic",
        (
            "ak.wwise.core.soundbank.generated",
            "--event-count",
            "1",
            "--match-json",
            SemanticJsonArgument({"platform": "Windows"}),
        ),
        allow_omitted_default_event_count_one=True,
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["wait-topic", *arguments])

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


@pytest.mark.parametrize(
    "step",
    (
        ExpectedGatewayStep(
            "call",
            "call",
            ("ak.wwise.waapi.getFunctions",),
        ),
        ExpectedGatewayStep(
            "missing",
            "wait-topic",
            ("ak.wwise.core.soundbank.generated",),
        ),
        ExpectedGatewayStep(
            "multiple",
            "wait-topic",
            (
                "ak.wwise.core.soundbank.generated",
                "--event-count",
                "2",
            ),
        ),
        ExpectedGatewayStep(
            "duplicate",
            "wait-topic",
            (
                "ak.wwise.core.soundbank.generated",
                "--event-count",
                "1",
                "--event-count",
                "1",
            ),
        ),
    ),
)
def test_wait_topic_omitted_default_flag_rejects_invalid_step_shapes(
    step: ExpectedGatewayStep,
) -> None:
    with pytest.raises(ValueError, match="canonical --event-count 1"):
        ExpectedGatewayStep(
            step.name,
            step.subcommand,
            step.arguments,
            allow_omitted_default_event_count_one=True,
        )


def test_wait_topic_omitted_default_flag_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="must be a bool"):
        ExpectedGatewayStep(
            "wait",
            "wait-topic",
            ("ak.wwise.core.soundbank.generated", "--event-count", "1"),
            allow_omitted_default_event_count_one=1,  # type: ignore[arg-type]
        )


def test_authenticated_rejection_is_terminal_and_never_executes_later_command(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (ExpectedGatewayStep("status", "status"),)

    with CodexGatewayBroker(skill_source=skill, expected_steps=steps, transport="tcp") as broker:
        wrong = run_model_command(broker, ["buses"])
        assert wrong.returncode == 126
        assert "expected step" in wrong.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

        blocked = run_model_command(broker, ["status"])
        assert blocked.returncode == 126
        assert "terminal FAILED" in blocked.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

        evidence = broker.evidence()
        assert evidence.terminal_state == "FAILED"
        assert evidence.complete is False
        assert evidence.passed is False
        assert [record.accepted for record in evidence.records] == [False, False]


@pytest.mark.parametrize(
    "selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
        (),
    ),
)
def test_matching_optional_model_version_selector_is_sanitized_before_runner(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        runner_environment={**os.environ, "WWISE_VERSION": "2022.1"},
        transport="tcp",
    ) as broker:
        arguments = [*selector, "status"]
        result = run_model_command(broker, arguments)

        assert result.returncode == 0, result.stderr
        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.records[0].gateway_arguments == tuple(arguments)
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(calls[0]) == ["gateway.py", "status"]
        observed = [["python", str(broker.runner_path), "gateway.py", *arguments]]
        assert broker.reconcile(observed).passed is True


@pytest.mark.parametrize(
    "selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
    ),
)
def test_runner_level_version_selector_is_canonicalized_and_sanitized(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        runner_environment={**os.environ, "WWISE_VERSION": "2022.1"},
        transport="tcp",
    ) as broker:
        raw = ["python", str(broker.runner_path), *selector, "gateway.py", "status"]
        result = run_model_argv(
            raw,
            environment=(model_environment := broker.model_environment(os.environ)),
            windows_interpreter=(
                Path(model_environment[SHIM_TRUSTED_PYTHON_ENV])
                if os.name == "nt"
                else None
            ),
            windows_command_directory=broker.shim_directory,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        evidence = broker.evidence()
        assert evidence.passed is True
        record = evidence.records[0]
        assert record.model_argv[1:] == tuple(raw[1:])
        canonical = ("python", str(broker.runner_path), "gateway.py", *selector, "status")
        assert record.normalized_model_argv == canonical
        assert record.gateway_arguments == (*selector, "status")
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(calls[0]) == ["gateway.py", "status"]
        assert broker.reconcile((raw,)).passed is True


@pytest.mark.parametrize(
    "runner_tail",
    (
        ("--version", "2023.1", "gateway.py", "status"),
        ("--version=", "gateway.py", "status"),
        ("--wwise-version", "2022.1", "other.py", "status"),
        ("--version", "2022.1", "--version", "2022.1", "gateway.py", "status"),
        ("--state-dir", "/tmp/forbidden", "gateway.py", "status"),
    ),
)
def test_invalid_runner_level_selector_forms_fail_terminal_without_execution(
    tmp_path: Path,
    runner_tail: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        result = run_model_argv(
            ["python", str(broker.runner_path), *runner_tail],
            environment=(model_environment := broker.model_environment(os.environ)),
            windows_interpreter=(
                Path(model_environment[SHIM_TRUSTED_PYTHON_ENV])
                if os.name == "nt"
                else None
            ),
            windows_command_directory=broker.shim_directory,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().passed is False
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


@pytest.mark.parametrize(
    "arguments",
    (
        ("--version", "2023.1", "status"),
        ("--wwise-version=2023.1", "status"),
        ("--version=", "status"),
        ("--wwise-version", "", "status"),
        ("--version", "2022.1", "--version", "2022.1", "status"),
        ("status", "--version", "2022.1"),
    ),
)
def test_invalid_or_duplicate_model_version_selector_fails_terminal(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, list(arguments))

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().passed is False
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_trusted_step_observer_runs_in_order_after_validated_steps(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    observed: list[tuple[str, str, Path, Path]] = []

    def observer(step, payload, state_directory, evidence_directory) -> None:
        observed.append(
            (step.name, payload["command"], state_directory, evidence_directory)
        )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("first", "status"),
            ExpectedGatewayStep("second", "buses"),
        ),
        trusted_step_observer=observer,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        assert run_model_command(broker, ["buses"]).returncode == 0

        assert observed == [
            ("first", "status", broker.state_directory, broker.evidence_directory),
            ("second", "buses", broker.state_directory, broker.evidence_directory),
        ]
        assert broker.evidence().passed is True


def test_trusted_pre_observer_runs_after_argv_validation_before_gateway_process(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    events: list[str] = []

    def before(step, state_directory, evidence_directory) -> None:
        assert step.name == "status"
        assert state_directory.is_dir()
        assert evidence_directory.is_dir()
        assert not (state_directory / "fake-runner-calls.jsonl").exists()
        events.append("before")

    def after(step, payload, state_directory, evidence_directory) -> None:
        del step, payload, evidence_directory
        assert (state_directory / "fake-runner-calls.jsonl").is_file()
        events.append("after")

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        trusted_step_pre_observer=before,
        trusted_step_observer=after,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        assert events == ["before", "after"]
        assert broker.evidence().passed is True


def test_broker_runner_cannot_write_python_bytecode_into_the_skill_tree(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": "report-python-bytecode-policy",
        },
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["status"])
        evidence = broker.evidence()

    assert result.returncode == 0
    assert evidence.records[0].payload["python_dont_write_bytecode"] == "1"


def test_subscription_ack_is_secret_fresh_step_bound_and_broker_validated(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep("soundbank.generated.wait", "wait-topic", (topic,))
    observed: list[TrustedSubscriptionAckExpectation] = []
    ambient = {
        **os.environ,
        SUBSCRIPTION_ACK_PATH_ENV: "/tmp/model-forged-ack.json",
        SUBSCRIPTION_ACK_NONCE_ENV: "model-visible-nonce",
        SUBSCRIPTION_ACK_TOPIC_ENV: "wrong",
        SUBSCRIPTION_ACK_STEP_ENV: "wrong",
    }

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        trusted_subscription_ack=TrustedSubscriptionAckSpec(step.name, topic),
        trusted_subscription_ack_observer=observed.append,
        transport="tcp",
    ) as broker:
        model_environment = broker.model_environment(ambient)
        for name in (
            SUBSCRIPTION_ACK_PATH_ENV,
            SUBSCRIPTION_ACK_NONCE_ENV,
            SUBSCRIPTION_ACK_TOPIC_ENV,
            SUBSCRIPTION_ACK_STEP_ENV,
        ):
            assert name not in model_environment
            assert name not in broker.model_environment_overrides()
        expectation = broker.subscription_ack_expectation
        assert expectation is not None
        assert expectation.contract == SUBSCRIPTION_ACK_CONTRACT
        assert expectation.step_name == step.name
        assert expectation.topic == topic
        assert expectation.path.parent == broker.evidence_directory
        assert not expectation.path.exists()
        assert len(expectation.nonce_sha256) == 64
        assert not hasattr(expectation, "nonce")

        result = run_model_command(broker, ["wait-topic", topic])

        assert result.returncode == 0
        assert observed == [expectation]
        assert expectation.path.is_file()
        payload = json.loads(expectation.path.read_text(encoding="utf-8"))
        assert payload["contract"] == SUBSCRIPTION_ACK_CONTRACT
        assert payload["step_name"] == step.name
        assert payload["topic"] == topic
        assert (
            hashlib.sha256(payload["nonce"].encode("utf-8")).hexdigest()
            == expectation.nonce_sha256
        )
        evidence = broker.evidence()
        assert evidence.passed is True
        validated = evidence.records[0].subscription_ack
        assert validated is not None
        assert validated["contract"] == broker_module.VALIDATED_SUBSCRIPTION_ACK_CONTRACT
        assert validated["ack_file_sha256"] == hashlib.sha256(
            expectation.path.read_bytes()
        ).hexdigest()
        assert validated["runner_parent_process_id"] == payload[
            "runner_parent_process_id"
        ]
        assert validated["gateway_process_id"] == payload["gateway_process_id"]
        assert (
            evidence.records[0].started_at_unix_ns
            <= validated["subscribed_at_unix_ns"]
            <= validated["validated_at_unix_ns"]
            <= evidence.records[0].finished_at_unix_ns
        )


def test_stream_topic_ndjson_is_validated_and_observer_receives_events(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep(
        "soundbank.generated.stream",
        "stream-topic",
        (topic,),
        gateway_global_arguments=("--timeout", "30"),
    )
    observed: list[Mapping[str, object]] = []

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        trusted_subscription_ack=TrustedSubscriptionAckSpec(step.name, topic),
        trusted_subscription_ack_observer=lambda _expectation: None,
        trusted_step_observer=lambda _step, payload, _state, _evidence: observed.append(payload),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "topic-stream"},
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["--timeout", "30", "stream-topic", topic],
        )
        evidence = broker.evidence()

    assert result.returncode == 0, result.stderr
    assert [json.loads(line)["record_type"] for line in result.stdout.splitlines()] == [
        "started",
        "event",
        "terminal",
    ]
    assert evidence.passed is True
    assert evidence.records[0].payload["record_type"] == "terminal"
    assert evidence.records[0].payload["cleanup"] == "unsubscribed"
    assert observed[0]["events"] == [
        {"soundbank": {"name": "Weapons_Core"}}
    ]


@pytest.mark.parametrize(
    "mode",
    ("topic-stream-bad-sequence", "topic-stream-bad-cleanup"),
)
def test_stream_topic_rejects_malformed_or_unclean_terminal_evidence(
    tmp_path: Path,
    mode: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep(
        "soundbank.generated.stream",
        "stream-topic",
        (topic,),
        gateway_global_arguments=("--timeout", "30"),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        trusted_subscription_ack=TrustedSubscriptionAckSpec(step.name, topic),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": mode},
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["--timeout", "30", "stream-topic", topic],
        )
        evidence = broker.evidence()

    assert result.returncode == 125
    assert evidence.passed is False
    assert evidence.records[0].payload_error


def test_windows_subscription_ack_accepts_only_the_trusted_redirector_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        broker_module,
        "_windows_process_parent_map",
        lambda: {
            200: 100,
            300: 200,
            400: 300,
            500: 200,
            600: 100,
            700: 701,
            701: 700,
            901: 900,
        },
    )

    assert broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=100,
        gateway_process_id=600,
    )
    assert broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=300,
        gateway_process_id=400,
    )
    assert not broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=900,
        gateway_process_id=901,
    )
    assert not broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=300,
        gateway_process_id=500,
    )
    assert not broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=700,
        gateway_process_id=999,
    )
    assert not broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=300,
        gateway_process_id=999,
    )
    assert not broker_module._subscription_ack_process_binding_is_valid(
        platform_name="nt",
        launched_process_id=100,
        reported_parent_process_id=300,
        gateway_process_id=300,
    )


@pytest.mark.parametrize(
    "mode",
    (
        "subscription-ack-missing",
        "subscription-ack-wrong-topic",
        "subscription-ack-duplicate",
    ),
)
def test_subscription_ack_missing_wrong_or_duplicate_fails_broker_record(
    tmp_path: Path,
    mode: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep("soundbank.generated.wait", "wait-topic", (topic,))
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        trusted_subscription_ack=TrustedSubscriptionAckSpec(step.name, topic),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": mode},
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["wait-topic", topic])
        evidence = broker.evidence()

        assert result.returncode == 125
        assert evidence.passed is False
        assert evidence.terminal_state == "FAILED"
        assert evidence.records[0].payload_error


def test_subscription_ack_forged_between_validation_and_launch_fails_closed(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    step = ExpectedGatewayStep("soundbank.generated.wait", "wait-topic", (topic,))

    def forge(expectation: TrustedSubscriptionAckExpectation) -> None:
        expectation.path.write_text("{}\n", encoding="utf-8")

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        trusted_subscription_ack=TrustedSubscriptionAckSpec(step.name, topic),
        trusted_subscription_ack_observer=forge,
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["wait-topic", topic])
        assert result.returncode == 125
        assert broker.evidence().passed is False
        assert broker.evidence().records[0].payload_error


@pytest.mark.parametrize(
    "spec",
    (
        TrustedSubscriptionAckSpec("missing", "ak.test.topic"),
        TrustedSubscriptionAckSpec("wait", "ak.test.other"),
    ),
)
def test_subscription_ack_spec_must_match_exact_wait_step(
    tmp_path: Path,
    spec: TrustedSubscriptionAckSpec,
) -> None:
    skill = make_fake_skill(tmp_path)
    with pytest.raises(ValueError, match="subscription ACK"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(
                ExpectedGatewayStep("wait", "wait-topic", ("ak.test.topic",)),
            ),
            trusted_subscription_ack=spec,
        )


def test_trusted_step_observer_failure_is_terminal_and_prevents_progression(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    observed: list[str] = []

    def reject_seal(step, payload, state_directory, evidence_directory) -> None:
        observed.append(step.name)
        assert payload["command"] == "status"
        assert state_directory.is_dir()
        assert evidence_directory.is_dir()
        raise RuntimeError("transaction seal mismatch")

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("status", "status"),
            ExpectedGatewayStep("execute", "execute", ("tx-dynamic-123",)),
        ),
        trusted_step_observer=reject_seal,
        transport="tcp",
    ) as broker:
        failed = run_model_command(broker, ["status"])
        assert failed.returncode == 125
        assert "trusted step observer failed" in failed.stderr
        assert "transaction seal mismatch" in failed.stderr

        evidence = broker.evidence()
        record = evidence.records[0]
        assert observed == ["status"]
        assert "trusted step observer failed: RuntimeError" in record.payload_error
        assert "transaction seal mismatch" in record.payload_error
        assert record.runner_exit_code == 0
        assert record.exit_code == 125
        assert record.succeeded is False
        assert evidence.consumed_step_names == ()
        assert evidence.terminal_state == "FAILED"

        blocked = run_model_command(broker, ["execute", "tx-dynamic-123"])
        assert blocked.returncode == 126
        assert "terminal FAILED" in blocked.stderr
        assert observed == ["status"]
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 1
        assert not (broker.state_directory / "mutation-executed").exists()


def test_extra_command_after_completion_invalidates_terminal_evidence(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        assert broker.evidence().passed is True

        extra = run_model_command(broker, ["status"])
        assert extra.returncode == 126
        assert "terminal COMPLETE" in extra.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 1
        evidence = broker.evidence()
        assert evidence.terminal_state == "FAILED"
        assert evidence.passed is False
        assert len(evidence.records) == 2
        rejected = evidence.records[1]
        assert rejected.step_name is None
        assert rejected.authenticated is True
        assert rejected.accepted is False
        assert rejected.rejection == "broker is terminal COMPLETE"
        assert rejected.exit_code == 126
        assert rejected.runner_exit_code is None
        assert rejected.allowed_exit_codes == ()


def test_broker_rejects_wrong_preview_json_and_bad_dynamic_binding(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    expected_request = {"operation": "ak.wwise.core.object.setNotes", "value": "expected"}
    steps = (
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(expected_request)),
        ),
        ExpectedGatewayStep(
            "show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("show", "/transaction_id"),
                "--confirmation-token",
                ResponseBinding("show", "/confirmation/token"),
            ),
        ),
    )
    with CodexGatewayBroker(skill_source=skill, expected_steps=steps, transport="tcp") as broker:
        wrong_json = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps({**expected_request, "value": "wrong"})],
        )
        assert wrong_json.returncode == 126
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

        blocked = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(expected_request, separators=(",", ":"))],
        )
        assert blocked.returncode == 126
        assert "terminal FAILED" in blocked.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

    mutation_steps = (
        *steps,
        ExpectedGatewayStep(
            "execute",
            "execute",
            (ResponseBinding("confirm", "/transaction_id"),),
        ),
    )
    with CodexGatewayBroker(skill_source=skill, expected_steps=mutation_steps, transport="tcp") as broker:
        preview = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(expected_request, separators=(",", ":"))],
        )
        assert preview.returncode == 0
        shown = run_model_command(
            broker,
            ["transaction-show", "tx-dynamic-123", "--summary-only"],
        )
        assert shown.returncode == 0
        wrong_binding = run_model_command(
            broker,
            [
                "confirm",
                "tx-invented",
                "--confirmation-token",
                "ct1-0123456789abcdefghjkmnpq",
            ],
        )
        assert wrong_binding.returncode == 126
        assert "does not match" in wrong_binding.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 2

        blocked_mutation = run_model_command(
            broker,
            ["execute", "tx-dynamic-123"],
        )
        assert blocked_mutation.returncode == 126
        assert "terminal FAILED" in blocked_mutation.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 2
        assert not (broker.state_directory / "mutation-executed").exists()


def test_broker_rejects_a_confirmation_token_not_returned_by_transaction_show(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected_request = {
        "operation": "ak.wwise.core.object.setNotes",
        "value": "expected",
    }
    steps = (
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(expected_request)),
        ),
        ExpectedGatewayStep(
            "show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("show", "/transaction_id"),
                "--confirmation-token",
                ResponseBinding("show", "/confirmation/token"),
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
    ) as broker:
        assert run_model_command(
            broker,
            [
                "preview",
                "--request-json",
                json.dumps(expected_request, separators=(",", ":")),
            ],
        ).returncode == 0
        assert run_model_command(
            broker,
            ["transaction-show", "tx-dynamic-123", "--summary-only"],
        ).returncode == 0

        rejected = run_model_command(
            broker,
            [
                "confirm",
                "tx-dynamic-123",
                "--confirmation-token",
                "ct1-0123456789abcdefghjkmnpr",
            ],
        )

        assert rejected.returncode == 126
        assert "does not match show/confirmation/token" in rejected.stderr
        assert (
            len(
                (
                    broker.state_directory / "fake-runner-calls.jsonl"
                ).read_text().splitlines()
            )
            == 2
        )
        assert broker.evidence().terminal_state == "FAILED"


@pytest.mark.parametrize(
    "mode",
    ("confirmation-token-only", "confirmation-wrong-journal-head"),
)
def test_broker_rejects_incomplete_or_misbound_transaction_show_confirmation(
    tmp_path: Path,
    mode: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "object.setNotes", "arguments": {"value": "closed"}}
    steps = (
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_MODE": mode,
        },
    ) as broker:
        assert run_model_command(
            broker,
            [
                "preview",
                "--request-json",
                json.dumps(request, separators=(",", ":")),
            ],
        ).returncode == 0

        shown = run_model_command(
            broker,
            ["transaction-show", "tx-dynamic-123", "--summary-only"],
        )

        assert shown.returncode == 125
        assert "confirmation" in shown.stderr
        evidence = broker.evidence()
        assert evidence.terminal_state == "FAILED"
        assert evidence.records[-1].succeeded is False


def test_broker_rejects_inserted_characters_in_compact_transaction_id(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    expected_request = {"operation": "ak.wwise.core.object.setNotes", "value": "expected"}
    compact_transaction_id = "tx1-0123456789abcdefghjk"
    inserted_transaction_id = (
        compact_transaction_id[:-2] + "af" + compact_transaction_id[-2:]
    )
    steps = (
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(expected_request)),
        ),
        ExpectedGatewayStep(
            "show",
            "transaction-show",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--summary-only",
            ),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("show", "/transaction_id"),
                "--confirmation-token",
                ResponseBinding("show", "/confirmation/token"),
            ),
        ),
        ExpectedGatewayStep(
            "execute",
            "execute",
            (ResponseBinding("confirm", "/transaction_id"),),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport="tcp",
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "FAKE_GATEWAY_TRANSACTION_ID": compact_transaction_id,
        },
    ) as broker:
        preview = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(expected_request, separators=(",", ":"))],
        )
        assert preview.returncode == 0
        shown = run_model_command(
            broker,
            ["transaction-show", compact_transaction_id, "--summary-only"],
        )
        assert shown.returncode == 0

        wrong_binding = run_model_command(
            broker,
            [
                "confirm",
                inserted_transaction_id,
                "--confirmation-token",
                "ct1-0123456789abcdefghjkmnpq",
            ],
        )

        assert wrong_binding.returncode == 126
        assert "does not match" in wrong_binding.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 2
        assert not (broker.state_directory / "mutation-executed").exists()
        assert broker.evidence().terminal_state == "FAILED"


def test_broker_token_authentication_fails_before_runner(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        bad_environment = broker.model_environment(os.environ)
        bad_environment[BROKER_TOKEN_ENV] = "not-the-token"
        rejected = run_model_command(broker, ["status"], environment=bad_environment)

        assert rejected.returncode == 126
        assert "authentication failed" in rejected.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()
        assert broker.evidence().records[0].rejection == "broker authentication failed"


@pytest.mark.skipif(os.name == "nt", reason="POSIX shim contract")
def test_broker_installs_posix_shims_and_exposes_small_harness_overlay(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert (broker.shim_directory / "python").is_file()
        assert (broker.shim_directory / "python3").is_file()
        shim_source = (broker.shim_directory / "python").read_text(encoding="utf-8")
        assert "connection.settimeout(135.0)" in shim_source
        assert "os.write(descriptor, remaining)" in shim_source
        assert "stdout_written = write_all(1" in shim_source
        assert "stderr_written = write_all(2" in shim_source
        assert "OUTPUT_ARM_SECONDS = 0.25" in shim_source
        assert "OUTPUT_DRAIN_SECONDS = 0.25" in shim_source
        assert shim_source.count("time.sleep(OUTPUT_ARM_SECONDS)") == 2
        assert shim_source.count("time.sleep(OUTPUT_DRAIN_SECONDS)") == 2
        assert shim_source.index("time.sleep(OUTPUT_ARM_SECONDS)") < shim_source.index(
            "stdout_written = write_all(1"
        )
        overlay = broker.model_environment_overrides("/trusted/bin")
        assert "HOME" not in overlay
        assert "CODEX_HOME" not in overlay
        assert overlay["PATH"] == f"{broker.shim_directory}{os.pathsep}/trusted/bin"
        assert overlay[BASH_ENV_NAME] == str(broker.bash_env_path)
        assert "PATHEXT" not in overlay
        assert SHIM_TRUSTED_PYTHON_ENV not in overlay
        assert overlay[GATEWAY_REQUIRED_ENV] == "1"

        result = subprocess.run(
            [
                "/bin/bash",
                "-lc",
                " ".join(
                    (
                        "python3",
                        shlex.quote(str(broker.runner_path)),
                        "gateway.py",
                        "status",
                    )
                ),
            ],
            env={**os.environ, **overlay},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout
        visible_payload = json.loads(result.stdout[result.stdout.index("{") :])
        assert visible_payload["command"] == "status"
        assert result.stderr == ""
        record = broker.evidence().records[0]
        assert record.stdout == result.stdout
        assert record.normalized_model_argv[0] == "python3"
        assert record.payload is not None
        assert record.payload["gateway_required_visible"] is False


def test_broker_materializes_closed_windows_powershell_shims_and_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(broker_module, "_broker_platform_name", lambda: "nt")
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert broker.platform_name == "nt"
        assert not (broker.shim_directory / "python").exists()
        assert not (broker.shim_directory / "python3").exists()
        source_path = broker.shim_directory / WINDOWS_SHIM_SCRIPT_NAME
        assert source_path.is_file()
        assert source_path.is_symlink() is False
        source = source_path.read_text(encoding="utf-8")
        assert "WINDOWS_WRAPPER = True" in source
        assert "shim_interpreter = sys.argv[1]" in source
        assert "shim_argv = sys.argv[2:]" in source
        for name in WINDOWS_COMMAND_SHIM_NAMES:
            wrapper = broker.shim_directory / name
            assert wrapper.is_file()
            assert wrapper.is_symlink() is False
            raw = wrapper.read_bytes()
            assert raw.startswith(b"\xef\xbb\xbf") is False
            assert raw.endswith(b"\n")
            assert b"\r" not in raw
            assert SHIM_TRUSTED_PYTHON_ENV.encode("ascii") in raw
            assert WINDOWS_SHIM_SCRIPT_NAME.encode("ascii") in raw
            assert b"$PSScriptRoot" in raw
            assert b"@args" in raw
            assert b"$ErrorActionPreference = 'Stop'" in raw
            assert b"$PSNativeCommandArgumentPassing = 'Standard'" in raw
            assert b"$PSNativeCommandUseErrorActionPreference = $false" in raw
            assert b"$LASTEXITCODE = $null" not in raw
            assert raw.count(b"[System.Environment]::Exit(") == 4
            assert b" exit " not in raw
            interpreter_name = Path(name).stem.encode("ascii")
            assert b"'" + interpreter_name + b"' @args" in raw
            for forbidden in (
                b"Invoke-Expression",
                b"Start-Process",
                b"EncodedCommand",
                b"FromBase64String",
                b"ConvertFrom-Json",
                b"Set-ExecutionPolicy",
            ):
                assert forbidden not in raw
        assert not (broker.shim_directory / "python.cmd").exists()
        assert not (broker.shim_directory / "python3.cmd").exists()

        overlay = broker.model_environment_overrides(
            r"C:\Windows\System32",
            existing_pathext=".EXE;.bat;.Cmd;.PY",
        )
        assert overlay["PATH"] == (
            f"{broker.shim_directory};" r"C:\Windows\System32"
        )
        assert overlay["PATHEXT"] == ".PS1;.EXE;.BAT;.CMD;.PY"
        assert overlay[SHIM_TRUSTED_PYTHON_ENV] == str(broker.trusted_python)
        assert BASH_ENV_NAME not in overlay
        with pytest.raises(GatewayBrokerError, match="has not started"):
            _ = broker.bash_env_path

        mixed_case_base = {
            "Path": r"C:\Trusted\Bin",
            "PathExt": ".EXE;.CMD",
            "Bash_Env": r"C:\forged\bash_env",
            "waapi_codex_gateway_shim_trusted_python": r"C:\forged\python.exe",
        }
        environment = broker.model_environment(mixed_case_base)
        assert "Path" not in environment
        assert "PathExt" not in environment
        assert "Bash_Env" not in environment
        assert "waapi_codex_gateway_shim_trusted_python" not in environment
        assert environment["PATH"].endswith(r";C:\Trusted\Bin")
        assert environment["PATHEXT"] == ".PS1;.EXE;.CMD"
        assert environment[SHIM_TRUSTED_PYTHON_ENV] == str(
            broker.trusted_python
        )


@pytest.mark.parametrize(
    "value",
    ("", ".EXE;;.CMD", ".EXE; .CMD", ".EXE;.CMD&calc", "EXE;.CMD"),
)
def test_broker_windows_pathext_fails_closed_on_ambiguous_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setattr(broker_module, "_broker_platform_name", lambda: "nt")
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        with pytest.raises(GatewayBrokerError, match="PATHEXT"):
            broker.model_environment_overrides(
                r"C:\Windows\System32",
                existing_pathext=value,
            )


def test_broker_fails_closed_when_no_native_shim_backend_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        broker_module,
        "_broker_platform_name",
        lambda: "unsupported",
    )
    skill = make_fake_skill(tmp_path)
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    )

    with pytest.raises(GatewayBrokerError, match="only native POSIX or Windows"):
        broker.start()
    assert broker._temporary_directory is None
    assert broker._working_root is None


@pytest.mark.parametrize("interpreter_name", ("python", "python3"))
@pytest.mark.skipif(os.name != "nt", reason="native Windows PowerShell resolution")
def test_native_windows_powershell_shim_preserves_hostile_json(
    tmp_path: Path,
    interpreter_name: str,
) -> None:
    pwsh = native_pwsh_73_or_skip()

    skill = make_fake_skill(tmp_path)
    request = {
        "contract": "waapi-skill.windows-relay-hostile-json/v1",
        "edge_values": {
            "empty": "",
            "trailing_backslash": "C:\\Program Files\\Audio\\tail\\",
            "escaped_quote": 'say "hello" then write \\"',
            "control": "line one\nline two\tend\u0001",
            "unicode": "雪・你好・café",
            "literal_environment_token": "%TEMP%\\not-expanded\\",
        },
        "rows": [
            {
                "index": index,
                "name": f'row {index}: "quoted" and apostrophe \'',
                "path": rf"C:\Program Files\Audio & Tools\row-{index}\雪.wav",
                "operators_are_data": "& | ; < > $() ` % ^ ! [ ] { }",
            }
            for index in range(24)
        ],
    }
    request_json = json.dumps(
        request,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    options_json = json.dumps(
        {"return": ["id", "name", "path"], "note": "你好 & goodbye"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    uri = "ak.wwise.core.object.get"
    arguments = [
        "call",
        uri,
        "--args-json",
        request_json,
        "--options-json",
        options_json,
    ]
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "hostile-call",
                "call",
                (
                    uri,
                    "--args-json",
                    SemanticJsonArgument(request),
                    "--options-json",
                    SemanticJsonArgument(json.loads(options_json)),
                ),
            ),
        ),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "exact-output"},
        transport="tcp",
    ) as broker:
        command_script = interpreter_name + " " + " ".join(
            "'" + argument.replace("'", "''") + "'"
            for argument in (
                str(broker.invocation_runner_path),
                "gateway.py",
                *arguments,
            )
        )
        result = subprocess.run(
            [
                pwsh,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command_script,
            ],
            env=broker.model_environment(os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert payload["command"] == "call"
        assert payload["shim_trusted_python_visible"] is False
        assert payload["bash_env_visible"] is False
        record = broker.evidence().records[0]
        assert len(request_json.encode("utf-8")) >= 2299
        assert request_json.count('"') >= 108
        assert record.model_argv == (
            interpreter_name,
            str(broker.invocation_runner_path),
            "gateway.py",
            *arguments,
        )
        assert record.normalized_model_argv[0] == interpreter_name
        assert record.succeeded is True


@pytest.mark.skipif(os.name != "nt", reason="native Windows PowerShell resolution")
def test_native_windows_powershell_shim_preserves_public_typed_container_facts(
    tmp_path: Path,
) -> None:
    """Prove the current typed path through pwsh, the PS1 relay, and Broker.

    This deliberately stops before ``draft-check`` so the test remains offline.
    The durable Draft is then materialized by the same authoritative Composer
    seam used before Preview.
    """

    pwsh = native_pwsh_73_or_skip()
    skill = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    hostile_bank = r'\SoundBanks\雪 & "Quoted"; $not_expanded | %TEMP% ` tail'
    hostile_event = (
        "\\Events\\空 间 & 'apostrophe'; $(not-run) | %TEMP% ` "
        '\\"tail'
    )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "soundbank.setInclusions",
        "arguments": {
            "soundbank": {"kind": "path", "value": hostile_bank},
            "mode": "replace",
            "inclusions": [
                {
                    "object": {"kind": "path", "value": hostile_event},
                    "filters": ["events", "media"],
                }
            ],
        },
    }
    protocol = build_transaction_protocol((request,))
    final_action_index = max(
        index
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "draft-apply"
    )
    steps = protocol.steps[: final_action_index + 1]

    def pointer(payload: object, value: str) -> object:
        current = payload
        for token in value.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    payloads: dict[str, dict[str, object]] = {}
    observed: list[tuple[str, ...]] = []
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        expected_wwise_version="2025.1",
        transport="tcp",
        working_root=tmp_path / "broker-root",
    ) as broker:
        assert json.loads(broker.config_path.read_text(encoding="utf-8"))[
            "wwise_version"
        ] == "2025.1"
        for step in steps:
            argv: list[str] = ["--version", "2025.1", step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    argv.append(str(pointer(payloads[argument.step], argument.pointer)))
                    continue
                if isinstance(
                    argument,
                    (DraftTypedActionArgument, DraftTypedActionBatchArgument),
                ):
                    actions = (
                        argument.actions
                        if isinstance(argument, DraftTypedActionBatchArgument)
                        else (argument,)
                    )
                    for typed_action in actions:
                        action = dict(typed_action.expected)
                        for binding in typed_action.response_bindings:
                            action[binding.pointer.removeprefix("/")] = pointer(
                                payloads[binding.step], binding.response_pointer
                            )
                        argv.extend(typed_action_cli_arguments(action))
                    continue
                assert isinstance(argument, str)
                argv.append(argument)

            full_argv = (
                "python",
                str(broker.invocation_runner_path),
                "gateway.py",
                *argv,
            )
            command_script = "& " + " ".join(quote(value) for value in full_argv)
            result = subprocess.run(
                [
                    pwsh,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command_script,
                ],
                env=broker.model_environment(os.environ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, {
                "stderr": result.stderr,
                "stdout": result.stdout,
                "evidence": broker.evidence().as_dict(include_output=True),
            }
            payload = json.loads(result.stdout[result.stdout.index("{") :])
            payloads[step.name] = payload
            observed.append(full_argv)

        start = payloads["tx01.draft-start"]
        draft_id = str(pointer(start, "/draft/draft_id"))
        authority = str(pointer(start, "/task_authority"))
        stored = OperationDraftStore(broker.state_directory).inspect(
            draft_id,
            task_authority=authority,
        )
        materialized = materialize_operation_request(
            "soundbank.setInclusions",
            "2025.1",
            stored.composition,
        )
        assert materialized == request
        assert broker.evidence().complete is True
        assert broker.reconcile(observed).passed is True
        assert any(
            record.payload is not None
            and record.payload.get("command") == "request-array-item"
            for record in broker.evidence().records
        )
        transported = tuple(
            value
            for record in broker.evidence().records
            for value in record.model_argv
        )
        assert hostile_bank in transported
        assert hostile_event in transported


@pytest.mark.skipif(os.name != "nt", reason="native Windows PowerShell resolution")
def test_native_windows_powershell_shim_propagates_packaged_exit_two(
    tmp_path: Path,
) -> None:
    pwsh = native_pwsh_73_or_skip()
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "expected-error",
                "status",
                allowed_exit_codes=(2,),
                expected_error_code="PACKAGED_PREVIEW_UNAVAILABLE",
                expected_result_command="status",
            ),
        ),
        runner_environment={
            **os.environ,
            "FAKE_GATEWAY_MODE": "expected-error-exact-output",
        },
        transport="tcp",
    ) as broker:
        command_script = "python '" + str(broker.invocation_runner_path).replace(
            "'", "''"
        ) + "' 'gateway.py' 'status'"
        result = subprocess.run(
            [
                pwsh,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command_script,
            ],
            env=broker.model_environment(os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

        assert result.returncode == 2, result.stderr
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error_code"] == "PACKAGED_PREVIEW_UNAVAILABLE"
        record = broker.evidence().records[0]
        assert record.runner_exit_code == 2
        assert record.exit_code == 2
        assert record.succeeded is True


@pytest.mark.parametrize(
    ("runner_timeout", "expected_response_timeout"),
    ((0.05, 30.0), (120.0, 135.0), (240.0, 255.0)),
)
def test_broker_shim_response_timeout_is_finite_and_outlives_runner_budget(
    tmp_path: Path,
    runner_timeout: float,
    expected_response_timeout: float,
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
        runner_timeout_seconds=runner_timeout,
    ) as broker:
        source_name = WINDOWS_SHIM_SCRIPT_NAME if os.name == "nt" else "python"
        source = (broker.shim_directory / source_name).read_text(encoding="utf-8")
        assert f"connection.settimeout({expected_response_timeout!r})" in source


def test_broker_fails_closed_and_records_invalid_runner_evidence(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    (skill / "scripts" / "run.py").write_text(
        'print("not a gateway JSON payload")\n',
        encoding="utf-8",
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["status"])
        assert result.returncode == 125
        record = broker.evidence().records[0]
        assert record.accepted is True
        assert record.runner_exit_code == 0
        assert record.exit_code == 125
        assert record.payload is None
        assert "JSON" in record.payload_error
        assert record.succeeded is False
        assert broker.evidence().terminal_state == "FAILED"
        assert run_model_command(broker, ["status"]).returncode == 126
        assert len(broker.evidence().accepted_records) == 1


@pytest.mark.parametrize(
    ("mode", "error_text"),
    [
        ("bad-ok", "ok must be exactly true"),
        ("bad-command", "payload command must be exactly"),
        ("bad-contract", "payload contract must be"),
        ("bad-exit", "runner exit 7"),
    ],
)
def test_bad_runner_payload_or_exit_is_terminal(
    tmp_path: Path,
    mode: str,
    error_text: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    observer_calls: list[str] = []
    runner_environment = {**os.environ, "FAKE_GATEWAY_MODE": mode}
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("status", "status"),
            ExpectedGatewayStep("execute", "execute", ("tx-dynamic-123",)),
        ),
        runner_environment=runner_environment,
        trusted_step_observer=lambda step, *_: observer_calls.append(step.name),
        transport="tcp",
    ) as broker:
        failed = run_model_command(broker, ["status"])
        assert failed.returncode == 125
        record = broker.evidence().records[0]
        assert error_text in record.payload_error
        assert record.succeeded is False
        assert observer_calls == []
        assert broker.evidence().consumed_step_names == ()
        assert broker.evidence().terminal_state == "FAILED"

        blocked = run_model_command(broker, ["execute", "tx-dynamic-123"])
        assert blocked.returncode == 126
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()
        assert len(calls) == 1
        assert not (broker.state_directory / "mutation-executed").exists()


def test_subprocess_oserror_is_recorded_and_terminal(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        # Freeze the already-materialized shim interpreter.  On POSIX it is in
        # the shebang; on Windows it is the direct closed Python shim launch.
        # Changing only the broker's runner interpreter then forces its
        # subprocess.run boundary to raise FileNotFoundError.
        model_environment = broker.model_environment(os.environ)
        broker.trusted_python = tmp_path / "missing-python"
        failed = run_model_command(
            broker,
            ["status"],
            environment=model_environment,
        )
        assert failed.returncode == 125
        record = broker.evidence().records[0]
        assert record.accepted is True
        assert record.runner_exit_code is None
        assert "FileNotFoundError" in record.payload_error
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().complete is False
        reconciliation = broker.reconcile(
            [["python", str(broker.runner_path), "gateway.py", "status"]]
        )
        assert reconciliation.passed is False
        assert any("did not succeed" in error for error in reconciliation.errors)


@pytest.mark.skipif(os.name != "posix", reason="process-group timeout contract is POSIX-specific")
def test_runner_timeout_kills_reaps_and_records_terminal_failure(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "hang-ignore-term"},
        transport="tcp",
        # Leave enough time for a cold Python interpreter to import this large
        # fake runner and write its PID; the assertions below still prove the
        # configured timeout and hard reap.
        runner_timeout_seconds=1.0,
    ) as broker:
        started = time.monotonic()
        failed = run_model_command(broker, ["status"])
        elapsed = time.monotonic() - started

        assert elapsed < 3.0
        assert failed.returncode == 125
        record = broker.evidence().records[0]
        assert record.accepted is True
        assert record.runner_exit_code == 124
        assert record.succeeded is False
        assert "packaged gateway runner timed out" in record.payload_error
        assert broker.evidence().terminal_state == "FAILED"
        assert broker._active_process is None
        assert broker._active_process_done.is_set()

        runner_pid = int(
            (broker.state_directory / "fake-runner-pid").read_text(encoding="utf-8")
        )
        with pytest.raises(ProcessLookupError):
            os.kill(runner_pid, 0)


@pytest.mark.skipif(os.name != "posix", reason="process-group lifecycle contract is POSIX-specific")
def test_close_terminates_kills_and_reaps_active_runner_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_fake_skill(tmp_path)
    root = tmp_path / "broker-root"
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "hang-ignore-term"},
        working_root=root,
        transport="tcp",
        runner_timeout_seconds=30,
    ).start()
    results: list[subprocess.CompletedProcess[str]] = []
    command_thread = threading.Thread(
        target=lambda: results.append(run_model_command(broker, ["status"])),
        name="test-model-command",
    )
    command_thread.start()

    pid_path = broker.state_directory / "fake-runner-pid"
    deadline = time.monotonic() + 5
    while not pid_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_path.is_file(), "fake packaged runner did not enter its blocking state"
    runner_pid = int(pid_path.read_text(encoding="utf-8"))

    delivered_signals: list[int] = []
    real_killpg = os.killpg

    def recording_killpg(process_group: int, signum: int) -> None:
        if process_group == runner_pid:
            delivered_signals.append(signum)
        real_killpg(process_group, signum)

    monkeypatch.setattr(broker_module.os, "killpg", recording_killpg)
    started = time.monotonic()
    broker.close()
    elapsed = time.monotonic() - started
    command_thread.join(timeout=2)

    assert elapsed < 3
    assert command_thread.is_alive() is False
    assert [signal.SIGTERM, signal.SIGKILL] == delivered_signals
    assert broker._thread is not None and broker._thread.is_alive() is False
    assert broker._active_process is None
    assert broker._active_process_done.is_set()
    with pytest.raises(ProcessLookupError):
        os.kill(runner_pid, 0)
    assert len(results) == 1
    assert results[0].returncode == 125
    record = broker.evidence().records[0]
    assert record.runner_exit_code == -signal.SIGKILL
    assert "runner exit" in record.payload_error


@pytest.mark.parametrize("failure_stage", ["bind", "shims", "thread"])
def test_start_failure_rolls_back_all_owned_resources_and_remains_one_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    class StartFailure(RuntimeError):
        pass

    skill = make_fake_skill(tmp_path)
    root = tmp_path / "owned"
    root.mkdir()
    sentinel = root / "keep.txt"
    sentinel.write_text("user-owned", encoding="utf-8")
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        working_root=root,
        transport="tcp",
    )
    failure = StartFailure(failure_stage)

    if failure_stage == "bind":
        real_bind = broker._bind_socket

        def bind_then_fail(path: Path) -> None:
            real_bind(path)
            raise failure

        monkeypatch.setattr(broker, "_bind_socket", bind_then_fail)
    elif failure_stage == "shims":
        real_write_shims = broker._write_shims

        def write_then_fail() -> None:
            real_write_shims()
            raise failure

        monkeypatch.setattr(broker, "_write_shims", write_then_fail)
    else:
        real_thread_start = broker_module.threading.Thread.start

        def thread_start_then_fail(thread: threading.Thread) -> None:
            real_thread_start(thread)
            raise failure

        monkeypatch.setattr(broker_module.threading.Thread, "start", thread_start_then_fail)

    with pytest.raises(StartFailure) as caught:
        broker.start()
    assert caught.value is failure
    assert sorted(path.name for path in root.iterdir()) == [sentinel.name]
    assert broker._socket is None
    assert broker._socket_path is None
    assert broker._thread is None
    assert broker._started is False
    assert broker._created_directories == []
    with pytest.raises(GatewayBrokerError, match="has not started"):
        _ = broker.shim_directory
    with pytest.raises(GatewayBrokerError, match="cannot be restarted"):
        broker.start()


def test_failed_start_removes_implicit_temporary_root_and_preserves_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_fake_skill(tmp_path)
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    )
    failure = RuntimeError("shim write failed")
    captured_roots: list[Path] = []
    real_write_shims = broker._write_shims

    def write_then_fail() -> None:
        assert broker._working_root is not None
        captured_roots.append(broker._working_root)
        real_write_shims()
        raise failure

    monkeypatch.setattr(broker, "_write_shims", write_then_fail)
    with pytest.raises(RuntimeError) as caught:
        broker.start()

    assert caught.value is failure
    assert len(captured_roots) == 1
    assert captured_roots[0].exists() is False
    assert broker._temporary_directory is None
    assert broker._working_root is None
    with pytest.raises(GatewayBrokerError, match="cannot be restarted"):
        broker.start()


def test_constructor_rejects_empty_steps_and_runner_owned_global_overrides(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with pytest.raises(ValueError, match="at least one"):
        CodexGatewayBroker(skill_source=skill, expected_steps=())
    with pytest.raises(ValueError, match="only for execute"):
        ExpectedGatewayStep("status", "status", allowed_exit_codes=(0, 2))
    with pytest.raises(ValueError, match="only for execute"):
        ExpectedGatewayStep(
            "status",
            "status",
            allowed_exit_codes=(0, 2),
            terminal_execute=True,
        )
    with pytest.raises(ValueError, match="expected_error_code"):
        ExpectedGatewayStep("status", "status", allowed_exit_codes=(2,))
    with pytest.raises(ValueError, match="only when allowed_exit_codes"):
        ExpectedGatewayStep(
            "status",
            "status",
            expected_error_code="WRONG",
            expected_result_command="status",
        )
    with pytest.raises(ValueError, match="runner-owned"):
        ExpectedGatewayStep(
            "status",
            "status",
            gateway_global_arguments=("--state-dir", "/tmp/model-state"),
        )
    with pytest.raises(ValueError, match="canonical"):
        ExpectedGatewayStep(
            "call",
            "call",
            ("ak.wwise.waapi.getFunctions",),
            allow_omitted_empty_json_objects=True,
        )
    with pytest.raises(TypeError, match="callable or None"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(ExpectedGatewayStep("status", "status"),),
            trusted_step_observer="not-callable",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="expected_wwise_version"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(ExpectedGatewayStep("status", "status"),),
            expected_wwise_version="2030.1",
        )
    with pytest.raises(ValueError, match="final broker step"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(
                ExpectedGatewayStep(
                    "execute",
                    "execute",
                    ("tx",),
                    allowed_exit_codes=(0, 2),
                    terminal_execute=True,
                ),
                ExpectedGatewayStep("status", "status"),
            ),
        )
    for arguments in (
        ("--state-dir", "/tmp/model-state"),
        ("--state-dir=/tmp/model-state",),
        ("--evidence-dir", "/tmp/model-evidence"),
        ("--evidence-dir=/tmp/model-evidence",),
    ):
        with pytest.raises(ValueError, match="runner-owned"):
            CodexGatewayBroker(
                skill_source=skill,
                expected_steps=(ExpectedGatewayStep("status", "status"),),
                gateway_global_arguments=arguments,
            )


def test_new_broker_attaches_existing_a_phase_state_with_new_token_and_evidence(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "ak.wwise.core.object.setNotes", "value": "phase-a"}
    a_root = tmp_path / "phase-a-owned"
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "preview",
                "preview",
                ("--request-json", SemanticJsonArgument(request)),
            ),
        ),
        working_root=a_root,
        transport="tcp",
    ) as phase_a:
        a_environment = phase_a.model_environment(os.environ)
        old_token = a_environment[BROKER_TOKEN_ENV]
        assert run_model_command(
            phase_a,
            ["preview", "--request-json", json.dumps(request)],
            environment=a_environment,
        ).returncode == 0
        shared_state = phase_a.state_directory
        a_evidence = phase_a.evidence_directory
        assert phase_a.evidence().passed is True

    b_root = tmp_path / "phase-b-owned"
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("show", "transaction-show", ("tx-dynamic-123",)),
        ),
        existing_state_directory=shared_state,
        working_root=b_root,
        transport="tcp",
    ) as phase_b:
        assert phase_b.state_directory == shared_state
        assert phase_b.evidence_directory != a_evidence
        b_environment = phase_b.model_environment(os.environ)
        assert b_environment[BROKER_TOKEN_ENV] != old_token

        stale_environment = dict(b_environment)
        stale_environment[BROKER_TOKEN_ENV] = old_token
        stale = run_model_command(
            phase_b,
            ["transaction-show", "tx-dynamic-123"],
            environment=stale_environment,
        )
        assert stale.returncode == 126
        assert "authentication failed" in stale.stderr
        assert len((shared_state / "fake-runner-calls.jsonl").read_text().splitlines()) == 1

        attached = run_model_command(
            phase_b,
            ["transaction-show", "tx-dynamic-123"],
            environment=b_environment,
        )
        assert attached.returncode == 0
        payload = json.loads(attached.stdout[attached.stdout.index("{") :])
        assert payload["transaction_id"] == "tx-dynamic-123"
        assert payload["state_dir"] == str(shared_state)
        assert len((shared_state / "fake-runner-calls.jsonl").read_text().splitlines()) == 2
        # The stale-token attempt is audited but does not poison the new
        # authenticated broker state.
        assert phase_b.evidence().terminal_state == "COMPLETE"
        assert phase_b.evidence().complete is False
        assert phase_b.evidence().passed is False


def test_existing_state_directory_must_exist_and_not_be_symlink(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    step = (ExpectedGatewayStep("status", "status"),)
    with pytest.raises(ValueError, match="existing directory"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=step,
            existing_state_directory=tmp_path / "missing",
        )

    real = tmp_path / "real-state"
    real.mkdir()
    linked = tmp_path / "linked-state"
    create_symlink_or_skip(linked, real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=step,
            existing_state_directory=linked,
        )


@pytest.mark.parametrize(
    "selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
    ),
)
def test_resolver_canonicalizes_runner_and_gateway_level_version_selectors(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    runner = str(skill / "scripts" / "run.py")
    runner_level = ["python", runner, *selector, "gateway.py", "status"]
    gateway_level = ["python", runner, "gateway.py", *selector, "status"]

    before = resolve_gateway_invocation(runner_level, skill_source=skill)
    after = resolve_gateway_invocation(gateway_level, skill_source=skill)

    assert before.raw_model_argv != after.raw_model_argv
    assert before.normalized_model_argv == after.normalized_model_argv
    assert before.gateway_arguments == after.gateway_arguments
    assert before.argv_sha256 == after.argv_sha256


def test_resolver_and_reconciliation_fail_closed(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    correct = ["python3", str(skill / "scripts" / "run.py"), "gateway.py", "status"]
    resolved = resolve_gateway_invocation(correct, skill_source=skill)
    assert resolved.subcommand == "status"
    assert resolved.normalized_model_argv[0] == "python3"

    with pytest.raises(GatewayInvocationError, match="exactly"):
        resolve_gateway_invocation(
            ["python", str(skill.resolve() / "scripts" / "../scripts" / "run.py"), "gateway.py", "status"],
            skill_source=skill,
        )
    with pytest.raises(GatewayInvocationError, match="gateway.py"):
        resolve_gateway_invocation(
            ["python", str(skill / "scripts" / "run.py"), "other.py", "status"],
            skill_source=skill,
        )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        evidence = broker.evidence()
        mismatch = reconcile_gateway_commands(
            [["python", str(skill / "scripts" / "run.py"), "gateway.py", "buses"]],
            evidence,
            skill_source=skill,
        )
        assert mismatch.passed is False
        assert any("differs" in error for error in mismatch.errors)


def test_resolver_accepts_only_the_exact_task_local_relative_runner(
    tmp_path: Path,
) -> None:
    candidate = make_fake_skill(tmp_path / "candidate")
    invocation = make_fake_skill(
        tmp_path / "task" / ".agents" / "skills"
    )
    relative_runner = (
        TASK_LOCAL_RUNNER_WINDOWS if os.name == "nt" else TASK_LOCAL_RUNNER_POSIX
    )

    resolved = resolve_gateway_invocation(
        ["python", relative_runner, "gateway.py", "status"],
        skill_source=candidate,
        invocation_skill_source=invocation,
    )

    assert resolved.raw_model_argv[1] == relative_runner
    assert resolved.runner_path == str(invocation / "scripts" / "run.py")
    assert resolved.normalized_model_argv[1] == resolved.runner_path
    with pytest.raises(GatewayInvocationError, match="runner path"):
        resolve_gateway_invocation(
            [
                "python",
                relative_runner.replace("run.py", "rn.py"),
                "gateway.py",
                "status",
            ],
            skill_source=candidate,
            invocation_skill_source=invocation,
        )


@pytest.mark.parametrize(
    ("raw_runner", "normalized_runner"),
    (
        (
            TASK_LOCAL_RUNNER_POSIX,
            "/tmp/task/.agents/skills/waapi-skill/scripts/run.py",
        ),
        (
            TASK_LOCAL_RUNNER_WINDOWS,
            r"C:\task\.agents\skills\waapi-skill\scripts\run.py",
        ),
    ),
)
def test_task_local_runner_binding_uses_owning_path_flavor(
    raw_runner: str,
    normalized_runner: str,
) -> None:
    assert task_local_runner_matches_normalized(raw_runner, normalized_runner)
    assert not task_local_runner_matches_normalized(
        raw_runner.replace("run.py", "rn.py"),
        normalized_runner,
    )
    assert not task_local_runner_matches_normalized(
        raw_runner,
        normalized_runner.replace("waapi-skill", "other-skill"),
    )


def test_windows_codex_shlex_audio_import_event_reconciles_exact_broker_argv_and_hashes(
    tmp_path: Path,
) -> None:
    """Bind Codex's display command to the Broker without repairing JSON."""

    skill = make_fake_skill(tmp_path)
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": "<Sound>Rifle_Thunder_Near",
                    "audio_file": r"C:\Audio fixtures\Rifle\Thunder Near.wav",
                    "import_language": "SFX",
                    "properties": [
                        {"name": "Volume", "value": -2.0},
                        {"name": "IsLoopingEnabled", "value": True},
                        {
                            "name": "Notes",
                            "value": "sealed Rifle import evidence " * 72,
                        },
                    ],
                }
            ],
            "import_operation": "replaceExisting",
        },
    }
    request_json = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    assert len(request_json.encode("utf-8")) > 2048
    step = ExpectedGatewayStep(
        "preview",
        "preview",
        ("--request-json", SemanticJsonArgument(request)),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "exact-output"},
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["preview", "--request-json", request_json],
        )
        assert result.returncode == 0, result.stderr
        evidence = broker.evidence()
        assert evidence.passed is True

        def powershell_literal(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        script = " ".join(
            (
                "python",
                powershell_literal(str(broker.invocation_runner_path)),
                "gateway.py",
                "preview",
                "--request-json",
                powershell_literal(request_json),
            )
        )

        def rust_shlex_double_quoted(value: str) -> str:
            assert not any(character in value for character in "$`!^")
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

        pwsh = r"C:\Program Files\PowerShell\7\pwsh.exe"
        command = " ".join(
            (
                rust_shlex_double_quoted(pwsh),
                "-NoProfile",
                "-Command",
                rust_shlex_double_quoted(script),
            )
        )
        observed, has_operators, parse_error = parse_command_argv(
            command,
            platform_name="nt",
            windows_powershell_core_host=WindowsPowerShellCoreHost(
                executable=pwsh,
                version="7.6.4",
                native_argument_passing="Windows",
                sha256="a" * 64,
            ),
        )
        assert observed[-1] == request_json
        assert has_operators is False
        assert parse_error == ""

        exact = reconcile_gateway_commands(
            (observed,),
            evidence,
            skill_source=skill,
            shim_directory=broker.shim_directory,
        )
        assert exact.passed is True

        mutations = (
            request_json.replace("Rifle_Thunder_Near", "Rifle_Thunder_Far", 1),
            request_json.replace("Thunder Near.wav", "Thunder Far.wav", 1),
            request_json.replace('"value":-2.0', '"value":-3.0', 1),
        )
        for mutated in mutations:
            assert mutated != request_json
            mismatched = (*observed[:-1], mutated)
            reconciliation = reconcile_gateway_commands(
                (mismatched,),
                evidence,
                skill_source=skill,
                shim_directory=broker.shim_directory,
            )
            assert reconciliation.passed is False
            assert "command 0: normalized argv differs from broker record" in (
                reconciliation.errors
            )
            assert "command 0: argv hash differs from broker record" in (
                reconciliation.errors
            )


def test_broker_accepts_empty_explicit_working_root_and_preserves_evidence(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    root = tmp_path / "owned"
    root.mkdir()
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        working_root=root,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        state_directory = broker.state_directory
        assert (state_directory / "fake-runner-calls.jsonl").is_file()
    assert (state_directory / "fake-runner-calls.jsonl").is_file()


def _metadata_step_with_limit(
    configured_limit: str | BoundedIntegerArgument,
    *,
    object_type: str = "ActorMixer",
    query_labels: tuple[str, ...] = ("output volume",),
) -> ExpectedGatewayStep:
    query_arguments = tuple(
        item
        for label in query_labels
        for item in ("--query", MetadataQueryArgument(label))
    )
    return ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            object_type,
            *query_arguments,
            "--limit",
            configured_limit,
        ),
    )


@pytest.mark.parametrize(
    ("configured_limit", "queries"),
    (
        ("2", ("looping", "routing", "volume", "playback limit", "instances")),
        ("3", ("fade time", "delay", "probability")),
        ("8", ("volume",)),
    ),
)
def test_metadata_query_slots_accept_the_configured_candidate_limit(
    tmp_path: Path,
    configured_limit: str,
    queries: tuple[str, ...],
) -> None:
    metadata_step = _metadata_step_with_limit(
        configured_limit,
        query_labels=queries,
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step,),
    )
    supplied_queries = tuple(
        item
        for index in range(len(queries))
        for item in ("--query", f"bounded query {index}")
    )
    actual = (
        "metadata",
        "discover",
        "--object-type",
        "ActorMixer",
        *supplied_queries,
        "--limit",
        configured_limit,
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        metadata_step,
        actual,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == actual


def test_metadata_query_slots_reject_omitted_fixed_query_slots(
    tmp_path: Path,
) -> None:
    metadata_step = _metadata_step_with_limit(
        "2",
        object_type="Sound",
        query_labels=(
            "looping enabled",
            "looping infinite",
            "ignore parent playback limit",
            "sound instance limit enabled",
            "maximum sound instances per object",
            "volume",
            "output bus routing",
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step,),
    )
    actual = (
        "metadata",
        "discover",
        "--object-type",
        "Sound",
        "--query",
        "looping",
        "--query",
        "playback instance limit",
        "--query",
        "volume",
        "--query",
        "output bus",
        "--limit",
        "3",
    )

    with pytest.raises(GatewayInvocationError, match="query slot count"):
        broker._validate_step(metadata_step, actual)  # noqa: SLF001

    complete = (
        "metadata",
        "discover",
        "--object-type",
        "Sound",
        "--query",
        "looping",
        "--query",
        "loop count",
        "--query",
        "ignore parent playback limit",
        "--query",
        "limit instances",
        "--query",
        "maximum instances",
        "--query",
        "volume",
        "--query",
        "output bus",
        "--limit",
        "2",
    )
    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        metadata_step,
        complete,
    )
    assert len(semantic_hash) == 64
    assert execution_arguments == complete


def test_metadata_query_slots_accept_only_canonical_bounded_limits(
    tmp_path: Path,
) -> None:
    metadata_step = _metadata_step_with_limit(
        BoundedIntegerArgument(1, 8),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step,),
    )
    hashes: dict[str, str] = {}
    for query_count, supplied_limit in ((1, "8"), (3, "3"), (8, "2")):
        queries = tuple(
            item
            for index in range(query_count)
            for item in ("--query", f"bounded query {index}")
        )
        actual = (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            *queries,
            "--limit",
            supplied_limit,
        )
        semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
            metadata_step,
            actual,
        )
        hashes[supplied_limit] = semantic_hash
        assert execution_arguments == actual
    assert len(set(hashes.values())) == 3

    for supplied_limit in ("0", "9", "01", "+3", "3.0"):
        with pytest.raises(GatewayInvocationError):
            broker._validate_step(  # noqa: SLF001
                metadata_step,
                (
                    "metadata",
                    "discover",
                    "--object-type",
                    "ActorMixer",
                    "--query",
                    "volume",
                    "--limit",
                    supplied_limit,
                ),
            )


@pytest.mark.parametrize(
    "runtime_order",
    (
        ("schema", "metadata.discover"),
        ("metadata.discover", "schema"),
    ),
)
def test_broker_accepts_only_declared_read_only_pair_linearizations(
    tmp_path: Path,
    runtime_order: tuple[str, str],
) -> None:
    skill = make_fake_skill(tmp_path)
    schema = ExpectedGatewayStep(
        "schema",
        "operation-schema",
        ("object.set",),
    )
    metadata = _metadata_step_with_limit(BoundedIntegerArgument(1, 8))
    commands = {
        "schema": ["operation-schema", "object.set"],
        "metadata.discover": [
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--limit",
            "8",
        ],
    }
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(schema, metadata),
        commutative_read_only_step_groups=(
            ("schema", "metadata.discover"),
        ),
        transport="tcp",
    ) as broker:
        completed = [
            run_model_command(broker, commands[name])
            for name in runtime_order
        ]
        assert [result.returncode for result in completed] == [0, 0]
        evidence = broker.evidence()
        assert evidence.expected_step_names == (
            "schema",
            "metadata.discover",
        )
        assert evidence.consumed_step_names == runtime_order
        assert tuple(record.step_name for record in evidence.records) == runtime_order
        assert evidence.passed is True
        reconciliation = broker.reconcile(
            [result.args for result in completed]
        )
        assert reconciliation.passed is True


@pytest.mark.parametrize(
    "runtime_order",
    (
        ("schema", "metadata.discover", "draft.start"),
        ("metadata.discover", "schema", "draft.start"),
        ("schema", "draft.start", "metadata.discover"),
    ),
)
def test_broker_accepts_only_dependency_safe_composer_setup_orders(
    tmp_path: Path,
    runtime_order: tuple[str, str, str],
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep("schema", "operation-schema", ("audio.import",)),
        _metadata_step_with_limit(BoundedIntegerArgument(1, 8)),
        ExpectedGatewayStep("draft.start", "draft-start", ("audio.import",)),
    )
    commands = {
        "schema": ["operation-schema", "audio.import"],
        "metadata.discover": [
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--limit",
            "8",
        ],
        "draft.start": ["draft-start", "audio.import"],
    }
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        commutative_read_only_step_groups=(("schema", "metadata.discover"),),
        commutative_composer_setup_step_groups=(
            ("metadata.discover", "draft.start"),
        ),
        transport="tcp",
    ) as broker:
        completed = [
            run_model_command(broker, commands[name])
            for name in runtime_order
        ]
        assert [result.returncode for result in completed] == [0, 0, 0]
        evidence = broker.evidence()
        assert evidence.consumed_step_names == runtime_order
        assert evidence.passed is True
        assert broker.reconcile([result.args for result in completed]).passed


@pytest.mark.parametrize(
    "runtime_order",
    (
        ("relationship.output_bus.01", "relationship.output_bus.02"),
        ("relationship.output_bus.02", "relationship.output_bus.01"),
    ),
)
def test_broker_accepts_declared_closed_exact_id_query_pair_linearizations(
    tmp_path: Path,
    runtime_order: tuple[str, str],
) -> None:
    skill = make_fake_skill(tmp_path)
    ids = {
        "relationship.output_bus.01": "{11111111-1111-1111-1111-111111111111}",
        "relationship.output_bus.02": "{22222222-2222-2222-2222-222222222222}",
    }

    def step(name: str) -> ExpectedGatewayStep:
        return ExpectedGatewayStep(
            name,
            "query-object",
            (
                "--object-id",
                ids[name],
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "type",
                "--return-field",
                "path",
            ),
        )

    canonical = tuple(ids)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=tuple(step(name) for name in canonical),
        commutative_read_only_step_groups=(canonical,),
        transport="tcp",
    ) as broker:
        completed = [
            run_model_command(
                broker,
                [
                    "query-object",
                    "--object-id",
                    ids[name],
                    "--return-field",
                    "id",
                    "--return-field",
                    "name",
                    "--return-field",
                    "type",
                    "--return-field",
                    "path",
                ],
            )
            for name in runtime_order
        ]

        assert [result.returncode for result in completed] == [0, 0]
        evidence = broker.evidence()
        assert evidence.consumed_step_names == runtime_order
        assert evidence.passed is True


@pytest.mark.parametrize(
    "runtime_order",
    tuple(itertools.permutations(("source", "dead_bus", "target_bus"))),
)
def test_broker_accepts_declared_closed_exact_identity_query_group_linearizations(
    tmp_path: Path,
    runtime_order: tuple[str, str, str],
) -> None:
    skill = make_fake_skill(tmp_path)
    selectors = {
        "source": ("--object-id", "{11111111-1111-1111-1111-111111111111}"),
        "dead_bus": ("--object-id", "{22222222-2222-2222-2222-222222222222}"),
        "target_bus": ("--path", r"\Busses\Default Work Unit\Main Audio Bus"),
    }

    def arguments(name: str) -> tuple[str, ...]:
        return (
            *selectors[name],
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        )

    canonical = tuple(selectors)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=tuple(
            ExpectedGatewayStep(name, "query-object", arguments(name))
            for name in canonical
        ),
        commutative_read_only_step_groups=(canonical,),
        transport="tcp",
    ) as broker:
        completed = [
            run_model_command(broker, ["query-object", *arguments(name)])
            for name in runtime_order
        ]

        assert [result.returncode for result in completed] == [0, 0, 0]
        evidence = broker.evidence()
        assert evidence.consumed_step_names == runtime_order
        assert evidence.passed is True
        assert broker.reconcile([result.args for result in completed]).passed


def test_broker_rejects_commutative_identity_group_with_an_internal_binding(
    tmp_path: Path,
) -> None:
    seed = ExpectedGatewayStep(
        "seed",
        "query-object",
        (
            "--object-id",
            "{11111111-1111-1111-1111-111111111111}",
            "--return-field",
            "id",
        ),
    )
    first = ExpectedGatewayStep(
        "first",
        "query-object",
        (
            "--object-id",
            ResponseBinding("seed", "/objects/0/id"),
            "--return-field",
            "id",
        ),
    )
    dependent = ExpectedGatewayStep(
        "dependent",
        "query-object",
        (
            "--object-id",
            ResponseBinding("first", "/objects/0/id"),
            "--return-field",
            "id",
        ),
    )

    with pytest.raises(ValueError, match="bindings precede the group"):
        CodexGatewayBroker(
            skill_source=tmp_path / "waapi-skill",
            expected_steps=(seed, first, dependent),
            commutative_read_only_step_groups=(("first", "dependent"),),
        )


def test_broker_rejects_an_unbounded_commutative_read_only_group(
    tmp_path: Path,
) -> None:
    names = tuple(f"read.{index}" for index in range(5))
    steps = tuple(
        ExpectedGatewayStep(
            name,
            "query-object",
            (
                "--object-id",
                f"{{11111111-1111-1111-1111-{index:012d}}}",
                "--return-field",
                "id",
            ),
        )
        for index, name in enumerate(names, start=1)
    )

    with pytest.raises(ValueError, match="between 2 and 4"):
        CodexGatewayBroker(
            skill_source=tmp_path / "waapi-skill",
            expected_steps=steps,
            commutative_read_only_step_groups=(names,),
        )


def test_broker_accepts_typed_schema_envelopes_for_public_discovery(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (
        ExpectedGatewayStep(
            "schema",
            "request-schema",
            ("ak.wwise.core.getInfo",),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        runner_environment={
            **os.environ,
            "FAKE_GATEWAY_MODE": "typed-schema",
        },
    ) as broker:
        result = run_model_command(
            broker,
            ["request-schema", "ak.wwise.core.getInfo"],
        )

    assert result.returncode == 0
    assert broker.evidence().passed


def test_broker_compares_business_query_meaning_not_option_group_order(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = (
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--path-segment",
        "Default Work Unit",
        "--relationship",
        "descendants",
        "--predicate",
        "kind-is",
        "all-sounds",
        "--predicate",
        "volume-db-at-most",
        "-6.0",
        "--max-results",
        "12",
        "--include",
        "volume-db",
        "--include",
        "notes",
    )
    reordered = [
        "query-object",
        "--include",
        "notes",
        "--predicate",
        "volume-db-at-most",
        "-6.0",
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--path-segment",
        "Default Work Unit",
        "--max-results",
        "12",
        "--predicate",
        "kind-is",
        "all-sounds",
        "--include",
        "volume-db",
        "--relationship",
        "descendants",
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("query", "query-object", expected),),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, reordered)

    assert result.returncode == 0
    assert broker.evidence().passed


def test_broker_rejects_native_leading_separator_in_business_query(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = (
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--relationship",
        "descendants",
        "--max-results",
        "12",
    )
    supplied = [
        "query-object",
        "--path-segment",
        r"\Actor-Mixer Hierarchy",
        "--relationship",
        "descendants",
        "--max-results",
        "12",
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("query", "query-object", expected),),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, supplied)

    assert result.returncode != 0
    assert not broker.evidence().passed


def test_broker_accepts_equivalent_business_query_number_spelling(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = (
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--relationship",
        "descendants",
        "--predicate",
        "volume-db-at-most",
        "-6.0",
        "--max-results",
        "12",
    )
    supplied = [
        "query-object",
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--relationship",
        "descendants",
        "--predicate",
        "volume-db-at-most",
        "-6",
        "--max-results",
        "12",
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("query", "query-object", expected),),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, supplied)

    assert result.returncode == 0
    assert broker.evidence().passed


def test_broker_accepts_closed_soundbank_topic_business_shortcuts(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    handle = "tvc1-8ef27a61d0fe6eb7197dad1d055ef960"
    expected = (
        topic,
        "--event-count",
        "3",
        "--topic-contract-digest",
        "a" * 64,
        "--topic-option",
        "include",
        "id",
        "--topic-option",
        "include",
        "name",
        "--topic-option",
        "include",
        "type",
        "--topic-option",
        "include",
        "path",
        "--event-entry-as",
        "platform",
        "-",
        "name",
        handle,
        "Windows",
    )
    supplied = [
        "--timeout",
        "120",
        "wait-topic",
        topic,
        "--event-count",
        "3",
        "--topic-contract-digest",
        "a" * 64,
        "--include-object-identity",
        "--match-platform-name",
        "Windows",
    ]
    step = ExpectedGatewayStep(
        "wait",
        "wait-topic",
        expected,
        gateway_global_arguments=("--timeout", "120"),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, supplied)

    assert result.returncode == 0
    assert broker.evidence().passed


def test_broker_accepts_soundbank_match_shortcut_before_identity_projection(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.soundbank.generated"
    expected = (
        topic,
        "--event-count",
        BoundedIntegerArgument(3, 64),
        "--topic-contract-digest",
        "a" * 64,
        "--topic-option",
        "include",
        "id",
        "--topic-option",
        "include",
        "name",
        "--topic-option",
        "include",
        "type",
        "--topic-option",
        "include",
        "path",
        "--event-match",
        "soundbank-name",
        "Weapons_Core",
    )
    supplied = [
        "--timeout",
        "30",
        "wait-topic",
        topic,
        "--event-count",
        "64",
        "--topic-contract-digest",
        "a" * 64,
        "--match-soundbank-name",
        "Weapons_Core",
        "--include-object-identity",
    ]
    step = ExpectedGatewayStep(
        "wait",
        "wait-topic",
        expected,
        gateway_global_arguments=("--timeout", "30"),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, supplied)

    assert result.returncode == 0
    assert broker.evidence().passed


def test_broker_rejects_a_different_soundbank_topic_shortcut_value(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    handle = "tvc1-8ef27a61d0fe6eb7197dad1d055ef960"
    step = ExpectedGatewayStep(
        "wait",
        "wait-topic",
        (
            topic,
            "--event-count",
            "1",
            "--topic-contract-digest",
            "a" * 64,
            "--topic-option",
            "include",
            "id",
            "--topic-option",
            "include",
            "name",
            "--topic-option",
            "include",
            "type",
            "--topic-option",
            "include",
            "path",
            "--event-entry-as",
            "platform",
            "-",
            "name",
            handle,
            "Windows",
        ),
    )
    with CodexGatewayBroker(
        skill_source=make_fake_skill(tmp_path),
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            [
                "wait-topic",
                topic,
                "--event-count",
                "1",
                "--topic-contract-digest",
                "a" * 64,
                "--include-object-identity",
                "--match-platform-name",
                "Mac",
            ],
        )

    assert result.returncode == 126
    assert broker.evidence().terminal_state == "FAILED"


def test_broker_accepts_the_closed_all_sound_business_alias(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = (
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--predicate",
        "kind-is",
        "all-sounds",
        "--max-results",
        "12",
    )
    supplied = [
        "query-object",
        "--path-segment",
        "Actor-Mixer Hierarchy",
        "--predicate",
        "kind-is",
        "sound",
        "--max-results",
        "12",
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("query", "query-object", expected),),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, supplied)

    assert result.returncode == 0
    assert broker.evidence().passed


def test_broker_does_not_treat_sound_sfx_as_all_sounds(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = (
        "--kind",
        "all-sounds",
        "--max-results",
        "12",
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("query", "query-object", expected),),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            ["query-object", "--kind", "sound-sfx", "--max-results", "12"],
        )

    assert result.returncode != 0
    assert broker.evidence().passed is False


@pytest.mark.parametrize("read_schema", (False, True))
def test_broker_accepts_one_optional_initial_query_schema(
    tmp_path: Path,
    read_schema: bool,
) -> None:
    skill = make_fake_skill(tmp_path)
    query_arguments = ("--kind", "all-sounds", "--max-results", "12")
    steps = (
        ExpectedGatewayStep("query-schema", "query-schema"),
        ExpectedGatewayStep("query", "query-object", query_arguments),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_initial_query_schema=True,
        transport="tcp",
    ) as broker:
        completed = []
        if read_schema:
            completed.append(run_model_command(broker, ["query-schema"]))
        completed.append(
            run_model_command(broker, ["query-object", *query_arguments])
        )

    assert all(result.returncode == 0 for result in completed)
    evidence = broker.evidence()
    assert evidence.passed
    assert evidence.expected_step_names == (
        ("query-schema", "query") if read_schema else ("query",)
    )


def test_broker_optional_query_schema_rejects_the_advanced_contract(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("query-schema", "query-schema"),
            ExpectedGatewayStep(
                "query",
                "query-object",
                ("--kind", "all-sounds", "--max-results", "12"),
            ),
        ),
        optional_initial_query_schema=True,
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["query-schema", "--advanced"])

    assert result.returncode != 0
    assert broker.evidence().passed is False


@pytest.mark.parametrize(
    "schema_arguments",
    (
        (),
        (("query-schema",),),
        (("query-schema", "--advanced"),),
        (("query-schema",), ("query-schema", "--advanced")),
    ),
)
def test_broker_accepts_bounded_optional_query_schema_disclosures(
    tmp_path: Path,
    schema_arguments: tuple[tuple[str, ...], ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    query_arguments = ("--kind", "all-sounds", "--max-results", "12")
    steps = (
        ExpectedGatewayStep("query-schema", "query-schema"),
        ExpectedGatewayStep(
            "query-schema.advanced",
            "query-schema",
            ("--advanced",),
        ),
        ExpectedGatewayStep("query", "query-object", query_arguments),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        optional_query_schema_step_names=(
            "query-schema",
            "query-schema.advanced",
        ),
        transport="tcp",
    ) as broker:
        results = [
            run_model_command(broker, arguments)
            for arguments in schema_arguments
        ]
        results.append(
            run_model_command(broker, ["query-object", *query_arguments])
        )

    assert all(result.returncode == 0 for result in results)
    evidence = broker.evidence()
    assert evidence.passed
    assert evidence.expected_step_names == (
        tuple(
            "query-schema.advanced"
            if arguments == ("query-schema", "--advanced")
            else "query-schema"
            for arguments in schema_arguments
        )
        + ("query",)
    )


def test_broker_rejects_a_different_business_query_predicate(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    expected = (
        "--kind",
        "all-sounds",
        "--predicate",
        "volume-db-at-most",
        "-6.0",
        "--max-results",
        "12",
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("query", "query-object", expected),),
        transport="tcp",
    ) as broker:
        result = run_model_command(
            broker,
            [
                "query-object",
                "--kind",
                "all-sounds",
                "--predicate",
                "volume-db-at-most",
                "-5.0",
                "--max-results",
                "12",
            ],
        )

    assert result.returncode != 0
    assert broker.evidence().passed is False


def test_broker_rejects_commutative_query_pair_outside_closed_identity_shape(
    tmp_path: Path,
) -> None:
    broad = ExpectedGatewayStep(
        "broad",
        "query-object",
        ("--path", r"\Actor-Mixer Hierarchy", "--all-results"),
    )
    exact = ExpectedGatewayStep(
        "exact",
        "query-object",
        (
            "--object-id",
            "{11111111-1111-1111-1111-111111111111}",
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        ),
    )

    with pytest.raises(ValueError, match="closed exact-ID"):
        CodexGatewayBroker(
            skill_source=tmp_path / "waapi-skill",
            expected_steps=(broad, exact),
            commutative_read_only_step_groups=(("broad", "exact"),),
        )


def test_broker_commutative_pair_still_rejects_duplicates_and_preview_races(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    schema = ExpectedGatewayStep(
        "schema",
        "operation-schema",
        ("object.set",),
    )
    metadata = _metadata_step_with_limit(BoundedIntegerArgument(1, 8))
    preview = ExpectedGatewayStep("preview", "preview")
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(schema, metadata, preview),
        commutative_read_only_step_groups=(
            ("schema", "metadata.discover"),
        ),
        transport="tcp",
    ) as broker:
        first = run_model_command(
            broker,
            [
                "metadata",
                "discover",
                "--object-type",
                "ActorMixer",
                "--query",
                "volume",
                "--limit",
                "8",
            ],
        )
        duplicate = run_model_command(
            broker,
            [
                "metadata",
                "discover",
                "--object-type",
                "ActorMixer",
                "--query",
                "volume",
                "--limit",
                "8",
            ],
        )
        assert first.returncode == 0
        assert duplicate.returncode != 0
        assert broker.evidence().passed is False

    other_root = tmp_path / "other"
    other_root.mkdir()
    other_skill = make_fake_skill(other_root)
    with CodexGatewayBroker(
        skill_source=other_skill,
        expected_steps=(schema, metadata, preview),
        commutative_read_only_step_groups=(
            ("schema", "metadata.discover"),
        ),
        transport="tcp",
    ) as broker:
        raced = run_model_command(broker, ["preview"])
        assert raced.returncode != 0
        assert broker.evidence().consumed_step_names == ()


@pytest.mark.parametrize(
    "wrong_command",
    (
        ["operation-schema", "object.create"],
        [
            "metadata",
            "discover",
            "--object-type",
            "Sound",
            "--query",
            "volume",
            "--limit",
            "8",
        ],
    ),
)
def test_broker_commutative_pair_rejects_wrong_operation_or_object_scope(
    tmp_path: Path,
    wrong_command: list[str],
) -> None:
    skill = make_fake_skill(tmp_path)
    schema = ExpectedGatewayStep(
        "schema",
        "operation-schema",
        ("object.set",),
    )
    metadata = _metadata_step_with_limit(BoundedIntegerArgument(1, 8))
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(schema, metadata),
        commutative_read_only_step_groups=(
            ("schema", "metadata.discover"),
        ),
        transport="tcp",
    ) as broker:
        rejected = run_model_command(broker, wrong_command)
        assert rejected.returncode != 0
        evidence = broker.evidence()
        assert evidence.consumed_step_names == ()
        assert len(evidence.rejected_records) == 1


@pytest.mark.parametrize("supplied_limit", ("1", "2", "3", "4", "7"))
def test_metadata_query_slots_reject_a_limit_mismatched_with_actual_query_count(
    tmp_path: Path,
    supplied_limit: str,
) -> None:
    metadata_step = _metadata_step_with_limit("8")
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step,),
    )

    with pytest.raises(GatewayInvocationError, match="actual query count"):
        broker._validate_step(  # noqa: SLF001
            metadata_step,
            (
                "metadata",
                "discover",
                "--object-type",
                "ActorMixer",
                "--query",
                "volume",
                "--limit",
                supplied_limit,
            ),
        )


@pytest.mark.parametrize("configured_limit", ("0", "9", "01", "+2", " 2", "2 "))
def test_metadata_query_slots_reject_a_noncanonical_configured_limit(
    tmp_path: Path,
    configured_limit: str,
) -> None:
    metadata_step = _metadata_step_with_limit(configured_limit)
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step,),
    )

    with pytest.raises(
        GatewayInvocationError,
        match="canonical --limit.*1 through 8",
    ):
        broker._validate_step(  # noqa: SLF001
            metadata_step,
            (
                "metadata",
                "discover",
                "--object-type",
                "ActorMixer",
                "--query",
                "volume",
                "--limit",
                configured_limit,
            ),
        )


def _archive_test_weather_agent_metadata_step_crosses_broker_validation(
    tmp_path: Path,
) -> None:
    from .support.codex_integration_weather_runtime_v1 import (  # noqa: PLC0415
        ACTION_METADATA_QUERIES,
        RTPC_METADATA_QUERIES,
        SOUND_METADATA_QUERIES,
        _build_metadata_workflow_protocol,
    )

    def request(operation: str, sentinel: int) -> dict[str, object]:
        arguments: dict[str, object] = {"sentinel": sentinel}
        if operation == "audio.import":
            arguments = {
                "import_operation": "createNew",
                "imports": [
                    {
                        "audio_file": native_absolute_test_path("inputs", "rain.wav"),
                        "object_path": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"
                        ),
                        "object_type": "Sound SFX",
                        "import_language": "SFX",
                    }
                ],
            }
        elif operation == "object.set":
            arguments = {
                "objects": [
                    {
                        "object": {
                            "kind": "path",
                            "value": r"\Events\Default Work Unit\Weather\Action",
                        },
                        "properties": [
                            {"name": "FadeTime", "value": 0.25}
                        ],
                    }
                ]
            }
        elif operation == "object.setRTPC":
            arguments = {
                "object": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                },
                "property": "Volume",
                "control_input": {
                    "kind": "path",
                    "value": r"\Game Parameters\Default Work Unit\RainIntensity",
                },
                "points": [
                    {"x": 0.0, "y": -96.0, "shape": "Linear"},
                    {"x": 100.0, "y": 0.0, "shape": "Linear"},
                ],
                "mode": "add_or_replace",
            }
        return {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2022.1",
            "operation": operation,
            "arguments": arguments,
        }

    volume_projection = (
        MetadataTokenProjection("Volume", "property", "Real64"),
    )
    protocol = _build_metadata_workflow_protocol(
        (
            request("audio.import", 1),
            request("object.set", 2),
            request("object.setRTPC", 3),
        ),
        metadata=(
            (
                "Sound",
                SOUND_METADATA_QUERIES,
                ("Volume",),
                volume_projection,
                "wire_exact",
            ),
            (
                "Action",
                ACTION_METADATA_QUERIES,
                ("FadeTime",),
                (
                    MetadataTokenProjection(
                        "FadeTime",
                        "property",
                        "Real64",
                    ),
                ),
                "wire_exact",
            ),
            (
                "Sound",
                RTPC_METADATA_QUERIES,
                ("Volume",),
                volume_projection,
                "wire_exact",
            ),
        ),
    )
    assert [
        step.name for step in protocol.steps if step.subcommand == "metadata"
    ] == ["tx02.metadata", "tx03.metadata"]
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=protocol.steps,
    )
    rtpc_metadata_step = next(
        step for step in protocol.steps if step.name == "tx03.metadata"
    )
    complete_rtpc_queries = (
        "metadata",
        "discover",
        "--object-type",
        "Sound",
        *tuple(
            item
            for query in RTPC_METADATA_QUERIES
            for item in ("--query", query)
        ),
        "--limit",
        "8",
    )
    complete_hash, complete_execution = broker._validate_step(  # noqa: SLF001
        rtpc_metadata_step,
        complete_rtpc_queries,
    )
    assert len(complete_hash) == 64
    assert complete_execution == complete_rtpc_queries
    metadata_step = next(
        step for step in protocol.steps if step.name == "tx02.metadata"
    )
    assert metadata_step.arguments[-2:] == ("--limit", "8")
    actual = (
        "metadata",
        "discover",
        "--object-type",
        "Action",
        *tuple(
            item
            for query in ACTION_METADATA_QUERIES
            for item in ("--query", query)
        ),
        "--limit",
        "8",
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        metadata_step,
        actual,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == actual


def test_metadata_query_slots_accept_rephrasing_but_keep_a_closed_scope(
    tmp_path: Path,
) -> None:
    metadata_step = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            MetadataQueryArgument("output volume"),
            "--query",
            MetadataQueryArgument("voice gain"),
            "--limit",
            "8",
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step,),
    )
    actual = (
        "metadata",
        "discover",
        "--object-type",
        "ActorMixer",
        "--query",
        "音量属性",
        "--query",
        "声音增益",
        "--limit",
        "8",
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        metadata_step,
        actual,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == actual
    reordered_actual = (
        "metadata",
        "discover",
        "--query",
        "音量属性",
        "--object-type",
        "ActorMixer",
        "--query",
        "声音增益",
        "--limit",
        "8",
    )
    reordered_hash, reordered_execution = broker._validate_step(  # noqa: SLF001
        metadata_step,
        reordered_actual,
    )
    assert len(reordered_hash) == 64
    assert reordered_execution == reordered_actual
    for query_count in (1, 3, 8):
        queries = tuple(
            item
            for index in range(query_count)
            for item in ("--query", f"bounded query {index}")
        )
        variable_actual = (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            *queries,
            "--limit",
            "8" if query_count <= 2 else "3" if query_count <= 4 else "2",
        )
        with pytest.raises(GatewayInvocationError, match="query slot count"):
            broker._validate_step(metadata_step, variable_actual)  # noqa: SLF001
    with pytest.raises(GatewayInvocationError, match="must be distinct"):
        broker._validate_step(  # noqa: SLF001
            metadata_step,
            (
                "metadata",
                "discover",
                "--object-type",
                "ActorMixer",
                "--query",
                "same query",
                "--query",
                "same   query",
                "--limit",
                "8",
            ),
        )
    with pytest.raises(GatewayInvocationError, match="bounded, non-empty"):
        broker._validate_step(  # noqa: SLF001
            metadata_step,
            (
                "metadata",
                "discover",
                "--object-type",
                "ActorMixer",
                "--query",
                "volume\tproperty",
                "--query",
                "gain",
                "--limit",
                "8",
            ),
        )
    for malformed in (
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--limit",
            "8",
        ),
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            *tuple(
                item
                for index in range(9)
                for item in ("--query", f"query {index}")
            ),
            "--limit",
            "8",
        ),
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--query",
            "--limit",
            "8",
        ),
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--limit",
            "7",
        ),
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--limit",
            "8",
            "--extra",
        ),
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--limit",
            "8",
        ),
        (
            "metadata",
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            "volume",
            "--limit",
            "8",
            "--limit",
            "8",
        ),
    ):
        with pytest.raises(GatewayInvocationError, match="metadata discover"):
            broker._validate_step(metadata_step, malformed)  # noqa: SLF001
    with pytest.raises(GatewayInvocationError, match="must be exactly"):
        broker._validate_step(  # noqa: SLF001
            metadata_step,
            (
                "metadata",
                "discover",
                "--object-type",
                "Sound",
                "--query",
                "volume",
                "--query",
                "gain",
                "--limit",
                "8",
            ),
        )


def test_metadata_bound_preview_requires_tokens_from_the_exact_prior_scope(
    tmp_path: Path,
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "object": {"kind": "path", "value": r"\Root\Target"},
            "properties": [{"name": "Volume", "value": -3}],
        },
    }
    metadata_step = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            MetadataQueryArgument("output volume"),
            "--limit",
            "8",
        ),
    )
    trusted_projection = project_required_metadata_tokens(
        _metadata_discovery_payload(),
        object_type="ActorMixer",
        required_tokens=("Volume", "OverrideOutput"),
    )
    assert trusted_projection == (
        MetadataTokenProjection("Volume", "property", "Real32"),
        MetadataTokenProjection("OverrideOutput", "property", "Boolean"),
    )
    preview_step = ExpectedGatewayStep(
        "tx01.preview",
        "preview",
        (
            "--apply",
            "--request-json",
            MetadataBoundJsonArgument(
                expected=request,
                metadata_step="metadata.discover",
                object_type="ActorMixer",
                required_tokens=("Volume", "OverrideOutput"),
                expected_required_token_projection=trusted_projection,
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step, preview_step),
    )
    preview_argv = (
        "preview",
        "--apply",
        "--request-json",
        json.dumps(request, ensure_ascii=False, separators=(",", ":")),
    )

    with pytest.raises(GatewayInvocationError, match="source.*unavailable"):
        broker._validate_step(preview_step, preview_argv)  # noqa: SLF001

    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload()
    )
    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        preview_step,
        preview_argv,
    )
    assert len(semantic_hash) == 64
    assert execution_arguments == preview_argv

    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload(dependency_names=())
    )
    with pytest.raises(GatewayInvocationError, match="absent.*OverrideOutput"):
        broker._validate_step(preview_step, preview_argv)  # noqa: SLF001

    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload(object_type="Sound")
    )
    with pytest.raises(GatewayInvocationError, match="configured live object-type"):
        broker._validate_step(preview_step, preview_argv)  # noqa: SLF001

    wrong_kind = _metadata_discovery_payload()
    wrong_kind["agent_result"]["candidates"][0]["kind"] = "reference"
    broker._payloads_by_step["metadata.discover"] = wrong_kind  # noqa: SLF001
    with pytest.raises(GatewayInvocationError, match="projection differs"):
        broker._validate_step(preview_step, preview_argv)  # noqa: SLF001

    wrong_type = _metadata_discovery_payload()
    wrong_type["agent_result"]["candidates"][0]["metadata"]["type"] = "Int32"
    broker._payloads_by_step["metadata.discover"] = wrong_type  # noqa: SLF001
    with pytest.raises(GatewayInvocationError, match="projection differs"):
        broker._validate_step(preview_step, preview_argv)  # noqa: SLF001

    changed_request = json.loads(json.dumps(request))
    changed_request["arguments"]["properties"][0]["value"] = -2
    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(changed_request, separators=(",", ":")),
            ),
        )


def _object_set_metadata_broker(
    tmp_path: Path,
    expected_request: dict[str, object],
) -> tuple[CodexGatewayBroker, ExpectedGatewayStep]:
    metadata_step = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            "ActorMixer",
            "--query",
            MetadataQueryArgument("volume"),
            "--limit",
            "8",
        ),
    )
    preview_step = ExpectedGatewayStep(
        "tx01.preview",
        "preview",
        (
            "--apply",
            "--request-json",
            MetadataBoundJsonArgument(
                expected=expected_request,
                metadata_step="metadata.discover",
                object_type="ActorMixer",
                required_tokens=("Volume",),
                expected_required_token_projection=(
                    MetadataTokenProjection(
                        "Volume",
                        "property",
                        "Real32",
                    ),
                ),
                equivalence="object_set_v1",
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step, preview_step),
    )
    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload(
            candidate_names=("Volume",),
            dependency_names=(),
        )
    )
    return broker, preview_step


def _object_set_metadata_request() -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "path",
                        "value": r"\Actor-Mixer Hierarchy\Target",
                    },
                    "properties": [{"name": "Volume", "value": -3}],
                }
            ]
        },
    }


@pytest.mark.parametrize(
    ("expected_defaults", "actual_defaults"),
    (
        ({}, {"list_mode": "append"}),
        ({"list_mode": "append"}, {}),
        ({}, {"auto_add_to_source_control": False}),
        ({"auto_add_to_source_control": False}, {}),
        ({}, {"on_name_conflict": "fail"}),
        ({"on_name_conflict": "fail"}, {}),
        (
            {},
            {
                "list_mode": "append",
                "on_name_conflict": "fail",
                "auto_add_to_source_control": False,
            },
        ),
    ),
)
def test_object_set_metadata_equivalence_accepts_only_schema_root_defaults(
    expected_defaults: dict[str, object],
    actual_defaults: dict[str, object],
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    expected_arguments = expected_request["arguments"]
    assert isinstance(expected_arguments, dict)
    expected_arguments.update(expected_defaults)
    actual_request = json.loads(json.dumps(expected_request))
    actual_arguments = actual_request["arguments"]
    for field in expected_defaults:
        actual_arguments.pop(field, None)
    actual_arguments.update(actual_defaults)
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )
    preview_argv = (
        "preview",
        "--apply",
        "--request-json",
        json.dumps(actual_request, separators=(",", ":")),
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        preview_step,
        preview_argv,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == preview_argv


@pytest.mark.parametrize(
    "difference",
    (
        "nondefault-list-mode",
        "nondefault-auto-add",
        "nondefault-on-name-conflict",
        "row-level-list-mode",
        "unknown-root-field",
    ),
)
def test_object_set_metadata_equivalence_rejects_every_unreviewed_difference(
    difference: str,
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    actual_request = json.loads(json.dumps(expected_request))
    arguments = actual_request["arguments"]
    row = arguments["objects"][0]
    if difference == "nondefault-list-mode":
        arguments["list_mode"] = "replaceAll"
    elif difference == "nondefault-auto-add":
        arguments["auto_add_to_source_control"] = True
    elif difference == "nondefault-on-name-conflict":
        arguments["on_name_conflict"] = "rename"
    elif difference == "row-level-list-mode":
        row["list_mode"] = "append"
    elif difference == "unknown-root-field":
        arguments["unreviewed_default"] = False
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual_request, separators=(",", ":")),
            ),
        )


def test_object_set_metadata_equivalence_keeps_direct_child_identity_exact(
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    expected_request["arguments"]["objects"][0]["object"] = {
        "kind": "direct-child",
        "parent": {
            "kind": "path",
            "value": r"\Events\Default Work Unit\Weather\Play_Rain",
        },
        "type": "Action",
    }
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )
    exact_request = json.loads(json.dumps(expected_request))
    exact_argv = (
        "preview",
        "--apply",
        "--request-json",
        json.dumps(exact_request, separators=(",", ":")),
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        preview_step,
        exact_argv,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == exact_argv

    variants = []
    wrong_parent = json.loads(json.dumps(expected_request))
    wrong_parent["arguments"]["objects"][0]["object"]["parent"]["value"] = (
        r"\Events\Default Work Unit\Weather\Play_Wind"
    )
    variants.append(wrong_parent)
    wrong_type = json.loads(json.dumps(expected_request))
    wrong_type["arguments"]["objects"][0]["object"]["type"] = "Event"
    variants.append(wrong_type)
    legacy_waql = json.loads(json.dumps(expected_request))
    legacy_waql["arguments"]["objects"][0]["object"] = {
        "kind": "waql",
        "value": (
            'from object "\\Events\\Default Work Unit\\Weather\\Play_Rain" '
            'select children where type = "Action" take 2'
        ),
    }
    variants.append(legacy_waql)

    for changed_request in variants:
        with pytest.raises(GatewayInvocationError, match="semantically equal"):
            broker._validate_step(  # noqa: SLF001
                preview_step,
                (
                    "preview",
                    "--apply",
                    "--request-json",
                    json.dumps(changed_request, separators=(",", ":")),
                ),
            )


def test_object_set_metadata_equivalence_accepts_equal_live_real_number_spellings(
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    expected_objects = expected_request["arguments"]["objects"]
    expected_objects[0]["properties"][0]["value"] = -1.0
    for suffix, value in (("B", -2.0), ("C", -4.0)):
        row = json.loads(json.dumps(expected_objects[0]))
        row["object"]["value"] += suffix
        row["properties"][0]["value"] = value
        expected_objects.append(row)
    actual_request = json.loads(json.dumps(expected_request))
    for row in actual_request["arguments"]["objects"]:
        row["properties"][0]["value"] = int(row["properties"][0]["value"])
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )
    preview_argv = (
        "preview",
        "--apply",
        "--request-json",
        json.dumps(actual_request, separators=(",", ":")),
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        preview_step,
        preview_argv,
    )

    assert len(semantic_hash) == 64
    assert execution_arguments == preview_argv


@pytest.mark.parametrize(
    ("expected_value", "actual_value"),
    (
        (-3.0, True),
        (-3.0, "-3"),
        (-3.0, -2.999999999999),
        (float(2**53 + 1), 2**53 + 1),
        (1.0, 10**400),
    ),
)
def test_object_set_metadata_equivalence_rejects_non_equivalent_real_values(
    expected_value: object,
    actual_value: object,
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    expected_request["arguments"]["objects"][0]["properties"][0][
        "value"
    ] = expected_value
    actual_request = json.loads(json.dumps(expected_request))
    actual_request["arguments"]["objects"][0]["properties"][0][
        "value"
    ] = actual_value
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual_request, separators=(",", ":")),
            ),
        )


def test_object_set_metadata_equivalence_keeps_integer_properties_type_strict(
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    actual_request = json.loads(json.dumps(expected_request))
    actual_request["arguments"]["objects"][0]["properties"][0]["value"] = -3.0
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )
    expected_argument = preview_step.arguments[2]
    assert isinstance(expected_argument, MetadataBoundJsonArgument)
    strict_argument = MetadataBoundJsonArgument(
        expected=expected_argument.expected,
        metadata_step=expected_argument.metadata_step,
        object_type=expected_argument.object_type,
        required_tokens=expected_argument.required_tokens,
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Int32"),
        ),
        equivalence="object_set_v1",
    )
    strict_step = ExpectedGatewayStep(
        preview_step.name,
        preview_step.subcommand,
        (*preview_step.arguments[:2], strict_argument),
    )
    metadata_payload = _metadata_discovery_payload(
        candidate_names=("Volume",),
        dependency_names=(),
    )
    metadata_payload["agent_result"]["candidates"][0]["metadata"]["type"] = "Int32"
    broker._payloads_by_step["metadata.discover"] = metadata_payload  # noqa: SLF001

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            strict_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual_request, separators=(",", ":")),
            ),
        )


def test_object_set_metadata_equivalence_requires_a_live_type_projection(
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    expected_request["arguments"]["objects"][0]["properties"][0]["value"] = -3.0
    actual_request = json.loads(json.dumps(expected_request))
    actual_request["arguments"]["objects"][0]["properties"][0]["value"] = -3
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )
    expected_argument = preview_step.arguments[2]
    assert isinstance(expected_argument, MetadataBoundJsonArgument)
    unprojected_argument = MetadataBoundJsonArgument(
        expected=expected_argument.expected,
        metadata_step=expected_argument.metadata_step,
        object_type=expected_argument.object_type,
        required_tokens=expected_argument.required_tokens,
        equivalence="object_set_v1",
    )
    unprojected_step = ExpectedGatewayStep(
        preview_step.name,
        preview_step.subcommand,
        (*preview_step.arguments[:2], unprojected_argument),
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            unprojected_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual_request, separators=(",", ":")),
            ),
        )


def test_object_set_metadata_equivalence_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    expected_request = _object_set_metadata_request()
    broker, preview_step = _object_set_metadata_broker(
        tmp_path,
        expected_request,
    )
    serialized = json.dumps(expected_request, separators=(",", ":"))
    duplicate = serialized.replace(
        '"objects":',
        '"list_mode":"append","list_mode":"append","objects":',
        1,
    )

    with pytest.raises(GatewayInvocationError, match="duplicate JSON"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                duplicate,
            ),
        )


def _audio_import_equivalence_requests() -> tuple[
    dict[str, object],
    dict[str, object],
]:
    expected: dict[str, object] = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": r"\Actor-Mixer Hierarchy\A",
                    "audio_file": "/owned/a.wav",
                    "properties": [
                        {"name": "Volume", "value": -1},
                    ],
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": r"\Master-Mixer Hierarchy\Close",
                            },
                        }
                    ],
                },
                {
                    "object_path": r"\Actor-Mixer Hierarchy\B",
                    "audio_file": "/owned/b.wav",
                },
            ],
            "defaults": {
                "properties": [
                    {"name": "Volume", "value": -3},
                    {"name": "IsLoopingEnabled", "value": True},
                ],
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {
                            "kind": "path",
                            "value": r"\Master-Mixer Hierarchy\Main",
                        },
                    }
                ],
            },
            "import_operation": "createNew",
        },
    }
    expanded: dict[str, object] = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": r"\Actor-Mixer Hierarchy\A",
                    "audio_file": "/owned/a.wav",
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "Volume", "value": -1},
                    ],
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": r"\Master-Mixer Hierarchy\Close",
                            },
                        }
                    ],
                },
                {
                    "object_path": r"\Actor-Mixer Hierarchy\B",
                    "audio_file": "/owned/b.wav",
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "Volume", "value": -3},
                    ],
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": r"\Master-Mixer Hierarchy\Main",
                            },
                        }
                    ],
                },
            ],
            "import_operation": "createNew",
        },
    }
    return expected, expanded


def _audio_import_equivalence_broker(
    tmp_path: Path,
    expected_request: dict[str, object],
) -> tuple[CodexGatewayBroker, ExpectedGatewayStep]:
    metadata_step = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            "Sound",
            "--query",
            MetadataQueryArgument("looping and routing"),
            "--limit",
            "8",
        ),
    )
    preview_step = ExpectedGatewayStep(
        "tx01.preview",
        "preview",
        (
            "--apply",
            "--request-json",
            MetadataBoundJsonArgument(
                expected=expected_request,
                metadata_step="metadata.discover",
                object_type="Sound",
                required_tokens=(
                    "Volume",
                    "IsLoopingEnabled",
                    "OutputBus",
                ),
                equivalence="audio_import_v1",
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step, preview_step),
    )
    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload(
            object_type="Sound",
            candidate_names=(
                "Volume",
                "IsLoopingEnabled",
                "OutputBus",
            ),
            dependency_names=(),
        )
    )
    return broker, preview_step


def test_audio_import_absolute_paths_keep_added_import_location_wire_significant(
    tmp_path: Path,
) -> None:
    expected, _ = _audio_import_equivalence_requests()
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )
    with_inferred_common_parent = json.loads(json.dumps(expected))
    with_inferred_common_parent["arguments"]["defaults"]["import_location"] = {
        "kind": "path",
        "value": r"\Actor-Mixer Hierarchy",
    }

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(with_inferred_common_parent, separators=(",", ":")),
            ),
        )


def _reference_activation_equivalence_broker(
    tmp_path: Path,
) -> tuple[
    CodexGatewayBroker,
    ExpectedGatewayStep,
    dict[str, object],
]:
    expected: dict[str, object] = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit"
                        r"\Weather"
                    ),
                    "object_type": "ActorMixer",
                },
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit"
                        r"\Weather\<Sound>Rain"
                    ),
                    "object_type": "Sound",
                    "audio_file": "/owned/rain.wav",
                    "properties": [
                        {
                            "name": "UseMaxSoundPerInstance",
                            "value": True,
                        },
                        {"name": "OverrideOutput", "value": True},
                    ],
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": (
                                    r"\Master-Mixer Hierarchy"
                                    r"\Default Work Unit\Weather"
                                ),
                            },
                        }
                    ],
                },
            ],
            "import_operation": "createNew",
        },
    }
    metadata_step = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            "Sound",
            "--query",
            MetadataQueryArgument("routing and playback limit"),
            "--limit",
            "8",
        ),
    )
    preview_step = ExpectedGatewayStep(
        "tx01.preview",
        "preview",
        (
            "--apply",
            "--request-json",
            MetadataBoundJsonArgument(
                expected=expected,
                metadata_step="metadata.discover",
                object_type="Sound",
                required_tokens=(
                    "UseMaxSoundPerInstance",
                    "OutputBus",
                    "OverrideOutput",
                ),
                expected_required_token_projection=(
                    MetadataTokenProjection(
                        "UseMaxSoundPerInstance",
                        "property",
                        "Boolean",
                    ),
                    MetadataTokenProjection(
                        "OutputBus",
                        "reference",
                        "",
                    ),
                    MetadataTokenProjection(
                        "OverrideOutput",
                        "property",
                        "Boolean",
                    ),
                ),
                equivalence="audio_import_v1",
                gateway_derived_reference_activations=(
                    GatewayDerivedReferenceActivationAllowance(
                        row_index=1,
                        property_name="OverrideOutput",
                        property_value=True,
                        reference_name="OutputBus",
                    ),
                ),
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step, preview_step),
    )
    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload(
            object_type="Sound",
            candidate_names=(
                "UseMaxSoundPerInstance",
                "OutputBus",
            ),
            dependency_names=("OverrideOutput",),
        )
    )
    return broker, preview_step, expected


def test_audio_import_reference_activation_explicit_and_omitted_hash_equally(
    tmp_path: Path,
) -> None:
    broker, preview_step, expected = (
        _reference_activation_equivalence_broker(tmp_path)
    )
    omitted = json.loads(json.dumps(expected))
    omitted_properties = omitted["arguments"]["imports"][1]["properties"]
    omitted["arguments"]["imports"][1]["properties"] = [
        item
        for item in omitted_properties
        if item["name"] != "OverrideOutput"
    ]

    explicit_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    omitted_hash, omitted_argv = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(omitted, separators=(",", ":")),
        ),
    )

    assert explicit_hash == omitted_hash
    executed_request = json.loads(omitted_argv[-1])
    assert executed_request == omitted
    assert all(
        item["name"] != "OverrideOutput"
        for item in executed_request["arguments"]["imports"][1][
            "properties"
        ]
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value["arguments"]["imports"][1]["properties"][1].__setitem__(
            "value",
            False,
        ),
        lambda value: (
            value["arguments"]["imports"][1].__setitem__(
                "properties",
                [
                    item
                    for item in value["arguments"]["imports"][1]["properties"]
                    if item["name"] != "OverrideOutput"
                ],
            ),
            value["arguments"]["imports"][0].__setitem__(
                "properties",
                [{"name": "OverrideOutput", "value": True}],
            ),
        ),
        lambda value: (
            value["arguments"]["imports"][1].__setitem__(
                "properties",
                [
                    item
                    for item in value["arguments"]["imports"][1]["properties"]
                    if item["name"] != "OverrideOutput"
                ],
            ),
            value["arguments"].__setitem__(
                "defaults",
                {
                    "properties": [
                        {"name": "OverrideOutput", "value": True}
                    ]
                },
            ),
        ),
        lambda value: (
            value["arguments"]["imports"][1].__setitem__(
                "properties",
                [
                    item
                    for item in value["arguments"]["imports"][1]["properties"]
                    if item["name"] != "OverrideOutput"
                ],
            ),
            value["arguments"]["imports"][1].pop("references"),
        ),
        lambda value: (
            value["arguments"]["imports"][1].__setitem__(
                "properties",
                [
                    item
                    for item in value["arguments"]["imports"][1]["properties"]
                    if item["name"] != "OverrideOutput"
                ],
            ),
            value["arguments"]["imports"][1]["references"][0].__setitem__(
                "name",
                "UserAuxSend0",
            ),
        ),
        lambda value: (
            value["arguments"]["imports"][1].__setitem__(
                "properties",
                [
                    item
                    for item in value["arguments"]["imports"][1]["properties"]
                    if item["name"] != "OverrideOutput"
                ],
            ),
            value["arguments"]["imports"][1]["references"][0][
                "target"
            ].__setitem__(
                "value",
                r"\Master-Mixer Hierarchy\Default Work Unit\Other",
            ),
        ),
        lambda value: value["arguments"]["imports"][1].__setitem__(
            "properties",
            [
                item
                for item in value["arguments"]["imports"][1]["properties"]
                if item["name"] != "UseMaxSoundPerInstance"
            ],
        ),
    ),
    ids=(
        "explicit-conflict",
        "wrong-row",
        "defaults-promotion",
        "missing-related-reference",
        "wrong-related-reference-name",
        "wrong-related-reference-target",
        "ordinary-dependency-omission",
    ),
)
def test_audio_import_reference_activation_rejects_unapproved_differences(
    tmp_path: Path,
    mutate,
) -> None:
    broker, preview_step, expected = (
        _reference_activation_equivalence_broker(tmp_path)
    )
    actual = json.loads(json.dumps(expected))
    mutate(actual)

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual, separators=(",", ":")),
            ),
        )


def test_audio_import_reference_activation_does_not_tolerate_bad_json(
    tmp_path: Path,
) -> None:
    broker, preview_step, expected = (
        _reference_activation_equivalence_broker(tmp_path)
    )
    encoded = json.dumps(expected, separators=(",", ":"))[:-1]

    with pytest.raises(GatewayInvocationError, match="strict JSON"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            ("preview", "--apply", "--request-json", encoded),
        )


def test_audio_import_metadata_equivalence_expands_defaults_and_binds_actual(
    tmp_path: Path,
) -> None:
    expected, expanded = _audio_import_equivalence_requests()
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    expected_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    expanded_hash, expanded_argv = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expanded, separators=(",", ":")),
        ),
    )
    partial = json.loads(json.dumps(expanded))
    partial["arguments"]["defaults"] = {
        "properties": [
            {"name": "IsLoopingEnabled", "value": True}
        ]
    }
    for row in partial["arguments"]["imports"]:
        row["properties"] = [
            item
            for item in row["properties"]
            if item["name"] != "IsLoopingEnabled"
        ]
    partial_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(partial, separators=(",", ":")),
        ),
    )

    assert len(expected_hash) == len(expanded_hash) == len(partial_hash) == 64
    assert expected_hash == expanded_hash == partial_hash
    assert json.loads(expanded_argv[-1]) == expanded


@pytest.mark.parametrize(
    ("import_language", "expected_type", "actual_type"),
    (
        ("SFX", "Sound", "Sound SFX"),
        ("SFX", "Sound SFX", "Sound"),
        ("English(US)", "Sound", "Sound Voice"),
        ("English(US)", "Sound Voice", "Sound"),
    ),
    ids=(
        "sfx-generic-to-specialized",
        "sfx-specialized-to-generic",
        "voice-generic-to-specialized",
        "voice-specialized-to-generic",
    ),
)
def test_audio_import_media_sound_aliases_have_one_canonical_hash(
    tmp_path: Path,
    import_language: str,
    expected_type: str,
    actual_type: str,
) -> None:
    expected, _ = _audio_import_equivalence_requests()
    for row in expected["arguments"]["imports"]:
        row["object_type"] = expected_type
        row["import_language"] = import_language
    actual = json.loads(json.dumps(expected))
    for row in actual["arguments"]["imports"]:
        row["object_type"] = actual_type
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    expected_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    actual_hash, execution_argv = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(actual, separators=(",", ":")),
        ),
    )

    assert expected_hash == actual_hash
    assert json.loads(execution_argv[-1]) == actual


@pytest.mark.parametrize(
    ("import_language", "expected_type"),
    (
        (None, "Sound"),
        ("SFX", "Sound SFX"),
        ("English(US)", "Sound Voice"),
    ),
    ids=(
        "generic-without-language",
        "sfx-specialization",
        "voice-specialization",
    ),
)
def test_audio_import_untyped_media_rows_may_omit_the_implicit_sound_type(
    tmp_path: Path,
    import_language: str | None,
    expected_type: str,
) -> None:
    expected, _ = _audio_import_equivalence_requests()
    for row in expected["arguments"]["imports"]:
        row["object_type"] = expected_type
        if import_language is not None:
            row["import_language"] = import_language
    actual = json.loads(json.dumps(expected))
    for row in actual["arguments"]["imports"]:
        row.pop("object_type")
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    expected_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    actual_hash, execution_argv = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(actual, separators=(",", ":")),
        ),
    )

    assert expected_hash == actual_hash
    assert json.loads(execution_argv[-1]) == actual


@pytest.mark.parametrize(
    "difference",
    (
        "structure-only",
        "typed-path",
        "cross-language",
        "unrelated-type",
        "second-media-source",
    ),
)
def test_audio_import_implicit_sound_type_equivalence_stays_closed(
    tmp_path: Path,
    difference: str,
) -> None:
    expected, _ = _audio_import_equivalence_requests()
    for row in expected["arguments"]["imports"]:
        row["object_type"] = "Sound SFX"
        row["import_language"] = "SFX"
    actual = json.loads(json.dumps(expected))
    for row in actual["arguments"]["imports"]:
        row.pop("object_type")

    if difference == "structure-only":
        for request in (expected, actual):
            for row in request["arguments"]["imports"]:
                row.pop("audio_file")
                row.pop("import_language")
    elif difference == "typed-path":
        for request in (expected, actual):
            for index, row in enumerate(request["arguments"]["imports"]):
                row["object_path"] = (
                    rf"\Actor-Mixer Hierarchy\<Sound>Typed_{index}"
                )
    elif difference == "cross-language":
        for row in expected["arguments"]["imports"]:
            row["object_type"] = "Sound Voice"
    elif difference == "unrelated-type":
        for row in expected["arguments"]["imports"]:
            row["object_type"] = "RandomSequenceContainer"
    else:
        for row in actual["arguments"]["imports"]:
            row["audio_file_base64"] = "UklGRg=="

    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )
    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual, separators=(",", ":")),
            ),
        )


@pytest.mark.parametrize(
    ("import_language", "expected_type", "actual_type"),
    (
        ("SFX", "Sound", "Sound Voice"),
        ("SFX", "Sound SFX", "Sound Voice"),
        ("English(US)", "Sound", "Sound SFX"),
        ("English(US)", "Sound Voice", "Sound SFX"),
    ),
    ids=(
        "sfx-generic-is-not-voice",
        "sfx-specialized-is-not-voice",
        "voice-generic-is-not-sfx",
        "voice-specialized-is-not-sfx",
    ),
)
def test_audio_import_media_sound_aliases_do_not_cross_language_semantics(
    tmp_path: Path,
    import_language: str,
    expected_type: str,
    actual_type: str,
) -> None:
    expected, _ = _audio_import_equivalence_requests()
    for row in expected["arguments"]["imports"]:
        row["object_type"] = expected_type
        row["import_language"] = import_language
    actual = json.loads(json.dumps(expected))
    for row in actual["arguments"]["imports"]:
        row["object_type"] = actual_type
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual, separators=(",", ":")),
            ),
        )


def test_audio_import_sound_alias_requires_an_effective_media_language(
    tmp_path: Path,
) -> None:
    expected, _ = _audio_import_equivalence_requests()
    for row in expected["arguments"]["imports"]:
        row["object_type"] = "Sound"
    actual = json.loads(json.dumps(expected))
    for row in actual["arguments"]["imports"]:
        row["object_type"] = "Sound SFX"
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual, separators=(",", ":")),
            ),
        )


@pytest.mark.parametrize(
    ("expected_type", "actual_type"),
    (
        ("Sound", "Sound SFX"),
        ("ActorMixer", "PropertyContainer"),
        ("RandomSequenceContainer", "RandomContainer"),
        ("RandomSequenceContainer", "SequenceContainer"),
        ("MusicPlaylistContainer", "MusicRanSeqCntr"),
    ),
    ids=(
        "structure-only-sound",
        "actor-mixer-reflection-name",
        "random-container-specialization",
        "sequence-container-specialization",
        "music-playlist-reflection-name",
    ),
)
def test_audio_import_non_media_or_non_sound_syntax_aliases_remain_exact(
    expected_type: str,
    actual_type: str,
) -> None:
    expected = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Node"
                    ),
                    "object_type": expected_type,
                }
            ],
            "import_operation": "createNew",
        },
    }
    actual = json.loads(json.dumps(expected))
    actual["arguments"]["imports"][0]["object_type"] = actual_type
    argument = MetadataBoundJsonArgument(
        expected=expected,
        metadata_step="metadata.discover",
        object_type="Sound",
        required_tokens=("Volume",),
        equivalence="audio_import_v1",
    )

    assert not broker_module._metadata_bound_json_equal(  # noqa: SLF001
        actual,
        argument,
    )


def test_audio_import_canonical_structure_and_sound_tokens_pass_exact_broker() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Snow"
                    ),
                    "object_type": "RandomSequenceContainer",
                },
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Snow\Snow_Step_01"
                    ),
                    "object_type": "Sound SFX",
                    "audio_file": "/owned/snow_step_01.wav",
                    "import_language": "SFX",
                },
            ],
            "import_operation": "createNew",
        },
    }
    argument = SemanticJsonArgument(request)

    assert broker_module._semantic_json_equal(  # noqa: SLF001
        json.loads(json.dumps(request)),
        argument,
    )


def _audio_import_default_operation_request() -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Snow\Snow_Step_01"
                    ),
                    "object_type": "Sound SFX",
                    "audio_file": "/owned/snow_step_01.wav",
                    "import_language": "SFX",
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "Volume", "value": -2.0},
                    ],
                }
            ],
            "import_operation": "createNew",
        },
    }


def test_audio_import_default_operation_equivalence_allows_only_omission() -> None:
    expected = _audio_import_default_operation_request()
    argument = SemanticJsonArgument(
        expected,
        equivalence="audio_import_default_operation_v1",
    )
    omitted = json.loads(json.dumps(expected))
    del omitted["arguments"]["import_operation"]

    assert broker_module._semantic_json_equal(omitted, argument)  # noqa: SLF001
    assert broker_module._semantic_json_equal(expected, argument)  # noqa: SLF001


@pytest.mark.parametrize(
    "mutation",
    (
        "promote_defaults",
        "reverse_properties",
        "object_type_alias",
        "different_operation",
        "unknown_argument",
    ),
)
def test_audio_import_default_operation_equivalence_keeps_other_fields_exact(
    mutation: str,
) -> None:
    expected = _audio_import_default_operation_request()
    actual = json.loads(json.dumps(expected))
    arguments = actual["arguments"]
    row = arguments["imports"][0]
    if mutation == "promote_defaults":
        arguments["defaults"] = {
            "properties": row.pop("properties"),
        }
    elif mutation == "reverse_properties":
        row["properties"].reverse()
    elif mutation == "object_type_alias":
        row["object_type"] = "Sound"
    elif mutation == "different_operation":
        arguments["import_operation"] = "replaceExisting"
    else:
        arguments["unexpected"] = True
    argument = SemanticJsonArgument(
        expected,
        equivalence="audio_import_default_operation_v1",
    )

    assert not broker_module._semantic_json_equal(  # noqa: SLF001
        actual,
        argument,
    )


def test_audio_import_metadata_equivalence_normalizes_only_live_real_values() -> None:
    expected, _ = _audio_import_equivalence_requests()
    expected["arguments"]["imports"][0]["properties"][0]["value"] = -1.0
    argument = MetadataBoundJsonArgument(
        expected=expected,
        metadata_step="metadata.discover",
        object_type="Sound",
        required_tokens=(
            "Volume",
            "IsLoopingEnabled",
            "OutputBus",
        ),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real64"),
            MetadataTokenProjection(
                "IsLoopingEnabled",
                "property",
                "Boolean",
            ),
            MetadataTokenProjection("OutputBus", "reference", ""),
        ),
        equivalence="audio_import_v1",
    )
    integral = json.loads(json.dumps(expected))
    integral["arguments"]["imports"][0]["properties"][0]["value"] = -1

    assert broker_module._metadata_bound_json_equal(  # noqa: SLF001
        integral,
        argument,
    )

    unrelated = json.loads(json.dumps(integral))
    unrelated["arguments"]["imports"][0]["properties"].append(
        {"name": "Unrequested", "value": True}
    )
    assert not broker_module._metadata_bound_json_equal(  # noqa: SLF001
        unrelated,
        argument,
    )


def test_rtpc_metadata_equivalence_normalizes_points_and_default_mode_only() -> None:
    expected = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setRTPC",
        "arguments": {
            "object": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            },
            "property": "Volume",
            "control_input": {
                "kind": "path",
                "value": r"\Game Parameters\Default Work Unit\Rain",
            },
            "points": [
                {"x": 0.0, "y": -48.0, "shape": "Linear"},
                {"x": 100.0, "y": 0.0, "shape": "Linear"},
            ],
            "mode": "add_or_replace",
        },
    }
    argument = MetadataBoundJsonArgument(
        expected=expected,
        metadata_step="metadata.discover",
        object_type="Sound",
        required_tokens=("Volume",),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real64"),
        ),
        equivalence="object_set_rtpc_v1",
    )
    equivalent = json.loads(json.dumps(expected))
    equivalent["arguments"].pop("mode")
    equivalent["arguments"]["points"] = [
        {"x": 0, "y": -48, "shape": "Linear"},
        {"x": 100, "y": 0, "shape": "Linear"},
    ]

    assert broker_module._metadata_bound_json_equal(  # noqa: SLF001
        equivalent,
        argument,
    )

    different = json.loads(json.dumps(equivalent))
    different["arguments"]["points"][1]["y"] = -1
    assert not broker_module._metadata_bound_json_equal(  # noqa: SLF001
        different,
        argument,
    )


def test_audio_import_metadata_equivalence_rejects_only_omitted_use_existing_mode(
    tmp_path: Path,
) -> None:
    expected, expanded = _audio_import_equivalence_requests()
    expected["arguments"]["import_operation"] = "useExisting"
    expanded["arguments"]["import_operation"] = "useExisting"
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    expected_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    expanded_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expanded, separators=(",", ":")),
        ),
    )

    assert expected_hash == expanded_hash

    omitted_mode = json.loads(json.dumps(expanded))
    omitted_mode["arguments"].pop("import_operation")
    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(omitted_mode, separators=(",", ":")),
            ),
        )


def _audio_import_scalar_default_requests() -> tuple[
    dict[str, object],
    dict[str, object],
]:
    expected, _ = _audio_import_equivalence_requests()
    expected_rows = expected["arguments"]["imports"]
    for index, (row, subfolder) in enumerate(zip(
        expected_rows,
        ("Weapons/Rifle", "Weapons/Shotgun"),
        strict=True,
    )):
        row["object_type"] = "Sound SFX"
        row["import_language"] = "SFX"
        row["originals_subfolder"] = subfolder
        row["import_location"] = {
            "kind": "path",
            "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
        }
        row["event"] = {
            "path": rf"\Events\Default Work Unit\Import_{index}",
            "action": "Play",
        }

    factored = json.loads(json.dumps(expected))
    factored_defaults = factored["arguments"]["defaults"]
    factored_defaults.update(
        {
            "object_type": "Sound SFX",
            "import_language": "SFX",
            # Every row overrides this value, so it has no effective meaning.
            "originals_subfolder": "Unused",
            "import_location": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
            },
            # This valid default is also fully overridden and has no effect.
            "event": {
                "path": r"\Events\Default Work Unit\Unused",
                "action": "Stop",
            },
        }
    )
    for row in factored["arguments"]["imports"]:
        row.pop("object_type")
        row.pop("import_language")
        row.pop("import_location")
    return expected, factored


def test_audio_import_metadata_equivalence_expands_closed_scalar_defaults(
    tmp_path: Path,
) -> None:
    expected, factored = _audio_import_scalar_default_requests()
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    expected_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    factored_hash, factored_argv = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(factored, separators=(",", ":")),
        ),
    )

    assert expected_hash == factored_hash
    assert json.loads(factored_argv[-1]) == factored


def test_audio_import_metadata_equivalence_keeps_inline_base64_wire_exact(
    tmp_path: Path,
) -> None:
    expected, factored = _audio_import_scalar_default_requests()
    inline_audio = (
        "Mission/Complete.wav|"
        "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgLsAAAB3AQACABAAZGF0YQAAAAA="
    )
    for request in (expected, factored):
        first_row = request["arguments"]["imports"][0]
        first_row.pop("audio_file")
        first_row["audio_file_base64"] = inline_audio
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    expected_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expected, separators=(",", ":")),
        ),
    )
    factored_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(factored, separators=(",", ":")),
        ),
    )
    assert expected_hash == factored_hash

    factored["arguments"]["imports"][0]["audio_file_base64"] = (
        inline_audio[:-1] + "A"
    )
    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(factored, separators=(",", ":")),
            ),
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value["arguments"]["defaults"].__setitem__(
            "object_type",
            ["Sound SFX"],
        ),
        lambda value: value["arguments"]["defaults"].__setitem__(
            "Object_Type",
            value["arguments"]["defaults"].pop("object_type"),
        ),
        lambda value: value["arguments"]["defaults"].__setitem__(
            "import_location",
            {"kind": "path"},
        ),
        lambda value: value["arguments"]["defaults"].__setitem__(
            "event",
            {"path": r"\Events\Default Work Unit\Unused", "action": "Delete"},
        ),
        lambda value: (
            value["arguments"]["defaults"].__setitem__(
                "import_language",
                "sfx",
            ),
            value["arguments"]["imports"][0].pop("import_language", None),
        ),
        lambda value: (
            value["arguments"]["defaults"].__setitem__(
                "originals_subfolder",
                "Weapons/Rifle",
            ),
            value["arguments"]["imports"][1].pop(
                "originals_subfolder",
                None,
            ),
        ),
    ),
    ids=(
        "malformed-no-op-default",
        "case-mismatched-field",
        "malformed-no-op-identity",
        "malformed-no-op-event",
        "case-changed-effective-language",
        "changed-effective-subfolder",
    ),
)
def test_audio_import_metadata_equivalence_rejects_unsafe_scalar_defaults(
    tmp_path: Path,
    mutate,
) -> None:
    expected, factored = _audio_import_scalar_default_requests()
    mutate(factored)
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(factored, separators=(",", ":")),
            ),
        )


def test_audio_import_metadata_equivalence_rejects_duplicate_scalar_default_key(
    tmp_path: Path,
) -> None:
    expected, factored = _audio_import_scalar_default_requests()
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )
    encoded = json.dumps(factored, separators=(",", ":"))
    encoded = encoded.replace(
        '"object_type":"Sound SFX"',
        '"object_type":"Sound SFX","object_type":"Sound SFX"',
        1,
    )

    with pytest.raises(GatewayInvocationError, match="duplicate JSON"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            ("preview", "--apply", "--request-json", encoded),
        )


def _refactor_row_override_into_default(value: dict[str, object]) -> None:
    arguments = value["arguments"]
    arguments["defaults"] = {
        "properties": [{"name": "Volume", "value": -1}]
    }
    arguments["imports"][0]["properties"] = [
        item
        for item in arguments["imports"][0]["properties"]
        if item["name"] != "Volume"
    ]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value["arguments"].__setitem__(
            "import_operation",
            "replaceExisting",
        ),
        lambda value: value["arguments"]["imports"][1]["properties"].pop(),
        lambda value: value["arguments"]["imports"][0]["properties"][1].__setitem__(
            "name",
            "volume",
        ),
        lambda value: value["arguments"]["imports"][0]["properties"].append(
            {"name": "Volume", "value": -1}
        ),
        lambda value: value["arguments"]["imports"][0]["references"].append(
            {
                "name": "OutputBus",
                "target": {
                    "kind": "path",
                    "value": r"\Master-Mixer Hierarchy\Close",
                },
            }
        ),
        lambda value: value["arguments"].__setitem__(
            "defaults",
            {"properties": {"name": "Volume", "value": -3}},
        ),
        _refactor_row_override_into_default,
        lambda value: value["arguments"]["imports"].reverse(),
    ),
    ids=(
        "other-field",
        "missing-effective-default",
        "name-is-case-sensitive",
        "duplicate-property",
        "duplicate-reference",
        "invalid-default-array",
        "reverse-factor-row-override",
        "import-row-order",
    ),
)
def test_audio_import_metadata_equivalence_rejects_non_equivalent_or_invalid_forms(
    tmp_path: Path,
    mutate,
) -> None:
    expected, expanded = _audio_import_equivalence_requests()
    mutate(expanded)
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(expanded, separators=(",", ":")),
            ),
        )


def test_audio_import_metadata_equivalence_rejects_duplicate_json_object_keys(
    tmp_path: Path,
) -> None:
    expected, expanded = _audio_import_equivalence_requests()
    broker, preview_step = _audio_import_equivalence_broker(
        tmp_path,
        expected,
    )
    encoded = json.dumps(expanded, separators=(",", ":"))
    encoded = encoded.replace(
        '"operation":"audio.import"',
        '"operation":"audio.import","operation":"audio.import"',
        1,
    )

    with pytest.raises(GatewayInvocationError, match="duplicate JSON"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            ("preview", "--apply", "--request-json", encoded),
        )


def test_audio_import_metadata_equivalence_rejects_invalid_expected_scope() -> None:
    expected, _ = _audio_import_equivalence_requests()
    expected["operation"] = "object.set"
    with pytest.raises(ValueError, match="valid audio.import"):
        MetadataBoundJsonArgument(
            expected=expected,
            metadata_step="metadata.discover",
            object_type="Sound",
            required_tokens=("Volume",),
            equivalence="audio_import_v1",
        )
    with pytest.raises(ValueError, match="wire_exact"):
        MetadataBoundJsonArgument(
            expected={},
            metadata_step="metadata.discover",
            object_type="Sound",
            required_tokens=("Volume",),
            equivalence="open",
        )


def _audio_import_tab_equivalence_broker(
    tmp_path: Path,
    *,
    version: str,
) -> tuple[
    CodexGatewayBroker,
    ExpectedGatewayStep,
    dict[str, object],
]:
    request: dict[str, object] = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "audio.importTabDelimited",
        "arguments": {
            "import_file": "/owned/import.tsv",
            "import_location": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
            },
            "import_language": "SFX",
        },
    }
    metadata_step = ExpectedGatewayStep(
        "metadata.discover",
        "metadata",
        (
            "discover",
            "--object-type",
            "Sound",
            "--query",
            MetadataQueryArgument("looping"),
            "--limit",
            "8",
        ),
    )
    preview_step = ExpectedGatewayStep(
        "tx01.preview",
        "preview",
        (
            "--apply",
            "--request-json",
            MetadataBoundJsonArgument(
                expected=request,
                metadata_step="metadata.discover",
                object_type="Sound",
                required_tokens=("IsLoopingEnabled",),
                equivalence="audio_import_tab_v1",
            ),
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "waapi-skill",
        expected_steps=(metadata_step, preview_step),
    )
    broker._payloads_by_step["metadata.discover"] = (  # noqa: SLF001
        _metadata_discovery_payload(
            object_type="Sound",
            candidate_names=("IsLoopingEnabled",),
            dependency_names=(),
        )
    )
    return broker, preview_step, request


@pytest.mark.parametrize(
    ("version", "explicit_defaults"),
    (
        (
            "2022.1",
            {
                "import_operation": "createNew",
                "auto_add_to_source_control": False,
            },
        ),
        (
            "2025.1",
            {
                "import_operation": "createNew",
                "auto_add_to_source_control": False,
                "auto_check_out_to_source_control": False,
            },
        ),
    ),
)
def test_audio_import_tab_equivalence_accepts_only_versioned_no_op_defaults(
    tmp_path: Path,
    version: str,
    explicit_defaults: dict[str, object],
) -> None:
    broker, preview_step, request = _audio_import_tab_equivalence_broker(
        tmp_path,
        version=version,
    )
    expanded = json.loads(json.dumps(request))
    expanded["arguments"].update(explicit_defaults)

    omitted_hash, _ = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(request, separators=(",", ":")),
        ),
    )
    expanded_hash, expanded_argv = broker._validate_step(  # noqa: SLF001
        preview_step,
        (
            "preview",
            "--apply",
            "--request-json",
            json.dumps(expanded, separators=(",", ":")),
        ),
    )

    assert omitted_hash == expanded_hash
    assert json.loads(expanded_argv[-1]) == expanded


@pytest.mark.parametrize(
    ("version", "mutate"),
    (
        (
            "2022.1",
            lambda value: value["arguments"].__setitem__(
                "auto_check_out_to_source_control",
                False,
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "auto_check_out_to_source_control",
                True,
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "auto_add_to_source_control",
                True,
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "import_operation",
                "replaceExisting",
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "import_language",
                "English(US)",
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "import_file",
                "/owned/other.tsv",
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "import_location",
                {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Other Work Unit",
                },
            ),
        ),
        (
            "2025.1",
            lambda value: value["arguments"].__setitem__(
                "extra",
                False,
            ),
        ),
    ),
    ids=(
        "unsupported-old-version-auto-check",
        "non-default-auto-check",
        "non-default-auto-add",
        "different-operation",
        "different-language",
        "different-file",
        "different-location",
        "extra-field",
    ),
)
def test_audio_import_tab_equivalence_rejects_non_default_or_open_forms(
    tmp_path: Path,
    version: str,
    mutate,
) -> None:
    broker, preview_step, request = _audio_import_tab_equivalence_broker(
        tmp_path,
        version=version,
    )
    actual = json.loads(json.dumps(request))
    mutate(actual)

    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(actual, separators=(",", ":")),
            ),
        )


def test_audio_import_tab_equivalence_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    broker, preview_step, request = _audio_import_tab_equivalence_broker(
        tmp_path,
        version="2025.1",
    )
    encoded = json.dumps(request, separators=(",", ":")).replace(
        '"import_language":"SFX"',
        '"import_language":"SFX","import_language":"SFX"',
        1,
    )

    with pytest.raises(GatewayInvocationError, match="duplicate JSON"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            ("preview", "--apply", "--request-json", encoded),
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("version", "2030.1"),
        lambda value: value.__setitem__("operation", "audio.import"),
        lambda value: value["arguments"].pop("import_file"),
        lambda value: value["arguments"].__setitem__(
            "auto_add_to_source_control",
            0,
        ),
        lambda value: value["arguments"].__setitem__(
            "auto_check_out_to_source_control",
            False,
        ),
    ),
    ids=(
        "unsupported-version",
        "wrong-operation",
        "missing-required-field",
        "non-boolean-default",
        "unsupported-old-version-auto-check",
    ),
)
def test_audio_import_tab_equivalence_rejects_invalid_expected_scope(
    mutate,
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.importTabDelimited",
        "arguments": {
            "import_file": "/owned/import.tsv",
            "import_location": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
            },
            "import_language": "SFX",
        },
    }
    mutate(request)

    with pytest.raises(
        ValueError,
        match="valid audio.importTabDelimited",
    ):
        MetadataBoundJsonArgument(
            expected=request,
            metadata_step="metadata.discover",
            object_type="Sound",
            required_tokens=("IsLoopingEnabled",),
            equivalence="audio_import_tab_v1",
        )

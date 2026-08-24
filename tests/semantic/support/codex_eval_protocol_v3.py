"""Closed broker protocols for one executable V3 heavy scenario.

The scenario adapters own business requests.  This module only translates
those already-closed requests into exact, ordered packaged-gateway steps and
turn-boundary prefix counts for a single fresh Codex task.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_gateway_broker import (
    DraftTypedActionArgument,
    DraftTypedActionBatchArgument,
    DraftActionMetadataBinding,
    DraftActionQueryIdentityBinding,
    DraftActionResponseBinding,
    ExpectedGatewayStep,
    InlineTypedOperationArgument,
    MetadataBoundJsonArgument,
    MetadataQueryArgument,
    MetadataTokenProjection,
    OBJECT_SET_SCHEMA_DEFAULTS,
    ResponseBinding,
    SemanticJsonArgument,
    TypedRequestFactsArgument,
    validate_commutative_composer_setup_step_groups,
    validate_commutative_read_only_step_groups,
    validate_operation_draft_protocol_steps,
)
from tests.semantic.support.codex_gateway_contracts import (
    metadata_candidate_limit_for_query_count,
)
from wwise_waapi.operation_composer import (
    MAX_TYPED_ACTIONS_PER_APPLY,
    OperationComposerError,
    apply_composer_action,
    materialize_operation_request,
    new_composition,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    COMPOSER_INPUT_MODE,
    INLINE_TYPED_INPUT_MODE,
    OperationContractError,
    operation_input_mode,
    parse_operation_request,
)
from wwise_waapi.typed_operations import (
    INLINE_OPERATIONS,
    draft_operation_request_contract,
    inline_operation_cli_arguments,
)
from wwise_waapi.typed_topics import topic_match_contract, topic_options_contract
from wwise_waapi.typed_requests import (
    TypedRequestFact,
    TypedRequestError,
    materialize_typed_request,
    request_contract,
    typed_request_construction_for_values,
    typed_request_facts_for_values,
)


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
OPERATION_DRAFT_ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
_SEALED_FILE_REPLAY_OPERATIONS = frozenset(
    {"lua.executeCliFile", "lua.executeCoreFile"}
)


def _typed_fact_cli_arguments(
    facts: Sequence[TypedRequestFact],
    *,
    prefix: str = "",
) -> tuple[str, ...]:
    flag_prefix = f"{prefix}-" if prefix else ""
    values: list[str] = []
    for fact in facts:
        flag = f"--{flag_prefix}{fact.action}"
        values.append(flag)
        if fact.action in {"set", "append"}:
            values.extend((fact.handle, fact.value_type, fact.value))
        elif fact.action == "present":
            values.append(fact.handle)
        elif fact.action == "choose":
            values.extend((fact.handle, fact.value))
        elif fact.action == "choose-dynamic":
            if fact.key is None:
                raise V3ProtocolError("typed dynamic branch is missing its key")
            values.extend((fact.handle, fact.key, fact.value))
        elif fact.action in {"map-put", "map-correct"}:
            if fact.key is None:
                raise V3ProtocolError("typed map fact is missing its key")
            values.extend((fact.handle, fact.key, fact.value_type, fact.value))
        elif fact.action == "map-remove":
            if fact.key is None:
                raise V3ProtocolError("typed map removal is missing its key")
            values.extend((fact.handle, fact.key))
        else:
            raise V3ProtocolError(f"unsupported typed fact action {fact.action!r}")
    return tuple(values)


class V3ProtocolError(ValueError):
    """A materialized scenario cannot form an exact broker allow-list."""


def build_object_set_composer_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
    reference_identity_sources: Mapping[str, str] | None = None,
    metadata_binding: DraftActionMetadataBinding | None = None,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one reviewed flat object.set request into one typed Draft flow."""

    normalized = _validate_operation_request(request)
    if normalized["operation"] != "object.set":
        raise V3ProtocolError("Composer transaction builder requires object.set")
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("Composer transaction label must be txNN")
    arguments = normalized["arguments"]
    objects = arguments.get("objects")
    if not isinstance(objects, list) or not objects:
        raise V3ProtocolError("object.set Composer request requires objects")

    identity_sources = dict(reference_identity_sources or {})
    if any(
        not isinstance(path, str)
        or not path.startswith("\\")
        or not isinstance(step, str)
        or not step
        for path, step in identity_sources.items()
    ):
        raise V3ProtocolError("Composer reference identity sources are invalid")
    action_specs: list[
        tuple[Mapping[str, Any], tuple[DraftActionQueryIdentityBinding, ...]]
    ] = []
    for option_name in (
        "platform",
        "list_mode",
        "on_name_conflict",
        "auto_add_to_source_control",
    ):
        if option_name in arguments:
            default = OBJECT_SET_SCHEMA_DEFAULTS.get(option_name)
            if (
                option_name in OBJECT_SET_SCHEMA_DEFAULTS
                and type(arguments[option_name]) is type(default)
                and arguments[option_name] == default
            ):
                continue
            action_specs.append(
                (
                    {
                        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                        "action": "set_request_option",
                        "name": option_name,
                        "value": arguments[option_name],
                    },
                    (),
                )
            )
    allowed_request_fields = {
        "objects",
        "platform",
        "list_mode",
        "on_name_conflict",
        "auto_add_to_source_control",
    }
    if set(arguments) - allowed_request_fields:
        raise V3ProtocolError("object.set Composer request fields are not supported")

    for raw_target in objects:
        if not isinstance(raw_target, Mapping) or not isinstance(
            raw_target.get("object"), Mapping
        ):
            raise V3ProtocolError("object.set Composer target is invalid")
        action: dict[str, Any] = {
            "contract": OPERATION_DRAFT_ACTION_CONTRACT,
            "action": "add_target",
            "selector": dict(raw_target["object"]),
        }
        for field_name in (
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
        ):
            if field_name in raw_target:
                action[field_name] = raw_target[field_name]
        properties = raw_target.get("properties", [])
        references = raw_target.get("references", [])
        children = raw_target.get("children", [])
        unsupported = set(raw_target) - {
            "object",
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
            "children",
        }
        if (
            unsupported
            or not isinstance(properties, list)
            or not isinstance(references, list)
            or not isinstance(children, list)
        ):
            raise V3ProtocolError("object.set Composer target fields are not supported")
        for row in properties:
            if not isinstance(row, Mapping) or set(row) != {"name", "value"}:
                raise V3ProtocolError("object.set Composer property is invalid")
        if properties:
            action["properties"] = [dict(row) for row in properties]
        identity_bindings: list[DraftActionQueryIdentityBinding] = []
        for reference_index, row in enumerate(references):
            if not isinstance(row, Mapping) or set(row) != {"name", "target"}:
                raise V3ProtocolError("object.set Composer reference is invalid")
            target = row["target"]
            if (
                isinstance(target, Mapping)
                and target.get("kind") == "path"
                and isinstance(target.get("value"), str)
                and target["value"] in identity_sources
            ):
                identity_bindings.append(
                    DraftActionQueryIdentityBinding(
                        pointer=f"/references/{reference_index}/target",
                        step=identity_sources[target["value"]],
                    )
                )
        if references:
            action["references"] = [dict(row) for row in references]
        action_specs.append((action, tuple(identity_bindings)))

        def append_children(
            rows: Sequence[Any],
            *,
            parent_action_index: int,
        ) -> None:
            for row in rows:
                if (
                    not isinstance(row, Mapping)
                    or not isinstance(row.get("type"), str)
                    or not isinstance(row.get("name"), str)
                ):
                    raise V3ProtocolError("object.set Composer child is invalid")
                nested = row.get("children", [])
                unsupported_child = set(row) - {"type", "name", "children"}
                if unsupported_child or not isinstance(nested, list):
                    raise V3ProtocolError(
                        "object.set Composer child fields are not supported"
                    )
                action_specs.append(
                    (
                        {
                            "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                            "action": "add_child",
                            "parent_handle": f"@action:{parent_action_index}",
                            "type": row["type"],
                            "name": row["name"],
                        },
                        (),
                    )
                )
                append_children(nested, parent_action_index=len(action_specs))

        append_children(children, parent_action_index=len(action_specs))

    steps: list[ExpectedGatewayStep] = [
        ExpectedGatewayStep(
            name=f"{label}.operation-schema",
            subcommand="operation-schema",
            arguments=("object.set",),
        ),
        ExpectedGatewayStep(
            name=f"{label}.draft-start",
            subcommand="draft-start",
            arguments=("object.set",),
        ),
    ]
    latest_revision_step = f"{label}.draft-start"
    issued_handle_bindings: dict[int, tuple[str, str]] = {}
    action_cursor = 0
    action_step_index = 0
    while action_cursor < len(action_specs):
        available_parent_actions = frozenset(issued_handle_bindings)
        batch_rows: list[
            tuple[
                int,
                Mapping[str, Any],
                tuple[DraftActionQueryIdentityBinding, ...],
            ]
        ] = []
        for offset in range(
            action_cursor,
            min(len(action_specs), action_cursor + MAX_TYPED_ACTIONS_PER_APPLY),
        ):
            action, identity_bindings = action_specs[offset]
            parent_handle = action.get("parent_handle")
            parent_index = (
                int(parent_handle.removeprefix("@action:"))
                if isinstance(parent_handle, str)
                and parent_handle.startswith("@action:")
                else None
            )
            if parent_index is not None and parent_index not in available_parent_actions:
                break
            batch_rows.append((offset + 1, action, identity_bindings))
        if not batch_rows:
            raise V3ProtocolError("object.set Composer child parent is unavailable")

        action_step_index += 1
        action_name = f"{label}.action.{action_step_index:03d}"
        typed_actions: list[DraftTypedActionArgument] = []
        created_handle_index = 0
        for original_index, raw_action, identity_bindings in batch_rows:
            action = dict(raw_action)
            response_bindings: tuple[DraftActionResponseBinding, ...] = ()
            parent_handle = action.get("parent_handle")
            if isinstance(parent_handle, str) and parent_handle.startswith("@action:"):
                parent_index = int(parent_handle.removeprefix("@action:"))
                parent_step, response_pointer = issued_handle_bindings[parent_index]
                action.pop("parent_handle")
                response_bindings = (
                    DraftActionResponseBinding(
                        "/parent_handle",
                        parent_step,
                        response_pointer,
                    ),
                )
            typed_actions.append(
                DraftTypedActionArgument(
                    expected=action,
                    response_bindings=response_bindings,
                    query_identity_bindings=identity_bindings,
                    metadata_binding=(
                        metadata_binding
                        if action.get("action") == "add_target"
                        and any(
                            name in action
                            for name in ("properties", "references")
                        )
                        else None
                    ),
                )
            )
            if action.get("action") in {"add_target", "add_child"}:
                issued_handle_bindings[original_index] = (
                    action_name,
                    f"/draft/action_result/created_handles/{created_handle_index}",
                )
                created_handle_index += 1

        typed_argument: DraftTypedActionArgument | DraftTypedActionBatchArgument
        typed_argument = (
            typed_actions[0]
            if len(typed_actions) == 1
            else DraftTypedActionBatchArgument(tuple(typed_actions))
        )
        steps.append(
            ExpectedGatewayStep(
                name=action_name,
                subcommand="draft-apply",
                arguments=(
                    ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(f"{label}.draft-start", "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(latest_revision_step, "/draft/revision"),
                    "--compact",
                    "--facts",
                    typed_argument,
                ),
            )
        )
        latest_revision_step = action_name
        action_cursor += len(batch_rows)
    check_name = f"{label}.check"
    preview_name = f"{label}.preview"
    show_name = f"{label}.transaction-show"
    confirm_name = f"{label}.confirm"
    execute_name = f"{label}.execute"
    steps.extend(
        (
            ExpectedGatewayStep(
                name=check_name,
                subcommand="draft-check",
                arguments=(
                    ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(f"{label}.draft-start", "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(latest_revision_step, "/draft/revision"),
                ),
            ),
            ExpectedGatewayStep(
                name=preview_name,
                subcommand="preview-from-draft",
                arguments=(
                    ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(f"{label}.draft-start", "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(check_name, "/draft/revision"),
                    "--apply",
                ),
            ),
            ExpectedGatewayStep(
                name=show_name,
                subcommand="transaction-show",
                arguments=(ResponseBinding(preview_name, "/transaction_id"), "--summary-only"),
            ),
            ExpectedGatewayStep(
                name=confirm_name,
                subcommand="confirm",
                arguments=(
                    ResponseBinding(show_name, "/transaction_id"),
                    "--confirmation-token",
                    ResponseBinding(show_name, "/confirmation/token"),
                ),
            ),
            ExpectedGatewayStep(
                name=execute_name,
                subcommand="execute",
                arguments=(ResponseBinding(confirm_name, "/transaction_id"),),
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep(
                name=f"{label}.verify",
                subcommand="verify",
                arguments=(ResponseBinding(execute_name, "/transaction_id"),),
            ),
        )
    )
    return tuple(steps)


def build_audio_import_composer_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
    metadata_binding: DraftActionMetadataBinding | None = None,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one canonical audio.import request into deep business Draft steps."""

    del metadata_binding  # live Field Handles replace the retired metadata-first action seam
    normalized = _validate_operation_request(request)
    if normalized["operation"] != "audio.import":
        raise V3ProtocolError("business transaction builder requires audio.import")
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    version = str(normalized["version"])
    arguments = normalized["arguments"]
    imports = arguments.get("imports")
    if not isinstance(imports, list) or not imports:
        raise V3ProtocolError("audio.import business request requires import rows")
    allowed_request_fields = {
        "imports",
        "defaults",
        "import_operation",
        "auto_add_to_source_control",
        "auto_check_out_to_source_control",
    }
    if set(arguments) - allowed_request_fields:
        raise V3ProtocolError("audio.import business request fields are not supported")
    defaults = arguments.get("defaults", {})
    if not isinstance(defaults, Mapping):
        raise V3ProtocolError("audio.import business defaults must be an object")

    steps: list[ExpectedGatewayStep] = [
        ExpectedGatewayStep(
            name=f"{label}.operation-schema",
            subcommand="operation-schema",
            arguments=("audio.import",),
        ),
        ExpectedGatewayStep(
            name=f"{label}.draft-start",
            subcommand="draft-start",
            arguments=("audio.import",),
        ),
    ]
    draft_start = f"{label}.draft-start"
    latest_revision_step = draft_start
    object_bindings: dict[tuple[str, str], ResponseBinding] = {}
    field_bindings: dict[tuple[str, str, str], ResponseBinding] = {}
    planned_by_path: dict[str, ResponseBinding] = {}
    bind_object_index = 0
    bind_field_index = 0

    def draft_prefix() -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(latest_revision_step, "/draft/revision"),
        )

    def bind_object(selector: Mapping[str, Any]) -> ResponseBinding:
        nonlocal bind_object_index, latest_revision_step
        kind = selector.get("kind")
        value = selector.get("value")
        if kind not in {"id", "path"} or not isinstance(value, str) or not value:
            raise V3ProtocolError("audio.import business identity must be exact id or path")
        key = (str(kind), value)
        existing = object_bindings.get(key)
        if existing is not None:
            return existing
        bind_object_index += 1
        step_name = f"{label}.bind-object.{bind_object_index:03d}"
        steps.append(
            ExpectedGatewayStep(
                name=step_name,
                subcommand="draft-bind-object",
                arguments=(
                    *draft_prefix(),
                    "--object-id" if kind == "id" else "--object-path",
                    value,
                ),
            )
        )
        latest_revision_step = step_name
        binding = ResponseBinding(step_name, "/bound_object/handle")
        object_bindings[key] = binding
        return binding

    def bind_field(
        *,
        token: str,
        object_handle: ResponseBinding | None,
        class_name: str,
    ) -> ResponseBinding:
        nonlocal bind_field_index, latest_revision_step
        scope_kind = "object" if object_handle is not None else "class"
        scope_identity = (
            f"{object_handle.step}:{object_handle.pointer}"
            if object_handle is not None
            else class_name
        )
        key = (scope_kind, scope_identity, token)
        existing = field_bindings.get(key)
        if existing is not None:
            return existing
        bind_field_index += 1
        step_name = f"{label}.bind-field.{bind_field_index:03d}"
        scope_arguments: tuple[Any, ...] = (
            ("--object-handle", object_handle)
            if object_handle is not None
            else ("--class-name", class_name)
        )
        steps.append(
            ExpectedGatewayStep(
                name=step_name,
                subcommand="draft-bind-field",
                arguments=(
                    *draft_prefix(),
                    *scope_arguments,
                    "--token",
                    token,
                ),
            )
        )
        latest_revision_step = step_name
        binding = ResponseBinding(step_name, "/bound_field/handle")
        field_bindings[key] = binding
        return binding

    native_mode = arguments.get("import_operation")
    mode = None if native_mode is None else {
        "createNew": "create",
        "useExisting": "reimport",
        "replaceExisting": "replace",
    }.get(native_mode)
    if native_mode is not None and mode is None:
        raise V3ProtocolError("audio.import business mode is unsupported")
    configure_arguments: list[Any] = [*draft_prefix()]
    if mode is not None:
        configure_arguments.extend(("--mode", mode))
    if "auto_add_to_source_control" in arguments:
        configure_arguments.append(
            "--add-to-source-control"
            if arguments["auto_add_to_source_control"] is True
            else "--no-add-to-source-control"
        )
    if "auto_check_out_to_source_control" in arguments:
        configure_arguments.append(
            "--check-out-from-source-control"
            if arguments["auto_check_out_to_source_control"] is True
            else "--no-check-out-from-source-control"
        )
    configure_name: str | None = None
    if len(configure_arguments) > len(draft_prefix()):
        configure_name = f"{label}.configure"
        steps.append(
            ExpectedGatewayStep(
                name=configure_name,
                subcommand="draft-business-configure",
                arguments=tuple(configure_arguments),
            )
        )
        latest_revision_step = configure_name

    def value_text(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and not math.isfinite(value):
                raise V3ProtocolError("audio.import business value must be finite")
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        if isinstance(value, str):
            return value
        raise V3ProtocolError("audio.import business value type is unsupported")

    def resolved_path(fields: Mapping[str, Any]) -> str:
        path = fields.get("object_path")
        if not isinstance(path, str) or not path:
            raise V3ProtocolError("audio.import business row requires object_path")
        if path.startswith("\\"):
            return path
        location = fields.get("import_location")
        if not isinstance(location, Mapping) or location.get("kind") != "path":
            raise V3ProtocolError("relative audio.import path requires exact import_location")
        base = location.get("value")
        if not isinstance(base, str) or not base.startswith("\\"):
            raise V3ProtocolError("audio.import import_location path is invalid")
        return base.rstrip("\\") + "\\" + path.lstrip("\\")

    def split_target(path: str) -> tuple[str, str, str | None]:
        parent, separator, leaf = path.rpartition("\\")
        if not separator or not parent or not leaf:
            raise V3ProtocolError("audio.import target path has no bindable parent")
        typed_segment: str | None = None
        if leaf.startswith("<") and ">" in leaf:
            typed_segment, leaf = leaf[1:].split(">", 1)
        if not leaf:
            raise V3ProtocolError("audio.import target name is empty")
        return parent, leaf, typed_segment

    def semantic_kind(
        *,
        object_type: Any,
        typed_segment: str | None,
        language: Any,
    ) -> str:
        token = str(typed_segment or object_type or "").casefold().replace(" ", "")
        if token in {"sound", "soundsfx"}:
            return "sound-sfx" if str(language).casefold() == "sfx" else "sound-voice"
        if token == "soundvoice":
            return "sound-voice"
        mapping = {
            "actormixer": "actor-mixer",
            "blendcontainer": "blend-container",
            "musicplaylistcontainer": "music-playlist-container",
            "musicranseqcntr": "music-playlist-container",
            "musicsegment": "music-segment",
            "musicswitchcontainer": "music-switch-container",
            "musictrack": "music-track",
            "randomcontainer": "random-container",
            "sequencecontainer": "sequence-container",
            "randomsequencecontainer": "random-container",
            "switchcontainer": "switch-container",
            "folder": "virtual-folder",
            "virtualfolder": "virtual-folder",
        }
        result = mapping.get(token)
        if result is None:
            raise V3ProtocolError(
                f"audio.import business object type {object_type!r} is unsupported"
            )
        return result

    for row_index, raw_row in enumerate(imports):
        if not isinstance(raw_row, Mapping):
            raise V3ProtocolError("audio.import business row must be an object")
        fields = {**dict(defaults), **dict(raw_row)}
        for collection_name in ("properties", "references"):
            raw_collection = fields.get(collection_name, [])
            if not isinstance(raw_collection, list) or not all(
                isinstance(item, Mapping) and isinstance(item.get("name"), str)
                for item in raw_collection
            ):
                raise V3ProtocolError(
                    "business transaction builder requires one valid audio.import request"
                )
            names = [str(item["name"]) for item in raw_collection]
            if len(names) != len(set(names)):
                raise V3ProtocolError(
                    "business transaction builder requires one valid audio.import request"
                )
        target_path = resolved_path(fields)
        parent_path, name, typed_segment = split_target(target_path)
        object_type = fields.get("object_type")
        language = fields.get("import_language")
        kind = semantic_kind(
            object_type=object_type,
            typed_segment=typed_segment,
            language=language,
        )
        existing_target_handle: ResponseBinding | None = None
        if mode in {"reimport", "replace"}:
            existing_target_handle = bind_object({"kind": "path", "value": target_path})
            target_arguments: list[Any] = [
                "--object-handle",
                existing_target_handle,
            ]
            subcommand = "draft-declare-existing"
        else:
            parent_handle = planned_by_path.get(parent_path)
            if parent_handle is None:
                parent_handle = bind_object({"kind": "path", "value": parent_path})
            target_arguments = [
                "--parent-handle",
                parent_handle,
                "--name",
                name,
                "--kind",
                kind,
            ]
            subcommand = "draft-declare-new"

        business_fields: list[tuple[str, Any]] = []
        direct_mapping = (
            ("audio_file", "media_file"),
            ("audio_file_base64", "inline_wav"),
            ("import_language", "language"),
            ("originals_subfolder", "originals_subfolder"),
            ("notes", "notes"),
            ("audio_source_notes", "audio_source_notes"),
            ("dialogue_event", "dialogue_event_directive"),
            ("switch_assignment", "switch_value"),
        )
        for native_name, business_name in direct_mapping:
            if native_name in fields:
                business_fields.append((business_name, fields[native_name]))

        properties = fields.get("properties", [])
        if not isinstance(properties, list):
            raise V3ProtocolError("audio.import properties must be an array")
        property_rows = [dict(item) for item in properties if isinstance(item, Mapping)]
        if len(property_rows) != len(properties):
            raise V3ProtocolError("audio.import property row must be an object")
        property_by_name = {str(item.get("name")): item.get("value") for item in property_rows}
        if "Volume" in property_by_name:
            business_fields.append(("volume_db", property_by_name.pop("Volume")))
        loop_enabled = property_by_name.get("IsLoopingEnabled")
        loop_infinite = property_by_name.get("IsLoopingInfinite")
        if loop_enabled is True and loop_infinite is True:
            property_by_name.pop("IsLoopingEnabled")
            property_by_name.pop("IsLoopingInfinite")
            business_fields.append(("loop", "infinite"))
        max_instances_enabled = property_by_name.get("UseMaxSoundPerInstance")
        max_instances = property_by_name.get("MaxSoundPerInstance")
        if (
            max_instances_enabled is True
            and isinstance(max_instances, int)
            and not isinstance(max_instances, bool)
        ):
            property_by_name.pop("UseMaxSoundPerInstance")
            property_by_name.pop("MaxSoundPerInstance")
            business_fields.append(("max_instances", max_instances))

        references = fields.get("references", [])
        if not isinstance(references, list):
            raise V3ProtocolError("audio.import references must be an array")
        reference_rows = [dict(item) for item in references if isinstance(item, Mapping)]
        if len(reference_rows) != len(references):
            raise V3ProtocolError("audio.import reference row must be an object")
        dynamic_values: list[tuple[ResponseBinding, Any]] = []
        metadata_class = "Sound" if kind in {"sound-sfx", "sound-voice"} else str(object_type)
        for token, value in property_by_name.items():
            field_handle = bind_field(
                token=token,
                object_handle=existing_target_handle,
                class_name=metadata_class,
            )
            dynamic_values.append((field_handle, value))
        for item in reference_rows:
            token = item.get("name")
            target = item.get("target")
            if not isinstance(token, str) or not isinstance(target, Mapping):
                raise V3ProtocolError("audio.import reference is incomplete")
            target_handle = bind_object(target)
            if token == "OutputBus":
                business_fields.append(("output_bus", target_handle))
            else:
                field_handle = bind_field(
                    token=token,
                    object_handle=existing_target_handle,
                    class_name=metadata_class,
                )
                dynamic_values.append((field_handle, target_handle))

        event_arguments: list[Any] = []
        event = fields.get("event")
        if event is not None:
            if not isinstance(event, Mapping):
                raise V3ProtocolError("audio.import event must be an object")
            event_path = event.get("path")
            event_action = event.get("action", "Play")
            if not isinstance(event_path, str) or not isinstance(event_action, str):
                raise V3ProtocolError("audio.import event is incomplete")
            event_parent, event_name, _typed = split_target(event_path)
            event_parent_handle = bind_object(
                {"kind": "path", "value": event_parent}
            )
            event_arguments = [
                "--event-parent-handle",
                event_parent_handle,
                "--event-name",
                event_name,
                "--event-action",
                event_action,
            ]

        declaration_name = f"{label}.declare.{row_index + 1:03d}"
        declaration_arguments: list[Any] = [
            *draft_prefix(),
            "--declaration-id",
            f"row-{row_index + 1:03d}",
            *target_arguments,
        ]
        for field_name, field_value in business_fields:
            declaration_arguments.extend(
                ("--field", field_name, field_value if isinstance(field_value, ResponseBinding) else value_text(field_value))
            )
        for field_handle, field_value in dynamic_values:
            declaration_arguments.extend(
                (
                    "--field-value",
                    field_handle,
                    field_value if isinstance(field_value, ResponseBinding) else value_text(field_value),
                )
            )
        declaration_arguments.extend(event_arguments)
        steps.append(
            ExpectedGatewayStep(
                name=declaration_name,
                subcommand=subcommand,
                arguments=tuple(declaration_arguments),
            )
        )
        latest_revision_step = declaration_name
        if mode == "create":
            planned_by_path[target_path] = ResponseBinding(
                declaration_name,
                f"/draft/declarations/{row_index}/result_handle",
            )

    check_name = f"{label}.check"
    preview_name = f"{label}.preview"
    show_name = f"{label}.transaction-show"
    confirm_name = f"{label}.confirm"
    execute_name = f"{label}.execute"
    steps.extend(
        (
            ExpectedGatewayStep(
                name=check_name,
                subcommand="draft-check",
                arguments=(*draft_prefix(),),
            ),
            ExpectedGatewayStep(
                name=preview_name,
                subcommand="preview-from-draft",
                arguments=(
                    ResponseBinding(draft_start, "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(draft_start, "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(check_name, "/draft/revision"),
                    "--apply",
                ),
                expected_operation_request=normalized,
            ),
            ExpectedGatewayStep(
                name=show_name,
                subcommand="transaction-show",
                arguments=(ResponseBinding(preview_name, "/transaction_id"), "--summary-only"),
            ),
            ExpectedGatewayStep(
                name=confirm_name,
                subcommand="confirm",
                arguments=(
                    ResponseBinding(show_name, "/transaction_id"),
                    "--confirmation-token",
                    ResponseBinding(show_name, "/confirmation/token"),
                ),
            ),
            ExpectedGatewayStep(
                name=execute_name,
                subcommand="execute",
                arguments=(ResponseBinding(confirm_name, "/transaction_id"),),
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep(
                name=f"{label}.verify",
                subcommand="verify",
                arguments=(ResponseBinding(execute_name, "/transaction_id"),),
            ),
        )
    )
    return tuple(steps)


def materialize_audio_import_composer_protocol_request(
    protocol: V3GatewayProtocol,
    *,
    version: str,
) -> dict[str, Any]:
    """Replay one reviewed audio.import Draft protocol into its canonical request."""

    starts = [
        (index, step)
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "draft-start"
        and step.arguments == ("audio.import",)
    ]
    previews = [
        (index, step)
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "preview-from-draft"
    ]
    if len(starts) != 1 or len(previews) != 1 or starts[0][0] >= previews[0][0]:
        raise V3ProtocolError(
            "audio.import Composer protocol topology is invalid"
        )
    preview = previews[0][1]
    witness = preview.expected_operation_request
    if witness is None:
        raise V3ProtocolError(
            "audio.import business protocol lacks its sealed request witness"
        )
    try:
        normalized = _validate_operation_request(witness)
    except V3ProtocolError:
        raise
    if normalized["version"] != version or normalized["operation"] != "audio.import":
        raise V3ProtocolError(
            "audio.import business protocol witness differs from its version binding"
        )
    return normalized


def materialize_typed_transaction_protocol_requests(
    protocol: V3GatewayProtocol,
    *,
    version: str,
    allow_cleaned_file_evidence: bool = False,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    """Replay every current typed transaction to its canonical request.

    This is the current-evidence inverse used by prompt provenance and
    semantic oracles. It accepts only the normal typed protocol objects that
    were already validated when ``V3GatewayProtocol`` was constructed; legacy
    JSON preview decoding stays in the offline archive codec.
    """

    results: list[tuple[str, Mapping[str, Any]]] = []
    for step in protocol.steps:
        if step.subcommand == "typed-call":
            witness = step.arguments[-1] if step.arguments else None
            if not isinstance(witness, TypedRequestFactsArgument):
                raise V3ProtocolError(
                    "typed-call transaction lacks its canonical facts witness"
                )
            if witness.io_root is None:
                continue
            results.append(
                (
                    f"/composer/{step.name}",
                    {
                        "contract": OPERATION_REQUEST_CONTRACT,
                        "version": version,
                        "operation": "waapi.call",
                        "arguments": {
                            "api": witness.contract.uri,
                            "args": dict(witness.expected_args),
                            "options": dict(witness.expected_options),
                            "io_root": witness.io_root,
                        },
                    },
                )
            )
            continue
        if step.subcommand != "typed-operation":
            continue
        witness = step.arguments[-1] if step.arguments else None
        if not isinstance(witness, InlineTypedOperationArgument):
            raise V3ProtocolError(
                "inline typed transaction lacks its canonical materialization witness"
            )
        results.append(
            (
                f"/composer/{step.name}",
                json.loads(
                    json.dumps(
                        dict(witness.expected),
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
            )
        )
    starts = tuple(
        (index, step)
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "draft-start"
    )
    for start_index, start in starts:
        operation = str(start.arguments[0])
        next_start_index = next(
            (
                index
                for index in range(start_index + 1, len(protocol.steps))
                if protocol.steps[index].subcommand == "draft-start"
            ),
            len(protocol.steps),
        )
        # A mutating Draft is represented by its immutable Preview handoff.
        # Read-only Drafts have no Preview and terminate at draft-check.  Pick
        # the lifecycle-specific terminal rather than whichever command occurs
        # first, otherwise every mutation would be mislabeled as a read and an
        # audio.import replay would be truncated before preview-from-draft.
        terminal_index = next(
            (
                index
                for index in range(start_index + 1, next_start_index)
                if protocol.steps[index].subcommand == "preview-from-draft"
            ),
            None,
        )
        if terminal_index is None:
            terminal_index = next(
                (
                    index
                    for index in range(start_index + 1, next_start_index)
                    if protocol.steps[index].subcommand == "draft-check"
                ),
                None,
            )
        if terminal_index is None:
            continue
        if (
            allow_cleaned_file_evidence
            and operation in _SEALED_FILE_REPLAY_OPERATIONS
        ):
            facts: list[TypedRequestFact] = []
            for step in protocol.steps[start_index + 1 : terminal_index]:
                if step.subcommand != "draft-apply":
                    continue
                argument = step.arguments[-1] if step.arguments else None
                action_arguments = (
                    (argument,)
                    if isinstance(argument, DraftTypedActionArgument)
                    else (
                        argument.actions
                        if isinstance(argument, DraftTypedActionBatchArgument)
                        else ()
                    )
                )
                if not action_arguments or any(
                    action_argument.operation != operation
                    or action_argument.response_bindings
                    or action_argument.query_identity_bindings
                    for action_argument in action_arguments
                ):
                    raise V3ProtocolError(
                        "sealed Lua file replay contains a dynamic Draft action"
                    )
                for action_argument in action_arguments:
                    action = dict(action_argument.expected)
                    allowed = {
                        "contract",
                        "action",
                        "fact_action",
                        "field_handle",
                        "value_type",
                        "value",
                        "key",
                    }
                    if (
                        set(action) - allowed
                        or action.get("contract")
                        != OPERATION_DRAFT_ACTION_CONTRACT
                        or action.get("action") != "add_typed_fact"
                        or not all(
                            isinstance(action.get(name), str)
                            for name in (
                                "fact_action",
                                "field_handle",
                                "value_type",
                                "value",
                            )
                        )
                        or (
                            "key" in action
                            and not isinstance(action.get("key"), str)
                        )
                    ):
                        raise V3ProtocolError(
                            "sealed Lua file replay contains an invalid typed fact"
                        )
                    facts.append(
                        TypedRequestFact(
                            str(action["fact_action"]),
                            str(action["field_handle"]),
                            str(action["value_type"]),
                            str(action["value"]),
                            key=action.get("key"),
                        )
                    )
            contract = draft_operation_request_contract(operation, version)
            try:
                materialized = materialize_typed_request(
                    contract,
                    schema_digest=contract.schema_digest,
                    facts=tuple(facts),
                )
            except TypedRequestError as exc:
                raise V3ProtocolError(
                    "sealed Lua file replay cannot materialize its typed facts"
                ) from exc
            request = {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": version,
                "operation": operation,
                "arguments": dict(materialized.args),
            }
        elif operation == "audio.import":
            segment_start = start_index
            while segment_start > 0 and protocol.steps[segment_start - 1].subcommand in {
                "metadata",
                "query-object",
                "operation-schema",
            }:
                segment_start -= 1
            request = materialize_audio_import_composer_protocol_request(
                V3GatewayProtocol(
                    tuple(protocol.steps[segment_start : terminal_index + 1]),
                    (terminal_index - segment_start + 1,),
                ),
                version=version,
            )
        else:
            composition = new_composition(operation, version)
            issued_handles: dict[tuple[str, str], str] = {}

            def composition_handles(value: Any) -> set[str]:
                if isinstance(value, Mapping):
                    result = {
                        item
                        for key, item in value.items()
                        if key == "handle" and isinstance(item, str)
                    }
                    for item in value.values():
                        result.update(composition_handles(item))
                    return result
                if isinstance(value, list):
                    result: set[str] = set()
                    for item in value:
                        result.update(composition_handles(item))
                    return result
                return set()

            for step in protocol.steps[start_index + 1 : terminal_index]:
                if step.subcommand != "draft-apply":
                    continue
                argument = step.arguments[-1] if step.arguments else None
                action_arguments = (
                    (argument,)
                    if isinstance(argument, DraftTypedActionArgument)
                    else (
                        argument.actions
                        if isinstance(argument, DraftTypedActionBatchArgument)
                        else ()
                    )
                )
                if not action_arguments:
                    raise V3ProtocolError(
                        "typed transaction contains a non-typed Draft action"
                    )
                # Handles issued by the shared Typed Core are deterministic for
                # the exact version/schema/field lineage.  The expected action
                # therefore already contains the value that the public
                # disclosure response must bind at runtime.  Query-identity
                # bindings likewise retain the reviewed path form in evidence;
                # the Broker separately proves the live GUID/path equivalence.
                created_handle_index = 0
                for action_argument in action_arguments:
                    prior_handles = composition_handles(composition)
                    action = dict(action_argument.expected)
                    for binding in action_argument.response_bindings:
                        bound = issued_handles.get(
                            (binding.step, binding.response_pointer)
                        )
                        if bound is not None:
                            action[binding.pointer.removeprefix("/")] = bound
                    try:
                        composition, _ = apply_composer_action(
                            operation,
                            version,
                            composition,
                            action,
                        )
                    except OperationComposerError as exc:
                        raise V3ProtocolError(
                            "typed transaction action cannot be replayed"
                        ) from exc
                    created = sorted(
                        composition_handles(composition) - prior_handles
                    )
                    if len(created) == 1:
                        issued_handles[
                            (
                                step.name,
                                "/draft/action_result/created_handles/"
                                f"{created_handle_index}",
                            )
                        ] = created[0]
                        created_handle_index += 1
                    elif created:
                        raise V3ProtocolError(
                            "typed transaction action created ambiguous handles"
                        )
            try:
                request = materialize_operation_request(
                    operation,
                    version,
                    composition,
                )
            except OperationComposerError as exc:
                raise V3ProtocolError(
                    "typed transaction cannot materialize its request"
                ) from exc
        results.append((f"/composer/{protocol.steps[terminal_index].name}", request))
    return tuple(results)


def build_audio_import_composer_protocol(
    request: Mapping[str, Any],
    *,
    metadata_binding: DraftActionMetadataBinding | None = None,
    metadata_step: ExpectedGatewayStep | None = None,
    schema_first: bool = False,
) -> V3GatewayProtocol:
    """Build one complete normal-input audio.import transaction."""

    if (metadata_binding is None) != (metadata_step is None):
        raise V3ProtocolError(
            "audio.import Composer metadata step and binding must be paired"
        )
    steps = list(
        build_audio_import_composer_transaction_steps(
            request,
            label="tx01",
            metadata_binding=metadata_binding,
        )
    )
    # Deep audio.import binds custom fields inside the Draft. Retained
    # metadata parameters are accepted only for sealed scenario compatibility.
    del metadata_step, schema_first
    commutative_groups: tuple[tuple[str, str], ...] = ()
    preview_indexes = tuple(
        index
        for index, step in enumerate(steps, start=1)
        if step.subcommand == "preview-from-draft"
    )
    if len(preview_indexes) != 1 or preview_indexes[0] >= len(steps):
        raise V3ProtocolError(
            "audio.import Composer protocol requires one nonterminal preview"
        )
    return V3GatewayProtocol(
        steps=tuple(steps),
        turn_prefix_counts=(preview_indexes[0], len(steps)),
        commutative_read_only_step_groups=commutative_groups,
    )


def _build_generic_typed_draft_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
    refusal: "StructuredRefusal | None" = None,
    direct_read: bool = False,
    post_filter: Mapping[str, Any] | None = None,
    request_options: Mapping[str, Any] | None = None,
) -> tuple[ExpectedGatewayStep, ...]:
    operation = str(request["operation"])
    version = str(request["version"])
    arguments = request["arguments"]
    if not isinstance(arguments, Mapping):
        raise V3ProtocolError("typed Draft request arguments must be an object")
    try:
        contract = (
            request_contract(version, operation)
            if operation.startswith("ak.")
            else draft_operation_request_contract(operation, version)
        )
        if direct_read != (operation.startswith("ak.") and contract.effect == "read"):
            raise V3ProtocolError("typed Draft lifecycle does not match its operation effect")
        construction = typed_request_construction_for_values(
            contract,
            args=arguments,
            options=(
                {}
                if request_options is None
                else _normalize_json_object(request_options, field="typed Draft options")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise V3ProtocolError(
            f"typed Draft request for {operation!r} is not constructible: {exc}"
        ) from exc
    steps: list[ExpectedGatewayStep] = [
        ExpectedGatewayStep(
            f"{label}.operation-schema",
            "request-schema" if operation.startswith("ak.") else "operation-schema",
            (operation,),
        ),
        ExpectedGatewayStep(
            f"{label}.draft-start",
            "draft-start",
            (operation,),
        ),
    ]
    revision_step = f"{label}.draft-start"
    disclosure_by_child: dict[str, str] = {}
    disclosed_handle_bindings: dict[str, tuple[str, str]] = {}
    disclosure_groups: dict[str, list[ExpectedGatewayStep]] = {}
    disclosure_group_order: list[str] = []
    disclosure_group_by_step: dict[str, str] = {}
    disclosure_root_by_child: dict[str, str] = {}
    ordered_disclosure_steps: list[
        tuple[Any, tuple[ExpectedGatewayStep, ...]]
    ] = []
    for disclosure_index, disclosure in enumerate(
        construction.disclosures,
        start=1,
    ):
        current_disclosure_steps: list[ExpectedGatewayStep] = []
        base_name = f"{label}.disclose.{disclosure_index:03d}"
        parent_argument: Any = disclosure.parent_handle
        parent_token_arguments: tuple[Any, ...] = ()
        if disclosure.parent_child_handle is not None:
            parent_source = disclosure_by_child.get(disclosure.parent_child_handle)
            if parent_source is None:
                raise V3ProtocolError("typed Draft disclosure parent is unavailable")
            parent_argument = ResponseBinding(parent_source, "/handle")
            parent_token_arguments = (
                "--parent-schema-token",
                ResponseBinding(parent_source, "/schema_lineage_token"),
            )
            disclosure_root = disclosure_root_by_child[disclosure.parent_child_handle]
        else:
            disclosure_root = disclosure.child_handle
        if disclosure_root not in disclosure_groups:
            disclosure_groups[disclosure_root] = []
            disclosure_group_order.append(disclosure_root)
        command_arguments: list[Any] = [
            operation,
            *(
                ()
                if parent_token_arguments
                else ("--schema-digest", contract.schema_digest)
            ),
            (
                "--array-handle"
                if disclosure.command == "request-array-item"
                else "--map-handle"
            ),
            parent_argument,
            (
                "--index"
                if disclosure.command == "request-array-item"
                else "--key"
            ),
            disclosure.key,
            "--shape",
            disclosure.shape,
            *parent_token_arguments,
        ]
        if disclosure.choice_handle is not None:
            if disclosure.choice_index is None:
                raise V3ProtocolError("typed Draft disclosure choice is unindexed")
            if disclosure.parent_choice_group_index is not None:
                if disclosure.parent_child_handle is None:
                    raise V3ProtocolError(
                        "typed Draft parent-published choice lacks its parent"
                    )
                choice_source = disclosure_by_child[disclosure.parent_child_handle]
                choice_pointer = (
                    "/child_contract/branch_choices/"
                    f"{disclosure.parent_choice_group_index}/choices/"
                    f"{disclosure.choice_index}/handle"
                )
            else:
                choice_name = f"{base_name}.choices"
                choice_step = ExpectedGatewayStep(
                    choice_name,
                    disclosure.command,
                    tuple(command_arguments),
                )
                disclosure_groups[disclosure_root].append(choice_step)
                current_disclosure_steps.append(choice_step)
                disclosure_group_by_step[choice_name] = disclosure_root
                choice_source = choice_name
                choice_pointer = f"/choices/{disclosure.choice_index}/handle"
            disclosed_handle_bindings[disclosure.choice_handle] = (
                choice_source,
                choice_pointer,
            )
            command_arguments.extend(
                (
                    "--choice-handle",
                    ResponseBinding(
                        choice_source,
                        choice_pointer,
                    ),
                )
            )
        disclosure_step = ExpectedGatewayStep(
            base_name, disclosure.command, tuple(command_arguments)
        )
        disclosure_groups[disclosure_root].append(disclosure_step)
        current_disclosure_steps.append(disclosure_step)
        disclosure_group_by_step[base_name] = disclosure_root
        disclosure_by_child[disclosure.child_handle] = base_name
        disclosure_root_by_child[disclosure.child_handle] = disclosure_root
        disclosed_handle_bindings[disclosure.child_handle] = (base_name, "/handle")
        ordered_disclosure_steps.append(
            (disclosure, tuple(current_disclosure_steps))
        )
    fact_rows: list[
        tuple[int, Any, tuple[DraftActionResponseBinding, ...], Mapping[str, Any]]
    ] = []
    for index, fact in enumerate(construction.facts, start=1):
        response_bindings: list[DraftActionResponseBinding] = []
        if fact.handle in disclosed_handle_bindings:
            source_step, source_pointer = disclosed_handle_bindings[fact.handle]
            response_bindings.append(
                DraftActionResponseBinding(
                    "/field_handle",
                    source_step,
                    source_pointer,
                )
            )
        if fact.value in disclosed_handle_bindings:
            source_step, source_pointer = disclosed_handle_bindings[fact.value]
            response_bindings.append(
                DraftActionResponseBinding(
                    "/value",
                    source_step,
                    source_pointer,
                )
            )
        action = {
            "contract": OPERATION_DRAFT_ACTION_CONTRACT,
            "action": "add_typed_fact",
            "fact_action": fact.action,
            "field_handle": fact.handle,
            **(
                {"value_type": fact.value_type, "value": fact.value}
                if fact.action in {"set", "append", "map-put"}
                else {"value": fact.value}
                if fact.action == "choose"
                else {"key": fact.key, "value": fact.value}
                if fact.action == "choose-dynamic"
                else {}
            ),
            **(
                {"key": fact.key}
                if fact.action == "map-put" and fact.key is not None
                else {}
            ),
        }
        fact_rows.append((index, fact, tuple(response_bindings), action))

    independent_rows = tuple(row for row in fact_rows if not row[2])
    dependent_rows_by_group: dict[
        str,
        list[tuple[int, Any, tuple[DraftActionResponseBinding, ...], Mapping[str, Any]]],
    ] = {root: [] for root in disclosure_group_order}
    for row in (row for row in fact_rows if row[2]):
        roots = {
            disclosure_group_by_step[binding.step]
            for binding in row[2]
            if binding.step in disclosure_group_by_step
        }
        if len(roots) != 1:
            raise V3ProtocolError(
                "typed Draft dependent fact crosses disclosure groups"
            )
        dependent_rows_by_group[next(iter(roots))].append(row)

    action_step_index = 0

    def append_fact_rows(
        rows: Sequence[
            tuple[
                int,
                Any,
                tuple[DraftActionResponseBinding, ...],
                Mapping[str, Any],
            ]
        ],
    ) -> None:
        nonlocal action_step_index, revision_step
        atomic_groups: list[tuple[Any, ...]] = []
        row_index = 0
        while row_index < len(rows):
            row = rows[row_index]
            fact = row[1]
            if fact.action != "choose-dynamic":
                atomic_groups.append((row,))
                row_index += 1
                continue
            if row_index + 1 >= len(rows):
                raise V3ProtocolError(
                    "typed Draft dynamic choice is missing its value fact"
                )
            paired_row = rows[row_index + 1]
            paired_fact = paired_row[1]
            if (
                paired_fact.action != "map-put"
                or paired_fact.handle != fact.handle
                or paired_fact.key != fact.key
            ):
                raise V3ProtocolError(
                    "typed Draft dynamic choice differs from its value fact"
                )
            atomic_groups.append((row, paired_row))
            row_index += 2

        batches: list[tuple[Any, ...]] = []
        pending: list[Any] = []
        for group in atomic_groups:
            if pending and len(pending) + len(group) > MAX_TYPED_ACTIONS_PER_APPLY:
                batches.append(tuple(pending))
                pending = []
            pending.extend(group)
        if pending:
            batches.append(tuple(pending))

        for batch in batches:
            action_step_index += 1
            step_name = f"{label}.action.{action_step_index:03d}"
            action_arguments = tuple(
                DraftTypedActionArgument(
                    action,
                    response_bindings=response_bindings,
                    operation=operation,
                )
                for _index, _fact, response_bindings, action in batch
            )
            typed_argument: DraftTypedActionArgument | DraftTypedActionBatchArgument
            typed_argument = (
                action_arguments[0]
                if len(action_arguments) == 1
                else DraftTypedActionBatchArgument(action_arguments)
            )
            steps.append(
                ExpectedGatewayStep(
                    step_name,
                    "draft-apply",
                    (
                        ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                        "--task-authority",
                        ResponseBinding(f"{label}.draft-start", "/task_authority"),
                        "--expected-revision",
                        ResponseBinding(revision_step, "/draft/revision"),
                        "--compact",
                        "--facts",
                        typed_argument,
                    ),
                )
            )
            revision_step = step_name

    append_fact_rows(independent_rows)
    interleave_disclosed_nodes = bool(construction.disclosures)
    if interleave_disclosed_nodes:
        fact_indexes = [
            disclosure.fact_index for disclosure in construction.disclosures
        ]
        if fact_indexes != sorted(set(fact_indexes)):
            raise V3ProtocolError(
                "typed Draft disclosure fact indexes are not strictly ordered"
            )
        covered_dependent_indexes: set[int] = set()
        position = 0
        while position < len(ordered_disclosure_steps):
            disclosure, disclosure_steps = ordered_disclosure_steps[position]
            grouped_steps = list(disclosure_steps)
            next_position = position + 1
            if next_position < len(ordered_disclosure_steps):
                next_disclosure, next_steps = ordered_disclosure_steps[next_position]
                if (
                    next_disclosure.parent_child_handle == disclosure.child_handle
                    and next_disclosure.parent_choice_group_index is not None
                ):
                    grouped_steps.extend(next_steps)
                    next_position += 1
            steps.extend(grouped_steps)
            next_fact_index = (
                construction.disclosures[next_position].fact_index
                if next_position < len(construction.disclosures)
                else len(construction.facts)
            )
            node_fact_index = disclosure.fact_index
            if node_fact_index > 0:
                possible_choice = construction.facts[node_fact_index - 1]
                if (
                    possible_choice.action == "choose-dynamic"
                    and possible_choice.handle == disclosure.parent_handle
                    and possible_choice.key == disclosure.key
                ):
                    node_fact_index -= 1
            node_rows = tuple(
                row
                for row in fact_rows
                if node_fact_index <= row[0] - 1 < next_fact_index
                and row[2]
            )
            if not node_rows:
                raise V3ProtocolError(
                    "typed Draft disclosure has no dependent node facts"
                )
            covered_dependent_indexes.update(row[0] for row in node_rows)
            append_fact_rows(node_rows)
            position = next_position
        expected_dependent_indexes = {row[0] for row in fact_rows if row[2]}
        if covered_dependent_indexes != expected_dependent_indexes:
            raise V3ProtocolError(
                "typed Draft node-local fact schedule is incomplete"
            )
    else:
        for root in disclosure_group_order:
            steps.extend(disclosure_groups[root])
            append_fact_rows(dependent_rows_by_group[root])
    check_name = f"{label}.check"
    check_trailing: tuple[Any, ...] = ()
    if post_filter is not None:
        normalized_filter = _normalize_json_object(post_filter, field="typed read post filter")
        if (
            operation != "ak.wwise.core.mediaPool.get"
            or set(normalized_filter) != {"field", "operator", "value", "limit"}
            or normalized_filter["field"] != "Filename"
            or normalized_filter["operator"] != "containsCaseSensitive"
        ):
            raise V3ProtocolError("typed read post filter is outside its closed contract")
        check_trailing = (
            "--post-filter-value",
            str(normalized_filter["value"]),
            "--post-filter-limit",
            str(normalized_filter["limit"]),
        )
    steps.append(
        ExpectedGatewayStep(
            check_name,
            "draft-check",
            (
                ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding(f"{label}.draft-start", "/task_authority"),
                "--expected-revision",
                ResponseBinding(revision_step, "/draft/revision"),
                *check_trailing,
            ),
        )
    )
    if direct_read:
        return tuple(steps)
    steps.append(
        ExpectedGatewayStep(
            f"{label}.preview",
            "preview-from-draft",
            (
                ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                "--task-authority",
                ResponseBinding(f"{label}.draft-start", "/task_authority"),
                "--expected-revision",
                ResponseBinding(check_name, "/draft/revision"),
                "--apply",
            ),
            allowed_exit_codes=(2,) if refusal is not None else (0,),
            expected_error_code=refusal.error_code if refusal is not None else "",
            expected_result_command=refusal.result_command if refusal is not None else "",
        )
    )
    return tuple(steps)


def _typed_disclosure_protocol_steps(
    disclosures: Sequence[Any],
    *,
    operation: str,
    schema_digest: str,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Bind every opaque nested handle before one inline typed-call."""

    steps: list[ExpectedGatewayStep] = []
    disclosure_by_child: dict[str, str] = {}
    for disclosure_index, disclosure in enumerate(disclosures, start=1):
        base_name = f"{label}.disclose.{disclosure_index:03d}"
        parent_argument: Any = disclosure.parent_handle
        parent_token_arguments: tuple[Any, ...] = ()
        if disclosure.parent_child_handle is not None:
            parent_source = disclosure_by_child.get(disclosure.parent_child_handle)
            if parent_source is None:
                raise V3ProtocolError("typed request disclosure parent is unavailable")
            parent_argument = ResponseBinding(parent_source, "/handle")
            parent_token_arguments = (
                "--parent-schema-token",
                ResponseBinding(parent_source, "/schema_lineage_token"),
            )
        command_arguments: list[Any] = [
            operation,
            *(
                ()
                if parent_token_arguments
                else ("--schema-digest", schema_digest)
            ),
            (
                "--array-handle"
                if disclosure.command == "request-array-item"
                else "--map-handle"
            ),
            parent_argument,
            "--index" if disclosure.command == "request-array-item" else "--key",
            disclosure.key,
            "--shape",
            disclosure.shape,
            *parent_token_arguments,
        ]
        if disclosure.choice_handle is not None:
            if disclosure.choice_index is None:
                raise V3ProtocolError("typed request disclosure choice is unindexed")
            choice_name = f"{base_name}.choices"
            steps.append(
                ExpectedGatewayStep(
                    choice_name,
                    disclosure.command,
                    tuple(command_arguments),
                )
            )
            command_arguments.extend(
                (
                    "--choice-handle",
                    ResponseBinding(
                        choice_name,
                        f"/choices/{disclosure.choice_index}/handle",
                    ),
                )
            )
        steps.append(
            ExpectedGatewayStep(base_name, disclosure.command, tuple(command_arguments))
        )
        disclosure_by_child[disclosure.child_handle] = base_name
    return tuple(steps)


def typed_read_draft_steps(
    name: str,
    api: str,
    *,
    version: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
    post_filter: Mapping[str, Any] | None = None,
) -> tuple[ExpectedGatewayStep, ...]:
    """Build one exact complex read through the shared typed Draft lifecycle."""

    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": api,
        "arguments": _normalize_json_object(args, field="typed read args"),
    }
    return _build_generic_typed_draft_transaction_steps(
            request,
            label=name,
            direct_read=True,
            post_filter=post_filter,
            request_options=options,
        )


def metadata_candidate_limit(queries: Sequence[str]) -> int:
    """Return the deterministic per-query candidate budget from the Skill."""

    if isinstance(queries, (str, bytes)):
        raise V3ProtocolError(
            "metadata candidate budget requires a query sequence"
        )
    count = len(tuple(queries))
    if not 1 <= count <= 8:
        raise V3ProtocolError(
            "metadata candidate budget requires 1..8 query phrases"
        )
    return metadata_candidate_limit_for_query_count(count)


def operation_request_equivalence(operation: str) -> str:
    """Return the one reviewed JSON equivalence for an operation request."""

    if operation in {"object.create", "object.set"}:
        return "object_operation_v1"
    if operation == "soundbank.generate":
        return "soundbank_generate_v1"
    if operation == "switchContainer.removeAssignment":
        return "switch_container_remove_assignment_v1"
    return "wire_exact"


@dataclass(frozen=True, slots=True)
class V3GatewayProtocol:
    steps: tuple[ExpectedGatewayStep, ...]
    turn_prefix_counts: tuple[int, ...]
    allowed_turn_prefix_counts: tuple[tuple[int, ...], ...] = ()
    terminal_prefix_counts: tuple[int, ...] = ()
    commutative_read_only_step_groups: tuple[tuple[str, str], ...] = ()
    commutative_composer_setup_step_groups: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("V3GatewayProtocol.steps must be non-empty")
        if not self.turn_prefix_counts:
            raise ValueError("V3GatewayProtocol.turn_prefix_counts must be non-empty")
        if tuple(sorted(self.turn_prefix_counts)) != self.turn_prefix_counts:
            raise ValueError("turn prefix counts must be ordered")
        if (
            not self.allowed_turn_prefix_counts
            and len(set(self.turn_prefix_counts)) != len(self.turn_prefix_counts)
        ):
            raise ValueError("turn prefix counts must be unique")
        if self.turn_prefix_counts[-1] != len(self.steps):
            raise ValueError("final turn prefix must consume the complete protocol")
        if self.allowed_turn_prefix_counts:
            if len(self.allowed_turn_prefix_counts) != len(self.turn_prefix_counts):
                raise ValueError(
                    "allowed turn prefixes must match the turn-boundary count"
                )
            for index, (maximum, allowed) in enumerate(
                zip(
                    self.turn_prefix_counts,
                    self.allowed_turn_prefix_counts,
                    strict=True,
                ),
                start=1,
            ):
                if (
                    not allowed
                    or tuple(sorted(set(allowed))) != allowed
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or not 1 <= value <= maximum
                        for value in allowed
                    )
                    or maximum not in allowed
                ):
                    raise ValueError(
                        f"allowed prefix choices for turn {index} are invalid"
                    )
            terminal = self.terminal_prefix_counts
            if (
                not terminal
                or tuple(sorted(set(terminal))) != terminal
                or any(
                    value not in self.allowed_turn_prefix_counts[-1]
                    for value in terminal
                )
            ):
                raise ValueError(
                    "terminal prefixes must be unique final-turn allowed choices"
                )
        elif self.terminal_prefix_counts:
            raise ValueError(
                "terminal prefixes require explicit allowed turn prefixes"
            )
        names = tuple(step.name for step in self.steps)
        if len(names) != len(set(names)):
            raise ValueError("V3 gateway step names must be unique")
        validate_operation_draft_protocol_steps(self.steps)
        groups = validate_commutative_read_only_step_groups(
            self.steps,
            self.commutative_read_only_step_groups,
        )
        if groups != self.commutative_read_only_step_groups:
            raise ValueError(
                "commutative read-only step groups must use canonical tuples"
            )
        setup_groups = validate_commutative_composer_setup_step_groups(
            self.steps,
            self.commutative_composer_setup_step_groups,
        )
        if setup_groups != self.commutative_composer_setup_step_groups:
            raise ValueError(
                "commutative Composer setup step groups must use canonical tuples"
            )
        checkpoint_counts = set(self.turn_prefix_counts)
        for allowed in self.allowed_turn_prefix_counts:
            checkpoint_counts.update(allowed)
        indexes = {name: index for index, name in enumerate(names)}
        for group in groups:
            if any(
                indexes[group[0]] + offset in checkpoint_counts
                for offset in range(1, len(group))
            ):
                raise ValueError(
                    "a commutative read-only group cannot cross a turn prefix"
                )
        for group in setup_groups:
            if any(
                indexes[group[0]] + offset in checkpoint_counts
                for offset in range(1, len(group))
            ):
                raise ValueError(
                    "a commutative Composer setup group cannot cross a turn prefix"
                )

    def allowed_prefixes_for_turn(self, index: int) -> tuple[int, ...]:
        if not 1 <= index <= len(self.turn_prefix_counts):
            raise IndexError("turn index is outside the protocol")
        if self.allowed_turn_prefix_counts:
            return self.allowed_turn_prefix_counts[index - 1]
        return (self.turn_prefix_counts[index - 1],)

    @property
    def accepted_terminal_prefixes(self) -> tuple[int, ...]:
        if self.terminal_prefix_counts:
            return self.terminal_prefix_counts
        return (len(self.steps),)


@dataclass(frozen=True, slots=True)
class StructuredRefusal:
    error_code: str
    result_command: str = "preview"

    def __post_init__(self) -> None:
        if not self.error_code or not self.error_code.strip():
            raise ValueError("structured refusal error_code must be non-empty")
        if not self.result_command or not self.result_command.strip():
            raise ValueError("structured refusal result_command must be non-empty")


def build_transaction_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    refusal: StructuredRefusal | None = None,
    terminal_execute: bool = False,
    request_equivalences: Sequence[str] | None = None,
) -> V3GatewayProtocol:
    """Build one or more separately confirmed immutable transactions.

    A multi-transaction scenario previews the first request on turn one.  Each
    confirmation turn completes only the currently visible transaction and,
    except for the final confirmation, obtains a new schema and preview for the
    next request.  The transaction-show call starts from the exact preview
    transaction id.  Confirmation then binds both its transaction id and its
    short state-scoped token to that show response; execute and verify each bind
    to the immediately preceding response.  No continuation value is guessed
    or injected into the prompt.
    """

    normalized = tuple(_validate_operation_request(request) for request in requests)
    if not normalized:
        raise V3ProtocolError("transaction protocol requires at least one request")
    if refusal is not None and len(normalized) != 1:
        raise V3ProtocolError("a structured refusal supports exactly one preview request")
    if terminal_execute and len(normalized) != 1:
        raise V3ProtocolError(
            "a terminal-execute transaction supports exactly one request"
        )
    if terminal_execute and refusal is not None:
        raise V3ProtocolError(
            "terminal execute and structured preview refusal are mutually exclusive"
        )
    if request_equivalences is None:
        equivalences = tuple(
            operation_request_equivalence(str(request["operation"]))
            for request in normalized
        )
    else:
        equivalences = tuple(request_equivalences)
        if len(equivalences) != len(normalized):
            raise V3ProtocolError(
                "request equivalences must match the transaction request count"
            )
        for request, equivalence in zip(normalized, equivalences, strict=True):
            operation = str(request["operation"])
            default = operation_request_equivalence(operation)
            if equivalence != default and not (
                operation == "audio.import"
                and equivalence == "audio_import_default_operation_v1"
            ):
                raise V3ProtocolError(
                    "request equivalence is not reviewed for the operation"
                )

    steps: list[ExpectedGatewayStep] = []
    prefixes: list[int] = []
    for index, (request, request_equivalence) in enumerate(
        zip(normalized, equivalences, strict=True),
        start=1,
    ):
        label = f"tx{index:02d}"
        operation = str(request["operation"])
        if operation == "waapi.call":
            call_arguments = request["arguments"]
            if not isinstance(call_arguments, Mapping):
                raise V3ProtocolError("waapi.call arguments must be an object")
            api = call_arguments.get("api")
            raw_args = call_arguments.get("args")
            raw_options = call_arguments.get("options")
            if (
                not isinstance(api, str)
                or not isinstance(raw_args, Mapping)
                or not isinstance(raw_options, Mapping)
            ):
                raise V3ProtocolError("typed waapi.call request is incomplete")
            try:
                contract = request_contract(str(request["version"]), api)
                construction = typed_request_construction_for_values(
                    contract,
                    args=raw_args,
                    options=raw_options,
                )
            except (TypeError, ValueError) as exc:
                raise V3ProtocolError(
                    f"typed waapi.call request for {api!r} is not constructible: {exc}"
                ) from exc
            if contract.route != "isolated_transaction":
                raise V3ProtocolError(
                    "waapi.call semantic protocol is reserved for isolated typed routes"
                )
            io_root = call_arguments.get("io_root")
            if not isinstance(io_root, str) or not io_root:
                raise V3ProtocolError("isolated typed call requires one io_root")
            steps.append(
                ExpectedGatewayStep(
                    name=f"{label}.request-schema",
                    subcommand="request-schema",
                    arguments=(api,),
                )
            )
            disclosure_steps = _typed_disclosure_protocol_steps(
                construction.disclosures,
                operation=api,
                schema_digest=contract.schema_digest,
                label=label,
            )
            steps.extend(disclosure_steps)
            steps.append(
                ExpectedGatewayStep(
                    name=f"{label}.preview",
                    subcommand="typed-call",
                    arguments=(
                        api,
                        "--schema-digest",
                        contract.schema_digest,
                        "--apply",
                        "--io-root",
                        io_root,
                        TypedRequestFactsArgument(
                            contract=contract,
                            expected_args=dict(raw_args),
                            expected_options=dict(raw_options),
                            io_root=io_root,
                        ),
                    ),
                )
            )
            prefixes.append(len(steps))
            preview_name = f"{label}.preview"
            if refusal is not None:
                steps[-1] = replace(
                    steps[-1],
                    allowed_exit_codes=(2,),
                    expected_error_code=refusal.error_code,
                    expected_result_command=refusal.result_command,
                )
                continue
            preview_transaction_id = ResponseBinding(preview_name, "/transaction_id")
            show_name = f"{label}.transaction-show"
            confirm_name = f"{label}.confirm"
            execute_name = f"{label}.execute"
            steps.extend(
                (
                    ExpectedGatewayStep(
                        name=show_name,
                        subcommand="transaction-show",
                        arguments=(preview_transaction_id, "--summary-only"),
                    ),
                    ExpectedGatewayStep(
                        name=confirm_name,
                        subcommand="confirm",
                        arguments=(
                            ResponseBinding(show_name, "/transaction_id"),
                            "--confirmation-token",
                            ResponseBinding(show_name, "/confirmation/token"),
                        ),
                    ),
                    ExpectedGatewayStep(
                        name=execute_name,
                        subcommand="execute",
                        arguments=(ResponseBinding(confirm_name, "/transaction_id"),),
                        allowed_exit_codes=(0, 2),
                        terminal_execute=terminal_execute,
                    ),
                )
            )
            if not terminal_execute:
                steps.append(
                    ExpectedGatewayStep(
                        name=f"{label}.verify",
                        subcommand="verify",
                        arguments=(ResponseBinding(execute_name, "/transaction_id"),),
                    )
                )
            if index == len(normalized):
                prefixes.append(len(steps))
            continue
        steps.append(
            ExpectedGatewayStep(
                name=f"{label}.operation-schema",
                subcommand="operation-schema",
                arguments=(operation,),
            )
        )
        preview_name = f"{label}.preview"
        input_mode = operation_input_mode(operation, str(request["version"]))
        if input_mode == INLINE_TYPED_INPUT_MODE:
            inline_argv = inline_operation_cli_arguments(request)
            steps.append(
                ExpectedGatewayStep(
                    name=preview_name,
                    subcommand="typed-operation",
                    arguments=(
                        inline_argv[0],
                        InlineTypedOperationArgument(request, operation=operation),
                    ),
                    allowed_exit_codes=(2,) if refusal is not None else (0,),
                    expected_error_code=refusal.error_code if refusal is not None else "",
                    expected_result_command=(
                        refusal.result_command if refusal is not None else ""
                    ),
                )
            )
        elif input_mode in {
            COMPOSER_INPUT_MODE,
            BUSINESS_DECLARATION_INPUT_MODE,
        }:
            if operation == "object.set":
                operation_steps = build_object_set_composer_transaction_steps(
                    request,
                    label=label,
                )
            elif (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation == "audio.import"
            ):
                operation_steps = build_audio_import_composer_transaction_steps(
                    request,
                    label=label,
                )
            else:
                operation_steps = _build_generic_typed_draft_transaction_steps(
                    request,
                    label=label,
                    refusal=refusal,
                )
            preview_index = next(
                (
                    position
                    for position, item in enumerate(operation_steps)
                    if item.subcommand == "preview-from-draft"
                ),
                None,
            )
            if preview_index is None:
                raise V3ProtocolError(
                    f"operation {operation!r} typed Draft has no Preview handoff"
                )
            construction = list(operation_steps[1 : preview_index + 1])
            if refusal is not None:
                construction[-1] = replace(
                    construction[-1],
                    allowed_exit_codes=(2,),
                    expected_error_code=refusal.error_code,
                    expected_result_command=refusal.result_command,
                )
            # The typed builders own schema through Preview. The schema step
            # already appended above is identical, so retain only their tail.
            steps.extend(construction)
            preview_name = f"{label}.preview"
        else:
            raise V3ProtocolError(
                f"operation {operation!r} has no typed semantic input mode"
            )
        # Construction of every next Preview belongs to the preceding
        # confirmation turn. Record the cumulative boundary only after that
        # operation's actual typed construction (which may contain many Draft
        # actions), never from a fixed two-step assumption.
        prefixes.append(len(steps))
        if refusal is not None:
            continue

        preview_transaction_id = ResponseBinding(
            preview_name,
            "/transaction_id",
        )
        show_name = f"{label}.transaction-show"
        confirm_name = f"{label}.confirm"
        execute_name = f"{label}.execute"
        steps.extend(
            (
                ExpectedGatewayStep(
                    name=show_name,
                    subcommand="transaction-show",
                    arguments=(preview_transaction_id, "--summary-only"),
                ),
                ExpectedGatewayStep(
                    name=confirm_name,
                    subcommand="confirm",
                    arguments=(
                        ResponseBinding(show_name, "/transaction_id"),
                        "--confirmation-token",
                        ResponseBinding(show_name, "/confirmation/token"),
                    ),
                ),
                ExpectedGatewayStep(
                    name=execute_name,
                    subcommand="execute",
                    arguments=(ResponseBinding(confirm_name, "/transaction_id"),),
                    # Ordinary mutations have two closed outcomes: success
                    # continues to verify, while one exact non-retryable
                    # indeterminate result terminates at execute.  Migration's
                    # terminal_execute flag additionally makes successful
                    # execute terminal because its oracle is caller-owned.
                    allowed_exit_codes=(0, 2),
                    terminal_execute=terminal_execute,
                ),
            )
        )
        if not terminal_execute:
            steps.append(
                ExpectedGatewayStep(
                    name=f"{label}.verify",
                    subcommand="verify",
                    arguments=(ResponseBinding(execute_name, "/transaction_id"),),
                )
            )
        if index == len(normalized):
            prefixes.append(len(steps))
        else:
            # The next loop appends its schema/preview into this same
            # confirmation turn.  Its prefix is recorded after that append.
            continue

    if refusal is not None:
        prefixes = [len(steps)]
    return V3GatewayProtocol(tuple(steps), tuple(prefixes))


def build_metadata_transaction_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    object_type: str,
    object_identity: str | None = None,
    metadata_queries: Sequence[str],
    required_tokens: Sequence[str],
    expected_required_token_projection: (
        Sequence[MetadataTokenProjection] | None
    ) = None,
    equivalence: str = "wire_exact",
    schema_first: bool = False,
) -> V3GatewayProtocol:
    """Add one live object-type discovery to immutable transactions.

    Suggested query phrases define the fixed number of bounded query slots,
    while the broker accepts natural rephrasing.  Every dynamic token must
    occur in that exact brokered discovery payload.  Requests remain wire-exact
    unless the caller selects one explicitly reviewed metadata-bound
    equivalence.  The default keeps discovery first.  ``schema_first`` is the
    closed object-mutation variant: it exposes the configured adapter version
    before the exact reflected object-type scope must be selected.
    """

    if not requests:
        raise V3ProtocolError(
            "metadata-bound transaction protocol requires at least one operation request"
        )
    if not isinstance(schema_first, bool):
        raise V3ProtocolError("schema_first must be a Boolean")
    if equivalence not in {
        "wire_exact",
        "audio_import_v1",
        "audio_import_tab_v1",
        "object_set_v1",
        "object_set_rtpc_v1",
    }:
        raise V3ProtocolError(
            "metadata-bound equivalence must be wire_exact, "
            "audio_import_v1, audio_import_tab_v1, object_set_v1, "
            "or object_set_rtpc_v1"
        )
    if equivalence == "audio_import_v1" and any(
        request.get("operation") != "audio.import"
        for request in requests
    ):
        raise V3ProtocolError(
            "audio_import_v1 is valid only for audio.import requests"
        )
    if equivalence == "audio_import_tab_v1" and any(
        request.get("operation") != "audio.importTabDelimited"
        for request in requests
    ):
        raise V3ProtocolError(
            "audio_import_tab_v1 is valid only for "
            "audio.importTabDelimited requests"
        )
    if equivalence == "object_set_v1" and any(
        request.get("operation") != "object.set"
        for request in requests
    ):
        raise V3ProtocolError(
            "object_set_v1 is valid only for object.set requests"
        )
    if equivalence == "object_set_rtpc_v1" and any(
        request.get("operation") != "object.setRTPC"
        for request in requests
    ):
        raise V3ProtocolError(
            "object_set_rtpc_v1 is valid only for object.setRTPC requests"
        )
    if (
        not isinstance(object_type, str)
        or not object_type
        or object_type != object_type.strip()
        or len(object_type) > 256
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in object_type
        )
    ):
        raise V3ProtocolError(
            "metadata-bound transaction protocol requires one bounded exact object type"
        )
    if object_identity is not None and (
        not isinstance(object_identity, str)
        or not object_identity
        or object_identity != object_identity.strip()
        or len(object_identity) > 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in object_identity)
    ):
        raise V3ProtocolError(
            "metadata-bound transaction object identity must be bounded"
        )
    if isinstance(metadata_queries, (str, bytes)):
        queries: tuple[Any, ...] = ()
    else:
        queries = tuple(metadata_queries)
    if (
        not 1 <= len(queries) <= 8
        or any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 160
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
            for value in queries
        )
        or len({" ".join(value.split()).casefold() for value in queries})
        != len(queries)
        or sum(len(value) for value in queries) > 640
    ):
        raise V3ProtocolError(
            "metadata-bound transaction requires 1..8 distinct bounded query suggestions"
        )
    if isinstance(required_tokens, (str, bytes)):
        tokens: tuple[Any, ...] = ()
    else:
        tokens = tuple(required_tokens)
    if (
        not tokens
        or any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or value.startswith("@")
            or len(value) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
            for value in tokens
        )
        or len(tokens) != len({value.casefold() for value in tokens})
    ):
        raise V3ProtocolError(
            "metadata-bound transaction requires unique exact live tokens"
        )
    projection = (
        None
        if expected_required_token_projection is None
        else tuple(expected_required_token_projection)
    )
    if projection is not None and (
        any(
            not isinstance(item, MetadataTokenProjection)
            for item in projection
        )
        or tuple(item.name for item in projection) != tokens
    ):
        raise V3ProtocolError(
            "expected required-token projection must match required_tokens in order"
        )

    metadata_step_name = "metadata.discover"
    metadata_arguments: list[Any] = [
        "discover",
        "--object" if object_identity is not None else "--object-type",
        object_identity if object_identity is not None else object_type,
    ]
    for query in queries:
        metadata_arguments.extend(
            (
                "--query",
                MetadataQueryArgument(query),
            )
        )
    metadata_arguments.extend(
        ("--limit", str(metadata_candidate_limit(queries)))
    )
    metadata_step = ExpectedGatewayStep(
        name=metadata_step_name,
        subcommand="metadata",
        arguments=tuple(metadata_arguments),
    )
    if equivalence == "audio_import_v1":
        if len(requests) != 1:
            raise V3ProtocolError(
                "audio.import Composer metadata protocol requires one request"
            )
        return build_audio_import_composer_protocol(requests[0])
    base = build_transaction_protocol(requests)
    if not any(
        step.subcommand in {"typed-operation", "preview-from-draft"}
        for step in base.steps
    ):
        raise V3ProtocolError("typed transaction lacks its Preview-producing step")
    if schema_first:
        if (
            not base.steps
            or base.steps[0].subcommand != "operation-schema"
        ):
            raise V3ProtocolError(
                "schema-first metadata requires one typed transaction prefix"
            )
        steps = [base.steps[0], metadata_step, *base.steps[1:]]
    else:
        steps = [metadata_step, *base.steps]
    binding = DraftActionMetadataBinding(
        step=metadata_step_name,
        object_type=object_type,
        required_tokens=tuple(tokens),
        expected_projection=projection,
    )
    bound = False
    for index, step in enumerate(steps):
        arguments = list(step.arguments)
        changed = False
        for argument_index, argument in enumerate(arguments):
            if isinstance(argument, DraftTypedActionArgument):
                action_tokens = _tokens_from_typed_action(argument.expected)
                if action_tokens & set(tokens):
                    arguments[argument_index] = replace(
                        argument,
                        metadata_binding=binding,
                    )
                    changed = True
                    bound = True
            elif isinstance(argument, DraftTypedActionBatchArgument):
                bound_actions: list[DraftTypedActionArgument] = []
                batch_changed = False
                for action in argument.actions:
                    if _tokens_from_typed_action(action.expected) & set(tokens):
                        action = replace(action, metadata_binding=binding)
                        batch_changed = True
                        bound = True
                    bound_actions.append(action)
                if batch_changed:
                    arguments[argument_index] = DraftTypedActionBatchArgument(
                        tuple(bound_actions)
                    )
                    changed = True
            elif isinstance(argument, TypedRequestFactsArgument):
                arguments[argument_index] = replace(
                    argument,
                    metadata_binding=binding,
                )
                changed = True
                bound = True
        if changed:
            steps[index] = replace(step, arguments=tuple(arguments))
    # Inline typed operations carry fixed argv rather than a variable fact
    # sentinel. Bind their Preview-producing step directly to the same sealed
    # metadata response so discovery is evidence, not merely ordering.
    if not bound:
        inline_indexes = tuple(
            index
            for index, step in enumerate(steps)
            if step.subcommand == "typed-operation"
        )
        if len(inline_indexes) == 1:
            inline_index = inline_indexes[0]
            steps[inline_index] = replace(
                steps[inline_index],
                metadata_binding=binding,
            )
            bound = True
    # Generic schema-derived Draft facts describe values by opaque field
    # handles, so token names are not repeated in each action witness. Bind the
    # live metadata projection to the immutable Preview handoff instead; the
    # Broker then proves the exact discovery response before accepting the
    # materialized request.
    if not bound:
        preview_indexes = tuple(
            index
            for index, step in enumerate(steps)
            if step.subcommand == "preview-from-draft"
        )
        if len(preview_indexes) == 1:
            preview_index = preview_indexes[0]
            steps[preview_index] = replace(
                steps[preview_index],
                metadata_binding=binding,
            )
            bound = True
    if not bound:
        raise V3ProtocolError(
            "metadata-bound typed transaction has no token-bearing input"
        )
    return V3GatewayProtocol(
        steps=tuple(steps),
        turn_prefix_counts=tuple(value + 1 for value in base.turn_prefix_counts),
    )


def _tokens_from_typed_action(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {
            str(value["name"])
            for _key in (0,)
            if isinstance(value.get("name"), str)
        }
        for nested in value.values():
            found.update(_tokens_from_typed_action(nested))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for nested in value:
            found.update(_tokens_from_typed_action(nested))
        return found
    return set()


def build_schema_query_transaction_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    query_step: ExpectedGatewayStep,
) -> V3GatewayProtocol:
    """Require one exact object lookup before the typed transaction begins.

    This narrow form is for a same-name merge whose natural request does not
    state the existing root's exact Wwise type.  The lookup remains a required,
    auditable broker step; it is not an optional discovery allowance.  It must
    precede ``operation-schema`` so the schema's sole public continuation can
    be followed directly without inserting an unrelated read in the middle.
    """

    if len(requests) != 1:
        raise V3ProtocolError(
            "schema-query transaction requires exactly one operation request"
        )
    if (
        not isinstance(query_step, ExpectedGatewayStep)
        or query_step.subcommand != "query-object"
        or not query_step.name
    ):
        raise V3ProtocolError(
            "schema-query transaction requires one exact query-object step"
        )
    base = build_transaction_protocol(requests)
    if not base.steps or base.steps[0].subcommand != "operation-schema":
        raise V3ProtocolError(
            "schema-query transaction requires one typed transaction prefix"
        )
    return V3GatewayProtocol(
        steps=(query_step, *base.steps),
        turn_prefix_counts=tuple(value + 1 for value in base.turn_prefix_counts),
    )


def build_direct_protocol(
    steps: Sequence[ExpectedGatewayStep],
) -> V3GatewayProtocol:
    """Build a single-turn exact read/topic protocol supplied by an adapter."""

    values = tuple(steps)
    if not values:
        raise V3ProtocolError("direct protocol requires at least one gateway step")
    return V3GatewayProtocol(values, (len(values),))


def build_modification_policy_protocol(
    base: V3GatewayProtocol,
    *,
    policy: str,
) -> V3GatewayProtocol:
    """Derive one closed mutation protocol for a canonical project policy.

    The input is the already materialized, independently reviewed one-request
    ask-before-changes transaction protocol.  This function changes only the
    policy mechanics: read-only stops after schema without attempting an executable preview,
    ask-before-changes retains the later confirmation turn, and allow-changes
    executes directly from the policy-authorized preview in the same turn.
    """

    if policy not in {"read_only", "ask_before_changes", "allow_changes"}:
        raise V3ProtocolError(
            "modification policy must be read_only, ask_before_changes, or allow_changes"
        )
    if len(base.turn_prefix_counts) != 2 or len(base.steps) < 6:
        raise V3ProtocolError(
            "modification-policy evaluation requires one typed transaction"
        )
    operation_schema = base.steps[0]
    transaction_show, confirm, execute, verify = base.steps[-4:]
    construction = base.steps[:-4]
    preview = construction[-1]
    if (
        operation_schema.subcommand != "operation-schema"
        or preview.subcommand not in {"typed-operation", "preview-from-draft"}
        or transaction_show.subcommand != "transaction-show"
        or confirm.subcommand != "confirm"
        or execute.subcommand != "execute"
        or verify.subcommand != "verify"
        or preview.allowed_exit_codes != (0,)
    ):
        raise V3ProtocolError(
            "base transaction protocol differs from the reviewed six-step shape"
        )
    if policy == "read_only":
        return V3GatewayProtocol(
            steps=(operation_schema,),
            turn_prefix_counts=(1, 1),
            allowed_turn_prefix_counts=((1,), (1,)),
            terminal_prefix_counts=(1,),
        )
    if policy == "ask_before_changes":
        return base

    direct_execute = replace(
        execute,
        arguments=(ResponseBinding(preview.name, "/transaction_id"),),
    )
    direct_verify = replace(
        verify,
        arguments=(ResponseBinding(direct_execute.name, "/transaction_id"),),
    )
    return V3GatewayProtocol(
        steps=(
            *construction,
            direct_execute,
            direct_verify,
        ),
        turn_prefix_counts=(len(construction) + 2,),
    )


def call_step(
    name: str,
    api: str,
    *,
    version: str,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    post_filter: Mapping[str, Any] | None = None,
) -> ExpectedGatewayStep:
    argument_values = _normalize_json_object(
        {} if args is None else args,
        field="call args",
    )
    option_values = _normalize_json_object(
        {} if options is None else options,
        field="call options",
    )
    try:
        contract = request_contract(version, api)
        facts = typed_request_facts_for_values(
            contract,
            args=argument_values,
            options=option_values,
        )
    except (TypeError, ValueError) as exc:
        raise V3ProtocolError(
            f"call request for {api!r} cannot use the typed contract: {exc}"
        ) from exc
    payload = contract.as_gateway_payload()
    input_shape = payload.get("input_shape")
    if input_shape == "draft":
        raise V3ProtocolError(
            f"call request for {api!r} requires the typed Draft lifecycle"
        )
    subcommand = "typed-zero-call" if not contract.fields else "typed-call"
    gateway_arguments: tuple[Any, ...] = (
        api,
        "--schema-digest",
        contract.schema_digest,
        *(("--apply",) if contract.effect != "read" else ()),
    )
    if facts:
        gateway_arguments = (
            *gateway_arguments,
            TypedRequestFactsArgument(
                contract=contract,
                expected_args=argument_values,
                expected_options=option_values,
            ),
        )
    if post_filter is not None:
        post_filter_value = _normalize_json_object(
            post_filter,
            field="call post filter",
        )
        if not post_filter_value:
            raise V3ProtocolError("call post filter must not be empty")
        if api != "ak.wwise.core.mediaPool.get":
            raise V3ProtocolError("typed post filter is supported only for Media Pool")
        filter_value = post_filter_value.get("value")
        filter_limit = post_filter_value.get("limit")
        if set(post_filter_value) != {"value", "limit"}:
            raise V3ProtocolError("typed Media Pool post filter has an invalid shape")
        gateway_arguments = (
            *gateway_arguments,
            "--post-filter-value",
            str(filter_value),
            "--post-filter-limit",
            str(filter_limit),
        )
    return ExpectedGatewayStep(
        name=name,
        subcommand=subcommand,
        arguments=gateway_arguments,
    )


def query_object_step(name: str, arguments: Sequence[str]) -> ExpectedGatewayStep:
    if not arguments or arguments[0] != "query-object":
        raise V3ProtocolError("query-object arguments must start with the subcommand")
    return ExpectedGatewayStep(
        name=name,
        subcommand="query-object",
        arguments=tuple(arguments[1:]),
    )


def query_schema_step(name: str = "query-schema") -> ExpectedGatewayStep:
    return ExpectedGatewayStep(name=name, subcommand="query-schema")


def request_schema_step(name: str, api: str) -> ExpectedGatewayStep:
    if not isinstance(api, str) or not api.startswith("ak.wwise."):
        raise V3ProtocolError("request-schema requires one exact WAAPI API")
    return ExpectedGatewayStep(
        name=name,
        subcommand="request-schema",
        arguments=(api,),
    )


def topic_schema_step(name: str, topic: str) -> ExpectedGatewayStep:
    if not isinstance(topic, str) or not topic.startswith("ak.wwise."):
        raise V3ProtocolError("topic-schema requires one exact WAAPI topic")
    return ExpectedGatewayStep(
        name=name,
        subcommand="topic-schema",
        arguments=(topic,),
    )


def wait_topic_step(
    name: str,
    topic: str,
    *,
    version: str,
    event_count: int,
    match: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    timeout_seconds: float = 120.0,
    schema_step_name: str | None = None,
) -> ExpectedGatewayStep:
    if not isinstance(event_count, int) or isinstance(event_count, bool) or not 1 <= event_count <= 64:
        raise V3ProtocolError("wait-topic event_count must be an integer from 1 through 64")
    if timeout_seconds <= 0:
        raise V3ProtocolError("wait-topic timeout must be positive")
    option_values = _normalize_json_object(
        {} if options is None else options,
        field="wait-topic options",
    )
    match_values = _normalize_json_object(
        {} if match is None else match,
        field="wait-topic match",
    )
    try:
        options_contract = topic_options_contract(version, topic)
        match_contract = topic_match_contract(version, topic)
        option_facts = typed_request_facts_for_values(
            options_contract,
            args={},
            options=option_values,
        )
        match_facts = typed_request_facts_for_values(
            match_contract,
            args=match_values,
            options={},
        )
    except (TypeError, ValueError) as exc:
        raise V3ProtocolError(
            f"Topic {topic!r} cannot use its typed protocol: {exc}"
        ) from exc
    arguments: list[Any] = [
        topic,
        "--event-count",
        str(event_count),
        "--options-schema-digest",
        (
            ResponseBinding(schema_step_name, "/options/schema_digest")
            if schema_step_name is not None
            else options_contract.schema_digest
        ),
        "--match-schema-digest",
        (
            ResponseBinding(schema_step_name, "/event_match/schema_digest")
            if schema_step_name is not None
            else match_contract.schema_digest
        ),
        *(_typed_fact_cli_arguments(option_facts, prefix="option")),
        *(_typed_fact_cli_arguments(match_facts, prefix="match")),
    ]
    return ExpectedGatewayStep(
        name=name,
        subcommand="wait-topic",
        gateway_global_arguments=("--timeout", _format_timeout(timeout_seconds)),
        arguments=tuple(arguments),
        allow_omitted_default_event_count_one=event_count == 1,
    )


def _validate_operation_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise V3ProtocolError("operation request must be a mapping")
    result = _normalize_json_object(request, field="operation request")
    if set(result) != {"contract", "version", "operation", "arguments"}:
        raise V3ProtocolError("operation request must use the closed v1 envelope")
    if result["contract"] != OPERATION_REQUEST_CONTRACT:
        raise V3ProtocolError("operation request contract is invalid")
    if not isinstance(result["version"], str) or not result["version"]:
        raise V3ProtocolError("operation request version must be non-empty")
    if not isinstance(result["operation"], str) or not result["operation"]:
        raise V3ProtocolError("operation request operation must be non-empty")
    if not isinstance(result["arguments"], Mapping) or not result["arguments"]:
        raise V3ProtocolError("operation request arguments must be a non-empty mapping")
    return result


def _normalize_json_object(value: Any, *, field: str) -> dict[str, Any]:
    """Copy one protocol-owned object into strict, recursively plain JSON.

    Reviewed V3 builders freeze data with mapping proxies and tuples.  Broker
    allow-list values must instead be directly serializable by the broker's
    unchanged canonical JSON encoder.  Reject unknown values and malformed
    object keys here, at protocol construction, rather than during a live
    model command.
    """

    if not isinstance(value, Mapping):
        raise V3ProtocolError(f"{field} must be a mapping")
    try:
        normalized = _normalize_json_value(value, field=field, active=set())
        if not isinstance(normalized, dict):  # defensive for runtime callers
            raise V3ProtocolError(f"{field} must normalize to a JSON object")
        json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except V3ProtocolError:
        raise
    except Exception as exc:  # noqa: BLE001 - input mappings must fail as protocol data
        raise V3ProtocolError(f"{field} is not canonical JSON: {exc}") from exc
    return normalized


def _normalize_json_value(
    value: Any,
    *,
    field: str,
    active: set[int],
) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise V3ProtocolError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise V3ProtocolError(f"{field} contains a recursive object")
        active.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, nested in value.items():
                if type(key) is not str:
                    raise V3ProtocolError(
                        f"{field} contains a non-string object key"
                    )
                if key in result:
                    raise V3ProtocolError(
                        f"{field} contains a duplicate object key {key!r}"
                    )
                result[key] = _normalize_json_value(
                    nested,
                    field=f"{field}[{key!r}]",
                    active=active,
                )
            return result
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise V3ProtocolError(f"{field} contains a recursive array")
        active.add(identity)
        try:
            return [
                _normalize_json_value(
                    nested,
                    field=f"{field}[{index}]",
                    active=active,
                )
                for index, nested in enumerate(value)
            ]
        finally:
            active.remove(identity)
    raise V3ProtocolError(
        f"{field} contains non-JSON value {type(value).__name__}"
    )


def _format_timeout(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


__all__ = [
    "StructuredRefusal",
    "V3GatewayProtocol",
    "V3ProtocolError",
    "build_direct_protocol",
    "build_audio_import_composer_protocol",
    "build_audio_import_composer_transaction_steps",
    "build_object_set_composer_transaction_steps",
    "build_modification_policy_protocol",
    "build_metadata_transaction_protocol",
    "build_schema_query_transaction_protocol",
    "build_transaction_protocol",
    "call_step",
    "metadata_candidate_limit",
    "materialize_audio_import_composer_protocol_request",
    "materialize_typed_transaction_protocol_requests",
    "operation_request_equivalence",
    "query_object_step",
    "query_schema_step",
    "request_schema_step",
    "topic_schema_step",
    "wait_topic_step",
]

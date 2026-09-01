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
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_gateway_broker import (
    BoundedIntegerArgument,
    DraftTypedActionArgument,
    DraftTypedActionBatchArgument,
    DraftActionMetadataBinding,
    DraftActionQueryIdentityBinding,
    DraftActionResponseBinding,
    ExactArgumentAlternatives,
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
    validate_optional_topic_schema_step_groups,
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
from wwise_waapi.authoring_ui_business_contracts import (
    authoring_ui_business_contract_data,
)
from wwise_waapi.exact_artifact_business_contracts import (
    EXACT_ARTIFACT_BUSINESS_OPERATIONS,
    exact_artifact_business_contract_data,
)
from wwise_waapi.typed_operations import (
    INLINE_OPERATIONS,
    compound_child_request_contract,
    draft_operation_request_contract,
    inline_operation_cli_arguments,
)
from wwise_waapi.typed_topics import topic_match_contract, topic_options_contract
from wwise_waapi.topic_business import (
    topic_business_contract,
    topic_business_value_choices,
)
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


@dataclass(frozen=True, slots=True)
class CompoundUndoChildExpectation:
    """One canonical child request and its Agent-visible binding selector."""

    request: Mapping[str, Any]
    selector: Mapping[str, Any]


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


@dataclass(slots=True)
class _BusinessDraftSteps:
    """Own the shared mutable-revision grammar for business Draft protocols."""

    label: str
    steps: list[ExpectedGatewayStep]
    draft_start: str
    latest_revision_step: str

    @classmethod
    def start(cls, *, operation: str, label: str) -> _BusinessDraftSteps:
        draft_start = f"{label}.draft-start"
        return cls(
            label=label,
            steps=[
                ExpectedGatewayStep(
                    name=f"{label}.operation-schema",
                    subcommand="operation-schema",
                    arguments=(operation,),
                ),
                ExpectedGatewayStep(
                    name=draft_start,
                    subcommand="draft-start",
                    arguments=(operation,),
                ),
            ],
            draft_start=draft_start,
            latest_revision_step=draft_start,
        )

    def prefix(self) -> tuple[Any, ...]:
        return (
            ResponseBinding(self.draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(self.draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(self.latest_revision_step, "/draft/revision"),
        )

    def advance(self, step_name: str) -> None:
        self.latest_revision_step = step_name

    def bind_object(
        self,
        selector: Any,
        *,
        step_name: str,
        error_subject: str,
        role: str | None = None,
    ) -> ResponseBinding:
        if not isinstance(selector, Mapping):
            raise V3ProtocolError(
                f"{error_subject} identity must be exact id or path"
            )
        kind = selector.get("kind")
        value = selector.get("value")
        if kind == "exact-type-name":
            object_type = selector.get("type")
            name = selector.get("name")
            if (
                set(selector) != {"kind", "type", "name"}
                or not isinstance(object_type, str)
                or not object_type
                or not isinstance(name, str)
                or not name
            ):
                raise V3ProtocolError(
                    f"{error_subject} exact typed name is invalid"
                )
            selector_arguments = (
                "--exact-type-name",
                object_type,
                name,
            )
        elif kind == "path" and isinstance(value, str) and value:
            native_segments = tuple(
                segment for segment in value.split("\\") if segment
            )
            if not native_segments or "\\" + "\\".join(native_segments) != value:
                raise V3ProtocolError(
                    f"{error_subject} path must have canonical Wwise segments"
                )
            segments = tuple(
                re.sub(r"^<[^<>\\]+>", "", segment)
                for segment in native_segments
            )
            if any(not segment or "<" in segment or ">" in segment for segment in segments):
                raise V3ProtocolError(
                    f"{error_subject} path contains unsupported native type syntax"
                )
            selector_arguments: tuple[Any, ...] = tuple(
                item
                for segment in segments
                for item in ("--object-path-segment", segment)
            )
        elif kind == "id" and isinstance(value, str) and value:
            selector_arguments = ("--object-id", value)
        else:
            raise V3ProtocolError(
                f"{error_subject} identity must be exact id, path, or typed name"
            )
        role_arguments: tuple[Any, ...] = () if role is None else ("--role", role)
        self.steps.append(
            ExpectedGatewayStep(
                name=step_name,
                subcommand="draft-bind-object",
                arguments=(*self.prefix(), *role_arguments, *selector_arguments),
            )
        )
        self.advance(step_name)
        return ResponseBinding(step_name, "/bound_object/handle")


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
    existing_target_paths: frozenset[str] | None = None,
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

    draft = _BusinessDraftSteps.start(operation="audio.import", label=label)
    steps = draft.steps
    object_bindings: dict[tuple[str, str], ResponseBinding] = {}
    field_bindings: dict[tuple[str, str, str], ResponseBinding] = {}
    planned_by_path: dict[str, str] = {}
    batch_rows: list[dict[str, Any]] = []
    bind_object_index = 0
    bind_field_index = 0

    def bind_object(selector: Mapping[str, Any]) -> ResponseBinding:
        nonlocal bind_object_index
        kind = selector.get("kind")
        value = selector.get("value")
        if kind not in {"id", "path"} or not isinstance(value, str) or not value:
            raise V3ProtocolError("audio.import business identity must be exact id or path")
        binding_kind = str(kind)
        binding_value = value
        key = (binding_kind, binding_value)
        existing = object_bindings.get(key)
        if existing is not None:
            return existing
        bind_object_index += 1
        step_name = f"{label}.bind-object.{bind_object_index:03d}"
        binding = draft.bind_object(
            selector,
            step_name=step_name,
            error_subject="audio.import business",
        )
        object_bindings[key] = binding
        return binding

    def bind_field(
        *,
        token: str,
        object_handle: ResponseBinding | None,
        class_name: str,
    ) -> ResponseBinding:
        nonlocal bind_field_index
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
                    *draft.prefix(),
                    *scope_arguments,
                    "--token",
                    token,
                ),
            )
        )
        draft.advance(step_name)
        binding = ResponseBinding(step_name, "/bound_field/handle")
        field_bindings[key] = binding
        return binding

    native_mode = arguments.get("import_operation")
    if native_mode not in {None, "createNew", "useExisting", "replaceExisting"}:
        raise V3ProtocolError("audio.import business mode is unsupported")
    mode = "replace" if native_mode == "replaceExisting" else None
    existing_target_form = native_mode in {"useExisting", "replaceExisting"}
    normalized_existing_target_paths = (
        None
        if existing_target_paths is None
        else frozenset(
            re.sub(r"(?<=\\)<[^<>\\]+>", "", path)
            for path in existing_target_paths
        )
    )
    configure_arguments: list[Any] = [*draft.prefix()]
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
    if len(configure_arguments) > len(draft.prefix()):
        configure_name = f"{label}.configure"
        steps.append(
            ExpectedGatewayStep(
                name=configure_name,
                subcommand="draft-business-configure",
                arguments=tuple(configure_arguments),
            )
        )
        draft.advance(configure_name)

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
        token = (
            str(typed_segment or object_type or "")
            .casefold()
            .replace(" ", "")
            .replace("-", "")
        )
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
        row_uses_existing_target = existing_target_form and not (
            native_mode == "useExisting"
            and normalized_existing_target_paths is not None
            and re.sub(r"(?<=\\)<[^<>\\]+>", "", target_path)
            not in normalized_existing_target_paths
        )
        if row_uses_existing_target:
            existing_target_handle = bind_object({"kind": "path", "value": target_path})
            row_form = "existing"
            row_target: Any = existing_target_handle
        else:
            parent_declaration_id = planned_by_path.get(parent_path)
            if parent_declaration_id is None:
                row_form = "new-root"
                row_target = bind_object({"kind": "path", "value": parent_path})
            else:
                row_form = "new-child"
                row_target = parent_declaration_id

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
                if (
                    native_name == "import_language"
                    and kind == "sound-sfx"
                    and str(fields[native_name]).casefold() == "sfx"
                ):
                    continue
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
        if "IgnoreParentMaxSoundInstance" in property_by_name:
            business_fields.append(
                (
                    "override_parent_instance_limit",
                    property_by_name.pop("IgnoreParentMaxSoundInstance"),
                )
            )

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

        declaration_id = f"row-{row_index + 1:03d}"
        batch_rows.append(
            {
                "id": declaration_id,
                "form": row_form,
                "target": row_target,
                "name": name,
                "kind": kind,
                "fields": business_fields,
                "field_values": dynamic_values,
                "event": event_arguments,
            }
        )
        if not existing_target_form:
            planned_by_path[target_path] = declaration_id

    batch_name = f"{label}.declare-batch"
    batch_arguments: list[Any] = [
        *draft.prefix(),
        "--expected-declaration-count",
        str(len(batch_rows)),
        "--expected-switch-assignment-count",
        str(
            sum(
                1
                for row in batch_rows
                for field_name, _value in row["fields"]
                if field_name == "switch_value"
            )
        ),
    ]
    media_values = [
        field_value
        for row in batch_rows
        for field_name, field_value in row["fields"]
        if field_name == "media_file"
    ]
    media_paths = [
        Path(value)
        for value in media_values
        if isinstance(value, str)
    ]
    shared_media_directory: Path | None = None
    if (
        len(media_paths) == len(media_values)
        and len(media_paths) >= 2
        and all(path.is_absolute() and path.name for path in media_paths)
        and len({path.parent for path in media_paths}) == 1
    ):
        shared_media_directory = media_paths[0].parent
        batch_arguments.extend(
            ("--media-directory", str(shared_media_directory))
        )
    for row in batch_rows:
        declaration_id = row["id"]
        batch_arguments.extend(("--row-order", declaration_id))
        if row["form"] == "new-root":
            batch_arguments.extend(
                (
                    "--new-row",
                    declaration_id,
                    row["target"],
                    row["name"],
                    row["kind"],
                )
            )
        elif row["form"] == "new-child":
            batch_arguments.extend(
                (
                    "--new-row",
                    declaration_id,
                    row["target"],
                    row["name"],
                    row["kind"],
                )
            )
        else:
            batch_arguments.extend(
                ("--existing-row", declaration_id, row["target"])
            )
        for field_name, field_value in row["fields"]:
            rendered_value = (
                field_value
                if isinstance(field_value, ResponseBinding)
                else value_text(field_value)
            )
            if field_name == "switch_value":
                batch_arguments.extend(
                    ("--switch-value", declaration_id, rendered_value)
                )
            elif (
                field_name == "media_file"
                and shared_media_directory is not None
            ):
                batch_arguments.extend(
                    (
                        "--media-file",
                        declaration_id,
                        Path(str(rendered_value)).name,
                    )
                )
            else:
                batch_arguments.extend(
                    ("--field", declaration_id, field_name, rendered_value)
                )
        for field_handle, field_value in row["field_values"]:
            batch_arguments.extend(
                (
                    "--field-value",
                    declaration_id,
                    field_handle,
                    (
                        field_value
                        if isinstance(field_value, ResponseBinding)
                        else value_text(field_value)
                    ),
                )
            )
        event_arguments = row["event"]
        if event_arguments:
            batch_arguments.extend(
                (
                    "--event",
                    declaration_id,
                    event_arguments[1],
                    event_arguments[3],
                    event_arguments[5],
                )
            )
    steps.append(
        ExpectedGatewayStep(
            name=batch_name,
            subcommand="draft-declare-import-batch",
            arguments=tuple(batch_arguments),
            allow_explicit_derived_sfx_language=all(
                row["kind"] == "sound-sfx" for row in batch_rows
            ),
        )
    )
    draft.advance(batch_name)

    # The public business continuation tells a fresh Agent to bind every exact
    # live object before it configures or declares the import batch.  Keep the
    # formal Broker protocol in that same Gateway-owned order.  The inverse
    # builder discovers bindings while walking declarations, so normalize the
    # finished setup here and rebuild only the optimistic revision chain; all
    # object/field/declaration handle dependencies retain their named sources.
    fixed_prefix = steps[:2]
    mutable_business_steps = steps[2:]
    binding_steps = [
        step
        for step in mutable_business_steps
        if step.subcommand in {"draft-bind-object", "draft-bind-field"}
    ]
    configure_steps = [
        step
        for step in mutable_business_steps
        if step.subcommand == "draft-business-configure"
    ]
    declaration_steps = [
        step
        for step in mutable_business_steps
        if step.subcommand
        in {
            "draft-declare-import-batch",
            "draft-declare-new",
            "draft-declare-existing",
        }
    ]
    if len(binding_steps) + len(configure_steps) + len(declaration_steps) != len(
        mutable_business_steps
    ):
        raise V3ProtocolError("audio.import business setup contains an unknown step")
    ordered_business_steps = (
        *binding_steps,
        *configure_steps,
        *declaration_steps,
    )
    resequenced_steps: list[ExpectedGatewayStep] = []
    previous_revision_step = draft.draft_start
    for step in ordered_business_steps:
        arguments = list(step.arguments)
        if (
            len(arguments) < 5
            or arguments[3] != "--expected-revision"
            or not isinstance(arguments[4], ResponseBinding)
        ):
            raise V3ProtocolError(
                "audio.import business setup lacks a bound revision argument"
            )
        arguments[4] = ResponseBinding(
            previous_revision_step,
            "/draft/revision",
        )
        resequenced = replace(step, arguments=tuple(arguments))
        resequenced_steps.append(resequenced)
        previous_revision_step = resequenced.name
    steps = [*fixed_prefix, *resequenced_steps]
    draft.steps = steps
    draft.advance(previous_revision_step)
    request_witness: Mapping[str, Any] = normalized
    if native_mode == "createNew":
        witness_arguments = dict(normalized["arguments"])
        witness_arguments.pop("import_operation", None)
        request_witness = {
            **normalized,
            "arguments": witness_arguments,
        }

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
                arguments=(*draft.prefix(),),
            ),
            ExpectedGatewayStep(
                name=preview_name,
                subcommand="preview-from-draft",
                arguments=(
                    ResponseBinding(draft.draft_start, "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(draft.draft_start, "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(check_name, "/draft/revision"),
                ),
                expected_operation_request=request_witness,
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


OBJECT_LIFECYCLE_BUSINESS_OPERATIONS = frozenset(
    {
        "object.copy",
        "object.delete",
        "object.move",
        "object.setName",
        "object.setNotes",
    }
)

OBJECT_METADATA_BUSINESS_OPERATIONS = frozenset(
    {
        "object.setLinked",
        "object.setProperty",
        "object.setReference",
    }
)

SWITCH_ASSIGNMENT_BUSINESS_OPERATIONS = frozenset(
    {
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    }
)

SOUNDBANK_BUSINESS_OPERATIONS = frozenset(
    {
        "soundbank.convertExternalSources",
        "soundbank.generate",
        "soundbank.processDefinitionFiles",
        "soundbank.setInclusions",
    }
)

OBJECT_GRAPH_BUSINESS_OPERATIONS = frozenset({"object.create", "object.set"})


def _business_selector_key(selector: Mapping[str, Any], *, subject: str) -> str:
    """Return one strict, order-independent identity key for protocol reuse."""

    try:
        return json.dumps(
            selector,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise V3ProtocolError(f"{subject} identity is not strict JSON") from exc


def _business_scalar_cli_value(value: Any, *, subject: str) -> Any:
    """Encode one closed scalar without leaking a native field type choice."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise V3ProtocolError(f"{subject} numeric value must be finite")
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if isinstance(value, float) and value.is_integer():
            return ExactArgumentAlternatives((str(int(value)), encoded))
        return encoded
    if isinstance(value, str):
        return value
    raise V3ProtocolError(f"{subject} field value is unsupported")


def _build_object_set_business_transaction_steps(
    normalized: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one closed bulk object edit into Business Draft declarations."""

    try:
        parsed = parse_operation_request(normalized)
    except OperationContractError as exc:
        raise V3ProtocolError(
            f"object set business request is invalid: {exc}"
        ) from exc
    arguments = parsed.arguments
    if set(arguments) - {"objects", "on_name_conflict"}:
        raise V3ProtocolError("object set business request fields are not closed")
    objects = arguments.get("objects")
    if not isinstance(objects, list) or not objects:
        raise V3ProtocolError("object set business request requires target rows")

    draft = _BusinessDraftSteps.start(operation="object.set", label=label)
    steps = draft.steps
    object_handles: dict[str, ResponseBinding] = {}
    field_handles: dict[tuple[str, str], ResponseBinding] = {}

    def bind(selector: Any, *, role: str) -> ResponseBinding:
        if not isinstance(selector, Mapping):
            raise V3ProtocolError("object set identity must be an object")
        key = _business_selector_key(selector, subject="object set")
        existing = object_handles.get(key)
        if existing is not None:
            return existing
        step_name = f"{label}.bind-{role}-{len(object_handles) + 1:02d}"
        handle = draft.bind_object(
            selector,
            step_name=step_name,
            error_subject="object set business",
        )
        object_handles[key] = handle
        return handle

    prepared: list[dict[str, Any]] = []
    for index, row in enumerate(objects, start=1):
        if not isinstance(row, Mapping) or set(row) - {
            "object",
            "notes",
            "properties",
            "references",
            "children",
        }:
            raise V3ProtocolError("object set target row is not closed")
        target = bind(row.get("object"), role=f"target-{index:02d}")
        references = row.get("references", [])
        if not isinstance(references, list):
            raise V3ProtocolError("object set references must be an array")
        reference_rows: list[tuple[str, ResponseBinding | None]] = []
        for reference in references:
            if (
                not isinstance(reference, Mapping)
                or set(reference) != {"name", "target"}
                or not isinstance(reference.get("name"), str)
            ):
                raise V3ProtocolError("object set reference is not closed")
            target_selector = reference.get("target")
            target_handle = (
                None
                if target_selector is None
                else bind(target_selector, role=f"reference-{index:02d}")
            )
            reference_rows.append((str(reference["name"]), target_handle))
        prepared.append(
            {
                "index": index,
                "row": row,
                "target": target,
                "references": tuple(reference_rows),
            }
        )

    for item in prepared:
        row = item["row"]
        properties = row.get("properties", [])
        if not isinstance(properties, list):
            raise V3ProtocolError("object set properties must be an array")
        for prop in properties:
            if (
                not isinstance(prop, Mapping)
                or set(prop) != {"name", "value"}
                or not isinstance(prop.get("name"), str)
            ):
                raise V3ProtocolError("object set property is not closed")
            name = str(prop["name"])
            if name == "Volume":
                continue
            key = (
                _business_selector_key(row["object"], subject="object set"),
                name,
            )
            if key in field_handles:
                continue
            step_name = f"{label}.discover-field-{len(field_handles) + 1:02d}"
            steps.append(
                ExpectedGatewayStep(
                    name=step_name,
                    subcommand="draft-discover-fields",
                    arguments=(
                        *draft.prefix(),
                        "--object-handle",
                        item["target"],
                        "--meaning",
                        name.casefold(),
                    ),
                )
            )
            draft.advance(step_name)
            field_handles[key] = ResponseBinding(
                step_name,
                "/field_candidates/0/handle",
            )

    native_kind = {
        "ActorMixer": "actor-mixer",
        "RandomSequenceContainer": "random-container",
        "Sound": "sound-sfx",
    }

    def declare_child(
        child: Mapping[str, Any],
        *,
        parent_handle: Any,
        declaration_id: str,
        step_suffix: str,
    ) -> None:
        if not isinstance(child, Mapping) or set(child) - {
            "type",
            "name",
            "children",
            "properties",
            "notes",
        }:
            raise V3ProtocolError("object set child declaration is not closed")
        object_type = child.get("type")
        name = child.get("name")
        if object_type not in native_kind or not isinstance(name, str) or not name:
            raise V3ProtocolError("object set child type or name is unsupported")
        arguments_out: list[Any] = [
            *draft.prefix(),
            "--declaration-id",
            declaration_id,
            "--parent-handle",
            parent_handle,
            "--name",
            name,
            "--kind",
            native_kind[str(object_type)],
        ]
        notes = child.get("notes")
        if notes is not None:
            arguments_out.extend(
                (
                    "--field",
                    "notes",
                    _business_scalar_cli_value(notes, subject="object set"),
                )
            )
        properties = child.get("properties", [])
        if not isinstance(properties, list):
            raise V3ProtocolError("object set child properties must be an array")
        for prop in properties:
            if (
                not isinstance(prop, Mapping)
                or set(prop) != {"name", "value"}
                or prop.get("name") != "Volume"
            ):
                raise V3ProtocolError(
                    "object set child property requires a reviewed stable field"
                )
            arguments_out.extend(
                (
                    "--field",
                    "volume_db",
                    _business_scalar_cli_value(
                        prop.get("value"), subject="object set"
                    ),
                )
            )
        step_name = f"{label}.declare-{step_suffix}"
        steps.append(
            ExpectedGatewayStep(
                name=step_name,
                subcommand="draft-declare-new",
                arguments=tuple(arguments_out),
            )
        )
        draft.advance(step_name)
        child_parent = ResponseBinding(
            step_name,
            "/draft/declared_object/result_handle",
        )
        nested = child.get("children", [])
        if not isinstance(nested, list):
            raise V3ProtocolError("object set nested children must be an array")
        for nested_index, nested_child in enumerate(nested, start=1):
            declare_child(
                nested_child,
                parent_handle=child_parent,
                declaration_id=f"{declaration_id}-{nested_index:02d}",
                step_suffix=f"{step_suffix}-{nested_index:02d}",
            )

    for item in prepared:
        row = item["row"]
        declaration_id = f"target-{item['index']:02d}"
        arguments_out: list[Any] = [
            *draft.prefix(),
            "--declaration-id",
            declaration_id,
            "--object-handle",
            item["target"],
        ]
        if "notes" in row:
            arguments_out.extend(
                (
                    "--field",
                    "notes",
                    _business_scalar_cli_value(
                        row["notes"], subject="object set"
                    ),
                )
            )
        for prop in row.get("properties", []):
            name = str(prop["name"])
            if name == "Volume":
                arguments_out.extend(
                    (
                        "--field",
                        "volume_db",
                        _business_scalar_cli_value(
                            prop.get("value"), subject="object set"
                        ),
                    )
                )
            else:
                arguments_out.extend(
                    (
                        "--field-value",
                        field_handles[
                            (
                                _business_selector_key(
                                    row["object"], subject="object set"
                                ),
                                name,
                            )
                        ],
                        _business_scalar_cli_value(
                            prop.get("value"), subject="object set"
                        ),
                    )
                )
        for name, target_handle in item["references"]:
            if name != "OutputBus" or target_handle is None:
                raise V3ProtocolError(
                    "object set reference requires one bound output bus"
                )
            arguments_out.extend(("--field", "output_bus", target_handle))
        step_name = f"{label}.declare-existing-{item['index']:02d}"
        steps.append(
            ExpectedGatewayStep(
                name=step_name,
                subcommand="draft-declare-existing",
                arguments=tuple(arguments_out),
            )
        )
        draft.advance(step_name)
        parent_handle = ResponseBinding(
            step_name,
            "/draft/declared_object/result_handle",
        )
        children = row.get("children", [])
        if not isinstance(children, list):
            raise V3ProtocolError("object set children must be an array")
        for child_index, child in enumerate(children, start=1):
            declare_child(
                child,
                parent_handle=parent_handle,
                declaration_id=f"{declaration_id}-child-{child_index:02d}",
                step_suffix=f"child-{item['index']:02d}-{child_index:02d}",
            )

    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(steps)


def build_object_graph_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
    parent_selector: Mapping[str, Any] | None = None,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one closed recursive object tree into Business Draft steps."""

    normalized = _validate_operation_request(request)
    if normalized["operation"] not in OBJECT_GRAPH_BUSINESS_OPERATIONS:
        raise V3ProtocolError(
            "object graph business builder requires object.create"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    if normalized["operation"] == "object.set":
        return _build_object_set_business_transaction_steps(
            normalized,
            label=label,
        )
    try:
        parsed = parse_operation_request(normalized)
    except OperationContractError as exc:
        raise V3ProtocolError(
            f"object graph business request is invalid: {exc}"
        ) from exc
    arguments = parsed.arguments
    allowed_root_fields = {
        "parent",
        "type",
        "name",
        "children",
        "properties",
        "references",
        "notes",
        "on_name_conflict",
        "platform",
        "auto_add_to_source_control",
        "replace_owned_root",
    }
    if (
        set(arguments) - allowed_root_fields
        or not isinstance(arguments.get("type"), str)
        or not isinstance(arguments.get("name"), str)
        or not arguments["name"]
    ):
        raise V3ProtocolError("object graph business root is not closed")

    kind_by_native_type = {
        "ActorMixer": "actor-mixer",
        "BlendContainer": "blend-container",
        "MusicRanSeqCntr": "music-playlist-container",
        "MusicSegment": "music-segment",
        "MusicSwitchContainer": "music-switch-container",
        "MusicTrack": "music-track",
        "RandomSequenceContainer": "random-container",
        "Sound": "sound-sfx",
        "SwitchContainer": "switch-container",
        "Folder": "virtual-folder",
    }
    reference_handles: dict[str, ResponseBinding] = {}

    def semantic_kind(node: Mapping[str, Any]) -> str:
        native_type = node.get("type")
        try:
            kind = kind_by_native_type[str(native_type)]
        except KeyError as exc:
            raise V3ProtocolError(
                f"object graph native type {native_type!r} has no reviewed business kind"
            ) from exc
        language = node.get("language")
        if native_type == "Sound" and isinstance(language, str) and language != "SFX":
            return "sound-voice"
        return kind

    def stable_fields(node: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
        fields: list[tuple[str, Any]] = []
        notes = node.get("notes")
        if notes is not None:
            if not isinstance(notes, str):
                raise V3ProtocolError("object graph notes must be text")
            fields.append(("notes", notes))
        language = node.get("language")
        if language is not None:
            if not isinstance(language, str) or not language:
                raise V3ProtocolError("object graph language must be text")
            fields.append(("language", language))
        properties = node.get("properties", [])
        if not isinstance(properties, list):
            raise V3ProtocolError("object graph properties must be an array")
        property_map: dict[str, Any] = {}
        for row in properties:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"name", "value"}
                or not isinstance(row.get("name"), str)
                or row["name"] in property_map
            ):
                raise V3ProtocolError("object graph properties are not closed")
            property_map[str(row["name"])] = row.get("value")
        looping = property_map.pop("IsLoopingEnabled", None)
        infinite = property_map.pop("IsLoopingInfinite", None)
        if looping is not None or infinite is not None:
            if looping is True and infinite is True:
                fields.append(("loop", "infinite"))
            elif looping is False and infinite in {None, False}:
                fields.append(("loop", "off"))
            else:
                raise V3ProtocolError(
                    "object graph loop fields do not form one closed business value"
                )
        field_names = {
            "Volume": "volume_db",
            "MaxNumInstances": "max_instances",
            "OverrideParentMaxNumInstances": "override_parent_instance_limit",
        }
        for native_name, value in property_map.items():
            try:
                field_name = field_names[native_name]
            except KeyError as exc:
                raise V3ProtocolError(
                    f"object graph property {native_name!r} requires a bound field handle"
                ) from exc
            fields.append(
                (
                    field_name,
                    _business_scalar_cli_value(value, subject="object graph"),
                )
            )
        references = node.get("references", [])
        if not isinstance(references, list):
            raise V3ProtocolError("object graph references must be an array")
        for reference in references:
            if (
                not isinstance(reference, Mapping)
                or set(reference) != {"name", "target"}
                or reference.get("name") != "OutputBus"
                or not isinstance(reference.get("target"), Mapping)
            ):
                raise V3ProtocolError(
                    "object graph reference requires one output bus target"
                )
            try:
                handle = reference_handles[
                    _business_selector_key(
                        reference["target"],
                        subject="object graph reference",
                    )
                ]
            except KeyError as exc:
                raise V3ProtocolError(
                    "object graph reference target was not pre-bound"
                ) from exc
            fields.append(("output_bus", handle))
        return tuple(fields)

    def children(node: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        raw = node.get("children", [])
        if not isinstance(raw, list):
            raise V3ProtocolError("object graph children must be an array")
        values: list[Mapping[str, Any]] = []
        for child in raw:
            if not isinstance(child, Mapping):
                raise V3ProtocolError("object graph child must be an object")
            allowed = {
                "type",
                "name",
                "children",
                "properties",
                "references",
                "notes",
                "language",
            }
            if (
                set(child) - allowed
                or not isinstance(child.get("type"), str)
                or not isinstance(child.get("name"), str)
                or not child["name"]
            ):
                raise V3ProtocolError("object graph child shape is not closed")
            values.append(child)
        return tuple(values)

    draft = _BusinessDraftSteps.start(operation="object.create", label=label)
    steps = draft.steps
    selector = arguments.get("parent") if parent_selector is None else parent_selector
    parent_handle = draft.bind_object(
        selector,
        step_name=f"{label}.bind-parent",
        error_subject="object graph business parent",
    )

    def bind_references(node: Mapping[str, Any]) -> None:
        references = node.get("references", [])
        if not isinstance(references, list):
            raise V3ProtocolError("object graph references must be an array")
        for reference in references:
            if (
                not isinstance(reference, Mapping)
                or set(reference) != {"name", "target"}
                or reference.get("name") != "OutputBus"
                or not isinstance(reference.get("target"), Mapping)
            ):
                raise V3ProtocolError(
                    "object graph reference requires one output bus target"
                )
            selector = reference["target"]
            key = _business_selector_key(
                selector,
                subject="object graph reference",
            )
            if key not in reference_handles:
                step_name = (
                    f"{label}.bind-reference-{len(reference_handles) + 1:02d}"
                )
                reference_handles[key] = draft.bind_object(
                    selector,
                    step_name=step_name,
                    error_subject="object graph reference target",
                )
        for child in children(node):
            bind_references(child)

    bind_references(arguments)
    conflict = arguments.get("on_name_conflict")
    configure_arguments: list[Any] = [*draft.prefix()]
    if conflict is not None:
        if conflict not in {"fail", "rename", "merge", "replace"}:
            raise V3ProtocolError("object graph name conflict policy is invalid")
        configure_arguments.extend(("--name-conflict", str(conflict)))
    if "platform" in arguments:
        configure_arguments.extend(("--platform", str(arguments["platform"])))
    if "auto_add_to_source_control" in arguments:
        configure_arguments.append(
            "--add-to-source-control"
            if arguments["auto_add_to_source_control"] is True
            else "--no-add-to-source-control"
        )
    replace_owner = arguments.get("replace_owned_root")
    if replace_owner is not None:
        configure_suffix = configure_arguments[len(draft.prefix()) :]
        owner_handle = draft.bind_object(
            replace_owner,
            step_name=f"{label}.bind-replace-owner",
            error_subject="object graph replacement owner",
        )
        configure_arguments = [*draft.prefix(), *configure_suffix]
        configure_arguments.extend(("--replace-owner-handle", owner_handle))
    if len(configure_arguments) > len(draft.prefix()):
        configure_name = f"{label}.configure"
        steps.append(
            ExpectedGatewayStep(
                name=configure_name,
                subcommand="draft-business-configure",
                arguments=tuple(configure_arguments),
            )
        )
        draft.advance(configure_name)

    def declare(
        node: Mapping[str, Any],
        *,
        parent: Any,
        declaration_id: str,
        step_suffix: str,
    ) -> None:
        step_name = f"{label}.declare-{step_suffix}"
        declaration_arguments: list[Any] = [
            *draft.prefix(),
            "--declaration-id",
            declaration_id,
            "--parent-handle",
            parent,
            "--name",
            str(node["name"]),
            "--kind",
            semantic_kind(node),
        ]
        for field_name, value in stable_fields(node):
            declaration_arguments.extend(("--field", field_name, value))
        steps.append(
            ExpectedGatewayStep(
                name=step_name,
                subcommand="draft-declare-new",
                arguments=tuple(declaration_arguments),
            )
        )
        draft.advance(step_name)
        child_parent = ResponseBinding(
            step_name,
            "/draft/declared_object/result_handle",
        )
        for child_index, child in enumerate(children(node), start=1):
            declare(
                child,
                parent=child_parent,
                declaration_id=f"{declaration_id}-{child_index:02d}",
                step_suffix=f"{step_suffix}-{child_index:02d}",
            )

    declare(
        arguments,
        parent=parent_handle,
        declaration_id="root",
        step_suffix="root",
    )

    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(steps)


def build_object_lifecycle_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one canonical object lifecycle request into Business Draft steps."""

    normalized = _validate_operation_request(request)
    operation = str(normalized["operation"])
    if operation not in OBJECT_LIFECYCLE_BUSINESS_OPERATIONS:
        raise V3ProtocolError(
            "object lifecycle business builder requires one reviewed operation"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    arguments = normalized["arguments"]
    allowed_fields = {
        "object.copy": {
            "object",
            "parent",
            "on_name_conflict",
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        },
        "object.delete": {"object", "auto_check_out_to_source_control"},
        "object.move": {
            "object",
            "parent",
            "on_name_conflict",
            "auto_check_out_to_source_control",
        },
        "object.setName": {"object", "value"},
        "object.setNotes": {"object", "value"},
    }[operation]
    if set(arguments) - allowed_fields:
        raise V3ProtocolError(
            "object lifecycle business request fields are not supported"
        )
    try:
        parsed = parse_operation_request(normalized)
    except OperationContractError as exc:
        raise V3ProtocolError(
            f"object lifecycle business request is invalid: {exc}"
        ) from exc
    canonical_arguments = parsed.arguments

    draft = _BusinessDraftSteps.start(operation=operation, label=label)
    steps = draft.steps

    def bind_object(selector: Mapping[str, Any], *, role: str) -> ResponseBinding:
        step_name = f"{label}.bind-{role}"
        return draft.bind_object(
            selector,
            step_name=step_name,
            error_subject="object lifecycle business",
        )

    object_selector = canonical_arguments.get("object")
    if not isinstance(object_selector, Mapping):
        raise V3ProtocolError("object lifecycle business request lacks object identity")
    object_handle = bind_object(object_selector, role="object")
    parent_handle: ResponseBinding | None = None
    if operation in {"object.copy", "object.move"}:
        parent_selector = canonical_arguments.get("parent")
        if not isinstance(parent_selector, Mapping):
            raise V3ProtocolError(
                "object lifecycle business request lacks parent identity"
            )
        parent_handle = bind_object(parent_selector, role="parent")

    declaration_arguments: list[Any] = [
        *draft.prefix(),
        "--object-handle",
        object_handle,
    ]
    if parent_handle is not None:
        declaration_arguments.extend(("--parent-handle", parent_handle))
    value = canonical_arguments.get("value")
    if operation == "object.setName":
        declaration_arguments.extend(("--new-name", str(value)))
    elif operation == "object.setNotes":
        declaration_arguments.extend(("--notes", str(value)))
    if "on_name_conflict" in canonical_arguments:
        declaration_arguments.extend(
            ("--name-conflict", str(canonical_arguments["on_name_conflict"]))
        )
    for field, positive, negative in (
        (
            "auto_add_to_source_control",
            "--add-to-source-control",
            "--no-add-to-source-control",
        ),
        (
            "auto_check_out_to_source_control",
            "--check-out-from-source-control",
            "--no-check-out-from-source-control",
        ),
    ):
        if field in canonical_arguments:
            declaration_arguments.append(
                positive if canonical_arguments[field] is True else negative
            )
    declaration_name = f"{label}.declare-object-change"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-object-change",
            arguments=tuple(declaration_arguments),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(steps)


def build_compound_undo_business_transaction_steps(
    children: Sequence[CompoundUndoChildExpectation],
    *,
    display_name: str,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Compose checked child Business Drafts into one compound Preview."""

    if not 1 <= len(children) <= 32:
        raise V3ProtocolError("compound Undo requires 1..32 child requests")
    if not isinstance(display_name, str) or not display_name.strip():
        raise V3ProtocolError("compound Undo display name is invalid")
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    normalized_children = tuple(
        _validate_operation_request(child.request) for child in children
    )
    versions = {str(request["version"]) for request in normalized_children}
    if len(versions) != 1:
        raise V3ProtocolError("compound Undo children must share one version")
    (version,) = tuple(versions)
    if any(
        request["operation"] not in OBJECT_LIFECYCLE_BUSINESS_OPERATIONS
        for request in normalized_children
    ):
        raise V3ProtocolError(
            "Fresh compound Undo profile accepts object lifecycle children only"
        )
    parent_request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.undoGroup",
        "arguments": {
            "display_name": display_name,
            "calls": [
                {
                    "schema_digest": compound_child_request_contract(
                        str(request["operation"]), version
                    ).schema_digest,
                    "request": request,
                }
                for request in normalized_children
            ],
        },
    }
    try:
        normalized_parent = parse_operation_request(parent_request).as_dict()
    except OperationContractError as exc:
        raise V3ProtocolError(f"compound Undo request is invalid: {exc}") from exc

    parent = _BusinessDraftSteps.start(operation="waapi.undoGroup", label=label)
    steps: list[ExpectedGatewayStep] = list(parent.steps)
    checked_child_labels: list[str] = []
    for index, request in enumerate(normalized_children, start=1):
        child_label = f"tx{index:02d}"
        flow_request = {
            **request,
            "arguments": {
                **dict(request["arguments"]),
                "object": dict(children[index - 1].selector),
            },
        }
        child_steps = list(
            build_object_lifecycle_business_transaction_steps(
                flow_request,
                label=child_label,
            )
        )
        if not child_steps or child_steps[-1].subcommand != "preview-from-draft":
            raise V3ProtocolError("compound Undo child protocol lacks Preview terminal")
        child_steps.pop()
        steps.extend(child_steps)
        checked_child_labels.append(child_label)

    declaration_arguments: list[Any] = [
        *parent.prefix(),
        "--display-name",
        display_name,
    ]
    for child_label in checked_child_labels:
        declaration_arguments.extend(
            (
                "--child-draft",
                ResponseBinding(f"{child_label}.draft-start", "/draft/draft_id"),
                ResponseBinding(f"{child_label}.draft-start", "/task_authority"),
            )
        )
    declaration_name = f"{label}.declare-undo-plan"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-undo-plan",
            arguments=tuple(declaration_arguments),
        )
    )
    parent.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=parent.prefix(),
        )
    )
    parent.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=parent.prefix(),
            expected_operation_request=normalized_parent,
        )
    )
    return tuple(steps)


def build_switch_assignment_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one exact relationship outcome into bound business Draft steps."""

    normalized = _validate_operation_request(request)
    operation = str(normalized["operation"])
    if operation not in SWITCH_ASSIGNMENT_BUSINESS_OPERATIONS:
        raise V3ProtocolError(
            "Switch assignment business builder requires one reviewed operation"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    try:
        parsed = parse_operation_request(normalized)
    except OperationContractError as exc:
        raise V3ProtocolError(
            f"Switch assignment business request is invalid: {exc}"
        ) from exc
    arguments = parsed.arguments
    if set(arguments) != {
        "switch_container",
        "child",
        "state_or_switch",
    }:
        raise V3ProtocolError(
            "Switch assignment business request fields are not closed"
        )

    draft = _BusinessDraftSteps.start(operation=operation, label=label)
    steps = draft.steps
    handles: dict[str, ResponseBinding] = {}
    for role in ("switch_container", "child", "state_or_switch"):
        step_name = f"{label}.bind-{role.replace('_', '-')}"
        handles[role] = draft.bind_object(
            arguments[role],
            step_name=step_name,
            error_subject=f"Switch assignment {role}",
            role=role,
        )

    declaration_name = f"{label}.declare-switch-assignment"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-switch-assignment",
            arguments=(
                *draft.prefix(),
                "--switch-container-handle",
                handles["switch_container"],
                "--child-handle",
                handles["child"],
                "--state-or-switch-handle",
                handles["state_or_switch"],
            ),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(steps)


def build_core_business_transaction_steps(
    *,
    api: str,
    version: str,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Seal one explicit no-checkout Core save Draft through one Preview."""

    if api != "ak.wwise.core.project.save" or version != "2025.1":
        raise V3ProtocolError("Core business Fresh proof supports exact 2025.1 project.save")
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    draft_start = f"{label}.draft-start"
    declaration = f"{label}.declare-core-plan"
    check = f"{label}.check"

    def prefix(revision_step: str) -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(revision_step, "/draft/revision"),
        )

    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {"autoCheckOutToSourceControl": False},
            "options": {},
        },
    }
    return (
        ExpectedGatewayStep(
            name=f"{label}.request-schema",
            subcommand="request-schema",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=draft_start,
            subcommand="draft-start",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=declaration,
            subcommand="draft-declare-core-plan",
            arguments=(
                *prefix(draft_start),
                "--value",
                "auto_check_out",
                "false",
            ),
        ),
        ExpectedGatewayStep(
            name=check,
            subcommand="draft-check",
            arguments=prefix(declaration),
        ),
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=prefix(check),
            expected_operation_request=request,
        ),
    )


def build_audio_convert_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one audio.convert native witness into its public Core Draft."""

    normalized = _validate_operation_request(request)
    arguments = normalized.get("arguments")
    if (
        normalized.get("operation") != "waapi.call"
        or not isinstance(arguments, Mapping)
        or arguments.get("api") != "ak.wwise.core.audio.convert"
        or set(arguments) != {"api", "args", "options", "io_root"}
        or arguments.get("options") != {}
    ):
        raise V3ProtocolError(
            "audio.convert business request must be one closed waapi.call witness"
        )
    raw_args = arguments.get("args")
    io_root = arguments.get("io_root")
    if (
        not isinstance(raw_args, Mapping)
        or set(raw_args) != {"objects", "platforms", "languages"}
        or not isinstance(io_root, str)
        or not io_root
    ):
        raise V3ProtocolError("audio.convert business request fields are incomplete")

    def strings(field: str) -> tuple[str, ...]:
        value = raw_args.get(field)
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise V3ProtocolError(
                f"audio.convert {field} must be a nonempty string array"
            )
        return tuple(value)

    objects = strings("objects")
    platforms = strings("platforms")
    languages = strings("languages")
    draft = _BusinessDraftSteps.start(
        operation="ak.wwise.core.audio.convert",
        label=label,
    )
    # This exact-URI business route is discovered through request-schema.
    draft.steps[0] = replace(
        draft.steps[0],
        name=f"{label}.request-schema",
        subcommand="request-schema",
        arguments=("ak.wwise.core.audio.convert",),
    )
    handles = tuple(
        draft.bind_object(
            {"kind": "path", "value": path},
            step_name=f"{label}.bind-audio-object-{index:02d}",
            error_subject="audio.convert object",
            role="audio_object",
        )
        for index, path in enumerate(objects, start=1)
    )
    declaration_name = f"{label}.declare-core-plan"
    declaration: list[Any] = [*draft.prefix()]
    for handle in handles:
        declaration.extend(("--role", "audio_object_handles", handle))
    for platform in platforms:
        declaration.extend(("--item", "platform_names", platform))
    for language in languages:
        declaration.extend(("--item", "languages", language))
    declaration.extend(("--value", "io_root", io_root))
    draft.steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-core-plan",
            arguments=tuple(declaration),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    draft.steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    draft.steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(draft.steps)


def build_cli_console_business_transaction_steps(
    *,
    api: str,
    version: str,
    label: str,
    project_file: str,
    output_directory: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Seal one SoundBank build intent through the deep CLI Business Draft."""

    if api != "ak.wwise.cli.generateSoundbank" or version != "2025.1":
        raise V3ProtocolError(
            "CLI/Console business Fresh proof supports exact 2025.1 SoundBank generation"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    if (
        not isinstance(project_file, str)
        or not Path(project_file).is_absolute()
        or not project_file.casefold().endswith(".wproj")
    ):
        raise V3ProtocolError(
            "CLI/Console business Fresh proof requires one absolute WPROJ path"
        )
    if output_directory != "GeneratedSoundBanks/FreshAgent":
        raise V3ProtocolError(
            "CLI/Console business Fresh proof requires the reviewed relative output"
        )
    draft_start = f"{label}.draft-start"
    declaration = f"{label}.declare-cli-console-plan"
    check = f"{label}.check"

    def prefix(revision_step: str) -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(revision_step, "/draft/revision"),
        )

    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {
                "project": project_file,
                "platform": ["Windows"],
                "skip-languages": True,
                "no-source-control": True,
                "soundbank-path": ["Windows", output_directory],
                "quiet": True,
            },
            "options": {},
            "io_root": str(Path(project_file).parent),
        },
    }
    return (
        ExpectedGatewayStep(
            name=f"{label}.request-schema",
            subcommand="request-schema",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=draft_start,
            subcommand="draft-start",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=declaration,
            subcommand="draft-declare-cli-console-plan",
            arguments=(
                *prefix(draft_start),
                "--value",
                "project_file",
                project_file,
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
                output_directory,
                "--value",
                "verbosity",
                "quiet",
            ),
        ),
        ExpectedGatewayStep(
            name=check,
            subcommand="draft-check",
            arguments=prefix(declaration),
        ),
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=prefix(check),
            expected_operation_request=request,
        ),
    )


def build_debug_control_business_transaction_steps(
    *,
    version: str,
    label: str,
    enabled: bool,
) -> tuple[ExpectedGatewayStep, ...]:
    """Build one safe named Debug boolean Preview from one business outcome."""

    if version != "2021.1" or type(enabled) is not bool:
        raise V3ProtocolError(
            "Debug-control Fresh proof requires Wwise 2021.1 and one boolean outcome"
        )
    draft = _BusinessDraftSteps.start(
        operation="debug.setAutomationMode",
        label=label,
    )
    declaration_name = f"{label}.declare-debug-intent"
    draft.steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-debug-intent",
            arguments=(
                *draft.prefix(),
                "--enable" if enabled else "--disable",
            ),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    draft.steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    draft.steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request={
                "contract": "waapi-skill.operation-request/v1",
                "version": version,
                "operation": "debug.setAutomationMode",
                "arguments": {"enabled": enabled},
            },
        )
    )
    return tuple(draft.steps)


def build_host_ui_debug_business_transaction_steps(
    *,
    version: str,
    label: str,
    output_file: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Build one closed test-tone Preview through business units only."""

    api = "ak.wwise.debug.generateToneWAV"
    draft_start = f"{label}.draft-start"
    declaration = f"{label}.declare-host-plan"
    check = f"{label}.check"

    def prefix(revision_step: str) -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(revision_step, "/draft/revision"),
        )

    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {
                "path": output_file,
                "waveform": "sine",
                "frequency": 440,
                "channelConfig": "2.0",
                "bitDepth": "int16",
                "sampleRate": 48000,
                "attackTime": 0.05,
                "sustainTime": 1.0,
                "releaseTime": 0.1,
                "sustainLevel": -6,
                "setAnonymous": True,
                "waveformChannelMask": 3,
            },
            "options": {},
            "io_root": str(Path(output_file).parent),
        },
    }
    return (
        ExpectedGatewayStep(
            name=f"{label}.request-schema",
            subcommand="request-schema",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=draft_start,
            subcommand="draft-start",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=declaration,
            subcommand="draft-declare-host-plan",
            arguments=(
                *prefix(draft_start),
                "--value",
                "output_file",
                output_file,
                "--value",
                "waveform",
                "sine",
                "--value",
                "frequency_hz",
                "440",
                "--value",
                "channel_layout",
                "2.0",
                "--value",
                "bit_depth",
                "int16",
                "--value",
                "sample_rate_hz",
                "48000",
                "--value",
                "attack_seconds",
                "0.05",
                "--value",
                "sustain_seconds",
                "1.0",
                "--value",
                "release_seconds",
                "0.1",
                "--value",
                "sustain_db",
                "-6",
                "--toggle",
                "anonymous_channels",
                "enable",
                "--item",
                "waveform_channels",
                "0",
                "--item",
                "waveform_channels",
                "1",
            ),
        ),
        ExpectedGatewayStep(
            name=check,
            subcommand="draft-check",
            arguments=prefix(declaration),
        ),
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=prefix(check),
            expected_operation_request=request,
        ),
    )


def build_project_setting_business_transaction_steps(
    *,
    version: str,
    label: str,
    object_id: str,
    object_name: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Seal one Game Parameter range outcome through the business Draft."""

    api = "ak.wwise.core.gameParameter.setRange"
    if version != "2025.1":
        raise V3ProtocolError(
            "Project-setting Fresh proof supports exact Wwise 2025.1"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    if not isinstance(object_id, str) or not re.fullmatch(
        r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}",
        object_id,
    ):
        raise V3ProtocolError("Project-setting Fresh proof requires one exact GUID")
    if (
        not isinstance(object_name, str)
        or not object_name.strip()
        or object_name != object_name.strip()
        or len(object_name) > 255
        or any(separator in object_name for separator in ("\\", "/"))
    ):
        raise V3ProtocolError(
            "Project-setting Fresh proof requires one bounded exact object name"
        )
    draft_start = f"{label}.draft-start"
    bind = f"{label}.bind-game-parameter"
    declaration = f"{label}.declare-project-setting-plan"
    check = f"{label}.check"

    def prefix(revision_step: str) -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(revision_step, "/draft/revision"),
        )

    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {
                "object": object_id.upper(),
                "min": -10.0,
                "max": 100.0,
                "onCurveUpdate": "stretch",
            },
            "options": {},
        },
    }
    return (
        ExpectedGatewayStep(
            name=f"{label}.request-schema",
            subcommand="request-schema",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=draft_start,
            subcommand="draft-start",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=bind,
            subcommand="draft-bind-object",
            arguments=(
                *prefix(draft_start),
                "--role",
                "game_parameter",
                "--exact-type-name",
                "GameParameter",
                object_name,
            ),
        ),
        ExpectedGatewayStep(
            name=declaration,
            subcommand="draft-declare-project-setting-plan",
            arguments=(
                *prefix(bind),
                "--game-parameter-handle",
                ResponseBinding(bind, "/bound_object/handle"),
                "--minimum",
                "-10",
                "--maximum",
                "100",
                "--curve-update-outcome",
                "stretch",
            ),
        ),
        ExpectedGatewayStep(
            name=check,
            subcommand="draft-check",
            arguments=prefix(declaration),
        ),
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=prefix(check),
            expected_operation_request=request,
        ),
    )


def build_runtime_control_business_transaction_steps(
    *,
    version: str,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Seal one Profiler data-selection outcome through the runtime Draft."""

    api = "ak.wwise.core.profiler.enableProfilerData"
    if version != "2025.1":
        raise V3ProtocolError(
            "Runtime-control Fresh proof supports exact Wwise 2025.1"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    draft_start = f"{label}.draft-start"
    declaration = f"{label}.declare-runtime-control-plan"
    check = f"{label}.check"

    def prefix(revision_step: str) -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(revision_step, "/draft/revision"),
        )

    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {
                "dataTypes": [
                    {"dataType": "voices", "enable": True},
                ]
            },
            "options": {},
        },
    }
    return (
        ExpectedGatewayStep(
            name=f"{label}.request-schema",
            subcommand="request-schema",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=draft_start,
            subcommand="draft-start",
            arguments=(api,),
        ),
        ExpectedGatewayStep(
            name=declaration,
            subcommand="draft-declare-runtime-control-plan",
            arguments=(
                *prefix(draft_start),
                "--capture-data",
                "voices",
                "enable",
            ),
        ),
        ExpectedGatewayStep(
            name=check,
            subcommand="draft-check",
            arguments=prefix(declaration),
        ),
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=prefix(check),
            expected_operation_request=request,
        ),
    )


def build_soundengine_business_transaction_steps(
    *,
    version: str,
    label: str,
    operation: str = "ak.soundengine.postMsgMonitor",
    monitor_message: str = "",
    game_object_name: str = "",
    event_id: str = "",
    event_name: str = "",
    listener_handle: str = "",
    listener_id: int = 0,
) -> tuple[ExpectedGatewayStep, ...]:
    """Seal one reviewed SoundEngine intent through the Business Draft."""

    if version != "2022.1":
        raise V3ProtocolError(
            "SoundEngine Fresh proof supports exact Wwise 2022.1"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    supported = {
        "ak.soundengine.postMsgMonitor",
        "ak.soundengine.registerGameObj",
        "ak.soundengine.executeActionOnEvent",
        "ak.soundengine.setListenerSpatialization",
    }
    if operation not in supported:
        raise V3ProtocolError("SoundEngine Fresh operation is not reviewed")
    draft_start = f"{label}.draft-start"
    declaration = f"{label}.declare-soundengine-plan"
    check = f"{label}.check"

    def prefix(revision_step: str) -> tuple[Any, ...]:
        return (
            ResponseBinding(draft_start, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(draft_start, "/task_authority"),
            "--expected-revision",
            ResponseBinding(revision_step, "/draft/revision"),
        )

    declaration_arguments: tuple[Any, ...]
    request: Mapping[str, Any] | None
    bind_step: ExpectedGatewayStep | None = None
    revision_step = draft_start
    if operation == "ak.soundengine.postMsgMonitor":
        if (
            not isinstance(monitor_message, str)
            or not monitor_message.strip()
            or monitor_message != monitor_message.strip()
            or len(monitor_message.encode("utf-8")) > 512
        ):
            raise V3ProtocolError(
                "SoundEngine monitor message must be one bounded exact value"
            )
        declaration_arguments = ("--monitor-message", monitor_message)
        native_args: Mapping[str, Any] = {"message": monitor_message}
    elif operation == "ak.soundengine.registerGameObj":
        if (
            not isinstance(game_object_name, str)
            or not game_object_name.strip()
            or game_object_name != game_object_name.strip()
            or len(game_object_name.encode("utf-8")) > 512
        ):
            raise V3ProtocolError(
                "SoundEngine game object name must be one bounded exact value"
            )
        declaration_arguments = ("--game-object-name", game_object_name)
        native_args = {"name": game_object_name}
    elif operation == "ak.soundengine.executeActionOnEvent":
        if not isinstance(event_id, str) or not re.fullmatch(
            r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}",
            event_id,
        ):
            raise V3ProtocolError("SoundEngine Event proof requires one exact GUID")
        if (
            not isinstance(event_name, str)
            or not event_name.strip()
            or event_name != event_name.strip()
        ):
            raise V3ProtocolError("SoundEngine Event proof requires one exact name")
        bind_name = f"{label}.bind-event"
        bind_step = ExpectedGatewayStep(
            name=bind_name,
            subcommand="draft-bind-object",
            arguments=(
                *prefix(draft_start),
                "--role",
                "event",
                "--exact-type-name",
                "Event",
                event_name,
            ),
        )
        revision_step = bind_name
        declaration_arguments = (
            "--event-handle",
            ResponseBinding(bind_name, "/bound_object/handle"),
            "--action",
            "Stop",
            "--fade-duration-ms",
            "250",
            "--fade-curve",
            "Linear",
        )
        native_args = {
            "event": event_id.upper(),
            "actionType": 0,
            "gameObject": 0xFFFFFFFFFFFFFFFF,
            "transitionDuration": 250,
            "fadeCurve": 4,
        }
    else:
        if not isinstance(listener_handle, str) or not re.fullmatch(
            r"goh1-[0-9a-f]{32}", listener_handle
        ):
            raise V3ProtocolError(
                "SoundEngine listener proof requires one opaque handle"
            )
        if (
            isinstance(listener_id, bool)
            or not isinstance(listener_id, int)
            or not 0 <= listener_id <= 0xFFFFFFFFFFFFFFDF
        ):
            raise V3ProtocolError(
                "SoundEngine listener proof requires one valid native fixture ID"
            )
        declaration_arguments = (
            "--listener-handle",
            listener_handle,
            "--spatialization",
            "enabled",
            "--channel-layout",
            "5.1",
        )
        native_args = {
            "listener": listener_id,
            "spatialized": True,
            "channelConfig": 6 | (1 << 8) | (0x60F << 12),
            "volumeOffsets": [0.0] * 6,
        }

    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": operation,
            "args": dict(native_args),
            "options": {},
        },
    }
    steps: list[ExpectedGatewayStep] = [
        ExpectedGatewayStep(
            name=f"{label}.request-schema",
            subcommand="request-schema",
            arguments=(operation,),
        ),
        ExpectedGatewayStep(
            name=draft_start,
            subcommand="draft-start",
            arguments=(operation,),
        ),
    ]
    if bind_step is not None:
        steps.append(bind_step)
    steps.extend(
        (
            ExpectedGatewayStep(
            name=declaration,
            subcommand="draft-declare-soundengine-plan",
            arguments=(
                    *prefix(revision_step),
                    *declaration_arguments,
            ),
        ),
        ExpectedGatewayStep(
            name=check,
            subcommand="draft-check",
            arguments=prefix(declaration),
        ),
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=prefix(check),
                expected_operation_request=(
                    None
                    if operation == "ak.soundengine.registerGameObj"
                    else request
                ),
        ),
        )
    )
    return tuple(steps)


def build_authoring_ui_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one capture or live-command choice into one UI Business Draft."""

    normalized = _validate_operation_request(request)
    operation = str(normalized["operation"])
    if operation not in {"ui.captureScreen", "ui.commands.execute"}:
        raise V3ProtocolError(
            "Authoring UI Fresh builder supports capture and execute previews"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    version = str(normalized["version"])
    try:
        authoring_ui_business_contract_data(operation, version)
        parsed = parse_operation_request(normalized)
    except (OperationContractError, ValueError) as exc:
        raise V3ProtocolError(
            f"Authoring UI business request is invalid: {exc}"
        ) from exc
    arguments = parsed.arguments
    declaration: list[Any] = []
    if operation == "ui.captureScreen":
        if set(arguments) - {"view_name", "view_channel", "rect"}:
            raise V3ProtocolError("capture business request fields are not closed")
        if "view_name" in arguments:
            declaration.extend(("--view-name", str(arguments["view_name"])))
        if "view_channel" in arguments:
            declaration.extend(("--view-channel", str(arguments["view_channel"])))
        if "rect" in arguments:
            rect = arguments["rect"]
            if not isinstance(rect, Mapping):
                raise V3ProtocolError("capture rectangle is invalid")
            declaration.extend(
                (
                    "--rect",
                    str(rect["x"]),
                    str(rect["y"]),
                    str(rect["width"]),
                    str(rect["height"]),
                )
            )
    else:
        if "command" not in arguments or set(arguments) - {
            "command",
            "objects",
            "platforms",
            "value",
            "files",
        }:
            raise V3ProtocolError("command business request fields are not closed")
        declaration.extend(("--command-id", str(arguments["command"])))
        for field, flag in (
            ("objects", "--command-object"),
            ("platforms", "--command-platform"),
            ("files", "--command-file"),
        ):
            for value in arguments.get(field, []):
                declaration.extend((flag, str(value)))
        if "value" in arguments:
            value = arguments["value"]
            if value is None:
                kind, encoded = "null", "null"
            elif type(value) is bool:
                kind, encoded = "boolean", "true" if value else "false"
            elif type(value) is int:
                kind, encoded = "integer", str(value)
            elif type(value) is float:
                kind, encoded = "number", json.dumps(value, allow_nan=False)
            elif isinstance(value, str):
                kind, encoded = "string", value
            else:  # pragma: no cover - canonical parser rejects this first
                raise V3ProtocolError("command value is not a strict scalar")
            declaration.extend(("--value", kind, encoded))

    draft = _BusinessDraftSteps.start(operation=operation, label=label)
    steps = draft.steps
    steps[:0] = [
        ExpectedGatewayStep(
            name=f"{label}.operations",
            subcommand="operations",
        )
    ]
    declaration_name = f"{label}.declare-ui-plan"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-ui-plan",
            arguments=(*draft.prefix(), *declaration),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(steps)


def build_soundbank_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one closed SoundBank request into one complete business plan."""

    normalized = _validate_operation_request(request)
    operation = str(normalized["operation"])
    if operation not in SOUNDBANK_BUSINESS_OPERATIONS:
        raise V3ProtocolError(
            "SoundBank business builder requires one reviewed operation"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    try:
        parsed = parse_operation_request(normalized)
    except OperationContractError as exc:
        raise V3ProtocolError(
            f"SoundBank business request is invalid: {exc}"
        ) from exc
    arguments = parsed.arguments
    draft = _BusinessDraftSteps.start(operation=operation, label=label)
    steps = draft.steps
    bound: dict[str, ResponseBinding] = {}
    binding_index = 0

    def bind(
        selector: Any,
        *,
        role: str,
        object_type: str | None = None,
    ) -> ResponseBinding:
        nonlocal binding_index
        if object_type is not None:
            if not isinstance(selector, str) or not selector:
                raise V3ProtocolError("SoundBank name binding is invalid")
            selector = {
                "kind": "exact-type-name",
                "type": object_type,
                "name": selector,
            }
        if not isinstance(selector, Mapping):
            raise V3ProtocolError("SoundBank object identity is invalid")
        key = json.dumps(
            {"role": role, "selector": dict(selector)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = bound.get(key)
        if existing is not None:
            return existing
        binding_index += 1
        result = draft.bind_object(
            selector,
            step_name=f"{label}.bind-object.{binding_index:03d}",
            error_subject="SoundBank business",
            role=role,
        )
        bound[key] = result
        return result

    initial_prefix = draft.prefix()
    declaration_arguments: list[Any] = [*initial_prefix]
    if operation == "soundbank.setInclusions":
        declaration_arguments.extend(
            (
                "--mode",
                str(arguments["mode"]),
                "--soundbank-handle",
                bind(arguments["soundbank"], role="soundbank"),
            )
        )
        for row in arguments["inclusions"]:
            object_handle = bind(row["object"], role="inclusion_object")
            declaration_arguments.extend(
                (
                    "--inclusion",
                    object_handle,
                    *(str(filter_name) for filter_name in row["filters"]),
                )
            )
    elif operation == "soundbank.generate":
        bank_handles: list[tuple[Mapping[str, Any], ResponseBinding]] = []
        for bank in arguments["soundbanks"]:
            handle = bind(
                str(bank["name"]),
                role="soundbank",
                object_type="SoundBank",
            )
            bank_handles.append((bank, handle))
        declaration_arguments = [*draft.prefix()]
        inclusion_names = {
            "event": "events",
            "structure": "structures",
            "media": "media",
        }
        for bank, handle in bank_handles:
            declaration_arguments.extend(
                (
                    "--soundbank",
                    handle,
                    str(bank["artifact_expectation"]),
                )
            )
            for selector in bank.get("events", []):
                declaration_arguments.extend(
                    ("--event", handle, bind(selector, role="event"))
                )
            for selector in bank.get("aux_busses", []):
                declaration_arguments.extend(
                    ("--aux-bus", handle, bind(selector, role="aux_bus"))
                )
            inclusions = tuple(bank.get("inclusions", []))
            if inclusions:
                declaration_arguments.extend(
                    (
                        "--generation-inclusion",
                        handle,
                        *(
                            inclusion_names[str(inclusion)]
                            for inclusion in inclusions
                        ),
                    )
                )
            if "rebuild" in bank:
                declaration_arguments.extend(
                    (
                        "--rebuild-soundbank"
                        if bank["rebuild"] is True
                        else "--no-rebuild-soundbank",
                        handle,
                    )
                )
        for platform in arguments["platforms"]:
            declaration_arguments.extend(("--platform", str(platform)))
        for language in arguments.get("languages", []):
            declaration_arguments.extend(("--language", str(language)))
        for field, flag in (
            ("rebuild_soundbanks", "rebuild-soundbanks"),
            ("clear_audio_file_cache", "clear-audio-file-cache"),
            ("rebuild_init_bank", "rebuild-init-bank"),
        ):
            if field in arguments:
                declaration_arguments.append(
                    f"--{flag}" if arguments[field] is True else f"--no-{flag}"
                )
        declaration_arguments.extend(("--io-root", str(arguments["io_root"])))
    elif operation == "soundbank.convertExternalSources":
        for source in arguments["sources"]:
            declaration_arguments.extend(
                (
                    "--source",
                    str(source["input"]),
                    str(source["platform"]),
                    str(source["output"]),
                )
            )
        declaration_arguments.extend(("--io-root", str(arguments["io_root"])))
    else:
        for path in arguments["files"]:
            declaration_arguments.extend(("--definition-file", str(path)))
        declaration_arguments.extend(("--io-root", str(arguments["io_root"])))

    declaration_arguments[: len(initial_prefix)] = draft.prefix()
    declaration_name = f"{label}.declare-soundbank-plan"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-soundbank-plan",
            arguments=tuple(declaration_arguments),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
        )
    )
    return tuple(steps)


_TAB_IMPORT_NATIVE_TO_BUSINESS_MODE = {
    "createNew": "create",
    "useExisting": "reimport",
    "replaceExisting": "replace",
}


def _exact_artifact_argument_cli(
    arguments: Mapping[str, Any],
) -> tuple[str, ...]:
    """Encode one exact strict-JSON map through the public business CLI."""

    values: list[str] = []
    for key, value in arguments.items():
        if not isinstance(key, str) or not key:
            raise V3ProtocolError("Lua business argument keys must be non-empty strings")
        if isinstance(value, str):
            value_type = "string"
            encoded = value
        elif type(value) is bool:
            value_type = "boolean"
            encoded = "true" if value else "false"
        elif type(value) is int:
            value_type = "integer"
            encoded = str(value)
        elif type(value) is float and math.isfinite(value):
            value_type = "number"
            encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        elif value is None:
            value_type = "null"
            encoded = "null"
        elif isinstance(value, (dict, list)):
            value_type = "json"
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        else:
            raise V3ProtocolError(
                "Lua business arguments must contain only strict JSON values"
            )
        values.extend(("--argument", key, value_type, encoded))
    return tuple(values)


def build_exact_artifact_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate exact user artifacts into one Gateway-owned business plan."""

    normalized = _validate_operation_request(request)
    operation = str(normalized["operation"])
    if operation not in EXACT_ARTIFACT_BUSINESS_OPERATIONS:
        raise V3ProtocolError(
            "exact-artifact business builder requires one reviewed operation"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    version = str(normalized["version"])
    try:
        exact_artifact_business_contract_data(operation, version)
    except ValueError as exc:
        raise V3ProtocolError(
            f"exact-artifact business request is unavailable: {exc}"
        ) from exc
    arguments = normalized["arguments"]
    required_by_operation = {
        "audio.importTabDelimited": {
            "import_file",
            "import_location",
            "import_language",
        },
        "lua.executeCliFile": {
            "script_file",
            "io_root",
            "source_authority",
        },
        "lua.executeCoreFile": {
            "script_file",
            "io_root",
            "source_authority",
        },
        "lua.executeCoreInline": {
            "lua_code",
            "io_root",
            "source_authority",
        },
    }
    optional_by_operation = {
        "audio.importTabDelimited": {
            "import_operation",
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        },
        "lua.executeCliFile": {"wa_args", "watchdog_seconds"},
        "lua.executeCoreFile": {"wa_args"},
        "lua.executeCoreInline": {"wa_args"},
    }
    required = required_by_operation[operation]
    if not required.issubset(arguments) or set(arguments) - (
        required | optional_by_operation[operation]
    ):
        raise V3ProtocolError(
            "exact-artifact business request fields are not closed"
        )
    draft = _BusinessDraftSteps.start(operation=operation, label=label)
    steps = draft.steps
    declaration_arguments: list[Any] = []
    expected_request = normalized

    if operation == "audio.importTabDelimited":
        if (
            not isinstance(arguments["import_file"], str)
            or not arguments["import_file"]
            or not isinstance(arguments["import_language"], str)
            or not arguments["import_language"]
        ):
            raise V3ProtocolError("tabular import exact fields are invalid")
        location = arguments["import_location"]
        location_handle = draft.bind_object(
            location,
            step_name=f"{label}.bind-import-location",
            error_subject="tabular import location",
            role="import_location",
        )
        declaration_arguments.extend(
            (
                "--table-file",
                str(arguments["import_file"]),
                "--location-handle",
                location_handle,
                "--language",
                str(arguments["import_language"]),
            )
        )
        if "import_operation" in arguments:
            mode = _TAB_IMPORT_NATIVE_TO_BUSINESS_MODE.get(
                arguments["import_operation"]
            )
            if mode is None:
                raise V3ProtocolError("tabular import operation is invalid")
            declaration_arguments.extend(("--mode", mode))
        for native, positive, negative in (
            (
                "auto_add_to_source_control",
                "--add-to-source-control",
                "--no-add-to-source-control",
            ),
            (
                "auto_check_out_to_source_control",
                "--check-out-from-source-control",
                "--no-check-out-from-source-control",
            ),
        ):
            if native in arguments:
                if type(arguments[native]) is not bool:
                    raise V3ProtocolError(
                        "tabular import source-control settings must be Boolean"
                    )
                declaration_arguments.append(
                    positive if arguments[native] else negative
                )
    else:
        authority = arguments.get("source_authority")
        if authority != "user_supplied_verbatim":
            raise V3ProtocolError(
                "Lua source authority must be the closed user-supplied constant"
            )
        if operation.endswith("File"):
            script_file = arguments["script_file"]
            if not isinstance(script_file, str) or not script_file:
                raise V3ProtocolError("Lua script file must be one exact path")
            declaration_arguments.extend(("--script-file", script_file))
            expected_arguments = dict(arguments)
            expected_arguments["io_root"] = str(Path(script_file).parent)
            expected_request = dict(normalized)
            expected_request["arguments"] = expected_arguments
        else:
            if (
                not isinstance(arguments["lua_code"], str)
                or not arguments["lua_code"]
                or not isinstance(arguments["io_root"], str)
                or not arguments["io_root"]
            ):
                raise V3ProtocolError(
                    "inline Lua source and io_root must be non-empty strings"
                )
            declaration_arguments.extend(
                (
                    "--lua-source",
                    arguments["lua_code"],
                    "--io-root",
                    arguments["io_root"],
                )
            )
        wa_args = arguments.get("wa_args", {})
        if not isinstance(wa_args, Mapping):
            raise V3ProtocolError("Lua wa_args must be one strict JSON object")
        declaration_arguments.extend(_exact_artifact_argument_cli(wa_args))
        if "watchdog_seconds" in arguments:
            watchdog = arguments["watchdog_seconds"]
            if (
                version not in {"2024.1", "2025.1"}
                or type(watchdog) is not int
                or watchdog < 0
            ):
                raise V3ProtocolError(
                    "Lua CLI watchdog is available as a non-negative integer on Wwise 2024.1+"
                )
            declaration_arguments.extend(
                ("--watchdog-seconds", str(watchdog))
            )

    declaration_name = f"{label}.declare-artifact-plan"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-artifact-plan",
            arguments=(*draft.prefix(), *declaration_arguments),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=expected_request,
        )
    )
    return tuple(steps)


def build_object_metadata_business_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
    field_meaning: str | None = None,
    object_selector: Mapping[str, Any] | None = None,
    target_selector: Mapping[str, Any] | None = None,
    discover_before_target: bool = True,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one canonical field edit into bound business Draft steps."""

    normalized = _validate_operation_request(request)
    operation = str(normalized["operation"])
    if operation not in OBJECT_METADATA_BUSINESS_OPERATIONS:
        raise V3ProtocolError(
            "object metadata business builder requires one reviewed operation"
        )
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("business transaction label must be txNN")
    try:
        parsed = parse_operation_request(normalized)
    except OperationContractError as exc:
        raise V3ProtocolError(
            f"object metadata business request is invalid: {exc}"
        ) from exc
    arguments = parsed.arguments
    field_name = (
        arguments.get("reference")
        if operation == "object.setReference"
        else arguments.get("property")
    )
    if not isinstance(field_name, str) or not field_name:
        raise V3ProtocolError("object metadata business request lacks field meaning")
    discovery_meaning = field_name if field_meaning is None else field_meaning
    if not isinstance(discovery_meaning, str) or not discovery_meaning.strip():
        raise V3ProtocolError("object metadata business field meaning is invalid")

    draft = _BusinessDraftSteps.start(operation=operation, label=label)
    steps = draft.steps

    def bind_object(selector: Any, *, role: str) -> ResponseBinding:
        if not isinstance(selector, Mapping):
            raise V3ProtocolError(
                f"object metadata business request lacks {role} identity"
            )
        step_name = f"{label}.bind-{role}"
        return draft.bind_object(
            selector,
            step_name=step_name,
            error_subject="object metadata business",
        )

    source_handle = bind_object(
        arguments.get("object") if object_selector is None else object_selector,
        role="object",
    )
    target_handle: ResponseBinding | None = None
    if (
        operation == "object.setReference"
        and arguments.get("target") is not None
        and not discover_before_target
    ):
        target_handle = bind_object(
            arguments.get("target") if target_selector is None else target_selector,
            role="target",
        )

    discover_name = f"{label}.discover-field"
    discover_arguments: list[Any] = [
        *draft.prefix(),
        "--object-handle",
        source_handle,
        "--meaning",
        discovery_meaning,
    ]
    if "platform" in arguments:
        discover_arguments.extend(("--platform", str(arguments["platform"])))
    steps.append(
        ExpectedGatewayStep(
            name=discover_name,
            subcommand="draft-discover-fields",
            arguments=tuple(discover_arguments),
        )
    )
    draft.advance(discover_name)
    field_handle = ResponseBinding(discover_name, "/field_candidates/0/handle")
    if (
        operation == "object.setReference"
        and arguments.get("target") is not None
        and discover_before_target
    ):
        target_handle = bind_object(
            arguments.get("target") if target_selector is None else target_selector,
            role="target",
        )
    declaration_arguments: list[Any] = [
        *draft.prefix(),
        "--object-handle",
        source_handle,
        "--field-handle",
        field_handle,
    ]
    if operation == "object.setProperty":
        value = arguments.get("value")
        if isinstance(value, bool):
            value_text = "true" if value else "false"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            value_text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        elif isinstance(value, str):
            value_text = value
        else:
            raise V3ProtocolError(
                "object metadata business property value is unsupported"
            )
        declaration_arguments.extend(("--business-value", value_text))
    elif operation == "object.setReference":
        declaration_arguments.extend(
            ("--target-handle", target_handle)
            if target_handle is not None
            else ("--clear-reference",)
        )
    else:
        declaration_arguments.extend(
            (
                "--link-state",
                "linked" if arguments.get("linked") is True else "unlinked",
            )
        )
    declaration_name = f"{label}.declare-field-change"
    steps.append(
        ExpectedGatewayStep(
            name=declaration_name,
            subcommand="draft-declare-field-change",
            arguments=tuple(declaration_arguments),
        )
    )
    draft.advance(declaration_name)
    check_name = f"{label}.check"
    steps.append(
        ExpectedGatewayStep(
            name=check_name,
            subcommand="draft-check",
            arguments=draft.prefix(),
        )
    )
    draft.advance(check_name)
    steps.append(
        ExpectedGatewayStep(
            name=f"{label}.preview",
            subcommand="preview-from-draft",
            arguments=draft.prefix(),
            expected_operation_request=normalized,
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
            and protocol.steps[terminal_index].expected_operation_request is None
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
        elif (
            protocol.steps[terminal_index].expected_operation_request
            is not None
        ):
            request = _validate_operation_request(
                protocol.steps[terminal_index].expected_operation_request
            )
            request_arguments = request.get("arguments")
            request_operation = request.get("operation")
            operation_matches = request_operation == operation or (
                request_operation == "waapi.call"
                and isinstance(request_arguments, Mapping)
                and request_arguments.get("api") == operation
            )
            if not operation_matches or request["version"] != version:
                raise V3ProtocolError(
                    "business request witness differs from its Draft binding"
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
    existing_target_paths: frozenset[str] | None = None,
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
            existing_target_paths=existing_target_paths,
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
    optional_topic_schema_step_groups: tuple[tuple[str, ...], ...] = ()

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
        optional_topic_groups = validate_optional_topic_schema_step_groups(
            self.steps,
            self.optional_topic_schema_step_groups,
        )
        if optional_topic_groups != self.optional_topic_schema_step_groups:
            raise ValueError(
                "optional Topic schema step groups must use canonical tuples"
            )
        if optional_topic_groups and not self.allowed_turn_prefix_counts:
            raise ValueError(
                "optional Topic schema steps require explicit allowed prefixes"
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
        for group in optional_topic_groups:
            start = indexes[group[0]]
            if any(
                start < count < start + len(group)
                for count in self.turn_prefix_counts
            ):
                raise ValueError(
                    "an optional Topic schema group cannot cross a turn prefix"
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

    @property
    def optional_query_schema_step_names(self) -> tuple[str, ...]:
        """Return the bounded leading query disclosures that may be omitted.

        A closed business query may be issued directly, after the ordinary
        business schema, or after both the ordinary and advanced read-only
        schemas.  The selected disclosure reads remain broker-authenticated;
        only their presence is optional and the final business query is still
        exact.
        """

        maximum = len(self.steps)
        optional = self.steps[:-1]
        allowed = tuple(range(1, maximum + 1))
        return (
            tuple(step.name for step in optional)
            if maximum >= 2
            and self.steps[-1].subcommand == "query-object"
            and all(step.subcommand == "query-schema" for step in optional)
            and self.turn_prefix_counts == (maximum,)
            and self.allowed_turn_prefix_counts == (allowed,)
            and self.terminal_prefix_counts == allowed
            else ()
        )

    @property
    def optional_initial_query_schema(self) -> bool:
        """Whether this seal permits omitting one initial query-schema read."""

        maximum = len(self.steps)
        return bool(
            maximum >= 2
            and self.steps[0].subcommand == "query-schema"
            and not self.steps[0].arguments
            and self.steps[1].subcommand == "query-object"
            and self.turn_prefix_counts == (maximum,)
            and self.allowed_turn_prefix_counts == ((maximum - 1, maximum),)
            and self.terminal_prefix_counts == (maximum - 1, maximum)
        )

    @property
    def optional_initial_operations_discovery(self) -> bool:
        """Whether one leading operations catalog read may be omitted."""

        if (
            len(self.steps) < 2
            or self.steps[0].subcommand != "operations"
            or self.steps[0].arguments
            or self.steps[1].subcommand not in {
                "operation-schema",
                "request-schema",
            }
            or len(self.steps[1].arguments) != 1
            or not self.allowed_turn_prefix_counts
        ):
            return False
        return all(
            maximum - 1 in allowed and maximum in allowed
            for maximum, allowed in zip(
                self.turn_prefix_counts,
                self.allowed_turn_prefix_counts,
                strict=True,
            )
        ) and {
            len(self.steps) - 1,
            len(self.steps),
        }.issubset(self.terminal_prefix_counts)


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
    object_metadata_field_meanings: Sequence[str | None] | None = None,
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
    if object_metadata_field_meanings is None:
        metadata_meanings: tuple[str | None, ...] = (None,) * len(normalized)
    else:
        metadata_meanings = tuple(object_metadata_field_meanings)
        if len(metadata_meanings) != len(normalized) or any(
            value is not None
            and (not isinstance(value, str) or not value.strip())
            for value in metadata_meanings
        ):
            raise V3ProtocolError(
                "object metadata meanings must match the transaction request count"
            )

    steps: list[ExpectedGatewayStep] = []
    prefixes: list[int] = []
    for index, (request, request_equivalence, metadata_meaning) in enumerate(
        zip(normalized, equivalences, metadata_meanings, strict=True),
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
            if api == "ak.wwise.core.audio.convert":
                if refusal is not None:
                    raise V3ProtocolError(
                        "audio.convert Core business Draft has no reviewed refusal lane"
                    )
                operation_steps = build_audio_convert_business_transaction_steps(
                    request,
                    label=label,
                )
                steps.extend(operation_steps)
                preview_name = f"{label}.preview"
                prefixes.append(len(steps))
                show_name = f"{label}.transaction-show"
                confirm_name = f"{label}.confirm"
                execute_name = f"{label}.execute"
                steps.extend(
                    (
                        ExpectedGatewayStep(
                            name=show_name,
                            subcommand="transaction-show",
                            arguments=(
                                ResponseBinding(preview_name, "/transaction_id"),
                                "--summary-only",
                            ),
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
                            arguments=(
                                ResponseBinding(confirm_name, "/transaction_id"),
                            ),
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
                            arguments=(
                                ResponseBinding(execute_name, "/transaction_id"),
                            ),
                        )
                    )
                if index == len(normalized):
                    prefixes.append(len(steps))
                continue
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
            if (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation in OBJECT_GRAPH_BUSINESS_OPERATIONS
            ):
                operation_steps = build_object_graph_business_transaction_steps(
                    request,
                    label=label,
                )
            elif operation == "object.set":
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
            elif (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation in OBJECT_LIFECYCLE_BUSINESS_OPERATIONS
            ):
                operation_steps = build_object_lifecycle_business_transaction_steps(
                    request,
                    label=label,
                )
            elif (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation in OBJECT_METADATA_BUSINESS_OPERATIONS
            ):
                operation_steps = build_object_metadata_business_transaction_steps(
                    request,
                    label=label,
                    field_meaning=metadata_meaning,
                )
            elif (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation in SWITCH_ASSIGNMENT_BUSINESS_OPERATIONS
            ):
                operation_steps = build_switch_assignment_business_transaction_steps(
                    request,
                    label=label,
                )
            elif (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation in SOUNDBANK_BUSINESS_OPERATIONS
            ):
                operation_steps = build_soundbank_business_transaction_steps(
                    request,
                    label=label,
                )
            elif (
                input_mode == BUSINESS_DECLARATION_INPUT_MODE
                and operation in EXACT_ARTIFACT_BUSINESS_OPERATIONS
            ):
                operation_steps = build_exact_artifact_business_transaction_steps(
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
    object_set_requests = all(
        request.get("operation") == "object.set" for request in requests
    )
    if object_set_requests:
        if equivalence == "object_set_v1":
            return build_transaction_protocol(requests)
        raise V3ProtocolError(
            "object.set Business Draft owns live field discovery"
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
    metadata_business = all(
        request.get("operation") in OBJECT_METADATA_BUSINESS_OPERATIONS
        for request in requests
    )
    if metadata_business:
        if len(requests) != 1 or len(queries) != 1 or len(tokens) != 1:
            raise V3ProtocolError(
                "object metadata business discovery requires one request and meaning"
            )
        return build_transaction_protocol(
            requests,
            object_metadata_field_meanings=(str(queries[0]),),
        )
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


def build_operations_discovery_protocol(
    base: V3GatewayProtocol,
) -> V3GatewayProtocol:
    """Permit one compact named-operation inventory before a business schema.

    Natural-language mutation intent does not itself disclose an exact named
    operation.  This wrapper seals the public discovery step that makes that
    identifier visible, then preserves the independently built transaction
    protocol byte-for-byte after it.
    """

    if not isinstance(base, V3GatewayProtocol) or not base.steps:
        raise V3ProtocolError("operations discovery requires one protocol")
    first = base.steps[0]
    if (
        first.subcommand not in {"operation-schema", "request-schema"}
        or len(first.arguments) != 1
        or not isinstance(first.arguments[0], str)
        or not first.arguments[0]
    ):
        raise V3ProtocolError(
            "operations discovery must precede one exact operation or request schema"
        )
    label = first.name.rsplit(".", 1)[0]
    discovery = ExpectedGatewayStep(
        name=f"{label}.operations",
        subcommand="operations",
    )
    if any(step.name == discovery.name for step in base.steps):
        raise V3ProtocolError("operations discovery step name collides")

    base_allowed = (
        base.allowed_turn_prefix_counts
        or tuple((value,) for value in base.turn_prefix_counts)
    )
    allowed = tuple(
        tuple(sorted({item for value in values for item in (value, value + 1)}))
        for values in base_allowed
    )
    base_terminal = base.terminal_prefix_counts or (len(base.steps),)
    terminal = tuple(
        sorted({item for value in base_terminal for item in (value, value + 1)})
    )
    return V3GatewayProtocol(
        steps=(discovery, *base.steps),
        turn_prefix_counts=tuple(value + 1 for value in base.turn_prefix_counts),
        allowed_turn_prefix_counts=allowed,
        terminal_prefix_counts=terminal,
        commutative_read_only_step_groups=base.commutative_read_only_step_groups,
        commutative_composer_setup_step_groups=(
            base.commutative_composer_setup_step_groups
        ),
        optional_topic_schema_step_groups=base.optional_topic_schema_step_groups,
    )


def build_optional_topic_schema_protocol(
    steps: Sequence[ExpectedGatewayStep],
) -> V3GatewayProtocol:
    """Allow only sealed, bounded Topic disclosures before one lifecycle call."""

    values = tuple(steps)
    if len(values) < 2:
        raise V3ProtocolError(
            "Topic schema protocol requires base schema and lifecycle"
        )
    if len(values) == 2:
        return build_direct_protocol(values)
    optional_names = tuple(step.name for step in values[1:-1])
    minimum = 2
    maximum = len(values)
    allowed = tuple(range(minimum, maximum + 1))
    return V3GatewayProtocol(
        steps=values,
        turn_prefix_counts=(maximum,),
        allowed_turn_prefix_counts=(allowed,),
        terminal_prefix_counts=allowed,
        optional_topic_schema_step_groups=(optional_names,),
    )


def build_optional_query_schema_protocol(
    query_step: ExpectedGatewayStep,
    *,
    allow_advanced: bool = False,
) -> V3GatewayProtocol:
    """Allow a direct closed query after zero or more exact schema reads."""

    if query_step.subcommand != "query-object":
        raise V3ProtocolError("optional query schema must precede query-object")
    if type(allow_advanced) is not bool:
        raise V3ProtocolError("allow_advanced must be a boolean")
    schema_steps = (query_schema_step(),)
    if allow_advanced:
        schema_steps += (
            ExpectedGatewayStep(
                name="query-schema.advanced",
                subcommand="query-schema",
                arguments=("--advanced",),
            ),
        )
    steps = (*schema_steps, query_step)
    allowed = tuple(range(1, len(steps) + 1))
    return V3GatewayProtocol(
        steps=steps,
        turn_prefix_counts=(len(steps),),
        allowed_turn_prefix_counts=(allowed,),
        terminal_prefix_counts=allowed,
    )


def build_optional_query_repair_protocol(
    query_step: ExpectedGatewayStep,
) -> V3GatewayProtocol:
    """Seal one live kind-clarification repair before the reviewed query."""

    if query_step.subcommand != "query-object":
        raise V3ProtocolError("query repair must finish with query-object")
    ambiguous = query_object_step(
        "query-repair.ambiguous-kind",
        ("query-object", "--custom-kind", "Music", "--max-results", "1"),
    )
    refined = ExpectedGatewayStep(
        name="query-repair.refined-kind",
        subcommand="query-object",
        arguments=(
            "--custom-kind",
            ResponseBinding(
                ambiguous.name,
                "/agent_result/candidates/0/name",
            ),
            "--max-results",
            "1",
        ),
    )
    steps = (query_schema_step(), ambiguous, refined, query_step)
    maximum = len(steps)
    return V3GatewayProtocol(
        steps=steps,
        turn_prefix_counts=(maximum,),
        allowed_turn_prefix_counts=((maximum - 1, maximum),),
        terminal_prefix_counts=(maximum - 1, maximum),
    )


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
    schema = base.steps[0]
    transaction_show, confirm, execute, verify = base.steps[-4:]
    construction = base.steps[:-4]
    preview = construction[-1]
    if (
        schema.subcommand not in {"operation-schema", "request-schema"}
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
            steps=(schema,),
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


def media_pool_business_call_step(
    name: str,
    *,
    scenario_id: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
    post_filter: Mapping[str, Any] | None,
) -> ExpectedGatewayStep:
    """Compile one reviewed Media Pool request to the public business CLI."""

    def alternatives(values: tuple[str, ...]) -> Any:
        return values[0] if len(values) == 1 else ExactArgumentAlternatives(values)

    if set(args) - {"databases", "filters", "maxResults", "searchText"}:
        raise V3ProtocolError("Media Pool business args contain an unreviewed field")
    if set(options) != {"return"}:
        raise V3ProtocolError("Media Pool business options must contain only return")
    databases = args.get("databases")
    filters = args.get("filters")
    max_results = args.get("maxResults")
    return_fields = options.get("return")
    if (
        not isinstance(databases, (list, tuple))
        or not databases
        or not all(isinstance(value, str) and value for value in databases)
        or not isinstance(filters, (list, tuple))
        or not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or not isinstance(return_fields, (list, tuple))
        or not all(isinstance(value, str) and value for value in return_fields)
    ):
        raise V3ProtocolError("Media Pool business request shape is invalid")

    arguments: list[Any] = [
        "ak.wwise.core.mediaPool.get",
        "--max-results",
        str(max_results),
    ]
    for database in databases:
        if database.casefold() == r"\databases\project originals".casefold():
            database_value: Any = ExactArgumentAlternatives(
                (
                    "project-originals",
                    "Project Originals",
                    r"\Databases\Project Originals",
                )
            )
        else:
            database_value = database
        arguments.extend(("--database-scope", database_value))
    search_text = args.get("searchText")
    if search_text is not None:
        if not isinstance(search_text, str) or not search_text:
            raise V3ProtocolError("Media Pool searchText must be non-empty text")
        arguments.extend(("--search-text", search_text))
    for index, row in enumerate(filters):
        if (
            not isinstance(row, Mapping)
            or set(row) != {"type", "field", "operator", "value"}
            or row.get("type") != "field"
            or not isinstance(row.get("field"), str)
            or not isinstance(row.get("operator"), str)
        ):
            raise V3ProtocolError(
                f"Media Pool filter {index} is outside the closed field shape"
            )
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise V3ProtocolError(
                f"Media Pool filter {index} has an unsupported business value"
            )
        flag = "--text-filter" if isinstance(value, str) else "--number-filter"
        encoded = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        field_aliases = {
            "Filename": ("Filename", "filename", "name", "name/file"),
            "Path": ("Path", "path"),
            "FileId": ("FileId", "fileid", "file-id"),
            "Db": ("Db", "database", "database-id"),
            "WAV/Duration": ("WAV/Duration", "duration", "duration-seconds"),
            "WAV/Sample Rate": (
                "WAV/Sample Rate",
                "sample-rate",
                "sample-rate-hz",
            ),
            "WAV/Bit Depth": ("WAV/Bit Depth", "bit-depth"),
            "WAV/Channels": ("WAV/Channels", "channels", "channel-count"),
            "IXML/Scene": ("IXML/Scene", "ixml-scene", "scene"),
            "IXML/Take": ("IXML/Take", "ixml-take", "take"),
        }
        field_name = str(row["field"])
        field_value = alternatives(field_aliases.get(field_name, (field_name,)))
        arguments.extend((flag, field_value, str(row["operator"]), encoded))

    canonical_fields = {
        "Path",
        "FileId",
        "Db",
        "Filename",
        "WAV/Duration",
        "WAV/Sample Rate",
        "WAV/Bit Depth",
        "WAV/Channels",
    }
    for field_name in return_fields:
        if field_name not in canonical_fields:
            include_aliases = {
                "IXML/Scene": ("IXML/Scene", "ixml-scene", "scene"),
                "IXML/Take": ("IXML/Take", "ixml-take", "take"),
            }
            arguments.extend(
                (
                    "--include-field",
                    alternatives(include_aliases.get(field_name, (field_name,))),
                )
            )

    if post_filter is not None:
        if (
            set(post_filter) != {"field", "operator", "value", "limit"}
            or post_filter.get("field") != "Filename"
            or post_filter.get("operator") != "containsCaseSensitive"
            or not isinstance(post_filter.get("value"), str)
            or not isinstance(post_filter.get("limit"), int)
            or isinstance(post_filter.get("limit"), bool)
        ):
            raise V3ProtocolError("Media Pool post-filter is outside its business CLI")
        arguments.extend(("--exact-name-contains", str(post_filter["value"])))
        arguments.extend(("--final-limit", str(post_filter["limit"])))

    sort_rules = {
        "VS25-F-MEDIAPOOL-GET-01": (
            ("WAV/Duration", "ascending"),
            ("Path", "ascending"),
        ),
        "VS25-F-MEDIAPOOL-GET-02": (("Path", "ascending"),),
        "VS25-F-MEDIAPOOL-GET-03": (),
        "VS25-F-MEDIAPOOL-GET-04": (),
        "VS25-F-MEDIAPOOL-GET-05": (
            ("WAV/Duration", "descending"),
            ("Path", "ascending"),
        ),
    }
    try:
        selected_sort_rules = sort_rules[scenario_id]
    except KeyError as exc:
        raise V3ProtocolError("Media Pool scenario has no reviewed business order") from exc
    for field_name, direction in selected_sort_rules:
        sort_aliases = {
            "WAV/Duration": ("WAV/Duration", "duration", "duration-seconds"),
            "Path": ("Path", "path"),
        }
        arguments.extend(
            (
                "--sort-by",
                ExactArgumentAlternatives(sort_aliases[field_name]),
                direction,
            )
        )
    return ExpectedGatewayStep(
        name=name,
        subcommand="core-call",
        arguments=tuple(arguments),
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


def topic_schema_step(
    name: str,
    topic: str,
    *,
    entry: str | None = None,
) -> ExpectedGatewayStep:
    if not isinstance(topic, str) or not topic.startswith("ak.wwise."):
        raise V3ProtocolError("topic-schema requires one exact WAAPI topic")
    if entry is not None and (
        not isinstance(entry, str)
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,127}", entry)
    ):
        raise V3ProtocolError("topic-schema entry must be one stable scope token")
    return ExpectedGatewayStep(
        name=name,
        subcommand="topic-schema",
        arguments=(topic, *(("--entry", entry) if entry is not None else ())),
    )


def topic_schema_entry_or_match_group_step(
    name: str,
    topic: str,
    *,
    scope: str,
) -> ExpectedGatewayStep:
    """Accept either bounded disclosure that closes one nested match scope."""

    if not isinstance(topic, str) or not topic.startswith("ak.wwise."):
        raise V3ProtocolError("topic-schema requires one exact WAAPI topic")
    if not isinstance(scope, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,127}", scope
    ):
        raise V3ProtocolError("topic-schema scope must be one stable token")
    return ExpectedGatewayStep(
        name=name,
        subcommand="topic-schema",
        arguments=(
            topic,
            ExactArgumentAlternatives(("--entry", "--match-group")),
            scope,
        ),
    )


def topic_schema_match_group_step(
    name: str,
    topic: str,
    *,
    group: str,
) -> ExpectedGatewayStep:
    if not isinstance(topic, str) or not topic.startswith("ak.wwise."):
        raise V3ProtocolError("topic-schema requires one exact WAAPI topic")
    if not isinstance(group, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,127}", group
    ):
        raise V3ProtocolError("topic-schema group must be one stable token")
    return ExpectedGatewayStep(
        name=name,
        subcommand="topic-schema",
        arguments=(topic, "--match-group", group),
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
    arguments: list[Any] = [
        topic,
        "--event-count",
        str(event_count),
        "--topic-contract-digest",
        topic_business_contract(version, topic).contract_digest,
        *(_business_topic_arguments(
            topic,
            version=version,
            options=option_values,
            match=match_values,
        )),
    ]
    return ExpectedGatewayStep(
        name=name,
        subcommand="wait-topic",
        gateway_global_arguments=("--timeout", _format_timeout(timeout_seconds)),
        arguments=tuple(arguments),
        allow_omitted_default_event_count_one=event_count == 1,
    )


def stream_topic_step(
    name: str,
    topic: str,
    *,
    version: str,
    event_count: int,
    match: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    timeout_seconds: float,
) -> ExpectedGatewayStep:
    """Build one finite persistent Topic stream from closed business facts."""

    if timeout_seconds <= 0:
        raise V3ProtocolError("stream-topic timeout must be positive")
    if (
        not isinstance(event_count, int)
        or isinstance(event_count, bool)
        or not 1 <= event_count <= 64
    ):
        raise V3ProtocolError(
            "stream-topic expected event count must be an integer from 1 through 64"
        )
    option_values = _normalize_json_object(
        {} if options is None else options,
        field="stream-topic options",
    )
    match_values = _normalize_json_object(
        {} if match is None else match,
        field="stream-topic match",
    )
    return ExpectedGatewayStep(
        name=name,
        subcommand="stream-topic",
        gateway_global_arguments=("--timeout", _format_timeout(timeout_seconds)),
        arguments=(
            topic,
            "--event-count",
            BoundedIntegerArgument(min(event_count + 1, 64), 64),
            "--topic-contract-digest",
            topic_business_contract(version, topic).contract_digest,
            *_business_topic_arguments(
                topic,
                version=version,
                options=option_values,
                match=match_values,
            ),
        ),
    )


def _business_topic_arguments(
    topic: str,
    *,
    version: str,
    options: Mapping[str, Any],
    match: Mapping[str, Any],
) -> tuple[str, ...]:
    contract = topic_business_contract(version, topic)
    arguments: list[str] = []
    for values, fields, flag in (
        (options, contract.option_fields, "--topic-option-as"),
        (match, contract.match_fields, "--event-match-as"),
    ):
        for path, value in _topic_scalar_leaves(values):
            field = next(
                (
                    item
                    for item in fields
                    if any(candidate.path == path for candidate in item._candidates)
                ),
                None,
            )
            if field is None:
                entry = next(
                    (
                        item
                        for item in contract.entry_fields
                        if None not in item._path
                        and tuple(item._path) == path[:-1]
                    ),
                    None,
                )
                if entry is None or flag != "--event-match-as":
                    raise V3ProtocolError(
                        f"Topic {topic!r} business protocol requires a complex "
                        f"fixture compiler for {'.'.join(path)!r}"
                    )
                kind, encoded = _topic_business_value(value)
                choice = _topic_value_choice_handle(
                    contract,
                    channel="event-entry",
                    owner=(entry.token,),
                    kind=kind,
                )
                arguments.extend(
                    (
                        "--event-entry-as",
                        entry.token,
                        "-",
                        path[-1],
                        choice,
                        encoded,
                    )
                )
                continue
            items = value if isinstance(value, list) else [value]
            for item in items:
                kind, encoded = _topic_business_value(item)
                if len(field.accepted_value_kinds) == 1:
                    arguments.extend((flag.removesuffix("-as"), field.token, encoded))
                else:
                    choice = _topic_value_choice_handle(
                        contract,
                        channel=(
                            "topic-option"
                            if flag == "--topic-option-as"
                            else "event-match"
                        ),
                        owner=(field.token,),
                        kind=kind,
                    )
                    arguments.extend((flag, field.token, choice, encoded))
    return tuple(arguments)


def _topic_value_choice_handle(
    contract: Any,
    *,
    channel: str,
    owner: tuple[str, ...],
    kind: str,
) -> str:
    meaning = {
        "text": "literal_text",
        "integer": "whole_number",
        "number": "decimal_number",
        "toggle": "on_or_off",
        "null": "explicit_empty",
    }[kind]
    for choice in topic_business_value_choices(
        contract,
        channel=channel,
        owner=owner,
    ):
        if choice.meaning == meaning:
            return choice.handle
    raise V3ProtocolError(
        f"Topic business value {channel} {'/'.join(owner)!r} does not accept {meaning}"
    )


def _topic_scalar_leaves(
    value: Mapping[str, Any],
    path: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, ...], Any], ...]:
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key, item in value.items():
        item_path = (*path, key)
        if isinstance(item, Mapping):
            leaves.extend(_topic_scalar_leaves(item, item_path))
        elif isinstance(item, list) and any(
            isinstance(child, (Mapping, list)) for child in item
        ):
            raise V3ProtocolError(
                "Complex Topic fixtures must use the business row compiler"
            )
        else:
            leaves.append((item_path, item))
    return tuple(leaves)


def _topic_business_value(value: Any) -> tuple[str, str]:
    if value is None:
        return "null", "null"
    if isinstance(value, bool):
        return "toggle", "true" if value else "false"
    if isinstance(value, int):
        return "integer", str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise V3ProtocolError("Topic business number must be finite")
        return "number", str(value)
    if isinstance(value, str):
        return "text", value
    raise V3ProtocolError("Topic business scalar has an unsupported value")


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
    "CompoundUndoChildExpectation",
    "StructuredRefusal",
    "V3GatewayProtocol",
    "V3ProtocolError",
    "build_direct_protocol",
    "build_optional_query_repair_protocol",
    "build_optional_query_schema_protocol",
    "build_optional_topic_schema_protocol",
    "build_audio_import_composer_protocol",
    "build_audio_import_composer_transaction_steps",
    "build_authoring_ui_business_transaction_steps",
    "build_cli_console_business_transaction_steps",
    "build_debug_control_business_transaction_steps",
    "build_host_ui_debug_business_transaction_steps",
    "build_core_business_transaction_steps",
    "build_project_setting_business_transaction_steps",
    "build_soundengine_business_transaction_steps",
    "build_compound_undo_business_transaction_steps",
    "OBJECT_LIFECYCLE_BUSINESS_OPERATIONS",
    "build_object_lifecycle_business_transaction_steps",
    "build_object_metadata_business_transaction_steps",
    "build_soundbank_business_transaction_steps",
    "build_switch_assignment_business_transaction_steps",
    "build_object_graph_business_transaction_steps",
    "build_object_set_composer_transaction_steps",
    "build_modification_policy_protocol",
    "build_metadata_transaction_protocol",
    "build_schema_query_transaction_protocol",
    "build_transaction_protocol",
    "call_step",
    "metadata_candidate_limit",
    "materialize_audio_import_composer_protocol_request",
    "materialize_typed_transaction_protocol_requests",
    "media_pool_business_call_step",
    "operation_request_equivalence",
    "query_object_step",
    "query_schema_step",
    "request_schema_step",
    "topic_schema_step",
    "topic_schema_match_group_step",
    "stream_topic_step",
    "wait_topic_step",
]

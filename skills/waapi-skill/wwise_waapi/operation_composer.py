"""Closed, typed composition for narrowly reviewed operation fragments.

The Composer never accepts a native WAAPI payload or a complete operation
request.  It owns a small fact model and materializes one canonical request
from Registry-projected fragments.  Live resolution and mutation execution
remain downstream responsibilities of the normal transaction ingress.
"""

from __future__ import annotations

import json
import math
import re
import secrets
from typing import Any, Callable, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256
from .operation_registry import (
    COMPOSER_INPUT_MODE,
    OperationContractError,
    audio_import_composer_fragment_contract,
    object_set_composer_fragment_contract,
    operation_input_mode,
    parse_operation_request,
    validate_audio_import_composer_fragment,
    validate_object_set_composer_fragment,
)


OPERATION_DRAFT_ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
OPERATION_COMPOSITION_CONTRACT = "waapi-skill.operation-composition/v1"
OPERATION_COMPOSER_CONTRACT = "waapi-skill.operation-composer/v1"
OBJECT_SET_COMPOSER_OPERATION = "object.set"
AUDIO_IMPORT_COMPOSER_OPERATION = "audio.import"
MAX_COMPOSER_ACTION_BYTES = 32 * 1024
MAX_AUDIO_IMPORT_COMPOSER_ACTION_BYTES = 384 * 1024
_TARGET_HANDLE_PATTERN = re.compile(r"^odh1-[0-9a-f]{24}$")
_BASE_ACTION_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "set_request_option": (("name", "value"), ()),
    "clear_request_option": (("name",), ()),
    "add_target": (
        ("selector",),
        (
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
        ),
    ),
    "set_target_field": (("target_handle", "name", "value"), ()),
    "clear_target_field": (("target_handle", "name"), ()),
    "set_property": (("target_handle", "name", "value"), ()),
    "remove_property": (("target_handle", "name"), ()),
    "set_reference": (("owner_handle", "name", "target"), ()),
    "remove_reference": (("owner_handle", "name"), ()),
    "add_child": (("parent_handle", "type", "name"), ()),
    "set_node_field": (("node_handle", "name", "value"), ()),
    "clear_node_field": (("node_handle", "name"), ()),
    "set_node_property": (("node_handle", "name", "value"), ()),
    "remove_node_property": (("node_handle", "name"), ()),
    "remove_node": (("node_handle",), ()),
    "add_list": (("target_handle", "name"), ()),
    "remove_list": (("list_handle",), ()),
    "add_list_member": (("list_handle", "type", "name"), ()),
    "remove_target": (("target_handle",), ()),
}
_IMPORT_ACTION_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "add_import_file": (
        ("owner_handle",),
        (
            "audio_file",
            "audio_file_base64",
            "originals_subfolder",
            "language",
            "object_type",
        ),
    ),
    "set_import_file_field": (("file_handle", "name", "value"), ()),
    "clear_import_file_field": (("file_handle", "name"), ()),
    "remove_import_file": (("file_handle",), ()),
    "set_import_option": (("owner_handle", "name", "value"), ()),
    "clear_import_option": (("owner_handle", "name"), ()),
    "remove_import": (("owner_handle",), ()),
}
_AUDIO_IMPORT_ROW_OPTIONAL_FIELDS = (
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
)
_AUDIO_IMPORT_ACTION_FIELDS: dict[
    str, tuple[tuple[str, ...], tuple[str, ...]]
] = {
    "set_import_option": (("name", "value"), ()),
    "clear_import_option": (("name",), ()),
    "set_import_default": (("name", "value"), ()),
    "clear_import_default": (("name",), ()),
    "add_import_row": (
        ("object_path",),
        _AUDIO_IMPORT_ROW_OPTIONAL_FIELDS,
    ),
    "add_switch_assigned_import_row": (
        ("object_path", "assignment"),
        _AUDIO_IMPORT_ROW_OPTIONAL_FIELDS,
    ),
    "set_import_row_field": (("import_handle", "name", "value"), ()),
    "clear_import_row_field": (("import_handle", "name"), ()),
    "remove_import_row": (("import_handle",), ()),
}


class OperationComposerError(ValueError):
    """A typed action or materialized fact set is outside the closed Adapter."""

    error_code = "OPERATION_DRAFT_ACTION_INVALID"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})
        if error_code is not None:
            self.error_code = error_code

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


def build_typed_action_from_cli(
    action_name: str,
    *,
    values: Sequence[Sequence[str]] = (),
    nulls: Sequence[str] = (),
    selectors: Sequence[Sequence[str]] = (),
    properties: Sequence[Sequence[str]] = (),
    references: Sequence[Sequence[str]] = (),
    events: Sequence[Sequence[str]] = (),
    assignments: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    """Build one closed action from typed argv facts, never from JSON text."""

    if not isinstance(action_name, str) or not action_name:
        raise OperationComposerError("--action must name one typed action.")
    action: dict[str, Any] = {
        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
        "action": action_name,
    }

    def set_once(name: str, value: Any) -> None:
        if not isinstance(name, str) or not name:
            raise OperationComposerError("Typed action field names must be non-empty.")
        if name in {"contract", "action"} or name in action:
            raise OperationComposerError(
                "Typed action fields must be unique and cannot replace fixed fields.",
                details={"field": name},
            )
        action[name] = value

    for row in values:
        if len(row) != 3:
            raise OperationComposerError(
                "--value requires FIELD TYPE VALUE."
            )
        field, value_type, raw_value = row
        set_once(field, _parse_cli_scalar(value_type, raw_value))
    for field in nulls:
        set_once(field, None)
    for row in selectors:
        if len(row) < 3:
            raise OperationComposerError(
                "--selector requires FIELD KIND and the kind's typed values."
            )
        field, *tokens = row
        selector, consumed = _parse_cli_selector(tokens)
        if consumed != len(tokens):
            raise OperationComposerError("--selector contains extra values.")
        set_once(field, selector)
    for row in events:
        if len(row) != 3:
            raise OperationComposerError("--event requires FIELD ACTION PATH.")
        field, event_action, path = row
        set_once(field, {"action": event_action, "path": path})
    for row in assignments:
        if len(row) not in {1, 2}:
            raise OperationComposerError(
                "--assignment requires none or switch VALUE."
            )
        mode, *assignment_value = row
        if mode == "none" and not assignment_value:
            set_once("assignment", {"mode": "none"})
        elif mode == "switch" and len(assignment_value) == 1:
            set_once(
                "assignment",
                {"mode": "switch", "value": assignment_value[0]},
            )
        else:
            raise OperationComposerError(
                "--assignment accepts only none or switch with one value."
            )

    grouped_properties: dict[str, list[dict[str, Any]]] = {}
    for row in properties:
        if len(row) != 4:
            raise OperationComposerError(
                "--property requires FIELD NAME TYPE VALUE."
            )
        field, name, value_type, raw_value = row
        grouped_properties.setdefault(field, []).append(
            {"name": name, "value": _parse_cli_scalar(value_type, raw_value)}
        )
    for field, descriptors in grouped_properties.items():
        set_once(field, descriptors)

    grouped_references: dict[str, list[dict[str, Any]]] = {}
    for row in references:
        if len(row) < 4:
            raise OperationComposerError(
                "--reference requires FIELD NAME KIND and the kind's typed values."
            )
        field, name, *tokens = row
        target, consumed = _parse_cli_selector(tokens)
        if consumed != len(tokens):
            raise OperationComposerError("--reference contains extra values.")
        grouped_references.setdefault(field, []).append(
            {"name": name, "target": target}
        )
    for field, descriptors in grouped_references.items():
        set_once(field, descriptors)
    return action


def parse_typed_action_cli_arguments(arguments: Sequence[str]) -> dict[str, Any]:
    """Parse the closed variable-length ``draft-apply`` typed argv suffix."""

    values: list[tuple[str, ...]] = []
    nulls: list[str] = []
    selectors: list[tuple[str, ...]] = []
    properties: list[tuple[str, ...]] = []
    references: list[tuple[str, ...]] = []
    events: list[tuple[str, ...]] = []
    assignments: list[tuple[str, ...]] = []
    if len(arguments) < 2 or arguments[0] != "--action":
        raise OperationComposerError(
            "Typed action argv must start with --action ACTION."
        )
    action_name = arguments[1]
    index = 2
    while index < len(arguments):
        flag = arguments[index]
        if flag == "--value":
            row = _require_cli_argv_row(arguments, index, 4, flag)
            values.append(row[1:])
            index += 4
        elif flag == "--null":
            row = _require_cli_argv_row(arguments, index, 2, flag)
            nulls.append(row[1])
            index += 2
        elif flag == "--property":
            row = _require_cli_argv_row(arguments, index, 5, flag)
            properties.append(row[1:])
            index += 5
        elif flag == "--event":
            row = _require_cli_argv_row(arguments, index, 4, flag)
            events.append(row[1:])
            index += 4
        elif flag == "--selector":
            if index + 3 > len(arguments):
                raise OperationComposerError("--selector is incomplete.")
            field = arguments[index + 1]
            _selector, consumed = _parse_cli_selector(arguments[index + 2 :])
            end = index + 2 + consumed
            selectors.append((field, *arguments[index + 2 : end]))
            index = end
        elif flag == "--reference":
            if index + 4 > len(arguments):
                raise OperationComposerError("--reference is incomplete.")
            field = arguments[index + 1]
            name = arguments[index + 2]
            _selector, consumed = _parse_cli_selector(arguments[index + 3 :])
            end = index + 3 + consumed
            references.append((field, name, *arguments[index + 3 : end]))
            index = end
        elif flag == "--assignment":
            if index + 2 > len(arguments):
                raise OperationComposerError("--assignment is incomplete.")
            mode = arguments[index + 1]
            if mode == "none":
                assignments.append((mode,))
                index += 2
            elif mode == "switch" and index + 3 <= len(arguments):
                assignments.append((mode, arguments[index + 2]))
                index += 3
            else:
                raise OperationComposerError("--assignment is invalid.")
        else:
            raise OperationComposerError(
                "Typed action argv contains an unknown fact flag.",
                details={"flag": flag},
            )
    return build_typed_action_from_cli(
        action_name,
        values=values,
        nulls=nulls,
        selectors=selectors,
        properties=properties,
        references=references,
        events=events,
        assignments=assignments,
    )


def _require_cli_argv_row(
    arguments: Sequence[str],
    index: int,
    size: int,
    flag: str,
) -> tuple[str, ...]:
    end = index + size
    if end > len(arguments):
        raise OperationComposerError(f"{flag} is incomplete.")
    return tuple(arguments[index:end])


def typed_action_cli_arguments(action: Mapping[str, Any]) -> tuple[str, ...]:
    """Serialize one validated action as typed argv facts without JSON quoting."""

    _require_json_object(action, label="action")
    if action.get("contract") != OPERATION_DRAFT_ACTION_CONTRACT:
        raise OperationComposerError("Typed action has an invalid contract.")
    action_name = action.get("action")
    if not isinstance(action_name, str) or not action_name:
        raise OperationComposerError("Typed action has an invalid action name.")
    arguments: list[str] = ["--action", action_name]
    for field, value in action.items():
        if field in {"contract", "action"}:
            continue
        if value is None:
            arguments.extend(("--null", field))
        elif isinstance(value, Mapping) and "kind" in value:
            arguments.extend(("--selector", field, *_selector_cli_tokens(value)))
        elif (
            isinstance(value, Mapping)
            and set(value).issubset({"action", "path"})
            and set(value) == {"action", "path"}
        ):
            arguments.extend(
                ("--event", field, str(value["action"]), str(value["path"]))
            )
        elif isinstance(value, Mapping) and "mode" in value:
            mode = value.get("mode")
            if mode == "none" and set(value) == {"mode"}:
                arguments.extend(("--assignment", "none"))
            elif mode == "switch" and set(value) == {"mode", "value"}:
                arguments.extend(
                    ("--assignment", "switch", str(value["value"]))
                )
            else:
                raise OperationComposerError("Typed assignment is invalid.")
        elif isinstance(value, list):
            for descriptor in value:
                if not isinstance(descriptor, Mapping):
                    raise OperationComposerError("Typed descriptor list is invalid.")
                if set(descriptor) == {"name", "value"}:
                    value_type, raw_value = _scalar_cli_tokens(descriptor["value"])
                    arguments.extend(
                        (
                            "--property",
                            field,
                            str(descriptor["name"]),
                            value_type,
                            raw_value,
                        )
                    )
                elif set(descriptor) == {"name", "target"} and isinstance(
                    descriptor["target"], Mapping
                ):
                    arguments.extend(
                        (
                            "--reference",
                            field,
                            str(descriptor["name"]),
                            *_selector_cli_tokens(descriptor["target"]),
                        )
                    )
                else:
                    raise OperationComposerError("Typed descriptor is invalid.")
        else:
            value_type, raw_value = _scalar_cli_tokens(value)
            arguments.extend(("--value", field, value_type, raw_value))
    return tuple(arguments)


def _parse_cli_scalar(value_type: str, raw_value: str) -> Any:
    if value_type == "string":
        return raw_value
    if value_type == "boolean":
        if raw_value == "true":
            return True
        if raw_value == "false":
            return False
        raise OperationComposerError("boolean values must be true or false.")
    if value_type == "integer":
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw_value):
            raise OperationComposerError("integer values must use canonical decimal syntax.")
        return int(raw_value)
    if value_type == "number":
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise OperationComposerError("number values must use JSON number syntax.") from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise OperationComposerError("number values must use JSON number syntax.")
        if isinstance(value, float) and not math.isfinite(value):
            raise OperationComposerError("number values must be finite.")
        return value
    raise OperationComposerError(
        "Typed scalar type must be string, number, integer, or boolean.",
        details={"type": value_type},
    )


def _scalar_cli_tokens(value: Any) -> tuple[str, str]:
    if isinstance(value, str):
        return "string", value
    if isinstance(value, bool):
        return "boolean", "true" if value else "false"
    if isinstance(value, int):
        return "integer", str(value)
    if isinstance(value, float) and math.isfinite(value):
        return "number", json.dumps(value, ensure_ascii=False, allow_nan=False)
    raise OperationComposerError("Typed scalar value is unsupported.")


def _parse_cli_selector(
    tokens: Sequence[str],
    *,
    depth: int = 0,
) -> tuple[dict[str, Any], int]:
    if depth > 8 or not tokens:
        raise OperationComposerError("Typed selector is missing or too deeply nested.")
    kind = tokens[0]
    if kind in {"id", "path"}:
        if len(tokens) < 2:
            raise OperationComposerError(f"{kind} selector requires VALUE.")
        return {"kind": kind, "value": tokens[1]}, 2
    if kind == "exact-type-name":
        if len(tokens) < 3:
            raise OperationComposerError("exact-type-name requires TYPE NAME.")
        return {"kind": kind, "type": tokens[1], "name": tokens[2]}, 3
    if kind == "direct-child":
        if len(tokens) < 3:
            raise OperationComposerError(
                "direct-child requires TYPE and a parent selector."
            )
        parent, consumed = _parse_cli_selector(tokens[2:], depth=depth + 1)
        return {"kind": kind, "type": tokens[1], "parent": parent}, 2 + consumed
    if kind == "scoped-name":
        if len(tokens) < 4:
            raise OperationComposerError(
                "scoped-name requires TYPE NAME and a parent selector."
            )
        parent, consumed = _parse_cli_selector(tokens[3:], depth=depth + 1)
        return {
            "kind": kind,
            "type": tokens[1],
            "name": tokens[2],
            "parent": parent,
        }, 3 + consumed
    raise OperationComposerError(
        "Typed selector kind is not supported.", details={"kind": kind}
    )


def _selector_cli_tokens(selector: Mapping[str, Any], *, depth: int = 0) -> tuple[str, ...]:
    if depth > 8:
        raise OperationComposerError("Typed selector is too deeply nested.")
    kind = selector.get("kind")
    if kind in {"id", "path"} and set(selector) == {"kind", "value"}:
        return str(kind), str(selector["value"])
    if kind == "exact-type-name" and set(selector) == {"kind", "type", "name"}:
        return kind, str(selector["type"]), str(selector["name"])
    if kind == "direct-child" and set(selector) == {"kind", "type", "parent"}:
        parent = selector["parent"]
        if not isinstance(parent, Mapping):
            raise OperationComposerError("Typed selector parent is invalid.")
        return kind, str(selector["type"]), *_selector_cli_tokens(parent, depth=depth + 1)
    if kind == "scoped-name" and set(selector) == {
        "kind",
        "type",
        "name",
        "parent",
    }:
        parent = selector["parent"]
        if not isinstance(parent, Mapping):
            raise OperationComposerError("Typed selector parent is invalid.")
        return (
            kind,
            str(selector["type"]),
            str(selector["name"]),
            *_selector_cli_tokens(parent, depth=depth + 1),
        )
    raise OperationComposerError("Typed selector is invalid.")


def operation_composer_contract(operation: str, version: str) -> dict[str, Any]:
    """Return one reviewed Adapter contract, derived from the Registry."""

    try:
        input_mode = operation_input_mode(operation, version)
    except OperationContractError as exc:
        raise OperationComposerError(
            f"No Operation Composer Adapter is available for {operation!r}.",
            error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
            details={"operation": operation, "version": version},
        ) from exc
    if input_mode != COMPOSER_INPUT_MODE:
        raise OperationComposerError(
            f"No Operation Composer Adapter is available for {operation!r}.",
            error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
            details={"operation": operation, "version": version},
        )

    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        fragments = audio_import_composer_fragment_contract(version)
        import_operation_contract = fragments["request_options"][
            "import_operation"
        ]
        gateway_default = import_operation_contract.get("default")
        import_operation_values = import_operation_contract.get("enum")
        if (
            gateway_default != "createNew"
            or not isinstance(import_operation_values, list)
            or import_operation_values
            != ["createNew", "useExisting", "replaceExisting"]
        ):
            raise RuntimeError(
                "Registry returned an invalid audio.import operation default"
            )
        flat_import_row_discipline = {
            "initial_row_action_by_intent": {
                "without_switch_assignment": "add_import_row",
                "with_requested_switch_assignment": (
                    "add_switch_assigned_import_row"
                ),
            },
            "one_initial_action_per_row": True,
            "assignment_intent_is_explicit_in_action_name": True,
            "never_guess_assignment_intent": True,
            "include_every_known_field": True,
            "split_initial_row_across_follow_up_actions": False,
            "follow_up_row_actions": "corrections_only",
            "metadata_dependency_activation": "gateway_owned_do_not_submit",
        }
        import_row_user_fact_checklist = {
            "copy_every_explicit_fact_for_this_row": True,
            "copy_only_explicit_user_facts": True,
            "unrequested_dependency_candidates_are_not_action_fields": True,
            "batch_facts_apply_to_each_affected_row": True,
            "mixed_structure_and_media_defaults_are_not_safe": True,
            "media_row_examples": [
                "import_language",
                "object_type",
                "event",
                "properties",
                "references",
                "switch_assignment",
            ],
            "distinct_metadata_tokens_are_independent_facts": True,
            "requested_switch_assignment_is_not_a_later_action": True,
        }
        planning_discipline = {
            "dynamic_metadata": {
                "fields": ["properties", "references"],
                "query_granularity": (
                    "one_successful_command_per_object_type"
                ),
                "all_required_tokens_share_that_result": True,
                "split_required_tokens_across_queries": False,
                "action_fields_source": "explicit_user_request_only",
                "unrequested_dependency_candidates": (
                    "validation_only_do_not_copy_into_action"
                ),
                "complete_before": (
                    "first-draft-apply-using-properties-or-references"
                ),
                "schema_and_metadata_may_swap": True,
                "draft_start_may_precede": True,
                "successful_result_survives_metadata_independent_actions": True,
                "repeat_successful_query": False,
            },
            "import_operation": {
                "source": (
                    "registry_fragments.request_options.import_operation"
                ),
                "action": "set_import_option",
                "gateway_default": gateway_default,
                "default_is_materialized_at": "draft-start",
                "action_required_only_for": [
                    value
                    for value in import_operation_values
                    if value != gateway_default
                ],
                "do_not_submit_redundant_default": True,
            },
        }
        action_shapes = {
            action_name: {
                "fixed_fields": {
                    "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                    "action": action_name,
                },
                "required_fields": list(required_fields),
                "optional_fields": list(optional_fields),
                **(
                    {
                        "construction_discipline": dict(
                            flat_import_row_discipline
                        )
                    }
                    if action_name in {
                        "add_import_row",
                        "add_switch_assigned_import_row",
                    }
                    else {}
                ),
                **(
                    {
                        "user_fact_checklist": dict(
                            import_row_user_fact_checklist
                        )
                    }
                    if action_name in {
                        "add_import_row",
                        "add_switch_assigned_import_row",
                    }
                    else {}
                ),
                **(
                    {
                        "conditional_required_fields": [
                            {
                                "when": "every_row",
                                "require_effective": ["object_type"],
                                "effective_sources": [
                                    "row",
                                    "explicit_defaults",
                                ],
                                "reason": (
                                    "every row requires an explicit object type"
                                ),
                            },
                            {
                                "when_any_present": [
                                    "audio_file",
                                    "audio_file_base64",
                                ],
                                "require_effective": ["import_language"],
                                "effective_sources": [
                                    "row",
                                    "explicit_defaults",
                                ],
                                "reason": (
                                    "media rows require an explicit import language"
                                ),
                            }
                        ]
                    }
                    if action_name in {
                        "add_import_row",
                        "add_switch_assigned_import_row",
                    }
                    else {}
                ),
                **(
                    {
                        "assignment_contract": {
                            "required": True,
                            "normal_form": {
                                "mode": "switch",
                                "required_fields": ["mode", "value"],
                                "additional_fields": False,
                            },
                            "requested_switch_assignment_must_use_mode": "switch",
                            "switch_assignment_is_not_a_later_action": True,
                        }
                    }
                    if action_name == "add_switch_assigned_import_row"
                    else {}
                ),
            }
            for action_name, (required_fields, optional_fields) in (
                _AUDIO_IMPORT_ACTION_FIELDS.items()
            )
        }
        return {
            "contract": OPERATION_COMPOSER_CONTRACT,
            "operation": operation,
            "version": version,
            "action_contract": OPERATION_DRAFT_ACTION_CONTRACT,
            "action_construction": {
                "fixed_fields_are_required": True,
                "include_every_required_field": True,
                "include_only_selected_optional_fields": True,
                "additional_fields": False,
            },
            "planning_discipline": planning_discipline,
            "start_preconditions": {
                "dynamic_metadata": dict(
                    planning_discipline["dynamic_metadata"]
                ),
                "draft_start_may_precede": True,
                "metadata_independent_actions_may_precede": True,
                "successful_metadata_survives_metadata_independent_actions": True,
                "repeat_successful_metadata": False,
                "actions_using_properties_or_references_wait_for": [
                    "dynamic_metadata"
                ],
                "failure_policy": (
                    "do_not_apply_dynamic_fields_then_backfill_metadata"
                ),
            },
            "flat_import_row_discipline": flat_import_row_discipline,
            "action_shapes": action_shapes,
            "composition_contract": OPERATION_COMPOSITION_CONTRACT,
            "actions": list(_AUDIO_IMPORT_ACTION_FIELDS),
            "limits": {
                "imports": fragments["limits"]["imports"],
                "action_bytes": MAX_AUDIO_IMPORT_COMPOSER_ACTION_BYTES,
            },
            "registry_fragments": fragments,
            "complete_request_is_never_an_action": True,
            "completion_discipline": {
                "successful_action_response_is_complete": True,
                "compact_projection_is_not_truncation": True,
                "schema_required_fields_status_scope": (
                    "structural_preview_readiness_only"
                ),
                "user_intent_coverage": (
                    "compare_planned_actions_before_draft-check"
                ),
                "draft_inspect_required_before_next_planned_action": False,
            },
        }
    if operation != OBJECT_SET_COMPOSER_OPERATION:  # registry invariant
        raise RuntimeError(
            f"Composer lane {operation!r} lacks a local Adapter implementation"
        )
    fragments = object_set_composer_fragment_contract(version)
    action_fields = dict(_BASE_ACTION_FIELDS)
    if fragments["import_supported"]:
        action_fields.update(_IMPORT_ACTION_FIELDS)
    actions = list(action_fields)
    return {
        "contract": OPERATION_COMPOSER_CONTRACT,
        "operation": operation,
        "version": version,
        "action_contract": OPERATION_DRAFT_ACTION_CONTRACT,
        "action_construction": {
            "fixed_fields_are_required": True,
            "include_every_required_field": True,
            "include_only_selected_optional_fields": True,
            "additional_fields": False,
        },
        "flat_target_row_discipline": {
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
        },
        "action_shapes": {
            action_name: {
                "fixed_fields": {
                    "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                    "action": action_name,
                },
                "required_fields": list(required_fields),
                "optional_fields": list(optional_fields),
            }
            for action_name, (required_fields, optional_fields) in action_fields.items()
        },
        "composition_contract": OPERATION_COMPOSITION_CONTRACT,
        "actions": actions,
        "limits": {
            "targets": fragments["limits"]["targets"],
            "properties_per_target": fragments["limits"]["properties_per_target"],
            "action_bytes": MAX_COMPOSER_ACTION_BYTES,
        },
        "registry_fragments": fragments,
        "complete_request_is_never_an_action": True,
        "completion_discipline": {
            "successful_action_response_is_complete": True,
            "compact_projection_is_not_truncation": True,
            "schema_required_fields_status_scope": (
                "structural_preview_readiness_only"
            ),
            "user_intent_coverage": (
                "compare_planned_actions_before_draft-check"
            ),
            "draft_inspect_required_before_next_planned_action": False,
        },
    }


def operation_composer_digest(operation: str, version: str) -> str:
    return canonical_sha256(operation_composer_contract(operation, version))


def new_composition(operation: str, version: str) -> dict[str, Any]:
    contract = operation_composer_contract(operation, version)
    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        gateway_default = contract["planning_discipline"]["import_operation"][
            "gateway_default"
        ]
        return {
            "contract": OPERATION_COMPOSITION_CONTRACT,
            "request_options": {"import_operation": gateway_default},
            "defaults": {},
            "imports": [],
        }
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "request_options": {},
        "targets": [],
    }


def apply_composer_action(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
    action: Mapping[str, Any],
    *,
    handle_factory: Callable[[], str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Validate and apply one closed action without mutating the input mapping."""

    operation_composer_contract(operation, version)
    normalized = _normalize_composition(composition, operation=operation, version=version)
    _require_json_object(action, label="action")
    try:
        action_size = len(canonical_json_bytes(dict(action)))
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise OperationComposerError("Operation Draft action must be strict JSON.") from exc
    action_limit = operation_composer_contract(operation, version)["limits"][
        "action_bytes"
    ]
    if action_size > action_limit:
        raise OperationComposerError(
            "Operation Draft action exceeds its fixed byte ceiling.",
            details={
                "size_bytes": action_size,
                "limit_bytes": action_limit,
            },
        )
    if action.get("contract") != OPERATION_DRAFT_ACTION_CONTRACT:
        raise OperationComposerError(
            f"action contract must be {OPERATION_DRAFT_ACTION_CONTRACT!r}."
        )
    action_name = action.get("action")
    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        return _apply_audio_import_action(
            version,
            normalized,
            action,
            action_name=action_name,
            handle_factory=handle_factory,
        )
    if action_name == "set_request_option":
        _require_exact_keys(
            action,
            required=("contract", "action", "name", "value"),
            label="set_request_option action",
        )
        descriptor = _validate_fragment(
            version,
            fragment="request_option",
            payload={"name": action.get("name"), "value": action.get("value")},
        )
        normalized["request_options"][descriptor["name"]] = descriptor["value"]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "clear_request_option":
        _require_exact_keys(
            action,
            required=("contract", "action", "name"),
            label="clear_request_option action",
        )
        name = action.get("name")
        if not isinstance(name, str) or name not in normalized["request_options"]:
            raise OperationComposerError(
                "The requested Operation Draft option does not exist.",
                details={"name": name},
            )
        del normalized["request_options"][name]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "add_target":
        _require_allowed_keys(
            action,
            required=("contract", "action", "selector"),
            optional=(
                "name",
                "notes",
                "platform",
                "list_mode",
                "on_name_conflict",
                "properties",
                "references",
            ),
            label="add_target action",
        )
        target_limit = _target_limit(version)
        if len(normalized["targets"]) >= target_limit:
            raise OperationComposerError(
                "Operation Draft target ceiling has been reached.",
                details={"limit": target_limit},
            )
        selector = _validate_fragment(
            version,
            fragment="target_selector",
            payload=action.get("selector"),
        )
        fields: dict[str, Any] = {}
        for name in (
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
        ):
            if name not in action:
                continue
            descriptor = _validate_fragment(
                version,
                fragment="target_field",
                payload={"name": name, "value": action[name]},
            )
            fields[descriptor["name"]] = descriptor["value"]
        raw_properties = action.get("properties", [])
        if (
            not isinstance(raw_properties, list)
            or len(raw_properties) > _property_limit(version)
        ):
            raise OperationComposerError(
                "add_target properties are invalid or exceed their ceiling.",
                details={"limit": _property_limit(version)},
            )
        properties = [
            _validate_fragment(
                version,
                fragment="scalar_property",
                payload=item,
            )
            for item in raw_properties
        ]
        property_names = [str(item["name"]) for item in properties]
        if len(property_names) != len(set(property_names)):
            raise OperationComposerError(
                "add_target property facts must be unique."
            )
        raw_references = action.get("references", [])
        if (
            not isinstance(raw_references, list)
            or len(raw_references) > _property_limit(version)
        ):
            raise OperationComposerError(
                "add_target references are invalid or exceed their ceiling.",
                details={"limit": _property_limit(version)},
            )
        references = [
            _validate_fragment(version, fragment="reference", payload=item)
            for item in raw_references
        ]
        reference_names = [str(item["name"]) for item in references]
        if len(reference_names) != len(set(reference_names)):
            raise OperationComposerError(
                "add_target reference facts must be unique."
            )
        selector_key = canonical_json_bytes(selector)
        if any(
            canonical_json_bytes(item["selector"]) == selector_key
            for item in normalized["targets"]
        ):
            raise OperationComposerError(
                "Operation Draft target selectors must be unique."
            )
        factory = handle_factory or _new_target_handle
        handle = factory()
        if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
            raise OperationComposerError(
                "Gateway target handle generation returned an invalid handle."
            )
        normalized["targets"].append(
            {
                "handle": handle,
                "selector": selector,
                "fields": fields,
                "properties": properties,
                "references": references,
                "children": [],
                "lists": [],
                "import": None,
            }
        )
        return normalized, action_name
    if action_name in {"set_target_field", "clear_target_field"}:
        required = (
            ("contract", "action", "target_handle", "name", "value")
            if action_name == "set_target_field"
            else ("contract", "action", "target_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        target = _target_for_handle(normalized, action.get("target_handle"))
        name = action.get("name")
        fields = target["fields"]
        assert isinstance(fields, dict)
        if action_name == "set_target_field":
            descriptor = _validate_fragment(
                version,
                fragment="target_field",
                payload={"name": name, "value": action.get("value")},
            )
            fields[descriptor["name"]] = descriptor["value"]
        else:
            if not isinstance(name, str) or name not in fields:
                raise OperationComposerError(
                    "The requested target field fact does not exist.",
                    details={"name": name},
                )
            del fields[name]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "set_property":
        _require_exact_keys(
            action,
            required=("contract", "action", "target_handle", "name", "value"),
            label="set_property action",
        )
        target = _target_for_handle(normalized, action.get("target_handle"))
        descriptor = _validate_fragment(
            version,
            fragment="scalar_property",
            payload={"name": action.get("name"), "value": action.get("value")},
        )
        properties = target["properties"]
        assert isinstance(properties, list)
        match_index = next(
            (
                index
                for index, existing in enumerate(properties)
                if existing["name"] == descriptor["name"]
            ),
            None,
        )
        if match_index is None:
            property_limit = _property_limit(version)
            if len(properties) >= property_limit:
                raise OperationComposerError(
                    "Target property ceiling has been reached.",
                    details={"limit": property_limit},
                )
            properties.append(descriptor)
        else:
            properties[match_index] = descriptor
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "remove_property":
        _require_exact_keys(
            action,
            required=("contract", "action", "target_handle", "name"),
            label="remove_property action",
        )
        target = _target_for_handle(normalized, action.get("target_handle"))
        name = action.get("name")
        if not isinstance(name, str):
            raise OperationComposerError("remove_property name must be a string.")
        properties = target["properties"]
        assert isinstance(properties, list)
        match_index = next(
            (
                index
                for index, existing in enumerate(properties)
                if existing["name"] == name
            ),
            None,
        )
        if match_index is None:
            raise OperationComposerError(
                "The requested property fact does not exist.",
                details={"name": name},
            )
        del properties[match_index]
        return normalized, action_name
    if action_name in {"set_reference", "remove_reference"}:
        required = (
            ("contract", "action", "owner_handle", "name", "target")
            if action_name == "set_reference"
            else ("contract", "action", "owner_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        owner = _owner_for_handle(normalized, action.get("owner_handle"))
        references = owner["references"]
        assert isinstance(references, list)
        name = action.get("name")
        match_index = next(
            (
                index
                for index, existing in enumerate(references)
                if existing["name"] == name
            ),
            None,
        )
        if action_name == "set_reference":
            descriptor = _validate_fragment(
                version,
                fragment="reference",
                payload={"name": name, "target": action.get("target")},
            )
            if match_index is None:
                if len(references) >= _property_limit(version):
                    raise OperationComposerError(
                        "Owner reference ceiling has been reached.",
                        details={"limit": _property_limit(version)},
                    )
                references.append(descriptor)
            else:
                references[match_index] = descriptor
        else:
            if match_index is None:
                raise OperationComposerError(
                    "The requested reference fact does not exist.",
                    details={"name": name},
                )
            del references[match_index]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "remove_target":
        _require_exact_keys(
            action,
            required=("contract", "action", "target_handle"),
            label="remove_target action",
        )
        target = _target_for_handle(normalized, action.get("target_handle"))
        normalized["targets"].remove(target)
        return normalized, action_name
    if action_name == "add_child":
        _require_exact_keys(
            action,
            required=("contract", "action", "parent_handle", "type", "name"),
            label="add_child action",
        )
        parent = _owner_for_handle(normalized, action.get("parent_handle"))
        node_payload = _validate_fragment(
            version,
            fragment="node",
            payload={"type": action.get("type"), "name": action.get("name")},
        )
        children = parent["children"]
        assert isinstance(children, list)
        limit = _composer_limit(version, "children_per_parent")
        if len(children) >= limit:
            raise OperationComposerError(
                "Operation Draft child ceiling has been reached.",
                details={"limit": limit},
            )
        if any(
            item["fields"]["name"].casefold() == str(node_payload["name"]).casefold()
            for item in children
        ):
            raise OperationComposerError("Sibling object names must be unique.")
        children.append(
            _new_node(
                type_name=str(node_payload["type"]),
                name=str(node_payload["name"]),
                handle_factory=handle_factory,
            )
        )
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name in {"set_node_field", "clear_node_field"}:
        required = (
            ("contract", "action", "node_handle", "name", "value")
            if action_name == "set_node_field"
            else ("contract", "action", "node_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        node = _node_for_handle(normalized, action.get("node_handle"))
        name = action.get("name")
        fields = node["fields"]
        assert isinstance(fields, dict)
        if action_name == "set_node_field":
            descriptor = _validate_fragment(
                version,
                fragment="node_field",
                payload={"name": name, "value": action.get("value")},
            )
            fields[descriptor["name"]] = descriptor["value"]
        else:
            if name in {"type", "name"}:
                raise OperationComposerError("Required node fields cannot be cleared.")
            if not isinstance(name, str) or name not in fields:
                raise OperationComposerError(
                    "The requested node field fact does not exist.",
                    details={"name": name},
                )
            del fields[name]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name in {"set_node_property", "remove_node_property"}:
        required = (
            ("contract", "action", "node_handle", "name", "value")
            if action_name == "set_node_property"
            else ("contract", "action", "node_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        node = _node_for_handle(normalized, action.get("node_handle"))
        properties = node["properties"]
        assert isinstance(properties, list)
        name = action.get("name")
        match_index = next(
            (
                index
                for index, existing in enumerate(properties)
                if existing["name"] == name
            ),
            None,
        )
        if action_name == "set_node_property":
            descriptor = _validate_fragment(
                version,
                fragment="scalar_property",
                payload={"name": name, "value": action.get("value")},
            )
            if match_index is None:
                if len(properties) >= _property_limit(version):
                    raise OperationComposerError(
                        "Node property ceiling has been reached.",
                        details={"limit": _property_limit(version)},
                    )
                properties.append(descriptor)
            else:
                properties[match_index] = descriptor
        else:
            if match_index is None:
                raise OperationComposerError(
                    "The requested node property fact does not exist.",
                    details={"name": name},
                )
            del properties[match_index]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "remove_node":
        _require_exact_keys(
            action,
            required=("contract", "action", "node_handle"),
            label="remove_node action",
        )
        _remove_node(normalized, action.get("node_handle"))
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "add_list":
        _require_exact_keys(
            action,
            required=("contract", "action", "target_handle", "name"),
            label="add_list action",
        )
        target = _target_for_handle(normalized, action.get("target_handle"))
        descriptor = _validate_fragment(
            version,
            fragment="list_name",
            payload=action.get("name"),
        )
        lists = target["lists"]
        assert isinstance(lists, list)
        limit = _composer_limit(version, "lists_per_target")
        if len(lists) >= limit:
            raise OperationComposerError(
                "Operation Draft list ceiling has been reached.",
                details={"limit": limit},
            )
        if any(item["name"].casefold() == descriptor["name"].casefold() for item in lists):
            raise OperationComposerError("Operation Draft list names must be unique.")
        lists.append(
            {
                "handle": _new_handle(handle_factory=handle_factory, label="list"),
                "name": descriptor["name"],
                "objects": [],
            }
        )
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "remove_list":
        _require_exact_keys(
            action,
            required=("contract", "action", "list_handle"),
            label="remove_list action",
        )
        owner, descriptor = _list_for_handle(normalized, action.get("list_handle"))
        owner["lists"].remove(descriptor)
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "add_list_member":
        _require_exact_keys(
            action,
            required=("contract", "action", "list_handle", "type", "name"),
            label="add_list_member action",
        )
        _owner, descriptor = _list_for_handle(normalized, action.get("list_handle"))
        node_payload = _validate_fragment(
            version,
            fragment="node",
            payload={"type": action.get("type"), "name": action.get("name")},
        )
        objects = descriptor["objects"]
        limit = _composer_limit(version, "children_per_parent")
        if len(objects) >= limit:
            raise OperationComposerError(
                "Operation Draft list-member ceiling has been reached.",
                details={"limit": limit},
            )
        if any(
            item["fields"]["name"].casefold() == str(node_payload["name"]).casefold()
            for item in objects
        ):
            raise OperationComposerError("List member names must be unique.")
        objects.append(
            _new_node(
                type_name=str(node_payload["type"]),
                name=str(node_payload["name"]),
                handle_factory=handle_factory,
            )
        )
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "add_import_file":
        _require_allowed_keys(
            action,
            required=("contract", "action", "owner_handle"),
            optional=(
                "audio_file",
                "audio_file_base64",
                "originals_subfolder",
                "language",
                "object_type",
            ),
            label="add_import_file action",
        )
        owner = _owner_for_handle(normalized, action.get("owner_handle"))
        raw_file = {
            name: action[name]
            for name in (
                "audio_file",
                "audio_file_base64",
                "originals_subfolder",
                "language",
                "object_type",
            )
            if name in action
        }
        descriptor = _validate_fragment(
            version,
            fragment="import_file",
            payload=raw_file,
        )
        import_fact = owner.get("import")
        if import_fact is None:
            import_fact = {"options": {}, "files": []}
            owner["import"] = import_fact
        files = import_fact["files"]
        limit = _composer_limit(version, "files_per_import")
        if len(files) >= limit:
            raise OperationComposerError(
                "Operation Draft import-file ceiling has been reached.",
                details={"limit": limit},
            )
        files.append(
            {
                "handle": _new_handle(handle_factory=handle_factory, label="import file"),
                **descriptor,
            }
        )
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name in {"set_import_option", "clear_import_option"}:
        required = (
            ("contract", "action", "owner_handle", "name", "value")
            if action_name == "set_import_option"
            else ("contract", "action", "owner_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        owner = _owner_for_handle(normalized, action.get("owner_handle"))
        import_fact = owner.get("import")
        if not isinstance(import_fact, dict):
            raise OperationComposerError("The requested owner has no import facts.")
        options = import_fact["options"]
        name = action.get("name")
        if action_name == "set_import_option":
            descriptor = _validate_fragment(
                version,
                fragment="import_option",
                payload={"name": name, "value": action.get("value")},
            )
            options[descriptor["name"]] = descriptor["value"]
        else:
            if not isinstance(name, str) or name not in options:
                raise OperationComposerError("The requested import option does not exist.")
            del options[name]
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name in {"set_import_file_field", "clear_import_file_field"}:
        required = (
            ("contract", "action", "file_handle", "name", "value")
            if action_name == "set_import_file_field"
            else ("contract", "action", "file_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        _owner, file_fact = _import_file_for_handle(normalized, action.get("file_handle"))
        name = action.get("name")
        allowed = {
            "audio_file",
            "audio_file_base64",
            "originals_subfolder",
            "language",
            "object_type",
        }
        if not isinstance(name, str) or name not in allowed:
            raise OperationComposerError("The requested import-file field is not reviewed.")
        candidate = {key: value for key, value in file_fact.items() if key != "handle"}
        if action_name == "set_import_file_field":
            if name == "audio_file":
                candidate.pop("audio_file_base64", None)
            elif name == "audio_file_base64":
                candidate.pop("audio_file", None)
            candidate[name] = action.get("value")
        else:
            if name in {"audio_file", "audio_file_base64"}:
                raise OperationComposerError(
                    "The only import source cannot be cleared; remove the file fact instead."
                )
            if name not in candidate:
                raise OperationComposerError("The requested import-file field does not exist.")
            del candidate[name]
        descriptor = _validate_fragment(
            version,
            fragment="import_file",
            payload=candidate,
        )
        file_fact.clear()
        file_fact.update({"handle": action.get("file_handle"), **descriptor})
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "remove_import_file":
        _require_exact_keys(
            action,
            required=("contract", "action", "file_handle"),
            label="remove_import_file action",
        )
        owner, file_fact = _import_file_for_handle(normalized, action.get("file_handle"))
        import_fact = owner["import"]
        import_fact["files"].remove(file_fact)
        if not import_fact["files"]:
            owner["import"] = None
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    if action_name == "remove_import":
        _require_exact_keys(
            action,
            required=("contract", "action", "owner_handle"),
            label="remove_import action",
        )
        owner = _owner_for_handle(normalized, action.get("owner_handle"))
        if owner.get("import") is None:
            raise OperationComposerError("The requested owner has no import facts.")
        owner["import"] = None
        _materialize_if_complete(operation, version, normalized)
        return normalized, action_name
    raise OperationComposerError(
        "Operation Draft action is not supported by this Adapter.",
        details={
            "action": action_name,
            "allowed": operation_composer_contract(operation, version)["actions"],
        },
    )


def materialize_operation_request(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and canonically reparse the complete operation request."""

    normalized = _normalize_composition(composition, operation=operation, version=version)
    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        return _materialize_audio_import_request(version, normalized)
    targets = normalized["targets"]
    if not targets or len(targets) > _target_limit(version):
        raise OperationComposerError(
            "Operation Draft needs between one and the target ceiling before it can be checked.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
            details={
                "target_count": len(targets),
                "minimum": 1,
                "limit": _target_limit(version),
            },
        )
    for target in targets:
        if not _target_has_change(target):
            raise OperationComposerError(
                "Every Operation Draft target needs at least one requested change.",
                error_code="OPERATION_DRAFT_INCOMPLETE",
                details={"target_handle": target["handle"]},
            )
    arguments = {
        "objects": [
            {
                "object": dict(target["selector"]),
                **dict(target["fields"]),
                **(
                    {"properties": [dict(item) for item in target["properties"]]}
                    if target["properties"]
                    else {}
                ),
                **(
                    {"references": [dict(item) for item in target["references"]]}
                    if target["references"]
                    else {}
                ),
                **(
                    {"children": [_materialize_node(item) for item in target["children"]]}
                    if target["children"]
                    else {}
                ),
                **(
                    {
                        "lists": [
                            {
                                "name": item["name"],
                                "objects": [
                                    _materialize_node(node) for node in item["objects"]
                                ],
                            }
                            for item in target["lists"]
                        ]
                    }
                    if target["lists"]
                    else {}
                ),
                **(
                    {"import": _materialize_import(target["import"])}
                    if target["import"] is not None
                    else {}
                ),
            }
            for target in targets
        ],
        **dict(normalized["request_options"]),
    }
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": operation,
        "arguments": arguments,
    }
    try:
        return parse_operation_request(request, expected_version=version).as_dict()
    except OperationContractError as exc:
        raise OperationComposerError(
            str(exc),
            details=exc.details,
            error_code=exc.error_code,
        ) from exc


def composition_projection(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_composition(composition, operation=operation, version=version)
    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        return _audio_import_composition_projection(version, normalized)
    facts = [
        {
            "handle": target["handle"],
            "selector": dict(target["selector"]),
            **dict(target["fields"]),
            "properties": [dict(item) for item in target["properties"]],
            "references": [dict(item) for item in target["references"]],
            "children": [_node_projection(item) for item in target["children"]],
            "lists": [
                {
                    "handle": item["handle"],
                    "name": item["name"],
                    "objects": [_node_projection(node) for node in item["objects"]],
                }
                for item in target["lists"]
            ],
            "import": (
                None
                if target["import"] is None
                else _import_projection(target["import"])
            ),
        }
        for target in normalized["targets"]
    ]
    missing: list[str] = []
    if not facts:
        missing.append("target")
    else:
        for fact in facts:
            if not _projected_target_has_change(fact):
                missing.append(f"targets[{fact['handle']}].change")
            effective_list_mode = fact.get(
                "list_mode",
                normalized["request_options"].get("list_mode", "append"),
            )
            if effective_list_mode == "append":
                for list_fact in fact["lists"]:
                    if not list_fact["objects"]:
                        missing.append(
                            f"targets[{fact['handle']}].lists[{list_fact['handle']}].objects"
                        )
    if not facts:
        allowed = [
            "set_request_option",
            "clear_request_option",
            "add_target",
            "inspect",
            "cancel",
        ]
    elif missing:
        allowed = [
            "set_request_option",
            "clear_request_option",
            "add_target",
            "set_property",
            "set_reference",
            "remove_reference",
            "set_target_field",
            "clear_target_field",
            "add_child",
            "set_node_field",
            "clear_node_field",
            "set_node_property",
            "remove_node_property",
            "remove_node",
            "add_list",
            "remove_list",
            "add_list_member",
            "add_import_file",
            "set_import_file_field",
            "clear_import_file_field",
            "remove_import_file",
            "set_import_option",
            "clear_import_option",
            "remove_import",
            "remove_target",
            "inspect",
            "cancel",
        ]
    else:
        allowed = [
            "set_request_option",
            "clear_request_option",
            "add_target",
            "set_property",
            "set_reference",
            "remove_reference",
            "set_target_field",
            "clear_target_field",
            "add_child",
            "set_node_field",
            "clear_node_field",
            "set_node_property",
            "remove_node_property",
            "remove_node",
            "add_list",
            "remove_list",
            "add_list_member",
            "add_import_file",
            "set_import_file_field",
            "clear_import_file_field",
            "remove_import_file",
            "set_import_option",
            "clear_import_option",
            "remove_import",
            "remove_property",
            "remove_target",
            "check",
            "inspect",
            "cancel",
        ]
    supported_actions = set(operation_composer_contract(operation, version)["actions"])
    lifecycle_actions = {"check", "inspect", "cancel", "preview-from-draft"}
    allowed = [
        action
        for action in allowed
        if action in supported_actions or action in lifecycle_actions
    ]
    return {
        "request_options": dict(normalized["request_options"]),
        "current_facts": facts,
        "missing_fields": missing,
        "missing_fields_status": "complete" if not missing else "incomplete",
        "allowed_actions": allowed,
    }


def _normalize_composition(
    composition: Mapping[str, Any],
    *,
    operation: str,
    version: str,
) -> dict[str, Any]:
    operation_composer_contract(operation, version)
    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        return _normalize_audio_import_composition(composition, version=version)
    _require_json_object(composition, label="composition")
    actual_keys = set(composition)
    required_keys = {"contract", "targets"}
    optional_keys = {"request_options"}
    if not required_keys.issubset(actual_keys) or actual_keys - required_keys - optional_keys:
        raise OperationComposerError(
            "composition fields are invalid.",
            details={
                "missing": sorted(required_keys - actual_keys),
                "unexpected": sorted(actual_keys - required_keys - optional_keys),
            },
        )
    if composition.get("contract") != OPERATION_COMPOSITION_CONTRACT:
        raise OperationComposerError("Operation Draft composition contract is invalid.")
    raw_request_options = composition.get("request_options", {})
    if not isinstance(raw_request_options, Mapping):
        raise OperationComposerError("Operation Draft request options are invalid.")
    request_options: dict[str, Any] = {}
    for name, value in raw_request_options.items():
        descriptor = _validate_fragment(
            version,
            fragment="request_option",
            payload={"name": name, "value": value},
        )
        request_options[descriptor["name"]] = descriptor["value"]
    raw_targets = composition.get("targets")
    if not isinstance(raw_targets, list) or len(raw_targets) > _target_limit(version):
        raise OperationComposerError(
            "Operation Draft composition exceeds its target ceiling.",
            details={"limit": _target_limit(version)},
        )
    targets: list[dict[str, Any]] = []
    handles: set[str] = set()
    for raw_target in raw_targets:
        _require_json_object(raw_target, label="composition target")
        actual_target_keys = set(raw_target)
        required_target_keys = {"handle", "selector", "properties"}
        optional_target_keys = {
            "fields",
            "references",
            "children",
            "lists",
            "import",
        }
        if (
            not required_target_keys.issubset(actual_target_keys)
            or actual_target_keys - required_target_keys - optional_target_keys
        ):
            raise OperationComposerError("composition target fields are invalid.")
        handle = raw_target.get("handle")
        if (
            not isinstance(handle, str)
            or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None
            or handle in handles
        ):
            raise OperationComposerError("Operation Draft target handle is invalid.")
        handles.add(handle)
        selector = _validate_fragment(
            version,
            fragment="target_selector",
            payload=raw_target.get("selector"),
        )
        raw_properties = raw_target.get("properties")
        if (
            not isinstance(raw_properties, list)
            or len(raw_properties) > _property_limit(version)
        ):
            raise OperationComposerError(
                "Operation Draft target properties are invalid or exceed their ceiling.",
                details={"limit": _property_limit(version)},
            )
        properties = [
            _validate_fragment(
                version,
                fragment="scalar_property",
                payload=item,
            )
            for item in raw_properties
        ]
        names = [str(item["name"]) for item in properties]
        if len(names) != len(set(names)):
            raise OperationComposerError("Operation Draft property facts must be unique.")
        raw_references = raw_target.get("references", [])
        if (
            not isinstance(raw_references, list)
            or len(raw_references) > _property_limit(version)
        ):
            raise OperationComposerError(
                "Operation Draft target references are invalid or exceed their ceiling.",
                details={"limit": _property_limit(version)},
            )
        references = [
            _validate_fragment(version, fragment="reference", payload=item)
            for item in raw_references
        ]
        reference_names = [str(item["name"]) for item in references]
        if len(reference_names) != len(set(reference_names)):
            raise OperationComposerError("Operation Draft reference facts must be unique.")
        raw_fields = raw_target.get("fields", {})
        if not isinstance(raw_fields, Mapping):
            raise OperationComposerError("Operation Draft target fields are invalid.")
        fields: dict[str, Any] = {}
        for name, value in raw_fields.items():
            descriptor = _validate_fragment(
                version,
                fragment="target_field",
                payload={"name": name, "value": value},
            )
            fields[descriptor["name"]] = descriptor["value"]
        raw_children = raw_target.get("children", [])
        if not isinstance(raw_children, list):
            raise OperationComposerError("Operation Draft target children are invalid.")
        children = [
            _normalize_node(item, version=version, depth=1)
            for item in raw_children
        ]
        if len(children) > _composer_limit(version, "children_per_parent"):
            raise OperationComposerError("Operation Draft target children exceed their ceiling.")
        raw_lists = raw_target.get("lists", [])
        if not isinstance(raw_lists, list) or len(raw_lists) > _composer_limit(
            version, "lists_per_target"
        ):
            raise OperationComposerError("Operation Draft target lists are invalid.")
        lists = [
            _normalize_list(item, version=version)
            for item in raw_lists
        ]
        if len({item["name"].casefold() for item in lists}) != len(lists):
            raise OperationComposerError("Operation Draft list names must be unique.")
        import_fact = _normalize_import(
            raw_target.get("import"),
            version=version,
        )
        targets.append(
            {
                "handle": handle,
                "selector": selector,
                "fields": fields,
                "properties": properties,
                "references": references,
                "children": children,
                "lists": lists,
                "import": import_fact,
            }
        )
    selector_keys = [canonical_json_bytes(item["selector"]) for item in targets]
    if len(selector_keys) != len(set(selector_keys)):
        raise OperationComposerError("Operation Draft target selectors must be unique.")
    all_nodes = _iter_nodes(targets)
    if len(targets) + len(all_nodes) > _composer_limit(version, "total_nodes"):
        raise OperationComposerError(
            "Operation Draft target and child nodes exceed their shared ceiling.",
            details={
                "count": len(targets) + len(all_nodes),
                "limit": _composer_limit(version, "total_nodes"),
            },
        )
    handles = _all_handles(targets)
    if len(handles) != len(set(handles)):
        raise OperationComposerError("Operation Draft handles must be unique.")
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "request_options": request_options,
        "targets": targets,
    }


def _materialize_if_complete(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
) -> None:
    projection = composition_projection(operation, version, composition)
    if not projection["missing_fields"]:
        materialize_operation_request(operation, version, composition)


def _apply_audio_import_action(
    version: str,
    composition: dict[str, Any],
    action: Mapping[str, Any],
    *,
    action_name: Any,
    handle_factory: Callable[[], str] | None,
) -> tuple[dict[str, Any], str]:
    if action_name in {"set_import_option", "clear_import_option"}:
        required = (
            ("contract", "action", "name", "value")
            if action_name == "set_import_option"
            else ("contract", "action", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        options = composition["request_options"]
        assert isinstance(options, dict)
        if action_name == "set_import_option":
            descriptor = _validate_audio_import_fragment(
                version,
                fragment="request_option",
                payload={"name": action.get("name"), "value": action.get("value")},
            )
            options[descriptor["name"]] = descriptor["value"]
        else:
            name = action.get("name")
            if not isinstance(name, str) or name not in options:
                raise OperationComposerError(
                    "The requested audio.import option does not exist.",
                    details={"name": name},
                )
            del options[name]
        _materialize_if_complete(AUDIO_IMPORT_COMPOSER_OPERATION, version, composition)
        return composition, str(action_name)
    if action_name in {"set_import_default", "clear_import_default"}:
        required = (
            ("contract", "action", "name", "value")
            if action_name == "set_import_default"
            else ("contract", "action", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        defaults = composition["defaults"]
        assert isinstance(defaults, dict)
        name = action.get("name")
        if action_name == "set_import_default":
            descriptor = _validate_audio_import_fragment(
                version,
                fragment="row_field",
                payload={"name": name, "value": action.get("value")},
            )
            defaults[descriptor["name"]] = descriptor["value"]
        else:
            if not isinstance(name, str) or name not in defaults:
                raise OperationComposerError(
                    "The requested audio.import default does not exist.",
                    details={"name": name},
                )
            del defaults[name]
        _materialize_if_complete(AUDIO_IMPORT_COMPOSER_OPERATION, version, composition)
        return composition, str(action_name)
    if action_name in {
        "add_import_row",
        "add_switch_assigned_import_row",
    }:
        row_field_names = tuple(
            operation_composer_contract(
                AUDIO_IMPORT_COMPOSER_OPERATION, version
            )["registry_fragments"]["supported_row_fields"]
        )
        required_action_fields, optional_action_fields = (
            _AUDIO_IMPORT_ACTION_FIELDS[action_name]
        )
        compatibility_optional_fields = (
            ("assignment",) if action_name == "add_import_row" else ()
        )
        _require_allowed_keys(
            action,
            required=(
                "contract",
                "action",
                *required_action_fields,
            ),
            optional=(*optional_action_fields, *compatibility_optional_fields),
            label=f"{action_name} action",
        )
        has_assignment = "assignment" in action
        assignment = action.get("assignment")
        if has_assignment and not isinstance(assignment, Mapping):
            raise OperationComposerError(
                "add_import_row assignment must be an object."
            )
        mode = assignment.get("mode") if isinstance(assignment, Mapping) else None
        if action_name == "add_switch_assigned_import_row" and not has_assignment:
            raise OperationComposerError(
                "add_switch_assigned_import_row requires a switch assignment."
            )
        if not has_assignment:
            switch_assignment = None
        elif mode == "switch":
            _require_exact_keys(
                assignment,
                required=("mode", "value"),
                label="add_import_row switch assignment",
            )
            switch_assignment = _validate_audio_import_fragment(
                version,
                fragment="row_field",
                payload={
                    "name": "switch_assignment",
                    "value": assignment.get("value"),
                },
            )
        elif mode == "none":
            _require_exact_keys(
                assignment,
                required=("mode",),
                label="legacy add_import_row no-assignment intent",
            )
            switch_assignment = None
        else:
            raise OperationComposerError(
                "add_import_row assignment mode must be 'switch' or 'none'.",
                details={"mode": mode},
            )
        rows = composition["imports"]
        assert isinstance(rows, list)
        limit = _audio_import_limit(version)
        if len(rows) >= limit:
            raise OperationComposerError(
                "Operation Draft import-row ceiling has been reached.",
                details={"limit": limit},
            )
        fields: dict[str, Any] = {}
        for name in row_field_names:
            if name not in action:
                continue
            descriptor = _validate_audio_import_fragment(
                version,
                fragment="row_field",
                payload={"name": name, "value": action[name]},
            )
            fields[descriptor["name"]] = descriptor["value"]
        if switch_assignment is not None:
            fields[switch_assignment["name"]] = switch_assignment["value"]
        defaults = composition["defaults"]
        assert isinstance(defaults, dict)
        if "object_type" not in fields and "object_type" not in defaults:
            raise OperationComposerError(
                "audio.import rows require an explicit object type.",
                details={
                    "missing_fields": ["object_type"],
                    "row_kind": "structure_or_media",
                },
            )
        if any(name in fields for name in ("audio_file", "audio_file_base64")):
            if "import_language" not in fields and "import_language" not in defaults:
                raise OperationComposerError(
                    "audio.import media rows require an explicit import language.",
                    details={
                        "missing_fields": ["import_language"],
                        "row_kind": "media",
                    },
                )
        object_path = fields.get("object_path")
        if isinstance(object_path, str) and any(
            row["fields"].get("object_path") == object_path for row in rows
        ):
            raise OperationComposerError(
                "Operation Draft import object paths must be unique.",
                details={"object_path": object_path},
            )
        handle = (handle_factory or _new_target_handle)()
        if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
            raise OperationComposerError(
                "Gateway import-row handle generation returned an invalid handle."
            )
        rows.append({"handle": handle, "fields": fields})
        _materialize_if_complete(AUDIO_IMPORT_COMPOSER_OPERATION, version, composition)
        return composition, str(action_name)
    if action_name in {"set_import_row_field", "clear_import_row_field"}:
        required = (
            ("contract", "action", "import_handle", "name", "value")
            if action_name == "set_import_row_field"
            else ("contract", "action", "import_handle", "name")
        )
        _require_exact_keys(action, required=required, label=f"{action_name} action")
        row = _audio_import_row_for_handle(composition, action.get("import_handle"))
        fields = row["fields"]
        assert isinstance(fields, dict)
        name = action.get("name")
        if action_name == "set_import_row_field":
            descriptor = _validate_audio_import_fragment(
                version,
                fragment="row_field",
                payload={"name": name, "value": action.get("value")},
            )
            if descriptor["name"] == "object_path" and any(
                other is not row
                and other["fields"].get("object_path") == descriptor["value"]
                for other in composition["imports"]
            ):
                raise OperationComposerError(
                    "Operation Draft import object paths must be unique.",
                    details={"object_path": descriptor["value"]},
                )
            fields[descriptor["name"]] = descriptor["value"]
        else:
            if not isinstance(name, str) or name not in fields:
                raise OperationComposerError(
                    "The requested audio.import row field does not exist.",
                    details={"name": name},
                )
            del fields[name]
        _materialize_if_complete(AUDIO_IMPORT_COMPOSER_OPERATION, version, composition)
        return composition, str(action_name)
    if action_name == "remove_import_row":
        _require_exact_keys(
            action,
            required=("contract", "action", "import_handle"),
            label="remove_import_row action",
        )
        row = _audio_import_row_for_handle(composition, action.get("import_handle"))
        composition["imports"].remove(row)
        return composition, action_name
    raise OperationComposerError(
        "Operation Draft action is not supported by this Adapter.",
        details={
            "action": action_name,
            "allowed": operation_composer_contract(
                AUDIO_IMPORT_COMPOSER_OPERATION, version
            )["actions"],
        },
    )


def _normalize_audio_import_composition(
    composition: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    _require_json_object(composition, label="composition")
    required = {"contract", "imports"}
    optional = {"request_options", "defaults"}
    actual = set(composition)
    if not required.issubset(actual) or actual - required - optional:
        raise OperationComposerError(
            "audio.import composition fields are invalid.",
            details={
                "missing": sorted(required - actual),
                "unexpected": sorted(actual - required - optional),
            },
        )
    if composition.get("contract") != OPERATION_COMPOSITION_CONTRACT:
        raise OperationComposerError("Operation Draft composition contract is invalid.")
    raw_options = composition.get("request_options", {})
    if not isinstance(raw_options, Mapping):
        raise OperationComposerError("audio.import request options are invalid.")
    options: dict[str, Any] = {}
    for name, value in raw_options.items():
        descriptor = _validate_audio_import_fragment(
            version,
            fragment="request_option",
            payload={"name": name, "value": value},
        )
        options[descriptor["name"]] = descriptor["value"]
    raw_defaults = composition.get("defaults", {})
    if not isinstance(raw_defaults, Mapping):
        raise OperationComposerError("audio.import defaults are invalid.")
    defaults: dict[str, Any] = {}
    for name, value in raw_defaults.items():
        descriptor = _validate_audio_import_fragment(
            version,
            fragment="row_field",
            payload={"name": name, "value": value},
        )
        defaults[descriptor["name"]] = descriptor["value"]
    raw_rows = composition.get("imports")
    limit = _audio_import_limit(version)
    if not isinstance(raw_rows, list) or len(raw_rows) > limit:
        raise OperationComposerError(
            "audio.import composition rows are invalid or exceed their ceiling.",
            details={"limit": limit},
        )
    rows: list[dict[str, Any]] = []
    handles: set[str] = set()
    object_paths: set[str] = set()
    for raw_row in raw_rows:
        _require_json_object(raw_row, label="audio.import composition row")
        if set(raw_row) != {"handle", "fields"}:
            raise OperationComposerError("audio.import composition row fields are invalid.")
        handle = raw_row.get("handle")
        if (
            not isinstance(handle, str)
            or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None
            or handle in handles
        ):
            raise OperationComposerError("Operation Draft import-row handle is invalid.")
        handles.add(handle)
        raw_fields = raw_row.get("fields")
        if not isinstance(raw_fields, Mapping):
            raise OperationComposerError("audio.import row facts are invalid.")
        fields: dict[str, Any] = {}
        for name, value in raw_fields.items():
            descriptor = _validate_audio_import_fragment(
                version,
                fragment="row_field",
                payload={"name": name, "value": value},
            )
            fields[descriptor["name"]] = descriptor["value"]
        object_path = fields.get("object_path")
        if isinstance(object_path, str):
            if object_path in object_paths:
                raise OperationComposerError(
                    "Operation Draft import object paths must be unique."
                )
            object_paths.add(object_path)
        rows.append({"handle": handle, "fields": fields})
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "request_options": options,
        "defaults": defaults,
        "imports": rows,
    }


def _materialize_audio_import_request(
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    rows = composition["imports"]
    if not rows:
        raise OperationComposerError(
            "Operation Draft needs at least one import row before it can be checked.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
            details={"import_count": 0, "minimum": 1},
        )
    defaults = composition["defaults"]
    missing: list[str] = []
    for row in rows:
        fields = row["fields"]
        effective = {**defaults, **fields}
        if "object_path" not in effective:
            missing.append(f"imports[{row['handle']}].object_path")
        if not any(
            name in effective
            for name in ("audio_file", "audio_file_base64", "object_type")
        ):
            missing.append(f"imports[{row['handle']}].source_or_structure_type")
    if missing:
        raise OperationComposerError(
            "Operation Draft import rows are incomplete.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
            details={"missing_fields": missing},
        )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": AUDIO_IMPORT_COMPOSER_OPERATION,
        "arguments": {
            "imports": [dict(row["fields"]) for row in rows],
            **({"defaults": dict(defaults)} if defaults else {}),
            **dict(composition["request_options"]),
        },
    }
    try:
        return parse_operation_request(request, expected_version=version).as_dict()
    except OperationContractError as exc:
        raise OperationComposerError(
            str(exc),
            details=exc.details,
            error_code=exc.error_code,
        ) from exc


def _audio_import_composition_projection(
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    del version
    defaults = composition["defaults"]
    facts = [
        {"handle": row["handle"], **_audio_import_public_fields(row["fields"])}
        for row in composition["imports"]
    ]
    missing: list[str] = []
    if not facts:
        missing.append("import_row")
    for raw_row, row in zip(composition["imports"], facts):
        effective = {**defaults, **raw_row["fields"]}
        if "object_path" not in effective:
            missing.append(f"imports[{row['handle']}].object_path")
        if not any(
            name in effective
            for name in ("audio_file", "audio_file_base64", "object_type")
        ):
            missing.append(f"imports[{row['handle']}].source_or_structure_type")
    allowed = list(_AUDIO_IMPORT_ACTION_FIELDS)
    if not missing:
        allowed.append("check")
    allowed.extend(("inspect", "cancel"))
    return {
        "request_options": dict(composition["request_options"]),
        "defaults": _audio_import_public_fields(defaults),
        "action_guidance": {
            "switch_assignment": {
                "when_user_requested": "use_add_switch_assigned_import_row",
                "typed_argv_suffix": [
                    "--assignment",
                    "switch",
                    "<exact-value>",
                ],
                "omission_means": "no_switch_assignment",
                "follow_up_assignment_action_exists": False,
                "guessing_allowed": False,
            }
        },
        "current_facts": facts,
        "missing_fields": missing,
        "missing_fields_status": "complete" if not missing else "incomplete",
        "allowed_actions": allowed,
    }


def _audio_import_public_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Project import facts without echoing opaque inline media."""

    projected = dict(fields)
    inline_media = projected.get("audio_file_base64")
    if isinstance(inline_media, str):
        projected["audio_file_base64"] = {
            "redacted": True,
            "utf8_bytes": len(inline_media.encode("utf-8")),
            "canonical_sha256": canonical_sha256(inline_media),
        }
    return projected


def _audio_import_row_for_handle(
    composition: Mapping[str, Any],
    handle: Any,
) -> dict[str, Any]:
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("import_handle is invalid.")
    rows = composition.get("imports")
    assert isinstance(rows, list)
    for row in rows:
        if row["handle"] == handle:
            return row
    raise OperationComposerError(
        "import_handle does not name a fact in this Operation Draft."
    )


def _validate_audio_import_fragment(
    version: str,
    *,
    fragment: str,
    payload: Any,
) -> dict[str, Any]:
    try:
        return validate_audio_import_composer_fragment(
            version,
            fragment=fragment,
            payload=payload,
        )
    except OperationContractError as exc:
        raise OperationComposerError(
            str(exc),
            details={"cause_error_code": exc.error_code, **exc.details},
        ) from exc


def _audio_import_limit(version: str) -> int:
    value = audio_import_composer_fragment_contract(version)["limits"]["imports"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError("Registry returned an invalid audio.import row limit")
    return value


def _validate_fragment(
    version: str,
    *,
    fragment: str,
    payload: Any,
) -> dict[str, Any]:
    try:
        return validate_object_set_composer_fragment(
            version,
            fragment=fragment,
            payload=payload,
        )
    except OperationContractError as exc:
        raise OperationComposerError(
            str(exc),
            details={"cause_error_code": exc.error_code, **exc.details},
        ) from exc


def _property_limit(version: str) -> int:
    value = object_set_composer_fragment_contract(version)["limits"][
        "properties_per_target"
    ]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError("Registry returned an invalid Composer property limit")
    return value


def _target_limit(version: str) -> int:
    value = object_set_composer_fragment_contract(version)["limits"]["targets"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError("Registry returned an invalid Composer target limit")
    return value


def _composer_limit(version: str, name: str) -> int:
    value = object_set_composer_fragment_contract(version)["limits"].get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError(f"Registry returned an invalid Composer {name} limit")
    return value


def _new_node(
    *,
    type_name: str,
    name: str,
    handle_factory: Callable[[], str] | None,
) -> dict[str, Any]:
    return {
        "handle": _new_handle(handle_factory=handle_factory, label="node"),
        "fields": {"type": type_name, "name": name},
        "properties": [],
        "references": [],
        "children": [],
        "import": None,
    }


def _new_handle(
    *,
    handle_factory: Callable[[], str] | None,
    label: str,
) -> str:
    factory = handle_factory or _new_target_handle
    handle = factory()
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError(
            f"Gateway {label} handle generation returned an invalid handle."
        )
    return handle


def _normalize_node(
    value: Any,
    *,
    version: str,
    depth: int,
) -> dict[str, Any]:
    _require_json_object(value, label="composition node")
    _require_allowed_keys(
        value,
        required=("handle", "fields", "properties", "children", "import"),
        optional=("references",),
        label="composition node",
    )
    if depth > _composer_limit(version, "depth"):
        raise OperationComposerError("Operation Draft node depth exceeds its ceiling.")
    handle = value.get("handle")
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("Operation Draft node handle is invalid.")
    raw_fields = value.get("fields")
    if not isinstance(raw_fields, Mapping) or not {"type", "name"}.issubset(raw_fields):
        raise OperationComposerError("Operation Draft node fields are invalid.")
    fields: dict[str, Any] = {}
    for name, field_value in raw_fields.items():
        descriptor = _validate_fragment(
            version,
            fragment="node_field",
            payload={"name": name, "value": field_value},
        )
        fields[descriptor["name"]] = descriptor["value"]
    raw_properties = value.get("properties")
    if not isinstance(raw_properties, list) or len(raw_properties) > _property_limit(version):
        raise OperationComposerError("Operation Draft node properties are invalid.")
    properties = [
        _validate_fragment(version, fragment="scalar_property", payload=item)
        for item in raw_properties
    ]
    if len({item["name"] for item in properties}) != len(properties):
        raise OperationComposerError("Operation Draft node property facts must be unique.")
    raw_references = value.get("references", [])
    if (
        not isinstance(raw_references, list)
        or len(raw_references) > _property_limit(version)
    ):
        raise OperationComposerError("Operation Draft node references are invalid.")
    references = [
        _validate_fragment(version, fragment="reference", payload=item)
        for item in raw_references
    ]
    if len({item["name"] for item in references}) != len(references):
        raise OperationComposerError("Operation Draft node reference facts must be unique.")
    raw_children = value.get("children")
    if not isinstance(raw_children, list) or len(raw_children) > _composer_limit(
        version, "children_per_parent"
    ):
        raise OperationComposerError("Operation Draft node children are invalid.")
    children = [
        _normalize_node(item, version=version, depth=depth + 1)
        for item in raw_children
    ]
    normalized = {
        "handle": handle,
        "fields": fields,
        "properties": properties,
        "references": references,
        "children": children,
        "import": _normalize_import(value.get("import"), version=version),
    }
    _validate_fragment(version, fragment="node", payload=_materialize_node(normalized))
    return normalized


def _materialize_node(node: Mapping[str, Any]) -> dict[str, Any]:
    fields = dict(node["fields"])
    result = dict(fields)
    properties = node["properties"]
    references = node["references"]
    children = node["children"]
    if properties:
        result["properties"] = [dict(item) for item in properties]
    if references:
        result["references"] = [dict(item) for item in references]
    if children:
        result["children"] = [_materialize_node(item) for item in children]
    if node["import"] is not None:
        result["import"] = _materialize_import(node["import"])
    return result


def _node_projection(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "handle": node["handle"],
        **dict(node["fields"]),
        "properties": [dict(item) for item in node["properties"]],
        "references": [dict(item) for item in node["references"]],
        "children": [_node_projection(item) for item in node["children"]],
        "import": (
            None if node["import"] is None else _import_projection(node["import"])
        ),
    }


def _iter_nodes(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        result.append(node)
        for child in node["children"]:
            visit(child)

    for target in targets:
        for child in target["children"]:
            visit(child)
        for descriptor in target["lists"]:
            for member in descriptor["objects"]:
                visit(member)
    return result


def _all_handles(targets: list[dict[str, Any]]) -> list[str]:
    result = [str(target["handle"]) for target in targets]
    for target in targets:
        result.extend(str(item["handle"]) for item in target["lists"])
    nodes = _iter_nodes(targets)
    result.extend(str(node["handle"]) for node in nodes)
    for owner in [*targets, *nodes]:
        import_fact = owner.get("import")
        if isinstance(import_fact, Mapping):
            result.extend(str(item["handle"]) for item in import_fact["files"])
    return result


def _node_for_handle(composition: dict[str, Any], handle: Any) -> dict[str, Any]:
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("node_handle is invalid.")
    for node in _iter_nodes(composition["targets"]):
        if node["handle"] == handle:
            return node
    raise OperationComposerError("node_handle does not name a fact in this Operation Draft.")


def _owner_for_handle(composition: dict[str, Any], handle: Any) -> dict[str, Any]:
    try:
        return _target_for_handle(composition, handle)
    except OperationComposerError:
        return _node_for_handle(composition, handle)


def _remove_node(composition: dict[str, Any], handle: Any) -> None:
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("node_handle is invalid.")

    def remove(children: list[dict[str, Any]]) -> bool:
        for index, node in enumerate(children):
            if node["handle"] == handle:
                del children[index]
                return True
            if remove(node["children"]):
                return True
        return False

    for target in composition["targets"]:
        if remove(target["children"]):
            return
        for descriptor in target["lists"]:
            if remove(descriptor["objects"]):
                return
    raise OperationComposerError("node_handle does not name a fact in this Operation Draft.")


def _target_has_change(target: Mapping[str, Any]) -> bool:
    return bool(
        any(name in target["fields"] for name in ("name", "notes"))
        or target["properties"]
        or target["references"]
        or target["children"]
        or target["lists"]
        or target["import"] is not None
    )


def _projected_target_has_change(target: Mapping[str, Any]) -> bool:
    structural_fields = {
        "handle",
        "selector",
        "properties",
        "references",
        "children",
        "lists",
        "import",
    }
    return bool(
        target["properties"]
        or target["references"]
        or target["children"]
        or target["lists"]
        or target["import"] is not None
        or any(name in target for name in ("name", "notes"))
    )


def _normalize_list(value: Any, *, version: str) -> dict[str, Any]:
    _require_json_object(value, label="composition list")
    _require_exact_keys(
        value,
        required=("handle", "name", "objects"),
        label="composition list",
    )
    handle = value.get("handle")
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("Operation Draft list handle is invalid.")
    name = _validate_fragment(
        version,
        fragment="list_name",
        payload=value.get("name"),
    )["name"]
    raw_objects = value.get("objects")
    if not isinstance(raw_objects, list) or len(raw_objects) > _composer_limit(
        version, "children_per_parent"
    ):
        raise OperationComposerError("Operation Draft list members are invalid.")
    objects = [
        _normalize_node(item, version=version, depth=1)
        for item in raw_objects
    ]
    if len({item["fields"]["name"].casefold() for item in objects}) != len(objects):
        raise OperationComposerError("Operation Draft list member names must be unique.")
    return {"handle": handle, "name": name, "objects": objects}


def _list_for_handle(
    composition: dict[str, Any],
    handle: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("list_handle is invalid.")
    for target in composition["targets"]:
        for descriptor in target["lists"]:
            if descriptor["handle"] == handle:
                return target, descriptor
    raise OperationComposerError("list_handle does not name a fact in this Operation Draft.")


def _normalize_import(value: Any, *, version: str) -> dict[str, Any] | None:
    if value is None:
        return None
    _require_json_object(value, label="composition import")
    _require_exact_keys(
        value,
        required=("options", "files"),
        label="composition import",
    )
    raw_options = value.get("options")
    if not isinstance(raw_options, Mapping):
        raise OperationComposerError("Operation Draft import options are invalid.")
    options: dict[str, Any] = {}
    for name, option_value in raw_options.items():
        descriptor = _validate_fragment(
            version,
            fragment="import_option",
            payload={"name": name, "value": option_value},
        )
        options[descriptor["name"]] = descriptor["value"]
    raw_files = value.get("files")
    if not isinstance(raw_files, list) or not raw_files or len(raw_files) > _composer_limit(
        version, "files_per_import"
    ):
        raise OperationComposerError("Operation Draft import files are invalid.")
    files: list[dict[str, Any]] = []
    handles: set[str] = set()
    for raw_file in raw_files:
        _require_json_object(raw_file, label="composition import file")
        handle = raw_file.get("handle")
        if (
            not isinstance(handle, str)
            or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None
            or handle in handles
        ):
            raise OperationComposerError("Operation Draft import-file handle is invalid.")
        handles.add(handle)
        descriptor = _validate_fragment(
            version,
            fragment="import_file",
            payload={key: item for key, item in raw_file.items() if key != "handle"},
        )
        files.append({"handle": handle, **descriptor})
    return {"options": options, "files": files}


def _materialize_import(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "files": [
            {key: item for key, item in file_fact.items() if key != "handle"}
            for file_fact in value["files"]
        ],
        **dict(value["options"]),
    }


def _import_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(value["options"]),
        "files": [dict(file_fact) for file_fact in value["files"]],
    }


def _import_file_for_handle(
    composition: dict[str, Any],
    handle: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("file_handle is invalid.")
    owners: list[dict[str, Any]] = list(composition["targets"])
    owners.extend(_iter_nodes(composition["targets"]))
    for owner in owners:
        import_fact = owner.get("import")
        if not isinstance(import_fact, Mapping):
            continue
        for file_fact in import_fact["files"]:
            if file_fact["handle"] == handle:
                return owner, file_fact
    raise OperationComposerError("file_handle does not name a fact in this Operation Draft.")


def _target_for_handle(
    composition: dict[str, Any],
    handle: Any,
) -> dict[str, Any]:
    if not isinstance(handle, str) or _TARGET_HANDLE_PATTERN.fullmatch(handle) is None:
        raise OperationComposerError("target_handle is invalid.")
    for target in composition["targets"]:
        if target["handle"] == handle:
            return target
    raise OperationComposerError(
        "target_handle does not name a fact in this Operation Draft."
    )


def _new_target_handle() -> str:
    return f"odh1-{secrets.token_hex(12)}"


def _require_json_object(value: Any, *, label: str) -> None:
    if not isinstance(value, Mapping):
        raise OperationComposerError(f"{label} must be a JSON object.")
    try:
        normalized = json.loads(canonical_json_bytes(dict(value)).decode("utf-8"))
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise OperationComposerError(f"{label} must be strict JSON.") from exc
    if not isinstance(normalized, dict):
        raise OperationComposerError(f"{label} must be a JSON object.")


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: tuple[str, ...],
    label: str,
) -> None:
    expected = set(required)
    actual = set(value)
    if actual != expected:
        raise OperationComposerError(
            f"{label} fields are invalid.",
            details={
                "missing": sorted(expected - actual),
                "unexpected": sorted(actual - expected),
            },
        )


def _require_allowed_keys(
    value: Mapping[str, Any],
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    label: str,
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    actual = set(value)
    if not required_set.issubset(actual) or actual - allowed:
        raise OperationComposerError(
            f"{label} fields are invalid.",
            details={
                "missing": sorted(required_set - actual),
                "unexpected": sorted(actual - allowed),
            },
        )


__all__ = [
    "AUDIO_IMPORT_COMPOSER_OPERATION",
    "MAX_COMPOSER_ACTION_BYTES",
    "OBJECT_SET_COMPOSER_OPERATION",
    "OPERATION_COMPOSER_CONTRACT",
    "OPERATION_COMPOSITION_CONTRACT",
    "OPERATION_DRAFT_ACTION_CONTRACT",
    "OperationComposerError",
    "apply_composer_action",
    "composition_projection",
    "materialize_operation_request",
    "new_composition",
    "operation_composer_contract",
    "operation_composer_digest",
]

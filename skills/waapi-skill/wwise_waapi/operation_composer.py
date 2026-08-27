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
from .business_declaration_state import BusinessDeclarationSession
from .business_adapters import business_adapter
from .metadata_discovery import metadata_candidate_limit_contract
from .operation_registry import (
    audio_import_business_contract,
    OperationContractError,
    operation_business_contract,
    operation_uses_business_declaration,
    parse_operation_request,
)
from .typed_requests import (
    MAX_TYPED_ARRAY_ITEMS,
    MAX_TYPED_ACTIONS_PER_APPLY,
    MAX_TYPED_REQUEST_FACTS,
    MAX_TYPED_REQUEST_BYTES,
    MAX_TYPED_STRING_BYTES,
    TypedRequestError,
    TypedRequestFact,
    materialize_typed_request,
    request_contract,
)
from .typed_operations import (
    DRAFT_TYPED_OPERATIONS,
    compound_child_operations,
    compound_child_request_contract,
    draft_operation_request_contract,
)


OPERATION_DRAFT_ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
OPERATION_COMPOSITION_CONTRACT = "waapi-skill.operation-composition/v1"
OPERATION_COMPOSER_CONTRACT = "waapi-skill.operation-composer/v1"
AUDIO_IMPORT_COMPOSER_OPERATION = "audio.import"
MAX_COMPOSER_ACTION_BYTES = 32 * 1024
# Schema-derived typed Draft facts may carry one Registry-authorized 64 KiB
# scalar plus the fixed action envelope. This does not widen the separate
# media-aware audio.import ceiling.
MAX_TYPED_COMPOSER_ACTION_BYTES = 72 * 1024
# A field projection this large leaves too little of the fixed 32 KiB agent
# output budget for the operation identity and the sole construction route.
# The same fields remain losslessly available through the shared compact table.
MAX_INLINE_COMPOSER_FIELD_PROJECTION_BYTES = 18 * 1024
_TYPED_FACT_HANDLE_PATTERN = re.compile(r"^tdh1-[0-9a-f]{24}$")
_GENERIC_TYPED_ACTION_FIELDS: dict[
    str, tuple[tuple[str, ...], tuple[str, ...]]
] = {
    "add_typed_fact": (
        ("fact_action", "field_handle"),
        ("value_type", "value", "key"),
    ),
    "correct_typed_fact": (
        (
            "fact_handle",
            "fact_action",
            "field_handle",
        ),
        ("value_type", "value", "key"),
    ),
    "remove_typed_fact": (("fact_handle",), ()),
}


def operation_draft_construction_boundary(
    *,
    read_only: bool = False,
) -> dict[str, Any]:
    """Describe the non-mutating phase and its required public terminal."""

    required_terminal = "draft_check_result" if read_only else "preview"
    return {
        "phase": (
            "read_request_construction" if read_only else "preview_construction"
        ),
        "mutation": False,
        "complete": False,
        "required_terminal": required_terminal,
        "before": "continue_no_confirm_no_end",
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
    empty_lists: Sequence[str] = (),
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
        if len(row) not in {2, 3}:
            raise OperationComposerError(
                "--event requires FIELD ACTION PATH or --event-path requires FIELD PATH."
            )
        field, *event_values = row
        if len(event_values) == 1:
            set_once(field, {"path": event_values[0]})
        else:
            event_action, path = event_values
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
    for field in empty_lists:
        set_once(field, [])

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


def parse_typed_action_cli_arguments(
    arguments: Sequence[str],
    *,
    legacy_compatibility: bool = False,
) -> dict[str, Any]:
    """Parse the closed variable-length ``draft-apply`` typed argv suffix.

    ``legacy_compatibility`` exists only for offline replay of already sealed
    evidence.  The public Gateway leaves it disabled so the old generic fact
    grammar cannot become a second normal model-facing input surface.
    """

    values: list[tuple[str, ...]] = []
    nulls: list[str] = []
    selectors: list[tuple[str, ...]] = []
    properties: list[tuple[str, ...]] = []
    references: list[tuple[str, ...]] = []
    events: list[tuple[str, ...]] = []
    assignments: list[tuple[str, ...]] = []
    empty_lists: list[str] = []
    if len(arguments) < 2 or arguments[0] != "--action":
        raise OperationComposerError(
            "Typed action argv must start with --action ACTION."
        )
    action_name = arguments[1]
    if action_name in _GENERIC_TYPED_ACTION_FIELDS:
        return _parse_generic_typed_action_cli_arguments(arguments)
    index = 2
    while index < len(arguments):
        flag = arguments[index]
        direct_action_fields = {
            ("add_target", "--name"): "name",
            ("add_target", "--notes"): "notes",
            ("add_target", "--platform"): "platform",
            ("add_target", "--list-mode"): "list_mode",
            ("add_target", "--on-name-conflict"): "on_name_conflict",
            ("set_property", "--target-handle"): "target_handle",
            ("remove_property", "--target-handle"): "target_handle",
            ("set_target_field", "--target-handle"): "target_handle",
            ("clear_target_field", "--target-handle"): "target_handle",
            ("remove_target", "--target-handle"): "target_handle",
            ("set_reference", "--owner-handle"): "owner_handle",
            ("remove_reference", "--owner-handle"): "owner_handle",
            ("add_child", "--parent-handle"): "parent_handle",
            ("add_child", "--type"): "type",
            ("add_child", "--name"): "name",
            ("add_list", "--target-handle"): "target_handle",
            ("set_node_field", "--node-handle"): "node_handle",
            ("clear_node_field", "--node-handle"): "node_handle",
            ("set_node_property", "--node-handle"): "node_handle",
            ("remove_node_property", "--node-handle"): "node_handle",
            ("remove_node", "--node-handle"): "node_handle",
            ("remove_list", "--list-handle"): "list_handle",
            ("add_list_member", "--list-handle"): "list_handle",
            ("add_list_member", "--type"): "type",
            ("add_list_member", "--name"): "name",
            ("add_import_file", "--owner-handle"): "owner_handle",
            ("add_import_file", "--audio-file"): "audio_file",
            ("add_import_file", "--audio-file-base64"): "audio_file_base64",
            ("add_import_file", "--originals-subfolder"): "originals_subfolder",
            ("add_import_file", "--language"): "language",
            ("add_import_file", "--object-type"): "object_type",
            ("set_import_file_field", "--file-handle"): "file_handle",
            ("clear_import_file_field", "--file-handle"): "file_handle",
            ("remove_import_file", "--file-handle"): "file_handle",
            ("set_import_option", "--owner-handle"): "owner_handle",
            ("clear_import_option", "--owner-handle"): "owner_handle",
            ("remove_import", "--owner-handle"): "owner_handle",
        }
        direct_action_field = direct_action_fields.get((action_name, flag))
        if direct_action_field is not None:
            row = _require_cli_argv_row(arguments, index, 2, flag)
            values.append((direct_action_field, "string", row[1]))
            index += 2
        elif flag == "--option":
            if action_name in {"set_request_option", "set_import_option"}:
                row = _require_cli_argv_row(arguments, index, 4, flag)
                values.extend((("name", "string", row[1]), ("value", row[2], row[3])))
                index += 4
            elif action_name in {"clear_request_option", "clear_import_option"}:
                row = _require_cli_argv_row(arguments, index, 2, flag)
                values.append(("name", "string", row[1]))
                index += 2
            else:
                raise OperationComposerError("--option is not valid for this typed action.")
        elif flag == "--list":
            if action_name != "add_list":
                raise OperationComposerError("--list is not valid for this typed action.")
            row = _require_cli_argv_row(arguments, index, 2, flag)
            values.append(("name", "string", row[1]))
            index += 2
        elif flag == "--field":
            if action_name in {
                "set_target_field",
                "set_node_field",
                "set_import_file_field",
            }:
                row = _require_cli_argv_row(arguments, index, 4, flag)
                values.extend(
                    (("name", "string", row[1]), ("value", row[2], row[3]))
                )
                index += 4
            elif action_name in {
                "clear_target_field",
                "clear_node_field",
                "clear_import_file_field",
            }:
                row = _require_cli_argv_row(arguments, index, 2, flag)
                values.append(("name", "string", row[1]))
                index += 2
            else:
                raise OperationComposerError(
                    "--field is not valid for this typed action."
                )
        elif flag == "--value":
            if not legacy_compatibility:
                raise OperationComposerError(
                    "--value is available only for sealed archive replay."
                )
            row = _require_cli_argv_row(arguments, index, 4, flag)
            values.append(row[1:])
            index += 4
        elif flag == "--null":
            if not legacy_compatibility:
                raise OperationComposerError(
                    "--null is available only for sealed archive replay."
                )
            row = _require_cli_argv_row(arguments, index, 2, flag)
            nulls.append(row[1])
            index += 2
        elif flag == "--property":
            property_field = {
                "add_target": "properties",
            }.get(action_name)
            if property_field is not None:
                legacy_field = (
                    legacy_compatibility
                    and index + 1 < len(arguments)
                    and arguments[index + 1] == property_field
                )
                row = _require_cli_argv_row(
                    arguments, index, 5 if legacy_field else 4, flag
                )
                properties.append(
                    tuple(row[1:])
                    if legacy_field
                    else (property_field, *row[1:])
                )
                index += len(row)
            elif action_name in {"set_property", "set_node_property"}:
                row = _require_cli_argv_row(arguments, index, 4, flag)
                values.extend((("name", "string", row[1]), ("value", row[2], row[3])))
                index += 4
            elif action_name in {"remove_property", "remove_node_property"}:
                row = _require_cli_argv_row(arguments, index, 2, flag)
                values.append(("name", "string", row[1]))
                index += 2
            else:
                raise OperationComposerError(
                    "--property is not valid for this typed action."
                )
        elif flag == "--target":
            if index + 2 > len(arguments):
                raise OperationComposerError("--target is incomplete.")
            target_field = {
                "add_target": "selector",
                "set_reference": "target",
            }.get(action_name)
            if target_field is None:
                raise OperationComposerError(
                    "--target is not valid for this typed action."
                )
            _selector, consumed = _parse_cli_selector(arguments[index + 1 :])
            end = index + 1 + consumed
            selectors.append((target_field, *arguments[index + 1 : end]))
            index = end
        elif flag == "--selector" and legacy_compatibility:
            if index + 3 > len(arguments):
                raise OperationComposerError("--selector is incomplete.")
            field = arguments[index + 1]
            _selector, consumed = _parse_cli_selector(arguments[index + 2 :])
            end = index + 2 + consumed
            selectors.append((field, *arguments[index + 2 : end]))
            index = end
        elif flag == "--reference":
            reference_field = {
                "add_target": "references",
            }.get(action_name)
            if reference_field is not None:
                legacy_field = (
                    legacy_compatibility
                    and index + 1 < len(arguments)
                    and arguments[index + 1] == reference_field
                )
                offset = 2 if legacy_field else 1
                if index + offset + 2 > len(arguments):
                    raise OperationComposerError("--reference is incomplete.")
                name = arguments[index + offset]
                _selector, consumed = _parse_cli_selector(
                    arguments[index + offset + 1 :]
                )
                end = index + offset + 1 + consumed
                references.append(
                    (
                        reference_field,
                        name,
                        *arguments[index + offset + 1 : end],
                    )
                )
                index = end
            elif action_name == "set_reference":
                if index + 3 > len(arguments):
                    raise OperationComposerError("--reference is incomplete.")
                name = arguments[index + 1]
                _selector, consumed = _parse_cli_selector(arguments[index + 2 :])
                end = index + 2 + consumed
                values.append(("name", "string", name))
                selectors.append(("target", *arguments[index + 2 : end]))
                index = end
            elif action_name == "remove_reference":
                row = _require_cli_argv_row(arguments, index, 2, flag)
                values.append(("name", "string", row[1]))
                index += 2
            else:
                raise OperationComposerError(
                    "--reference is not valid for this typed action."
                )
        else:
            raise OperationComposerError(
                "Typed action argv contains an unknown fact flag.",
                details={"flag": flag},
            )
    action = build_typed_action_from_cli(
        action_name,
        values=values,
        nulls=nulls,
        selectors=selectors,
        properties=properties,
        references=references,
        events=events,
        assignments=assignments,
        empty_lists=empty_lists,
    )
    if (
        action_name in {"set_import_option", "clear_import_option"}
        and "owner_handle" not in action
        and action.get("name")
        not in {
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        }
        and not legacy_compatibility
    ):
        raise OperationComposerError(
            "audio.import source-control option is not public.",
            details={"name": action.get("name")},
        )
    return action


def parse_typed_action_cli_argument_sequence(
    arguments: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Parse one or more ordered typed actions from one ``--facts`` suffix.

    Every action still starts with the existing ``--action`` marker.  Candidate
    boundaries are accepted only when both adjacent slices independently parse
    through the authoritative single-action grammar.  This keeps an option-like
    business value such as the literal ``--action`` unambiguous and avoids a
    second fact syntax.
    """

    tokens = tuple(arguments)
    if not tokens or tokens[0] != "--action":
        raise OperationComposerError(
            "Typed action argv must start with --action ACTION."
        )
    action_starts = tuple(
        index for index, token in enumerate(tokens) if token == "--action"
    )
    if len(action_starts) > MAX_TYPED_ACTIONS_PER_APPLY * 2:
        # Values may themselves equal ``--action``; allow one such value per
        # action while keeping the ambiguity search strictly bounded.
        raise OperationComposerError(
            "Typed action batch exceeds its fixed marker ceiling."
        )

    starts = (*action_starts, len(tokens))
    parses_by_start: dict[int, list[tuple[dict[str, Any], ...]]] = {}

    def parse_from(start: int) -> list[tuple[dict[str, Any], ...]]:
        cached = parses_by_start.get(start)
        if cached is not None:
            return cached
        results: list[tuple[dict[str, Any], ...]] = []
        start_position = action_starts.index(start)
        for end in starts[start_position + 1 :]:
            try:
                action = parse_typed_action_cli_arguments(tokens[start:end])
            except OperationComposerError:
                continue
            if end == len(tokens):
                results.append((action,))
            elif end in action_starts:
                for tail in parse_from(end):
                    candidate = (action, *tail)
                    if len(candidate) <= MAX_TYPED_ACTIONS_PER_APPLY:
                        results.append(candidate)
                    if len(results) > 1:
                        break
            if len(results) > 1:
                break
        parses_by_start[start] = results
        return results

    parses = parse_from(0)
    if not parses:
        raise OperationComposerError("Typed action batch is invalid.")
    if len(parses) != 1:
        raise OperationComposerError("Typed action batch boundaries are ambiguous.")
    if len(parses[0]) > MAX_TYPED_ACTIONS_PER_APPLY:
        raise OperationComposerError(
            "Typed action batch exceeds its fixed action ceiling."
        )
    return parses[0]


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
    if action_name in _GENERIC_TYPED_ACTION_FIELDS:
        required, optional = _GENERIC_TYPED_ACTION_FIELDS[action_name]
        _require_allowed_keys(
            action,
            required=("contract", "action", *required),
            optional=optional,
            label="generic typed action",
        )
        arguments: list[str] = ["--action", action_name]
        flag_by_field = {
            "fact_handle": "--fact-handle",
            "fact_action": "--fact-action",
            "field_handle": "--field-handle",
            "value_type": "--value-type",
            "value": "--fact-value",
            "key": "--key",
        }
        for field in (*required, *optional):
            if field in action:
                arguments.extend((flag_by_field[field], str(action[field])))
        return tuple(arguments)
    specialized = _specialized_typed_action_cli_arguments(action_name, action)
    if specialized is not None:
        return ("--action", action_name, *specialized)
    arguments: list[str] = ["--action", action_name]
    for field, value in action.items():
        if field in {"contract", "action"}:
            continue
        if value is None:
            arguments.extend(("--null", field))
        elif isinstance(value, Mapping) and "kind" in value:
            target_field = {
                "add_target": "selector",
                "set_reference": "target",
            }.get(action_name)
            if target_field != field:
                raise OperationComposerError(
                    "Typed selector is not valid for this action field."
                )
            arguments.extend(("--target", *_selector_cli_tokens(value)))
        elif isinstance(value, list):
            for descriptor in value:
                if not isinstance(descriptor, Mapping):
                    raise OperationComposerError("Typed descriptor list is invalid.")
                if set(descriptor) == {"name", "value"}:
                    if action_name != "add_target" or field != "properties":
                        raise OperationComposerError(
                            "Typed property is not valid for this action field."
                        )
                    value_type, raw_value = _scalar_cli_tokens(descriptor["value"])
                    arguments.extend(
                        (
                            "--property",
                            str(descriptor["name"]),
                            value_type,
                            raw_value,
                        )
                    )
                elif set(descriptor) == {"name", "target"} and isinstance(
                    descriptor["target"], Mapping
                ):
                    if action_name != "add_target" or field != "references":
                        raise OperationComposerError(
                            "Typed reference is not valid for this action field."
                        )
                    arguments.extend(
                        (
                            "--reference",
                            str(descriptor["name"]),
                            *_selector_cli_tokens(descriptor["target"]),
                        )
                    )
                else:
                    raise OperationComposerError("Typed descriptor is invalid.")
        else:
            value_type, raw_value = _scalar_cli_tokens(value)
            direct_action_flag = {
                ("add_target", "name"): "--name",
                ("add_target", "notes"): "--notes",
                ("add_target", "platform"): "--platform",
                ("add_target", "list_mode"): "--list-mode",
                ("add_target", "on_name_conflict"): "--on-name-conflict",
            }.get((action_name, field))
            if direct_action_flag is not None:
                if value_type != "string":
                    raise OperationComposerError(
                        "Typed action text fields must be strings."
                    )
                arguments.extend((direct_action_flag, raw_value))
            else:
                arguments.extend(("--value", field, value_type, raw_value))
    return tuple(arguments)


def _specialized_typed_action_cli_arguments(
    action_name: str,
    action: Mapping[str, Any],
) -> tuple[str, ...] | None:
    """Serialize normal action-specific flags; generic facts stay archive-only."""

    def text(field: str) -> str:
        value = action.get(field)
        if not isinstance(value, str):
            raise OperationComposerError(
                f"Typed action field {field!r} must be a string."
            )
        return value

    def scalar(field: str) -> tuple[str, str]:
        return _scalar_cli_tokens(action.get(field))

    compound = {
        "set_request_option": (None, "--option"),
        "set_import_option": (
            "--owner-handle" if "owner_handle" in action else None,
            "--option",
        ),
        "set_target_field": ("--target-handle", "--field"),
        "set_node_field": ("--node-handle", "--field"),
        "set_import_file_field": ("--file-handle", "--field"),
        "set_property": ("--target-handle", "--property"),
        "set_node_property": ("--node-handle", "--property"),
    }
    if action_name in compound:
        handle_flag, fact_flag = compound[action_name]
        result: list[str] = []
        if handle_flag is not None:
            handle_field = {
                "--owner-handle": "owner_handle",
                "--target-handle": "target_handle",
                "--node-handle": "node_handle",
                "--file-handle": "file_handle",
            }[handle_flag]
            result.extend((handle_flag, text(handle_field)))
        value = action.get("value")
        value_type, raw_value = scalar("value")
        result.extend((fact_flag, text("name"), value_type, raw_value))
        return tuple(result)

    clearing = {
        "clear_request_option": (None, "--option"),
        "clear_import_option": (
            "--owner-handle" if "owner_handle" in action else None,
            "--option",
        ),
        "clear_target_field": ("--target-handle", "--field"),
        "clear_node_field": ("--node-handle", "--field"),
        "clear_import_file_field": ("--file-handle", "--field"),
        "remove_property": ("--target-handle", "--property"),
        "remove_node_property": ("--node-handle", "--property"),
        "remove_reference": ("--owner-handle", "--reference"),
    }
    if action_name in clearing:
        handle_flag, fact_flag = clearing[action_name]
        result = []
        if handle_flag is not None:
            handle_field = {
                "--owner-handle": "owner_handle",
                "--target-handle": "target_handle",
                "--node-handle": "node_handle",
                "--file-handle": "file_handle",
            }[handle_flag]
            result.extend((handle_flag, text(handle_field)))
        result.extend((fact_flag, text("name")))
        return tuple(result)

    if action_name == "set_reference":
        return (
            "--owner-handle",
            text("owner_handle"),
            "--reference",
            text("name"),
            *_selector_cli_tokens(action.get("target")),
        )

    simple_fields = {
        "add_child": (
            ("--parent-handle", "parent_handle"),
            ("--type", "type"),
            ("--name", "name"),
        ),
        "add_list": (
            ("--target-handle", "target_handle"),
            ("--list", "name"),
        ),
        "add_list_member": (
            ("--list-handle", "list_handle"),
            ("--type", "type"),
            ("--name", "name"),
        ),
        "remove_target": (("--target-handle", "target_handle"),),
        "remove_node": (("--node-handle", "node_handle"),),
        "remove_list": (("--list-handle", "list_handle"),),
        "remove_import_file": (("--file-handle", "file_handle"),),
        "remove_import": (("--owner-handle", "owner_handle"),),
    }
    if action_name in simple_fields:
        return tuple(
            token
            for flag, field in simple_fields[action_name]
            for token in (flag, text(field))
        )

    if action_name == "add_import_file":
        flag_by_field = {
            "audio_file": "--audio-file",
            "audio_file_base64": "--audio-file-base64",
            "originals_subfolder": "--originals-subfolder",
            "language": "--language",
            "object_type": "--object-type",
        }
        result = ["--owner-handle", text("owner_handle")]
        for field, flag in flag_by_field.items():
            if field in action:
                result.extend((flag, text(field)))
        return tuple(result)
    return None


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
    if kind in {"id", "id-string", "id-integer", "path"}:
        if len(tokens) < 2:
            raise OperationComposerError(f"{kind} selector requires VALUE.")
        if kind == "id-integer":
            raw_value = tokens[1]
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw_value):
                raise OperationComposerError(
                    "id-integer selector values must use canonical decimal syntax."
                )
            return {"kind": "id", "value": int(raw_value)}, 2
        if kind == "id-string":
            return {"kind": "id", "value": tokens[1]}, 2
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
    if kind == "id" and set(selector) == {"kind", "value"}:
        value = selector["value"]
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise OperationComposerError("Typed id selector value is invalid.")
        return (
            "id-integer" if isinstance(value, int) else "id-string",
            str(value),
        )
    if kind == "path" and set(selector) == {"kind", "value"}:
        return "path", str(selector["value"])
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


def _metadata_query_batch_contract(
    *, include_limit_discipline: bool = False
) -> dict[str, Any]:
    """Describe the one scoped discovery batch used before one Draft."""

    contract: dict[str, Any] = {
        "scope": "one exact object, class, or object-type scope",
        **(
            {
                "reconcile_before_command": (
                    "list every requested property/reference assignment across rows; "
                    "require equal distinct checklist and --query counts; one-row "
                    "Volume and OutputBus still count"
                ),
                "business_fact_inventory": (
                    "count every requested toggle, mode, scalar, and reference as "
                    "one distinct checklist item even when one query could return "
                    "several candidates"
                ),
                "paired_setting_discipline": {
                    "loop_enabled_and_infinite_mode": (
                        "two distinct checklist items"
                    ),
                    "ignore_parent_enable_self_and_maximum_value": (
                        "three distinct checklist items"
                    ),
                },
            }
            if include_limit_discipline
            else {}
        ),
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
        "partial_fallback": (
            "one broader retry only when explicitly reported partial"
        ),
    }
    if include_limit_discipline:
        contract["limit_by_query_count"] = metadata_candidate_limit_contract()
        contract["required_final_argv"] = [
            "--limit",
            "<derived-from-query-count>",
        ]
    return contract


def _metadata_workflow_control() -> dict[str, str | bool]:
    """Keep operation-scoped discovery inside the same construction turn."""

    return {
        "metadata_success_is_terminal": False,
        "continue_same_turn_after_metadata": "draft-start",
        "reply_before_draft_start": "invalid",
    }


def _metadata_activation_decision() -> dict[str, str]:
    """Distinguish live token reuse from required live discovery."""

    return {
        "run_metadata_when": (
            "one_or_more_required_tokens_lack_prior_successful_live_result"
        ),
        "skip_metadata_when": (
            "every_required_token_has_prior_successful_live_result"
        ),
        "live_token_proof": "successful_metadata_discover_only",
        "when_skipped_continue_same_turn_with": "draft-start",
    }


def operation_composer_contract(operation: str, version: str) -> dict[str, Any]:
    """Return one reviewed Adapter contract, derived from the Registry."""

    if operation_uses_business_declaration(operation, version):
        raise OperationComposerError(
            f"No shallow Operation Composer Adapter is available for {operation!r}.",
            error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
            details={"operation": operation, "version": version},
        )

    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        typed = (
            compound_child_request_contract(operation, version)
            if operation in compound_child_operations(version)
            else request_contract(version, operation)
            if operation.startswith("ak.")
            else draft_operation_request_contract(operation, version)
        )
        if typed.as_gateway_payload()["input_shape"] != "draft":
            raise OperationComposerError(
                f"No Operation Composer Adapter is available for {operation!r}.",
                error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
                details={"operation": operation, "version": version},
            )
        gateway_field_payloads = typed.gateway_field_payloads()
        field_payloads: list[dict[str, Any]] = []
        for field in gateway_field_payloads:
            public_field = dict(field)
            public_field.pop("fact_construction", None)
            field_payloads.append(public_field)
        compact_field_table = len(canonical_json_bytes(field_payloads)) > (
            MAX_INLINE_COMPOSER_FIELD_PROJECTION_BYTES
        )
        top_level_fact_plan = typed.top_level_fact_plan()
        if compact_field_table:
            top_level_fact_plan = {
                key: value
                for key, value in top_level_fact_plan.items()
                if key
                not in {
                    "branch_fact_expansion",
                    "business_fact_selection",
                    "business_pointer_source",
                    "fact_batching",
                }
            }
        if operation == "soundbank.generate":
            top_level_fact_plan = {
                **top_level_fact_plan,
                "explicit_false_controls": {
                    "rebuild_soundbanks": "do_not_rebuild_all_soundbanks",
                    "clear_audio_file_cache": "do_not_clear_audio_file_cache",
                    "rebuild_init_bank": "do_not_rebuild_init_bank",
                    "prompt_present_false_is_not_omitted_as_default": True,
                    "batch_with_every_remaining_complete_top_level_fact": True,
                },
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
            "action_shapes": {
                name: {
                    "fixed_fields": {
                        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                        "action": name,
                    },
                    "required_fields": list(required),
                    "optional_fields": list(optional),
                }
                for name, (required, optional) in _GENERIC_TYPED_ACTION_FIELDS.items()
            },
            "composition_contract": OPERATION_COMPOSITION_CONTRACT,
            "actions": list(_GENERIC_TYPED_ACTION_FIELDS),
            "limits": {
                "facts": MAX_TYPED_REQUEST_FACTS,
                "array_items": MAX_TYPED_ARRAY_ITEMS,
                "string_utf8_bytes": MAX_TYPED_STRING_BYTES,
                "canonical_request_bytes": MAX_TYPED_REQUEST_BYTES,
                "action_bytes": MAX_TYPED_COMPOSER_ACTION_BYTES,
            },
            "typed_request_schema_digest": typed.schema_digest,
            "construction_order": typed.gateway_construction_order(),
            "top_level_fact_plan": top_level_fact_plan,
            **(
                {
                    "typed_request_field_table": typed.gateway_field_table(
                        direct_actions_override=False,
                        include_fact_construction=False,
                    )
                }
                if compact_field_table
                else {"typed_request_fields": field_payloads}
            ),
            "complete_request_is_never_an_action": True,
            "completion_discipline": {
                "successful_action_response_is_complete": True,
                "compact_projection_is_not_truncation": True,
                "schema_required_fields_status_scope": (
                    "structural_preview_readiness_only"
                ),
                "construction_boundary": operation_draft_construction_boundary(),
            },
        }

    raise OperationComposerError(
        f"No Operation Composer Adapter is available for {operation!r}.",
        error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
        details={"operation": operation, "version": version},
    )


def operation_composer_digest(operation: str, version: str) -> str:
    if operation == AUDIO_IMPORT_COMPOSER_OPERATION:
        return canonical_sha256(
            {
                "contract": "waapi-skill.audio-import-draft-binding/v1",
                "business_adapter": audio_import_business_contract(version),
            }
        )
    if operation_uses_business_declaration(operation, version):
        return canonical_sha256(
            {
                "contract": "waapi-skill.business-draft-binding/v1",
                "business_adapter": operation_business_contract(
                    operation,
                    version,
                ),
            }
        )
    return canonical_sha256(operation_composer_contract(operation, version))


def _typed_contract_is_flat(contract: Any) -> bool:
    by_handle = contract.fields_by_handle
    for field in contract.fields:
        if field.shape in {"object", "map"}:
            return False
        if field.parent_handle is not None:
            parent = by_handle.get(field.parent_handle)
            if parent is None or parent.shape != "branch":
                return False
        if field.shape == "array" and any(
            variant.get("type") in {"object", "array"}
            for variant in field.variants
        ):
            return False
    return True


def _typed_request_error_is_incomplete(message: str) -> bool:
    return (
        (message.startswith("Required field ") and message.endswith(" is missing"))
        or (
            message.startswith("Required field ")
            and message.endswith(" branch is missing")
        )
        or (
            message.startswith("Typed object ")
            and " is missing required keys" in message
        )
        or (message.startswith("Field ") and " requires at least " in message)
    )


def _parse_generic_typed_action_cli_arguments(
    arguments: Sequence[str],
) -> dict[str, Any]:
    action_name = arguments[1]
    required, optional = _GENERIC_TYPED_ACTION_FIELDS[action_name]
    field_by_flag = {
        "--fact-handle": "fact_handle",
        "--fact-action": "fact_action",
        "--field-handle": "field_handle",
        "--value-type": "value_type",
        "--fact-value": "value",
        "--key": "key",
    }
    action: dict[str, Any] = {
        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
        "action": action_name,
    }
    index = 2
    while index < len(arguments):
        flag = arguments[index]
        field = field_by_flag.get(flag)
        if field is None or index + 1 >= len(arguments):
            raise OperationComposerError(
                "Generic typed action contains an unknown or incomplete flag.",
                details={"flag": flag},
            )
        if field in action:
            raise OperationComposerError("Generic typed action fields must be unique.")
        action[field] = arguments[index + 1]
        index += 2
    _require_allowed_keys(
        action,
        required=("contract", "action", *required),
        optional=optional,
        label="generic typed action",
    )
    return action


def _new_typed_fact_handle() -> str:
    return f"tdh1-{secrets.token_hex(12)}"


def _normalize_generic_typed_composition(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    _require_json_object(composition, label="composition")
    _require_exact_keys(
        composition,
        required=("contract", "typed_request_schema_digest", "facts"),
        label="generic typed composition",
    )
    if composition.get("contract") != OPERATION_COMPOSITION_CONTRACT:
        raise OperationComposerError("Operation Draft composition contract is invalid.")
    contract = (
        draft_operation_request_contract(operation, version)
        if operation in DRAFT_TYPED_OPERATIONS
        else compound_child_request_contract(operation, version)
        if operation in compound_child_operations(version)
        else request_contract(version, operation)
    )
    if composition.get("typed_request_schema_digest") != contract.schema_digest:
        raise OperationComposerError("Typed request schema digest is stale.")
    raw_facts = composition.get("facts")
    if not isinstance(raw_facts, list) or len(raw_facts) > MAX_TYPED_REQUEST_FACTS:
        raise OperationComposerError("Generic typed fact count exceeds its ceiling.")
    facts: list[dict[str, Any]] = []
    handles: set[str] = set()
    for raw_fact in raw_facts:
        _require_json_object(raw_fact, label="typed fact")
        _require_allowed_keys(
            raw_fact,
            required=(
                "handle",
                "fact_action",
                "field_handle",
                "value_type",
                "value",
            ),
            optional=("key",),
            label="typed fact",
        )
        handle = raw_fact.get("handle")
        if (
            not isinstance(handle, str)
            or _TYPED_FACT_HANDLE_PATTERN.fullmatch(handle) is None
            or handle in handles
        ):
            raise OperationComposerError("Generic typed fact handle is invalid.")
        handles.add(handle)
        normalized = dict(raw_fact)
        for field in ("fact_action", "field_handle", "value_type", "value"):
            if not isinstance(normalized.get(field), str):
                raise OperationComposerError(
                    f"Generic typed fact {field!r} must be a string."
                )
        if "key" in normalized and not isinstance(normalized["key"], str):
            raise OperationComposerError("Generic typed fact key must be a string.")
        facts.append(normalized)
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "typed_request_schema_digest": contract.schema_digest,
        "facts": facts,
    }


def _apply_generic_typed_action(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
    action: Mapping[str, Any],
    *,
    handle_factory: Callable[[], str] | None,
    allow_cleaned_file_evidence: bool = False,
) -> tuple[dict[str, Any], str]:
    normalized = _normalize_generic_typed_composition(
        operation, version, composition
    )
    _require_json_object(action, label="action")
    try:
        action_size = len(canonical_json_bytes(dict(action)))
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise OperationComposerError(
            "Generic typed Draft action must be strict JSON."
        ) from exc
    if action_size > MAX_TYPED_COMPOSER_ACTION_BYTES:
        raise OperationComposerError(
            "Generic typed Draft action exceeds its fixed byte ceiling.",
            details={
                "size_bytes": action_size,
                "limit_bytes": MAX_TYPED_COMPOSER_ACTION_BYTES,
            },
        )
    if action.get("contract") != OPERATION_DRAFT_ACTION_CONTRACT:
        raise OperationComposerError(
            f"action contract must be {OPERATION_DRAFT_ACTION_CONTRACT!r}."
        )
    action_name = action.get("action")
    if action_name not in _GENERIC_TYPED_ACTION_FIELDS:
        raise OperationComposerError("Generic typed Draft action is unsupported.")
    required, optional = _GENERIC_TYPED_ACTION_FIELDS[str(action_name)]
    _require_allowed_keys(
        action,
        required=("contract", "action", *required),
        optional=optional,
        label="generic typed action",
    )
    facts = [dict(fact) for fact in normalized["facts"]]
    if action_name == "remove_typed_fact":
        fact_handle = action.get("fact_handle")
        matches = [index for index, fact in enumerate(facts) if fact["handle"] == fact_handle]
        if len(matches) != 1:
            raise OperationComposerError("fact_handle does not name a current typed fact.")
        facts.pop(matches[0])
        affected_handle = str(fact_handle)
    else:
        fact_payload = {
            field: action[field]
            for field in ("fact_action", "field_handle", "value_type", "value", "key")
            if field in action
        }
        for field, value in fact_payload.items():
            if not isinstance(value, str):
                raise OperationComposerError(
                    f"Generic typed action field {field!r} must be a string."
                )
        fact_action = fact_payload.get("fact_action")
        field_handle = fact_payload.get("field_handle")
        if not isinstance(fact_action, str) or not isinstance(field_handle, str):
            raise OperationComposerError(
                "Generic typed action requires fact_action and field_handle."
            )
        supplied = set(fact_payload) - {"fact_action", "field_handle"}
        required_by_fact_action = {
            "set": {"value_type", "value"},
            "append": {"value_type", "value"},
            "present": set(),
            "choose": {"value"},
            "choose-dynamic": {"key", "value"},
            "map-put": {"key", "value_type", "value"},
        }
        expected = required_by_fact_action.get(fact_action)
        if expected is None or supplied != expected:
            raise OperationComposerError(
                "Generic typed fact fields do not match the selected fact action.",
                details={
                    "fact_action": fact_action,
                    "required": sorted(expected or ()),
                    "supplied": sorted(supplied),
                },
            )
        if fact_action == "present":
            fact_payload.update({"value_type": "null", "value": "null"})
        elif fact_action == "choose":
            fact_payload["value_type"] = "branch"
        elif fact_action == "choose-dynamic":
            fact_payload["value_type"] = "choice"
        if action_name == "add_typed_fact":
            affected_handle = (
                handle_factory() if handle_factory is not None else _new_typed_fact_handle()
            )
            if (
                not isinstance(affected_handle, str)
                or _TYPED_FACT_HANDLE_PATTERN.fullmatch(affected_handle) is None
                or any(fact["handle"] == affected_handle for fact in facts)
            ):
                raise OperationComposerError("Generated typed fact handle is invalid.")
            facts.append({"handle": affected_handle, **fact_payload})
        else:
            fact_handle = action.get("fact_handle")
            matches = [index for index, fact in enumerate(facts) if fact["handle"] == fact_handle]
            if len(matches) != 1:
                raise OperationComposerError("fact_handle does not name a current typed fact.")
            affected_handle = str(fact_handle)
            facts[matches[0]] = {"handle": affected_handle, **fact_payload}
    candidate = {**normalized, "facts": facts}
    # Run the Core whenever the Draft is complete. Incomplete intermediate
    # revisions remain editable, while malformed supplied facts still fail
    # before any durable write.
    try:
        materialize_operation_request(
            operation,
            version,
            candidate,
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )
    except OperationComposerError as exc:
        if exc.error_code != "OPERATION_DRAFT_INCOMPLETE":
            raise
    return candidate, str(action_name)


def new_composition(operation: str, version: str) -> dict[str, Any]:
    if operation_uses_business_declaration(operation, version):
        operation_business_contract(operation, version)
        return {"contract": OPERATION_COMPOSITION_CONTRACT}
    contract = operation_composer_contract(operation, version)
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        return {
            "contract": OPERATION_COMPOSITION_CONTRACT,
            "typed_request_schema_digest": contract["typed_request_schema_digest"],
            "facts": [],
        }
    raise OperationComposerError(
        f"No Operation Composer Adapter is available for {operation!r}.",
        error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
        details={"operation": operation, "version": version},
    )


def apply_composer_action(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
    action: Mapping[str, Any],
    *,
    handle_factory: Callable[[], str] | None = None,
    allow_cleaned_file_evidence: bool = False,
) -> tuple[dict[str, Any], str]:
    """Validate and apply one closed action without mutating the input mapping."""

    operation_composer_contract(operation, version)
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        return _apply_generic_typed_action(
            operation,
            version,
            composition,
            action,
            handle_factory=handle_factory,
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )
    raise OperationComposerError(
        f"No Operation Composer Adapter is available for {operation!r}.",
        error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
        details={"operation": operation, "version": version},
    )
def materialize_operation_request(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
    *,
    allow_cleaned_file_evidence: bool = False,
) -> dict[str, Any]:
    """Build and canonically reparse the complete operation request."""

    if not isinstance(allow_cleaned_file_evidence, bool):
        raise TypeError("allow_cleaned_file_evidence must be a boolean")

    normalized = _normalize_composition(composition, operation=operation, version=version)
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        typed = (
            compound_child_request_contract(operation, version)
            if operation in compound_child_operations(version)
            else request_contract(version, operation)
            if operation.startswith("ak.")
            else draft_operation_request_contract(operation, version)
        )
        try:
            materialized = materialize_typed_request(
                typed,
                schema_digest=normalized["typed_request_schema_digest"],
                facts=tuple(
                    TypedRequestFact(
                        fact["fact_action"],
                        fact["field_handle"],
                        fact["value_type"],
                        fact["value"],
                        key=fact.get("key"),
                    )
                    for fact in normalized["facts"]
                ),
            )
        except TypedRequestError as exc:
            raise OperationComposerError(
                str(exc),
                error_code=(
                    "OPERATION_DRAFT_INCOMPLETE"
                    if _typed_request_error_is_incomplete(str(exc))
                    else "OPERATION_DRAFT_ACTION_INVALID"
                ),
            ) from exc
        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": "waapi.call" if operation.startswith("ak.") else operation,
            "arguments": (
                {
                    "api": operation,
                    "args": dict(materialized.args),
                    "options": dict(materialized.options),
                }
                if operation.startswith("ak.")
                else dict(materialized.args)
            ),
        }
        if operation in DRAFT_TYPED_OPERATIONS:
            try:
                return parse_operation_request(request, expected_version=version).as_dict()
            except OperationContractError as exc:
                raise OperationComposerError(
                    str(exc), details=exc.details, error_code=exc.error_code
                ) from exc
        return request
    if operation_uses_business_declaration(operation, version):
        raise OperationComposerError(
            f"{operation} Business Declarations require the production semantic compiler.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
            details={"missing_fields": ["compiled_business_plan"]},
        )
    raise OperationComposerError(
        f"No Operation Composer Adapter is available for {operation!r}.",
        error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
        details={"operation": operation, "version": version},
    )
def composition_projection(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
    *,
    allow_cleaned_file_evidence: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_composition(composition, operation=operation, version=version)
    if operation_uses_business_declaration(operation, version):
        return _business_composition_projection(
            normalized,
            operation=operation,
        )
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        missing: list[str] = []
        try:
            materialize_operation_request(
                operation,
                version,
                normalized,
                allow_cleaned_file_evidence=allow_cleaned_file_evidence,
            )
        except OperationComposerError as exc:
            if exc.error_code != "OPERATION_DRAFT_INCOMPLETE":
                raise
            missing.append("complete_typed_request")
        return {
            "current_facts": [dict(fact) for fact in normalized["facts"]],
            "missing_fields": missing,
            "missing_fields_status": "complete" if not missing else "incomplete",
            "allowed_actions": [
                *operation_composer_contract(operation, version)["actions"],
                "check",
                "inspect",
                "cancel",
            ],
        }
    raise OperationComposerError(
        f"No Operation Composer Adapter is available for {operation!r}.",
        error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
        details={"operation": operation, "version": version},
    )
def operation_draft_public_projection(
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate appendable Composer actions from Draft lifecycle commands."""

    projected = dict(projection)
    raw_allowed_actions = projected.get("allowed_actions")
    if not isinstance(raw_allowed_actions, list):
        return projected
    lifecycle_commands = {
        "check": "draft-check",
        "inspect": "draft-inspect",
        "cancel": "draft-cancel",
        "preview-from-draft": "preview-from-draft",
    }
    projected["allowed_actions"] = [
        action
        for action in raw_allowed_actions
        if action not in lifecycle_commands
    ]
    projected["allowed_lifecycle_commands"] = [
        lifecycle_commands[action]
        for action in raw_allowed_actions
        if action in lifecycle_commands
    ]
    return projected


def _normalize_composition(
    composition: Mapping[str, Any],
    *,
    operation: str,
    version: str,
) -> dict[str, Any]:
    if operation_uses_business_declaration(operation, version):
        return _normalize_business_composition(
            composition,
            operation=operation,
            version=version,
        )
    operation_composer_contract(operation, version)
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        return _normalize_generic_typed_composition(
            operation, version, composition
        )
    raise OperationComposerError(
        f"No Operation Composer Adapter is available for {operation!r}.",
        error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
        details={"operation": operation, "version": version},
    )


def _normalize_business_composition(
    composition: Mapping[str, Any],
    *,
    operation: str = AUDIO_IMPORT_COMPOSER_OPERATION,
    version: str,
) -> dict[str, Any]:
    """Normalize one production Business Declaration state."""

    operation_business_contract(operation, version)
    _require_json_object(composition, label="composition")
    if set(composition) - {"contract", "business_session"}:
        raise OperationComposerError(
            f"{operation} business composition fields are invalid."
        )
    if composition.get("contract") != OPERATION_COMPOSITION_CONTRACT:
        raise OperationComposerError(
            "Operation Draft composition contract is invalid."
        )
    raw_session = composition.get("business_session")
    if raw_session is None:
        return {"contract": OPERATION_COMPOSITION_CONTRACT}
    try:
        session = BusinessDeclarationSession.from_dict(raw_session).as_dict()
    except (TypeError, ValueError) as exc:
        raise OperationComposerError(
            f"{operation} business declaration state is invalid."
        ) from exc
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "business_session": session,
    }


def _business_composition_projection(
    composition: Mapping[str, Any],
    *,
    operation: str = AUDIO_IMPORT_COMPOSER_OPERATION,
) -> dict[str, Any]:
    """Project only the current deep business state; no legacy action grammar."""

    raw_session = composition.get("business_session")
    if raw_session is None:
        return {
            "business_revision": 0,
            "declarations": [],
            "preview": None,
            "detail_available": False,
            "missing_fields": ["business_declaration"],
            "missing_fields_status": "incomplete",
            "allowed_actions": business_adapter(operation).projection_actions(
                session_bound=False
            ),
        }
    session = BusinessDeclarationSession.from_dict(raw_session)
    adapter = business_adapter(operation)
    complete = adapter.is_complete(session)
    return {
        "business_revision": session.revision,
        "declarations": [row.as_dict() for row in session.declarations],
        "preview": (
            None
            if session.active_preview is None
            else session.active_preview.readable_projection()
        ),
        "detail_available": session.active_preview is not None,
        "missing_fields": [] if complete else ["business_declaration"],
        "missing_fields_status": (
            "complete" if complete else "incomplete"
        ),
        "allowed_actions": adapter.projection_actions(
            session_bound=True
        ),
    }


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
    "MAX_TYPED_ACTIONS_PER_APPLY",
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

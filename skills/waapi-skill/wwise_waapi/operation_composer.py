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
from .builders.common import SemanticValidationError
from .metadata_discovery import metadata_candidate_limit_contract
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
OBJECT_SET_COMPOSER_OPERATION = "object.set"
AUDIO_IMPORT_COMPOSER_OPERATION = "audio.import"
MAX_COMPOSER_ACTION_BYTES = 32 * 1024
# Schema-derived typed Draft facts may carry one Registry-authorized 64 KiB
# scalar plus the fixed action envelope.  This does not widen object.set's
# bespoke action surface or audio.import's separate media-aware ceiling.
MAX_TYPED_COMPOSER_ACTION_BYTES = 72 * 1024
MAX_AUDIO_IMPORT_COMPOSER_ACTION_BYTES = 384 * 1024
# A field projection this large leaves too little of the fixed 32 KiB agent
# output budget for the operation identity and the sole construction route.
# The same fields remain losslessly available through the shared compact table.
MAX_INLINE_COMPOSER_FIELD_PROJECTION_BYTES = 18 * 1024
_TARGET_HANDLE_PATTERN = re.compile(r"^odh1-[0-9a-f]{24}$")
_TYPED_FACT_HANDLE_PATTERN = re.compile(r"^tdh1-[0-9a-f]{24}$")
_UNDO_CHILD_HANDLE_PATTERN = re.compile(r"^uch1-[0-9a-f]{24}$")
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


_UNDO_GROUP_ACTION_FIELDS: dict[
    str, tuple[tuple[str, ...], tuple[str, ...]]
] = {
    "set_display_name": (("display_name",), ()),
    "add_child_call": (("child_operation",), ()),
    "add_child_typed_fact": (
        ("child_handle", "fact_action", "field_handle"),
        ("value_type", "value", "key"),
    ),
    "correct_child_typed_fact": (
        ("child_handle", "fact_handle", "fact_action", "field_handle"),
        ("value_type", "value", "key"),
    ),
    "remove_child_typed_fact": (("child_handle", "fact_handle"), ()),
    "remove_child_call": (("child_handle",), ()),
}
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
    "set_import_operation": (("mode",), ()),
    "set_import_option": (("name", "value"), ()),
    "clear_import_option": (("name",), ()),
    "set_import_default": (("name", "value"), ()),
    "clear_import_default": (("name",), ()),
    "add_import_row": (
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
    if action_name in _UNDO_GROUP_ACTION_FIELDS:
        return _parse_undo_group_action_cli_arguments(arguments)
    if action_name in _GENERIC_TYPED_ACTION_FIELDS:
        return _parse_generic_typed_action_cli_arguments(arguments)
    index = 2
    while index < len(arguments):
        flag = arguments[index]
        direct_import_row_fields = {
            "--object-path": "object_path",
            "--audio-file": "audio_file",
            "--audio-file-base64": "audio_file_base64",
            "--audio-source-notes": "audio_source_notes",
            "--dialogue-event": "dialogue_event",
            "--import-language": "import_language",
            "--notes": "notes",
            "--object-type": "object_type",
            "--originals-subfolder": "originals_subfolder",
        }
        direct_action_fields = {
            ("add_target", "--name"): "name",
            ("add_target", "--notes"): "notes",
            ("add_target", "--platform"): "platform",
            ("add_target", "--list-mode"): "list_mode",
            ("add_target", "--on-name-conflict"): "on_name_conflict",
            ("assign_import_row_switch", "--import-handle"): "import_handle",
            ("assign_import_row_switch", "--switch"): "switch",
            ("set_import_operation", "--mode"): "mode",
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
            ("set_import_row_field", "--import-handle"): "import_handle",
            ("clear_import_row_field", "--import-handle"): "import_handle",
            ("remove_import_row", "--import-handle"): "import_handle",
        }
        direct_action_field = direct_action_fields.get((action_name, flag))
        if direct_action_field is not None:
            row = _require_cli_argv_row(arguments, index, 2, flag)
            values.append((direct_action_field, "string", row[1]))
            index += 2
        elif flag in direct_import_row_fields:
            import_file_fields = {
                "--audio-file": "audio_file",
                "--audio-file-base64": "audio_file_base64",
                "--originals-subfolder": "originals_subfolder",
                "--object-type": "object_type",
                "--import-language": "language",
            }
            if action_name == "add_import_row":
                field_name = direct_import_row_fields[flag]
            elif action_name == "add_import_file" and flag in import_file_fields:
                field_name = import_file_fields[flag]
            else:
                raise OperationComposerError(
                    f"{flag} is not valid for this typed action."
                )
            row = _require_cli_argv_row(arguments, index, 2, flag)
            values.append((field_name, "string", row[1]))
            index += 2
        elif flag == "--import-location":
            if action_name == "add_import_row":
                selector_field = "import_location"
            elif action_name in {"set_import_default", "set_import_row_field"}:
                selector_field = "value"
                values.append(("name", "string", "import_location"))
            else:
                raise OperationComposerError(
                    "--import-location is not valid for this typed action."
                )
            if index + 2 > len(arguments):
                raise OperationComposerError("--import-location is incomplete.")
            _selector, consumed = _parse_cli_selector(arguments[index + 1 :])
            end = index + 1 + consumed
            selectors.append((selector_field, *arguments[index + 1 : end]))
            index = end
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
        elif flag == "--default":
            if action_name == "set_import_default":
                row = _require_cli_argv_row(arguments, index, 4, flag)
                values.extend(
                    (("name", "string", row[1]), ("value", row[2], row[3]))
                )
                index += 4
            elif action_name == "clear_import_default":
                row = _require_cli_argv_row(arguments, index, 2, flag)
                values.append(("name", "string", row[1]))
                index += 2
            else:
                raise OperationComposerError(
                    "--default is not valid for this typed action."
                )
        elif flag == "--field":
            if action_name in {
                "set_target_field",
                "set_node_field",
                "set_import_file_field",
                "set_import_row_field",
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
                "clear_import_row_field",
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
                "add_import_row": "properties",
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
            elif action_name in {"set_import_default", "set_import_row_field"}:
                row = _require_cli_argv_row(arguments, index, 4, flag)
                if not any(value_row[0] == "name" for value_row in values):
                    values.append(("name", "string", "properties"))
                properties.append(("value", *row[1:]))
                index += 4
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
        elif flag in {"--empty-properties", "--empty-references"}:
            field_name = flag.removeprefix("--empty-")
            if action_name == "add_import_row":
                empty_lists.append(field_name)
            elif action_name in {"set_import_default", "set_import_row_field"}:
                values.append(("name", "string", field_name))
                empty_lists.append("value")
            else:
                raise OperationComposerError(
                    f"{flag} is not valid for this typed action."
                )
            index += 1
        elif flag == "--event":
            if action_name == "add_import_row":
                legacy_field = (
                    legacy_compatibility
                    and index + 1 < len(arguments)
                    and arguments[index + 1] == "event"
                )
                row = _require_cli_argv_row(
                    arguments, index, 4 if legacy_field else 3, flag
                )
                events.append(
                    tuple(row[1:]) if legacy_field else ("event", *row[1:])
                )
                index += len(row)
            elif action_name == "set_import_default":
                row = _require_cli_argv_row(arguments, index, 3, flag)
                values.append(("name", "string", "event"))
                events.append(("value", *row[1:]))
                index += 3
            elif action_name == "set_import_row_field":
                legacy_field = (
                    legacy_compatibility
                    and index + 1 < len(arguments)
                    and arguments[index + 1] == "event"
                )
                row = _require_cli_argv_row(
                    arguments, index, 4 if legacy_field else 3, flag
                )
                values.append(("name", "string", "event"))
                offset = 2 if legacy_field else 1
                events.append(("value", row[offset], row[offset + 1]))
                index += len(row)
            else:
                raise OperationComposerError(
                    "--event is not valid for this typed action."
                )
        elif flag == "--event-path":
            row = _require_cli_argv_row(arguments, index, 2, flag)
            if action_name == "add_import_row":
                events.append(("event", row[1]))
            elif action_name in {"set_import_default", "set_import_row_field"}:
                values.append(("name", "string", "event"))
                events.append(("value", row[1]))
            else:
                raise OperationComposerError(
                    "--event-path is not valid for this typed action."
                )
            index += 2
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
                "add_import_row": "references",
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
            elif action_name in {"set_import_default", "set_import_row_field"}:
                if index + 3 > len(arguments):
                    raise OperationComposerError("--reference is incomplete.")
                name = arguments[index + 1]
                _selector, consumed = _parse_cli_selector(arguments[index + 2 :])
                end = index + 2 + consumed
                if not any(value_row[0] == "name" for value_row in values):
                    values.append(("name", "string", "references"))
                references.append(("value", name, *arguments[index + 2 : end]))
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
        elif flag == "--assignment":
            if action_name != "add_import_row" and not legacy_compatibility:
                raise OperationComposerError(
                    "--assignment is available only for sealed archive replay."
                )
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
    if action_name == "assign_import_row_switch" and not legacy_compatibility:
        raise OperationComposerError(
            "The handle-bound Switch assignment action is available only for "
            "sealed archive replay."
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
    if action_name in _UNDO_GROUP_ACTION_FIELDS:
        required, optional = _UNDO_GROUP_ACTION_FIELDS[action_name]
        _require_allowed_keys(
            action,
            required=("contract", "action", *required),
            optional=optional,
            label="Undo Group action",
        )
        flag_by_field = {
            "display_name": "--display-name",
            "child_operation": "--child-operation",
            "child_handle": "--child-handle",
            "fact_handle": "--fact-handle",
            "fact_action": "--fact-action",
            "field_handle": "--field-handle",
            "value_type": "--value-type",
            "value": "--fact-value",
            "key": "--key",
        }
        result = ["--action", action_name]
        for field in (*required, *optional):
            if field in action:
                result.extend((flag_by_field[field], str(action[field])))
        return tuple(result)
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
    if action_name == "assign_import_row_switch":
        raise OperationComposerError(
            "The handle-bound Switch assignment action is available only for "
            "sealed archive replay."
        )
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
            if action_name == "add_import_row" and field == "import_location":
                arguments.extend(
                    ("--import-location", *_selector_cli_tokens(value))
                )
                continue
            target_field = {
                "add_target": "selector",
                "set_reference": "target",
            }.get(action_name)
            if target_field != field:
                raise OperationComposerError(
                    "Typed selector is not valid for this action field."
                )
            arguments.extend(("--target", *_selector_cli_tokens(value)))
        elif (
            isinstance(value, Mapping)
            and set(value).issubset({"action", "path"})
            and "path" in value
        ):
            event_tokens = (
                ("--event", str(value["action"]), str(value["path"]))
                if "action" in value
                else ("--event-path", str(value["path"]))
            )
            if action_name == "add_import_row" and field == "event":
                arguments.extend(
                    event_tokens
                )
            elif action_name == "set_import_row_field" and field == "value":
                arguments.extend(
                    (
                        "--event",
                        field,
                        str(value["action"]),
                        str(value["path"]),
                    )
                )
            else:
                raise OperationComposerError(
                    "Typed event is not valid for this action field."
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
            if not value and action_name == "add_import_row" and field in {
                "properties",
                "references",
            }:
                arguments.append(f"--empty-{field}")
                continue
            for descriptor in value:
                if not isinstance(descriptor, Mapping):
                    raise OperationComposerError("Typed descriptor list is invalid.")
                if set(descriptor) == {"name", "value"}:
                    if action_name not in {"add_target", "add_import_row"} or field != "properties":
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
                    if action_name not in {"add_target", "add_import_row"} or field != "references":
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
                ("assign_import_row_switch", "import_handle"): "--import-handle",
                ("assign_import_row_switch", "switch"): "--switch",
                ("set_import_operation", "mode"): "--mode",
            }.get((action_name, field))
            direct_import_flag = {
                "object_path": "--object-path",
                "audio_file": "--audio-file",
                "audio_file_base64": "--audio-file-base64",
                "audio_source_notes": "--audio-source-notes",
                "dialogue_event": "--dialogue-event",
                "import_language": "--import-language",
                "import_location": "--import-location",
                "notes": "--notes",
                "object_type": "--object-type",
                "originals_subfolder": "--originals-subfolder",
            }.get(field)
            if direct_action_flag is not None:
                if value_type != "string":
                    raise OperationComposerError(
                        "Typed action text fields must be strings."
                    )
                arguments.extend((direct_action_flag, raw_value))
            elif action_name == "add_import_row" and direct_import_flag is not None:
                if value_type != "string":
                    raise OperationComposerError(
                        "Typed import-row text fields must be strings."
                    )
                arguments.extend((direct_import_flag, raw_value))
            else:
                arguments.extend(("--value", field, value_type, raw_value))
    return tuple(arguments)


def _parse_undo_group_action_cli_arguments(
    arguments: Sequence[str],
) -> dict[str, Any]:
    action_name = arguments[1]
    required, optional = _UNDO_GROUP_ACTION_FIELDS[action_name]
    field_by_flag = {
        "--display-name": "display_name",
        "--child-operation": "child_operation",
        "--child-handle": "child_handle",
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
            raise OperationComposerError("Undo Group typed action argv is invalid.")
        if field in action:
            raise OperationComposerError(f"{flag} may be supplied only once.")
        action[field] = arguments[index + 1]
        index += 2
    _require_allowed_keys(
        action,
        required=("contract", "action", *required),
        optional=optional,
        label="Undo Group action",
    )
    return action


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
        "set_import_row_field": ("--import-handle", "--field"),
        "set_property": ("--target-handle", "--property"),
        "set_node_property": ("--node-handle", "--property"),
        "set_import_default": (None, "--default"),
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
                "--import-handle": "import_handle",
            }[handle_flag]
            result.extend((handle_flag, text(handle_field)))
        value = action.get("value")
        if action_name in {"set_import_default", "set_import_row_field"}:
            name = text("name")
            if name == "import_location" and isinstance(value, Mapping):
                result.extend(
                    ("--import-location", *_selector_cli_tokens(value))
                )
                return tuple(result)
            if name == "event" and isinstance(value, Mapping) and (
                set(value) == {"path"} or set(value) == {"action", "path"}
            ):
                result.extend(
                    (
                        ("--event", str(value["action"]), str(value["path"]))
                        if "action" in value
                        else ("--event-path", str(value["path"]))
                    )
                )
                return tuple(result)
            if name in {"properties", "references"} and isinstance(value, list):
                if not value:
                    result.append(f"--empty-{name}")
                    return tuple(result)
                for descriptor in value:
                    if not isinstance(descriptor, Mapping):
                        raise OperationComposerError(
                            f"Typed import {name} descriptor is invalid."
                        )
                    if name == "properties" and set(descriptor) == {"name", "value"}:
                        value_type, raw_value = _scalar_cli_tokens(
                            descriptor["value"]
                        )
                        result.extend(
                            (
                                "--property",
                                str(descriptor["name"]),
                                value_type,
                                raw_value,
                            )
                        )
                    elif (
                        name == "references"
                        and set(descriptor) == {"name", "target"}
                        and isinstance(descriptor["target"], Mapping)
                    ):
                        result.extend(
                            (
                                "--reference",
                                str(descriptor["name"]),
                                *_selector_cli_tokens(descriptor["target"]),
                            )
                        )
                    else:
                        raise OperationComposerError(
                            f"Typed import {name} descriptor is invalid."
                        )
                return tuple(result)
        if (
            action_name == "set_import_row_field"
            and action.get("name") == "event"
            and isinstance(value, Mapping)
            and set(value) == {"action", "path"}
        ):
            result.extend(
                (
                    "--event",
                    "event",
                    str(value["action"]),
                    str(value["path"]),
                )
            )
            return tuple(result)
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
        "clear_import_row_field": ("--import-handle", "--field"),
        "remove_property": ("--target-handle", "--property"),
        "remove_node_property": ("--node-handle", "--property"),
        "remove_reference": ("--owner-handle", "--reference"),
        "clear_import_default": (None, "--default"),
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
                "--import-handle": "import_handle",
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
        "remove_import_row": (("--import-handle", "import_handle"),),
        "assign_import_row_switch": (
            ("--import-handle", "import_handle"),
            ("--switch", "switch"),
        ),
        "set_import_operation": (("--mode", "mode"),),
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


def _audio_import_hierarchy_row_order_contract() -> dict[str, str | bool]:
    """Keep import hierarchy ordering identical at schema and action time."""

    return {
        "requested_structure_rows_are_separate": True,
        "structure_rows": "tree_preorder_before_every_media_row",
        "media_rows": "prompt_order_after_all_structure_rows",
        "typed_descendant_path_does_not_replace_requested_structure_row": True,
        "batching": (
            "concatenate_structure_then_media_and_split_only_at_batch_limit"
        ),
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

    if operation == "waapi.undoGroup":
        typed = draft_operation_request_contract(operation, version)
        child_operations = compound_child_operations(version)
        return {
            "contract": OPERATION_COMPOSER_CONTRACT,
            "operation": operation,
            "version": version,
            "action_contract": OPERATION_DRAFT_ACTION_CONTRACT,
            "composition_contract": OPERATION_COMPOSITION_CONTRACT,
            "actions": list(_UNDO_GROUP_ACTION_FIELDS),
            "action_shapes": {
                name: {
                    "fixed_fields": {
                        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                        "action": name,
                    },
                    "required_fields": list(required),
                    "optional_fields": list(optional),
                }
                for name, (required, optional) in _UNDO_GROUP_ACTION_FIELDS.items()
            },
            "child_operations": sorted(child_operations),
            "child_contract_discovery": {
                "subcommand": "undo-child-schema",
                "gateway_argv": ["undo-child-schema", "CHILD_OPERATION"],
                "operation_must_come_from": "child_operations",
                "version": "configured_exact_version",
            },
            "typed_request_schema_digest": typed.schema_digest,
            "limits": {
                "calls": 32,
                "display_name_characters": 256,
                "child_facts": MAX_TYPED_REQUEST_FACTS,
                "canonical_request_bytes": 128 * 1024,
                "execution_plan_bytes": 256 * 1024,
                "accumulated_result_bytes": 256 * 1024,
                "action_bytes": MAX_TYPED_COMPOSER_ACTION_BYTES,
            },
            "complete_request_is_never_an_action": True,
        }

    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        typed = (
            request_contract(version, operation)
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
        if operation == "object.create":
            top_level_fact_plan = {
                **top_level_fact_plan,
                "branch_selection_authority": {
                    "business_pointer": "/args/parent",
                    "preserve_explicit_user_selector_kind_and_value": True,
                    "when_explicit_parent_path_is_present": (
                        "choose_path_branch_and_set_that_exact_parent_path"
                    ),
                    "queried_same_name_merge_target_guid_as_parent": (
                        "forbidden_identity_proof_only"
                    ),
                },
                "dynamic_disclosure_authority": (
                    "properties,references,children in that order"
                ),
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
            **(
                {
                    "start_preconditions": {
                        "dynamic_metadata_before_draft_start": True,
                        "applies_when": (
                            "unproven dynamic property/reference tokens are required"
                        ),
                        "workflow_control": _metadata_workflow_control(),
                        "activation_decision": _metadata_activation_decision(),
                        "metadata_scope": (
                            "use --object-type for the new type, never a target path"
                        ),
                    }
                }
                if operation == "object.create"
                else {}
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
        source_control_option_names = [
            name
            for name in (
                "auto_add_to_source_control",
                "auto_check_out_to_source_control",
            )
            if not isinstance(
                fragments["request_options"][name].get("supported_versions"),
                list,
            )
            or version
            in fragments["request_options"][name]["supported_versions"]
        ]
        flat_import_row_discipline = {
            "initial_row_action": "add_import_row",
            "one_initial_action_per_row": True,
            "switch_assignment": {
                "required_in_initial_row_action": True,
                "ordinary_row": {"mode": "none"},
                "when_user_requested": {
                    "mode": "switch",
                    "value": "VALUE",
                },
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
            "hierarchy_row_order": _audio_import_hierarchy_row_order_contract(),
            "metadata_dependency_activation": (
                "agent_selects_exact_token_gateway_validates_dependencies"
            ),
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
            "requested_enable_toggle_and_requested_value_are_distinct_facts": True,
            "switch_assignment_value_only_when_explicit": True,
        }
        planning_discipline = {
            "dynamic_metadata": {
                "fields": ["properties", "references"],
                "discovery_owner": "agent_metadata_discover",
                "validation_owner": "gateway_draft_check",
                "agent_metadata_command_required": (
                    "when_token_is_not_already_exact_live_evidence"
                ),
                "action_fields_source": (
                    "explicit_user_intent_plus_exact_live_tokens"
                ),
                "property_value_type": {
                    "source": (
                        "metadata.candidates[].metadata.typed_value_type"
                    ),
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
                "source": (
                    "registry_fragments.request_options.import_operation"
                ),
                "action": "set_import_operation",
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
                    if action_name == "add_import_row"
                    else {}
                ),
                **(
                    {
                        "user_fact_checklist": dict(
                            import_row_user_fact_checklist
                        )
                    }
                    if action_name == "add_import_row"
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
                    if action_name == "add_import_row"
                    else {}
                ),
                **(
                    {
                        "assignment_contract": {
                            "required_on_every_row": True,
                            "modes": {
                                "none": {"fields": ["mode"]},
                                "switch": {"fields": ["mode", "value"]},
                            },
                            "requires_exact_user_value": True,
                            "additional_fields": False,
                        }
                    }
                    if action_name == "add_import_row"
                    else {}
                ),
                **(
                    {
                        "allowed_names": list(source_control_option_names),
                        "value_type": "boolean",
                        "import_operation_uses": "set_import_operation",
                    }
                    if action_name
                    in {"set_import_option", "clear_import_option"}
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
                "agent_metadata_command_required": (
                    "when_dynamic_token_is_not_already_exact_live_evidence"
                ),
                "workflow_control": _metadata_workflow_control(),
                "activation_decision": _metadata_activation_decision(),
                "metadata_query_batch": _metadata_query_batch_contract(
                    include_limit_discipline=True
                ),
                "submit_only_explicit_user_facts": True,
                "draft_check_revalidates_dynamic_metadata": True,
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
                "construction_boundary": operation_draft_construction_boundary(),
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
            "prior_gateway_id": "opaque_exact_copy_only",
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
        },
        "start_preconditions": {
            "dynamic_metadata_before_draft_start": True,
            "applies_when": (
                "the request contains dynamic properties or references whose exact "
                "live tokens are not already proven"
            ),
            "workflow_control": _metadata_workflow_control(),
            "activation_decision": _metadata_activation_decision(),
            "metadata_scope": (
                "exact shared type: use --object-type; never --object <target-path>"
            ),
            "metadata_scope_decision": {
                "first_source": "exact_shared_target_type_from_every_selector",
                "direct_child_selector_type_is_exact_scope": True,
                "reviewed_property_container_fallback": (
                    "only_registry_default_actor_mixer_container_scope"
                ),
                "action_target_scope": "Action",
                "property_container_for_action_target": "invalid",
            },
            "metadata_gateway_argv_template": [
                "metadata",
                "discover",
                "--object-type",
                "<exact-shared-target-type>",
                "--query",
                "<requested-field-name>",
                "--limit",
                "<1..8>",
            ],
            "metadata_query_batch": _metadata_query_batch_contract(),
            "forbidden_scope_flags": ["--object"],
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
            "construction_boundary": operation_draft_construction_boundary(),
        },
    }


def operation_composer_digest(operation: str, version: str) -> str:
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


def _new_undo_child_handle() -> str:
    return f"uch1-{secrets.token_hex(12)}"


def _normalize_undo_group_composition(
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    _require_json_object(composition, label="composition")
    _require_exact_keys(
        composition,
        required=("contract", "display_name", "calls"),
        label="Undo Group composition",
    )
    if composition.get("contract") != OPERATION_COMPOSITION_CONTRACT:
        raise OperationComposerError("Operation Draft composition contract is invalid.")
    display_name = composition.get("display_name")
    if display_name is not None and (
        not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name) > 256
    ):
        raise OperationComposerError("Undo Group display name is invalid.")
    raw_calls = composition.get("calls")
    if not isinstance(raw_calls, list) or len(raw_calls) > 32:
        raise OperationComposerError("Undo Group child-call count exceeds its ceiling.")
    allowed = compound_child_operations(version)
    calls: list[dict[str, Any]] = []
    handles: set[str] = set()
    for raw_child in raw_calls:
        _require_json_object(raw_child, label="Undo Group child call")
        _require_exact_keys(
            raw_child,
            required=("handle", "operation", "schema_digest", "facts"),
            label="Undo Group child call",
        )
        handle = raw_child.get("handle")
        operation = raw_child.get("operation")
        if (
            not isinstance(handle, str)
            or _UNDO_CHILD_HANDLE_PATTERN.fullmatch(handle) is None
            or handle in handles
        ):
            raise OperationComposerError("Undo Group child handle is invalid.")
        if not isinstance(operation, str) or operation not in allowed:
            raise OperationComposerError("Undo Group child operation is not approved.")
        contract = compound_child_request_contract(operation, version)
        if raw_child.get("schema_digest") != contract.schema_digest:
            raise OperationComposerError("Undo Group child schema digest is stale.")
        raw_facts = raw_child.get("facts")
        if not isinstance(raw_facts, list) or len(raw_facts) > MAX_TYPED_REQUEST_FACTS:
            raise OperationComposerError("Undo Group child fact count exceeds its ceiling.")
        facts: list[dict[str, Any]] = []
        fact_handles: set[str] = set()
        for raw_fact in raw_facts:
            _require_json_object(raw_fact, label="Undo Group child fact")
            _require_allowed_keys(
                raw_fact,
                required=("handle", "fact_action", "field_handle", "value_type", "value"),
                optional=("key",),
                label="Undo Group child fact",
            )
            fact_handle = raw_fact.get("handle")
            if (
                not isinstance(fact_handle, str)
                or _TYPED_FACT_HANDLE_PATTERN.fullmatch(fact_handle) is None
                or fact_handle in fact_handles
            ):
                raise OperationComposerError("Undo Group child fact handle is invalid.")
            normalized = dict(raw_fact)
            if not all(
                isinstance(normalized.get(name), str)
                for name in ("fact_action", "field_handle", "value_type", "value")
            ) or ("key" in normalized and not isinstance(normalized["key"], str)):
                raise OperationComposerError("Undo Group child fact is invalid.")
            fact_handles.add(fact_handle)
            facts.append(normalized)
        handles.add(handle)
        calls.append(
            {
                "handle": handle,
                "operation": operation,
                "schema_digest": contract.schema_digest,
                "facts": facts,
            }
        )
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "display_name": display_name,
        "calls": calls,
    }


def _child_for_handle(composition: Mapping[str, Any], handle: object) -> dict[str, Any]:
    matches = [child for child in composition["calls"] if child["handle"] == handle]
    if len(matches) != 1:
        raise OperationComposerError("child_handle does not name a current Undo child.")
    return matches[0]


def _undo_fact_action(action: Mapping[str, Any]) -> dict[str, str]:
    payload = {
        name: str(action[name])
        for name in ("fact_action", "field_handle", "value_type", "value", "key")
        if name in action
    }
    supplied = set(payload) - {"fact_action", "field_handle"}
    required = {
        "set": {"value_type", "value"},
        "append": {"value_type", "value"},
        "present": set(),
        "choose": {"value"},
        "choose-dynamic": {"key", "value"},
        "map-put": {"key", "value_type", "value"},
    }.get(payload.get("fact_action"))
    if required is None or supplied != required:
        raise OperationComposerError("Undo child fact fields do not match its action.")
    if payload["fact_action"] == "present":
        payload.update({"value_type": "null", "value": "null"})
    elif payload["fact_action"] == "choose":
        payload["value_type"] = "branch"
    elif payload["fact_action"] == "choose-dynamic":
        payload["value_type"] = "choice"
    return payload


def _materialize_undo_child(version: str, child: Mapping[str, Any]) -> dict[str, Any]:
    contract = compound_child_request_contract(str(child["operation"]), version)
    try:
        materialized = materialize_typed_request(
            contract,
            schema_digest=str(child["schema_digest"]),
            facts=tuple(
                TypedRequestFact(
                    fact["fact_action"],
                    fact["field_handle"],
                    fact["value_type"],
                    fact["value"],
                    key=fact.get("key"),
                )
                for fact in child["facts"]
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
    operation = str(child["operation"])
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call" if operation.startswith("ak.") else operation,
        "arguments": (
            {"api": operation, "args": dict(materialized.args), "options": dict(materialized.options)}
            if operation.startswith("ak.")
            else dict(materialized.args)
        ),
    }
    try:
        return parse_operation_request(request, expected_version=version).as_dict()
    except (OperationContractError, SemanticValidationError) as exc:
        raise OperationComposerError(
            str(exc),
            error_code=(
                exc.error_code.value
                if isinstance(exc, SemanticValidationError)
                else exc.error_code
            ),
            details=exc.details,
        ) from exc


def _materialize_undo_group_request(
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    if composition["display_name"] is None or not composition["calls"]:
        raise OperationComposerError(
            "Undo Group needs a display name and at least one complete child.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
        )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.undoGroup",
        "arguments": {
            "display_name": composition["display_name"],
            "calls": [],
        },
    }
    request["arguments"]["calls"] = [
        {
            "schema_digest": child["schema_digest"],
            "request": _materialize_undo_child(version, child),
        }
        for child in composition["calls"]
    ]
    try:
        return parse_operation_request(request, expected_version=version).as_dict()
    except OperationContractError as exc:
        raise OperationComposerError(
            str(exc), error_code=exc.error_code, details=exc.details
        ) from exc


def _apply_undo_group_action(
    version: str,
    composition: Mapping[str, Any],
    action: Mapping[str, Any],
    *,
    handle_factory: Callable[[], str] | None,
) -> tuple[dict[str, Any], str]:
    normalized = _normalize_undo_group_composition(version, composition)
    _require_json_object(action, label="action")
    try:
        action_size = len(canonical_json_bytes(dict(action)))
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise OperationComposerError(
            "Undo Group action must be strict JSON."
        ) from exc
    if action_size > MAX_TYPED_COMPOSER_ACTION_BYTES:
        raise OperationComposerError(
            "Undo Group action exceeds its fixed byte ceiling.",
            details={
                "size_bytes": action_size,
                "limit_bytes": MAX_TYPED_COMPOSER_ACTION_BYTES,
            },
        )
    if action.get("contract") != OPERATION_DRAFT_ACTION_CONTRACT:
        raise OperationComposerError("action contract is invalid.")
    action_name = action.get("action")
    if action_name not in _UNDO_GROUP_ACTION_FIELDS:
        raise OperationComposerError("Undo Group action is unsupported.")
    required, optional = _UNDO_GROUP_ACTION_FIELDS[str(action_name)]
    _require_allowed_keys(
        action,
        required=("contract", "action", *required),
        optional=optional,
        label="Undo Group action",
    )
    candidate = {
        **normalized,
        "calls": [
            {**child, "facts": [dict(fact) for fact in child["facts"]]}
            for child in normalized["calls"]
        ],
    }
    if action_name == "set_display_name":
        candidate["display_name"] = action["display_name"]
    elif action_name == "add_child_call":
        if len(candidate["calls"]) >= 32:
            raise OperationComposerError("Undo Group child-call ceiling has been reached.")
        operation = action["child_operation"]
        if not isinstance(operation, str) or operation not in compound_child_operations(version):
            raise OperationComposerError("Undo Group child operation is not approved.")
        child_handle = handle_factory() if handle_factory is not None else _new_undo_child_handle()
        if (
            not isinstance(child_handle, str)
            or _UNDO_CHILD_HANDLE_PATTERN.fullmatch(child_handle) is None
            or any(child["handle"] == child_handle for child in candidate["calls"])
        ):
            raise OperationComposerError("Generated Undo Group child handle is invalid.")
        child_contract = compound_child_request_contract(operation, version)
        candidate["calls"].append(
            {
                "handle": child_handle,
                "operation": operation,
                "schema_digest": child_contract.schema_digest,
                "facts": [],
            }
        )
        candidate = _normalize_undo_group_composition(version, candidate)
        return candidate, str(action_name)
    elif action_name == "remove_child_call":
        child = _child_for_handle(candidate, action["child_handle"])
        candidate["calls"].remove(child)
    else:
        child = _child_for_handle(candidate, action["child_handle"])
        if action_name == "remove_child_typed_fact":
            matches = [fact for fact in child["facts"] if fact["handle"] == action["fact_handle"]]
            if len(matches) != 1:
                raise OperationComposerError("fact_handle does not name a current child fact.")
            child["facts"].remove(matches[0])
        else:
            fact_payload = _undo_fact_action(action)
            if action_name == "add_child_typed_fact":
                fact_handle = handle_factory() if handle_factory is not None else _new_typed_fact_handle()
                if (
                    not isinstance(fact_handle, str)
                    or _TYPED_FACT_HANDLE_PATTERN.fullmatch(fact_handle) is None
                    or any(fact["handle"] == fact_handle for fact in child["facts"])
                ):
                    raise OperationComposerError("Generated child fact handle is invalid.")
                child["facts"].append({"handle": fact_handle, **fact_payload})
            else:
                matches = [fact for fact in child["facts"] if fact["handle"] == action["fact_handle"]]
                if len(matches) != 1:
                    raise OperationComposerError("fact_handle does not name a current child fact.")
                matches[0].clear()
                matches[0].update({"handle": action["fact_handle"], **fact_payload})
        try:
            _materialize_undo_child(version, child)
        except OperationComposerError as exc:
            if exc.error_code not in {
                "OPERATION_DRAFT_INCOMPLETE",
                "SEMANTIC_INVALID_REQUEST",
                "SEMANTIC_SCHEMA_MISMATCH",
                "INVALID_ARGUMENT",
            }:
                raise
    candidate = _normalize_undo_group_composition(version, candidate)
    try:
        _materialize_undo_group_request(version, candidate)
    except OperationComposerError as exc:
        if exc.error_code not in {
            "OPERATION_DRAFT_INCOMPLETE",
            "SEMANTIC_SCHEMA_MISMATCH",
            "INVALID_ARGUMENT",
        }:
            raise
    return candidate, str(action_name)


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
    contract = operation_composer_contract(operation, version)
    if operation == "waapi.undoGroup":
        return {
            "contract": OPERATION_COMPOSITION_CONTRACT,
            "display_name": None,
            "calls": [],
        }
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        return {
            "contract": OPERATION_COMPOSITION_CONTRACT,
            "typed_request_schema_digest": contract["typed_request_schema_digest"],
            "facts": [],
        }
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
    allow_cleaned_file_evidence: bool = False,
) -> tuple[dict[str, Any], str]:
    """Validate and apply one closed action without mutating the input mapping."""

    operation_composer_contract(operation, version)
    if operation == "waapi.undoGroup":
        return _apply_undo_group_action(
            version,
            composition,
            action,
            handle_factory=handle_factory,
        )
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        return _apply_generic_typed_action(
            operation,
            version,
            composition,
            action,
            handle_factory=handle_factory,
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )
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
    *,
    allow_cleaned_file_evidence: bool = False,
) -> dict[str, Any]:
    """Build and canonically reparse the complete operation request."""

    if not isinstance(allow_cleaned_file_evidence, bool):
        raise TypeError("allow_cleaned_file_evidence must be a boolean")

    normalized = _normalize_composition(composition, operation=operation, version=version)
    if operation == "waapi.undoGroup":
        return _materialize_undo_group_request(version, normalized)
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        typed = (
            request_contract(version, operation)
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
            if allow_cleaned_file_evidence and operation in {
                "lua.executeCliFile",
                "lua.executeCoreFile",
            }:
                # A sealed PASS archive is replayed after its owned source tree
                # has been deleted.  Typed Core still rebuilds every fact and
                # the durable seal supplies the exact request comparison; only
                # the live file-existence proof is intentionally not repeated.
                return request
            try:
                return parse_operation_request(request, expected_version=version).as_dict()
            except OperationContractError as exc:
                raise OperationComposerError(
                    str(exc), details=exc.details, error_code=exc.error_code
                ) from exc
        return request
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
    *,
    allow_cleaned_file_evidence: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_composition(composition, operation=operation, version=version)
    if operation == "waapi.undoGroup":
        missing: list[str] = []
        if normalized["display_name"] is None:
            missing.append("display_name")
        if not normalized["calls"]:
            missing.append("child_call")
        for child in normalized["calls"]:
            try:
                _materialize_undo_child(version, child)
            except OperationComposerError as exc:
                if exc.error_code != "OPERATION_DRAFT_INCOMPLETE":
                    raise
                missing.append(f"calls[{child['handle']}].complete_typed_request")
        return {
            "display_name": normalized["display_name"],
            "current_facts": [
                {
                    "handle": child["handle"],
                    "operation": child["operation"],
                    "schema_digest": child["schema_digest"],
                    "facts": [dict(fact) for fact in child["facts"]],
                }
                for child in normalized["calls"]
            ],
            "missing_fields": missing,
            "missing_fields_status": "complete" if not missing else "incomplete",
            "allowed_actions": [
                *operation_composer_contract(operation, version)["actions"],
                "check",
                "inspect",
                "cancel",
            ],
        }
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
    operation_composer_contract(operation, version)
    if operation == "waapi.undoGroup":
        return _normalize_undo_group_composition(version, composition)
    if operation.startswith("ak.") or operation in DRAFT_TYPED_OPERATIONS:
        return _normalize_generic_typed_composition(
            operation, version, composition
        )
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
    if action_name == "set_import_operation":
        _require_exact_keys(
            action,
            required=("contract", "action", "mode"),
            label="set_import_operation action",
        )
        descriptor = _validate_audio_import_fragment(
            version,
            fragment="request_option",
            payload={"name": "import_operation", "value": action.get("mode")},
        )
        options = composition["request_options"]
        assert isinstance(options, dict)
        options[descriptor["name"]] = descriptor["value"]
        _materialize_if_complete(AUDIO_IMPORT_COMPOSER_OPERATION, version, composition)
        return composition, str(action_name)
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
    if action_name == "add_import_row":
        row_field_names = tuple(
            operation_composer_contract(
                AUDIO_IMPORT_COMPOSER_OPERATION, version
            )["registry_fragments"]["supported_row_fields"]
        )
        required_action_fields, optional_action_fields = (
            _AUDIO_IMPORT_ACTION_FIELDS[action_name]
        )
        _require_allowed_keys(
            action,
            required=(
                "contract",
                "action",
                *required_action_fields,
            ),
            optional=optional_action_fields,
            label=f"{action_name} action",
        )
        assignment = action.get("assignment")
        assignment_mode = assignment.get("mode") if isinstance(assignment, Mapping) else None
        if assignment_mode == "none":
            _require_exact_keys(
                assignment,
                required=("mode",),
                label="add_import_row assignment",
            )
            switch_assignment = None
        elif assignment_mode == "switch":
            _require_exact_keys(
                assignment,
                required=("mode", "value"),
                label="add_import_row assignment",
            )
            switch_assignment = _validate_audio_import_fragment(
                version,
                fragment="row_field",
                payload={
                    "name": "switch_assignment",
                    "value": assignment.get("value"),
                },
            )
        else:
            raise OperationComposerError(
                "add_import_row assignment mode must be 'none' or 'switch'.",
                details={"mode": assignment_mode},
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
    if action_name == "assign_import_row_switch":
        _require_exact_keys(
            action,
            required=("contract", "action", "import_handle", "switch"),
            label="assign_import_row_switch action",
        )
        row = _audio_import_row_for_handle(
            composition,
            action.get("import_handle"),
        )
        descriptor = _validate_audio_import_fragment(
            version,
            fragment="row_field",
            payload={
                "name": "switch_assignment",
                "value": action.get("switch"),
            },
        )
        fields = row["fields"]
        assert isinstance(fields, dict)
        fields[descriptor["name"]] = descriptor["value"]
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
                "action": "add_import_row",
                "required_on_every_row": True,
                "ordinary_row": ["--assignment", "none"],
                "when_user_requested": [
                    "--assignment",
                    "switch",
                    "<exact-value>",
                ],
                "applies_to": "this row's --object-path",
                "new_parent_or_container": (
                    "use switch on that row when the user assigns the new object"
                ),
                "other_rows": "use none unless the user assigns that row",
                "guessing_allowed": False,
            },
            "hierarchy_row_order": _audio_import_hierarchy_row_order_contract(),
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
    "MAX_TYPED_ACTIONS_PER_APPLY",
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

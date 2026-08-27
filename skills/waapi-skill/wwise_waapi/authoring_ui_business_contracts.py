"""Closed business declarations for Authoring UI capture and commands."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS
from .operation_ui_commands import (
    MAX_ARGUMENT_TOKEN_CHARS,
    MAX_ARGUMENT_TOKENS,
    MAX_COMMANDS_PER_PLAN,
    MAX_COMMAND_FILES,
    MAX_COMMAND_ID_CHARS,
    MAX_DEFAULT_SHORTCUT_CHARS,
    MAX_DISPLAY_NAME_CHARS,
    MAX_LUA_MODULE_DIRECTORIES,
    MAX_LUA_SELECTED_RETURN_CHARS,
    MAX_LUA_SELECTED_RETURN_FIELDS,
    MAX_MENU_SEGMENT_CHARS,
    MAX_MENU_SEGMENTS,
    MAX_OBJECT_ARGUMENTS,
    MAX_OBJECT_ARGUMENT_CHARS,
    MAX_OBJECT_TYPES,
    MAX_OBJECT_TYPE_CHARS,
    MAX_PATH_CHARS,
    MAX_PLATFORM_ARGUMENTS,
    MAX_PLATFORM_ARGUMENT_CHARS,
    START_MODES,
)


AUTHORING_UI_BUSINESS_CONTRACT = "waapi-skill.authoring-ui-business/v1"
AUTHORING_UI_BUSINESS_OPERATIONS = (
    "ui.captureScreen",
    "ui.commands.execute",
    "ui.commands.register",
    "ui.commands.unregister",
)


def authoring_ui_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    if operation not in AUTHORING_UI_BUSINESS_OPERATIONS:
        raise ValueError("unsupported Authoring UI business operation")
    if version not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError("unsupported Wwise version")
    declaration = _declaration(operation, version)
    return {
        "contract": AUTHORING_UI_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {
            "available": False,
            "roles": [],
            "role_required": False,
        },
        "declaration": declaration,
        "responsibility_split": {
            "agent": (
                "choose_capture_outcomes_or_live_command_business_values_and_"
                "copy_exact_user_handler_paths"
            ),
            "gateway": (
                "derive_authoring_host_guards_command_ids_platform_source_"
                "authority_revision_order_native_payload_and_cleanup"
            ),
        },
        "gateway_derivations": [
            "authoring_host_and_platform_guard",
            "project_scoped_command_ids",
            "source_authority_and_unknown_ownership_acknowledgement",
            "native_version_fields_and_serialization",
            "fresh_inventory_preconditions_and_postconditions",
            "registration_cleanup_companion",
        ],
        "legacy_inline_typed_public": False,
        "legacy_composer_public": False,
        "safety": {
            "authoring_host_required": True,
            "fresh_command_inventory": operation
            in {"ui.commands.execute", "ui.commands.register", "ui.commands.unregister"},
            "immutable_preview": True,
            "single_execute": True,
            "paired_unregister": operation == "ui.commands.register",
            "exact_handler_paths": True,
        },
    }


def _declaration(operation: str, version: str) -> dict[str, Any]:
    if operation == "ui.captureScreen":
        return {
            "subcommand": "draft-declare-ui-plan",
            "settings_field": "ui_plan",
            "submit_once": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "view_name": {"type": "string", "minLength": 1},
                    "view_channel": {"type": "integer", "minimum": 1, "maximum": 4},
                    "rectangle": _rectangle_schema(),
                },
            },
        }
    if operation == "ui.commands.execute":
        properties: dict[str, Any] = {
            "command_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_COMMAND_ID_CHARS,
            },
            "objects": _string_array(MAX_OBJECT_ARGUMENTS, MAX_OBJECT_ARGUMENT_CHARS),
            "platforms": _string_array(
                MAX_PLATFORM_ARGUMENTS,
                MAX_PLATFORM_ARGUMENT_CHARS,
            ),
            "value": {"strictJsonScalar": True},
        }
        if version == "2025.1":
            properties["files"] = _string_array(MAX_COMMAND_FILES, MAX_PATH_CHARS)
        return {
            "subcommand": "draft-declare-ui-plan",
            "settings_field": "ui_plan",
            "submit_once": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["command_id"],
                "properties": properties,
            },
        }
    if operation == "ui.commands.register":
        return {
            "subcommand": "draft-declare-ui-plan",
            "settings_field": "ui_plan",
            "submit_once": True,
            "staged": True,
            "header_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["command_count"],
                "properties": {
                    "command_count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_COMMANDS_PER_PLAN,
                    }
                },
            },
            "item_subcommand": "draft-add-ui-command",
            "item_schema": _business_command_schema(version),
        }
    return {
        "subcommand": "draft-declare-ui-plan",
        "settings_field": "ui_plan",
        "submit_once": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "oneOf": [
                {
                    "required": ["registered_command_keys"],
                    "forbidden": ["existing_command_ids", "confirm_unknown_ownership"],
                },
                {
                    "required": ["existing_command_ids", "confirm_unknown_ownership"],
                    "forbidden": ["registered_command_keys"],
                },
            ],
            "properties": {
                "registered_command_keys": _string_array(
                    MAX_COMMANDS_PER_PLAN,
                    128,
                ),
                "existing_command_ids": _string_array(
                    MAX_COMMANDS_PER_PLAN,
                    MAX_COMMAND_ID_CHARS,
                ),
                "confirm_unknown_ownership": {"const": True},
            },
        },
    }


def _business_command_schema(version: str) -> dict[str, Any]:
    handler_choices = [_notification_handler_schema(), _program_handler_schema()]
    if version in {"2023.1", "2024.1", "2025.1"}:
        handler_choices.append(_lua_handler_schema())
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["key", "display_name", "handler"],
        "properties": {
            "key": {"type": "string", "minLength": 1, "maxLength": 128},
            "display_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_DISPLAY_NAME_CHARS,
            },
            "handler": {
                "oneOf": handler_choices,
            },
            "default_shortcut": {
                "type": "string",
                "maxLength": MAX_DEFAULT_SHORTCUT_CHARS,
            },
            "context_menu": _context_menu_schema(),
            "main_menu": {
                "type": "object",
                "additionalProperties": False,
                "required": ["base_path"],
                "properties": {"base_path": _path_segments_schema()},
            },
        },
    }


def _notification_handler_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {"kind": {"const": "notification"}},
    }


def _program_handler_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "program_path"],
        "properties": {
            "kind": {"const": "program"},
            "program_path": _path_schema(),
            "working_directory": _path_schema(),
            "start_mode": {"enum": sorted(START_MODES)},
            "redirect_outputs": {"type": "boolean"},
        },
        "programArguments": "unsupported_requires_a_dedicated_closed_adapter",
    }


def _lua_handler_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "lua_script_path"],
        "properties": {
            "kind": {"const": "lua_script"},
            "lua_script_path": _path_schema(),
            "argument_tokens": _string_array(
                MAX_ARGUMENT_TOKENS,
                MAX_ARGUMENT_TOKEN_CHARS,
                minimum=0,
                unique=False,
                allow_empty_items=True,
            ),
            "working_directory": _path_schema(),
            "start_mode": {"enum": sorted(START_MODES)},
            "lua_module_directories": _string_array(
                MAX_LUA_MODULE_DIRECTORIES,
                MAX_PATH_CHARS,
                minimum=0,
            ),
            "lua_selected_return": _string_array(
                MAX_LUA_SELECTED_RETURN_FIELDS,
                MAX_LUA_SELECTED_RETURN_CHARS,
                minimum=0,
            ),
        },
    }


def _context_menu_schema() -> dict[str, Any]:
    object_types = _string_array(
        MAX_OBJECT_TYPES,
        MAX_OBJECT_TYPE_CHARS,
        minimum=0,
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "base_path": _string_array(
                MAX_MENU_SEGMENTS,
                MAX_MENU_SEGMENT_CHARS,
                minimum=0,
            ),
            "visible_for": object_types,
            "enabled_for": object_types,
        },
    }


def _path_schema() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": MAX_PATH_CHARS}


def _rectangle_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["x", "y", "width", "height"],
        "properties": {
            "x": {"type": "integer", "minimum": 0},
            "y": {"type": "integer", "minimum": 0},
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
        },
    }


def _string_array(
    maximum: int,
    length: int,
    *,
    minimum: int = 1,
    unique: bool = True,
    allow_empty_items: bool = False,
) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": unique,
        "items": {
            "type": "string",
            "minLength": 0 if allow_empty_items else 1,
            "maxLength": length,
        },
    }


def _path_segments_schema() -> dict[str, Any]:
    return _string_array(MAX_MENU_SEGMENTS, MAX_MENU_SEGMENT_CHARS)


__all__ = [
    "AUTHORING_UI_BUSINESS_CONTRACT",
    "AUTHORING_UI_BUSINESS_OPERATIONS",
    "authoring_ui_business_contract_data",
]

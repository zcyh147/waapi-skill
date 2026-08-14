"""Concise Gateway-owned input for simple dedicated operations.

This module owns only model-facing value composition.  It materializes the
same Canonical OperationRequest consumed by the existing Registry parser,
preparer, Preview lifecycle, dispatcher, and verifier.
"""

from __future__ import annotations

import json
from copy import deepcopy
import math
import re
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes
from .schema_inventory import load_definition_graph
from .typed_requests import (
    TypedRequestContract,
    compile_typed_request_contract,
    request_contract,
)
from .operation_registry import (
    INLINE_TYPED_INPUT_MODE,
    OPERATION_REQUEST_CONTRACT,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
    OperationContractError,
    list_operation_specs,
    operation_request_schema_digest,
    operation_request_machine_contract,
    parse_operation_request,
    validate_operation_identity_fragment,
)


INLINE_OPERATION_CONTRACT = "waapi-skill.inline-operation-input/v1"
INLINE_OPERATIONS = frozenset(
    {
        "debug.restartWaapiServers",
        "debug.setAsserts",
        "debug.setAutomationMode",
        "debug.testAssert",
        "debug.testCrash",
        "object.setLinked",
        "object.setName",
        "object.setNotes",
        "object.setProperty",
        "object.setReference",
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
        "object.delete",
        "object.copy",
        "object.move",
        "soundbank.processDefinitionFiles",
        "audio.importTabDelimited",
        "ui.captureScreen",
        "ui.commands.execute",
    }
)
DRAFT_TYPED_OPERATIONS = frozenset(
    {
        "object.create",
        "object.createPlugin",
        "object.setRTPC",
        "soundbank.convertExternalSources",
        "soundbank.generate",
        "soundbank.setInclusions",
        "ui.commands.register",
        "ui.commands.unregister",
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "waapi.undoGroup",
    }
)
_MAX_SELECTOR_DEPTH = 8
MAX_INLINE_OPERATION_VALUE_BYTES = 32 * 1024
MAX_INLINE_OPERATION_REQUEST_BYTES = 64 * 1024


class TypedOperationInputError(ValueError):
    """One concise typed operation value is invalid or incomplete."""


def _bounded_text(value: object, *, field: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypedOperationInputError(f"{field} must be a string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise TypedOperationInputError(f"{field} must contain valid Unicode") from exc
    if size > MAX_INLINE_OPERATION_VALUE_BYTES:
        raise TypedOperationInputError(
            f"{field} exceeds the {MAX_INLINE_OPERATION_VALUE_BYTES}-byte UTF-8 limit"
        )
    return value


def _parse_selector(
    tokens: Sequence[str],
    *,
    depth: int = 0,
) -> tuple[dict[str, Any], int]:
    if depth > _MAX_SELECTOR_DEPTH or not tokens:
        raise TypedOperationInputError("Typed selector is missing or too deeply nested")
    kind = tokens[0]
    if kind in {"id-string", "id-integer", "path"}:
        if len(tokens) < 2:
            raise TypedOperationInputError(f"{kind} selector requires VALUE")
        raw = tokens[1]
        if kind == "id-integer":
            if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw) is None:
                raise TypedOperationInputError("id-integer requires canonical decimal syntax")
            return {"kind": "id", "value": int(raw)}, 2
        return {"kind": "id" if kind == "id-string" else "path", "value": raw}, 2
    if kind == "exact-type-name":
        if len(tokens) < 3:
            raise TypedOperationInputError("exact-type-name requires TYPE NAME")
        return {"kind": kind, "type": tokens[1], "name": tokens[2]}, 3
    if kind == "direct-child":
        if len(tokens) < 3:
            raise TypedOperationInputError("direct-child requires TYPE PARENT_SELECTOR")
        parent, consumed = _parse_selector(tokens[2:], depth=depth + 1)
        if parent.get("kind") not in {"id", "path"}:
            raise TypedOperationInputError(
                "direct-child parent selector must be id-string, id-integer, or path"
            )
        return {"kind": kind, "type": tokens[1], "parent": parent}, 2 + consumed
    if kind == "scoped-name":
        if len(tokens) < 4:
            raise TypedOperationInputError("scoped-name requires TYPE NAME PARENT_SELECTOR")
        parent, consumed = _parse_selector(tokens[3:], depth=depth + 1)
        if parent.get("kind") not in {"id", "path"}:
            raise TypedOperationInputError(
                "scoped-name parent selector must be id-string, id-integer, or path"
            )
        return {
            "kind": kind,
            "type": tokens[1],
            "name": tokens[2],
            "parent": parent,
        }, 3 + consumed
    raise TypedOperationInputError(f"Unsupported typed selector kind {kind!r}")


def _selector(
    value: object,
    *,
    operation: str,
    version: str,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypedOperationInputError(f"{field} requires one typed selector")
    tokens = tuple(value)
    if not all(isinstance(token, str) for token in tokens):
        raise TypedOperationInputError(f"{field} selector tokens must be strings")
    for token in tokens:
        _bounded_text(token, field=f"{field} selector token", allow_empty=False)
    selector, consumed = _parse_selector(tokens)
    if consumed != len(tokens):
        raise TypedOperationInputError(f"{field} selector has trailing tokens")
    try:
        return validate_operation_identity_fragment(
            operation,
            version,
            role=field,
            payload=selector,
        )
    except OperationContractError as exc:
        raise TypedOperationInputError(str(exc)) from exc


def _typed_scalar(value_type: object, raw_value: object) -> Any:
    if not isinstance(value_type, str) or not isinstance(raw_value, str):
        raise TypedOperationInputError("typed scalar requires TYPE and VALUE strings")
    if value_type == "string":
        return _bounded_text(raw_value, field="value")
    if value_type == "boolean":
        if raw_value not in {"true", "false"}:
            raise TypedOperationInputError("boolean values must be true or false")
        return raw_value == "true"
    if value_type == "integer":
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw_value) is None:
            raise TypedOperationInputError("integer values must use canonical decimal syntax")
        return int(raw_value)
    if value_type == "number":
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise TypedOperationInputError("number values must use JSON number syntax") from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypedOperationInputError("number values must use JSON number syntax")
        if isinstance(value, float) and not math.isfinite(value):
            raise TypedOperationInputError("number values must be finite")
        return value
    raise TypedOperationInputError("scalar type must be string, integer, number, or boolean")


def _require_keys(
    values: Mapping[str, object],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    actual = set(values)
    missing = required - actual
    unexpected = actual - required - optional
    if missing or unexpected:
        raise TypedOperationInputError(
            "Typed operation fields are invalid: "
            f"missing={sorted(missing)!r}, unexpected={sorted(unexpected)!r}"
        )


def materialize_inline_operation_request(
    operation: str,
    version: str,
    values: Mapping[str, object],
) -> dict[str, Any]:
    """Materialize and strictly reparse one concise operation submission."""

    if operation not in INLINE_OPERATIONS:
        raise TypedOperationInputError(f"No inline typed adapter exists for {operation!r}")
    arguments: dict[str, Any]
    if operation in {
        "debug.restartWaapiServers",
        "debug.testAssert",
        "debug.testCrash",
    }:
        _require_keys(values, required=frozenset())
        arguments = {
            "acknowledge": {
                "debug.restartWaapiServers": "restart_waapi_servers",
                "debug.testAssert": "trigger_debug_assert",
                "debug.testCrash": "crash_wwise_process",
            }[operation]
        }
    elif operation in {"debug.setAsserts", "debug.setAutomationMode"}:
        _require_keys(values, required=frozenset({"enable"}))
        arguments = {"enable": _typed_scalar("boolean", values["enable"])}
    elif operation == "audio.importTabDelimited":
        _require_keys(
            values,
            required=frozenset(
                {"import_file", "import_location", "import_language"}
            ),
            optional=frozenset(
                {
                    "import_operation",
                    "auto_add_to_source_control",
                    "auto_check_out_to_source_control",
                }
            ),
        )
        arguments = {
            "import_file": _bounded_text(
                values["import_file"], field="import_file", allow_empty=False
            ),
            "import_location": _selector(
                values["import_location"],
                operation=operation,
                version=version,
                field="import_location",
            ),
            "import_language": _bounded_text(
                values["import_language"], field="import_language", allow_empty=False
            ),
        }
        if "import_operation" in values:
            arguments["import_operation"] = _bounded_text(
                values["import_operation"],
                field="import_operation",
                allow_empty=False,
            )
        for field in (
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        ):
            if field in values:
                arguments[field] = _typed_scalar("boolean", values[field])
    elif operation == "ui.captureScreen":
        _require_keys(
            values,
            required=frozenset(),
            optional=frozenset({"view_name", "view_channel", "rect"}),
        )
        arguments = {}
        if "view_name" in values:
            arguments["view_name"] = _bounded_text(
                values["view_name"], field="view_name", allow_empty=False
            )
        if "view_channel" in values:
            raw_channel = values["view_channel"]
            if not isinstance(raw_channel, str) or raw_channel not in {"1", "2", "3", "4"}:
                raise TypedOperationInputError("view_channel must be 1, 2, 3, or 4")
            arguments["view_channel"] = int(raw_channel)
        if "rect" in values:
            raw_rect = values["rect"]
            if (
                not isinstance(raw_rect, Sequence)
                or isinstance(raw_rect, (str, bytes))
                or len(raw_rect) != 4
            ):
                raise TypedOperationInputError("rect requires X Y WIDTH HEIGHT")
            parsed: list[int] = []
            for name, raw in zip(("x", "y", "width", "height"), raw_rect):
                if not isinstance(raw, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)", raw) is None:
                    raise TypedOperationInputError(f"rect {name} must be a non-negative integer")
                parsed.append(int(raw))
            if parsed[2] < 1 or parsed[3] < 1:
                raise TypedOperationInputError("rect width and height must be positive")
            arguments["rect"] = dict(zip(("x", "y", "width", "height"), parsed))
    elif operation == "ui.commands.execute":
        _require_keys(
            values,
            required=frozenset({"command"}),
            optional=frozenset(
                {"objects", "platforms", "value_type", "value", "files"}
            ),
        )
        if ("value_type" in values) != ("value" in values):
            raise TypedOperationInputError("command value requires both TYPE and VALUE")
        arguments = {
            "command": _bounded_text(values["command"], field="command", allow_empty=False)
        }
        for name, maximum in (("objects", 64), ("platforms", 16), ("files", 64)):
            if name not in values:
                continue
            raw_items = values[name]
            if (
                not isinstance(raw_items, Sequence)
                or isinstance(raw_items, (str, bytes))
                or not 1 <= len(raw_items) <= maximum
            ):
                raise TypedOperationInputError(f"{name} requires 1-{maximum} values")
            arguments[name] = [
                _bounded_text(item, field=name, allow_empty=False) for item in raw_items
            ]
        if "files" in arguments and version != "2025.1":
            raise TypedOperationInputError("command files are available only in Wwise 2025.1")
        if "value" in values:
            arguments["value"] = _typed_scalar(values["value_type"], values["value"])
    elif operation == "soundbank.processDefinitionFiles":
        _require_keys(values, required=frozenset({"files", "io_root"}))
        files = values["files"]
        if (
            not isinstance(files, Sequence)
            or isinstance(files, (str, bytes))
            or not files
            or len(files) > 32
        ):
            raise TypedOperationInputError(
                "soundbank.processDefinitionFiles requires 1-32 caller-owned files"
            )
        arguments = {
            "files": [
                _bounded_text(path, field="file", allow_empty=False) for path in files
            ],
            "io_root": _bounded_text(
                values["io_root"], field="io_root", allow_empty=False
            ),
        }
    elif operation in {
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    }:
        _require_keys(
            values,
            required=frozenset(
                {"switch_container", "child", "state_or_switch"}
            ),
        )
        arguments = {
            role: _selector(
                values[role], operation=operation, version=version, field=role
            )
            for role in ("switch_container", "child", "state_or_switch")
        }
    elif operation in {"object.setName", "object.setNotes"}:
        _require_keys(values, required=frozenset({"object", "text"}))
        arguments = {
            "object": _selector(values["object"], operation=operation, version=version, field="object"),
            "value": _bounded_text(
                values["text"],
                field="text",
                allow_empty=operation == "object.setNotes",
            ),
        }
    elif operation == "object.delete":
        _require_keys(
            values,
            required=frozenset({"object"}),
            optional=frozenset({"auto_check_out_to_source_control"}),
        )
        arguments = {
            "object": _selector(values["object"], operation=operation, version=version, field="object"),
        }
        if "auto_check_out_to_source_control" in values:
            arguments["auto_check_out_to_source_control"] = _typed_scalar(
                "boolean", values["auto_check_out_to_source_control"]
            )
    elif operation in {"object.copy", "object.move"}:
        _require_keys(
            values,
            required=frozenset({"object", "parent"}),
            optional=frozenset({"on_name_conflict", "auto_add_to_source_control", "auto_check_out_to_source_control"}),
        )
        arguments = {
            "object": _selector(values["object"], operation=operation, version=version, field="object"),
            "parent": _selector(values["parent"], operation=operation, version=version, field="parent"),
        }
        if "on_name_conflict" in values:
            conflict = _bounded_text(
                values["on_name_conflict"], field="on_name_conflict", allow_empty=False
            )
            if conflict not in {"fail", "rename"}:
                raise TypedOperationInputError(
                    "on_name_conflict must be fail or rename; replace is not exposed"
                )
            arguments["on_name_conflict"] = conflict
        if "auto_add_to_source_control" in values:
            if operation != "object.copy":
                raise TypedOperationInputError("auto_add_to_source_control applies only to object.copy")
            arguments["auto_add_to_source_control"] = _typed_scalar(
                "boolean", values["auto_add_to_source_control"]
            )
        if "auto_check_out_to_source_control" in values:
            arguments["auto_check_out_to_source_control"] = _typed_scalar(
                "boolean", values["auto_check_out_to_source_control"]
            )
    elif operation == "object.setProperty":
        _require_keys(
            values,
            required=frozenset({"object", "property", "value_type", "value"}),
            optional=frozenset({"platform"}),
        )
        arguments = {
            "object": _selector(values["object"], operation=operation, version=version, field="object"),
            "property": _bounded_text(values["property"], field="property", allow_empty=False),
            "value": _typed_scalar(values["value_type"], values["value"]),
        }
        if "platform" in values:
            arguments["platform"] = _bounded_text(
                values["platform"], field="platform", allow_empty=False
            )
    elif operation == "object.setReference":
        _require_keys(
            values,
            required=frozenset({"object", "reference"}),
            optional=frozenset({"target", "clear", "platform"}),
        )
        has_target = "target" in values
        clear = values.get("clear") is True
        if has_target == clear:
            raise TypedOperationInputError(
                "object.setReference requires exactly one of target or clear"
            )
        arguments = {
            "object": _selector(values["object"], operation=operation, version=version, field="object"),
            "reference": _bounded_text(values["reference"], field="reference", allow_empty=False),
            "target": (
                _selector(values["target"], operation=operation, version=version, field="target") if has_target else None
            ),
        }
        if "platform" in values:
            arguments["platform"] = _bounded_text(
                values["platform"], field="platform", allow_empty=False
            )
    else:
        _require_keys(
            values,
            required=frozenset({"object", "property", "platform", "linked"}),
        )
        arguments = {
            "object": _selector(values["object"], operation=operation, version=version, field="object"),
            "property": _bounded_text(values["property"], field="property", allow_empty=False),
            "platform": _bounded_text(values["platform"], field="platform", allow_empty=False),
            "linked": _typed_scalar("boolean", values["linked"]),
        }
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": arguments,
    }
    if len(canonical_json_bytes(request)) > MAX_INLINE_OPERATION_REQUEST_BYTES:
        raise TypedOperationInputError(
            "Typed operation request exceeds the "
            f"{MAX_INLINE_OPERATION_REQUEST_BYTES}-byte canonical limit"
        )
    try:
        parse_operation_request(request, expected_version=version)
    except OperationContractError as exc:
        raise TypedOperationInputError(str(exc)) from exc
    return request


def inline_operation_cli_arguments(request: Mapping[str, Any]) -> tuple[str, ...]:
    """Serialize one canonical inline operation into its only public argv form."""

    if not isinstance(request, Mapping):
        raise TypedOperationInputError("Inline operation request must be an object")
    operation = request.get("operation")
    version = request.get("version")
    arguments = request.get("arguments")
    if (
        not isinstance(operation, str)
        or not isinstance(version, str)
        or not isinstance(arguments, Mapping)
    ):
        raise TypedOperationInputError("Inline operation request is incomplete")
    if operation not in INLINE_OPERATIONS:
        raise TypedOperationInputError("Inline operation is not supported")
    result: list[str] = [
        operation,
        "--schema-digest",
        operation_request_schema_digest(operation, version),
        "--apply",
    ]

    def selector_tokens(value: Any) -> tuple[str, ...]:
        if not isinstance(value, Mapping):
            raise TypedOperationInputError("Inline selector is not an object")
        kind = value.get("kind")
        if kind in {"id", "path"}:
            raw = value.get("value")
            token = (
                "id-integer"
                if kind == "id" and isinstance(raw, int) and not isinstance(raw, bool)
                else "id-string"
                if kind == "id"
                else "path"
            )
            return (token, str(raw))
        if kind == "exact-type-name":
            return (kind, str(value.get("type")), str(value.get("name")))
        if kind == "direct-child":
            return (kind, str(value.get("type")), *selector_tokens(value.get("parent")))
        if kind == "scoped-name":
            return (
                kind,
                str(value.get("type")),
                str(value.get("name")),
                *selector_tokens(value.get("parent")),
            )
        raise TypedOperationInputError("Inline selector kind is unsupported")

    def scalar_tokens(value: Any) -> tuple[str, str]:
        value_type = (
            "boolean"
            if isinstance(value, bool)
            else "integer"
            if isinstance(value, int)
            else "number"
            if isinstance(value, float)
            else "string"
        )
        return value_type, (
            "true" if value is True else "false" if value is False else str(value)
        )

    if operation in {"debug.restartWaapiServers", "debug.testAssert", "debug.testCrash"}:
        pass
    elif operation in {"debug.setAsserts", "debug.setAutomationMode"}:
        result.extend(("--enable", scalar_tokens(arguments["enable"])[1]))
    elif operation == "audio.importTabDelimited":
        result.extend(("--import-file", str(arguments["import_file"])))
        result.extend(("--import-location", *selector_tokens(arguments["import_location"])))
        result.extend(("--import-language", str(arguments["import_language"])))
        for name, flag in (
            ("import_operation", "--import-operation"),
            ("auto_add_to_source_control", "--auto-add"),
            ("auto_check_out_to_source_control", "--auto-check-out"),
        ):
            if name in arguments:
                result.extend((flag, scalar_tokens(arguments[name])[1]))
    elif operation == "soundbank.processDefinitionFiles":
        for path in arguments["files"]:
            result.extend(("--file", str(path)))
        result.extend(("--io-root", str(arguments["io_root"])))
    elif operation in {"switchContainer.addAssignment", "switchContainer.removeAssignment"}:
        for name, flag in (
            ("switch_container", "--switch-container"),
            ("child", "--child"),
            ("state_or_switch", "--state-or-switch"),
        ):
            result.extend((flag, *selector_tokens(arguments[name])))
    elif operation in {"object.setName", "object.setNotes"}:
        result.extend(("--object", *selector_tokens(arguments["object"])))
        result.extend(("--text", str(arguments["value"])))
    elif operation in {"object.delete", "object.copy", "object.move"}:
        result.extend(("--object", *selector_tokens(arguments["object"])))
        if "parent" in arguments:
            result.extend(("--parent", *selector_tokens(arguments["parent"])))
        for name, flag in (
            ("on_name_conflict", "--on-name-conflict"),
            ("auto_add_to_source_control", "--auto-add"),
            ("auto_check_out_to_source_control", "--auto-check-out"),
        ):
            if name in arguments:
                result.extend((flag, scalar_tokens(arguments[name])[1]))
    elif operation == "object.setProperty":
        result.extend(("--object", *selector_tokens(arguments["object"])))
        result.extend(("--property", str(arguments["property"])))
        value_type, value = scalar_tokens(arguments["value"])
        result.extend(("--value", value_type, value))
        if "platform" in arguments:
            result.extend(("--platform", str(arguments["platform"])))
    elif operation == "object.setReference":
        result.extend(("--object", *selector_tokens(arguments["object"])))
        result.extend(("--reference", str(arguments["reference"])))
        if arguments["target"] is None:
            result.append("--clear")
        else:
            result.extend(("--target", *selector_tokens(arguments["target"])))
        if "platform" in arguments:
            result.extend(("--platform", str(arguments["platform"])))
    elif operation == "object.setLinked":
        result.extend(("--object", *selector_tokens(arguments["object"])))
        result.extend(("--property", str(arguments["property"])))
        result.extend(("--platform", str(arguments["platform"])))
        result.extend(("--linked", scalar_tokens(arguments["linked"])[1]))
    elif operation == "ui.captureScreen":
        if "view_name" in arguments:
            result.extend(("--view-name", str(arguments["view_name"])))
        if "view_channel" in arguments:
            result.extend(("--view-channel", str(arguments["view_channel"])))
        if "rect" in arguments:
            result.extend(
                ("--rect", *(str(arguments["rect"][key]) for key in ("x", "y", "width", "height")))
            )
    elif operation == "ui.commands.execute":
        result.extend(("--command", str(arguments["command"])))
        for name, flag in (("objects", "--command-object"), ("platforms", "--command-platform"), ("files", "--file")):
            for value in arguments.get(name, ()):
                result.extend((flag, str(value)))
        if "value" in arguments:
            value_type, value = scalar_tokens(arguments["value"])
            result.extend(("--value", value_type, value))
    else:
        raise TypedOperationInputError("Inline operation serializer is incomplete")
    # Re-run the strict materializer through the equivalent values indirectly by
    # requiring the canonical parser before returning the stable argv.
    try:
        parse_operation_request(request, expected_version=version)
    except OperationContractError as exc:
        raise TypedOperationInputError(str(exc)) from exc
    return tuple(result)


def inline_operation_contract(operation: str, version: str) -> dict[str, Any]:
    """Return one concise, exact-version continuation for public discovery."""

    if operation not in INLINE_OPERATIONS:
        raise TypedOperationInputError(f"No inline typed adapter exists for {operation!r}")
    fields: list[str] = (
        []
        if operation in {
            "debug.restartWaapiServers",
            "debug.testAssert",
            "debug.testCrash",
        }
        else ["--enable true|false"]
        if operation in {"debug.setAsserts", "debug.setAutomationMode"}
        else
        [
            "--switch-container SELECTOR",
            "--child SELECTOR",
            "--state-or-switch SELECTOR",
        ]
        if operation
        in {"switchContainer.addAssignment", "switchContainer.removeAssignment"}
        else (
            ["--file ABSOLUTE_PATH (repeat 1-32)", "--io-root ABSOLUTE_PATH"]
            if operation == "soundbank.processDefinitionFiles"
            else (
                [
                    "--import-file ABSOLUTE_PATH",
                    "--import-location SELECTOR",
                    "--import-language LANGUAGE",
                    "--import-operation createNew|useExisting|replaceExisting (optional)",
                    "--auto-add true|false (optional)",
                    *(
                        ["--auto-check-out true|false (optional)"]
                        if version in {"2023.1", "2024.1", "2025.1"}
                        else []
                    ),
                ]
                if operation == "audio.importTabDelimited"
                else ["--view-name NAME (optional)", "--view-channel 1|2|3|4 (optional)", "--rect X Y WIDTH HEIGHT (optional)"]
                if operation == "ui.captureScreen"
                else ["--command ID", "--command-object VALUE (repeat)", "--command-platform VALUE (repeat)", "--value TYPE VALUE (optional)", "--file ABSOLUTE_PATH (2025.1 only; repeat)"]
                if operation == "ui.commands.execute"
                else ["--object SELECTOR"]
            )
        )
    )
    schema_digest = operation_request_schema_digest(operation, version)
    continuation: dict[str, Any] = {
        "subcommand": "typed-operation",
        "operation": operation,
        "schema_digest": schema_digest,
        "gateway_argv_prefix": [
            "typed-operation",
            operation,
            "--schema-digest",
            schema_digest,
            "--apply",
        ],
        "required_flag": "--apply",
    }
    if operation in {
        "debug.restartWaapiServers",
        "debug.setAsserts",
        "debug.setAutomationMode",
        "debug.testAssert",
        "debug.testCrash",
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
        "soundbank.processDefinitionFiles",
        "audio.importTabDelimited",
        "ui.captureScreen",
        "ui.commands.execute",
    }:
        pass
    elif operation in {"object.setName", "object.setNotes"}:
        fields.append("--text TEXT")
    elif operation == "object.delete":
        fields.append("--auto-check-out true|false (optional; 2023.1+)")
    elif operation in {"object.copy", "object.move"}:
        fields.extend(["--parent SELECTOR", "--on-name-conflict fail|rename (optional)"])
        fields.append("--auto-check-out true|false (optional; 2023.1+)")
        if operation == "object.copy":
            fields.append("--auto-add true|false (optional; 2023.1+)")
    elif operation == "object.setProperty":
        fields.extend(
            ["--property TOKEN", "--value TYPE VALUE", "--platform PLATFORM (optional)"]
        )
    elif operation == "object.setReference":
        fields.extend(
            ["--reference TOKEN", "--platform PLATFORM (optional)"]
        )
        continuation["target_choice"] = ["--target SELECTOR", "--clear"]
    else:
        fields.extend(["--property TOKEN", "--platform PLATFORM", "--linked true|false"])
    continuation["fields"] = fields
    contract = {
        "contract": INLINE_OPERATION_CONTRACT,
        "operation": operation,
        "version": version,
        "schema_digest": schema_digest,
        "input_shape": (
            "zero"
            if operation
            in {
                "debug.restartWaapiServers",
                "debug.testAssert",
                "debug.testCrash",
            }
            else "inline"
        ),
        "selector_grammar": (
            "id-string VALUE | id-integer VALUE | path VALUE | "
            "exact-type-name TYPE NAME | direct-child TYPE PARENT_ID_OR_PATH_SELECTOR | "
            "scoped-name TYPE NAME PARENT_ID_OR_PATH_SELECTOR; "
            "PARENT_ID_OR_PATH_SELECTOR = id-string VALUE | id-integer VALUE | path VALUE"
        ),
        "bounds": {
            "value_utf8_bytes": MAX_INLINE_OPERATION_VALUE_BYTES,
            "canonical_request_bytes": MAX_INLINE_OPERATION_REQUEST_BYTES,
        },
        "continuation": continuation,
    }
    if contract["input_shape"] == "zero":
        terminal = {
            "debug.restartWaapiServers": {
                "expected_disconnect": True,
                "process_expectation": (
                    "wwise_process_remains_running_waapi_servers_restart"
                ),
            },
            "debug.testAssert": {
                "expected_disconnect": False,
                "process_expectation": (
                    "assert_handler_or_dialog_is_host_build_dependent"
                ),
            },
            "debug.testCrash": {
                "expected_disconnect": True,
                "process_expectation": "wwise_process_termination",
            },
        }[operation]
        contract["business_values_required"] = False
        contract["risk"] = {
            "dangerous_host_control": True,
            **terminal,
            "authorization": "explicit_confirmation_only",
            "terminal_result": "indeterminate_after_single_dispatch_attempt",
            "automatic_retry": False,
            "reconnect_and_repeat": False,
            "generic_verify_allowed": False,
        }
    if operation.startswith("debug."):
        contract.pop("selector_grammar", None)
    if operation == "object.setProperty":
        contract["metadata_dependency"] = {
            "token": "property",
            "source": "successful live metadata discover for this object/class scope",
            "never_infer": True,
            "preview_revalidates": True,
            "accepted_value_types": ["string", "integer", "number", "boolean"],
        }
    elif operation in {"object.setReference", "object.setLinked"}:
        contract["metadata_dependency"] = {
            "token": "reference" if operation == "object.setReference" else "property_or_reference",
            "source": "successful live metadata discover for this object/class scope",
            "never_infer": True,
            "preview_revalidates": True,
        }
    return contract


def draft_operation_request_contract(operation: str, version: str) -> TypedRequestContract:
    """Compile one complex dedicated operation through the shared Typed Core."""

    if operation not in DRAFT_TYPED_OPERATIONS:
        raise TypedOperationInputError(f"No typed Draft adapter exists for {operation!r}")
    machine = operation_request_machine_contract(operation, version)
    # Registry owns semantic leaf truth. Project its intentionally
    # metadata-narrowed scalar leaves into the finite Typed Core exactly as
    # compound children do; live metadata still revalidates the chosen scalar
    # during Preview preparation.
    arguments = _compound_child_typed_schema(
        deepcopy(machine["argument_contract"])
    )
    if not isinstance(arguments, dict):
        raise TypedOperationInputError("Typed Draft argument contract is malformed")
    if operation == "waapi.undoGroup":
        return compile_typed_request_contract(
            version=version,
            uri=operation,
            schema={
                "argsSchema": {
                    "type": "object",
                    "required": ["display_name", "calls"],
                    "additionalProperties": False,
                    "properties": {
                        "display_name": deepcopy(
                            arguments["properties"]["display_name"]
                        ),
                        # Child calls are represented by Adapter-issued handles,
                        # never by a caller-authored nested request document.
                        "calls": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": arguments["properties"]["calls"]["maxItems"],
                            "items": {"type": "string", "pattern": r"^uch1-[0-9a-f]{24}$"},
                        },
                    },
                },
                "optionsSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            graph=load_definition_graph(version),
        )
    if operation != "object.create":
        return compile_typed_request_contract(
            version=version,
            uri=operation,
            schema={
                "argsSchema": arguments,
                "optionsSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            graph=load_definition_graph(version),
        )
    node = {
        "type": "object",
        "required": ["type", "name"],
        "additionalProperties": False,
        "properties": {
            "type": deepcopy(arguments["properties"]["type"]),
            "name": {"type": "string", "minLength": 1},
            "notes": {"type": "string"},
            "properties": deepcopy(arguments["properties"]["properties"]),
            "references": deepcopy(arguments["properties"]["references"]),
            "children": {"type": "array", "items": {"$ref": "#/definitions/objectNode"}},
        },
    }
    arguments["definitions"] = {"objectNode": node}
    arguments["properties"]["children"]["items"] = {"$ref": "#/definitions/objectNode"}
    return compile_typed_request_contract(
        version=version,
        uri=operation,
        schema={
            "argsSchema": arguments,
            "optionsSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        graph=load_definition_graph(version),
    )


def compound_child_operations(version: str) -> Mapping[str, str]:
    """Map each permitted child input key to its exact native URI."""

    allowed = UNDO_GROUP_INNER_URIS_BY_VERSION.get(version)
    if allowed is None:
        raise TypedOperationInputError(f"Unsupported Wwise version {version!r}")
    by_uri: dict[str, list[str]] = {}
    for spec in list_operation_specs():
        if (
            spec.name not in {"waapi.call", "waapi.undoGroup"}
            and version in spec.supported_versions
            and spec.uri in allowed
        ):
            by_uri.setdefault(spec.uri, []).append(spec.name)
    result: dict[str, str] = {}
    for uri in sorted(allowed):
        named = by_uri.get(uri, [])
        if len(named) > 1:
            raise TypedOperationInputError(
                f"Undo Group member {uri!r} has ambiguous dedicated operations"
            )
        result[named[0] if named else uri] = uri
    return result


def compound_child_request_contract(
    child_operation: str,
    version: str,
) -> TypedRequestContract:
    """Compile one exact allowed Undo child without a raw request seam."""

    uri = compound_child_operations(version).get(child_operation)
    if uri is None:
        raise TypedOperationInputError(
            f"{child_operation!r} is not an approved typed Undo Group child"
        )
    if child_operation.startswith("ak."):
        return request_contract(version, uri)
    machine = operation_request_machine_contract(child_operation, version)
    arguments = _compound_child_typed_schema(
        deepcopy(machine["argument_contract"])
    )
    return compile_typed_request_contract(
        version=version,
        uri=f"undo-child:{child_operation}",
        schema={
            "argsSchema": arguments,
            "optionsSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        graph=load_definition_graph(version),
    )


def _compound_child_typed_schema(value: object) -> object:
    """Project Registry semantic leaves into the finite shared Typed Core."""

    if not isinstance(value, dict):
        return value
    projected = deepcopy(value)
    properties = projected.get("properties")
    if isinstance(properties, dict):
        projected["properties"] = {
            key: _compound_child_typed_schema(item)
            for key, item in properties.items()
        }
    items = projected.get("items")
    if isinstance(items, dict):
        projected["items"] = _compound_child_typed_schema(items)
    for keyword in ("oneOf", "anyOf"):
        branches = projected.get(keyword)
        if isinstance(branches, list):
            projected[keyword] = [
                _compound_child_typed_schema(item) for item in branches
            ]
    branches = projected.get("oneOf")
    if isinstance(branches, list):
        flattened: list[object] = []
        for branch in branches:
            if isinstance(branch, dict) and set(branch).issubset(
                {"oneOf", "description"}
            ) and isinstance(branch.get("oneOf"), list):
                flattened.extend(branch["oneOf"])
            else:
                flattened.append(branch)
        projected["oneOf"] = flattened
    if not any(
        key in projected
        for key in (
            "type",
            "oneOf",
            "anyOf",
            "const",
            "properties",
            "items",
            "$ref",
        )
    ):
        projected["oneOf"] = [
            {"type": "string"},
            {"type": "integer"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
        ]
    return projected


__all__ = [
    "INLINE_OPERATION_CONTRACT",
    "INLINE_OPERATIONS",
    "DRAFT_TYPED_OPERATIONS",
    "INLINE_TYPED_INPUT_MODE",
    "MAX_INLINE_OPERATION_REQUEST_BYTES",
    "MAX_INLINE_OPERATION_VALUE_BYTES",
    "TypedOperationInputError",
    "inline_operation_contract",
    "draft_operation_request_contract",
    "compound_child_operations",
    "compound_child_request_contract",
    "materialize_inline_operation_request",
    "inline_operation_cli_arguments",
]

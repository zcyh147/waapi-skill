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
from .typed_requests import TypedRequestContract, compile_typed_request_contract
from .operation_registry import (
    INLINE_TYPED_INPUT_MODE,
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    operation_request_schema_digest,
    operation_request_machine_contract,
    parse_operation_request,
    validate_operation_identity_fragment,
)


INLINE_OPERATION_CONTRACT = "waapi-skill.inline-operation-input/v1"
INLINE_OPERATIONS = frozenset(
    {
        "object.setLinked",
        "object.setName",
        "object.setNotes",
        "object.setProperty",
        "object.setReference",
        "object.delete",
        "object.copy",
        "object.move",
    }
)
DRAFT_TYPED_OPERATIONS = frozenset({"object.create"})
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
    if operation in {"object.setName", "object.setNotes"}:
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


def inline_operation_contract(operation: str, version: str) -> dict[str, Any]:
    """Return one concise, exact-version continuation for public discovery."""

    if operation not in INLINE_OPERATIONS:
        raise TypedOperationInputError(f"No inline typed adapter exists for {operation!r}")
    fields: list[str] = ["--object SELECTOR"]
    continuation: dict[str, Any] = {
        "subcommand": "typed-operation",
        "operation": operation,
        "required_flag": "--apply",
    }
    if operation in {"object.setName", "object.setNotes"}:
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
        "schema_digest": operation_request_schema_digest(operation, version),
        "input_shape": "inline",
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
    arguments = deepcopy(machine["argument_contract"])
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
    "materialize_inline_operation_request",
]

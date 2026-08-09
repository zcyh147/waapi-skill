"""Closed, typed composition for narrowly reviewed operation fragments.

The Composer never accepts a native WAAPI payload or a complete operation
request.  It owns a small fact model and materializes one canonical request
from Registry-projected fragments.  Live resolution and mutation execution
remain downstream responsibilities of the normal transaction ingress.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any, Callable, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .operation_registry import (
    OperationContractError,
    object_set_composer_fragment_contract,
    parse_operation_request,
    validate_object_set_composer_fragment,
)


OPERATION_DRAFT_ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
OPERATION_COMPOSITION_CONTRACT = "waapi-skill.operation-composition/v1"
OPERATION_COMPOSER_CONTRACT = "waapi-skill.operation-composer/v1"
OBJECT_SET_COMPOSER_OPERATION = "object.set"
MAX_COMPOSER_ACTION_BYTES = 32 * 1024
_TARGET_HANDLE_PATTERN = re.compile(r"^odh1-[0-9a-f]{24}$")


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


def operation_composer_contract(operation: str, version: str) -> dict[str, Any]:
    """Return the one additive Adapter contract, derived from the Registry."""

    if operation != OBJECT_SET_COMPOSER_OPERATION:
        raise OperationComposerError(
            f"No Operation Composer Adapter is available for {operation!r}.",
            error_code="OPERATION_DRAFT_ADAPTER_UNAVAILABLE",
            details={"operation": operation, "version": version},
        )
    fragments = object_set_composer_fragment_contract(version)
    return {
        "contract": OPERATION_COMPOSER_CONTRACT,
        "operation": operation,
        "version": version,
        "action_contract": OPERATION_DRAFT_ACTION_CONTRACT,
        "composition_contract": OPERATION_COMPOSITION_CONTRACT,
        "actions": [
            "add_target",
            "set_property",
            "remove_property",
            "remove_target",
        ],
        "limits": {
            "targets": 1,
            "properties_per_target": fragments["limits"]["properties_per_target"],
            "action_bytes": MAX_COMPOSER_ACTION_BYTES,
        },
        "registry_fragments": fragments,
        "complete_request_is_never_an_action": True,
    }


def operation_composer_digest(operation: str, version: str) -> str:
    return canonical_sha256(operation_composer_contract(operation, version))


def new_composition(operation: str, version: str) -> dict[str, Any]:
    operation_composer_contract(operation, version)
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
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
    if action_size > MAX_COMPOSER_ACTION_BYTES:
        raise OperationComposerError(
            "Operation Draft action exceeds its fixed byte ceiling.",
            details={
                "size_bytes": action_size,
                "limit_bytes": MAX_COMPOSER_ACTION_BYTES,
            },
        )
    if action.get("contract") != OPERATION_DRAFT_ACTION_CONTRACT:
        raise OperationComposerError(
            f"action contract must be {OPERATION_DRAFT_ACTION_CONTRACT!r}."
        )
    action_name = action.get("action")
    if action_name == "add_target":
        _require_exact_keys(
            action,
            required=("contract", "action", "selector"),
            label="add_target action",
        )
        if normalized["targets"]:
            raise OperationComposerError(
                "This Composer version supports exactly one target.",
                details={"limit": 1},
            )
        selector = _validate_fragment(
            version,
            fragment="target_selector",
            payload=action.get("selector"),
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
                "properties": [],
            }
        )
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
    if action_name == "remove_target":
        _require_exact_keys(
            action,
            required=("contract", "action", "target_handle"),
            label="remove_target action",
        )
        target = _target_for_handle(normalized, action.get("target_handle"))
        normalized["targets"].remove(target)
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
    targets = normalized["targets"]
    if len(targets) != 1:
        raise OperationComposerError(
            "Operation Draft needs exactly one target before it can be checked.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
            details={"target_count": len(targets), "required": 1},
        )
    target = targets[0]
    properties = target["properties"]
    if not properties:
        raise OperationComposerError(
            "Operation Draft target needs at least one scalar property.",
            error_code="OPERATION_DRAFT_INCOMPLETE",
            details={"target_handle": target["handle"]},
        )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": operation,
        "arguments": {
            "objects": [
                {
                    "object": dict(target["selector"]),
                    "properties": [dict(item) for item in properties],
                }
            ]
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


def composition_projection(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_composition(composition, operation=operation, version=version)
    facts = [
        {
            "handle": target["handle"],
            "selector": dict(target["selector"]),
            "properties": [dict(item) for item in target["properties"]],
        }
        for target in normalized["targets"]
    ]
    missing: list[str] = []
    if not facts:
        missing.append("target")
    else:
        handle = facts[0]["handle"]
        if not facts[0]["properties"]:
            missing.append(f"targets[{handle}].properties")
    if not facts:
        allowed = ["add_target", "inspect", "cancel"]
    elif missing:
        allowed = ["set_property", "remove_target", "inspect", "cancel"]
    else:
        allowed = [
            "set_property",
            "remove_property",
            "remove_target",
            "check",
            "inspect",
            "cancel",
        ]
    return {
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
    _require_json_object(composition, label="composition")
    _require_exact_keys(
        composition,
        required=("contract", "targets"),
        label="composition",
    )
    if composition.get("contract") != OPERATION_COMPOSITION_CONTRACT:
        raise OperationComposerError("Operation Draft composition contract is invalid.")
    raw_targets = composition.get("targets")
    if not isinstance(raw_targets, list) or len(raw_targets) > 1:
        raise OperationComposerError(
            "Operation Draft composition must contain zero or one target.",
            details={"limit": 1},
        )
    targets: list[dict[str, Any]] = []
    handles: set[str] = set()
    for raw_target in raw_targets:
        _require_json_object(raw_target, label="composition target")
        _require_exact_keys(
            raw_target,
            required=("handle", "selector", "properties"),
            label="composition target",
        )
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
        targets.append(
            {
                "handle": handle,
                "selector": selector,
                "properties": properties,
            }
        )
    return {"contract": OPERATION_COMPOSITION_CONTRACT, "targets": targets}


def _materialize_if_complete(
    operation: str,
    version: str,
    composition: Mapping[str, Any],
) -> None:
    projection = composition_projection(operation, version, composition)
    if not projection["missing_fields"]:
        materialize_operation_request(operation, version, composition)


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


__all__ = [
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

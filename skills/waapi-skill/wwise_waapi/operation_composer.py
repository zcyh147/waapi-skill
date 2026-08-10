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
    operation_composer_contract(operation, version)
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

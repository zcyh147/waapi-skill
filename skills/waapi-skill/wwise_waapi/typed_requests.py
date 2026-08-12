"""Schema-derived typed request facts for the public Gateway.

This module owns the deterministic conversion from short, typed facts into a
WAAPI ``args``/``options`` pair.  Callers never submit a JSON request tree:
they copy opaque field handles from :func:`request_contract` and the Gateway
materializes the tree under the exact reflected versioned schema.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256
from .capabilities import CapabilityCatalog, CapabilityNotFoundError
from .schema_inventory import (
    DefinitionGraph,
    SchemaInventoryError,
    load_definition_graph,
    resolve_schema_reference,
)
from .versions import SUPPORTED_WWISE_VERSION_KEYS


TYPED_REQUEST_CONTRACT = "waapi-skill.typed-request/v1"
TYPED_REQUEST_SCHEMA_CONTRACT = "waapi-skill.typed-request-schema/v1"
TYPED_REQUEST_HANDLE_PREFIX = "trh1-"
TYPED_REQUEST_TRACER_URI = "ak.wwise.core.profiler.getVoiceContributions"
MAX_TYPED_REQUEST_FACTS = 256
MAX_TYPED_ARRAY_ITEMS = 128
MAX_TYPED_STRING_BYTES = 16 * 1024
MAX_TYPED_REQUEST_BYTES = 64 * 1024
MAX_TYPED_SCHEMA_NODES = 1024
MAX_TYPED_SCHEMA_DEPTH = 16


class TypedRequestError(ValueError):
    """A typed request cannot be disclosed or materialized safely."""


@dataclass(frozen=True, slots=True)
class TypedFieldContract:
    """One exact schema location addressed by a Gateway-owned handle."""

    handle: str
    section: str
    name: str
    path: tuple[str, ...]
    required: bool
    shape: str
    variants: tuple[Mapping[str, Any], ...]
    parent_handle: str | None = None
    minimum_items: int | None = None
    maximum_items: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "handle": self.handle,
            "section": self.section,
            "name": self.name,
            "path": [self.section, *self.path],
            "required": self.required,
            "shape": self.shape,
            "accepted_types": sorted(
                {
                    str(variant["type"])
                    for variant in self.variants
                    if isinstance(variant.get("type"), str)
                }
            ),
        }
        enum_values = [
            value
            for variant in self.variants
            for value in variant.get("enum", ())
            if isinstance(variant.get("enum"), list)
        ]
        if enum_values:
            payload["enum"] = enum_values
        if self.shape == "array":
            payload["minimum_items"] = self.minimum_items
            payload["maximum_items"] = self.maximum_items
        return payload


@dataclass(frozen=True, slots=True)
class TypedRequestContract:
    """One immutable exact-version request construction contract."""

    version: str
    uri: str
    schema_digest: str
    fields: tuple[TypedFieldContract, ...]

    @property
    def fields_by_handle(self) -> Mapping[str, TypedFieldContract]:
        return {field.handle: field for field in self.fields}

    def as_gateway_payload(self) -> dict[str, Any]:
        return {
            "contract": TYPED_REQUEST_SCHEMA_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "request-schema",
            "version": self.version,
            "uri": self.uri,
            "input_shape": "inline",
            "schema_digest": self.schema_digest,
            "fields": [field.as_dict() for field in self.fields],
            "continuation": {
                "subcommand": "typed-call",
                "uri": self.uri,
                "schema_digest": self.schema_digest,
                "fact_flags": {
                    "scalar": "--set <field_handle> <type> <value>",
                    "array_item": "--append <field_handle> <type> <value>",
                    "container": "--present <object_or_array_handle>",
                },
            },
        }


@dataclass(frozen=True, slots=True)
class TypedRequestFact:
    action: str
    handle: str
    value_type: str
    value: str


@dataclass(frozen=True, slots=True)
class MaterializedTypedRequest:
    version: str
    uri: str
    schema_digest: str
    args: Mapping[str, Any]
    options: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": TYPED_REQUEST_CONTRACT,
            "version": self.version,
            "uri": self.uri,
            "schema_digest": self.schema_digest,
            "args": dict(self.args),
            "options": dict(self.options),
        }


def request_contract(version: str, uri: str) -> TypedRequestContract:
    """Compile the first reviewed read-only typed tracer contract."""

    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise TypedRequestError(f"Unsupported Wwise version {version!r}")
    if uri != TYPED_REQUEST_TRACER_URI:
        raise TypedRequestError(
            f"WAAPI URI {uri!r} has not migrated to the typed request surface"
        )
    try:
        capability = CapabilityCatalog().describe(version, uri)
    except CapabilityNotFoundError as exc:
        raise TypedRequestError(str(exc)) from exc
    if capability.item_type != "function":
        raise TypedRequestError(f"Typed request tracer requires a function URI: {uri}")
    graph = load_definition_graph(version)
    return compile_typed_request_contract(
        version=version,
        uri=uri,
        schema=capability.schema,
        graph=graph,
    )


def compile_typed_request_contract(
    *,
    version: str,
    uri: str,
    schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> TypedRequestContract:
    """Compile one already-authorized function schema into opaque field handles."""

    if graph.version != version:
        raise TypedRequestError("Typed request definition graph version does not match")
    schema_digest = canonical_sha256(
        {
            "contract": TYPED_REQUEST_SCHEMA_CONTRACT,
            "version": version,
            "uri": uri,
            "schema": schema,
            "definition_graph_sha256": graph.inventory_sha256,
            "limits": {
                "facts": MAX_TYPED_REQUEST_FACTS,
                "array_items": MAX_TYPED_ARRAY_ITEMS,
                "string_bytes": MAX_TYPED_STRING_BYTES,
                "request_bytes": MAX_TYPED_REQUEST_BYTES,
                "schema_nodes": MAX_TYPED_SCHEMA_NODES,
                "schema_depth": MAX_TYPED_SCHEMA_DEPTH,
            },
        }
    )
    fields: list[TypedFieldContract] = []
    node_count = [0]
    for section_name in ("args", "options"):
        schema_name = f"{section_name}Schema"
        root = schema.get(schema_name)
        if not isinstance(root, Mapping):
            raise TypedRequestError(f"{uri} {schema_name} must be an object")
        expanded_root = _expanded_schema(root, root_schema=root, graph=graph)
        _collect_object_fields(
            expanded_root,
            section=section_name,
            path=(),
            root_schema=root,
            graph=graph,
            schema_digest=schema_digest,
            fields=fields,
            node_count=node_count,
            depth=0,
            parent_handle=None,
        )
    return TypedRequestContract(
        version=version,
        uri=uri,
        schema_digest=schema_digest,
        fields=tuple(fields),
    )


def materialize_typed_request(
    contract: TypedRequestContract,
    *,
    schema_digest: str,
    facts: Sequence[TypedRequestFact],
) -> MaterializedTypedRequest:
    """Atomically validate typed facts and materialize canonical request trees."""

    if schema_digest != contract.schema_digest:
        raise TypedRequestError(
            "Typed request schema digest is stale or belongs to another version"
        )
    for field in contract.fields:
        expected_handle = TYPED_REQUEST_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": contract.schema_digest,
                "section": field.section,
                "path": list(field.path),
            }
        )[:24]
        if field.handle != expected_handle:
            raise TypedRequestError("Typed request contract handles are corrupt or stale")
    if len(facts) > MAX_TYPED_REQUEST_FACTS:
        raise TypedRequestError(
            f"Typed request accepts at most {MAX_TYPED_REQUEST_FACTS} facts"
        )
    by_handle = contract.fields_by_handle
    scalar_values: dict[str, Any] = {}
    array_values: dict[str, list[Any]] = {}
    present_handles: set[str] = set()
    for fact in facts:
        field = by_handle.get(fact.handle)
        if field is None:
            raise TypedRequestError("Typed request field handle is unknown or stale")
        if fact.action == "set":
            if field.shape != "scalar":
                raise TypedRequestError(f"Field {field.name!r} requires --append")
            if fact.handle in scalar_values:
                raise TypedRequestError(f"Field {field.name!r} may be set only once")
            scalar_values[fact.handle] = _parse_typed_scalar(
                fact.value_type,
                fact.value,
                variants=field.variants,
                field_name=field.name,
            )
        elif fact.action == "append":
            if field.shape != "array":
                raise TypedRequestError(f"Field {field.name!r} requires --set")
            values = array_values.setdefault(fact.handle, [])
            maximum_items = min(
                MAX_TYPED_ARRAY_ITEMS,
                field.maximum_items
                if field.maximum_items is not None
                else MAX_TYPED_ARRAY_ITEMS,
            )
            if len(values) >= maximum_items:
                raise TypedRequestError(
                    f"Field {field.name!r} accepts at most {maximum_items} items"
                )
            values.append(
                _parse_typed_scalar(
                    fact.value_type,
                    fact.value,
                    variants=field.variants,
                    field_name=field.name,
                )
            )
            present_handles.add(fact.handle)
        elif fact.action == "present":
            if field.shape not in {"object", "array"}:
                raise TypedRequestError(
                    f"Field {field.name!r} is not an object or array container"
                )
            if fact.handle in present_handles:
                raise TypedRequestError(
                    f"Field {field.name!r} may be marked present only once"
                )
            present_handles.add(fact.handle)
        else:
            raise TypedRequestError(f"Unsupported typed fact action {fact.action!r}")

    for handle in (*scalar_values, *array_values, *present_handles):
        parent_handle = by_handle[handle].parent_handle
        while parent_handle is not None:
            present_handles.add(parent_handle)
            parent_handle = by_handle[parent_handle].parent_handle

    args: dict[str, Any] = {}
    options: dict[str, Any] = {}
    materialized_containers: set[str] = set()
    for field in sorted(contract.fields, key=lambda item: len(item.path)):
        parent_present = (
            field.parent_handle is None
            or field.parent_handle in materialized_containers
        )
        present = (
            field.handle in scalar_values
            or field.handle in array_values
            or field.handle in present_handles
        )
        if field.required and parent_present and field.shape in {"object", "array"}:
            present = True
        if field.required and parent_present and field.shape == "scalar" and not present:
            raise TypedRequestError(f"Required field {field.name!r} is missing")
        if not present:
            continue
        if field.shape == "object":
            value: Any = {}
            materialized_containers.add(field.handle)
        elif field.shape == "array":
            value = list(array_values.get(field.handle, ()))
            materialized_containers.add(field.handle)
        else:
            if field.handle not in scalar_values:
                raise TypedRequestError(f"Required field {field.name!r} is missing")
            value = scalar_values[field.handle]
        if (
            field.shape == "array"
            and field.minimum_items is not None
            and len(value) < field.minimum_items
        ):
            raise TypedRequestError(
                f"Field {field.name!r} requires at least {field.minimum_items} items"
            )
        target = args if field.section == "args" else options
        _set_nested_value(target, field.path, value)
    request = MaterializedTypedRequest(
        version=contract.version,
        uri=contract.uri,
        schema_digest=contract.schema_digest,
        args=args,
        options=options,
    )
    if len(canonical_json_bytes(request.as_dict())) > MAX_TYPED_REQUEST_BYTES:
        raise TypedRequestError(
            f"Typed request exceeds the {MAX_TYPED_REQUEST_BYTES}-byte limit"
        )
    return request


def _collect_object_fields(
    node: Mapping[str, Any],
    *,
    section: str,
    path: tuple[str, ...],
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    schema_digest: str,
    fields: list[TypedFieldContract],
    node_count: list[int],
    depth: int,
    parent_handle: str | None,
) -> None:
    node_count[0] += 1
    if node_count[0] > MAX_TYPED_SCHEMA_NODES or depth > MAX_TYPED_SCHEMA_DEPTH:
        raise TypedRequestError("Typed request schema exceeds its packaged structure limits")
    if node.get("type") != "object":
        raise TypedRequestError(f"Typed request {section} root must be an object")
    if node.get("additionalProperties") is not False:
        raise TypedRequestError(
            "This typed request object requires a later open-map or branch adapter"
        )
    properties = node.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypedRequestError("Typed request object properties must be an object")
    required_raw = node.get("required", [])
    if not isinstance(required_raw, list) or not all(
        isinstance(name, str) for name in required_raw
    ):
        raise TypedRequestError("Typed request required fields must be a string array")
    required = frozenset(required_raw)
    for name, raw_child in properties.items():
        if not isinstance(name, str) or not isinstance(raw_child, Mapping):
            raise TypedRequestError("Typed request properties must contain schema objects")
        child_path = (*path, name)
        child = _expanded_schema(raw_child, root_schema=root_schema, graph=graph)
        child_type = child.get("type")
        handle = TYPED_REQUEST_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": schema_digest,
                "section": section,
                "path": list(child_path),
            }
        )[:24]
        if child_type == "object":
            fields.append(
                TypedFieldContract(
                    handle=handle,
                    section=section,
                    name=name,
                    path=child_path,
                    required=name in required,
                    shape="object",
                    variants=(),
                    parent_handle=parent_handle,
                )
            )
            _collect_object_fields(
                child,
                section=section,
                path=child_path,
                root_schema=root_schema,
                graph=graph,
                schema_digest=schema_digest,
                fields=fields,
                node_count=node_count,
                depth=depth + 1,
                parent_handle=handle,
            )
            continue
        collection = child_type == "array"
        value_schema = child.get("items") if collection else child
        if not isinstance(value_schema, Mapping):
            raise TypedRequestError(f"Typed request field {name!r} has no item schema")
        value_schema = _expanded_schema(
            value_schema,
            root_schema=root_schema,
            graph=graph,
        )
        variants = _scalar_variants(
            value_schema,
            root_schema=root_schema,
            graph=graph,
        )
        fields.append(
            TypedFieldContract(
                handle=handle,
                section=section,
                name=name,
                path=child_path,
                required=name in required,
                shape="array" if collection else "scalar",
                variants=variants,
                parent_handle=parent_handle,
                minimum_items=_optional_nonnegative_integer(
                    child.get("minItems"),
                    label=f"{name}.minItems",
                ),
                maximum_items=_optional_nonnegative_integer(
                    child.get("maxItems"),
                    label=f"{name}.maxItems",
                ),
            )
        )


def _expanded_schema(
    node: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> dict[str, Any]:
    reference = node.get("$ref", node.get("#ref"))
    if reference is None:
        return dict(node)
    if not isinstance(reference, str) or not reference:
        raise TypedRequestError("Typed request schema reference must be non-empty")
    try:
        resolved = resolve_schema_reference(
            reference,
            root_schema=root_schema,
            graph=graph,
        )
    except SchemaInventoryError as exc:
        raise TypedRequestError(str(exc)) from exc
    merged = dict(resolved.target)
    merged.update({key: value for key, value in node.items() if key not in {"$ref", "#ref"}})
    return merged


def _scalar_variants(
    node: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> tuple[Mapping[str, Any], ...]:
    expanded = _expanded_schema(node, root_schema=root_schema, graph=graph)
    branches = expanded.get("oneOf", expanded.get("anyOf"))
    candidates: Sequence[Any] = branches if isinstance(branches, list) else (expanded,)
    variants: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypedRequestError("Typed request scalar branch must be an object")
        resolved = _expanded_schema(candidate, root_schema=root_schema, graph=graph)
        value_type = resolved.get("type")
        if value_type not in {"string", "integer", "number", "boolean", "null"}:
            raise TypedRequestError(
                "This typed request field requires a later complex-shape adapter"
            )
        variants.append(resolved)
    return tuple(variants)


def _parse_typed_scalar(
    value_type: str,
    raw_value: str,
    *,
    variants: Sequence[Mapping[str, Any]],
    field_name: str,
) -> Any:
    if value_type == "string":
        value: Any = raw_value
    elif value_type == "integer":
        if re.fullmatch(r"-?(0|[1-9][0-9]*)", raw_value) is None:
            raise TypedRequestError(f"Field {field_name!r} requires a canonical integer")
        value = int(raw_value)
    elif value_type == "number":
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise TypedRequestError(f"Field {field_name!r} requires a number") from exc
        if not math.isfinite(value):
            raise TypedRequestError(f"Field {field_name!r} requires a finite number")
    elif value_type == "boolean":
        if raw_value not in {"true", "false"}:
            raise TypedRequestError(f"Field {field_name!r} requires true or false")
        value = raw_value == "true"
    elif value_type == "null":
        if raw_value != "null":
            raise TypedRequestError(f"Field {field_name!r} requires the literal null")
        value = None
    else:
        raise TypedRequestError(f"Unsupported typed scalar type {value_type!r}")
    if isinstance(value, str) and len(value.encode("utf-8")) > MAX_TYPED_STRING_BYTES:
        raise TypedRequestError(
            f"Field {field_name!r} exceeds the {MAX_TYPED_STRING_BYTES}-byte string limit"
        )
    matching = [
        variant
        for variant in variants
        if variant.get("type") == value_type
        or (variant.get("type") == "number" and value_type == "integer")
    ]
    if not matching:
        raise TypedRequestError(
            f"Field {field_name!r} does not accept typed value {value_type!r}"
        )
    if not any(_scalar_matches_variant(value, variant) for variant in matching):
        raise TypedRequestError(f"Field {field_name!r} violates its reflected schema")
    return value


def _scalar_matches_variant(value: Any, variant: Mapping[str, Any]) -> bool:
    enum = variant.get("enum")
    if isinstance(enum, list) and value not in enum:
        return False
    minimum = variant.get("minimum")
    maximum = variant.get("maximum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(minimum, (int, float)) and value < minimum:
            return False
        if isinstance(maximum, (int, float)) and value > maximum:
            return False
    pattern = variant.get("pattern")
    if isinstance(value, str) and isinstance(pattern, str):
        try:
            if re.fullmatch(pattern, value) is None:
                return False
        except re.error as exc:
            raise TypedRequestError("Packaged request schema contains an invalid pattern") from exc
    minimum_length = variant.get("minLength")
    if (
        isinstance(value, str)
        and isinstance(minimum_length, int)
        and not isinstance(minimum_length, bool)
        and len(value) < minimum_length
    ):
        return False
    return True


def _set_nested_value(target: dict[str, Any], path: Sequence[str], value: Any) -> None:
    if not path:
        raise TypedRequestError("Typed request field path must not be empty")
    current = target
    for part in path[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict):
            raise TypedRequestError("Typed request field paths overlap")
        current = existing
    current[path[-1]] = value


def _optional_nonnegative_integer(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypedRequestError(f"Typed request schema {label} must be non-negative")
    return value

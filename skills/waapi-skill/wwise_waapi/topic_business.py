"""Gateway-owned business construction for Topic options and event matches."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256
from .typed_requests import (
    MAX_TYPED_ARRAY_ITEMS,
    MAX_TYPED_SCHEMA_DEPTH,
    MaterializedTypedRequest,
    TypedFieldContract,
    TypedRequestFact,
    TypedRequestContract,
    _expanded_schema,
    _parse_typed_scalar,
    _structural_variants,
    materialize_typed_request,
    typed_request_construction_for_values,
)
from .typed_topics import topic_match_contract, topic_options_contract


TOPIC_BUSINESS_CONTRACT = "waapi-skill.topic-business/v1"
_SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean", "null"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class TopicBusinessError(ValueError):
    """One high-level Topic field cannot be compiled without native facts."""


@dataclass(frozen=True, slots=True)
class TopicBusinessFact:
    """One stable business field value; type and native location are inferred."""

    field: str
    value: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class TopicBusinessEmptyFact:
    """One static business container that must be present and empty."""

    field: str


@dataclass(frozen=True, slots=True)
class TopicBusinessEmptyRowFact:
    """One nested complex collection that must be present and empty."""

    collection: str
    parent_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TopicBusinessRowFact:
    """One scalar predicate inside a Gateway-owned complex event row."""

    collection: str
    indices: tuple[int, ...]
    field: str
    value: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class TopicBusinessEntryFact:
    """One exact user expression with a scalar value in an event object."""

    scope: str
    indices: tuple[int, ...]
    key: str
    value: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class TopicBusinessEntryEmptyFact:
    """One exact expression whose value is an empty object or list."""

    scope: str
    indices: tuple[int, ...]
    key: str
    shape: str


@dataclass(frozen=True, slots=True)
class TopicBusinessEntryObjectFact:
    """One field of an exact expression whose value is an object reference."""

    scope: str
    indices: tuple[int, ...]
    key: str
    field: str
    value: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class TopicBusinessEntryRowFact:
    """One row field of an exact expression whose value is an object list."""

    scope: str
    indices: tuple[int, ...]
    key: str
    item_index: int
    field: str
    value: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class TopicBusinessField:
    """Public business field plus its private reflected field candidates."""

    token: str
    cardinality: str
    accepted_value_kinds: tuple[str, ...]
    required: bool
    _candidates: tuple[TypedFieldContract, ...] = field(repr=False, compare=False)
    _branch_parent_handles: frozenset[str] = field(
        repr=False,
        compare=False,
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.token,
            "cardinality": self.cardinality,
            "accepted_value_kinds": list(self.accepted_value_kinds),
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class TopicBusinessEmptyField:
    """One stable static container presence contract."""

    token: str
    shape: str
    _path: tuple[str, ...] = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, str]:
        return {"field": self.token, "empty_shape": self.shape}


@dataclass(frozen=True, slots=True)
class TopicBusinessRowField:
    """One stable scalar field within a complex event row."""

    token: str
    accepted_value_kinds: tuple[str, ...]
    _path: tuple[str, ...] = field(repr=False, compare=False)
    _variants: tuple[Mapping[str, Any], ...] = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.token,
            "accepted_value_kinds": list(self.accepted_value_kinds),
        }


@dataclass(frozen=True, slots=True)
class TopicBusinessRowContract:
    """One complex collection whose exact array structure is Gateway-owned."""

    token: str
    index_depth: int
    fields: tuple[TopicBusinessRowField, ...]
    _path: tuple[str | None, ...] = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.token,
            "index_depth": self.index_depth,
            "fields": [item.as_dict() for item in self.fields],
        }


@dataclass(frozen=True, slots=True)
class TopicBusinessEntryContract:
    """One object scope accepting exact user-authored accessor keys."""

    token: str
    index_depth: int
    accepted_value_kinds: tuple[str, ...]
    object_fields: tuple[TopicBusinessRowField, ...]
    row_fields: tuple[TopicBusinessRowField, ...]
    _path: tuple[str | None, ...] = field(repr=False, compare=False)
    _scalar_variants: tuple[Mapping[str, Any], ...] = field(
        repr=False,
        compare=False,
    )
    _open_object_fields: bool = field(repr=False, compare=False, default=False)
    _open_row_fields: bool = field(repr=False, compare=False, default=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.token,
            "index_depth": self.index_depth,
            "accepted_value_kinds": list(self.accepted_value_kinds),
            "object_fields": [item.as_dict() for item in self.object_fields],
            "row_fields": [item.as_dict() for item in self.row_fields],
            "object_field_mode": (
                "exact-key" if self._open_object_fields else "closed"
            ),
            "row_field_mode": (
                "exact-key" if self._open_row_fields else "closed"
            ),
        }


@dataclass(frozen=True, slots=True)
class TopicBusinessContract:
    """The deep, handle-free Topic interface for one versioned event lane."""

    version: str
    topic: str
    option_fields: tuple[TopicBusinessField, ...]
    match_fields: tuple[TopicBusinessField, ...]
    option_empty_fields: tuple[TopicBusinessEmptyField, ...]
    match_empty_fields: tuple[TopicBusinessEmptyField, ...]
    row_fields: tuple[TopicBusinessRowContract, ...]
    entry_fields: tuple[TopicBusinessEntryContract, ...]
    transitional_boundaries: tuple[Mapping[str, str], ...]
    contract_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": TOPIC_BUSINESS_CONTRACT,
            "version": self.version,
            "topic": self.topic,
            "contract_digest": self.contract_digest,
            "options": [item.as_dict() for item in self.option_fields],
            "event_match": [item.as_dict() for item in self.match_fields],
            "option_empty": [item.as_dict() for item in self.option_empty_fields],
            "event_empty": [item.as_dict() for item in self.match_empty_fields],
            "event_rows": [item.as_dict() for item in self.row_fields],
            "exact_entries": [item.as_dict() for item in self.entry_fields],
            "transitional_boundaries": [
                dict(item) for item in self.transitional_boundaries
            ],
        }

    def as_gateway_dict(
        self,
        *,
        selected_row: str | None = None,
        selected_entry: str | None = None,
        selected_match_group: str | None = None,
        selected_row_field_group: str | None = None,
    ) -> dict[str, Any]:
        """Return the bounded handle-free field tables used by the Gateway."""

        if selected_row is not None and not any(
            row.token == selected_row for row in self.row_fields
        ):
            raise TopicBusinessError(
                f"Unknown event row collection {selected_row!r}"
            )
        if selected_row_field_group is not None and selected_row is None:
            raise TopicBusinessError(
                "Event row field-group disclosure requires one selected row"
            )
        if selected_entry is not None and not any(
            entry.token == selected_entry for entry in self.entry_fields
        ):
            raise TopicBusinessError(
                f"Unknown exact event entry scope {selected_entry!r}"
            )
        match_groups = _business_match_groups(self.match_fields)
        if (
            selected_match_group is not None
            and selected_match_group not in match_groups
        ):
            raise TopicBusinessError(
                f"Unknown event match group {selected_match_group!r}"
            )

        return {
            "contract": TOPIC_BUSINESS_CONTRACT,
            "version": self.version,
            "topic": self.topic,
            "contract_digest": self.contract_digest,
            "options": _gateway_field_table(self.option_fields),
            "event_match_groups": {
                "columns": ["group", "field_count", "field_digest"],
                "rows": [
                    [
                        group,
                        len(fields),
                        canonical_sha256([item.as_dict() for item in fields]),
                    ]
                    for group, fields in match_groups.items()
                ],
                "field_disclosure": (
                    "topic-schema <topic-uri> --match-group <group>"
                ),
            },
            "event_match": _gateway_field_table(
                match_groups.get(selected_match_group, ())
            ),
            "option_empty": [item.as_dict() for item in self.option_empty_fields],
            "event_empty": [item.as_dict() for item in self.match_empty_fields],
            "event_rows": _gateway_row_table(
                self.row_fields,
                selected_row=selected_row,
                selected_field_group=selected_row_field_group,
            ),
            "exact_entries": _gateway_entry_table(
                self.entry_fields,
                selected_entry=selected_entry,
            ),
            "transitional_boundaries": [
                dict(item) for item in self.transitional_boundaries
            ],
        }


@dataclass(frozen=True, slots=True)
class MaterializedTopicBusinessInputs:
    """Exact native subscription inputs compiled from business facts."""

    version: str
    topic: str
    options: Mapping[str, Any]
    match: Mapping[str, Any]
    option_request: MaterializedTypedRequest
    match_request: MaterializedTypedRequest


def topic_business_contract(version: str, topic: str) -> TopicBusinessContract:
    """Compile the static business-value surface for one reflected Topic."""

    options = topic_options_contract(version, topic)
    match = topic_match_contract(version, topic)
    option_fields = _business_fields(options.fields, section="options")
    match_fields = _business_fields(match.fields, section="match")
    option_empty_fields = _business_empty_fields(
        options.fields,
        section="options",
    )
    match_empty_fields = _business_empty_fields(match.fields, section="match")
    row_fields = _business_row_fields(match)
    entry_fields = _business_entry_fields(match)
    boundaries: tuple[Mapping[str, str], ...] = ()
    public_body = {
        "contract": TOPIC_BUSINESS_CONTRACT,
        "version": version,
        "topic": topic,
        "options": [item.as_dict() for item in option_fields],
        "event_match": [item.as_dict() for item in match_fields],
        "option_empty": [item.as_dict() for item in option_empty_fields],
        "event_empty": [item.as_dict() for item in match_empty_fields],
        "event_rows": [item.as_dict() for item in row_fields],
        "exact_entries": [item.as_dict() for item in entry_fields],
        "transitional_boundaries": [dict(item) for item in boundaries],
    }
    return TopicBusinessContract(
        version=version,
        topic=topic,
        option_fields=option_fields,
        match_fields=match_fields,
        option_empty_fields=option_empty_fields,
        match_empty_fields=match_empty_fields,
        row_fields=row_fields,
        entry_fields=entry_fields,
        transitional_boundaries=boundaries,
        contract_digest=canonical_sha256(public_body),
    )


def materialize_topic_business_inputs(
    *,
    version: str,
    topic: str,
    option_facts: Sequence[TopicBusinessFact],
    match_facts: Sequence[TopicBusinessFact],
    option_empty_facts: Sequence[TopicBusinessEmptyFact] = (),
    match_empty_facts: Sequence[TopicBusinessEmptyFact] = (),
    row_facts: Sequence[TopicBusinessRowFact] = (),
    empty_row_facts: Sequence[TopicBusinessEmptyRowFact] = (),
    entry_facts: Sequence[TopicBusinessEntryFact] = (),
    entry_empty_facts: Sequence[TopicBusinessEntryEmptyFact] = (),
    entry_object_facts: Sequence[TopicBusinessEntryObjectFact] = (),
    entry_row_facts: Sequence[TopicBusinessEntryRowFact] = (),
) -> MaterializedTopicBusinessInputs:
    """Compile business values through the existing reflected typed engine."""

    business = topic_business_contract(version, topic)
    options_contract = topic_options_contract(version, topic)
    match_contract = topic_match_contract(version, topic)
    option_typed_facts = _compile_business_facts(
        option_facts,
        business.option_fields,
        label="Topic option",
    )
    match_typed_facts = _compile_business_facts(
        match_facts,
        business.match_fields,
        label="event match",
    )
    try:
        option_request = materialize_typed_request(
            options_contract,
            schema_digest=options_contract.schema_digest,
            facts=option_typed_facts,
        )
        match_request = materialize_typed_request(
            match_contract,
            schema_digest=match_contract.schema_digest,
            facts=match_typed_facts,
        )
        if option_empty_facts:
            option_values = dict(option_request.options)
            _apply_static_empty_facts(
                option_values,
                option_empty_facts,
                business.option_empty_fields,
            )
            construction = typed_request_construction_for_values(
                options_contract,
                args={},
                options=option_values,
            )
            option_request = materialize_typed_request(
                options_contract,
                schema_digest=options_contract.schema_digest,
                facts=construction.facts,
            )
        if (
            match_empty_facts
            or row_facts
            or empty_row_facts
            or entry_facts
            or entry_empty_facts
            or entry_object_facts
            or entry_row_facts
        ):
            match_values = dict(match_request.args)
            _apply_static_empty_facts(
                match_values,
                match_empty_facts,
                business.match_empty_fields,
            )
            _apply_business_rows(
                match_values,
                row_facts,
                business.row_fields,
            )
            _apply_empty_business_rows(
                match_values,
                empty_row_facts,
                business.row_fields,
            )
            _apply_business_entries(
                match_values,
                scalar_facts=entry_facts,
                empty_facts=entry_empty_facts,
                object_facts=entry_object_facts,
                row_facts=entry_row_facts,
                entries=business.entry_fields,
            )
            construction = typed_request_construction_for_values(
                match_contract,
                args=match_values,
                options={},
            )
            match_request = materialize_typed_request(
                match_contract,
                schema_digest=match_contract.schema_digest,
                facts=construction.facts,
            )
    except ValueError as exc:
        raise TopicBusinessError(str(exc)) from exc
    return MaterializedTopicBusinessInputs(
        version=version,
        topic=topic,
        options=dict(option_request.options),
        match=dict(match_request.args),
        option_request=option_request,
        match_request=match_request,
    )


def _business_fields(
    fields: Sequence[TypedFieldContract],
    *,
    section: str,
) -> tuple[TopicBusinessField, ...]:
    groups: dict[tuple[str, ...], list[TypedFieldContract]] = {}
    by_handle = {item.handle: item for item in fields}
    for item in fields:
        if item.shape == "scalar":
            groups.setdefault(item.path, []).append(item)
        elif item.shape == "array" and all(
            variant.get("type") in _SCALAR_TYPES for variant in item.variants
        ):
            groups.setdefault(item.path, []).append(item)
    result: list[TopicBusinessField] = []
    for path, candidates in sorted(groups.items()):
        token = _business_token(path, section=section)
        cardinality = (
            "many" if any(item.shape == "array" for item in candidates) else "one"
        )
        accepted_types = sorted(
            {
                str(variant["type"])
                for item in candidates
                for variant in item.variants
                if variant.get("type") in _SCALAR_TYPES
            }
        )
        required = any(item.required for item in candidates) or any(
            item.parent_handle is not None
            and by_handle.get(item.parent_handle) is not None
            and by_handle[item.parent_handle].required
            for item in candidates
        )
        result.append(
            TopicBusinessField(
                token=token,
                cardinality=cardinality,
                accepted_value_kinds=tuple(
                    _business_kind(value) for value in accepted_types
                ),
                required=required,
                _candidates=tuple(candidates),
                _branch_parent_handles=frozenset(
                    item.parent_handle
                    for item in candidates
                    if item.parent_handle is not None
                    and by_handle[item.parent_handle].shape == "branch"
                ),
            )
        )
    tokens = [item.token for item in result]
    if len(tokens) != len(set(tokens)):
        raise TopicBusinessError("Topic business field names are not unique")
    return tuple(result)


def _business_empty_fields(
    fields: Sequence[TypedFieldContract],
    *,
    section: str,
) -> tuple[TopicBusinessEmptyField, ...]:
    by_path: dict[tuple[str, ...], str] = {}
    for item in fields:
        if item.overlay or item.shape not in {"object", "array", "map"}:
            continue
        shape = "list" if item.shape == "array" else "object"
        prior = by_path.get(item.path)
        if prior is not None and prior != shape:
            raise TopicBusinessError("Topic empty container shape is ambiguous")
        by_path[item.path] = shape
    return tuple(
        TopicBusinessEmptyField(
            token=_business_token(path, section=section),
            shape=shape,
            _path=path,
        )
        for path, shape in sorted(by_path.items())
    )


def _business_row_fields(
    contract: TypedRequestContract,
) -> tuple[TopicBusinessRowContract, ...]:
    rows: dict[str, TopicBusinessRowContract] = {}
    root = contract.schema_roots["args"]

    def walk(
        node: Mapping[str, Any],
        *,
        path: tuple[str | None, ...],
        depth: int,
        active: frozenset[str],
    ) -> None:
        if depth > MAX_TYPED_SCHEMA_DEPTH:
            return
        expanded = _expanded_schema(
            node,
            root_schema=root,
            graph=contract.definition_graph,
        )
        marker = canonical_sha256(expanded)
        if marker in active:
            return
        next_active = active | {marker}
        variants = _structural_variants(
            expanded,
            root_schema=root,
            graph=contract.definition_graph,
        )
        if len(variants) > 1:
            for variant in variants:
                walk(
                    variant,
                    path=path,
                    depth=depth + 1,
                    active=next_active,
                )
            return
        value_type = expanded.get("type")
        if value_type == "array":
            items = expanded.get("items")
            if not isinstance(items, Mapping):
                return
            item_variants = _structural_variants(
                items,
                root_schema=root,
                graph=contract.definition_graph,
            )
            object_variants = tuple(
                variant
                for variant in item_variants
                if _expanded_schema(
                    variant,
                    root_schema=root,
                    graph=contract.definition_graph,
                ).get("type")
                == "object"
            )
            if object_variants:
                logical = tuple(part for part in path if part is not None)
                token = _business_token(logical, section="match")
                fields = _row_scalar_fields(
                    object_variants,
                    root=root,
                    contract=contract,
                )
                existing = rows.get(token)
                candidate = TopicBusinessRowContract(
                    token=token,
                    index_depth=path.count(None),
                    fields=fields,
                    _path=path,
                )
                if existing is not None and existing != candidate:
                    raise TopicBusinessError(
                        f"Topic business row name {token!r} is ambiguous"
                    )
                rows[token] = candidate
                for variant in object_variants:
                    walk(
                        variant,
                        path=path,
                        depth=depth + 1,
                        active=next_active,
                    )
            return
        if value_type != "object":
            return
        properties = expanded.get("properties", {})
        if not isinstance(properties, Mapping):
            return
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            child_expanded = _expanded_schema(
                child,
                root_schema=root,
                graph=contract.definition_graph,
            )
            child_path = (*path, name)
            if child_expanded.get("type") == "array":
                child_path = (*child_path, None)
            walk(
                child,
                path=child_path,
                depth=depth + 1,
                active=next_active,
            )

    walk(root, path=(), depth=0, active=frozenset())
    return tuple(rows[token] for token in sorted(rows))


def _row_scalar_fields(
    variants: Sequence[Mapping[str, Any]],
    *,
    root: Mapping[str, Any],
    contract: TypedRequestContract,
) -> tuple[TopicBusinessRowField, ...]:
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}

    def collect(
        node: Mapping[str, Any],
        *,
        path: tuple[str, ...],
        depth: int,
        active: frozenset[str],
    ) -> None:
        if depth > MAX_TYPED_SCHEMA_DEPTH:
            return
        expanded = _expanded_schema(
            node,
            root_schema=root,
            graph=contract.definition_graph,
        )
        marker = canonical_sha256(expanded)
        if marker in active:
            return
        next_active = active | {marker}
        structural = _structural_variants(
            expanded,
            root_schema=root,
            graph=contract.definition_graph,
        )
        if len(structural) > 1:
            for variant in structural:
                collect(
                    variant,
                    path=path,
                    depth=depth + 1,
                    active=next_active,
                )
            return
        value_type = expanded.get("type")
        if value_type in _SCALAR_TYPES:
            grouped.setdefault(path, []).append(expanded)
            return
        if value_type != "object":
            return
        properties = expanded.get("properties", {})
        if not isinstance(properties, Mapping):
            return
        for name, child in properties.items():
            if isinstance(name, str) and isinstance(child, Mapping):
                collect(
                    child,
                    path=(*path, name),
                    depth=depth + 1,
                    active=next_active,
                )

    for variant in variants:
        collect(variant, path=(), depth=0, active=frozenset())
    result = []
    for path, candidates in sorted(grouped.items()):
        token = _business_token(path, section="match")
        accepted = tuple(
            _business_kind(value_type)
            for value_type in sorted(
                {
                    str(candidate["type"])
                    for candidate in candidates
                    if candidate.get("type") in _SCALAR_TYPES
                }
            )
        )
        result.append(
            TopicBusinessRowField(
                token=token,
                accepted_value_kinds=accepted,
                _path=path,
                _variants=tuple(candidates),
            )
        )
    tokens = [item.token for item in result]
    if len(tokens) != len(set(tokens)):
        raise TopicBusinessError("Topic business row field names are not unique")
    return tuple(result)


def _business_entry_fields(
    contract: TypedRequestContract,
) -> tuple[TopicBusinessEntryContract, ...]:
    root = contract.schema_roots["args"]
    collected: dict[
        tuple[str, tuple[str | None, ...]],
        dict[str, list[Mapping[str, Any]]],
    ] = {}

    def walk(
        node: Mapping[str, Any],
        *,
        path: tuple[str | None, ...],
        depth: int,
        active: frozenset[str],
    ) -> None:
        if depth > MAX_TYPED_SCHEMA_DEPTH:
            return
        expanded = _expanded_schema(
            node,
            root_schema=root,
            graph=contract.definition_graph,
        )
        marker = canonical_sha256(expanded)
        if marker in active:
            return
        next_active = active | {marker}
        structural = _structural_variants(
            expanded,
            root_schema=root,
            graph=contract.definition_graph,
        )
        if len(structural) > 1:
            for variant in structural:
                walk(
                    variant,
                    path=path,
                    depth=depth + 1,
                    active=next_active,
                )
            return
        value_type = expanded.get("type")
        if value_type == "array":
            items = expanded.get("items")
            if isinstance(items, Mapping):
                walk(
                    items,
                    path=path,
                    depth=depth + 1,
                    active=next_active,
                )
            return
        if value_type != "object":
            return
        dynamic_schemas: list[Mapping[str, Any]] = []
        patterns = expanded.get("patternProperties", {})
        if isinstance(patterns, Mapping):
            dynamic_schemas.extend(
                schema
                for schema in patterns.values()
                if isinstance(schema, Mapping)
            )
        additional = expanded.get("additionalProperties")
        if isinstance(additional, Mapping):
            dynamic_schemas.append(additional)
        unrestricted = additional is True
        if dynamic_schemas or unrestricted:
            logical = tuple(part for part in path if part is not None)
            token = (
                _business_token(logical, section="match")
                if logical
                else "event"
            )
            bucket = collected.setdefault(
                (token, path),
                {
                    "scalar": [],
                    "object": [],
                    "array": [],
                    "open_object": [],
                    "open_row": [],
                },
            )
            if unrestricted:
                bucket["scalar"].extend(
                    {"type": value_type}
                    for value_type in (
                        "string",
                        "integer",
                        "number",
                        "boolean",
                        "null",
                    )
                )
                bucket["open_object"].append({"type": "boolean"})
                bucket["open_row"].append({"type": "boolean"})
            for schema in dynamic_schemas:
                for variant in _structural_variants(
                    schema,
                    root_schema=root,
                    graph=contract.definition_graph,
                ):
                    variant_expanded = _expanded_schema(
                        variant,
                        root_schema=root,
                        graph=contract.definition_graph,
                    )
                    variant_type = variant_expanded.get("type")
                    if variant_type in _SCALAR_TYPES:
                        bucket["scalar"].append(variant_expanded)
                    elif variant_type == "object":
                        bucket["object"].append(variant_expanded)
                    elif variant_type == "array":
                        items = variant_expanded.get("items")
                        if isinstance(items, Mapping):
                            item_expanded = _expanded_schema(
                                items,
                                root_schema=root,
                                graph=contract.definition_graph,
                            )
                            if item_expanded.get("type") == "object":
                                bucket["array"].append(item_expanded)
        properties = expanded.get("properties", {})
        if not isinstance(properties, Mapping):
            return
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            child_expanded = _expanded_schema(
                child,
                root_schema=root,
                graph=contract.definition_graph,
            )
            child_path = (*path, name)
            if child_expanded.get("type") == "array":
                child_path = (*child_path, None)
            walk(
                child,
                path=child_path,
                depth=depth + 1,
                active=next_active,
            )

    walk(root, path=(), depth=0, active=frozenset())
    result = []
    seen_tokens: set[str] = set()
    for (token, path), variants in sorted(collected.items()):
        if token in seen_tokens:
            raise TopicBusinessError(
                f"Topic business exact-entry scope {token!r} is ambiguous"
            )
        seen_tokens.add(token)
        scalar_variants = tuple(variants["scalar"])
        result.append(
            TopicBusinessEntryContract(
                token=token,
                index_depth=path.count(None),
                accepted_value_kinds=tuple(
                    _business_kind(value_type)
                    for value_type in sorted(
                        {
                            str(variant["type"])
                            for variant in scalar_variants
                            if variant.get("type") in _SCALAR_TYPES
                        }
                    )
                ),
                object_fields=_row_scalar_fields(
                    variants["object"],
                    root=root,
                    contract=contract,
                ),
                row_fields=_row_scalar_fields(
                    variants["array"],
                    root=root,
                    contract=contract,
                ),
                _path=path,
                _scalar_variants=scalar_variants,
                _open_object_fields=bool(variants["open_object"]),
                _open_row_fields=bool(variants["open_row"]),
            )
        )
    return tuple(result)


def _transitional_boundaries(
    fields: Sequence[TypedFieldContract],
) -> tuple[Mapping[str, str], ...]:
    rows: dict[str, str] = {}
    for item in fields:
        if item.shape == "array" and any(
            variant.get("type") in {"object", "array"}
            for variant in item.variants
        ):
            rows[_business_token(item.path, section="match")] = (
                "complex_collection_requires_business_row_compiler"
            )
        elif (
            item.shape == "map"
            and item.open_map
            and (item.map_patterns or item.additional_variants)
        ):
            rows.setdefault(
                _business_token(item.path, section="match"),
                "dynamic_map_requires_business_entry_compiler",
            )
    return tuple(
        {"business_field": token, "reason": reason}
        for token, reason in sorted(rows.items())
    )


def _compile_business_facts(
    facts: Sequence[TopicBusinessFact],
    fields: Sequence[TopicBusinessField],
    *,
    label: str,
) -> tuple[TypedRequestFact, ...]:
    by_token = {item.token: item for item in fields}
    counts: dict[str, int] = {}
    result: list[TypedRequestFact] = []
    selected_branches: set[str] = set()
    for fact in facts:
        business_field = by_token.get(fact.field)
        if business_field is None:
            raise TopicBusinessError(f"Unknown {label} field {fact.field!r}")
        counts[fact.field] = counts.get(fact.field, 0) + 1
        if business_field.cardinality == "one" and counts[fact.field] > 1:
            raise TopicBusinessError(
                f"{label} field {fact.field!r} accepts one value"
            )
        candidate, value_type = _select_candidate(business_field, fact)
        if candidate.parent_handle in business_field._branch_parent_handles:
            # Branch parents are not part of the same path group. Their handle
            # is nevertheless sealed into every candidate and can be selected
            # directly without disclosing it to the caller.
            if candidate.parent_handle not in selected_branches:
                result.append(
                    TypedRequestFact(
                        "choose",
                        candidate.parent_handle,
                        "branch",
                        candidate.handle,
                    )
                )
                selected_branches.add(candidate.parent_handle)
        result.append(
            TypedRequestFact(
                "append" if candidate.shape == "array" else "set",
                candidate.handle,
                value_type,
                fact.value,
            )
        )
    return tuple(result)


def _select_candidate(
    field: TopicBusinessField,
    fact: TopicBusinessFact,
) -> tuple[TypedFieldContract, str]:
    supported = {
        str(variant["type"])
        for candidate in field._candidates
        for variant in candidate.variants
        if variant.get("type") in _SCALAR_TYPES
    }
    order = _preferred_types(fact.value, explicit_kind=fact.kind)
    for value_type in order:
        if value_type not in supported:
            continue
        for candidate in field._candidates:
            if not any(
                variant.get("type") == value_type
                for variant in candidate.variants
            ):
                continue
            try:
                _parse_typed_scalar(
                    value_type,
                    fact.value,
                    variants=candidate.variants,
                    field_name=field.token,
                )
            except ValueError:
                continue
            return candidate, value_type
    accepted = ", ".join(field.accepted_value_kinds)
    raise TopicBusinessError(
        f"{field.token!r} does not accept that value; expected {accepted}"
    )


def _apply_business_rows(
    target: dict[str, Any],
    facts: Sequence[TopicBusinessRowFact],
    rows: Sequence[TopicBusinessRowContract],
) -> None:
    by_token = {item.token: item for item in rows}
    seen: set[tuple[str, tuple[int, ...], str]] = set()
    for fact in facts:
        row = by_token.get(fact.collection)
        if row is None:
            raise TopicBusinessError(
                f"Unknown event row collection {fact.collection!r}"
            )
        if len(fact.indices) != row.index_depth or any(
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < MAX_TYPED_ARRAY_ITEMS
            for index in fact.indices
        ):
            raise TopicBusinessError(
                f"Event row collection {fact.collection!r} requires "
                f"{row.index_depth} index value(s) from 0 through "
                f"{MAX_TYPED_ARRAY_ITEMS - 1}"
            )
        row_field = next(
            (item for item in row.fields if item.token == fact.field),
            None,
        )
        if row_field is None:
            raise TopicBusinessError(
                f"Unknown {fact.collection!r} event row field {fact.field!r}"
            )
        identity = (fact.collection, fact.indices, fact.field)
        if identity in seen:
            raise TopicBusinessError(
                f"Event row field {fact.collection!r}/{fact.field!r} was repeated"
            )
        seen.add(identity)
        value = _parse_row_value(row_field, fact)
        row_target = _ensure_row_target(target, row._path, fact.indices)
        _set_business_path(row_target, row_field._path, value)


def _apply_static_empty_facts(
    target: dict[str, Any],
    facts: Sequence[TopicBusinessEmptyFact],
    fields: Sequence[TopicBusinessEmptyField],
) -> None:
    by_token = {item.token: item for item in fields}
    for fact in facts:
        field_contract = by_token.get(fact.field)
        if field_contract is None:
            raise TopicBusinessError(
                f"Unknown empty Topic business field {fact.field!r}"
            )
        _set_business_path(
            target,
            field_contract._path,
            [] if field_contract.shape == "list" else {},
        )


def _apply_empty_business_rows(
    target: dict[str, Any],
    facts: Sequence[TopicBusinessEmptyRowFact],
    rows: Sequence[TopicBusinessRowContract],
) -> None:
    by_token = {item.token: item for item in rows}
    for fact in facts:
        row = by_token.get(fact.collection)
        if row is None:
            raise TopicBusinessError(
                f"Unknown empty event row collection {fact.collection!r}"
            )
        expected_depth = row.index_depth - 1
        if len(fact.parent_indices) != expected_depth or any(
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < MAX_TYPED_ARRAY_ITEMS
            for index in fact.parent_indices
        ):
            raise TopicBusinessError(
                f"Empty event row collection {fact.collection!r} requires "
                f"{expected_depth} parent index value(s)"
            )
        collection_path = row._path[:-1]
        if not collection_path or row._path[-1] is not None:
            raise TopicBusinessError("Event row collection path is malformed")
        parent_path = collection_path[:-1]
        collection_name = collection_path[-1]
        if not isinstance(collection_name, str):
            raise TopicBusinessError("Event row collection path is malformed")
        parent = (
            _ensure_row_target(target, parent_path, fact.parent_indices)
            if parent_path
            else target
        )
        if collection_name in parent:
            raise TopicBusinessError("Empty event row conflicts with another fact")
        parent[collection_name] = []


def _parse_row_value(
    field: TopicBusinessRowField,
    fact: TopicBusinessRowFact,
) -> Any:
    supported = {
        str(variant["type"])
        for variant in field._variants
        if variant.get("type") in _SCALAR_TYPES
    }
    for value_type in _preferred_types(fact.value, explicit_kind=fact.kind):
        if value_type not in supported:
            continue
        variants = tuple(
            variant
            for variant in field._variants
            if variant.get("type") == value_type
        )
        try:
            return _parse_typed_scalar(
                value_type,
                fact.value,
                variants=variants,
                field_name=field.token,
            )
        except ValueError:
            continue
    accepted = ", ".join(field.accepted_value_kinds)
    raise TopicBusinessError(
        f"{field.token!r} does not accept that value; expected {accepted}"
    )


def _apply_business_entries(
    target: dict[str, Any],
    *,
    scalar_facts: Sequence[TopicBusinessEntryFact],
    empty_facts: Sequence[TopicBusinessEntryEmptyFact],
    object_facts: Sequence[TopicBusinessEntryObjectFact],
    row_facts: Sequence[TopicBusinessEntryRowFact],
    entries: Sequence[TopicBusinessEntryContract],
) -> None:
    by_token = {item.token: item for item in entries}
    for fact in scalar_facts:
        entry = _require_entry_scope(by_token, fact.scope, fact.indices)
        scope = _ensure_row_target(target, entry._path, fact.indices)
        if fact.key in scope:
            raise TopicBusinessError(
                f"Exact event entry {fact.scope!r}/{fact.key!r} was repeated"
            )
        scope[fact.key] = _parse_entry_scalar(entry, fact.value, fact.kind)
    for fact in empty_facts:
        entry = _require_entry_scope(by_token, fact.scope, fact.indices)
        if fact.shape not in {"object", "list"}:
            raise TopicBusinessError(
                "Exact event entry empty shape must be object or list"
            )
        if (
            fact.shape == "object"
            and not entry.object_fields
            and not entry._open_object_fields
        ):
            raise TopicBusinessError(
                f"Exact event entry scope {fact.scope!r} does not accept objects"
            )
        if (
            fact.shape == "list"
            and not entry.row_fields
            and not entry._open_row_fields
        ):
            raise TopicBusinessError(
                f"Exact event entry scope {fact.scope!r} does not accept lists"
            )
        scope = _ensure_row_target(target, entry._path, fact.indices)
        if fact.key in scope:
            raise TopicBusinessError(
                f"Exact event entry {fact.scope!r}/{fact.key!r} was repeated"
            )
        scope[fact.key] = {} if fact.shape == "object" else []
    for fact in object_facts:
        entry = _require_entry_scope(by_token, fact.scope, fact.indices)
        row_field = _require_entry_row_field(
            entry,
            entry.object_fields,
            scope=fact.scope,
            field_name=fact.field,
            open_fields=entry._open_object_fields,
        )
        scope = _ensure_row_target(target, entry._path, fact.indices)
        existing = scope.setdefault(fact.key, {})
        if not isinstance(existing, dict):
            raise TopicBusinessError("Exact event entry value shapes conflict")
        _set_business_path(
            existing,
            row_field._path,
            _parse_entry_row_value(row_field, fact.value, fact.kind),
        )
    for fact in row_facts:
        entry = _require_entry_scope(by_token, fact.scope, fact.indices)
        if (
            isinstance(fact.item_index, bool)
            or not isinstance(fact.item_index, int)
            or not 0 <= fact.item_index < MAX_TYPED_ARRAY_ITEMS
        ):
            raise TopicBusinessError(
                f"Exact event entry row index must be from 0 through "
                f"{MAX_TYPED_ARRAY_ITEMS - 1}"
            )
        row_field = _require_entry_row_field(
            entry,
            entry.row_fields,
            scope=fact.scope,
            field_name=fact.field,
            open_fields=entry._open_row_fields,
        )
        scope = _ensure_row_target(target, entry._path, fact.indices)
        existing = scope.setdefault(fact.key, [])
        if not isinstance(existing, list):
            raise TopicBusinessError("Exact event entry value shapes conflict")
        while len(existing) <= fact.item_index:
            existing.append({})
        row = existing[fact.item_index]
        if not isinstance(row, dict):
            raise TopicBusinessError("Exact event entry row must be an object")
        _set_business_path(
            row,
            row_field._path,
            _parse_entry_row_value(row_field, fact.value, fact.kind),
        )


def _require_entry_scope(
    entries: Mapping[str, TopicBusinessEntryContract],
    scope: str,
    indices: Sequence[int],
) -> TopicBusinessEntryContract:
    entry = entries.get(scope)
    if entry is None:
        raise TopicBusinessError(f"Unknown exact event entry scope {scope!r}")
    if len(indices) != entry.index_depth or any(
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < MAX_TYPED_ARRAY_ITEMS
        for index in indices
    ):
        raise TopicBusinessError(
            f"Exact event entry scope {scope!r} requires {entry.index_depth} "
            "bounded index value(s)"
        )
    return entry


def _require_entry_row_field(
    entry: TopicBusinessEntryContract,
    fields: Sequence[TopicBusinessRowField],
    *,
    scope: str,
    field_name: str,
    open_fields: bool,
) -> TopicBusinessRowField:
    field_contract = next(
        (item for item in fields if item.token == field_name),
        None,
    )
    if field_contract is None and open_fields:
        variants = tuple(
            {"type": value_type}
            for value_type in (
                "string",
                "integer",
                "number",
                "boolean",
                "null",
            )
        )
        field_contract = TopicBusinessRowField(
            token=field_name,
            accepted_value_kinds=entry.accepted_value_kinds,
            _path=(field_name,),
            _variants=variants,
        )
    if field_contract is None:
        raise TopicBusinessError(
            f"Unknown {scope!r} exact event entry field {field_name!r}"
        )
    return field_contract


def _parse_entry_scalar(
    entry: TopicBusinessEntryContract,
    value: str,
    kind: str | None,
) -> Any:
    supported = {
        str(variant["type"])
        for variant in entry._scalar_variants
        if variant.get("type") in _SCALAR_TYPES
    }
    for value_type in _preferred_types(value, explicit_kind=kind):
        if value_type not in supported:
            continue
        variants = tuple(
            variant
            for variant in entry._scalar_variants
            if variant.get("type") == value_type
        )
        try:
            return _parse_typed_scalar(
                value_type,
                value,
                variants=variants,
                field_name=entry.token,
            )
        except ValueError:
            continue
    accepted = ", ".join(entry.accepted_value_kinds)
    raise TopicBusinessError(
        f"Exact event entry {entry.token!r} does not accept that scalar; "
        f"expected {accepted}"
    )


def _parse_entry_row_value(
    field: TopicBusinessRowField,
    value: str,
    kind: str | None,
) -> Any:
    return _parse_row_value(
        field,
        TopicBusinessRowFact("entry", (), field.token, value, kind=kind),
    )


def _ensure_row_target(
    root: dict[str, Any],
    path: Sequence[str | None],
    indices: Sequence[int],
) -> dict[str, Any]:
    current: Any = root
    index_cursor = 0
    for position, part in enumerate(path):
        next_part = path[position + 1] if position + 1 < len(path) else "row"
        if part is not None:
            if not isinstance(current, dict):
                raise TopicBusinessError("Event row path conflicts with another fact")
            expected_factory = list if next_part is None else dict
            existing = current.get(part)
            if existing is None:
                existing = expected_factory()
                current[part] = existing
            if not isinstance(existing, expected_factory):
                raise TopicBusinessError("Event row path conflicts with another fact")
            current = existing
            continue
        if not isinstance(current, list):
            raise TopicBusinessError("Event row collection conflicts with another fact")
        index = indices[index_cursor]
        index_cursor += 1
        item_factory = list if next_part is None else dict
        while len(current) <= index:
            current.append(item_factory())
        if not isinstance(current[index], item_factory):
            raise TopicBusinessError("Event row index conflicts with another fact")
        current = current[index]
    if not isinstance(current, dict):
        raise TopicBusinessError("Event row item must be an object")
    return current


def _set_business_path(
    target: dict[str, Any],
    path: Sequence[str],
    value: Any,
) -> None:
    current = target
    for part in path[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise TopicBusinessError("Event row field conflicts with another fact")
        current = child
    if not path or path[-1] in current:
        raise TopicBusinessError("Event row field conflicts with another fact")
    current[path[-1]] = value


def _preferred_types(value: str, *, explicit_kind: str | None) -> tuple[str, ...]:
    kind_types = {
        "text": "string",
        "integer": "integer",
        "number": "number",
        "toggle": "boolean",
        "null": "null",
    }
    if explicit_kind is not None:
        selected = kind_types.get(explicit_kind)
        if selected is None:
            raise TopicBusinessError(f"Unknown business value kind {explicit_kind!r}")
        return (selected,)
    if value == "null":
        return ("null", "string", "boolean", "integer", "number")
    if value in {"true", "false"}:
        return ("boolean", "string", "integer", "number", "null")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ("string", "integer", "number", "boolean", "null")
    if isinstance(parsed, int) and not isinstance(parsed, bool):
        return ("integer", "number", "string", "boolean", "null")
    if isinstance(parsed, float):
        return ("number", "string", "integer", "boolean", "null")
    return ("string", "boolean", "integer", "number", "null")


def _business_token(path: Sequence[str], *, section: str) -> str:
    parts = []
    for raw in path:
        value = raw.removesuffix(":map")
        value = _CAMEL_BOUNDARY.sub("-", value).replace("_", "-").casefold()
        parts.append(value)
    token = "-".join(parts)
    if section == "options" and token == "return":
        return "include"
    return token


def _business_kind(value_type: str) -> str:
    return {
        "string": "text",
        "integer": "integer",
        "number": "number",
        "boolean": "toggle",
        "null": "null",
    }[value_type]


def _gateway_field_table(
    fields: Sequence[TopicBusinessField],
) -> dict[str, Any]:
    kind_sets: list[tuple[str, ...]] = []
    for item in fields:
        if item.accepted_value_kinds not in kind_sets:
            kind_sets.append(item.accepted_value_kinds)
    return {
        "columns": ["field", "cardinality", "value_kind_set", "required"],
        "value_kind_sets": [list(item) for item in kind_sets],
        "rows": [
            [
                item.token,
                item.cardinality,
                kind_sets.index(item.accepted_value_kinds),
                item.required,
            ]
            for item in fields
        ],
    }


def _business_match_groups(
    fields: Sequence[TopicBusinessField],
) -> dict[str, tuple[TopicBusinessField, ...]]:
    grouped: dict[str, list[TopicBusinessField]] = {}
    for item in fields:
        path = item._candidates[0].path
        group = _business_token(path[:1], section="match")
        grouped.setdefault(group, []).append(item)
    return {
        group: tuple(items)
        for group, items in sorted(grouped.items())
    }


def _gateway_row_table(
    rows: Sequence[TopicBusinessRowContract],
    *,
    selected_row: str | None,
    selected_field_group: str | None,
) -> dict[str, Any]:
    table_rows = [
        [
            row.token,
            row.index_depth,
            len(row.fields),
            canonical_sha256([item.as_dict() for item in row.fields]),
        ]
        for row in rows
    ]
    payload: dict[str, Any] = {
        "columns": [
            "collection",
            "index_depth",
            "field_count",
            "field_digest",
        ],
        "rows": table_rows,
        "field_disclosure": "topic-schema <topic-uri> --row <collection>",
    }
    if selected_row is not None:
        row = next(item for item in rows if item.token == selected_row)
        field_groups = _row_field_groups(row.fields)
        if (
            selected_field_group is not None
            and selected_field_group not in field_groups
        ):
            raise TopicBusinessError(
                f"Unknown {selected_row!r} event row field group "
                f"{selected_field_group!r}"
            )
        payload["selected"] = {
            "collection": row.token,
            "index_depth": row.index_depth,
            "field_groups": {
                "columns": ["group", "field_count", "field_digest"],
                "rows": [
                    [
                        group,
                        len(fields),
                        canonical_sha256([item.as_dict() for item in fields]),
                    ]
                    for group, fields in field_groups.items()
                ],
                "field_disclosure": (
                    "topic-schema <topic-uri> --row <collection> "
                    "--row-field-group <group>"
                ),
            },
            "fields": {
                "columns": ["field", "accepted_value_kinds"],
                "rows": [
                    [item.token, list(item.accepted_value_kinds)]
                    for item in field_groups.get(selected_field_group, ())
                ],
            },
        }
    return payload


def _row_field_groups(
    fields: Sequence[TopicBusinessRowField],
) -> dict[str, tuple[TopicBusinessRowField, ...]]:
    grouped: dict[str, list[TopicBusinessRowField]] = {}
    for item in fields:
        group = (
            "direct"
            if len(item._path) == 1
            else _business_token(item._path[:2], section="match")
        )
        grouped.setdefault(group, []).append(item)
    return {group: tuple(items) for group, items in sorted(grouped.items())}


def _gateway_entry_table(
    entries: Sequence[TopicBusinessEntryContract],
    *,
    selected_entry: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "columns": [
            "scope",
            "index_depth",
            "accepted_value_kinds",
            "object_field_count",
            "row_field_count",
            "object_field_mode",
            "row_field_mode",
        ],
        "rows": [
            [
                entry.token,
                entry.index_depth,
                list(entry.accepted_value_kinds),
                len(entry.object_fields),
                len(entry.row_fields),
                "exact-key" if entry._open_object_fields else "closed",
                "exact-key" if entry._open_row_fields else "closed",
            ]
            for entry in entries
        ],
        "key_ownership": "exact_user_artifact_or_expression",
        "field_disclosure": "topic-schema <topic-uri> --entry <scope>",
    }
    if selected_entry is not None:
        entry = next(
            item for item in entries if item.token == selected_entry
        )
        payload["selected"] = entry.as_dict()
    return payload


__all__ = [
    "MaterializedTopicBusinessInputs",
    "TOPIC_BUSINESS_CONTRACT",
    "TopicBusinessContract",
    "TopicBusinessEmptyFact",
    "TopicBusinessEmptyField",
    "TopicBusinessEmptyRowFact",
    "TopicBusinessEntryContract",
    "TopicBusinessEntryEmptyFact",
    "TopicBusinessEntryFact",
    "TopicBusinessEntryObjectFact",
    "TopicBusinessEntryRowFact",
    "TopicBusinessError",
    "TopicBusinessFact",
    "TopicBusinessRowContract",
    "TopicBusinessRowFact",
    "TopicBusinessRowField",
    "materialize_topic_business_inputs",
    "topic_business_contract",
]

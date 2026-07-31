"""Read-only WAQL object discovery semantic builder."""

from __future__ import annotations

import math
import re

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import quote_waql_literal  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticReadbackPlan,
    SemanticValidationError,
)
from wwise_waapi.builders.identity import OBJECT_GET_URI  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.schema import SemanticSchemaValidator  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


SUPPORTED_SELECTS = ("descendants", "ancestors", "referencesTo", "children", "parent")
SUPPORTED_OPERATORS = ("=", "!=", "<", "<=", ">", ">=", ":")
MAX_QUERY_TAKE = 1000
MUTATING_WORDS = ("set", "delete", "create", "import", "move", "rename")
LEGACY_QUERY_KEYS = ("from", "transform")
BUILTIN_ACCESSORS = {
    "id",
    "name",
    "notes",
    "path",
    "filePath",
    "type",
    "classId",
    "category",
    "isPlayable",
    "isExplicitMute",
    "isExplicitSolo",
    "isImplicitMute",
    "isImplicitSolo",
    "isIncluded",
    "childrenCount",
    "pluginName",
    "convertedFilePath",
    "activeSource",
    "maxDurationSource.id",
    "maxDurationSource.trimmedDuration",
    "maxRadiusAttenuation.id",
    "maxRadiusAttenuation.radius",
}

STRUCTURED_QUERY_CONTRACT = "waapi-skill.object-query/v1"
# Compatibility alias for the descriptive name used during the internal draft.
STRUCTURED_OBJECT_QUERY_CONTRACT = STRUCTURED_QUERY_CONTRACT
MAX_STRUCTURED_QUERY_DEPTH = 12
MAX_STRUCTURED_QUERY_NODES = 256
MAX_STRUCTURED_SOURCE_ITEMS = 64
MAX_STRUCTURED_SOURCE_TYPES = 32
MAX_STRUCTURED_TRANSFORMS = 32
MAX_STRUCTURED_SELECT_EXPRESSIONS = 16
MAX_STRUCTURED_EXPRESSION_TOKENS = 16
MAX_STRUCTURED_BOOLEAN_DEPTH = 8
MAX_STRUCTURED_BOOLEAN_OPERANDS = 32
MAX_STRUCTURED_IDENTIFIER_LENGTH = 128
MAX_STRUCTURED_LITERAL_LENGTH = 4096
MAX_STRUCTURED_RETURN_FIELDS = 64
MAX_STRUCTURED_RETURN_FIELD_LENGTH = 256

# These patterns are shared by the public JSON Schema and the runtime compiler.
# Keeping one definition prevents ``query-schema`` from advertising a wider
# language than ``WaqlQueryBuilder`` will actually accept during preflight.
STRUCTURED_GUID_PATTERN = (
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
STRUCTURED_TYPE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_.]+$"
STRUCTURED_EXPRESSION_TOKEN_PATTERN = r"^(?:@@?)?[A-Za-z0-9_:]+$"
STRUCTURED_RETURN_ACCESSOR_PATTERN = (
    rf"^(?:@@?)?[A-Za-z0-9_:]+(?:\.(?:@@?)?[A-Za-z0-9_:]+)"
    rf"{{0,{MAX_STRUCTURED_EXPRESSION_TOKENS - 1}}}$"
)
_STRUCTURED_PATH_SEGMENT_PATTERN = (
    r'[^\\/"\x00-\x1f\x7f\u2028\u2029]+'
)
STRUCTURED_OBJECT_PATH_PATTERN = (
    rf"^(?:\\|\\{_STRUCTURED_PATH_SEGMENT_PATTERN}"
    rf"(?:\\{_STRUCTURED_PATH_SEGMENT_PATTERN})*)$"
)
STRUCTURED_QUERY_EDITOR_PATH_PATTERN = (
    rf"^\\Queries\\{_STRUCTURED_PATH_SEGMENT_PATTERN}"
    rf"(?:\\{_STRUCTURED_PATH_SEGMENT_PATTERN})*$"
)
STRUCTURED_LITERAL_STRING_PATTERN = (
    r'^(?:$|[^\s"\x00-\x1f\x7f\u2028\u2029]'
    r'(?:[^"\x00-\x1f\x7f\u2028\u2029]*'
    r'[^\s"\x00-\x1f\x7f\u2028\u2029])?)$'
)


@dataclass(slots=True, frozen=True)
class QueryPredicate:
    """One fail-closed WAQL where predicate supported by this builder."""

    field: str
    operator: str
    value: str | int | float | bool


def build_object_get_query(
    *,
    path: str | None = None,
    object_id: str | None = None,
    type: str | None = None,
    search: str | None = None,
    query: str | None = None,
    where: QueryPredicate | Mapping[str, Any] | Sequence[QueryPredicate | Mapping[str, Any]] | None = None,
    select: str | Sequence[str] | None = None,
    take: int | None = None,
    return_fields: Sequence[str] | None = None,
    source_note_checker: Any | None = None,
    schema_validator: SemanticSchemaValidator | None = None,
    version: str = DEFAULT_WWISE_VERSION,
    **legacy_or_unknown: Any,
) -> SemanticPreview:
    """Build a dispatcher-ready read-only ``ak.wwise.core.object.get`` WAQL preview.

    The builder intentionally accepts only grounded WAQL source/transform fragments and
    always requires explicit return fields so it never relies on Wwise defaults.
    """

    _reject_legacy_or_unknown_kwargs(legacy_or_unknown)
    _require_return_fields(return_fields)
    assert return_fields is not None

    source_note = (source_note_checker or SemanticSourceNoteChecker()).check(BuilderFamily.QUERY.value, version)
    if not source_note.allowed:
        raise SemanticValidationError(
            source_note.semantic_error_code(),
            source_note.reason or "Semantic source note is not valid for query builder.",
            details=source_note.as_dict(),
        )

    source = _source_clause(path=path, object_id=object_id, type=type, search=search, query=query)
    clauses = [source]
    clauses.extend(_select_clauses(select))
    predicate_clause = _where_clause(where)
    if predicate_clause:
        clauses.append(predicate_clause)
    if take is not None:
        clauses.append(_take_clause(take))

    waql = " ".join(part for part in clauses if part)
    _reject_mutating_waql(waql)
    args = {"waql": waql}
    options = {"return": list(return_fields)}
    validation = (schema_validator or SemanticSchemaValidator(version=version)).validate(OBJECT_GET_URI, args, options)

    envelope = SemanticEnvelope(
        OBJECT_GET_URI,
        args=args,
        options=options,
        metadata={
            "builder_family": BuilderFamily.QUERY.value,
            "source_note": source_note.as_dict(),
            "schema_validation": validation.as_dict(),
            "read_only": True,
        },
    )
    return SemanticPreview(
        envelope=envelope,
        source_note_family=BuilderFamily.QUERY.value,
        version=version,
        readback_plan=(
            SemanticReadbackPlan(
                OBJECT_GET_URI,
                args=args,
                options=options,
                description="read back WAQL object discovery rows requested by caller",
            ),
        ),
        evidence_plan=(
            {"kind": "source-note", "family": BuilderFamily.QUERY.value, "version": version},
            {"kind": "schema", "uri": OBJECT_GET_URI, "version": version},
        ),
    )


def build_query_preview(**kwargs: Any) -> SemanticPreview:
    """Alias with family-oriented naming for callers that prefer builder terminology."""

    return build_object_get_query(**kwargs)


def object_get_query(**kwargs: Any) -> SemanticPreview:
    """Alias that mirrors the target WAAPI function name."""

    return build_object_get_query(**kwargs)


class WaqlQueryBuilder:
    """Compile one closed structured query document into read-only WAQL.

    This builder deliberately has no raw-string escape hatch. Every WAQL token
    comes from a tagged source, an ordered transform, a bounded expression path,
    or a scalar literal.
    """

    def __init__(
        self,
        *,
        version: str = DEFAULT_WWISE_VERSION,
        source_note_checker: Any | None = None,
        schema_validator: SemanticSchemaValidator | None = None,
    ) -> None:
        self.version = version
        self.source_note_checker = source_note_checker
        self.schema_validator = schema_validator

    def build(self, request: Mapping[str, Any]) -> SemanticPreview:
        """Validate and compile ``waapi-skill.object-query/v1``."""

        _validate_structured_document_budget(request)
        document = _structured_mapping(
            request, context="structured object query"
        )
        _structured_exact_keys(
            document,
            required=("contract", "source", "transforms", "return"),
            context="structured object query",
        )
        if document.get("contract") != STRUCTURED_QUERY_CONTRACT:
            raise _structured_query_error(
                "Structured object query contract is unsupported.",
                details={
                    "contract": document.get("contract"),
                    "expected": STRUCTURED_QUERY_CONTRACT,
                },
            )

        source_clause, broad_source, source_identity = _structured_source_clause(
            document.get("source")
        )
        transforms = _structured_array(
            document.get("transforms"),
            context="structured object query transforms",
            minimum=0,
            maximum=MAX_STRUCTURED_TRANSFORMS,
        )
        transform_clauses, has_select = _structured_transform_clauses(
            transforms
        )
        return_fields = _structured_return_fields(document.get("return"))

        requires_final_take = broad_source or has_select
        has_final_take = bool(
            transforms
            and isinstance(transforms[-1], Mapping)
            and transforms[-1].get("kind") == "take"
        )
        if requires_final_take and not has_final_take:
            raise _structured_query_error(
                "Broad or expanding structured queries require a final take transform.",
                details={
                    "broad_source": broad_source,
                    "has_select": has_select,
                    "maximum_take": MAX_QUERY_TAKE,
                },
            )
        exact_identity = None if has_select else source_identity
        query_bound = (
            {
                "mode": "take",
                "value": transforms[-1]["value"],
            }
            if has_final_take
            else {
                "mode": "exact-object",
                "value": 1,
            }
        )

        clauses = [source_clause, *transform_clauses]
        waql = " ".join(clause for clause in clauses if clause)
        if not waql:
            raise _structured_query_error(
                "Structured object query must compile to a non-empty bounded WAQL query."
            )
        _reject_mutating_waql(waql)

        source_note = (
            self.source_note_checker or SemanticSourceNoteChecker()
        ).check(BuilderFamily.QUERY.value, self.version)
        if not source_note.allowed:
            raise SemanticValidationError(
                source_note.semantic_error_code(),
                source_note.reason
                or "Semantic source note is not valid for query builder.",
                details=source_note.as_dict(),
            )

        args = {"waql": waql}
        options = {"return": list(return_fields)}
        validation = (
            self.schema_validator
            or SemanticSchemaValidator(version=self.version)
        ).validate(OBJECT_GET_URI, args, options)
        envelope = SemanticEnvelope(
            OBJECT_GET_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.QUERY.value,
                "query_contract": STRUCTURED_QUERY_CONTRACT,
                "query_bound": query_bound,
                "exact_identity": exact_identity,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "read_only": True,
            },
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.QUERY.value,
            version=self.version,
            readback_plan=(
                SemanticReadbackPlan(
                    OBJECT_GET_URI,
                    args=args,
                    options=options,
                    description=(
                        "read back structured WAQL object discovery rows "
                        "requested by caller"
                    ),
                ),
            ),
            evidence_plan=(
                {
                    "kind": "source-note",
                    "family": BuilderFamily.QUERY.value,
                    "version": self.version,
                },
                {
                    "kind": "schema",
                    "uri": OBJECT_GET_URI,
                    "version": self.version,
                },
                {
                    "kind": "structured-query-contract",
                    "contract": STRUCTURED_QUERY_CONTRACT,
                },
            ),
        )


def build_structured_object_get_query(
    request: Mapping[str, Any],
    *,
    version: str = DEFAULT_WWISE_VERSION,
    source_note_checker: Any | None = None,
    schema_validator: SemanticSchemaValidator | None = None,
) -> SemanticPreview:
    """Build one dispatcher-ready object.get preview from a closed JSON AST."""

    return WaqlQueryBuilder(
        version=version,
        source_note_checker=source_note_checker,
        schema_validator=schema_validator,
    ).build(request)


def structured_query_schema(
    *,
    version: str = DEFAULT_WWISE_VERSION,
) -> dict[str, Any]:
    """Return the stable public JSON Schema for structured object queries."""

    def identity_schema(
        *,
        path_pattern: str,
        path_description: str,
    ) -> dict[str, Any]:
        return {
            "oneOf": [
                {
                    "type": "object",
                    "required": ["kind", "value"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"const": "id"},
                        "value": {
                            "type": "string",
                            "pattern": STRUCTURED_GUID_PATTERN,
                        },
                    },
                },
                {
                    "type": "object",
                    "required": ["kind", "value"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"const": "path"},
                        "value": {
                            "type": "string",
                            "pattern": path_pattern,
                            "maxLength": MAX_STRUCTURED_LITERAL_LENGTH,
                            "description": path_description,
                        },
                    },
                },
            ]
        }

    identity = identity_schema(
        path_pattern=STRUCTURED_OBJECT_PATH_PATTERN,
        path_description=(
            "Canonical absolute Wwise object path with single hierarchy separators."
        ),
    )
    query_identity = identity_schema(
        path_pattern=STRUCTURED_QUERY_EDITOR_PATH_PATTERN,
        path_description=(
            r"Canonical absolute Query Editor path beginning with \Queries\."
        ),
    )
    expression_path = {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_STRUCTURED_EXPRESSION_TOKENS,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_STRUCTURED_IDENTIFIER_LENGTH,
            "pattern": STRUCTURED_EXPRESSION_TOKEN_PATTERN,
            "description": (
                "One closed accessor/reference token: an optional @ or @@ "
                "prefix followed by ASCII letters, digits, underscores, or colons."
            ),
        },
    }
    scalar = {
        "type": ["string", "number", "boolean", "null"],
        "maxLength": MAX_STRUCTURED_LITERAL_LENGTH,
        "pattern": STRUCTURED_LITERAL_STRING_PATTERN,
    }
    string_literal = {
        "type": "string",
        "maxLength": MAX_STRUCTURED_LITERAL_LENGTH,
        "pattern": STRUCTURED_LITERAL_STRING_PATTERN,
    }

    def comparison_schema(
        *,
        operators: Sequence[str],
        value_schema: Mapping[str, Any],
    ) -> dict[str, Any]:
        operator_schema: dict[str, Any] = (
            {"const": operators[0]}
            if len(operators) == 1
            else {"enum": list(operators)}
        )
        return {
            "type": "object",
            "required": ["kind", "path", "operator", "value"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "compare"},
                "path": expression_path,
                "operator": operator_schema,
                "value": dict(value_schema),
            },
        }

    predicate_ref = {"$ref": "#/$defs/predicate"}
    predicate = {
        "oneOf": [
            comparison_schema(operators=("=", "!="), value_schema=scalar),
            comparison_schema(operators=(":",), value_schema=string_literal),
            comparison_schema(
                operators=("<", "<=", ">", ">="),
                value_schema={"type": "number"},
            ),
            {
                "type": "object",
                "required": ["kind", "path"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"const": "truthy"},
                    "path": expression_path,
                },
            },
            {
                "type": "object",
                "required": ["kind", "operands"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"enum": ["all", "any"]},
                    "operands": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_STRUCTURED_BOOLEAN_OPERANDS,
                        "items": predicate_ref,
                    },
                },
            },
            {
                "type": "object",
                "required": ["kind", "operand"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"const": "not"},
                    "operand": predicate_ref,
                },
            },
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": STRUCTURED_QUERY_CONTRACT,
        "x-wwise-version": version,
        "x-limits": {
            "document_depth": MAX_STRUCTURED_QUERY_DEPTH,
            "document_nodes": MAX_STRUCTURED_QUERY_NODES,
            "source_items": MAX_STRUCTURED_SOURCE_ITEMS,
            "source_types": MAX_STRUCTURED_SOURCE_TYPES,
            "transforms": MAX_STRUCTURED_TRANSFORMS,
            "select_expressions": MAX_STRUCTURED_SELECT_EXPRESSIONS,
            "expression_tokens": MAX_STRUCTURED_EXPRESSION_TOKENS,
            "boolean_depth": MAX_STRUCTURED_BOOLEAN_DEPTH,
            "boolean_operands": MAX_STRUCTURED_BOOLEAN_OPERANDS,
            "identifier_length": MAX_STRUCTURED_IDENTIFIER_LENGTH,
            "literal_length": MAX_STRUCTURED_LITERAL_LENGTH,
            "return_fields": MAX_STRUCTURED_RETURN_FIELDS,
            "return_field_length": MAX_STRUCTURED_RETURN_FIELD_LENGTH,
            "take": MAX_QUERY_TAKE,
        },
        "title": "WAAPI Skill structured object query",
        "type": "object",
        "required": ["contract", "source", "transforms", "return"],
        "additionalProperties": False,
        "properties": {
            "contract": {"const": STRUCTURED_QUERY_CONTRACT},
            "source": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["kind"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {
                                "const": "all",
                                "description": (
                                    "Use WAQL's implicit all-project source by "
                                    "omitting a from clause."
                                ),
                            }
                        },
                    },
                    {
                        "type": "object",
                        "required": ["kind"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {
                                "const": "project",
                                "description": "Compile the explicit from project source.",
                            }
                        },
                    },
                    {
                        "type": "object",
                        "required": ["kind", "types"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {"const": "type"},
                            "types": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": MAX_STRUCTURED_SOURCE_TYPES,
                                "uniqueItems": True,
                                "items": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": MAX_STRUCTURED_IDENTIFIER_LENGTH,
                                    "pattern": STRUCTURED_TYPE_IDENTIFIER_PATTERN,
                                    "description": (
                                        "Closed WAQL type token containing only "
                                        "ASCII letters, digits, underscores, or dots."
                                    ),
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["kind", "objects"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {"const": "object"},
                            "objects": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": MAX_STRUCTURED_SOURCE_ITEMS,
                                "uniqueItems": True,
                                "items": identity,
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["kind", "text"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {"const": "search"},
                            "text": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_STRUCTURED_LITERAL_LENGTH,
                                "pattern": STRUCTURED_LITERAL_STRING_PATTERN,
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["kind", "object"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {"const": "query"},
                            "object": query_identity,
                        },
                    },
                ]
            },
            "transforms": {
                "type": "array",
                "maxItems": MAX_STRUCTURED_TRANSFORMS,
                "description": (
                    "Sequential WAQL transforms. Broad or expanding queries "
                    "must end with take."
                ),
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "required": ["kind", "expressions"],
                            "additionalProperties": False,
                            "properties": {
                                "kind": {"const": "select"},
                                "expressions": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": MAX_STRUCTURED_SELECT_EXPRESSIONS,
                                    "uniqueItems": True,
                                    "items": expression_path,
                                },
                            },
                        },
                        {
                            "type": "object",
                            "required": ["kind", "predicate"],
                            "additionalProperties": False,
                            "properties": {
                                "kind": {"const": "where"},
                                "predicate": predicate_ref,
                            },
                        },
                        {
                            "type": "object",
                            "required": ["kind", "value"],
                            "additionalProperties": False,
                            "properties": {
                                "kind": {"const": "take"},
                                "value": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": MAX_QUERY_TAKE,
                                },
                            },
                        },
                    ]
                },
            },
            "return": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_STRUCTURED_RETURN_FIELDS,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_STRUCTURED_RETURN_FIELD_LENGTH,
                    "pattern": STRUCTURED_RETURN_ACCESSOR_PATTERN,
                    "description": (
                        "A closed dot-separated accessor path such as id, "
                        "@Volume, audioSource:language, or parent.id. Raw "
                        "return expressions, aliases, composition, and list "
                        "operators are not accepted."
                    ),
                },
            },
        },
        "$defs": {"predicate": predicate},
    }


def _structured_source_clause(
    payload: Any,
) -> tuple[str, bool, dict[str, Any] | None]:
    source = _structured_mapping(payload, context="structured query source")
    kind = source.get("kind")
    if kind == "all":
        _structured_exact_keys(source, required=("kind",), context="all source")
        return "", True, None
    if kind == "project":
        _structured_exact_keys(
            source, required=("kind",), context="project source"
        )
        return "from project", True, None
    if kind == "type":
        _structured_exact_keys(
            source, required=("kind", "types"), context="type source"
        )
        types = _structured_array(
            source.get("types"),
            context="type source types",
            minimum=1,
            maximum=MAX_STRUCTURED_SOURCE_TYPES,
        )
        rendered_types = [
            _structured_identifier(value, context=f"type source types[{index}]")
            for index, value in enumerate(types)
        ]
        _structured_unique(rendered_types, context="type source types")
        return "from type " + ", ".join(rendered_types), True, None
    if kind == "object":
        _structured_exact_keys(
            source, required=("kind", "objects"), context="object source"
        )
        objects = _structured_array(
            source.get("objects"),
            context="object source objects",
            minimum=1,
            maximum=MAX_STRUCTURED_SOURCE_ITEMS,
        )
        rendered_objects = [
            _structured_object_specifier(
                item,
                context=f"object source objects[{index}]",
                query_editor=False,
            )
            for index, item in enumerate(objects)
        ]
        _structured_unique(rendered_objects, context="object source objects")
        exact_identity = (
            {
                "kind": objects[0]["kind"],
                "value": objects[0]["value"],
            }
            if len(objects) == 1 and isinstance(objects[0], Mapping)
            else None
        )
        return (
            "from object " + ", ".join(rendered_objects),
            len(objects) > 1,
            exact_identity,
        )
    if kind == "search":
        _structured_exact_keys(
            source, required=("kind", "text"), context="search source"
        )
        text = _structured_text(
            source.get("text"),
            context="search source text",
            maximum=MAX_STRUCTURED_LITERAL_LENGTH,
            allow_empty=False,
        )
        return "from search " + _structured_quote_literal(text), True, None
    if kind == "query":
        _structured_exact_keys(
            source, required=("kind", "object"), context="query source"
        )
        rendered = _structured_object_specifier(
            source.get("object"),
            context="query source object",
            query_editor=True,
        )
        return "from query " + rendered, True, None
    raise _structured_query_error(
        "Structured query source kind is unsupported.",
        details={
            "kind": kind,
            "supported": ["all", "project", "type", "object", "search", "query"],
        },
    )


def _structured_transform_clauses(
    transforms: Sequence[Any],
) -> tuple[list[str], bool]:
    clauses: list[str] = []
    has_select = False
    take_indexes: list[int] = []
    for index, payload in enumerate(transforms):
        transform = _structured_mapping(
            payload, context=f"structured query transforms[{index}]"
        )
        kind = transform.get("kind")
        if kind == "select":
            _structured_exact_keys(
                transform,
                required=("kind", "expressions"),
                context=f"select transform[{index}]",
            )
            expressions = _structured_array(
                transform.get("expressions"),
                context=f"select transform[{index}] expressions",
                minimum=1,
                maximum=MAX_STRUCTURED_SELECT_EXPRESSIONS,
            )
            rendered = [
                _structured_expression_path(
                    expression,
                    context=f"select transform[{index}] expressions[{item_index}]",
                )
                for item_index, expression in enumerate(expressions)
            ]
            _structured_unique(
                rendered, context=f"select transform[{index}] expressions"
            )
            clauses.append("select " + ", ".join(rendered))
            has_select = True
            continue
        if kind == "where":
            _structured_exact_keys(
                transform,
                required=("kind", "predicate"),
                context=f"where transform[{index}]",
            )
            clauses.append(
                "where "
                + _structured_boolean_expression(
                    transform.get("predicate"),
                    context=f"where transform[{index}] predicate",
                    depth=0,
                    nested=False,
                )
            )
            continue
        if kind == "take":
            _structured_exact_keys(
                transform,
                required=("kind", "value"),
                context=f"take transform[{index}]",
            )
            value = transform.get("value")
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= MAX_QUERY_TAKE
            ):
                raise _structured_query_error(
                    f"take transform[{index}] must be an integer between 0 and {MAX_QUERY_TAKE}.",
                    details={
                        "value": value,
                        "minimum": 0,
                        "maximum": MAX_QUERY_TAKE,
                    },
                )
            clauses.append(f"take {value}")
            take_indexes.append(index)
            continue
        raise _structured_query_error(
            f"Structured query transform[{index}] kind is unsupported.",
            details={"kind": kind, "supported": ["select", "where", "take"]},
        )
    if take_indexes and (
        len(take_indexes) != 1 or take_indexes[0] != len(transforms) - 1
    ):
        raise _structured_query_error(
            "A structured query may contain at most one take transform and it must be final.",
            details={"take_indexes": take_indexes},
        )
    return clauses, has_select


def _structured_boolean_expression(
    payload: Any,
    *,
    context: str,
    depth: int,
    nested: bool,
) -> str:
    if depth > MAX_STRUCTURED_BOOLEAN_DEPTH:
        raise _structured_query_error(
            "Structured query boolean expression exceeds its depth limit.",
            details={
                "context": context,
                "depth": depth,
                "maximum": MAX_STRUCTURED_BOOLEAN_DEPTH,
            },
        )
    node = _structured_mapping(payload, context=context)
    kind = node.get("kind")
    if kind == "compare":
        _structured_exact_keys(
            node,
            required=("kind", "path", "operator", "value"),
            context=context,
        )
        operator = node.get("operator")
        if operator not in SUPPORTED_OPERATORS:
            raise _structured_query_error(
                f"{context} comparison operator is unsupported.",
                details={
                    "operator": operator,
                    "supported": list(SUPPORTED_OPERATORS),
                },
            )
        literal = node.get("value")
        if operator == ":" and not isinstance(literal, str):
            raise _structured_query_error(
                f"{context} ':' comparison requires a string literal.",
                details={"literal_type": type(literal).__name__},
            )
        if operator in {"<", "<=", ">", ">="} and (
            isinstance(literal, bool)
            or not isinstance(literal, (int, float))
        ):
            raise _structured_query_error(
                f"{context} ordered comparison requires a numeric literal.",
                details={"literal_type": type(literal).__name__},
            )
        return (
            _structured_expression_path(
                node.get("path"), context=f"{context} path"
            )
            + f" {operator} "
            + _structured_literal(literal, context=f"{context} value")
        )
    if kind == "truthy":
        _structured_exact_keys(
            node, required=("kind", "path"), context=context
        )
        return _structured_expression_path(
            node.get("path"), context=f"{context} path"
        )
    if kind in {"all", "any"}:
        _structured_exact_keys(
            node, required=("kind", "operands"), context=context
        )
        operands = _structured_array(
            node.get("operands"),
            context=f"{context} operands",
            minimum=1,
            maximum=MAX_STRUCTURED_BOOLEAN_OPERANDS,
        )
        rendered = [
            _structured_boolean_expression(
                operand,
                context=f"{context} operands[{index}]",
                depth=depth + 1,
                nested=True,
            )
            for index, operand in enumerate(operands)
        ]
        operator = " and " if kind == "all" else " or "
        result = operator.join(rendered)
        return f"({result})" if nested and len(rendered) > 1 else result
    if kind == "not":
        _structured_exact_keys(
            node, required=("kind", "operand"), context=context
        )
        operand = _structured_boolean_expression(
            node.get("operand"),
            context=f"{context} operand",
            depth=depth + 1,
            nested=False,
        )
        return f"! ({operand})"
    raise _structured_query_error(
        f"{context} kind is unsupported.",
        details={
            "kind": kind,
            "supported": ["compare", "truthy", "all", "any", "not"],
        },
    )


def _structured_expression_path(payload: Any, *, context: str) -> str:
    tokens = _structured_array(
        payload,
        context=context,
        minimum=1,
        maximum=MAX_STRUCTURED_EXPRESSION_TOKENS,
    )
    return ".".join(
        _structured_expression_token(token, context=f"{context}[{index}]")
        for index, token in enumerate(tokens)
    )


def _structured_expression_token(payload: Any, *, context: str) -> str:
    token = _structured_text(
        payload,
        context=context,
        maximum=MAX_STRUCTURED_IDENTIFIER_LENGTH,
        allow_empty=False,
    )
    if re.fullmatch(STRUCTURED_EXPRESSION_TOKEN_PATTERN, token) is None:
        raise _structured_query_error(
            f"{context} is not a closed WAQL path token.",
            details={"token": token},
        )
    return token


def _structured_object_specifier(
    payload: Any,
    *,
    context: str,
    query_editor: bool,
) -> str:
    value = _structured_mapping(payload, context=context)
    _structured_exact_keys(
        value, required=("kind", "value"), context=context
    )
    kind = value.get("kind")
    raw = value.get("value")
    if kind == "id":
        identity = _object_guid_specifier(raw)
    elif kind == "path":
        if query_editor:
            identity = _query_object_specifier(raw)
        else:
            identity = _object_path_specifier(raw)
    else:
        raise _structured_query_error(
            f"{context} kind must be id or path.",
            details={"kind": kind},
        )
    return _structured_quote_literal(identity)


def _structured_literal(payload: Any, *, context: str) -> str:
    if payload is None:
        return "null"
    if isinstance(payload, bool):
        return "true" if payload else "false"
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        if isinstance(payload, float) and not math.isfinite(payload):
            raise _structured_query_error(
                f"{context} numeric literal must be finite."
            )
        return str(payload)
    text = _structured_text(
        payload,
        context=context,
        maximum=MAX_STRUCTURED_LITERAL_LENGTH,
        allow_empty=True,
    )
    return _structured_quote_literal(text, allow_empty=True)


def _structured_quote_literal(value: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return '""'
    try:
        return quote_waql_literal(value)
    except ValueError as exc:
        raise _structured_query_error(
            str(exc),
            details={"boundary": "packaged-waql-literal-evidence"},
        ) from exc


def _structured_return_fields(payload: Any) -> tuple[str, ...]:
    fields = _structured_array(
        payload,
        context="structured object query return",
        minimum=1,
        maximum=MAX_STRUCTURED_RETURN_FIELDS,
    )
    normalized_values: list[str] = []
    for index, field in enumerate(fields):
        context = f"structured object query return[{index}]"
        value = _structured_text(
            field,
            context=context,
            maximum=MAX_STRUCTURED_RETURN_FIELD_LENGTH,
            allow_empty=False,
        )
        if re.fullmatch(STRUCTURED_RETURN_ACCESSOR_PATTERN, value) is None:
            raise _structured_query_error(
                f"{context} must be one canonical dot-separated accessor path."
            )
        normalized_values.append(value)
    normalized = tuple(normalized_values)
    _structured_unique(normalized, context="structured object query return")
    return normalized


def _structured_identifier(payload: Any, *, context: str) -> str:
    value = _structured_text(
        payload,
        context=context,
        maximum=MAX_STRUCTURED_IDENTIFIER_LENGTH,
        allow_empty=False,
    )
    if re.fullmatch(STRUCTURED_TYPE_IDENTIFIER_PATTERN, value) is None:
        raise _structured_query_error(
            f"{context} is not a closed WAQL identifier.",
            details={"identifier": value},
        )
    return value


def _structured_text(
    payload: Any,
    *,
    context: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    if (
        not isinstance(payload, str)
        or payload != payload.strip()
        or (not allow_empty and not payload)
        or len(payload) > maximum
        or any(
            ord(character) < 32
            or ord(character) == 127
            or character in {"\u2028", "\u2029"}
            for character in payload
        )
    ):
        raise _structured_query_error(
            f"{context} must be a bounded, trimmed string.",
            details={"maximum_length": maximum},
        )
    return payload


def _structured_array(
    payload: Any,
    *,
    context: str,
    minimum: int,
    maximum: int,
) -> list[Any]:
    if (
        not isinstance(payload, list)
        or not minimum <= len(payload) <= maximum
    ):
        raise _structured_query_error(
            f"{context} must be a JSON array with {minimum}..{maximum} items.",
            details={
                "actual_type": type(payload).__name__,
                "actual_count": len(payload) if isinstance(payload, list) else None,
                "minimum": minimum,
                "maximum": maximum,
            },
        )
    return payload


def _structured_mapping(payload: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise _structured_query_error(
            f"{context} must be a JSON object.",
            details={"actual_type": type(payload).__name__},
        )
    if not all(isinstance(key, str) for key in payload):
        raise _structured_query_error(f"{context} keys must be strings.")
    return payload


def _structured_exact_keys(
    payload: Mapping[str, Any],
    *,
    required: Sequence[str],
    context: str,
) -> None:
    required_keys = set(required)
    actual_keys = set(payload)
    missing = sorted(required_keys - actual_keys)
    extra = sorted(actual_keys - required_keys)
    if missing or extra:
        raise _structured_query_error(
            f"{context} has missing or unsupported fields.",
            details={"missing": missing, "extra": extra},
        )


def _structured_unique(values: Sequence[str], *, context: str) -> None:
    if len(values) != len(set(values)):
        raise _structured_query_error(
            f"{context} must not contain duplicate values."
        )


def _validate_structured_document_budget(payload: Any) -> None:
    nodes = 0

    def visit(value: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_STRUCTURED_QUERY_NODES:
            raise _structured_query_error(
                "Structured object query exceeds its node limit.",
                details={
                    "maximum": MAX_STRUCTURED_QUERY_NODES,
                    "actual_at_least": nodes,
                },
            )
        if depth > MAX_STRUCTURED_QUERY_DEPTH:
            raise _structured_query_error(
                "Structured object query exceeds its depth limit.",
                details={"maximum": MAX_STRUCTURED_QUERY_DEPTH, "depth": depth},
            )
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise _structured_query_error(
                        "Structured object query keys must be strings."
                    )
                if len(key) > MAX_STRUCTURED_IDENTIFIER_LENGTH:
                    raise _structured_query_error(
                        "Structured object query key exceeds its length limit."
                    )
                visit(item, depth + 1)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
            return
        if isinstance(value, str):
            if len(value) > MAX_STRUCTURED_LITERAL_LENGTH:
                raise _structured_query_error(
                    "Structured object query string exceeds its length limit.",
                    details={"maximum": MAX_STRUCTURED_LITERAL_LENGTH},
                )
            return
        if value is None or isinstance(value, (bool, int)):
            return
        if isinstance(value, float):
            if math.isfinite(value):
                return
            raise _structured_query_error(
                "Structured object query numbers must be finite."
            )
        raise _structured_query_error(
            "Structured object query must contain only JSON values.",
            details={"actual_type": type(value).__name__},
        )

    visit(payload, 0)


def _structured_query_error(
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> SemanticValidationError:
    return SemanticValidationError(
        SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
        message,
        details=details,
    )


def _source_clause(*, path: str | None, object_id: str | None, type: str | None, search: str | None, query: str | None) -> str:
    supplied = {
        "path": path,
        "object_id": object_id,
        "type": type,
        "search": search,
        "query": query,
    }
    active = {key: value for key, value in supplied.items() if _has_value(value)}
    if len(active) != 1:
        raise SemanticValidationError(
            SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY,
            "Query builder requires exactly one WAQL source: path, object_id, type, search, or query.",
            details={"sources": active},
        )
    if path is not None and _has_value(path):
        # A path is an object specifier, not a generic WAQL string.  Keep the
        # explicit form so exact-path failures remain distinguishable from
        # broad queries and can be normalized consistently.
        return f"from object {_quote_literal(_object_path_specifier(path))}"
    if object_id is not None and _has_value(object_id):
        return f"from object {_quote_literal(_object_guid_specifier(object_id))}"
    if type is not None and _has_value(type):
        return f"from type {_identifier(type, kind='type')}"
    if search is not None and _has_value(search):
        return f"from search {_quote_literal(search)}"
    assert query is not None
    return f"from query {_quote_literal(_query_object_specifier(query))}"


_CANONICAL_GUID = re.compile(STRUCTURED_GUID_PATTERN)


def _object_guid_specifier(value: str) -> str:
    if not isinstance(value, str) or _CANONICAL_GUID.fullmatch(value) is None:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL object_id must be a canonical braced GUID.",
            details={"object_id": value, "accepted": "canonical-guid"},
        )
    return value


def _object_path_specifier(value: str) -> str:
    valid = isinstance(value, str) and re.fullmatch(
        STRUCTURED_OBJECT_PATH_PATTERN,
        value,
    ) is not None
    if not valid:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL path must be an absolute Wwise object path with single hierarchy separators.",
            details={
                "path": value,
                "accepted": "absolute-single-separator-wwise-path",
                "boundary": "canonical-wwise-object-path",
            },
        )
    return value


def _query_object_specifier(value: str) -> str:
    """Validate one Query Editor object path or GUID, never raw WAQL."""

    if isinstance(value, str) and _CANONICAL_GUID.fullmatch(value):
        return value
    valid_path = isinstance(value, str) and re.fullmatch(
        STRUCTURED_QUERY_EDITOR_PATH_PATTERN,
        value,
    ) is not None
    if not valid_path:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL query source must be a canonical Query Editor {GUID} or an absolute "
            r"\Queries\... path with single hierarchy separators; raw WAQL is not accepted.",
            details={
                "query": value,
                "accepted": ["canonical-guid", r"\Queries\..."],
                "boundary": "query-editor-object-specifier",
            },
        )
    return value


def _select_clauses(select: str | Sequence[str] | None) -> list[str]:
    if select is None:
        return []
    values = (select,) if isinstance(select, str) else tuple(select)
    clauses: list[str] = []
    for value in values:
        if value not in SUPPORTED_SELECTS:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                f"Unsupported WAQL select transform: {value!r}",
                details={"select": value, "supported": list(SUPPORTED_SELECTS)},
            )
        clauses.append(f"select {value}")
    return clauses


def _where_clause(where: QueryPredicate | Mapping[str, Any] | Sequence[QueryPredicate | Mapping[str, Any]] | None) -> str:
    predicates = _predicate_tuple(where)
    if not predicates:
        return ""
    return "where " + " and ".join(_predicate_clause(predicate) for predicate in predicates)


def _predicate_tuple(where: QueryPredicate | Mapping[str, Any] | Sequence[QueryPredicate | Mapping[str, Any]] | None) -> tuple[QueryPredicate, ...]:
    if where is None:
        return ()
    if isinstance(where, QueryPredicate) or isinstance(where, Mapping):
        items: Iterable[QueryPredicate | Mapping[str, Any]] = (where,)
    elif isinstance(where, Sequence) and not isinstance(where, (str, bytes)):
        items = where
    else:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL where must be one JSON predicate object or an array of predicate objects.",
            details={"where_type": type(where).__name__},
        )
    return tuple(_predicate(item) for item in items)


def _predicate(value: QueryPredicate | Mapping[str, Any]) -> QueryPredicate:
    if isinstance(value, QueryPredicate):
        return value
    if not isinstance(value, Mapping):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL where predicates must be JSON objects.",
            details={"predicate_type": type(value).__name__},
        )
    missing = tuple(key for key in ("field", "operator", "value") if key not in value)
    if missing:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL where predicates require field, operator, and value.",
            details={"missing": list(missing)},
        )
    extra = tuple(sorted(str(key) for key in value if key not in {"field", "operator", "value"}))
    if extra:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL where predicates do not accept extra fields.",
            details={"extra": list(extra)},
        )
    return QueryPredicate(str(value["field"]), str(value["operator"]), value["value"])


def _predicate_clause(predicate: QueryPredicate) -> str:
    field = _accessor(predicate.field)
    operator = _operator(predicate.operator)
    value = _literal(predicate.value)
    return f"{field} {operator} {value}"


def _accessor(value: str) -> str:
    if value.startswith("@@"):
        return "@@" + _identifier(value[2:], kind="property")
    if value.startswith("@"):
        return "@" + _identifier(value[1:], kind="property")
    if value not in BUILTIN_ACCESSORS:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            f"Unsupported WAQL accessor: {value!r}",
            details={"accessor": value, "supported": sorted(BUILTIN_ACCESSORS)},
        )
    return value


def _operator(value: str) -> str:
    if value not in SUPPORTED_OPERATORS:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Unsupported WAQL operator: {value!r}",
            details={"operator": value, "supported": list(SUPPORTED_OPERATORS)},
        )
    return value


def _literal(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "WAQL numeric predicate literals must be finite.",
                details={"literal": str(value)},
            )
        return str(value)
    if not isinstance(value, str):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL predicate literals must be strings, numbers, or booleans.",
            details={"literal_type": type(value).__name__},
        )
    return _quote_literal(value)


def _quote_literal(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL string/path/GUID literals must be non-empty.",
            details={"literal_type": type(value).__name__},
        )
    if any(ord(character) < 32 for character in value):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL string/path/GUID literals must not contain control characters.",
        )
    # WAQL object paths use a single backslash as their hierarchy separator.
    # JSON serialization handles transport escaping; doubling separators here
    # changes the object specifier and makes valid leaf paths resolve as absent.
    try:
        return quote_waql_literal(value)
    except ValueError as exc:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            str(exc),
            details={"literal": value, "boundary": "packaged-waql-literal-evidence"},
        ) from exc


def _identifier(value: str, *, kind: str) -> str:
    if not isinstance(value, str) or not value or not all(character.isalnum() or character in ("_", ".") for character in value):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            f"Unsupported WAQL {kind} literal: {value!r}",
            details={kind: value},
        )
    return value


def _take_clause(take: int) -> str:
    if (
        not isinstance(take, int)
        or isinstance(take, bool)
        or take < 0
        or take > MAX_QUERY_TAKE
    ):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"WAQL take must be an integer between 0 and {MAX_QUERY_TAKE}.",
            details={"take": take, "minimum": 0, "maximum": MAX_QUERY_TAKE},
        )
    return f"take {take}"


def _require_return_fields(return_fields: Sequence[str] | None) -> None:
    if (
        not return_fields
        or isinstance(return_fields, (str, bytes))
        or not all(isinstance(field, str) and field for field in return_fields)
    ):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Query builder requires explicit non-empty options.return fields.",
            details={
                "return_fields": list(return_fields or []) if not isinstance(return_fields, str) else return_fields,
                "return_fields_type": type(return_fields).__name__,
            },
        )


def _reject_legacy_or_unknown_kwargs(values: Mapping[str, Any]) -> None:
    legacy = tuple(key for key in values if key in LEGACY_QUERY_KEYS)
    if legacy:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Legacy object.get from/transform query shape is not accepted; use WAQL semantic inputs only.",
            details={"legacy_keys": list(legacy)},
        )
    if values:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Unsupported query builder arguments.",
            details={"unknown_keys": sorted(values)},
        )


def _reject_mutating_waql(waql: str) -> None:
    # The builder owns the WAQL grammar, so only structural tokens need this
    # defense-in-depth check. User literals are already closed by
    # ``quote_waql_literal`` and may legitimately contain words such as
    # "delete" or "move" without changing this read-only query into a mutation.
    structural_waql = re.sub(r'"[^"\r\n]*"', '""', waql)
    padded = f" {structural_waql.lower()} "
    found = tuple(word for word in MUTATING_WORDS if f" {word} " in padded)
    if found:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Mutating words are not accepted in read-only WAQL query builder output.",
            details={"mutating_words": list(found)},
        )


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True

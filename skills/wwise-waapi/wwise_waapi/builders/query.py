"""Read-only WAQL object discovery semantic builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION  # pyright: ignore[reportMissingImports]

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


SUPPORTED_SELECTS = ("descendants", "ancestors", "referencesTo")
SUPPORTED_OPERATORS = ("=", "!=", "<", "<=", ">", ">=", ":")
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


@dataclass(slots=True, frozen=True)
class QueryPredicate:
    """One fail-closed WAQL where predicate supported by this builder."""

    field: str
    operator: str
    value: str | int | float | bool


def build_object_get_query(
    *,
    path: str | None = None,
    object_id: str | int | None = None,
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


def _source_clause(*, path: str | None, object_id: str | int | None, type: str | None, search: str | None, query: str | None) -> str:
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
        return _quote_literal(path)
    if object_id is not None and _has_value(object_id):
        return f"from object {_quote_literal(str(object_id))}"
    if type is not None and _has_value(type):
        return f"from type {_identifier(type, kind='type')}"
    if search is not None and _has_value(search):
        return f"from search {_quote_literal(search)}"
    assert query is not None
    return f"from query {_quote_literal(query)}"


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
    else:
        items = where
    return tuple(_predicate(item) for item in items)


def _predicate(value: QueryPredicate | Mapping[str, Any]) -> QueryPredicate:
    if isinstance(value, QueryPredicate):
        return value
    missing = tuple(key for key in ("field", "operator", "value") if key not in value)
    if missing:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL where predicates require field, operator, and value.",
            details={"missing": list(missing)},
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
        return str(value)
    if not isinstance(value, str):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL predicate literals must be strings, numbers, or booleans.",
            details={"literal_type": type(value).__name__},
        )
    return _quote_literal(value)


def _quote_literal(value: str) -> str:
    if not value:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL string/path/GUID literals must be non-empty.",
        )
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _identifier(value: str, *, kind: str) -> str:
    if not value or not all(character.isalnum() or character in ("_", ".") for character in value):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            f"Unsupported WAQL {kind} literal: {value!r}",
            details={kind: value},
        )
    return value


def _take_clause(take: int) -> str:
    if not isinstance(take, int) or isinstance(take, bool) or take < 0:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL take must be a non-negative integer.",
            details={"take": take},
        )
    return f"take {take}"


def _require_return_fields(return_fields: Sequence[str] | None) -> None:
    if not return_fields or not all(isinstance(field, str) and field for field in return_fields):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Query builder requires explicit non-empty options.return fields.",
            details={"return_fields": list(return_fields or [])},
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
    padded = f" {waql.lower()} "
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

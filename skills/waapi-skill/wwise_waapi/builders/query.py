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


_CANONICAL_GUID = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)


def _object_guid_specifier(value: str) -> str:
    if not isinstance(value, str) or _CANONICAL_GUID.fullmatch(value) is None:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "WAQL object_id must be a canonical braced GUID.",
            details={"object_id": value, "accepted": "canonical-guid"},
        )
    return value


def _object_path_specifier(value: str) -> str:
    valid = (
        isinstance(value, str)
        and value.startswith("\\")
        and (value == "\\" or not value.startswith("\\\\"))
        and (value == "\\" or not value.endswith("\\"))
        and (value == "\\" or "\\\\" not in value)
        and "/" not in value
        and '"' not in value
        and not any(
            ord(character) < 32
            or ord(character) == 127
            or character in {"\u2028", "\u2029"}
            for character in value
        )
    )
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
    valid_path = (
        isinstance(value, str)
        and value.startswith("\\Queries\\")
        and not value.startswith("\\\\")
        and not value.endswith("\\")
        and "\\\\" not in value
        and "/" not in value
        and '"' not in value
        and not any(
            ord(character) < 32
            or ord(character) == 127
            or character in {"\u2028", "\u2029"}
            for character in value
        )
    )
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

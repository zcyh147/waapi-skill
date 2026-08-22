"""Bounded live discovery of exact Wwise property and reference names.

This module deliberately performs lexical retrieval rather than semantic
selection.  It turns natural-language search phrases into a small, rich set of
live metadata candidates, but it never invents a property alias or claims that
the highest-ranked row is the user's intended field.

All live access is injected through ``read_call``.  The closed call surface is
limited to ``getTypes``, ``getPropertyAndReferenceNames``, and
``getPropertyInfo`` so callers can apply the same version checks and cache used
by transaction previews.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .builders.common import SemanticValidationError
from .builders.metadata import (
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
    ObjectTypeMetadataRecord,
    PropertyInfoMetadataRecord,
    parse_get_property_info_result,
    parse_get_types_result,
    parse_property_and_reference_names_result,
)
from .canonical import canonical_json_bytes


METADATA_DISCOVERY_CONTRACT = "waapi-skill.metadata-discovery/v2"
METADATA_DISCOVERY_DETAIL_CONTRACT = "waapi-skill.metadata-discovery/v1"

MAX_METADATA_DISCOVERY_QUERIES = 8
MAX_METADATA_DISCOVERY_QUERY_CHARS = 160
MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS = 640
DEFAULT_METADATA_DISCOVERY_LIMIT = 5
MAX_METADATA_DISCOVERY_LIMIT = 8

MAX_METADATA_DISCOVERY_TYPES = 2_048
MAX_METADATA_DISCOVERY_NAMES = 4_096
MAX_METADATA_DISCOVERY_NAME_CHARS = 256
MAX_METADATA_DISCOVERY_DETAIL_POOL = 32
MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN = 256
MAX_METADATA_DISCOVERY_DEPENDENCIES = 16
MAX_METADATA_DISCOVERY_DEPENDENCY_DEPTH = 2
MAX_METADATA_DISCOVERY_INFO_BYTES = 32 * 1024
MAX_METADATA_DISCOVERY_AGENT_RESULT_BYTES = 28 * 1024
MAX_METADATA_DISCOVERY_RESULT_BYTES = 512 * 1024
MAX_METADATA_DISCOVERY_ERROR_DETAILS_BYTES = 8 * 1024

_APPROVED_URIS = frozenset(
    {
        GET_TYPES_URI,
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    }
)
_CAMEL_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_MAX_METADATA_SEARCH_STRINGS = 96
_MAX_METADATA_SEARCH_STRING_CHARS = 512

_BOOLEAN_METADATA_TYPES = frozenset({"bool", "boolean"})
_INTEGER_METADATA_TYPES = frozenset(
    {
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
    }
)
_NUMBER_METADATA_TYPES = frozenset({"real32", "real64", "float", "double"})


def metadata_typed_value_type(metadata_type: str) -> str | None:
    """Map one reflected Wwise scalar type to the public typed-action token."""

    if not isinstance(metadata_type, str):
        return None
    normalized = metadata_type.casefold()
    if normalized in _BOOLEAN_METADATA_TYPES:
        return "boolean"
    if normalized in _INTEGER_METADATA_TYPES:
        return "integer"
    if normalized in _NUMBER_METADATA_TYPES:
        return "number"
    if normalized == "string":
        return "string"
    return None

ReadCall = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]


class MetadataDiscoveryError(ValueError):
    """A live metadata discovery request or result cannot be used safely."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = _bounded_error_details(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class MetadataDiscoveryResult:
    """Machine-readable lexical retrieval result backed by live WAAPI data."""

    scope: Mapping[str, Any]
    queries: tuple[str, ...]
    available_name_count: int
    query_results: tuple[Mapping[str, Any], ...]
    candidates: tuple[Mapping[str, Any], ...]
    dependency_candidates: tuple[Mapping[str, Any], ...]
    dependency_closure_complete: bool
    unresolved_dependencies: tuple[Mapping[str, Any], ...]
    fallback_detail_scan: Mapping[str, Any]

    def as_dict(self, *, detail: bool = False) -> dict[str, Any]:
        """Return the compact agent contract or the reviewed full audit view."""

        payload = {
            "contract": (
                METADATA_DISCOVERY_DETAIL_CONTRACT
                if detail
                else METADATA_DISCOVERY_CONTRACT
            ),
            "authority": "live-waapi",
            **({} if detail else {"result_detail": "compact"}),
            "scope": dict(self.scope),
            "queries": list(self.queries),
            "available_name_count": self.available_name_count,
            "candidate_count": len(self.candidates),
            "query_results": [dict(item) for item in self.query_results],
            "candidates": [
                (
                    dict(item)
                    if detail
                    else _compact_candidate_payload(item)
                )
                for item in self.candidates
            ],
            "dependency_candidates": [
                (
                    dict(item)
                    if detail
                    else _compact_dependency_candidate_payload(item)
                )
                for item in self.dependency_candidates
            ],
            "dependency_closure_complete": self.dependency_closure_complete,
            "unresolved_dependencies": [
                dict(item) for item in self.unresolved_dependencies
            ],
            "fallback_detail_scan": dict(self.fallback_detail_scan),
            "selection_required": True,
            "exact_live_name_required_for_mutation": True,
        }
        _require_result_size(
            payload,
            maximum_bytes=(
                MAX_METADATA_DISCOVERY_RESULT_BYTES
                if detail
                else MAX_METADATA_DISCOVERY_AGENT_RESULT_BYTES
            ),
            pretty=not detail,
        )
        return payload


@dataclass(frozen=True, slots=True)
class _Candidate:
    name: str
    info: PropertyInfoMetadataRecord
    scores: Mapping[str, int]

    @property
    def aggregate_score(self) -> int:
        return sum(self.scores.values())


def discover_metadata(
    *,
    read_call: ReadCall,
    queries: Sequence[str],
    object_type: str | None = None,
    class_id: int | None = None,
    object: str | int | None = None,
    limit: int = DEFAULT_METADATA_DISCOVERY_LIMIT,
) -> MetadataDiscoveryResult:
    """Retrieve bounded live metadata candidates for natural-language phrases.

    Exactly one of ``object_type``, ``class_id``, or ``object`` is required.
    ``object_type`` is resolved by an exact, case-insensitive match against the
    live ``getTypes`` ``name`` field before any class-scoped reads are made.
    ``limit`` bounds returned candidates per search phrase; the union remains
    capped by :data:`MAX_METADATA_DISCOVERY_DETAIL_POOL`.
    """

    normalized_queries = _validate_queries(queries)
    _validate_limit(limit)
    scope, live_scope_args = _resolve_scope(
        read_call,
        object_type=object_type,
        class_id=class_id,
        object=object,
    )
    names = _read_names(read_call, live_scope_args)

    initial_rankings = {
        query: _rank_names(query, names)
        for query in normalized_queries
    }
    initial_detail_names = _select_detail_pool(
        initial_rankings,
        query_order=normalized_queries,
        per_query_limit=limit,
    )
    fallback_queries = tuple(
        query for query in normalized_queries if not initial_rankings[query]
    )
    fallback_names = (
        names[:MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN]
        if fallback_queries
        else ()
    )
    detail_names = tuple(
        dict.fromkeys((*initial_detail_names, *fallback_names))
    )
    fallback_scan_complete = (
        not fallback_queries or len(fallback_names) == len(names)
    )
    fallback_detail_scan = {
        "status": (
            "not_needed"
            if not fallback_queries
            else "complete"
            if fallback_scan_complete
            else "partial"
        ),
        "trigger_queries": list(fallback_queries),
        "live_name_count": len(names),
        "inspected_name_count": len(fallback_names),
        "inspection_limit": MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN,
    }
    info_by_name = {
        name: _read_property_info(read_call, live_scope_args, name)
        for name in detail_names
    }

    enriched_rankings: dict[str, tuple[tuple[str, int], ...]] = {}
    for query in normalized_queries:
        ranked: list[tuple[str, int]] = []
        for name, info in info_by_name.items():
            score = _candidate_score(query, name=name, info=info)
            if score > 0:
                ranked.append((name, score))
        enriched_rankings[query] = tuple(
            sorted(ranked, key=lambda item: (-item[1], item[0].casefold(), item[0]))
        )

    selected_names = _select_candidates(
        enriched_rankings,
        query_order=normalized_queries,
        per_query_limit=limit,
    )
    selected = tuple(
        _Candidate(
            name=name,
            info=info_by_name[name],
            scores={
                query: dict(enriched_rankings[query]).get(name, 0)
                for query in normalized_queries
                if dict(enriched_rankings[query]).get(name, 0) > 0
            },
        )
        for name in selected_names
    )

    (
        dependency_candidates,
        dependency_names_by_candidate,
        dependency_closure_complete,
        unresolved_dependencies,
    ) = _resolve_dependency_closure(
        read_call,
        live_scope_args,
        available_names=names,
        candidates=selected,
    )

    candidate_payloads = tuple(
        _candidate_payload(
            candidate,
            query_order=normalized_queries,
            same_object_dependencies=dependency_names_by_candidate.get(
                candidate.name,
                (),
            ),
        )
        for candidate in selected
    )
    query_results = tuple(
        {
            "query": query,
            "status": _query_status(query, enriched_rankings[query]),
            "candidate_names": [
                name
                for name, _score in enriched_rankings[query][:limit]
                if name in selected_names
            ],
        }
        for query in normalized_queries
    )

    result = MetadataDiscoveryResult(
        scope=scope,
        queries=normalized_queries,
        available_name_count=len(names),
        query_results=query_results,
        candidates=candidate_payloads,
        dependency_candidates=dependency_candidates,
        dependency_closure_complete=dependency_closure_complete,
        unresolved_dependencies=unresolved_dependencies,
        fallback_detail_scan=fallback_detail_scan,
    )
    _require_result_size(result.as_dict())
    return result


def _resolve_scope(
    read_call: ReadCall,
    *,
    object_type: str | None,
    class_id: int | None,
    object: str | int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    supplied = (
        object_type is not None,
        class_id is not None,
        object is not None,
    )
    if sum(supplied) != 1:
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_SCOPE",
            "Metadata discovery requires exactly one object_type, class_id, or object scope.",
            details={
                "object_type_supplied": supplied[0],
                "class_id_supplied": supplied[1],
                "object_supplied": supplied[2],
            },
        )

    if object_type is not None:
        requested = _required_text(
            object_type,
            field="object_type",
            maximum=MAX_METADATA_DISCOVERY_NAME_CHARS,
        )
        rows = _read_types(read_call)
        matches = [
            row
            for row in rows
            if row.name.casefold() == requested.casefold()
        ]
        if len(matches) != 1:
            raise MetadataDiscoveryError(
                "OBJECT_TYPE_NOT_UNIQUE",
                "object_type must match exactly one live Wwise object type name.",
                details={
                    "requested": requested,
                    "matches": [row.as_dict() for row in matches[:8]],
                    "match_count": len(matches),
                },
            )
        match = matches[0]
        return (
            {
                "kind": "object_type",
                "requested": requested,
                "resolved": match.as_dict(),
            },
            {"classId": match.class_id},
        )

    if class_id is not None:
        if (
            isinstance(class_id, bool)
            or not isinstance(class_id, int)
            or not 0 <= class_id <= 0xFFFFFFFF
        ):
            raise MetadataDiscoveryError(
                "INVALID_CLASS_ID",
                "class_id must be a uint32 integer.",
                details={"actual_type": type(class_id).__name__},
            )
        return (
            {"kind": "class_id", "class_id": class_id},
            {"classId": class_id},
        )

    assert object is not None
    if isinstance(object, bool) or not isinstance(object, str | int):
        raise MetadataDiscoveryError(
            "INVALID_OBJECT_SCOPE",
            "object must be a non-empty WAAPI object identifier.",
            details={"actual_type": type(object).__name__},
        )
    if isinstance(object, str):
        normalized_object: str | int = _required_text(
            object,
            field="object",
            maximum=MAX_METADATA_DISCOVERY_NAME_CHARS * 8,
        )
    else:
        if not 0 <= object <= 0xFFFFFFFF:
            raise MetadataDiscoveryError(
                "INVALID_OBJECT_SCOPE",
                "Integer object identifiers must be uint32 values.",
                details={"actual": object},
            )
        normalized_object = object
    return (
        {"kind": "object", "object": normalized_object},
        {"object": normalized_object},
    )


def _read_types(read_call: ReadCall) -> tuple[ObjectTypeMetadataRecord, ...]:
    result = _closed_read(read_call, GET_TYPES_URI, {}, {})
    try:
        rows = parse_get_types_result(result)
    except SemanticValidationError as exc:
        raise _invalid_live_metadata(GET_TYPES_URI, exc) from exc
    if not rows:
        raise MetadataDiscoveryError(
            "EMPTY_LIVE_METADATA",
            "Live object.getTypes returned no object types.",
            details={"uri": GET_TYPES_URI},
        )
    if len(rows) > MAX_METADATA_DISCOVERY_TYPES:
        raise MetadataDiscoveryError(
            "LIVE_METADATA_LIMIT_EXCEEDED",
            "Live object type inventory exceeds the discovery limit.",
            details={
                "uri": GET_TYPES_URI,
                "count": len(rows),
                "limit": MAX_METADATA_DISCOVERY_TYPES,
            },
        )
    return rows


def _read_names(
    read_call: ReadCall,
    scope_args: Mapping[str, Any],
) -> tuple[str, ...]:
    result = _closed_read(
        read_call,
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        scope_args,
        {},
    )
    try:
        records = parse_property_and_reference_names_result(result)
    except SemanticValidationError as exc:
        raise _invalid_live_metadata(
            GET_PROPERTY_AND_REFERENCE_NAMES_URI,
            exc,
        ) from exc
    if len(records) > MAX_METADATA_DISCOVERY_NAMES:
        raise MetadataDiscoveryError(
            "LIVE_METADATA_LIMIT_EXCEEDED",
            "Live property/reference inventory exceeds the discovery limit.",
            details={
                "uri": GET_PROPERTY_AND_REFERENCE_NAMES_URI,
                "count": len(records),
                "limit": MAX_METADATA_DISCOVERY_NAMES,
            },
        )

    by_folded_name: dict[str, str] = {}
    for record in records:
        name = _required_live_name(record.name)
        folded = name.casefold()
        previous = by_folded_name.get(folded)
        if previous is not None and previous != name:
            raise MetadataDiscoveryError(
                "AMBIGUOUS_LIVE_NAME",
                "Live metadata returned property/reference names that differ only by case.",
                details={"names": [previous, name]},
            )
        by_folded_name[folded] = name
    return tuple(
        sorted(by_folded_name.values(), key=lambda value: (value.casefold(), value))
    )


def _read_property_info(
    read_call: ReadCall,
    scope_args: Mapping[str, Any],
    name: str,
) -> PropertyInfoMetadataRecord:
    result = _closed_read(
        read_call,
        GET_PROPERTY_INFO_URI,
        {**scope_args, "property": name},
        {},
    )
    try:
        info = parse_get_property_info_result(result)
    except SemanticValidationError as exc:
        raise _invalid_live_metadata(GET_PROPERTY_INFO_URI, exc) from exc
    if info.name != name:
        raise MetadataDiscoveryError(
            "LIVE_METADATA_NAME_MISMATCH",
            "getPropertyInfo returned metadata for a different field.",
            details={"requested": name, "actual": info.name},
        )
    payload = info.as_dict()
    try:
        size = len(canonical_json_bytes(payload))
    except (TypeError, ValueError) as exc:
        raise MetadataDiscoveryError(
            "INVALID_LIVE_METADATA",
            "getPropertyInfo returned non-JSON metadata.",
            details={
                "uri": GET_PROPERTY_INFO_URI,
                "property": name,
                "cause_type": type(exc).__name__,
            },
        ) from exc
    if size > MAX_METADATA_DISCOVERY_INFO_BYTES:
        raise MetadataDiscoveryError(
            "LIVE_METADATA_LIMIT_EXCEEDED",
            "One getPropertyInfo result exceeds the discovery size limit.",
            details={
                "uri": GET_PROPERTY_INFO_URI,
                "property": name,
                "size_bytes": size,
                "limit_bytes": MAX_METADATA_DISCOVERY_INFO_BYTES,
            },
        )
    return info


def _closed_read(
    read_call: ReadCall,
    uri: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
) -> Mapping[str, Any]:
    if uri not in _APPROVED_URIS:  # pragma: no cover - internal invariant
        raise AssertionError(f"metadata discovery URI is not approved: {uri}")
    try:
        result = read_call(uri, dict(args), dict(options))
    except MetadataDiscoveryError:
        raise
    except Exception as exc:
        raise MetadataDiscoveryError(
            "LIVE_METADATA_READ_FAILED",
            "A required live WAAPI metadata read failed.",
            details={
                "uri": uri,
                "cause_type": type(exc).__name__,
                "cause": _bounded_text(str(exc), 512),
            },
        ) from exc
    if not isinstance(result, Mapping):
        raise MetadataDiscoveryError(
            "INVALID_LIVE_METADATA",
            "Live WAAPI metadata reads must return JSON objects.",
            details={"uri": uri, "actual_type": type(result).__name__},
        )
    return result


def _rank_names(query: str, names: Sequence[str]) -> tuple[tuple[str, int], ...]:
    rows = [
        (name, _lexical_score(query, (name,)))
        for name in names
    ]
    return tuple(
        sorted(
            (row for row in rows if row[1] > 0),
            key=lambda item: (-item[1], item[0].casefold(), item[0]),
        )
    )


def _candidate_score(
    query: str,
    *,
    name: str,
    info: PropertyInfoMetadataRecord,
) -> int:
    canonical_score = _lexical_score(query, (name,))
    metadata_strings = _metadata_search_strings(info)
    metadata_score = _lexical_score(query, metadata_strings)
    return canonical_score * 4 + metadata_score


def _lexical_score(query: str, surfaces: Sequence[str]) -> int:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0
    query_compact = "".join(query_tokens)
    best = 0
    for surface in surfaces:
        surface_tokens = _tokens(surface)
        if not surface_tokens:
            continue
        surface_compact = "".join(surface_tokens)
        score = 0
        if query_compact == surface_compact:
            score += 20_000
        elif query_compact in surface_compact:
            score += 2_000
        elif len(surface_compact) >= 4 and surface_compact in query_compact:
            score += 1_000

        matched_tokens = 0
        for query_token in query_tokens:
            token_score = max(
                (
                    _token_score(query_token, surface_token)
                    for surface_token in surface_tokens
                ),
                default=0,
            )
            if token_score:
                matched_tokens += 1
                score += token_score
        if matched_tokens == len(query_tokens):
            score += 1_000
        score += matched_tokens * 100
        best = max(best, score)
    return best


def _token_score(query_token: str, surface_token: str) -> int:
    if query_token == surface_token:
        return 500
    shorter = min(len(query_token), len(surface_token))
    if shorter >= 4 and (
        query_token.startswith(surface_token)
        or surface_token.startswith(query_token)
    ):
        return 300
    if shorter >= 5 and (
        query_token in surface_token
        or surface_token in query_token
    ):
        return 180
    return 0


def _tokens(value: str) -> tuple[str, ...]:
    expanded = _CAMEL_ACRONYM_BOUNDARY.sub(" ", value)
    expanded = _CAMEL_WORD_BOUNDARY.sub(" ", expanded)
    return tuple(token.casefold() for token in _WORD.findall(expanded))


def _metadata_search_strings(
    info: PropertyInfoMetadataRecord,
) -> tuple[str, ...]:
    values: list[str] = [info.type]
    for source in (
        info.display,
        info.ui,
        info.restriction,
        info.dependencies,
    ):
        _collect_strings(source, values)
        if len(values) >= _MAX_METADATA_SEARCH_STRINGS:
            break
    return tuple(values[:_MAX_METADATA_SEARCH_STRINGS])


def _collect_strings(value: Any, output: list[str]) -> None:
    if len(output) >= _MAX_METADATA_SEARCH_STRINGS:
        return
    if isinstance(value, str):
        output.append(value[:_MAX_METADATA_SEARCH_STRING_CHARS])
        return
    if isinstance(value, Mapping):
        for key in sorted(value, key=lambda item: str(item)):
            _collect_strings(value[key], output)
            if len(output) >= _MAX_METADATA_SEARCH_STRINGS:
                return
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_strings(item, output)
            if len(output) >= _MAX_METADATA_SEARCH_STRINGS:
                return


def _select_detail_pool(
    rankings: Mapping[str, Sequence[tuple[str, int]]],
    *,
    query_order: Sequence[str],
    per_query_limit: int,
) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    depth = 0
    while len(selected) < MAX_METADATA_DISCOVERY_DETAIL_POOL:
        added = False
        for query in query_order:
            rows = rankings[query][:per_query_limit]
            if depth >= len(rows):
                continue
            name = rows[depth][0]
            if name not in seen:
                seen.add(name)
                selected.append(name)
                added = True
                if len(selected) >= MAX_METADATA_DISCOVERY_DETAIL_POOL:
                    break
        if not added:
            break
        depth += 1
    return tuple(selected)


def _select_candidates(
    rankings: Mapping[str, Sequence[tuple[str, int]]],
    *,
    query_order: Sequence[str],
    per_query_limit: int,
) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    depth = 0
    while len(selected) < MAX_METADATA_DISCOVERY_DETAIL_POOL:
        added = False
        for query in query_order:
            rows = rankings[query][:per_query_limit]
            if depth >= len(rows):
                continue
            name = rows[depth][0]
            if name not in seen:
                seen.add(name)
                selected.append(name)
                added = True
                if len(selected) >= MAX_METADATA_DISCOVERY_DETAIL_POOL:
                    break
        if not added:
            break
        depth += 1
    return tuple(selected)


def _resolve_dependency_closure(
    read_call: ReadCall,
    scope_args: Mapping[str, Any],
    *,
    available_names: Sequence[str],
    candidates: Sequence[_Candidate],
) -> tuple[
    tuple[Mapping[str, Any], ...],
    Mapping[str, tuple[str, ...]],
    bool,
    tuple[Mapping[str, Any], ...],
]:
    canonical_names = {name.casefold(): name for name in available_names}
    root_names = {candidate.name for candidate in candidates}
    info_by_name = {candidate.name: candidate.info for candidate in candidates}
    required_by: dict[str, set[str]] = {}
    names_by_candidate: dict[str, list[str]] = {
        candidate.name: [] for candidate in candidates
    }
    unresolved: list[dict[str, Any]] = []
    queue: list[tuple[str, str, PropertyInfoMetadataRecord, int]] = [
        (candidate.name, candidate.name, candidate.info, 0)
        for candidate in candidates
    ]
    expanded: set[tuple[str, str]] = set()

    while queue:
        root_name, source_name, info, depth = queue.pop(0)
        expansion_key = (root_name.casefold(), source_name.casefold())
        if expansion_key in expanded:
            continue
        expanded.add(expansion_key)
        for index, dependency in enumerate(info.dependencies):
            if _is_terminal_structural_dependency(dependency):
                # Wwise 2024+ may expose a visibility predicate such as
                # ``isMasterBus == false``.  It describes the current object
                # shape and names no further property to retrieve.  Preserve
                # it in the candidate's original metadata, but do not invent
                # a dependency token or mark the property closure incomplete.
                continue
            context = dependency.get("context")
            property_name = dependency.get("property")
            if (
                not isinstance(context, str)
                or context.casefold() != "self"
                or not isinstance(property_name, str)
                or not property_name.strip()
            ):
                unresolved.append(
                    {
                        "required_by": source_name,
                        "root_candidate": root_name,
                        "dependency_index": index,
                        "reason": "not-a-resolvable-same-object-property",
                        "dependency": dict(dependency),
                    }
                )
                continue
            canonical = canonical_names.get(property_name.casefold())
            if canonical is None:
                unresolved.append(
                    {
                        "required_by": source_name,
                        "root_candidate": root_name,
                        "dependency_index": index,
                        "reason": "dependency-name-not-in-live-inventory",
                        "dependency": dict(dependency),
                    }
                )
                continue
            if canonical == root_name:
                # A cyclic edge back to the selected candidate is already
                # satisfied by the root metadata and must not consume depth.
                continue
            if canonical not in names_by_candidate[root_name]:
                names_by_candidate[root_name].append(canonical)
            required_by.setdefault(canonical, set()).add(source_name)
            if canonical == source_name:
                continue
            if (
                root_name.casefold(),
                canonical.casefold(),
            ) in expanded:
                # The dependency metadata for this field was already expanded
                # for the same root.  This is a closed cycle, not a reason to
                # consume more depth or repeat a live read.
                continue
            if depth >= MAX_METADATA_DISCOVERY_DEPENDENCY_DEPTH:
                raise MetadataDiscoveryError(
                    "DEPENDENCY_LIMIT_EXCEEDED",
                    "Live same-object metadata dependencies exceed the discovery depth limit.",
                    details={
                        "root_candidate": root_name,
                        "property": canonical,
                        "limit": MAX_METADATA_DISCOVERY_DEPENDENCY_DEPTH,
                    },
                )
            if len(required_by) > MAX_METADATA_DISCOVERY_DEPENDENCIES:
                raise MetadataDiscoveryError(
                    "DEPENDENCY_LIMIT_EXCEEDED",
                    "Live same-object metadata dependencies exceed the discovery count limit.",
                    details={
                        "count": len(required_by),
                        "limit": MAX_METADATA_DISCOVERY_DEPENDENCIES,
                    },
                )
            dependency_info = info_by_name.get(canonical)
            if dependency_info is None:
                dependency_info = _read_property_info(
                    read_call,
                    scope_args,
                    canonical,
                )
                info_by_name[canonical] = dependency_info
            queue.append((root_name, canonical, dependency_info, depth + 1))

    dependency_payloads = tuple(
        {
            "name": name,
            "kind": _metadata_kind(info_by_name[name]),
            "required_by": sorted(
                required_by[name],
                key=lambda value: (value.casefold(), value),
            ),
            "metadata": info_by_name[name].as_dict(),
        }
        for name in sorted(
            (name for name in required_by if name not in root_names),
            key=lambda value: (value.casefold(), value),
        )
    )
    normalized_names_by_candidate = {
        name: tuple(
            sorted(values, key=lambda value: (value.casefold(), value))
        )
        for name, values in names_by_candidate.items()
    }
    unresolved_payload = tuple(unresolved[:MAX_METADATA_DISCOVERY_DEPENDENCIES])
    return (
        dependency_payloads,
        normalized_names_by_candidate,
        not unresolved,
        unresolved_payload,
    )


def _is_terminal_structural_dependency(dependency: Mapping[str, Any]) -> bool:
    """Recognize one schema-defined predicate that has no property edge."""

    return (
        set(dependency) == {"type", "action", "context", "value"}
        and dependency.get("type") == "isMasterBus"
        and isinstance(dependency.get("action"), str)
        and bool(dependency["action"].strip())
        and dependency.get("context", "").casefold() == "self"
        and isinstance(dependency.get("value"), bool)
    )


def _candidate_payload(
    candidate: _Candidate,
    *,
    query_order: Sequence[str],
    same_object_dependencies: Sequence[str],
) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "kind": _metadata_kind(candidate.info),
        "matched_queries": [
            query for query in query_order if candidate.scores.get(query, 0) > 0
        ],
        "match_evidence": [
            _match_evidence(
                query,
                name=candidate.name,
                info=candidate.info,
                score=candidate.scores[query],
            )
            for query in query_order
            if candidate.scores.get(query, 0) > 0
        ],
        "same_object_dependencies": list(same_object_dependencies),
        "metadata": candidate.info.as_dict(),
    }


def _compact_candidate_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Project one live candidate to the fields needed for safe selection."""

    name = str(candidate["name"])
    metadata = candidate["metadata"]
    assert isinstance(metadata, Mapping)
    return {
        "name": name,
        "kind": candidate["kind"],
        "matched_queries": list(candidate["matched_queries"]),
        "same_object_dependencies": list(
            candidate["same_object_dependencies"]
        ),
        "dependency_requirements": _compact_dependency_requirements(
            metadata,
            owner_name=name,
        ),
        "metadata": _compact_metadata(metadata),
    }


def _compact_dependency_candidate_payload(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Project dependency detail without repeating bulky UI-only metadata."""

    name = str(candidate["name"])
    metadata = candidate["metadata"]
    assert isinstance(metadata, Mapping)
    return {
        "name": name,
        "kind": candidate["kind"],
        "required_by": list(candidate["required_by"]),
        "dependency_requirements": _compact_dependency_requirements(
            metadata,
            owner_name=name,
        ),
        "metadata": _compact_metadata(metadata),
    }


def _compact_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Keep mutation-relevant metadata and omit redundant presentation bulk."""

    display = metadata.get("display")
    compact_display = (
        {
            key: display[key]
            for key in ("name", "group")
            if key in display
        }
        if isinstance(display, Mapping)
        else {}
    )
    restriction = metadata.get("restriction")
    compact_restriction = (
        dict(restriction) if isinstance(restriction, Mapping) else {}
    )
    payload = {
        "name": metadata["name"],
        "type": metadata["type"],
        "default": metadata.get("default"),
        "display": compact_display,
        "restriction": compact_restriction,
    }
    typed_value_type = metadata_typed_value_type(str(metadata["type"]))
    if typed_value_type is not None:
        payload["typed_value_type"] = typed_value_type
    if (
        str(compact_restriction.get("type", "")).casefold() == "range"
        and (
            "min" in compact_restriction
            or "max" in compact_restriction
        )
    ):
        payload["range"] = {
            key: compact_restriction[key]
            for key in ("min", "max")
            if key in compact_restriction
        }
    return payload


def _compact_dependency_requirements(
    metadata: Mapping[str, Any],
    *,
    owner_name: str,
) -> list[dict[str, Any]]:
    """Expose direct same-object dependency names and live-required values."""

    dependencies = metadata.get("dependencies")
    if not isinstance(dependencies, list | tuple):
        return []
    requirements: list[dict[str, Any]] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            continue
        context = dependency.get("context")
        name = dependency.get("property")
        if (
            not isinstance(context, str)
            or context.casefold() != "self"
            or not isinstance(name, str)
            or not name
            or name.casefold() == owner_name.casefold()
        ):
            continue
        requirement = dict(dependency)
        requirement["required_values"] = _dependency_required_values(
            dependency
        )
        requirements.append(requirement)
    return requirements


def _dependency_required_values(
    dependency: Mapping[str, Any],
) -> list[Any]:
    """Return exact condition values, plus the reviewed Boolean override case."""

    values: list[Any] = []
    seen: set[bytes] = set()
    conditions = dependency.get("conditions")
    if isinstance(conditions, list | tuple):
        for condition in conditions:
            restriction = (
                condition.get("restriction")
                if isinstance(condition, Mapping)
                else None
            )
            rows = (
                restriction.get("values")
                if isinstance(restriction, Mapping)
                else None
            )
            if not isinstance(rows, list | tuple):
                continue
            for row in rows:
                if not isinstance(row, Mapping) or "value" not in row:
                    continue
                value = row["value"]
                try:
                    canonical = canonical_json_bytes(value)
                except (TypeError, ValueError):
                    continue
                if canonical not in seen:
                    seen.add(canonical)
                    values.append(value)
    if values:
        return values
    if (
        dependency.get("type") == "override"
        and dependency.get("action") == "Enable"
    ):
        return [True]
    return []


def _query_status(
    query: str,
    ranking: Sequence[tuple[str, int]],
) -> str:
    if any(name.casefold() == query.casefold() for name, _score in ranking):
        return "exact_live_name"
    if not ranking:
        return "no_match"
    if len(ranking) == 1:
        return "single_candidate"
    return "multiple_candidates"


def _match_evidence(
    query: str,
    *,
    name: str,
    info: PropertyInfoMetadataRecord,
    score: int,
) -> dict[str, Any]:
    sources: list[dict[str, str]] = []
    if _lexical_score(query, (name,)) > 0:
        sources.append({"field": "name", "value": name})
    metadata_matches = sorted(
        {
            value
            for value in _metadata_search_strings(info)
            if _lexical_score(query, (value,)) > 0
        },
        key=lambda value: (value.casefold(), value),
    )
    sources.extend(
        {"field": "live_metadata", "value": value}
        for value in metadata_matches[:4]
    )
    return {
        "query": query,
        "score": score,
        "sources": sources,
    }


def _metadata_kind(info: PropertyInfoMetadataRecord) -> str:
    if (
        info.type.casefold() in {"reference", "objectreference"}
        or str(info.restriction.get("type", "")).casefold() == "reference"
    ):
        return "reference"
    return "property"


def _validate_queries(queries: Sequence[str]) -> tuple[str, ...]:
    if isinstance(queries, (str, bytes)) or not isinstance(queries, Sequence):
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_QUERY",
            "queries must be an ordered array of natural-language phrases.",
            details={"actual_type": type(queries).__name__},
        )
    if not 1 <= len(queries) <= MAX_METADATA_DISCOVERY_QUERIES:
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_QUERY",
            "Metadata discovery requires a bounded number of search phrases.",
            details={
                "count": len(queries),
                "minimum": 1,
                "maximum": MAX_METADATA_DISCOVERY_QUERIES,
            },
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for index, query in enumerate(queries):
        value = _required_text(
            query,
            field=f"queries[{index}]",
            maximum=MAX_METADATA_DISCOVERY_QUERY_CHARS,
        )
        value = " ".join(value.split())
        folded = value.casefold()
        if folded in seen:
            raise MetadataDiscoveryError(
                "INVALID_DISCOVERY_QUERY",
                "Metadata discovery search phrases must be distinct.",
                details={"duplicate_index": index},
            )
        seen.add(folded)
        normalized.append(value)
    if sum(len(value) for value in normalized) > MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS:
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_QUERY",
            "Metadata discovery search phrases exceed the total character limit.",
            details={
                "total_characters": sum(len(value) for value in normalized),
                "maximum": MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS,
            },
        )
    return tuple(normalized)


def _validate_limit(limit: int) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_METADATA_DISCOVERY_LIMIT
    ):
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_LIMIT",
            "Metadata discovery limit is outside the supported range.",
            details={
                "actual": limit,
                "minimum": 1,
                "maximum": MAX_METADATA_DISCOVERY_LIMIT,
            },
        )


def _required_text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_ARGUMENT",
            f"{field} must be a non-empty string.",
            details={"field": field, "actual_type": type(value).__name__},
        )
    normalized = value.strip()
    if len(normalized) > maximum:
        raise MetadataDiscoveryError(
            "INVALID_DISCOVERY_ARGUMENT",
            f"{field} exceeds the character limit.",
            details={
                "field": field,
                "characters": len(normalized),
                "maximum": maximum,
            },
        )
    return normalized


def _required_live_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise MetadataDiscoveryError(
            "INVALID_LIVE_METADATA",
            "Live property/reference names must be non-empty strings.",
            details={"uri": GET_PROPERTY_AND_REFERENCE_NAMES_URI},
        )
    if len(name) > MAX_METADATA_DISCOVERY_NAME_CHARS:
        raise MetadataDiscoveryError(
            "LIVE_METADATA_LIMIT_EXCEEDED",
            "One live property/reference name exceeds the discovery limit.",
            details={
                "uri": GET_PROPERTY_AND_REFERENCE_NAMES_URI,
                "characters": len(name),
                "limit": MAX_METADATA_DISCOVERY_NAME_CHARS,
            },
        )
    return name


def _invalid_live_metadata(
    uri: str,
    exc: SemanticValidationError,
) -> MetadataDiscoveryError:
    return MetadataDiscoveryError(
        "INVALID_LIVE_METADATA",
        "A live WAAPI metadata response failed its closed parser.",
        details={"uri": uri, "parser_error": exc.as_dict()},
    )


def _bounded_error_details(details: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(details)
    try:
        if len(canonical_json_bytes(payload)) <= MAX_METADATA_DISCOVERY_ERROR_DETAILS_BYTES:
            return payload
    except (TypeError, ValueError):
        pass
    return {
        "details_omitted": True,
        "reason": "error details exceeded the public JSON bound",
    }


def _bounded_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: maximum - 1] + "…"


def _require_result_size(
    payload: Mapping[str, Any],
    *,
    maximum_bytes: int = MAX_METADATA_DISCOVERY_RESULT_BYTES,
    pretty: bool = False,
) -> None:
    try:
        size = (
            len(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=False,
                    allow_nan=False,
                ).encode("utf-8")
            )
            + 1
            if pretty
            else len(canonical_json_bytes(payload))
        )
    except (TypeError, ValueError) as exc:
        raise MetadataDiscoveryError(
            "INVALID_LIVE_METADATA",
            "Metadata discovery result contains non-JSON live metadata.",
            details={"cause_type": type(exc).__name__},
        ) from exc
    if size > maximum_bytes:
        raise MetadataDiscoveryError(
            "DISCOVERY_RESULT_LIMIT_EXCEEDED",
            "Metadata discovery result exceeds the public size limit.",
            details={
                "size_bytes": size,
                "limit_bytes": maximum_bytes,
                "result_detail": payload.get("result_detail"),
            },
        )


__all__ = [
    "DEFAULT_METADATA_DISCOVERY_LIMIT",
    "MAX_METADATA_DISCOVERY_AGENT_RESULT_BYTES",
    "MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN",
    "MAX_METADATA_DISCOVERY_LIMIT",
    "MAX_METADATA_DISCOVERY_NAME_CHARS",
    "MAX_METADATA_DISCOVERY_QUERIES",
    "MAX_METADATA_DISCOVERY_QUERY_CHARS",
    "MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS",
    "METADATA_DISCOVERY_CONTRACT",
    "METADATA_DISCOVERY_DETAIL_CONTRACT",
    "MetadataDiscoveryError",
    "MetadataDiscoveryResult",
    "discover_metadata",
]

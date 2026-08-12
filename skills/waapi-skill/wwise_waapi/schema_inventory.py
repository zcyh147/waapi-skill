"""Immutable five-version schema graph and typed request surface inventory."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .builders.common import DEFAULT_MANIFEST_ROOT
from .capabilities import CapabilityCatalog
from .execution_contracts import AUTHORING_UI_EXECUTION_PROFILE
from .native_surface_policy import load_native_surface_policy
from .versions import SUPPORTED_WWISE_VERSION_KEYS


DEFINITION_GRAPH_CONTRACT = "waapi-skill.definition-graph/v1"
TYPED_REQUEST_SURFACE_CONTRACT = "waapi-skill.typed-request-surface/v1"
DEFINITION_GRAPH_FILENAME = "definitions.json"
TYPED_REQUEST_SURFACE_FILENAME = "typed-request-surface.json"
SCHEMA_SECTIONS = (
    "argsSchema",
    "optionsSchema",
    "resultSchema",
    "publishSchema",
)
SCHEMA_CHILD_MAP_KEYWORDS = frozenset(
    {"properties", "patternProperties", "definitions", "localDefinitions"}
)
SCHEMA_CHILD_LIST_KEYWORDS = frozenset({"oneOf", "anyOf", "allOf"})
SCHEMA_CHILD_SCHEMA_KEYWORDS = frozenset({"items", "additionalProperties"})
SCHEMA_ANNOTATION_KEYWORDS = frozenset(
    {
        "description",
        "descriptionOverride",
        "descriptions",
        "examples",
        "optionalPositional",
        "synopsis",
    }
)
SCHEMA_VALIDATION_KEYWORDS = frozenset(
    {
        "$ref",
        "#ref",
        "additionalProperties",
        "anyOf",
        "definitions",
        "enum",
        "id",
        "items",
        "localDefinitions",
        "maximum",
        "maxItems",
        "minimum",
        "minItems",
        "minLength",
        "oneOf",
        "pattern",
        "patternProperties",
        "properties",
        "required",
        "type",
    }
)
KNOWN_SCHEMA_KEYWORDS = (
    SCHEMA_VALIDATION_KEYWORDS
    | SCHEMA_ANNOTATION_KEYWORDS
    | SCHEMA_CHILD_LIST_KEYWORDS
)
LEGACY_2021_IMPLICIT_PROPERTY_NAMES = frozenset(
    {
        "ExcludedMemoryFiles",
        "GameParameters",
        "IncludedAuxBusses",
        "IncludedMemoryFiles",
        "ReferencedStreamedFiles",
        "StateGroups",
        "SwitchContainers",
        "SwitchGroups",
        "Triggers",
    }
)


class SchemaInventoryError(ValueError):
    """A packaged schema graph or request-surface inventory is invalid."""


@dataclass(frozen=True, slots=True)
class DefinitionGraph:
    """One exact-version collection of authoritative reflected definitions."""

    contract: str
    version: str
    wwise_build: str
    source_file_names: tuple[str, ...]
    documents: Mapping[str, Mapping[str, Any]]
    inventory_sha256: str

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset(
            str(name)
            for document in self.documents.values()
            for name in _require_mapping(
                document.get("definitions"),
                context="definition document definitions",
            )
        )


@dataclass(frozen=True, slots=True)
class ResolvedSchemaReference:
    """One same-version schema reference resolved to its exact target node."""

    reference: str
    document_name: str
    pointer: str
    target: Mapping[str, Any]


def load_definition_graph(
    version: str,
    *,
    root: Path = DEFAULT_MANIFEST_ROOT,
) -> DefinitionGraph:
    """Load one exact-version graph without any cross-version fallback."""

    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise SchemaInventoryError(f"Unsupported Wwise version: {version!r}")
    path = Path(root) / version / DEFINITION_GRAPH_FILENAME
    payload = _read_json_object(path)
    if payload.get("contract") != DEFINITION_GRAPH_CONTRACT:
        raise SchemaInventoryError(
            f"Definition graph {path} has an unsupported contract"
        )
    if payload.get("version") != version:
        raise SchemaInventoryError(
            f"Definition graph {path} expected {version}, got {payload.get('version')!r}"
        )
    build = payload.get("wwise_build")
    if not isinstance(build, str) or not build.startswith(f"{version}."):
        raise SchemaInventoryError(
            f"Definition graph {path} has an invalid Wwise build"
        )
    source_file_names = payload.get("source_file_names")
    if (
        not isinstance(source_file_names, list)
        or not source_file_names
        or not all(isinstance(name, str) and name for name in source_file_names)
        or len(source_file_names) != len(set(source_file_names))
    ):
        raise SchemaInventoryError(
            f"Definition graph {path} has invalid source file names"
        )
    documents_raw = _require_mapping(
        payload.get("documents"),
        context=f"Definition graph {path} documents",
    )
    documents: dict[str, Mapping[str, Any]] = {}
    for name, raw_document in documents_raw.items():
        if not isinstance(name, str) or not name.endswith(".json"):
            raise SchemaInventoryError(
                f"Definition graph {path} has an invalid document name"
            )
        document = _require_mapping(
            raw_document,
            context=f"Definition graph {path} document {name}",
        )
        definitions = _require_mapping(
            document.get("definitions"),
            context=f"Definition graph {path} document {name} definitions",
        )
        if not definitions:
            raise SchemaInventoryError(
                f"Definition graph {path} document {name} is empty"
            )
        documents[name] = MappingProxyType(dict(document))

    claimed_digest = payload.get("inventory_sha256")
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256", None)
    actual_digest = _canonical_sha256(unsigned)
    if (
        not isinstance(claimed_digest, str)
        or not hmac.compare_digest(claimed_digest, actual_digest)
    ):
        raise SchemaInventoryError(
            f"Definition graph {path} inventory digest does not match its content"
        )
    return DefinitionGraph(
        contract=DEFINITION_GRAPH_CONTRACT,
        version=version,
        wwise_build=build,
        source_file_names=tuple(source_file_names),
        documents=MappingProxyType(documents),
        inventory_sha256=claimed_digest,
    )


def validate_packaged_typed_request_surface(
    *,
    root: Path = DEFAULT_MANIFEST_ROOT,
) -> dict[str, Any]:
    """Validate and return the immutable 824-lane typed surface contract."""

    selected_root = Path(root)
    path = selected_root / TYPED_REQUEST_SURFACE_FILENAME
    payload = _read_json_object(path)
    if payload.get("contract") != TYPED_REQUEST_SURFACE_CONTRACT:
        raise SchemaInventoryError(
            f"Typed request surface {path} has an unsupported contract"
        )
    if payload.get("versions") != list(SUPPORTED_WWISE_VERSION_KEYS):
        raise SchemaInventoryError(
            f"Typed request surface {path} does not bind the supported versions"
        )
    claimed_digest = payload.get("inventory_sha256")
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256", None)
    actual_digest = _canonical_sha256(unsigned)
    if (
        not isinstance(claimed_digest, str)
        or not hmac.compare_digest(claimed_digest, actual_digest)
    ):
        raise SchemaInventoryError(
            f"Typed request surface {path} inventory digest does not match its content"
        )

    expected = build_typed_request_surface(root=selected_root)
    if expected["unresolved_references"]:
        raise SchemaInventoryError(
            f"Typed request surface {path} has unresolved same-version references"
        )
    if expected["unknown_schema_keywords"]:
        raise SchemaInventoryError(
            f"Typed request surface {path} has unknown schema keywords"
        )
    if payload != expected:
        raise SchemaInventoryError(
            f"Typed request surface {path} does not match the packaged schemas and policies"
        )
    return payload


def build_typed_request_surface(
    *,
    root: Path = DEFAULT_MANIFEST_ROOT,
) -> dict[str, Any]:
    """Build the deterministic maximum-profile surface from packaged truth."""

    selected_root = Path(root)
    catalog = CapabilityCatalog(manifest_root=selected_root)
    policy = load_native_surface_policy()
    blocked_by_lane = _blocked_field_counts(policy)
    rows: list[dict[str, Any]] = []
    unresolved_references: list[dict[str, str]] = []
    unknown_keywords: list[dict[str, str]] = []
    unique_functions: set[str] = set()
    unique_topics: set[str] = set()
    function_lanes = 0
    topic_lanes = 0

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        graph = load_definition_graph(version, root=selected_root)
        for document_name, document in graph.documents.items():
            for definition_name, definition in _require_mapping(
                document.get("definitions"),
                context=f"{version}/{document_name} definitions",
            ).items():
                if not isinstance(definition_name, str) or not isinstance(
                    definition, Mapping
                ):
                    raise SchemaInventoryError(
                        f"{version}/{document_name} has a malformed definition"
                    )
                for node_path, node in _walk_schema_nodes(
                    definition,
                    path=(
                        f"/definitions/{_encode_pointer_token(definition_name)}"
                    ),
                ):
                    for keyword in node:
                        if (
                            keyword not in KNOWN_SCHEMA_KEYWORDS
                            and not _is_legacy_implicit_property(node, keyword)
                        ):
                            unknown_keywords.append(
                                {
                                    "version": version,
                                    "uri": f"<definitions:{document_name}>",
                                    "section": "definitions",
                                    "pointer": node_path,
                                    "keyword": keyword,
                                }
                            )
                    for reference_keyword in ("$ref", "#ref"):
                        reference = node.get(reference_keyword)
                        if not isinstance(reference, str):
                            continue
                        try:
                            resolve_schema_reference(
                                reference,
                                root_schema=document,
                                graph=graph,
                            )
                        except SchemaInventoryError as exc:
                            unresolved_references.append(
                                {
                                    "version": version,
                                    "uri": f"<definitions:{document_name}>",
                                    "section": "definitions",
                                    "pointer": node_path,
                                    "reference": reference,
                                    "error": str(exc),
                                }
                            )
        for capability in catalog.entries_for_profile(
            version,
            profile=AUTHORING_UI_EXECUTION_PROFILE,
        ):
            if capability.item_type == "function":
                function_lanes += 1
                unique_functions.add(capability.uri)
            elif capability.item_type == "topic":
                topic_lanes += 1
                unique_topics.add(capability.uri)
            else:
                raise SchemaInventoryError(
                    f"Unsupported reflected item type: {capability.item_type!r}"
                )

            schema = capability.schema
            schema_keywords: set[str] = set()
            reference_count = 0
            for section_name, section in _schema_sections(schema):
                for node_path, node in _walk_schema_nodes(
                    section,
                    path=f"/{section_name}",
                ):
                    schema_keywords.update(node)
                    for keyword in node:
                        if (
                            keyword not in KNOWN_SCHEMA_KEYWORDS
                            and not _is_legacy_implicit_property(node, keyword)
                        ):
                            unknown_keywords.append(
                                {
                                    "version": version,
                                    "uri": capability.uri,
                                    "section": section_name,
                                    "pointer": node_path,
                                    "keyword": keyword,
                                }
                            )
                    for reference_keyword in ("$ref", "#ref"):
                        reference = node.get(reference_keyword)
                        if not isinstance(reference, str):
                            continue
                        reference_count += 1
                        try:
                            resolve_schema_reference(
                                reference,
                                root_schema=section,
                                graph=graph,
                            )
                        except SchemaInventoryError as exc:
                            unresolved_references.append(
                                {
                                    "version": version,
                                    "uri": capability.uri,
                                    "section": section_name,
                                    "pointer": node_path,
                                    "reference": reference,
                                    "error": str(exc),
                                }
                            )

            row = {
                "version": version,
                "uri": capability.uri,
                "item_type": capability.item_type,
                "correct_host": capability.host_surface
                or "wwise-console",
                "execution_policy": {
                    "route": capability.execution_contract["route"],
                    "effect": capability.execution_contract["effect"],
                    "executable": capability.execution_contract["executable"],
                    "verification_strategy": capability.execution_contract[
                        "verification_strategy"
                    ],
                },
                "schema_sha256": _canonical_sha256(schema),
                "definition_graph_sha256": graph.inventory_sha256,
                "schema_keywords": sorted(schema_keywords),
                "reference_count": reference_count,
                "intentionally_blocked_field_occurrences": blocked_by_lane.get(
                    (version, capability.host_surface or "wwise-console", capability.uri),
                    0,
                ),
            }
            rows.append(row)

    rows.sort(key=lambda row: (row["version"], row["item_type"], row["uri"]))
    unsigned: dict[str, Any] = {
        "contract": TYPED_REQUEST_SURFACE_CONTRACT,
        "versions": list(SUPPORTED_WWISE_VERSION_KEYS),
        "totals": {
            "function_lanes": function_lanes,
            "topic_lanes": topic_lanes,
            "total_lanes": len(rows),
            "unique_function_uris": len(unique_functions),
            "unique_topic_uris": len(unique_topics),
        },
        "intentionally_blocked_field_occurrences": sum(
            row["intentionally_blocked_field_occurrences"] for row in rows
        ),
        "unresolved_references": sorted(
            unresolved_references,
            key=lambda item: (
                item["version"],
                item["uri"],
                item["section"],
                item["pointer"],
                item["reference"],
            ),
        ),
        "unknown_schema_keywords": sorted(
            unknown_keywords,
            key=lambda item: (
                item["version"],
                item["uri"],
                item["section"],
                item["pointer"],
                item["keyword"],
            ),
        ),
        "lanes": rows,
    }
    return {**unsigned, "inventory_sha256": _canonical_sha256(unsigned)}


def resolve_schema_reference(
    reference: str,
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> ResolvedSchemaReference:
    """Resolve one local, global, external, or legacy same-document reference."""

    if not reference:
        raise SchemaInventoryError("Schema reference must not be empty")
    if reference == "#":
        return ResolvedSchemaReference(
            reference=reference,
            document_name="<schema>",
            pointer="",
            target=root_schema,
        )
    if reference.startswith("#/"):
        target = _resolve_pointer(root_schema, reference[1:])
        if target is not None:
            return ResolvedSchemaReference(
                reference=reference,
                document_name="<schema>",
                pointer=reference[1:],
                target=target,
            )
        target = _resolve_pointer(
            _default_definition_document(graph),
            reference[1:],
        )
        if target is not None:
            return ResolvedSchemaReference(
                reference=reference,
                document_name=_default_definition_document_name(graph),
                pointer=reference[1:],
                target=target,
            )
        raise SchemaInventoryError(
            f"Unresolved same-version schema reference {reference!r}"
        )
    if ".json#" in reference:
        document_name, fragment = reference.split("#", 1)
        try:
            document = graph.documents[document_name]
        except KeyError as exc:
            raise SchemaInventoryError(
                f"Unpackaged same-version definition document {document_name!r}"
            ) from exc
        target = _resolve_pointer(document, fragment)
        if target is None:
            raise SchemaInventoryError(
                f"Unresolved same-version schema reference {reference!r}"
            )
        return ResolvedSchemaReference(
            reference=reference,
            document_name=document_name,
            pointer=fragment,
            target=target,
        )

    for node_path, node in _walk_schema_nodes(root_schema, path=""):
        if node.get("id") == reference:
            return ResolvedSchemaReference(
                reference=reference,
                document_name="<schema>",
                pointer=node_path,
                target=node,
            )
    raise SchemaInventoryError(
        f"Unresolved legacy same-document schema reference {reference!r}"
    )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schema_sections(
    schema: Mapping[str, Any],
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for name in SCHEMA_SECTIONS:
        section = schema.get(name)
        if isinstance(section, Mapping):
            yield name, section


def _walk_schema_nodes(
    schema: Mapping[str, Any],
    *,
    path: str,
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    yield path, schema
    for keyword in SCHEMA_CHILD_MAP_KEYWORDS:
        children = schema.get(keyword)
        if not isinstance(children, Mapping):
            continue
        for raw_name, raw_child in children.items():
            if isinstance(raw_name, str) and isinstance(raw_child, Mapping):
                yield from _walk_schema_nodes(
                    raw_child,
                    path=f"{path}/{keyword}/{_encode_pointer_token(raw_name)}",
                )
    for keyword in SCHEMA_CHILD_LIST_KEYWORDS:
        children = schema.get(keyword)
        if not isinstance(children, list):
            continue
        for index, raw_child in enumerate(children):
            if isinstance(raw_child, Mapping):
                yield from _walk_schema_nodes(
                    raw_child,
                    path=f"{path}/{keyword}/{index}",
                )
    for keyword in SCHEMA_CHILD_SCHEMA_KEYWORDS:
        child = schema.get(keyword)
        if isinstance(child, Mapping):
            yield from _walk_schema_nodes(
                child,
                path=f"{path}/{keyword}",
            )
    for keyword, child in schema.items():
        if _is_legacy_implicit_property(schema, keyword):
            yield from _walk_schema_nodes(
                child,
                path=f"{path}/<legacy-properties>/{_encode_pointer_token(keyword)}",
            )


def _resolve_pointer(
    document: Mapping[str, Any],
    pointer: str,
) -> Mapping[str, Any] | None:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return None
    current: Any = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isascii() and token.isdigit():
            index = int(token)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current if isinstance(current, Mapping) else None


def _default_definition_document_name(graph: DefinitionGraph) -> str:
    if "waapi_definitions.json" in graph.documents:
        return "waapi_definitions.json"
    if len(graph.documents) == 1:
        return next(iter(graph.documents))
    raise SchemaInventoryError(
        f"Definition graph {graph.version} lacks a default WAAPI document"
    )


def _default_definition_document(
    graph: DefinitionGraph,
) -> Mapping[str, Any]:
    return graph.documents[_default_definition_document_name(graph)]


def _blocked_field_counts(
    policy: Mapping[str, Any],
) -> dict[tuple[str, str, str], int]:
    rows: dict[tuple[str, str, str], int] = {}
    raw_rules = policy.get("rules")
    if not isinstance(raw_rules, list):
        raise SchemaInventoryError("Native surface policy lacks rules")
    for raw_rule in raw_rules:
        rule = _require_mapping(raw_rule, context="native surface policy rule")
        uri = rule.get("uri")
        profile = rule.get("profile")
        versions = rule.get("versions")
        scopes = rule.get("scopes")
        if (
            not isinstance(uri, str)
            or not isinstance(profile, str)
            or not isinstance(versions, list)
            or not all(isinstance(version, str) for version in versions)
            or not isinstance(scopes, list)
        ):
            raise SchemaInventoryError("Native surface policy rule is malformed")
        count = 0
        for raw_scope in scopes:
            scope = _require_mapping(
                raw_scope,
                context="native surface policy scope",
            )
            classifications = _require_mapping(
                scope.get("classifications"),
                context="native surface policy classifications",
            )
            blocked = classifications.get("intentionally_blocked", [])
            if not isinstance(blocked, list) or not all(
                isinstance(value, str) for value in blocked
            ):
                raise SchemaInventoryError(
                    "Native surface intentionally_blocked values must be strings"
                )
            count += len(blocked)
        for version in versions:
            key = (version, profile, uri)
            if key in rows:
                raise SchemaInventoryError(
                    f"Duplicate native surface policy row: {key!r}"
                )
            rows[key] = count
    return rows


def _encode_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _is_legacy_implicit_property(
    schema: Mapping[str, Any],
    keyword: str,
) -> bool:
    """Recognize old Wwise result rows that omitted the properties wrapper."""

    return (
        schema.get("type") == "object"
        and keyword in LEGACY_2021_IMPLICIT_PROPERTY_NAMES
        and isinstance(schema.get(keyword), Mapping)
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaInventoryError(
            f"Could not read packaged schema inventory {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SchemaInventoryError(
            f"Packaged schema inventory {path} must be a JSON object"
        )
    return payload


def _require_mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaInventoryError(f"{context} must be an object")
    return value


__all__ = [
    "DEFINITION_GRAPH_CONTRACT",
    "TYPED_REQUEST_SURFACE_CONTRACT",
    "DefinitionGraph",
    "ResolvedSchemaReference",
    "SchemaInventoryError",
    "build_typed_request_surface",
    "load_definition_graph",
    "resolve_schema_reference",
    "validate_packaged_typed_request_surface",
]

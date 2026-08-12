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
LEGACY_2021_SOUNDBANK_IMPLICIT_PROPERTY_PATHS = frozenset(
    {
        "/publishSchema/properties/bankInfo/items/ExcludedMemoryFiles",
        "/publishSchema/properties/bankInfo/items/GameParameters",
        "/publishSchema/properties/bankInfo/items/IncludedAuxBusses",
        "/publishSchema/properties/bankInfo/items/IncludedMemoryFiles",
        "/publishSchema/properties/bankInfo/items/ReferencedStreamedFiles",
        "/publishSchema/properties/bankInfo/items/StateGroups",
        "/publishSchema/properties/bankInfo/items/SwitchGroups",
        "/publishSchema/properties/bankInfo/items/Triggers",
        "/publishSchema/properties/bankInfo/items/properties/IncludedEvents/items/IncludedMemoryFiles",
        "/publishSchema/properties/bankInfo/items/properties/IncludedEvents/items/SwitchContainers",
        "/publishSchema/properties/bankInfo/items/properties/IncludedEvents/items/properties/ExcludedMemoryFiles",
        "/publishSchema/properties/bankInfo/items/properties/IncludedEvents/items/properties/ReferencedStreamedFiles",
    }
)
LEGACY_2025_STRUCTURE_CHANGED_STRING_FALSE_PATHS = frozenset(
    {
        "/publishSchema/properties/objects/items/additionalProperties",
        "/publishSchema/properties/objects/items/properties/changes/items/additionalProperties",
        "/publishSchema/properties/objects/items/properties/changes/items/properties/nameChange/additionalProperties",
        "/publishSchema/properties/objects/items/properties/changes/items/properties/notesChange/additionalProperties",
        "/publishSchema/properties/objects/items/properties/changes/items/properties/ownerChange/additionalProperties",
        "/publishSchema/properties/objects/items/properties/changes/items/properties/parentChange/additionalProperties",
    }
)
SCHEMA_ENVELOPE_KEYWORDS = frozenset((*SCHEMA_SECTIONS, "description"))


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
    blocked_by_lane = _blocked_fields_by_lane(policy)
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
                            and not _is_legacy_implicit_property(
                                node,
                                keyword,
                                node_path=node_path,
                                allowed_paths=frozenset(),
                            )
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
                        if reference_keyword not in node:
                            continue
                        reference = node[reference_keyword]
                        if not isinstance(reference, str) or not reference:
                            raise SchemaInventoryError(
                                f"Schema reference at {node_path} must be a non-empty string"
                            )
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
            unknown_keywords.extend(
                validate_schema_envelope(
                    schema,
                    version=version,
                    uri=capability.uri,
                )
            )
            schema_keywords: set[str] = set()
            reference_count = 0
            legacy_implicit_paths = (
                LEGACY_2021_SOUNDBANK_IMPLICIT_PROPERTY_PATHS
                if version == "2021.1"
                and capability.item_type == "topic"
                and capability.uri == "ak.wwise.core.soundbank.generated"
                else frozenset()
            )
            legacy_string_false_paths = (
                LEGACY_2025_STRUCTURE_CHANGED_STRING_FALSE_PATHS
                if version == "2025.1"
                and capability.item_type == "topic"
                and capability.uri == "ak.wwise.core.object.structureChanged"
                else frozenset()
            )
            for section_name, section in _schema_sections(schema):
                for node_path, node in _walk_schema_nodes(
                    section,
                    path=f"/{section_name}",
                    legacy_implicit_paths=legacy_implicit_paths,
                    legacy_string_false_paths=legacy_string_false_paths,
                ):
                    schema_keywords.update(node)
                    for keyword in node:
                        if (
                            keyword not in KNOWN_SCHEMA_KEYWORDS
                            and not _is_legacy_implicit_property(
                                node,
                                keyword,
                                node_path=node_path,
                                allowed_paths=legacy_implicit_paths,
                            )
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
                        if reference_keyword not in node:
                            continue
                        reference = node[reference_keyword]
                        if not isinstance(reference, str) or not reference:
                            raise SchemaInventoryError(
                                f"Schema reference at {node_path} must be a non-empty string"
                            )
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
                "execution_policy": dict(capability.execution_contract),
                "execution_policy_sha256": _canonical_sha256(
                    capability.execution_contract
                ),
                "schema_sha256": _canonical_sha256(schema),
                "construction_shape": (
                    _function_construction_shape(
                        schema,
                        graph=graph,
                        execution_policy=capability.execution_contract,
                    )
                    if capability.item_type == "function"
                    else "topic"
                ),
                "definition_graph_sha256": graph.inventory_sha256,
                "schema_keywords": sorted(schema_keywords),
                "reference_count": reference_count,
                "intentionally_blocked_fields": list(
                    blocked_by_lane.get(
                        (
                            version,
                            capability.host_surface or "wwise-console",
                            capability.uri,
                        ),
                        (),
                    )
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
            len(row["intentionally_blocked_fields"]) for row in rows
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


def _function_construction_shape(
    schema: Mapping[str, Any],
    *,
    graph: DefinitionGraph,
    execution_policy: Mapping[str, Any],
) -> str:
    """Classify exact reflected request structure without a URI allowlist."""

    if execution_policy.get("route") == "compound_transaction_member":
        return "draft"

    for section_name in ("argsSchema", "optionsSchema"):
        section = schema.get(section_name)
        if not isinstance(section, Mapping):
            raise SchemaInventoryError(
                f"Function {section_name} must be an object for construction classification"
            )
        if _schema_accepts_business_input(
            section,
            root_schema=section,
            graph=graph,
            active_references=frozenset(),
        ):
            return "typed"
    return "zero"


def _schema_accepts_business_input(
    section: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    active_references: frozenset[str],
) -> bool:
    reference = section.get("$ref", section.get("#ref"))
    if isinstance(reference, str):
        if reference in active_references:
            return False
        resolved = resolve_schema_reference(
            reference,
            root_schema=root_schema,
            graph=graph,
        )
        return _schema_accepts_business_input(
            resolved.target,
            root_schema=root_schema,
            graph=graph,
            active_references=active_references | {reference},
        )
    branches = section.get("oneOf", section.get("anyOf"))
    if isinstance(branches, list):
        return any(
            isinstance(branch, Mapping)
            and _schema_accepts_business_input(
                branch,
                root_schema=root_schema,
                graph=graph,
                active_references=active_references,
            )
            for branch in branches
        )
    properties = section.get("properties", {})
    required = section.get("required", [])
    patterns = section.get("patternProperties", {})
    additional = section.get("additionalProperties", False)
    if (
        not isinstance(properties, Mapping)
        or not isinstance(required, list)
        or not isinstance(patterns, Mapping)
    ):
        raise SchemaInventoryError(
            "Function request schema is malformed for construction classification"
        )
    return bool(properties or required or patterns or additional is not False)


def validate_schema_envelope(
    schema: Mapping[str, Any],
    *,
    version: str,
    uri: str,
) -> list[dict[str, str]]:
    """Validate the reflected lane envelope and report unknown top-level keys."""

    unknown: list[dict[str, str]] = []
    for keyword, value in schema.items():
        if keyword not in SCHEMA_ENVELOPE_KEYWORDS:
            unknown.append(
                {
                    "version": version,
                    "uri": uri,
                    "section": "<envelope>",
                    "pointer": "/",
                    "keyword": keyword,
                }
            )
        elif keyword == "description" and not isinstance(value, str):
            raise SchemaInventoryError(
                f"Schema description for {uri} must be a string"
            )
        elif keyword != "description" and not isinstance(value, Mapping):
            raise SchemaInventoryError(
                f"Schema section {keyword} for {uri} must be an object"
            )
    return unknown


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

    legacy_target = _find_legacy_schema_id(root_schema, reference)
    if legacy_target is not None:
        node_path, node = legacy_target
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
        if name not in schema:
            continue
        section = schema[name]
        if not isinstance(section, Mapping):
            raise SchemaInventoryError(f"Schema section {name} must be an object")
        yield name, section


def _walk_schema_nodes(
    schema: Mapping[str, Any],
    *,
    path: str,
    legacy_implicit_paths: frozenset[str] = frozenset(),
    legacy_string_false_paths: frozenset[str] = frozenset(),
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    yield path, schema
    for keyword in SCHEMA_CHILD_MAP_KEYWORDS:
        if keyword not in schema:
            continue
        children = schema[keyword]
        if not isinstance(children, Mapping):
            raise SchemaInventoryError(
                f"Schema keyword {keyword} at {path or '/'} must be an object"
            )
        for raw_name, raw_child in children.items():
            if not isinstance(raw_name, str) or not isinstance(raw_child, Mapping):
                raise SchemaInventoryError(
                    f"Schema keyword {keyword} at {path or '/'} has a malformed child"
                )
            yield from _walk_schema_nodes(
                raw_child,
                path=f"{path}/{keyword}/{_encode_pointer_token(raw_name)}",
                legacy_implicit_paths=legacy_implicit_paths,
                legacy_string_false_paths=legacy_string_false_paths,
            )
    for keyword in SCHEMA_CHILD_LIST_KEYWORDS:
        if keyword not in schema:
            continue
        children = schema[keyword]
        if not isinstance(children, list):
            raise SchemaInventoryError(
                f"Schema keyword {keyword} at {path or '/'} must be an array"
            )
        for index, raw_child in enumerate(children):
            if not isinstance(raw_child, Mapping):
                raise SchemaInventoryError(
                    f"Schema keyword {keyword} at {path or '/'} has a malformed child"
                )
            yield from _walk_schema_nodes(
                raw_child,
                path=f"{path}/{keyword}/{index}",
                legacy_implicit_paths=legacy_implicit_paths,
                legacy_string_false_paths=legacy_string_false_paths,
            )
    for keyword in SCHEMA_CHILD_SCHEMA_KEYWORDS:
        if keyword not in schema:
            continue
        child = schema[keyword]
        if keyword == "additionalProperties" and isinstance(child, bool):
            continue
        if (
            keyword == "additionalProperties"
            and child == "false"
            and f"{path}/additionalProperties" in legacy_string_false_paths
        ):
            continue
        if keyword == "items" and isinstance(child, list):
            if not child or not all(isinstance(item, Mapping) for item in child):
                raise SchemaInventoryError(
                    f"Schema keyword items at {path or '/'} has a malformed child"
                )
            for index, item in enumerate(child):
                yield from _walk_schema_nodes(
                    item,
                    path=f"{path}/items/{index}",
                    legacy_implicit_paths=legacy_implicit_paths,
                    legacy_string_false_paths=legacy_string_false_paths,
                )
            continue
        if not isinstance(child, Mapping):
            raise SchemaInventoryError(
                f"Schema keyword {keyword} at {path or '/'} must be an object"
            )
        yield from _walk_schema_nodes(
            child,
            path=f"{path}/{keyword}",
            legacy_implicit_paths=legacy_implicit_paths,
            legacy_string_false_paths=legacy_string_false_paths,
        )
    for keyword, child in schema.items():
        if _is_legacy_implicit_property(
            schema,
            keyword,
            node_path=path,
            allowed_paths=legacy_implicit_paths,
        ):
            yield from _walk_schema_nodes(
                child,
                path=f"{path}/<legacy-properties>/{_encode_pointer_token(keyword)}",
                legacy_implicit_paths=legacy_implicit_paths,
                legacy_string_false_paths=legacy_string_false_paths,
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


def _find_legacy_schema_id(
    value: Any,
    reference: str,
    *,
    path: str = "",
) -> tuple[str, Mapping[str, Any]] | None:
    """Find an old same-document ``id`` without interpreting its container shape."""

    if isinstance(value, Mapping):
        if value.get("id") == reference:
            return path, value
        for keyword, child in value.items():
            found = _find_legacy_schema_id(
                child,
                reference,
                path=f"{path}/{_encode_pointer_token(str(keyword))}",
            )
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_legacy_schema_id(
                child,
                reference,
                path=f"{path}/{index}",
            )
            if found is not None:
                return found
    return None


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


def _blocked_fields_by_lane(
    policy: Mapping[str, Any],
) -> dict[tuple[str, str, str], tuple[dict[str, str], ...]]:
    rows: dict[tuple[str, str, str], tuple[dict[str, str], ...]] = {}
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
        blocked_fields: list[dict[str, str]] = []
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
            pointer = scope.get("pointer")
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                raise SchemaInventoryError(
                    "Native surface policy scope pointer must be absolute"
                )
            blocked_fields.extend(
                {"pointer": pointer, "field": field} for field in blocked
            )
        frozen_fields = tuple(
            sorted(
                blocked_fields,
                key=lambda item: (item["pointer"], item["field"]),
            )
        )
        for version in versions:
            key = (version, profile, uri)
            if key in rows:
                raise SchemaInventoryError(
                    f"Duplicate native surface policy row: {key!r}"
                )
            rows[key] = frozen_fields
    return rows


def _encode_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _is_legacy_implicit_property(
    schema: Mapping[str, Any],
    keyword: str,
    *,
    node_path: str,
    allowed_paths: frozenset[str],
) -> bool:
    """Recognize old Wwise result rows that omitted the properties wrapper."""

    return (
        schema.get("type") == "object"
        and f"{node_path}/{_encode_pointer_token(keyword)}" in allowed_paths
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
    "validate_schema_envelope",
    "validate_packaged_typed_request_surface",
]

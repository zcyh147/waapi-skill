"""Gateway-owned typed construction for reflected Topic inputs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .capabilities import CapabilityCatalog, CapabilityNotFoundError
from .canonical import canonical_sha256
from .schema_inventory import DefinitionGraph, load_definition_graph
from .typed_requests import (
    MaterializedTypedRequest,
    TypedRequestContract,
    TypedRequestFact,
    compile_typed_request_contract,
    materialize_typed_request,
)
from .versions import SUPPORTED_WWISE_VERSION_KEYS


TOPIC_OPTIONS_OPERATION_PREFIX = "topic.options:"
TOPIC_MATCH_OPERATION_PREFIX = "topic.match:"


class TypedTopicError(ValueError):
    """A reflected Topic input cannot be constructed safely."""


@dataclass(frozen=True, slots=True)
class MaterializedTypedTopicInputs:
    """Typed subscribe options and typed event-subset predicate."""

    version: str
    topic: str
    options_schema_digest: str
    match_schema_digest: str
    options: Mapping[str, Any]
    match: Mapping[str, Any]
    option_request: MaterializedTypedRequest
    match_request: MaterializedTypedRequest


def _topic_schema(version: str, topic: str) -> Mapping[str, Any]:
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise TypedTopicError(f"Unsupported Wwise version {version!r}")
    catalog = CapabilityCatalog()
    try:
        capability = catalog.describe(version, topic)
    except CapabilityNotFoundError:
        try:
            capability = catalog.authoring_ui_describe(version, topic)
        except CapabilityNotFoundError as exc:
            raise TypedTopicError(str(exc)) from exc
    if capability.item_type != "topic":
        raise TypedTopicError(f"Typed Topic construction requires a Topic URI: {topic}")
    return capability.schema


def topic_options_contract(version: str, topic: str) -> TypedRequestContract:
    """Compile one exact reflected options schema into typed facts."""

    schema = _topic_schema(version, topic)
    options = schema.get("optionsSchema")
    if not isinstance(options, Mapping):
        raise TypedTopicError(f"Topic {topic!r} has no reflected options schema")
    return compile_typed_request_contract(
        version=version,
        uri=f"{TOPIC_OPTIONS_OPERATION_PREFIX}{topic}",
        schema={
            "argsSchema": _empty_object_schema(),
            "optionsSchema": options,
        },
        graph=load_definition_graph(version),
    )


def topic_match_contract(version: str, topic: str) -> TypedRequestContract:
    """Compile an optional recursive subset predicate from the publish schema."""

    schema = _topic_schema(version, topic)
    publish = schema.get("publishSchema")
    if not isinstance(publish, Mapping):
        raise TypedTopicError(f"Topic {topic!r} has no reflected publish schema")
    return compile_typed_request_contract(
        version=version,
        uri=f"{TOPIC_MATCH_OPERATION_PREFIX}{topic}",
        schema={
            "argsSchema": _optional_match_schema(publish),
            "optionsSchema": _empty_object_schema(),
        },
        graph=_optional_match_definition_graph(version),
    )


def materialize_typed_topic_inputs(
    *,
    version: str,
    topic: str,
    options_schema_digest: str,
    option_facts: Sequence[TypedRequestFact],
    match_schema_digest: str,
    match_facts: Sequence[TypedRequestFact],
) -> MaterializedTypedTopicInputs:
    """Materialize both Topic surfaces without changing subscription behavior."""

    options_contract = topic_options_contract(version, topic)
    match_contract = topic_match_contract(version, topic)
    option_request = materialize_typed_request(
        options_contract,
        schema_digest=options_schema_digest,
        facts=option_facts,
    )
    match_request = materialize_typed_request(
        match_contract,
        schema_digest=match_schema_digest,
        facts=match_facts,
    )
    if option_request.args or match_request.options:
        raise TypedTopicError("Typed Topic section ownership is malformed")
    return MaterializedTypedTopicInputs(
        version=version,
        topic=topic,
        options_schema_digest=options_contract.schema_digest,
        match_schema_digest=match_contract.schema_digest,
        options=dict(option_request.options),
        match=dict(match_request.args),
        option_request=option_request,
        match_request=match_request,
    )


def _empty_object_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": {}}


def _optional_match_schema(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {
            key: _optional_match_schema(item)
            for key, item in value.items()
            if key != "required"
        }
        if result.get("type") == "object" and "additionalProperties" not in result:
            # Reflected publish objects that omit the keyword use JSON Schema's
            # open-object default. Preserve that exact meaning for match facts.
            result["additionalProperties"] = True
        return result
    if isinstance(value, list):
        return [_optional_match_schema(item) for item in value]
    return deepcopy(value)


def _optional_match_definition_graph(version: str) -> DefinitionGraph:
    """Remove nested publish requirements while retaining exact version data."""

    graph = load_definition_graph(version)
    projected_documents = {
        name: _optional_match_schema(document)
        for name, document in graph.documents.items()
    }
    documents = {
        name: MappingProxyType(document)
        for name, document in projected_documents.items()
    }
    return DefinitionGraph(
        contract=graph.contract,
        version=graph.version,
        wwise_build=graph.wwise_build,
        source_file_names=graph.source_file_names,
        documents=MappingProxyType(documents),
        inventory_sha256=canonical_sha256(
            {
                "source_inventory_sha256": graph.inventory_sha256,
                "projection": "optional-topic-match/v1",
                "documents": projected_documents,
            }
        ),
    )


__all__ = [
    "MaterializedTypedTopicInputs",
    "TOPIC_MATCH_OPERATION_PREFIX",
    "TOPIC_OPTIONS_OPERATION_PREFIX",
    "TypedTopicError",
    "materialize_typed_topic_inputs",
    "topic_match_contract",
    "topic_options_contract",
]

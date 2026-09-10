"""Gateway-owned typed construction for the established object-query builders."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .builders.common import SemanticPreview
from .builders.query import (
    ADVANCED_QUERY_CONTRACT,
    STRUCTURED_QUERY_CONTRACT,
    advanced_query_schema,
    build_advanced_object_get_query,
    build_structured_object_get_query,
    structured_query_schema,
)
from .schema_inventory import load_definition_graph
from .typed_requests import (
    MaterializedTypedRequest,
    TypedRequestContract,
    TypedRequestFact,
    compile_typed_request_contract,
    materialize_typed_request,
)
from .versions import SUPPORTED_WWISE_VERSION_KEYS


STRUCTURED_TYPED_QUERY_OPERATION = "query.object.structured"
ADVANCED_TYPED_QUERY_OPERATION = "query.object.advanced"


class TypedQueryError(ValueError):
    """A typed query cannot be disclosed or materialized safely."""


@dataclass(frozen=True, slots=True)
class MaterializedTypedQuery:
    """One typed document after authoritative Builder revalidation."""

    operation: str
    version: str
    schema_digest: str
    document: Mapping[str, Any]
    typed_request: MaterializedTypedRequest
    preview: SemanticPreview


def _query_schema_envelope(version: str, *, advanced: bool) -> dict[str, Any]:
    document_schema = deepcopy(
        advanced_query_schema(version=version)
        if advanced
        else structured_query_schema(version=version)
    )
    properties = document_schema.get("properties")
    required = document_schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise TypedQueryError("Packaged query schema is malformed")
    contract_schema = properties.pop("contract", None)
    expected_contract = (
        ADVANCED_QUERY_CONTRACT if advanced else STRUCTURED_QUERY_CONTRACT
    )
    if contract_schema != {"const": expected_contract} or "contract" not in required:
        raise TypedQueryError("Packaged query contract ownership is malformed")
    required.remove("contract")
    return {
        "argsSchema": document_schema,
        "optionsSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    }


def typed_query_contract(version: str, *, advanced: bool = False) -> TypedRequestContract:
    """Compile one exact-version query document into shared typed facts."""

    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise TypedQueryError(f"Unsupported Wwise version {version!r}")
    operation = (
        ADVANCED_TYPED_QUERY_OPERATION if advanced else STRUCTURED_TYPED_QUERY_OPERATION
    )
    return compile_typed_request_contract(
        version=version,
        uri=operation,
        schema=_query_schema_envelope(version, advanced=advanced),
        graph=load_definition_graph(version),
    )


def typed_query_schema_payload(version: str, *, advanced: bool = False) -> dict[str, Any]:
    """Return the single model-facing continuation for one query layer."""

    contract = typed_query_contract(version, advanced=advanced)
    payload = contract.as_gateway_payload()
    payload["command"] = "query-schema"
    payload["query_layer"] = (
        "advanced-native-waql" if advanced else "structured-builder"
    )
    payload["query_contract"] = (
        ADVANCED_QUERY_CONTRACT if advanced else STRUCTURED_QUERY_CONTRACT
    )
    payload["input_shape"] = "inline"
    payload["routing"] = {
        "preferred": "query-object simple flags",
        "use_this_layer_when": (
            "the structured Builder cannot express the read"
            if advanced
            else "simple query-object flags cannot express the read"
        ),
    }
    if advanced:
        payload["continuation"] = {
            "subcommand": "query-object",
            "query_layer": "advanced-native-waql",
            "typed_marker": "--typed-advanced",
            "schema_binding": "--schema-digest <schema_digest>",
            "typed_scalars": {
                "waql": "--waql <one bounded exact WAQL expression>",
                "return": "--advanced-return <expression> (repeat 1..64)",
                "max_results": "--max-results <1..1000>",
            },
        }
    else:
        payload["continuation"] = {
            "subcommand": "query-object",
            "query_layer": "structured-builder",
            "schema_binding": "--typed-schema-digest <schema_digest>",
            "fact_flags": {
                "scalar": "--typed-set <field_handle> <type> <value>",
                "array_item": "--typed-append <field_handle> <type> <value>",
                "container": "--typed-present <container_handle>",
                "branch": "--typed-choose <branch_handle> <choice_handle>",
                "dynamic_branch": (
                    "--typed-choose-dynamic <object_handle> <key> <choice_handle>"
                ),
                "map_put": (
                    "--typed-map-put <map_handle> <key> <type> <value>"
                ),
            },
            "execution": "dispatches the read directly after typed validation",
        }
    return payload


def materialize_typed_query(
    operation: str,
    version: str,
    schema_digest: str,
    facts: Sequence[TypedRequestFact],
) -> MaterializedTypedQuery:
    """Materialize typed facts and re-enter the authoritative query Builder."""

    if operation not in {
        STRUCTURED_TYPED_QUERY_OPERATION,
        ADVANCED_TYPED_QUERY_OPERATION,
    }:
        raise TypedQueryError(f"Unknown typed query operation {operation!r}")
    advanced = operation == ADVANCED_TYPED_QUERY_OPERATION
    contract = typed_query_contract(version, advanced=advanced)
    typed = materialize_typed_request(
        contract,
        schema_digest=schema_digest,
        facts=facts,
    )
    if typed.options:
        raise TypedQueryError("Typed query options must remain Gateway-owned")
    document = {
        "contract": ADVANCED_QUERY_CONTRACT if advanced else STRUCTURED_QUERY_CONTRACT,
        **dict(typed.args),
    }
    preview = (
        build_advanced_object_get_query(document, version=version)
        if advanced
        else build_structured_object_get_query(document, version=version)
    )
    return MaterializedTypedQuery(
        operation=operation,
        version=version,
        schema_digest=contract.schema_digest,
        document=document,
        typed_request=typed,
        preview=preview,
    )


__all__ = [
    "ADVANCED_TYPED_QUERY_OPERATION",
    "MaterializedTypedQuery",
    "STRUCTURED_TYPED_QUERY_OPERATION",
    "TypedQueryError",
    "materialize_typed_query",
    "typed_query_contract",
    "typed_query_schema_payload",
]

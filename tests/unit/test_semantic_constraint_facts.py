from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticErrorCode,
    SemanticValidationError,
)
from wwise_waapi.builders.schema import (  # pyright: ignore[reportMissingImports]
    SEMANTIC_CONSTRAINT_FACTS_SIZE_LIMIT,
    extract_semantic_constraint_facts,
)
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


def manifest_loader() -> ManifestSchemaLoader:
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "audit": {"schema_count": 2},
            "metadata": {"inventory_source": "unit-test"},
            "schemas": [
                {
                    "uri": "ak.wwise.core.object.get",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "from": {
                                    "oneOf": [
                                        {"required": ["id"]},
                                        {"required": ["name"]},
                                        {"required": ["path"]},
                                    ]
                                },
                                "waql": {"type": "string"},
                            },
                            "type": "object",
                        },
                        "optionsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "return": {"type": "array"},
                                "platform": {"type": "string"},
                                "language": {"type": "string"},
                            },
                            "type": "object",
                        },
                        "resultSchema": {
                            "properties": {"return": {"type": "array"}},
                            "type": "object",
                        },
                    },
                },
                {
                    "uri": "ak.wwise.core.object.delete",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {"properties": {"object": {"type": "string"}}, "required": ["object"]},
                        "optionsSchema": {"properties": {}},
                        "resultSchema": {"properties": {"deleted": {"type": "array"}}},
                    },
                },
            ],
        },
    )
    return ManifestSchemaLoader(store)


def test_object_get_constraint_facts_are_compact_and_uri_scoped() -> None:
    facts = extract_semantic_constraint_facts(
        "ak.wwise.core.object.get",
        BuilderFamily.QUERY,
        manifest_loader=manifest_loader(),
    )
    payload = facts.as_dict()

    assert payload["uri"] == "ak.wwise.core.object.get"
    assert payload["family"] == "query"
    assert payload["required_args"] == ["waql or legacy query expression"]
    assert payload["supported_args"] == ["from", "waql"]
    assert payload["supported_options"] == ["return", "platform", "language"]
    assert payload["identity_shape"] == ["waql", "from.id", "from.name", "from.path"]
    assert payload["property_hints"] == ["options.return selects returned object properties"]
    assert payload["result_fields"] == ["return"]
    assert "return array" in payload["result_shape"]
    assert payload["mutation_hints"] == [
        "read-only: Read-only. Query builders must not mutate Wwise state or dispatch automatically."
    ]
    assert [item["source"] for item in payload["provenance"]] == [
        "packaged-semantic-source-notes",
        "local-versioned-manifest",
        "targeted-uri-schema",
    ]
    assert payload["source_priority"] == [
        "packaged-semantic-source-notes",
        "local-versioned-manifest",
        "targeted-uri-schema",
        "official-docs-excluded-by-policy",
    ]


def test_constraint_facts_exclude_prompt_stuffing_sources() -> None:
    payload = extract_semantic_constraint_facts(
        "ak.wwise.core.object.get",
        "query",
        manifest_loader=manifest_loader(),
    ).as_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert len(encoded) <= SEMANTIC_CONSTRAINT_FACTS_SIZE_LIMIT
    assert '"schema"' not in encoded
    assert '"schemas"' not in encoded
    assert '"notes"' not in encoded
    assert '"official_urls"' not in encoded
    assert "audiokinetic.com" not in encoded
    assert "ak.wwise.core.object.delete" not in encoded
    assert "deleted" not in encoded
    assert "unit-test" not in encoded
    assert "resources/semantic/2022.1/source_notes.json" in encoded
    assert "resources/manifest/2022.1/schemas.json#ak.wwise.core.object.get" in encoded


def test_constraint_facts_reject_uri_outside_requested_family() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        extract_semantic_constraint_facts(
            "ak.wwise.core.object.get",
            BuilderFamily.OBJECT_MUTATION,
            manifest_loader=manifest_loader(),
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["family"] == "object-mutation"

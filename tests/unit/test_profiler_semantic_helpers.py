from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticErrorCode,
    SemanticValidationError,
    candidate_writable_child_container,
)
from wwise_waapi.builders.profiler import (  # pyright: ignore[reportMissingImports]
    PROFILER_PARAMETER_GUIDANCE_SIZE_LIMIT,
    extract_profiler_parameter_guidance,
)
from wwise_waapi.builders.schema import extract_semantic_constraint_facts  # pyright: ignore[reportMissingImports]
from wwise_waapi.deferred_registry import ApiClassifier, DeferredRegistry  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


VERSION = "2022.1"


def test_profiler_guidance_is_compact_and_shape_only() -> None:
    loader = manifest_loader()
    registry = deferred_registry()

    guidance = extract_profiler_parameter_guidance(
        "ak.wwise.core.profiler.startCapture",
        manifest_loader=loader,
        deferred_registry=registry,
    )
    payload = guidance.as_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["uri"] == "ak.wwise.core.profiler.startCapture"
    assert payload["family"] == "core.profiler"
    assert payload["parameter_shape"] == [
        "session: sessionId",
        "id: gameObject",
        "range: start, end",
        "output: return",
    ]
    assert payload["setup_hints"] == ["Profiler guidance is inventory-only."]
    assert payload["blocker_hints"] == [
        "Profiler behavior needs live session evidence.",
        "Registry lookup only; not behavioral coverage.",
    ]
    assert payload["source_priority"] == [
        "packaged-deferred-registry",
        "targeted-uri-schema",
        "official-docs-excluded-by-policy",
    ]
    assert len(encoded) <= PROFILER_PARAMETER_GUIDANCE_SIZE_LIMIT
    for token in ("workflow", "steps", "definitions", "argsSchema", "optionsSchema", "official_urls", "source_urls"):
        assert token not in encoded


def test_profiler_guidance_supports_log_like_and_capture_log_topics() -> None:
    guidance = extract_profiler_parameter_guidance(
        "ak.wwise.core.profiler.captureLog.itemAdded",
        manifest_loader=manifest_loader(),
        deferred_registry=deferred_registry(),
    ).as_dict()

    assert guidance["family"] == "core.profiler.captureLog"
    assert guidance["parameter_shape"] == [
        "session: sessionId",
        "id: itemId",
        "range: none",
        "output: none",
    ]
    assert guidance["setup_hints"] == [
        "Capture-log topics are inventory-only.",
        "setup: capture-log topic guidance stays inventory-only.",
    ]


def test_profiler_guidance_does_not_affect_read_only_or_compound_helpers() -> None:
    query_loader = query_manifest_loader()
    baseline = extract_semantic_constraint_facts(
        "ak.wwise.core.object.get",
        BuilderFamily.QUERY,
        manifest_loader=query_loader,
    ).as_dict()
    compound_before = candidate_writable_child_container("\\Actor-Mixer Hierarchy")

    extract_profiler_parameter_guidance(
        "ak.wwise.core.log.get",
        manifest_loader=manifest_loader(),
        deferred_registry=deferred_registry(),
    )

    assert extract_semantic_constraint_facts(
        "ak.wwise.core.object.get",
        BuilderFamily.QUERY,
        manifest_loader=query_loader,
    ).as_dict() == baseline
    assert candidate_writable_child_container("\\Actor-Mixer Hierarchy") == compound_before


def test_profiler_guidance_rejects_non_profiler_namespace() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        extract_profiler_parameter_guidance(
            "ak.soundengine.postEvent",
            manifest_loader=manifest_loader(),
            deferred_registry=deferred_registry(),
        )

    assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY


def manifest_loader() -> ManifestSchemaLoader:
    store = ManifestStore()
    store.record(
        VERSION,
        {
            "schemas": [
                {
                    "uri": "ak.wwise.core.object.get",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "from": {"type": "object"},
                                "waql": {"type": "string"},
                            },
                            "type": "object",
                        },
                        "optionsSchema": {
                            "additionalProperties": False,
                            "properties": {"return": {"type": "array"}},
                            "type": "object",
                        },
                        "resultSchema": {"properties": {"return": {"type": "array"}}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.wwise.core.profiler.startCapture",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "sessionId": {"type": "string"},
                                "gameObject": {"type": "string"},
                                "start": {"type": "integer"},
                                "end": {"type": "integer"},
                            },
                            "required": ["sessionId"],
                            "type": "object",
                        },
                        "optionsSchema": {
                            "additionalProperties": False,
                            "properties": {"return": {"type": "array"}},
                            "type": "object",
                        },
                        "resultSchema": {"properties": {"return": {"type": "array"}}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.wwise.core.log.get",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "sessionId": {"type": "string"},
                                "cursorTime": {"type": "integer"},
                            },
                            "required": ["sessionId"],
                            "type": "object",
                        },
                        "optionsSchema": {
                            "additionalProperties": False,
                            "properties": {"return": {"type": "array"}},
                            "type": "object",
                        },
                        "resultSchema": {"properties": {"return": {"type": "array"}}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.wwise.core.profiler.captureLog.itemAdded",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "sessionId": {"type": "string"},
                                "itemId": {"type": "string"},
                                "message": {"type": "string"},
                            },
                            "required": ["sessionId"],
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                        "resultSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
            ]
        },
    )
    return ManifestSchemaLoader(store)


def query_manifest_loader() -> ManifestSchemaLoader:
    store = ManifestStore()
    store.record(
        VERSION,
        {
            "schemas": [
                {
                    "uri": "ak.wwise.core.object.get",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {
                                "from": {"type": "object"},
                                "waql": {"type": "string"},
                            },
                            "type": "object",
                        },
                        "optionsSchema": {
                            "additionalProperties": False,
                            "properties": {"return": {"type": "array"}},
                            "type": "object",
                        },
                        "resultSchema": {"properties": {"return": {"type": "array"}}, "type": "object"},
                    },
                }
            ]
        },
    )
    return ManifestSchemaLoader(store)


def deferred_registry() -> DeferredRegistry:
    entries = []
    for uri, item_type, reason, blocking_condition, substitute_test in (
        (
            "ak.wwise.core.profiler.startCapture",
            "function",
            "Profiler guidance is inventory-only.",
            "Profiler behavior needs live session evidence.",
            "Registry lookup only; not behavioral coverage.",
        ),
        (
            "ak.wwise.core.log.get",
            "function",
            "Log guidance is inventory-only.",
            "Log behavior needs live session evidence.",
            "Registry lookup only; not behavioral coverage.",
        ),
        (
            "ak.wwise.core.profiler.captureLog.itemAdded",
            "topic",
            "Capture-log topics are inventory-only.",
            "Capture-log topics need live session evidence.",
            "Registry lookup only; not behavioral coverage.",
        ),
    ):
        classification = ApiClassifier().classify(uri, item_type)
        entries.append(
            {
                "uri": uri,
                "version": VERSION,
                "category": classification.category,
                "reason": reason,
                "evidence_source": "tests/unit/test_profiler_semantic_helpers.py",
                "blocking_condition": blocking_condition,
                "substitute_test": substitute_test,
                "owner_follow_up": "Task 11 bounded profiler guidance.",
                "date": "2026-05-11",
                "review_trigger": "When profiler/log guidance requirements change.",
                "risk_level": classification.risk_level,
                "inventory_coverage": "reflected-schema-ok",
                "behavioral_coverage": "deferred",
                "item_type": item_type,
            }
        )
    return DeferredRegistry.from_mappings(entries)

from __future__ import annotations

import json
from typing import Any

from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    GET_FUNCTIONS_URI,
    GET_SCHEMA_URI,
    GET_TOPICS_URI,
    DeterministicJsonWriter,
    build_manifest_from_caller,
)


class FakeReflectionCaller:
    def __init__(self, functions: list[dict[str, Any]], topics: list[dict[str, Any]]) -> None:
        self.functions = functions
        self.topics = topics
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def call(self, uri: str, args: dict[str, str] | None = None) -> Any:
        self.calls.append((uri, args))
        if uri == GET_FUNCTIONS_URI:
            return {"functions": self.functions}
        if uri == GET_TOPICS_URI:
            return {"topics": self.topics}
        if uri == GET_SCHEMA_URI:
            assert args is not None
            return {
                "schemaFor": args["uri"],
                "$ref": "#/definitions/ak.wwise.core.object",
                "examplePath": "/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject/SampleProject.wproj",
                "windowsPath": "C:\\Users\\fixture\\SampleProject\\SampleProject.wproj",
            }
        raise AssertionError(f"unexpected uri: {uri}")


def test_shuffled_reflection_input_produces_byte_identical_json() -> None:
    functions_a = [
        {"uri": "ak.zzz.last", "displayName": "Last"},
        {"uri": "ak.aaa.first", "displayName": "First"},
    ]
    topics_a = [
        {"uri": "ak.topic.beta", "displayName": "Beta"},
        {"uri": "ak.topic.alpha", "displayName": "Alpha"},
    ]
    functions_b = list(reversed(functions_a))
    topics_b = list(reversed(topics_a))

    writer = DeterministicJsonWriter()
    manifest_a = build_manifest_from_caller(
        FakeReflectionCaller(functions_a, topics_a),
        inventory_source="fixture-reflection",
        wwise_build="fixture-build",
    )
    manifest_b = build_manifest_from_caller(
        FakeReflectionCaller(functions_b, topics_b),
        inventory_source="fixture-reflection",
        wwise_build="fixture-build",
    )

    assert writer.dumps(manifest_a.as_dict()) == writer.dumps(manifest_b.as_dict())
    assert [entry["uri"] for entry in manifest_a.functions] == ["ak.aaa.first", "ak.zzz.last"]
    assert [entry["uri"] for entry in manifest_a.topics] == ["ak.topic.alpha", "ak.topic.beta"]


def test_generator_calls_inventory_and_schema_for_each_uri() -> None:
    caller = FakeReflectionCaller(
        functions=[{"uri": "ak.function.one"}, {"uri": "ak.function.two"}],
        topics=[{"uri": "ak.topic.one"}],
    )
    manifest = build_manifest_from_caller(caller, inventory_source="fixture-reflection")

    schema_calls = [args for uri, args in caller.calls if uri == GET_SCHEMA_URI]
    assert caller.calls[0:2] == [(GET_FUNCTIONS_URI, None), (GET_TOPICS_URI, None)]
    assert schema_calls == [
        {"uri": "ak.function.one"},
        {"uri": "ak.function.two"},
        {"uri": "ak.topic.one"},
    ]
    assert manifest.audit.counts_match is True
    assert manifest.audit.schema_count == 3


def test_manifest_contains_no_local_absolute_paths() -> None:
    manifest = build_manifest_from_caller(
        FakeReflectionCaller(functions=[{"uri": "ak.function.path"}], topics=[]),
        inventory_source="fixture-reflection",
    )
    serialized = json.dumps(manifest.as_dict(), sort_keys=True)

    assert "/Applications/Audiokinetic" not in serialized
    assert "C:\\\\Users" not in serialized
    assert "<local-path-redacted>" in serialized


def test_schema_json_pointer_refs_are_preserved_while_paths_are_redacted() -> None:
    manifest = build_manifest_from_caller(
        FakeReflectionCaller(functions=[{"uri": "ak.function.ref"}], topics=[]),
        inventory_source="fixture-reflection",
    )
    schema = manifest.schemas[0]["schema"]

    assert schema["$ref"] == "#/definitions/ak.wwise.core.object"
    assert schema["examplePath"] == "<local-path-redacted>"
    assert schema["windowsPath"] == "<local-path-redacted>"
    assert "#<local-path-redacted>" not in json.dumps(manifest.as_dict(), sort_keys=True)

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderContext,
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticReadbackPlan,
    SemanticValidationError,
    SourceNoteCheck,
    require_source_note,
)
from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck) -> None:
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


class FakeWaapiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> dict[str, bool]:
        self.calls.append((uri, args, options))
        return {"called": True}


def manifest_store() -> ManifestStore:
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "functions": [{"uri": "ak.wwise.core.object.delete"}, {"uri": "ak.wwise.core.object.get"}],
            "topics": [],
            "schemas": [
                {
                    "uri": "ak.wwise.core.object.get",
                    "schema": {"argsSchema": {"properties": {"waql": {"type": "string"}}}},
                }
            ],
        },
    )
    return store


def test_semantic_envelope_keeps_metadata_outside_dispatch_shape() -> None:
    envelope = SemanticEnvelope(
        uri="ak.wwise.core.object.get",
        args={"waql": "from type Sound"},
        options={"return": ["id", "name"]},
        metadata={"source_note_family": "query", "requires_destructive_gate": False},
    )

    assert envelope.dispatch_payload() == {
        "uri": "ak.wwise.core.object.get",
        "args": {"waql": "from type Sound"},
        "options": {"return": ["id", "name"]},
    }
    assert envelope.as_dict()["metadata"] == {"source_note_family": "query", "requires_destructive_gate": False}
    assert "metadata" not in envelope.dispatch_payload()["args"]
    assert "metadata" not in envelope.dispatch_payload()["options"]


def test_builder_family_values_match_plan_source_note_families() -> None:
    assert BuilderFamily.QUERY.value == "query"
    assert BuilderFamily.OBJECT_MUTATION.value == "object-mutation"
    assert BuilderFamily.PROPERTY_REFERENCE.value == "property-reference"
    assert BuilderFamily.IMPORT.value == "import"
    assert BuilderFamily.SOUNDBANK.value == "soundbank"
    assert BuilderFamily.SWITCHCONTAINER.value == "switchcontainer"


def test_builder_context_accepts_only_plan_families() -> None:
    accepted = (
        BuilderFamily.QUERY.value,
        BuilderFamily.OBJECT_MUTATION.value,
        BuilderFamily.PROPERTY_REFERENCE.value,
        BuilderFamily.IMPORT.value,
        BuilderFamily.SOUNDBANK.value,
        BuilderFamily.SWITCHCONTAINER.value,
    )

    for family in accepted:
        BuilderContext(family, manifest_loader=ManifestSchemaLoader(manifest_store())).require_supported_family()

    for family in ("soundengine", "transport", "ui", "cli", "remote", "debug", "unknown-family", "waql", "object", "property", "switch"):
        with pytest.raises(SemanticValidationError) as exc:
            BuilderContext(family, manifest_loader=ManifestSchemaLoader(manifest_store())).require_supported_family()
        assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY


def test_preview_serializes_required_metadata_and_readback_plans() -> None:
    preview = SemanticPreview(
        envelope=SemanticEnvelope("ak.wwise.core.object.get", args={"waql": "from type Sound"}),
        source_note_family=BuilderFamily.QUERY.value,
        readback_plan=(SemanticReadbackPlan("ak.wwise.core.object.get", args={"from": "readback"}),),
        evidence_plan=({"kind": "source-note", "required": True},),
    )

    payload = preview.as_dict()

    assert payload["requires_destructive_gate"] is False
    assert payload["source_note_family"] == "query"
    assert payload["version"] == "2022.1"
    assert payload["raw_dispatch_allowed"] is False
    assert payload["readback_plan"] == [
        {"uri": "ak.wwise.core.object.get", "args": {"from": "readback"}, "options": {}, "description": ""}
    ]
    assert json.loads(json.dumps(payload))["evidence_plan"] == [{"kind": "source-note", "required": True}]


def test_destructive_preview_marks_gate_without_dispatching() -> None:
    client = FakeWaapiClient()
    preview = SemanticPreview(
        envelope=SemanticEnvelope("ak.wwise.core.object.delete", args={"object": "{fixture}"}),
        source_note_family=BuilderFamily.OBJECT_MUTATION.value,
        requires_destructive_gate=True,
        readback_plan=(SemanticReadbackPlan("ak.wwise.core.object.get", description="confirm deletion target state"),),
    )

    payload = preview.as_dict()

    assert payload["requires_destructive_gate"] is True
    assert payload["raw_dispatch_allowed"] is False
    assert preview.dispatch_payload()["uri"] == "ak.wwise.core.object.delete"
    assert client.calls == []


def test_envelope_converts_to_dry_run_dispatcher_request_without_metadata() -> None:
    envelope = SemanticEnvelope(
        "ak.wwise.core.object.get",
        args={"waql": "from type Sound"},
        options={"return": ["id"]},
        metadata={"semantic": True},
    )

    request = envelope.to_dispatcher_request(version="2022.1")

    assert request.api == "ak.wwise.core.object.get"
    assert request.args == {"waql": "from type Sound"}
    assert request.options == {"return": ["id"]}
    assert request.dry_run is True
    assert "semantic" not in request.args


def test_manifest_schema_loader_uses_manifest_store_and_typed_errors() -> None:
    loader = ManifestSchemaLoader(manifest_store())

    assert loader.schema_for("ak.wwise.core.object.get")["argsSchema"]["properties"]["waql"] == {"type": "string"}

    with pytest.raises(SemanticValidationError) as missing_schema:
        loader.schema_for("ak.wwise.core.object.delete")
    assert missing_schema.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as unsupported_version:
        loader.load_manifest("1999.9")
    assert unsupported_version.value.error_code == SemanticErrorCode.UNSUPPORTED_WWISE_VERSION


def test_source_note_checker_adapter_accepts_task0_shape_and_reports_codes() -> None:
    checker = FakeSourceNoteChecker(SourceNoteCheck(True, "query", cited_fields=("waql",)))

    status = require_source_note(checker, BuilderFamily.QUERY)

    assert status.allowed is True
    assert checker.calls == [("query", "2022.1")]

    incomplete = FakeSourceNoteChecker(SourceNoteCheck(False, "query", missing_fields=("Examples",), reason="missing examples"))
    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(incomplete, BuilderFamily.QUERY)
    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert exc.value.details["missing_fields"] == ["Examples"]


def test_builder_context_rejects_unknown_family_with_typed_error() -> None:
    context = BuilderContext("unknown-family", manifest_loader=ManifestSchemaLoader(manifest_store()))

    with pytest.raises(SemanticValidationError) as exc:
        context.require_supported_family()

    assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY


def test_builder_does_not_patch_dispatcher() -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())
    preview = SemanticPreview(
        envelope=SemanticEnvelope("ak.wwise.core.object.delete", args={"object": "{fixture}"}),
        source_note_family=BuilderFamily.OBJECT_MUTATION.value,
        requires_destructive_gate=True,
    )

    request = preview.to_dispatcher_request()

    assert client.calls == []
    assert request.dry_run is True
    assert WwiseDispatcher.dispatch.__module__ == "wwise_waapi.dispatcher"

    result = dispatcher.dispatch(request)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["result"]["would_dispatch"] == "function"
    assert client.calls == []

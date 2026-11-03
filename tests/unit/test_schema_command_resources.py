"""Packaged schema lookup is command-scoped; live state is never reused."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wwise_waapi.builders.common import ManifestSchemaLoader
from wwise_waapi.builders.schema import SemanticSchemaValidator
from wwise_waapi.manifest import ManifestStore, command_manifest_resources


def test_command_schema_lookup_reads_once_isolates_outputs_and_refreshes_next_command(tmp_path, monkeypatch):
    version_dir = tmp_path / "2022.1"
    version_dir.mkdir()
    uri = "ak.test.commandSchema"
    for filename, value in {
        "manifest.json": {"version": "2022.1"},
        "functions.json": {"functions": [{"uri": uri}]},
        "topics.json": {"topics": []},
    }.items():
        (version_dir / filename).write_text(json.dumps(value), encoding="utf-8")
    schema_path = version_dir / "schemas.json"

    def write_schema(value_type):
        schema_path.write_text(json.dumps({"schemas": [{"uri": uri, "status": "ok", "schema": {
            "resultSchema": {"type": value_type},
        }}]}), encoding="utf-8")

    write_schema("integer")
    reads = 0
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        nonlocal reads
        if path == schema_path:
            reads += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    validator = SemanticSchemaValidator(ManifestSchemaLoader(ManifestStore(root=tmp_path)))
    with command_manifest_resources():
        first = validator.schema_for(uri)
        first["resultSchema"]["type"] = "boolean"
        write_schema("string")
        assert validator.schema_for(uri)["resultSchema"] == {"type": "integer"}
        assert reads == 1
    with command_manifest_resources():
        assert validator.schema_for(uri)["resultSchema"] == {"type": "string"}
        assert reads == 2
    schema_path.write_text("{corrupt", encoding="utf-8")
    with command_manifest_resources(), pytest.raises(json.JSONDecodeError):
        validator.schema_for(uri)

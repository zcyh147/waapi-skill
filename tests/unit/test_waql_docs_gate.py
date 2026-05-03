from __future__ import annotations

import json
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import (  # pyright: ignore[reportMissingImports]
    WAQL_API_URI,
    WaqlReferenceGate,
    require_waql_helper_generation,
    waql_api_uris,
    validate_waql_live_matrix,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest"
WAQL_REFERENCE = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "waql" / "2022.1" / "object-get-live-matrix.json"


def test_default_waql_reference_opens_helper_generation_gate() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")

    status = WaqlReferenceGate(WAQL_REFERENCE).check()
    waql_apis = require_waql_helper_generation(manifest, WAQL_REFERENCE)

    assert status.allowed is True
    assert waql_apis == (WAQL_API_URI,)


def test_manifest_identifies_waql_apis_from_schema_argument() -> None:
    manifest = {
        "schemas": [
            {"uri": "ak.wwise.core.getInfo", "schema": {"argsSchema": {"properties": {}}}},
            {"uri": WAQL_API_URI, "schema": {"argsSchema": {"properties": {"waql": {"type": "string"}}}}},
        ]
    }

    assert waql_api_uris(manifest) == (WAQL_API_URI,)


def test_missing_waql_reference_blocks_helper_generation(tmp_path: Path) -> None:
    manifest = {"schemas": [{"uri": WAQL_API_URI, "schema": {"argsSchema": {"properties": {"waql": {}}}}}]}

    with pytest.raises(RuntimeError, match="WAQL helper generation blocked"):
        require_waql_helper_generation(manifest, tmp_path / "missing.md")


def test_incomplete_waql_reference_blocks_helper_generation(tmp_path: Path) -> None:
    reference = tmp_path / "waql.json"
    reference.write_text(
        '{"metadata":{"name":"WAQL live sandbox matrix","uri":"ak.wwise.core.object.get","schema_source":"resources/manifest/2022.1/schemas.json#ak.wwise.core.object.get"},"live_cases":[{"id":"broken","uri":"ak.wwise.core.object.get","args":{"waql":"from type Sound"},"options":{"return":["id"]},"no_mutation":false,"sources":[]}]}',
        encoding="utf-8",
    )
    manifest = {"schemas": [{"uri": WAQL_API_URI, "schema": {"argsSchema": {"properties": {"waql": {}}}}}]}

    status = WaqlReferenceGate(reference).check()

    assert status.allowed is False
    assert "read-only" in status.reason or "incomplete" in status.reason
    with pytest.raises(RuntimeError, match="incomplete"):
        require_waql_helper_generation(manifest, reference)


def test_live_matrix_keeps_required_resource_fields_and_source_names() -> None:
    matrix = WAQL_REFERENCE.read_text(encoding="utf-8")

    validate_waql_live_matrix(json.loads(matrix))
    assert "waql-2022.1.md" not in matrix
    assert "resources/waql/2022.1/object-get-live-matrix.json" in matrix


def test_no_waql_api_does_not_require_docs_generation(tmp_path: Path) -> None:
    manifest = {"schemas": [{"uri": "ak.wwise.core.getInfo", "schema": {"argsSchema": {"properties": {}}}}]}

    assert require_waql_helper_generation(manifest, tmp_path / "missing.md") == ()

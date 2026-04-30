from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import (  # pyright: ignore[reportMissingImports]
    REQUIRED_REFERENCE_SECTIONS,
    WAQL_API_URI,
    WaqlReferenceGate,
    require_waql_helper_generation,
    waql_api_uris,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = REPO_ROOT / "resources" / "manifest"
WAQL_REFERENCE = REPO_ROOT / "references" / "waql-2022.1.md"


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
    reference = tmp_path / "waql.md"
    reference.write_text("# WAQL\n\n## Syntax\n\nNotebookLM wwise-2022.1-docs\n", encoding="utf-8")
    manifest = {"schemas": [{"uri": WAQL_API_URI, "schema": {"argsSchema": {"properties": {"waql": {}}}}}]}

    status = WaqlReferenceGate(reference).check()

    assert status.allowed is False
    assert "## Operators" in status.missing
    with pytest.raises(RuntimeError, match="incomplete"):
        require_waql_helper_generation(manifest, reference)


def test_reference_keeps_required_sections_and_source_names() -> None:
    text = WAQL_REFERENCE.read_text(encoding="utf-8")

    for section in REQUIRED_REFERENCE_SECTIONS:
        assert section in text
    assert "WwiseSDK-Windows_01.pdf" in text
    assert "WwiseSDK-Windows_02.pdf" in text
    assert "WwiseSDK-Windows_03.pdf" in text
    assert "## Gaps" in text


def test_no_waql_api_does_not_require_docs_generation(tmp_path: Path) -> None:
    manifest = {"schemas": [{"uri": "ak.wwise.core.getInfo", "schema": {"argsSchema": {"properties": {}}}}]}

    assert require_waql_helper_generation(manifest, tmp_path / "missing.md") == ()

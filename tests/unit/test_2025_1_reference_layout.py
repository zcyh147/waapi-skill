from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from wwise_waapi.builders.common import BuilderFamily, SemanticErrorCode  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
REFERENCE_ROOT = SKILL_ROOT / "references" / "semantic" / "2025.1"
SOURCE_NOTES = SKILL_ROOT / "resources" / "semantic" / "2025.1" / "source_notes.json"
GATE_PATH = REFERENCE_ROOT / "semantic-builder-notebooklm-gate.md"
VERSION_2025 = "2025.1"
NOTEBOOK_2025 = "wwise-2025.1-docs"
FAMILIES = (
    "query",
    "object-mutation",
    "property-reference",
    "import",
    "soundbank",
    "switchcontainer",
)
EXPECTED_FILES = {
    "semantic-builder-protocol.md",
    "semantic-builder-notebooklm-gate.md",
    *(f"semantic-builder-{family}.md" for family in FAMILIES),
}
REQUIRED_SECTIONS = (
    "## Official/source URLs",
    "## Endpoint inventory",
    "## Required fields",
    "## Optional fields",
    "## Return shape",
    "## Destructive behavior",
    "## Ambiguity constraints",
    "## Unsupported cases",
    "## Cited required fields",
)
FORBIDDEN_TEXT = (
    "wwise-2022.1-docs",
    "wwise-2023.1-docs",
    "wwise-2024.1-docs",
    "references/semantic-builder-",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "references/semantic/2024.1",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024.1",
    "resources/semantic/2025/",
    "references/semantic/2025/",
)
REQUIRED_NOTE_KEYS = {
    "family",
    "status",
    "version_target",
    "official_urls",
    "source_urls",
    "endpoints",
    "required_fields",
    "optional_fields",
    "return_shape",
    "destructive_behavior",
    "ambiguity_constraints",
    "unsupported_cases",
    "cited_required_fields",
}


def read_reference(name: str) -> str:
    return (REFERENCE_ROOT / f"semantic-builder-{name}.md").read_text(encoding="utf-8")


def read_source_notes() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(SOURCE_NOTES.read_text(encoding="utf-8")))


def write_artifact_resource(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "waapi-skill" / "resources" / "semantic" / "2025.1" / "source_notes.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_2025_1_semantic_reference_files_are_versioned_and_complete() -> None:
    assert {path.name for path in REFERENCE_ROOT.glob("semantic-builder-*.md")} == EXPECTED_FILES

    for name in ("protocol", "notebooklm-gate", *FAMILIES):
        text = read_reference(name)
        assert NOTEBOOK_2025 in text
        assert VERSION_2025 in text
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in text, f"{name} contains forbidden proof fragment: {forbidden}"

    for family in FAMILIES:
        text = read_reference(family)
        assert f"- family: `{family}`" in text
        assert "- status: `grounded`" in text
        assert "official URL status: `evidence-candidate`" in text
        assert "2025.1.7_6590" in text
        assert "## Evidence caveat" in text
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{family} missing {section}"


def test_2025_1_notebooklm_gate_evidence_is_persisted_locally() -> None:
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert "- Gate status: open" in gate_text
    assert "- Notebook id: wwise-2025.1-docs" in gate_text
    assert "- Auth result: success" in gate_text
    assert "- List result: success" in gate_text
    assert "- Query result: success" in gate_text
    assert "Evidence path: references/semantic/2025.1/semantic-builder-notebooklm-gate.md" in gate_text
    assert "python scripts/run.py auth_manager.py status" in gate_text
    assert "python scripts/run.py notebook_manager.py list" in gate_text
    assert "--notebook-id wwise-2025.1-docs" in gate_text
    assert "Runtime builders must read versioned local source-note resources" in gate_text


def test_2025_1_source_notes_schema_uses_only_2025_1_notebook_and_local_references() -> None:
    payload = read_source_notes()

    assert payload["version"] == VERSION_2025
    assert "notebook_id" not in payload
    assert payload["protocol"] == "references/semantic/2025.1/semantic-builder-protocol.md"
    assert set(payload["notes"]) == set(FAMILIES)

    seen_endpoints: set[str] = set()
    for family, note in payload["notes"].items():
        assert set(note) == REQUIRED_NOTE_KEYS
        assert note["family"] == family
        assert note["status"] == "grounded"
        assert "notebook_id" not in note
        assert note["version_target"] == VERSION_2025
        assert "gate_evidence_path" not in note
        assert note["source_urls"] == [f"references/semantic/2025.1/semantic-builder-{family}.md"]
        assert set(note["required_fields"]) <= set(note["cited_required_fields"])
        assert note["official_urls"]
        assert note["endpoints"]
        assert note["required_fields"]
        assert note["optional_fields"]
        assert note["return_shape"]
        assert note["destructive_behavior"]
        assert note["ambiguity_constraints"]
        assert note["unsupported_cases"]

        for endpoint in note["endpoints"]:
            assert endpoint not in seen_endpoints, endpoint
            seen_endpoints.add(endpoint)

        encoded_note = json.dumps(note, sort_keys=True)
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in encoded_note, f"{family} contains forbidden proof fragment: {forbidden}"


def test_2025_1_runtime_layout_checks_have_no_notebooklm_dependency() -> None:
    assert SOURCE_NOTES.is_file()
    assert GATE_PATH.is_file()
    assert importlib.util.find_spec("notebooklm") is None

    payload = read_source_notes()
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert "notebook_id" not in payload
    assert "NotebookLM" in gate_text
    assert "browser_state" not in gate_text
    assert "state.json" not in gate_text
    assert "notebooklm.google.com/notebook/" not in gate_text


def test_2025_1_source_note_checker_allows_grounded_local_notes() -> None:
    for family in BuilderFamily:
        status = SemanticSourceNoteChecker().check(family.value, version=VERSION_2025)

        assert status.allowed is True
        assert status.version == VERSION_2025
        assert status.reason == "Semantic source note is grounded."

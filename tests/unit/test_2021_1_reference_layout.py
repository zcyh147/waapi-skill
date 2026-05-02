from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, cast


REFERENCE_ROOT = Path("references") / "semantic" / "2021.1"
SOURCE_NOTES = Path("resources") / "semantic" / "2021.1" / "source_notes.json"
GATE_PATH = REFERENCE_ROOT / "semantic-builder-notebooklm-gate.md"
VERSION = "2021.1"
NOTEBOOK = "source_pending"
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
    "wwise-2025.1-docs",
    "references/semantic-builder-",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "references/semantic/2024.1",
    "references/semantic/2025.1",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024.1",
    "resources/semantic/2025.1",
)
REQUIRED_NOTE_KEYS = {
    "family",
    "status",
    "notebook_id",
    "version_target",
    "gate_evidence_path",
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


def test_2021_1_semantic_reference_files_are_versioned_and_pending() -> None:
    assert {path.name for path in REFERENCE_ROOT.glob("semantic-builder-*.md")} == EXPECTED_FILES

    for name in ("protocol", "notebooklm-gate", *FAMILIES):
        text = read_reference(name)
        assert VERSION in text
        assert "source_pending" in text
        assert "reflection_pending" in text or name != "protocol"
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in text, f"{name} contains forbidden proof fragment: {forbidden}"

    for family in FAMILIES:
        text = read_reference(family)
        assert f"- family: `{family}`" in text
        assert "- status: `source_pending`" in text
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{family} missing {section}"


def test_2021_1_notebooklm_gate_is_explicitly_pending() -> None:
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert "- Gate status: pending" in gate_text
    assert "- Notebook id: source_pending" in gate_text
    assert "- Auth result: pending" in gate_text
    assert "- List result: pending" in gate_text
    assert "- Query result: pending" in gate_text
    assert "not source proof" in gate_text
    assert "not be treated as behavioral evidence" in gate_text


def test_2021_1_source_notes_are_scaffold_only_and_local_only() -> None:
    payload = read_source_notes()

    assert payload["version"] == VERSION
    assert payload["notebook_id"] == NOTEBOOK
    assert payload["protocol"] == "references/semantic/2021.1/semantic-builder-protocol.md"
    assert set(payload["notes"]) == set(FAMILIES)

    seen_endpoints: set[str] = set()
    for family, note in payload["notes"].items():
        assert set(note) == REQUIRED_NOTE_KEYS
        assert note["family"] == family
        assert note["status"] == "source_pending"
        assert note["notebook_id"] == NOTEBOOK
        assert note["version_target"] == VERSION
        assert note["gate_evidence_path"] == "references/semantic/2021.1/semantic-builder-notebooklm-gate.md"
        assert note["source_urls"] == [
            "references/semantic/2021.1/semantic-builder-notebooklm-gate.md",
            f"references/semantic/2021.1/semantic-builder-{family}.md",
        ]
        assert note["official_urls"] == []
        assert note["endpoints"] == []
        assert note["required_fields"] == []
        assert note["optional_fields"] == []
        assert note["return_shape"] == "source_pending"
        assert note["destructive_behavior"] == "source_pending"
        assert note["ambiguity_constraints"] == "source_pending"
        assert note["unsupported_cases"] == "source_pending"
        assert note["cited_required_fields"] == []

        assert not seen_endpoints

        encoded_note = json.dumps(note, sort_keys=True)
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in encoded_note, f"{family} contains forbidden proof fragment: {forbidden}"


def test_2021_1_runtime_layout_checks_have_no_notebooklm_dependency() -> None:
    assert SOURCE_NOTES.is_file()
    assert GATE_PATH.is_file()
    assert importlib.util.find_spec("notebooklm") is None

    payload = read_source_notes()
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert payload["notebook_id"] == NOTEBOOK
    assert "browser_state" not in gate_text
    assert "state.json" not in gate_text
    assert "notebooklm.google.com/notebook/" not in gate_text

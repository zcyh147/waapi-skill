from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, cast


REFERENCE_ROOT = Path("references") / "semantic" / "2024.1"
SOURCE_NOTES = Path("skills") / "waapi-skill" / "resources" / "semantic" / "2024.1" / "source_notes.json"
GATE_PATH = REFERENCE_ROOT / "semantic-builder-notebooklm-gate.md"
TASK_5_NOTEBOOKLM_EVIDENCE = Path(".sisyphus") / "evidence" / "task-2024-5-notebooklm-gate.txt"
VERSION_2024 = "2024.1"
NOTEBOOK_2024 = "wwise-2024.1-docs"
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
    "references/semantic-builder-",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024/",
    "references/semantic/2024/",
    "resources/semantic/2025",
    "references/semantic/2025",
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


def test_2024_semantic_reference_files_are_versioned_and_complete() -> None:
    assert {path.name for path in REFERENCE_ROOT.glob("semantic-builder-*.md")} == EXPECTED_FILES

    for name in ("protocol", "notebooklm-gate", *FAMILIES):
        text = read_reference(name)
        assert NOTEBOOK_2024 in text
        assert VERSION_2024 in text
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in text, f"{name} contains forbidden proof fragment: {forbidden}"

    for family in FAMILIES:
        text = read_reference(family)
        assert f"- family: `{family}`" in text
        assert "- status: `grounded`" in text
        assert "official URL status: `evidence-candidate`" in text
        assert "2024.1.13_9056" in text
        assert "## Evidence caveat" in text
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{family} missing {section}"


def test_2024_notebooklm_gate_evidence_is_persisted_locally() -> None:
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert "- Gate status: open" in gate_text
    assert "- Notebook id: wwise-2024.1-docs" in gate_text
    assert "- Auth result: success" in gate_text
    assert "- List result: success" in gate_text
    assert "- Query result: success" in gate_text
    assert "Evidence path: references/semantic/2024.1/semantic-builder-notebooklm-gate.md" in gate_text
    assert "python scripts/run.py auth_manager.py status" in gate_text
    assert "python scripts/run.py notebook_manager.py list" in gate_text
    assert "--notebook-id wwise-2024.1-docs" in gate_text
    assert "Runtime builders must read versioned local source-note resources" in gate_text


def test_2024_source_notes_schema_uses_only_2024_notebook_and_local_references() -> None:
    payload = read_source_notes()

    assert payload["version"] == VERSION_2024
    assert payload["notebook_id"] == NOTEBOOK_2024
    assert payload["protocol"] == "references/semantic/2024.1/semantic-builder-protocol.md"
    assert set(payload["notes"]) == set(FAMILIES)

    seen_endpoints: set[str] = set()
    for family, note in payload["notes"].items():
        assert set(note) == REQUIRED_NOTE_KEYS
        assert note["family"] == family
        assert note["status"] == "grounded"
        assert note["notebook_id"] == NOTEBOOK_2024
        assert note["version_target"] == VERSION_2024
        assert note["gate_evidence_path"] == "references/semantic/2024.1/semantic-builder-notebooklm-gate.md"
        assert note["source_urls"] == [
            "references/semantic/2024.1/semantic-builder-notebooklm-gate.md",
            f"references/semantic/2024.1/semantic-builder-{family}.md",
        ]
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


def test_2024_runtime_layout_checks_have_no_notebooklm_dependency() -> None:
    assert SOURCE_NOTES.is_file()
    assert GATE_PATH.is_file()
    assert importlib.util.find_spec("notebooklm") is None

    payload = read_source_notes()
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert payload["notebook_id"] == NOTEBOOK_2024
    assert "NotebookLM" in gate_text
    assert "browser_state" not in gate_text
    assert "state.json" not in gate_text
    assert "notebooklm.google.com/notebook/" not in gate_text

def test_2024_task5_notebooklm_evidence_omits_auth_artifacts() -> None:
    evidence_text = TASK_5_NOTEBOOKLM_EVIDENCE.read_text(encoding="utf-8")

    assert "Authenticated: Yes" in evidence_text
    assert "Wwise 2024.1 Docs [ACTIVE]" in evidence_text
    assert "ID: wwise-2024.1-docs" in evidence_text
    assert "--notebook-id wwise-2024.1-docs" in evidence_text
    assert "State file: omitted (local auth artifact)" in evidence_text
    assert "browser_state" not in evidence_text
    assert "state.json" not in evidence_text
    assert "notebooklm.google.com/notebook/" not in evidence_text
    assert "cookie" not in evidence_text.lower()

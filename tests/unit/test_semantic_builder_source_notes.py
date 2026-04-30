from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    require_source_note,
)
from wwise_waapi.builders.source_notes import (  # pyright: ignore[reportMissingImports]
    DEFAULT_SEMANTIC_SOURCE_NOTES,
    EXPECTED_SOURCE_NOTE_URI_INVENTORY,
    REQUIRED_SOURCE_NOTE_FIELDS,
    SemanticSourceNoteChecker,
    source_note_uri_inventory,
)


EXPECTED_INVENTORY = EXPECTED_SOURCE_NOTE_URI_INVENTORY

EXCLUDED_URI_TOKENS = ("profiler", "transport", "soundengine", ".ui.", ".cli.", "remote", "debug")


def load_resource() -> dict[str, Any]:
    return json.loads(DEFAULT_SEMANTIC_SOURCE_NOTES.read_text(encoding="utf-8"))


def write_resource(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "source_notes.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_gate_evidence(tmp_path: Path, text: str) -> Path:
    evidence = tmp_path / "semantic-builder-notebooklm-gate.md"
    evidence.write_text(text, encoding="utf-8")
    return evidence


SUCCESS_GATE_EVIDENCE = """# Semantic builder NotebookLM gate evidence

- Gate status: open
- Notebook id: wwise-2022.1-docs
- Auth result: success
- List result: success
- Query result: success
"""


def test_grounded_source_notes_unlock_all_builder_families() -> None:
    checker = SemanticSourceNoteChecker()

    for family in BuilderFamily:
        status = require_source_note(checker, family)
        assert status.allowed is True
        assert status.family == family.value
        assert status.notebook_id == "wwise-2022.1-docs"
        assert status.cited_fields


def test_source_note_family_uri_inventory() -> None:
    inventory = source_note_uri_inventory()

    assert inventory == EXPECTED_INVENTORY
    assert set(inventory) == {family.value for family in BuilderFamily}

    all_uris = [uri for endpoints in inventory.values() for uri in endpoints]
    assert len(all_uris) == len(set(all_uris))
    assert not any(token in uri.lower() for uri in all_uris for token in EXCLUDED_URI_TOKENS)


def test_source_notes_have_explicit_status_and_required_sections() -> None:
    data = load_resource()

    assert data["version"] == "2022.1"
    assert data["notebook_id"] == "wwise-2022.1-docs"
    for family, note in data["notes"].items():
        assert family in EXPECTED_INVENTORY
        assert note["status"] in {"grounded", "fail-closed"}
        for field in REQUIRED_SOURCE_NOTE_FIELDS:
            assert field in note
        assert note["official_urls"]
        assert note["source_urls"]
        assert note["gate_evidence_path"] == "references/semantic-builder-notebooklm-gate.md"


def test_source_notes_have_no_embedded_gate_success_claims() -> None:
    data = load_resource()

    for note in data["notes"].values():
        assert "gate_evidence" not in note
        assert "auth_result" not in note
        assert "list_result" not in note
        assert "query_result" not in note


def test_missing_source_note_resource_fails_with_typed_code(tmp_path: Path) -> None:
    checker = SemanticSourceNoteChecker(tmp_path / "missing.json")

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE


def test_missing_family_note_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_resource()
    del data["notes"]["query"]
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE


def test_wrong_notebook_id_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_resource()
    data["notes"]["query"]["notebook_id"] = "other-notebook"
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_WRONG_NOTEBOOK
    assert "expected wwise-2022.1-docs" in str(exc.value)


def test_wrong_notebook_gate_evidence_fails_with_typed_code(tmp_path: Path) -> None:
    evidence = write_gate_evidence(tmp_path, SUCCESS_GATE_EVIDENCE.replace("wwise-2022.1-docs", "other-notebook"))
    data = load_resource()
    for note in data["notes"].values():
        note["gate_evidence_path"] = str(evidence)
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_WRONG_NOTEBOOK


def test_missing_gate_evidence_file_fails_closed(tmp_path: Path) -> None:
    data = load_resource()
    for note in data["notes"].values():
        note["gate_evidence_path"] = str(tmp_path / "missing-gate.md")
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert "missing" in str(exc.value)


def test_fail_closed_gate_evidence_file_does_not_unlock(tmp_path: Path) -> None:
    evidence = write_gate_evidence(
        tmp_path,
        SUCCESS_GATE_EVIDENCE.replace("- Gate status: open", "- Gate status: fail-closed")
        + "- Failure: NotebookLM query did not complete.\n",
    )
    data = load_resource()
    for note in data["notes"].values():
        note["gate_evidence_path"] = str(evidence)
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert "did not complete" in str(exc.value)


def test_incomplete_source_note_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_resource()
    del data["notes"]["query"]["return_shape"]
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert exc.value.details["missing_fields"] == ["return_shape"]


def test_fail_closed_status_does_not_unlock_builder(tmp_path: Path) -> None:
    data = load_resource()
    data["notes"]["query"]["status"] = "fail-closed"
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.QUERY)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert "status" in exc.value.details["missing_fields"]


def test_uncited_required_field_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_resource()
    note = data["notes"]["property-reference"]
    note["cited_required_fields"] = note["cited_required_fields"][:-1]
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data))

    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, BuilderFamily.PROPERTY_REFERENCE)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_UNCITED_FIELD
    assert exc.value.details["uncited_fields"] == [
        "ak.wwise.core.object.setAttenuationCurve: object, curveType, use, points"
    ]


def test_duplicate_uri_inventory_fails_closed(tmp_path: Path) -> None:
    data = load_resource()
    note = data["notes"]["query"]
    note["endpoints"] = ["ak.wwise.core.object.get", "ak.wwise.core.object.get"]
    path = write_resource(tmp_path, data)

    with pytest.raises(SemanticValidationError) as exc:
        source_note_uri_inventory(path)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE


def test_undercovered_object_mutation_inventory_fails_closed(tmp_path: Path) -> None:
    data = load_resource()
    data["notes"]["object-mutation"]["endpoints"] = ["ak.wwise.core.object.set"]

    with pytest.raises(SemanticValidationError) as exc:
        source_note_uri_inventory(write_resource(tmp_path, data))

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert "ak.wwise.core.object.create" in exc.value.details["expected"]


def test_excluded_families_have_no_source_notes(tmp_path: Path) -> None:
    checker = SemanticSourceNoteChecker()

    for family in ("profiler", "transport", "soundengine", "ui", "cli", "remote", "debug"):
        status = checker.check(family)
        assert status.allowed is False
        assert status.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE

    data = load_resource()
    mutated = copy.deepcopy(data)
    mutated["notes"]["transport"] = copy.deepcopy(mutated["notes"]["query"])
    mutated["notes"]["transport"]["family"] = "transport"
    with pytest.raises(SemanticValidationError) as exc:
        source_note_uri_inventory(write_resource(tmp_path, mutated))
    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE


def test_markdown_source_notes_exist_for_human_review() -> None:
    for name in ("protocol", *EXPECTED_INVENTORY):
        path = Path("references") / f"semantic-builder-{name}.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "NotebookLM gate evidence" in text or name == "protocol"
        assert "wwise-2022.1-docs" in text

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
    EXPECTED_SOURCE_NOTE_URI_INVENTORY,
    REQUIRED_SOURCE_NOTE_FIELDS,
    SemanticSourceNoteChecker,
    source_note_uri_inventory,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_NOTES_2023 = ROOT / "skills" / "waapi-skill" / "resources" / "semantic" / "2023.1" / "source_notes.json"
NOTEBOOK_ID_2023 = "wwise-2023.1-docs"
GATE_EVIDENCE_2023 = "references/semantic/2023.1/semantic-builder-notebooklm-gate.md"
EXPECTED_FAMILIES = {
    "query",
    "object-mutation",
    "property-reference",
    "import",
    "soundbank",
    "switchcontainer",
}
EXCLUDED_TERMS = ("profiler", "transport", "soundengine", ".ui.", ".cli.", "remote", "debug")


def load_2023_resource() -> dict[str, Any]:
    return json.loads(SOURCE_NOTES_2023.read_text(encoding="utf-8"))


def write_resource(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "source_notes.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_artifact_resource(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "waapi-skill" / "resources" / "semantic" / "2023.1" / "source_notes.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def assert_typed_failure(checker: SemanticSourceNoteChecker, family: BuilderFamily, error_code: SemanticErrorCode) -> SemanticValidationError:
    with pytest.raises(SemanticValidationError) as exc:
        require_source_note(checker, family, version="2023.1")
    assert exc.value.error_code == error_code
    return exc.value


def test_2023_source_notes_require_2023_notebook_evidence() -> None:
    checker = SemanticSourceNoteChecker(notebook_id=NOTEBOOK_ID_2023)

    for family in BuilderFamily:
        status = require_source_note(checker, family, version="2023.1")
        assert status.allowed is True
        assert status.version == "2023.1"
        assert status.family == family.value
        assert status.notebook_id == NOTEBOOK_ID_2023
        assert status.cited_fields

    default_checker = SemanticSourceNoteChecker()
    failure = assert_typed_failure(default_checker, BuilderFamily.QUERY, SemanticErrorCode.SOURCE_NOTE_WRONG_NOTEBOOK)
    assert "expected wwise-2022.1-docs" in failure.message


def test_2023_source_note_inventory_exact_families() -> None:
    data = load_2023_resource()
    inventory = source_note_uri_inventory(SOURCE_NOTES_2023)

    assert data["version"] == "2023.1"
    assert data["notebook_id"] == NOTEBOOK_ID_2023
    assert set(data["notes"]) == EXPECTED_FAMILIES
    assert set(inventory) == EXPECTED_FAMILIES
    assert inventory == EXPECTED_SOURCE_NOTE_URI_INVENTORY

    all_uris = [uri for endpoints in inventory.values() for uri in endpoints]
    assert len(all_uris) == len(set(all_uris))
    assert not any(token in uri.lower() for uri in all_uris for token in EXCLUDED_TERMS)


def test_2023_source_notes_use_only_versioned_local_evidence_paths() -> None:
    data = load_2023_resource()

    assert data["protocol"] == "references/semantic/2023.1/semantic-builder-protocol.md"
    for family, note in data["notes"].items():
        assert family in EXPECTED_FAMILIES
        assert note["status"] == "grounded"
        assert note["notebook_id"] == NOTEBOOK_ID_2023
        assert note["version_target"] == "2023.1"
        assert note["gate_evidence_path"] == GATE_EVIDENCE_2023
        assert note["endpoints"] == list(EXPECTED_SOURCE_NOTE_URI_INVENTORY[family])
        assert set(note["required_fields"]) <= set(note["cited_required_fields"])
        for field in REQUIRED_SOURCE_NOTE_FIELDS:
            assert field in note
        for evidence_path in [note["gate_evidence_path"], *note["source_urls"]]:
            assert evidence_path.startswith("references/semantic/2023.1/"), evidence_path
            assert "references/semantic-builder-" not in evidence_path
            assert "2022.1" not in evidence_path
        assert NOTEBOOK_ID_2023 in json.dumps(note)
        assert "wwise-2022.1-docs" not in json.dumps(note)


def test_2023_missing_source_note_resource_fails_with_typed_code(tmp_path: Path) -> None:
    checker = SemanticSourceNoteChecker(tmp_path / "missing.json", notebook_id=NOTEBOOK_ID_2023)

    failure = assert_typed_failure(checker, BuilderFamily.QUERY, SemanticErrorCode.MISSING_SOURCE_NOTE)

    assert failure.details["version"] == "2023.1"


def test_2023_wrong_resource_notebook_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_2023_resource()
    data["notebook_id"] = "wwise-2022.1-docs"
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data), notebook_id=NOTEBOOK_ID_2023)

    failure = assert_typed_failure(checker, BuilderFamily.QUERY, SemanticErrorCode.SOURCE_NOTE_WRONG_NOTEBOOK)

    assert "expected wwise-2023.1-docs" in failure.message


def test_2023_wrong_note_notebook_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_2023_resource()
    data["notes"]["query"]["notebook_id"] = "wwise-2022.1-docs"
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data), notebook_id=NOTEBOOK_ID_2023)

    failure = assert_typed_failure(checker, BuilderFamily.QUERY, SemanticErrorCode.SOURCE_NOTE_WRONG_NOTEBOOK)

    assert failure.details["notebook_id"] == "wwise-2022.1-docs"


def test_2023_inconsistent_gate_evidence_metadata_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_2023_resource()
    data["notes"]["query"]["gate_evidence_path"] = "references/semantic/2023.1/query-gate.md"
    checker = SemanticSourceNoteChecker(write_artifact_resource(tmp_path, data), notebook_id=NOTEBOOK_ID_2023)

    failure = assert_typed_failure(checker, BuilderFamily.QUERY, SemanticErrorCode.SOURCE_NOTE_INCOMPLETE)

    assert "exactly one gate evidence metadata path" in failure.message


def test_2023_gate_evidence_metadata_does_not_require_packaged_markdown_file(tmp_path: Path) -> None:
    data = load_2023_resource()
    for note in data["notes"].values():
        note["gate_evidence_path"] = "references/semantic/2023.1/missing-gate.md"
    checker = SemanticSourceNoteChecker(write_artifact_resource(tmp_path, data), notebook_id=NOTEBOOK_ID_2023)

    status = require_source_note(checker, BuilderFamily.QUERY, version="2023.1")

    assert status.allowed is True


def test_2023_incomplete_note_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_2023_resource()
    del data["notes"]["query"]["return_shape"]
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data), notebook_id=NOTEBOOK_ID_2023)

    failure = assert_typed_failure(checker, BuilderFamily.QUERY, SemanticErrorCode.SOURCE_NOTE_INCOMPLETE)

    assert failure.details["missing_fields"] == ["return_shape"]


def test_2023_uncited_required_field_fails_with_typed_code(tmp_path: Path) -> None:
    data = load_2023_resource()
    note = data["notes"]["property-reference"]
    note["cited_required_fields"] = note["cited_required_fields"][:-1]
    checker = SemanticSourceNoteChecker(write_resource(tmp_path, data), notebook_id=NOTEBOOK_ID_2023)

    failure = assert_typed_failure(checker, BuilderFamily.PROPERTY_REFERENCE, SemanticErrorCode.SOURCE_NOTE_UNCITED_FIELD)

    assert failure.details["uncited_fields"] == [
        "ak.wwise.core.object.setAttenuationCurve: object, curveType, points, plus curve usage fields"
    ]


def test_2023_endpoint_inventory_mismatch_fails_closed(tmp_path: Path) -> None:
    data = load_2023_resource()
    data["notes"]["object-mutation"]["endpoints"] = ["ak.wwise.core.object.set"]

    with pytest.raises(SemanticValidationError) as exc:
        source_note_uri_inventory(write_resource(tmp_path, data))

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert exc.value.details["family"] == "object-mutation"


def test_2023_excluded_family_absence_fails_closed(tmp_path: Path) -> None:
    checker = SemanticSourceNoteChecker(notebook_id=NOTEBOOK_ID_2023)

    for family in ("profiler", "transport", "soundengine", "ui", "cli", "remote", "debug"):
        status = checker.check(family, version="2023.1")
        assert status.allowed is False
        assert status.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE

    data = load_2023_resource()
    mutated = copy.deepcopy(data)
    mutated["notes"]["transport"] = copy.deepcopy(mutated["notes"]["query"])
    mutated["notes"]["transport"]["family"] = "transport"
    with pytest.raises(SemanticValidationError) as exc:
        source_note_uri_inventory(write_resource(tmp_path, mutated))
    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE

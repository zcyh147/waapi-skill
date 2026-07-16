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
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


EXPECTED_INVENTORY = EXPECTED_SOURCE_NOTE_URI_INVENTORY
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"

EXCLUDED_URI_TOKENS = ("profiler", "transport", "soundengine", ".ui.", ".cli.", "remote", "debug")


def load_resource() -> dict[str, Any]:
    return json.loads(DEFAULT_SEMANTIC_SOURCE_NOTES.read_text(encoding="utf-8"))


def write_resource(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "source_notes.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_artifact_resource(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "waapi-skill" / "resources" / "semantic" / "2022.1" / "source_notes.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_grounded_source_notes_unlock_all_builder_families() -> None:
    checker = SemanticSourceNoteChecker()

    for family in BuilderFamily:
        status = require_source_note(checker, family)
        assert status.allowed is True
        assert status.family == family.value
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
    assert "notebook_id" not in data
    for family, note in data["notes"].items():
        assert family in EXPECTED_INVENTORY
        assert note["status"] in {"grounded", "fail-closed"}
        for field in REQUIRED_SOURCE_NOTE_FIELDS:
            assert field in note
        assert note["official_urls"]
        assert note["source_urls"]
        assert "notebook_id" not in note
        assert "gate_evidence_path" not in note


def test_source_notes_have_no_embedded_gate_success_claims() -> None:
    data = load_resource()

    for note in data["notes"].values():
        assert "gate_evidence" not in note
        assert "auth_result" not in note
        assert "list_result" not in note
        assert "query_result" not in note


def test_source_note_required_field_semantics_match_reflected_behavior() -> None:
    data = load_resource()

    object_mutation = data["notes"]["object-mutation"]
    assert "ak.wwise.core.undo.beginGroup: no required fields" in object_mutation["required_fields"]
    assert "ak.wwise.core.undo.endGroup: displayName" in object_mutation["required_fields"]
    assert "ak.wwise.core.undo.beginGroup: no required fields" in object_mutation["cited_required_fields"]
    assert "ak.wwise.core.undo.endGroup: displayName" in object_mutation["cited_required_fields"]

    property_reference = data["notes"]["property-reference"]
    assert "ak.wwise.core.object.isPropertyEnabled: object, platform, property" in property_reference["required_fields"]
    assert "ak.wwise.core.object.isPropertyEnabled: object, platform, property" in property_reference["cited_required_fields"]

    import_note = data["notes"]["import"]
    assert "ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile" in import_note["required_fields"]
    assert "importLocation" in import_note["optional_fields"]
    assert "ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile" in import_note["cited_required_fields"]

    soundbank = data["notes"]["soundbank"]
    assert "ak.wwise.core.soundbank.convertExternalSources: sources array; each source entry input, platform" in soundbank["required_fields"]
    assert "ak.wwise.core.soundbank.convertExternalSources: sources array; each source entry input, platform" in soundbank["cited_required_fields"]


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
        path = SKILL_ROOT / "references" / "semantic" / "2022.1" / f"semantic-builder-{name}.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "NotebookLM gate evidence" in text or name == "protocol"
        assert "wwise-2022.1-docs" in text


def test_source_note_uri_inventory_accepts_every_packaged_version_specific_endpoint_set() -> None:
    root = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "resources" / "semantic"

    counts = {
        version: sum(len(uris) for uris in source_note_uri_inventory(root / version / "source_notes.json").values())
        for version in SUPPORTED_WWISE_VERSION_KEYS
    }

    assert counts == {"2021.1": 37, "2022.1": 37, "2023.1": 37, "2024.1": 38, "2025.1": 38}


def test_every_packaged_source_note_has_a_versioned_runtime_mirror_inside_the_skill() -> None:
    semantic_root = SKILL_ROOT / "resources" / "semantic"

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        payload = json.loads((semantic_root / version / "source_notes.json").read_text(encoding="utf-8"))
        source_paths = [payload["protocol"]]
        for family, note in payload["notes"].items():
            source_paths.extend(note["source_urls"])
        for relative_path in source_paths:
            mirror = (
                SKILL_ROOT / "references" / "semantic" / version / Path(relative_path).name
                if relative_path.startswith("references/")
                else SKILL_ROOT / relative_path
            )
            assert mirror.is_file(), (version, relative_path, mirror)

from __future__ import annotations

import json
from pathlib import Path

import wwise_waapi.builders as builders  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.common import BuilderFamily  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import EXPECTED_SOURCE_NOTE_URI_INVENTORY, source_note_uri_inventory  # pyright: ignore[reportMissingImports]


ROOT = Path(__file__).resolve().parents[2]
SOURCE_NOTES = ROOT / "skills" / "waapi-skill" / "resources" / "semantic" / "2022.1" / "source_notes.json"
SKILL_MD = ROOT / "skills" / "waapi-skill" / "SKILL.md"

INCLUDED_FAMILIES = {
    "query",
    "object-mutation",
    "property-reference",
    "import",
    "soundbank",
    "switchcontainer",
}
EXCLUDED_FAMILY_TERMS = ("profiler", "transport", "soundengine", "UI", "CLI", "remote", "debug")
REQUIRED_PUBLIC_EXPORTS = {
    "build_object_get_query",
    "ObjectMutationBuilder",
    "PropertyReferenceBuilder",
    "MetadataBuilder",
    "ImportBuilder",
    "SoundBankBuilder",
    "SwitchContainerAssignmentBuilder",
    "SemanticPreview",
    "SemanticValidationError",
    "source_note_uri_inventory",
}


def test_builder_package_exports_stable_semantic_api_without_root_package_promotion() -> None:
    exported = set(getattr(builders, "__all__", ()))

    assert REQUIRED_PUBLIC_EXPORTS <= exported
    for name in REQUIRED_PUBLIC_EXPORTS:
        assert getattr(builders, name) is not None

    root_init = (ROOT / "skills" / "waapi-skill" / "wwise_waapi" / "__init__.py").read_text(encoding="utf-8")
    assert "build_object_get_query" not in root_init
    assert "ObjectMutationBuilder" not in root_init


def test_source_note_inventory_contains_only_planned_p0_p1_p2_families() -> None:
    inventory = source_note_uri_inventory(SOURCE_NOTES)

    assert set(inventory) == INCLUDED_FAMILIES
    assert {family.value for family in BuilderFamily} == INCLUDED_FAMILIES
    assert inventory == EXPECTED_SOURCE_NOTE_URI_INVENTORY
    for family, endpoints in inventory.items():
        assert endpoints, family
        assert len(endpoints) == len(set(endpoints))


def test_source_notes_are_grounded_and_exclude_out_of_scope_families() -> None:
    payload = json.loads(SOURCE_NOTES.read_text(encoding="utf-8"))
    notes = payload["notes"]

    for family in INCLUDED_FAMILIES:
        note = notes[family]
        assert note["status"] == "grounded"
        assert "notebook_id" not in note
        assert "gate_evidence_path" not in note
        assert note["endpoints"] == list(EXPECTED_SOURCE_NOTE_URI_INVENTORY[family])
        assert set(note["required_fields"]) <= set(note["cited_required_fields"])

    inventory_text = json.dumps(notes, sort_keys=True)
    for term in EXCLUDED_FAMILY_TERMS:
        assert term.lower() in inventory_text.lower()
    for endpoints in EXPECTED_SOURCE_NOTE_URI_INVENTORY.values():
        for uri in endpoints:
            assert not any(excluded.lower() in uri.lower() for excluded in EXCLUDED_FAMILY_TERMS)


def test_source_note_required_field_strings_match_reflected_behavior() -> None:
    payload = json.loads(SOURCE_NOTES.read_text(encoding="utf-8"))
    notes = payload["notes"]

    assert "ak.wwise.core.undo.beginGroup: no required fields" in notes["object-mutation"]["required_fields"]
    assert "ak.wwise.core.undo.endGroup: displayName" in notes["object-mutation"]["required_fields"]
    assert "ak.wwise.core.object.isPropertyEnabled: object, platform, property" in notes["property-reference"]["required_fields"]
    assert "ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile" in notes["import"]["required_fields"]
    assert "importLocation" in notes["import"]["optional_fields"]
    assert "ak.wwise.core.soundbank.convertExternalSources: sources array; each source entry input, platform" in notes["soundbank"]["required_fields"]


def test_skill_docs_prefer_builders_without_claiming_live_execution() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "prefer the semantic planner before hand-writing dispatcher payloads" in text
    assert "source-grounded builders, previews, readback plans, and dispatcher requests" in text
    assert "it does not open Wwise, subscribe to topics, or dispatch live calls by default" in text
    assert "raw `WwiseDispatcher` contract remains the explicit escape hatch" in text
    assert "Packaged semantic builder source-note families" not in text
    for family in INCLUDED_FAMILIES:
        assert f"`{family}`" not in text
    forbidden_claims = (
        "builders execute live Wwise by default",
        "semantic builders dispatch live calls by default",
        "builders prove live execution",
    )
    for claim in forbidden_claims:
        assert claim not in text

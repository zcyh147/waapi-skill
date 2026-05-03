from __future__ import annotations

import json
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.deferred_registry import (  # pyright: ignore[reportMissingImports]
    ApiClassifier,
    DeferredEntry,
    DeferredRegistry,
    REQUIRED_COVERAGE_FIELDS,
    REQUIRED_DEFERRED_FIELDS,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
DEFERRED_RESOURCE = SKILL_ROOT / "resources" / "deferred" / "2022.1.json"
MANIFEST_DIR = SKILL_ROOT / "resources" / "manifest" / "2022.1"


def test_default_deferred_registry_covers_every_reflected_uri_with_inventory_only_status() -> None:
    registry = DeferredRegistry.load_default("2022.1")
    functions = json.loads((MANIFEST_DIR / "functions.json").read_text(encoding="utf-8"))["functions"]
    topics = json.loads((MANIFEST_DIR / "topics.json").read_text(encoding="utf-8"))["topics"]
    reflected_uris = {item["uri"] for item in functions + topics}

    assert set(registry.entries) == reflected_uris
    assert len(registry.entries) == 144
    assert {entry.inventory_coverage for entry in registry.entries.values()} == {"reflected-schema-ok"}
    assert {entry.behavioral_coverage for entry in registry.entries.values()} == {"deferred"}


def test_deferred_resource_declares_required_schema_and_coverage_model() -> None:
    payload = json.loads(DEFERRED_RESOURCE.read_text(encoding="utf-8"))

    assert payload["metadata"]["required_fields"] == list(REQUIRED_DEFERRED_FIELDS + REQUIRED_COVERAGE_FIELDS)
    assert "inventory_coverage" in payload["metadata"]["coverage_model"]
    assert "behavioral_coverage" in payload["metadata"]["coverage_model"]
    assert "not behavioral coverage" in payload["metadata"]["coverage_model"]["behavioral_coverage"]


def test_invalid_deferred_entry_reports_missing_evidence_and_blocking_condition() -> None:
    valid = _valid_entry_payload("ak.wwise.core.getInfo")
    del valid["evidence_source"]
    del valid["blocking_condition"]

    with pytest.raises(ValueError, match="evidence_source, blocking_condition"):
        DeferredEntry.from_mapping(valid)


def test_deferred_entry_rejects_behavioral_coverage_claims() -> None:
    payload = _valid_entry_payload("ak.wwise.core.getInfo")
    payload["behavioral_coverage"] = "tested"

    with pytest.raises(ValueError, match="behavioral_coverage='deferred'"):
        DeferredEntry.from_mapping(payload)


def test_classifier_uses_uri_namespace_not_freeform_labels() -> None:
    classifier = ApiClassifier()

    assert classifier.classify("ak.soundengine.postEvent").category == "soundengine"
    assert classifier.classify("ak.wwise.core.profiler.captureLog.itemAdded", "topic").category == "core.profiler.captureLog"
    assert classifier.classify("ak.wwise.ui.commands.execute").category == "ui.commands"
    assert classifier.classify("ak.wwise.debug.testCrash").risk_level == "high"
    with pytest.raises(ValueError, match="ak namespace"):
        classifier.classify("wwise.core.getInfo")


def test_legacy_record_still_creates_valid_deferred_entry() -> None:
    registry = DeferredRegistry()

    registry.record("ak.test.missing", "not implemented yet")

    entry = registry.require("ak.test.missing")
    assert entry.behavioral_coverage == "deferred"
    assert registry.missing() == ["ak.test.missing"]


def _valid_entry_payload(uri: str, item_type: str = "function") -> dict[str, str]:
    classification = ApiClassifier().classify(uri, item_type)
    return {
        "behavioral_coverage": "deferred",
        "blocking_condition": "Requires live fixture before behavioral execution can be asserted.",
        "category": classification.category,
        "date": "2026-04-30",
        "evidence_source": "resources/manifest/2022.1/functions.json + resources/manifest/2022.1/schemas.json",
        "inventory_coverage": "reflected-schema-ok",
        "item_type": item_type,
        "owner_follow_up": "Task 7 behavioral coverage implementation.",
        "reason": "Inventory/schema evidence exists but behavioral coverage is deferred.",
        "review_trigger": "When behavioral tests or manifest inventory change.",
        "risk_level": classification.risk_level,
        "substitute_test": "Inventory/schema validation only; not behavioral coverage.",
        "uri": uri,
        "version": "2022.1",
    }

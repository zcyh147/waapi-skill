from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.api_coverage import ApiCoverageBuilder  # pyright: ignore[reportMissingImports]
from wwise_waapi.deferred_registry import DeferredRegistry  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT
MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
COVERAGE_RESOURCE = SKILL_ROOT / "resources" / "coverage" / "2022.1" / "api-coverage.json"


def test_every_reflected_api_is_implemented_or_deferred_with_evidence() -> None:
    payload = _coverage_payload()
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    reflected = {entry["uri"] for entry in manifest["functions"] + manifest["topics"]}
    coverage = {entry["uri"] for entry in payload["coverage"]}

    assert coverage == reflected
    for entry in payload["coverage"]:
        assert entry["test_status"] in {"fake-route-tested", "deferred-with-substitute-test"}
        assert entry["test_status"] == "deferred-with-substitute-test" or entry["deferred"]["status"] is False
        assert entry["test_status"] != "deferred-with-substitute-test" or entry["deferred"]["status"] is True


def test_every_deferred_api_has_registry_evidence() -> None:
    registry = DeferredRegistry.load_default("2022.1")
    for entry in _coverage_payload()["coverage"]:
        if entry["deferred"]["status"] is False:
            continue
        deferred = registry.require(entry["uri"])
        assert deferred.item_type == entry["item_type"]
        assert deferred.category == entry["category"]
        assert deferred.risk_level == entry["risk_level"]
        assert deferred.inventory_coverage == "reflected-schema-ok"
        assert deferred.behavioral_coverage == "deferred"
        assert entry["deferred"]["evidence_source"] == deferred.evidence_source
        assert "not behavioral coverage" in deferred.substitute_test


def test_missing_artificial_api_fails_until_implemented_or_deferred_with_evidence() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    mutated = dict(manifest)
    mutated["topics"] = [*manifest["topics"], {"uri": "ak.wwise.ui.artificialTopic"}]
    store = ManifestStore()
    store.record("2022.1", mutated)

    with pytest.raises(KeyError, match="ak.wwise.ui.artificialTopic"):
        ApiCoverageBuilder(manifest_store=store).build("2022.1")


def test_resource_generation_is_byte_stable() -> None:
    generated = ApiCoverageBuilder().build("2022.1").as_dict()
    on_disk = _coverage_payload()

    assert generated == on_disk


def _coverage_payload() -> dict[str, Any]:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))

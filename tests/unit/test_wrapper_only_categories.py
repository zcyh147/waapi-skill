from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.api_coverage_audit import (  # pyright: ignore[reportMissingImports]
    ApiCoverageAuditor,
    Phase2CoverageStatusRecord,
)
from wwise_waapi.category_policy import (  # pyright: ignore[reportMissingImports]
    DEBUG_UNSAFE_LIVE_URIS,
    SKIPPED_APPROVED_CATEGORIES,
    WRAPPER_ONLY_CATEGORIES,
)
from wwise_waapi.deferred_registry import DeferredRegistry  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "wwise-waapi"
COVERAGE_ROOT = SKILL_ROOT / "resources" / "capabilities" / "2022.1"
MATRIX_RESOURCE = COVERAGE_ROOT / "live-coverage-matrix.json"
API_COVERAGE_RESOURCE = COVERAGE_ROOT / "api-coverage.json"
POLICY_RESOURCE = COVERAGE_ROOT / "wrapper-only-category-policy.json"


class FakeWaapiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((uri, args, options))
        return {"uri": uri, "called": True}


def test_policy_resource_encodes_user_category_decisions() -> None:
    policy = _policy_payload()
    categories = {entry["category"]: entry for entry in policy["categories"]}

    assert set(categories) == WRAPPER_ONLY_CATEGORIES | SKIPPED_APPROVED_CATEGORIES
    assert {category for category, entry in categories.items() if entry["target_status"] == "wrapper-only"} == WRAPPER_ONLY_CATEGORIES
    assert {category for category, entry in categories.items() if entry["target_status"] == "skipped-approved"} == SKIPPED_APPROVED_CATEGORIES
    assert policy["summary"] == {
        "category_count": 6,
        "entry_count": 32,
        "skipped_approved_count": 21,
        "wrapper_only_count": 11,
    }

    for entry in categories.values():
        assert entry["count_as_live_behavior"] is False
        assert entry["user_approved_rationale"].startswith("User guidance")
        assert entry["risk_explanation"]
        assert entry["future_review_trigger"].startswith("Revisit")
        assert "UNSUPPORTED_LIVE_BEHAVIOR" in entry["unsupported_live_diagnostic"]
        assert entry["user_guidance_reference"] == ".sisyphus/plans/wwise-waapi-live-sandbox-coverage.md:36-42"


def test_matrix_exempt_entries_have_policy_rationale_and_do_not_count_live() -> None:
    policy_by_uri = _policy_by_uri()
    exempt_categories = WRAPPER_ONLY_CATEGORIES | SKIPPED_APPROVED_CATEGORIES

    for entry in _matrix_entries():
        if entry["category"] not in exempt_categories:
            continue
        policy = policy_by_uri[entry["uri"]]
        assert entry["target_status"] == policy["target_status"]
        assert entry["counts_as_live_behavior"] is False
        assert entry["allowed_test_tier"] in {"wrapper-unit", "skipped-policy"}
        assert not entry["allowed_test_tier"].startswith("live")
        assert entry["fixture_prerequisites"] == []
        assert entry["user_approved_rationale"] == policy["user_approved_rationale"]
        assert entry["risk_explanation"] == policy["risk_explanation"]
        assert entry["future_review_trigger"] == policy["future_review_trigger"]
        assert entry["achieved_status"] != "live-tested"


def test_wrapper_entries_retain_schema_mapping_and_route_diagnostics() -> None:
    coverage_by_uri = _coverage_by_uri()

    for entry in _policy_payload()["entries"]:
        coverage = coverage_by_uri[entry["uri"]]
        assert entry["schema_status"] == coverage["schema_status"]
        assert entry["schema_mapping"] == coverage["schema_mapping"]
        assert entry["dispatcher_route"] == coverage["route"]
        assert entry["allowed_default_diagnostic"] == "schema-mapping-and-dispatcher-route-validation"
        assert entry["live_behavior"] == "unsupported-by-user-approved-phase2-policy"
        assert entry["count_as_live_behavior"] is False
        assert entry["schema_mapping"]["manifest_uri"].endswith(f"#{entry['uri']}")
        assert entry["dispatcher_route"]["dispatcher"] == "WwiseDispatcher.dispatch"
        if entry["item_type"] == "topic":
            assert entry["dispatcher_route"]["target"] == "SubscriptionManager.wait_for_event"
        else:
            assert entry["dispatcher_route"]["target"] == "WwiseDispatcher.dispatch"


def test_phase2_audit_counts_policy_entries_as_inventory_only() -> None:
    records = [
        Phase2CoverageStatusRecord(
            uri=entry["uri"],
            version=entry["version"],
            category=entry["category"],
            inventory_coverage="reflected-schema-ok",
            achieved_status=entry["target_status"],
            user_approved_rationale=entry["user_approved_rationale"],
            future_review_trigger=entry["future_review_trigger"],
        )
        for entry in _policy_payload()["entries"]
    ]
    manifest = {
        "functions": [{"uri": entry["uri"]} for entry in _policy_payload()["entries"] if entry["item_type"] == "function"],
        "topics": [{"uri": entry["uri"]} for entry in _policy_payload()["entries"] if entry["item_type"] == "topic"],
    }

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=records)

    assert result.passed is True
    assert result.reflected_count == 32
    assert result.phase2_status_covered_count == 32
    assert result.behavioral_covered_count == 0
    assert result.live_behavioral_covered_count == 0
    assert result.status_counts == {"skipped-approved": 21, "wrapper-only": 11}


def test_exempt_live_behavior_paths_return_unsupported_diagnostics_without_client_call() -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=_policy_manifest_store())

    for uri in (
        "ak.wwise.cli.dumpObjects",
        "ak.wwise.core.remote.getAvailableConsoles",
        "ak.wwise.debug.enableAutomationMode",
        "ak.wwise.ui.getSelectedObjects",
        "ak.wwise.ui.commands.getCommands",
        "ak.wwise.ui.project.open",
    ):
        result = dispatcher.dispatch(uri, live_behavior=True)
        assert result["ok"] is False, uri
        assert result["error_code"] == "UNSUPPORTED_LIVE_BEHAVIOR", uri
        assert result["category"] in WRAPPER_ONLY_CATEGORIES | SKIPPED_APPROVED_CATEGORIES
        assert "wrappers may validate schema/route metadata" in result["message"]

    assert client.calls == []


def test_debug_unsafe_routes_refuse_default_execution_but_keep_dry_run_diagnostics() -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=_policy_manifest_store())

    for uri in sorted(DEBUG_UNSAFE_LIVE_URIS):
        default_result = dispatcher.dispatch(uri)
        dry_run_result = dispatcher.dispatch(uri, dry_run=True)

        assert default_result["ok"] is False, uri
        assert default_result["error_code"] == "UNSUPPORTED_LIVE_BEHAVIOR", uri
        assert default_result["category"] == "debug", uri
        assert "assert/crash" in default_result["message"], uri
        assert dry_run_result["ok"] is True, uri
        assert dry_run_result["result"]["dry_run"] is True, uri
        assert dry_run_result["result"]["would_dispatch"] == "function", uri

    assert client.calls == []


def test_live_suites_do_not_reference_debug_crash_or_assert_routes() -> None:
    live_text = "\n".join(path.read_text(encoding="utf-8") for path in (REPO_ROOT / "tests" / "live").glob("*.py"))

    assert "ak.wwise.debug.testCrash" not in live_text
    assert "ak.wwise.debug.testAssert" not in live_text
    assert "ak.wwise.debug.enableAsserts" not in live_text


def _policy_payload() -> dict[str, Any]:
    return json.loads(POLICY_RESOURCE.read_text(encoding="utf-8"))


def _matrix_entries() -> list[Mapping[str, Any]]:
    return json.loads(MATRIX_RESOURCE.read_text(encoding="utf-8"))["matrix"]


def _coverage_by_uri() -> dict[str, Mapping[str, Any]]:
    return {entry["uri"]: entry for entry in json.loads(API_COVERAGE_RESOURCE.read_text(encoding="utf-8"))["coverage"]}


def _policy_by_uri() -> dict[str, Mapping[str, Any]]:
    return {entry["uri"]: entry for entry in _policy_payload()["entries"]}


def _policy_manifest_store() -> ManifestStore:
    entries = _policy_payload()["entries"]
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "functions": [{"uri": entry["uri"]} for entry in entries if entry["item_type"] == "function"],
            "topics": [{"uri": entry["uri"]} for entry in entries if entry["item_type"] == "topic"],
        },
    )
    return store

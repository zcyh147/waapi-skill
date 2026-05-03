from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
COVERAGE_RESOURCE = SKILL_ROOT / "resources" / "capabilities" / "2022.1" / "api-coverage.json"


class FakeWaapiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((uri, args, options))
        return {"fake": True, "uri": uri}


class FakeSubscriptionManager:
    def __init__(self) -> None:
        self.waits: list[str] = []

    def wait_for_event(self, topic: str, timeout: float = 5.0, options: dict[str, Any] | None = None, queue_size: int = 1) -> Any:
        self.waits.append(topic)
        raise AssertionError("Deferred topic routes must not be exercised by fake-route coverage")


def test_every_non_deferred_api_routes_with_fake_runtime() -> None:
    payload = _coverage_payload()
    non_deferred = [entry for entry in payload["coverage"] if entry["deferred"]["status"] is False]
    client = FakeWaapiClient()
    subscriptions = FakeSubscriptionManager()
    dispatcher = WwiseDispatcher(
        client=client,
        manifest_store=ManifestStore(root=MANIFEST_ROOT),
        subscription_manager=subscriptions,  # type: ignore[arg-type]
    )

    assert non_deferred, "No fake-route APIs were generated"
    for entry in non_deferred:
        result = dispatcher.dispatch(entry["uri"], timeout=0.25)
        assert result["ok"] is True, entry["uri"]
        assert result["api"] == entry["uri"]
        assert result["item_type"] == "function"
        assert result["category"] == entry["category"]
        assert result["risk_level"] == entry["risk_level"]

    assert [call[0] for call in client.calls] == [entry["uri"] for entry in non_deferred]
    assert subscriptions.waits == []


def test_deferred_routes_are_explicitly_substitute_or_registry_guarded() -> None:
    for entry in _coverage_payload()["coverage"]:
        if entry["deferred"]["status"] is False:
            continue
        assert entry["route"]["deferred_registry_required"] is True
        assert entry["route"]["route_test"] == "tests/unit/test_no_silent_skips.py::test_every_deferred_api_has_registry_evidence"
        assert entry["behavioral_evidence"]["coverage"] == "substitute-test"


def test_coverage_routes_match_manifest_item_types() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    expected_types = {entry["uri"]: "function" for entry in manifest["functions"]}
    expected_types.update({entry["uri"]: "topic" for entry in manifest["topics"]})

    for entry in _coverage_payload()["coverage"]:
        assert entry["item_type"] == expected_types[entry["uri"]]
        if entry["item_type"] == "topic":
            assert entry["route"]["target"] == "SubscriptionManager.wait_for_event"
            assert entry["route"]["mode"] == "bounded-topic-wait"
        else:
            assert entry["route"]["target"] == "WwiseDispatcher.dispatch"
            assert entry["route"]["mode"] == "function-call"


def _coverage_payload() -> dict[str, Any]:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))

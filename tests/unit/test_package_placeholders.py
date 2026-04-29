from __future__ import annotations

from wwise_waapi import DeferredRegistry, HeadlessLifecycle, ManifestStore, SubscriptionManager, WwiseDispatcher  # pyright: ignore[reportMissingImports]


def test_placeholder_registry_and_dispatcher_methods() -> None:
    deferred = DeferredRegistry()
    deferred.record("ak.test.missing", "not implemented yet")
    assert deferred.missing() == ["ak.test.missing"]

    manifest = ManifestStore()
    manifest.record("2022.1", {"functions": []})
    assert manifest.load("2022.1") == {"functions": []}

    subscriptions = SubscriptionManager()
    subscriptions.subscribe("ak.test.topic")
    subscriptions.unsubscribe("ak.test.topic")
    subscriptions.clear()
    assert subscriptions.active_topics == set()


def test_headless_lifecycle_defaults_are_safe_before_launch() -> None:
    lifecycle = HeadlessLifecycle()
    assert lifecycle.console_path is None
    assert lifecycle.port is None
    lifecycle.shutdown()


def test_dispatcher_returns_structured_error_before_live_client_exists() -> None:
    result = WwiseDispatcher().dispatch("ak.test.command")

    assert result["ok"] is False
    assert result["error_code"] == "API_NOT_FOUND"
    assert result["api"] == "ak.test.command"

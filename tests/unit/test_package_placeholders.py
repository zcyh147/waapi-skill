from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

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


@pytest.mark.parametrize(
    "method_name",
    ["launch", "wait_ready", "shutdown"],
)
def test_headless_methods_raise_not_implemented(method_name: str) -> None:
    lifecycle = HeadlessLifecycle()
    with pytest.raises(NotImplementedError):
        getattr(lifecycle, method_name)()


def test_dispatcher_placeholder_raises() -> None:
    with pytest.raises(NotImplementedError):
        WwiseDispatcher().dispatch("ak.test.command")

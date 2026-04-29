from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.subscriptions import (  # pyright: ignore[reportMissingImports]
    DEFAULT_CALLBACK_EXECUTOR,
    BackgroundSubscription,
    SubscriptionCallbackError,
    SubscriptionEvent,
    SubscriptionManager,
    SubscriptionTimeout,
    SubscriptionUnavailable,
    _put_bounded,
)


class FakeEventHandler:
    def __init__(self, client: "FakeSubscriptionClient", topic: str, callback: Callable[..., None] | None) -> None:
        self.client = client
        self.topic = topic
        self.callback = callback
        self.unsubscribe_calls = 0

    def unsubscribe(self) -> bool:
        self.unsubscribe_calls += 1
        return self.client.unsubscribe(self)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        self.client.in_waapi_callback = True
        try:
            if self.callback is not None:
                self.callback(*args, **kwargs)
        finally:
            self.client.in_waapi_callback = False


class FakeSubscriptionClient:
    def __init__(self, return_none: bool = False) -> None:
        self.return_none = return_none
        self.handlers: list[FakeEventHandler] = []
        self.unsubscribe_calls = 0
        self.call_while_in_callback = 0
        self.in_waapi_callback = False

    def subscribe(self, uri: str, callback_or_handler: Callable[..., None] | None = None, *args: Any, **kwargs: Any) -> FakeEventHandler | None:
        if self.return_none:
            return None
        handler = FakeEventHandler(self, uri, callback_or_handler)
        self.handlers.append(handler)
        return handler

    def unsubscribe(self, event_handler: FakeEventHandler) -> bool:
        self.unsubscribe_calls += 1
        if event_handler in self.handlers:
            self.handlers.remove(event_handler)
        return True

    def call(self, uri: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self.in_waapi_callback:
            self.call_while_in_callback += 1
        return {"uri": uri}


def non_daemon_thread_names() -> set[str]:
    return {thread.name for thread in threading.enumerate() if not thread.daemon and thread is not threading.main_thread()}


def test_default_executor_guidance_matches_waapi_sequential_executor() -> None:
    assert DEFAULT_CALLBACK_EXECUTOR == "waapi.SequentialThreadExecutor"


def test_subscribe_success_returns_idempotent_cleanup_handle() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    handle = manager.subscribe("ak.wwise.core.object.created")

    assert handle is not None
    assert manager.active_topics == {"ak.wwise.core.object.created"}
    assert handle.unsubscribe() is True
    assert handle.unsubscribe() is False
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_subscribe_none_result_is_rejected() -> None:
    manager = SubscriptionManager(FakeSubscriptionClient(return_none=True))

    with pytest.raises(SubscriptionUnavailable, match="did not create"):
        manager.subscribe("ak.topic.none")

    assert manager.active_topics == set()


def test_wait_for_event_receives_event_and_unsubscribes_once() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        client.handlers[0].emit({"id": 1}, sequence=2)

    publisher = threading.Thread(target=publish)
    publisher.start()
    event = manager.wait_for_event("ak.wwise.core.object.created", timeout=0.5)
    publisher.join(0.5)

    assert event.topic == "ak.wwise.core.object.created"
    assert event.payload == {"id": 1}
    assert event.kwargs == {"sequence": 2}
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_wait_for_event_timeout_unsubscribes_once() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    with pytest.raises(SubscriptionTimeout, match="Timed out"):
        manager.wait_for_event("ak.never", timeout=0.01)

    assert client.unsubscribe_calls == 1
    assert len(client.handlers) == 0
    assert manager.active_topics == set()


def test_wait_for_event_callback_only_hands_off_to_queue_not_client() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        client.handlers[0].emit({"safe": True})

    publisher = threading.Thread(target=publish)
    publisher.start()
    event = manager.wait_for_event("ak.safe", timeout=0.5)
    publisher.join(0.5)

    assert event.payload == {"safe": True}
    assert client.call_while_in_callback == 0


def test_background_listener_receives_event_and_cancel_cleans_up() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)
    received: list[dict[str, Any]] = []

    listener = manager.listen("ak.background", callback=lambda event: received.append(event.payload), join_timeout=0.5)
    assert isinstance(listener, BackgroundSubscription)
    assert listener.alive is True

    client.handlers[0].emit({"ok": True})
    deadline = time.monotonic() + 0.5
    while not received and time.monotonic() < deadline:
        time.sleep(0.001)

    assert received == [{"ok": True}]
    assert listener.cancel() is True
    assert listener.cancel() is False
    assert listener.alive is False
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_background_listener_records_callback_exception_and_still_cancels() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def broken_callback(event: Any) -> None:
        raise ValueError("boom")

    listener = manager.listen("ak.background.error", callback=broken_callback, join_timeout=0.5)
    client.handlers[0].emit({"bad": True})

    deadline = time.monotonic() + 0.5
    while not listener.callback_errors and time.monotonic() < deadline:
        time.sleep(0.001)

    with pytest.raises(SubscriptionCallbackError, match="boom"):
        listener.raise_if_callback_failed()
    assert listener.cancel() is True
    assert listener.alive is False
    assert client.unsubscribe_calls == 1


def test_context_manager_cancels_background_listener() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    with manager.listen("ak.context", join_timeout=0.5) as listener:
        assert listener.alive is True

    assert listener.alive is False
    assert client.unsubscribe_calls == 1


def test_subscription_tests_leave_no_extra_non_daemon_threads() -> None:
    before = non_daemon_thread_names()
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)
    listener = manager.listen("ak.thread.cleanup", join_timeout=0.5)
    assert listener.alive is True

    listener.cancel()
    deadline = time.monotonic() + 0.5
    while non_daemon_thread_names() != before and time.monotonic() < deadline:
        time.sleep(0.001)

    assert non_daemon_thread_names() == before


def test_bounded_queue_drops_oldest_event_when_full() -> None:
    event_queue: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=1)

    _put_bounded(event_queue, SubscriptionEvent(topic="ak.overflow", args=("old",)))
    _put_bounded(event_queue, SubscriptionEvent(topic="ak.overflow", args=("new",)))

    assert event_queue.get_nowait().payload == "new"


def test_background_listener_caps_callback_errors() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def broken_callback(event: Any) -> None:
        raise ValueError(f"boom-{event.payload}")

    listener = manager.listen("ak.background.error.cap", callback=broken_callback, join_timeout=0.5)
    client.handlers[0].emit("one")
    client.handlers[0].emit("two")

    deadline = time.monotonic() + 0.5
    while len(listener.callback_errors) < 1 and time.monotonic() < deadline:
        time.sleep(0.001)

    assert len(listener.callback_errors) == 1
    assert listener.cancel() is True


def test_clientless_registry_contract_is_preserved() -> None:
    manager = SubscriptionManager()

    assert manager.subscribe("ak.registry") is None
    manager.unsubscribe("ak.registry")
    manager.clear()

    assert manager.active_topics == set()

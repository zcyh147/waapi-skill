from __future__ import annotations

import json
import math
import os
import queue
import stat
import threading
import time
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.subscriptions as subscriptions_module
from wwise_waapi.subscriptions import (  # pyright: ignore[reportMissingImports]
    DEFAULT_CALLBACK_EXECUTOR,
    MAX_WAIT_EVENT_COUNT,
    BackgroundSubscription,
    SubscriptionCallbackError,
    SubscriptionCleanupError,
    SubscriptionAcknowledgementError,
    SubscriptionEvent,
    SubscriptionManager,
    SubscriptionStreamIngressError,
    SubscriptionStreamOverflow,
    SubscriptionTimeout,
    SubscriptionUnavailable,
    SUBSCRIPTION_ACK_CONTRACT,
    SUBSCRIPTION_ACK_ENV_NAMES,
    SUBSCRIPTION_ACK_NONCE_ENV,
    SUBSCRIPTION_ACK_PATH_ENV,
    SUBSCRIPTION_ACK_STEP_ENV,
    SUBSCRIPTION_ACK_TOPIC_ENV,
    TopicEventStream,
    _put_bounded,
    payload_matches,
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


def _configure_subscription_ack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    evidence_dir,
    target,
    topic: str = "ak.wwise.core.soundbank.generated",
) -> None:
    monkeypatch.setenv("WWISE_EVIDENCE_DIR", str(evidence_dir))
    monkeypatch.setenv(SUBSCRIPTION_ACK_PATH_ENV, str(target))
    monkeypatch.setenv(SUBSCRIPTION_ACK_NONCE_ENV, "n" * 43)
    monkeypatch.setenv(SUBSCRIPTION_ACK_TOPIC_ENV, topic)
    monkeypatch.setenv(SUBSCRIPTION_ACK_STEP_ENV, "soundbank.generated.wait")


def test_subscription_ack_is_atomically_published_only_after_subscribe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    target = evidence / "subscription-ack-test.json"
    _configure_subscription_ack(
        monkeypatch,
        evidence_dir=evidence,
        target=target,
    )
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    handle = manager.subscribe("ak.wwise.core.soundbank.generated")

    assert handle is not None
    assert len(client.handlers) == 1
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {
        "contract": SUBSCRIPTION_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": "ak.wwise.core.soundbank.generated",
        "nonce": "n" * 43,
        "runner_parent_process_id": payload["runner_parent_process_id"],
        "gateway_process_id": payload["gateway_process_id"],
        "subscribed_at_unix_ns": payload["subscribed_at_unix_ns"],
        "subscribed_at_monotonic_ns": payload["subscribed_at_monotonic_ns"],
    }
    assert payload["runner_parent_process_id"] == os.getppid()
    assert payload["gateway_process_id"] == os.getpid()
    assert payload["subscribed_at_unix_ns"] > 0
    assert payload["subscribed_at_monotonic_ns"] > 0
    encoded = target.read_bytes()
    assert encoded.endswith(b"\n")
    assert b"\r\n" not in encoded
    metadata = target.stat()
    assert metadata.st_nlink == 1
    if os.name == "posix":
        assert stat.S_IMODE(metadata.st_mode) & 0o077 == 0
    assert not list(evidence.glob(".subscription-ack-test.json.*.tmp"))
    handle.unsubscribe()


@pytest.mark.parametrize("failure", ("wrong_topic", "partial", "preexisting", "outside"))
def test_subscription_ack_failures_unsubscribe_and_publish_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    failure: str,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    target = evidence / "subscription-ack-test.json"
    _configure_subscription_ack(
        monkeypatch,
        evidence_dir=evidence,
        target=target,
    )
    if failure == "wrong_topic":
        monkeypatch.setenv(SUBSCRIPTION_ACK_TOPIC_ENV, "ak.wwise.core.object.created")
    elif failure == "partial":
        monkeypatch.delenv(SUBSCRIPTION_ACK_NONCE_ENV)
    elif failure == "preexisting":
        target.write_text("forged\n", encoding="utf-8")
    else:
        other = tmp_path / "other"
        other.mkdir()
        target = other / "subscription-ack-test.json"
        monkeypatch.setenv(SUBSCRIPTION_ACK_PATH_ENV, str(target))
    client = FakeSubscriptionClient()

    with pytest.raises(SubscriptionAcknowledgementError):
        SubscriptionManager(client).subscribe(
            "ak.wwise.core.soundbank.generated"
        )

    assert client.unsubscribe_calls == 1
    assert client.handlers == []
    if failure != "preexisting":
        assert not target.exists()


def test_duplicate_subscription_ack_is_rejected_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    target = evidence / "subscription-ack-test.json"
    _configure_subscription_ack(
        monkeypatch,
        evidence_dir=evidence,
        target=target,
    )
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)
    first = manager.subscribe("ak.wwise.core.soundbank.generated")
    original = target.read_bytes()

    with pytest.raises(SubscriptionAcknowledgementError):
        manager.subscribe("ak.wwise.core.soundbank.generated")

    assert target.read_bytes() == original
    assert client.unsubscribe_calls == 1
    assert first is not None
    first.unsubscribe()


def test_no_subscription_ack_environment_preserves_normal_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in SUBSCRIPTION_ACK_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    client = FakeSubscriptionClient()
    handle = SubscriptionManager(client).subscribe("ak.test.topic")
    assert handle is not None
    assert len(client.handlers) == 1
    handle.unsubscribe()


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


def test_unsubscribe_false_keeps_handle_and_topic_active_for_retry() -> None:
    class RetryCleanupClient(FakeSubscriptionClient):
        def __init__(self) -> None:
            super().__init__()
            self.results = [False, True]

        def unsubscribe(self, event_handler: FakeEventHandler) -> bool:
            self.unsubscribe_calls += 1
            result = self.results.pop(0)
            if result and event_handler in self.handlers:
                self.handlers.remove(event_handler)
            return result

    client = RetryCleanupClient()
    manager = SubscriptionManager(client)
    handle = manager.subscribe("ak.retry.cleanup")
    assert handle is not None

    assert handle.unsubscribe() is False
    assert handle.unsubscribed is False
    assert manager.active_topics == {"ak.retry.cleanup"}
    assert client.handlers == [handle.handler]

    assert handle.unsubscribe() is True
    assert handle.unsubscribed is True
    assert manager.active_topics == set()
    assert client.handlers == []


def test_ack_failure_reports_false_cleanup_without_claiming_unsubscribe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FalseCleanupClient(FakeSubscriptionClient):
        def unsubscribe(self, event_handler: FakeEventHandler) -> bool:
            del event_handler
            self.unsubscribe_calls += 1
            return False

    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    target = evidence / "subscription-ack-test.json"
    _configure_subscription_ack(
        monkeypatch,
        evidence_dir=evidence,
        target=target,
        topic="ak.wrong.topic",
    )
    client = FalseCleanupClient()
    manager = SubscriptionManager(client)

    with pytest.raises(
        SubscriptionAcknowledgementError,
        match="cleanup returned false and remains active",
    ):
        manager.subscribe("ak.actual.topic")

    assert client.unsubscribe_calls == 1
    assert len(client.handlers) == 1
    assert manager.active_topics == {"ak.actual.topic"}


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


def test_wait_for_event_accepts_unbounded_timeout_without_passing_infinity_to_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)
    queue_timeouts: list[float | None] = []
    original_get = queue.Queue.get

    def guarded_get(
        instance: queue.Queue[Any],
        block: bool = True,
        timeout: float | None = None,
    ) -> Any:
        queue_timeouts.append(timeout)
        assert timeout is None or math.isfinite(timeout)
        return original_get(instance, block=block, timeout=timeout)

    monkeypatch.setattr(queue.Queue, "get", guarded_get)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        client.handlers[0].emit({"id": 1})

    publisher = threading.Thread(target=publish)
    publisher.start()
    event = manager.wait_for_event("ak.unbounded", timeout=math.inf)
    publisher.join(0.5)

    assert event.payload == {"id": 1}
    assert queue_timeouts == [None]
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_unbounded_wait_keyboard_interrupt_unsubscribes_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def interrupted_get(
        instance: queue.Queue[Any],
        block: bool = True,
        timeout: float | None = None,
    ) -> Any:
        del instance, block
        assert timeout is None
        raise KeyboardInterrupt

    monkeypatch.setattr(queue.Queue, "get", interrupted_get)

    with pytest.raises(KeyboardInterrupt):
        manager.wait_for_event("ak.unbounded.cancelled", timeout=math.inf)

    assert client.unsubscribe_calls == 1
    assert client.handlers == []
    assert manager.active_topics == set()


def test_wait_for_events_accepts_unbounded_timeout_and_keeps_count_bounded() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        handler = client.handlers[0]
        handler.emit({"sequence": 1})
        handler.emit({"sequence": 2})

    publisher = threading.Thread(target=publish)
    publisher.start()
    events = manager.wait_for_events(
        "ak.unbounded.multi",
        event_count=2,
        timeout=math.inf,
    )
    publisher.join(0.5)

    assert [event.payload["sequence"] for event in events] == [1, 2]
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_wait_for_event_false_unsubscribe_is_a_distinct_cleanup_failure() -> None:
    class FalseCleanupClient(FakeSubscriptionClient):
        def unsubscribe(self, event_handler: FakeEventHandler) -> bool:
            del event_handler
            self.unsubscribe_calls += 1
            return False

    client = FalseCleanupClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        client.handlers[0].emit({"id": 1})

    publisher = threading.Thread(target=publish)
    publisher.start()
    with pytest.raises(SubscriptionCleanupError) as caught:
        manager.wait_for_event("ak.false.cleanup", timeout=0.5)
    publisher.join(0.5)

    assert caught.value.primary_error is None
    assert caught.value.reason == "unsubscribe_returned_false"
    assert client.unsubscribe_calls == 1
    assert len(client.handlers) == 1
    assert manager.active_topics == {"ak.false.cleanup"}


def test_wait_for_event_timeout_unsubscribes_once() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    with pytest.raises(SubscriptionTimeout, match="Timed out"):
        manager.wait_for_event("ak.never", timeout=0.01)

    assert client.unsubscribe_calls == 1
    assert len(client.handlers) == 0
    assert manager.active_topics == set()


def test_wait_for_event_timeout_includes_subscription_setup_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_timeouts: list[float] = []
    base_queue = queue.Queue

    class RecordingQueue(base_queue):  # type: ignore[type-arg]
        def get(
            self,
            block: bool = True,
            timeout: float | None = None,
        ) -> Any:
            if timeout is not None:
                queue_timeouts.append(timeout)
            return super().get(block=block, timeout=timeout)

    monkeypatch.setattr(subscriptions_module.queue, "Queue", RecordingQueue)

    class SlowSubscribeClient(FakeSubscriptionClient):
        def subscribe(
            self,
            uri: str,
            callback_or_handler: Callable[..., None] | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> FakeEventHandler | None:
            time.sleep(0.03)
            return super().subscribe(uri, callback_or_handler, *args, **kwargs)

    client = SlowSubscribeClient()
    manager = SubscriptionManager(client)

    with pytest.raises(SubscriptionTimeout, match="Timed out"):
        manager.wait_for_event("ak.never", timeout=0.04)

    assert len(queue_timeouts) == 1
    assert 0.0 <= queue_timeouts[0] < 0.02
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_wait_for_event_ignores_nonmatching_payload_then_returns_match() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        handler = client.handlers[0]
        handler.emit({"object": {"id": "wrong"}, "kind": "created"})
        handler.emit({"object": {"id": "wanted", "name": "UI"}, "kind": "created"})

    publisher = threading.Thread(target=publish)
    publisher.start()
    event = manager.wait_for_event(
        "ak.wwise.core.object.created",
        timeout=0.5,
        queue_size=4,
        predicate=lambda item: payload_matches(item.payload, {"object": {"id": "wanted"}}),
    )
    publisher.join(0.5)

    assert event.payload["object"]["name"] == "UI"
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_wait_for_events_collects_matching_events_in_order_and_unsubscribes_once() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        handler = client.handlers[0]
        handler.emit({"scope": "ignore", "sequence": 0})
        handler.emit({"scope": "wanted", "sequence": 1})
        handler.emit({"scope": "wanted", "sequence": 2})
        handler.emit({"scope": "wanted", "sequence": 3})

    publisher = threading.Thread(target=publish)
    publisher.start()
    events = manager.wait_for_events(
        "ak.wwise.core.soundbank.generated",
        event_count=3,
        timeout=0.5,
        predicate=lambda item: payload_matches(item.payload, {"scope": "wanted"}),
    )
    publisher.join(0.5)

    assert [event.payload["sequence"] for event in events] == [1, 2, 3]
    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


def test_wait_for_events_timeout_reports_partial_count_and_unsubscribes_once() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    def publish() -> None:
        while not client.handlers:
            time.sleep(0.001)
        client.handlers[0].emit({"sequence": 1})

    publisher = threading.Thread(target=publish)
    publisher.start()
    with pytest.raises(SubscriptionTimeout, match=r"received 1$"):
        manager.wait_for_events("ak.partial", event_count=2, timeout=0.03)
    publisher.join(0.5)

    assert client.unsubscribe_calls == 1
    assert manager.active_topics == set()


@pytest.mark.parametrize("event_count", (0, MAX_WAIT_EVENT_COUNT + 1, True, 1.5))
def test_wait_for_events_rejects_invalid_count_before_subscribing(event_count: object) -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    with pytest.raises(ValueError, match="event_count"):
        manager.wait_for_events("ak.invalid", event_count=event_count)  # type: ignore[arg-type]

    assert client.handlers == []
    assert manager.active_topics == set()


def test_payload_match_uses_recursive_mapping_subset_and_exact_arrays() -> None:
    payload = {"object": {"id": "wanted", "path": "\\Events\\UI"}, "values": [1, {"ok": True}]}

    assert payload_matches(payload, {"object": {"id": "wanted"}}) is True
    assert payload_matches(payload, {"object": {"id": "other"}}) is False
    assert payload_matches(payload, {"values": [1, {"ok": True}]}) is True
    assert payload_matches(payload, {"values": [1]}) is False


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


def test_persistent_stream_delivers_ordered_events_through_one_handler() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)

    stream = manager.open_stream("ak.persistent", queue_size=3)
    assert isinstance(stream, TopicEventStream)
    assert len(client.handlers) == 1
    handler = client.handlers[0]

    handler.emit({"sequence": 1})
    handler.emit({"sequence": 2})
    handler.emit({"sequence": 3})

    assert [
        stream.poll(timeout=0.01).payload["sequence"],  # type: ignore[union-attr]
        stream.poll(timeout=0.01).payload["sequence"],  # type: ignore[union-attr]
        stream.poll(timeout=0.01).payload["sequence"],  # type: ignore[union-attr]
    ] == [1, 2, 3]
    assert len(client.handlers) == 1
    assert client.call_while_in_callback == 0
    assert stream.close() is True


def test_persistent_stream_poll_returns_none_on_timeout() -> None:
    client = FakeSubscriptionClient()
    stream = SubscriptionManager(client).open_stream("ak.persistent.timeout")

    assert stream.poll(timeout=0.01) is None
    assert stream.close() is True


def test_persistent_stream_cleanup_runs_exactly_once() -> None:
    client = FakeSubscriptionClient()
    manager = SubscriptionManager(client)
    stream = manager.open_stream("ak.persistent.cleanup")

    assert stream.close() is True
    assert stream.close() is False
    assert client.unsubscribe_calls == 1
    assert client.handlers == []
    assert manager.active_topics == set()


def test_persistent_stream_overflow_fails_instead_of_dropping() -> None:
    client = FakeSubscriptionClient()
    stream = SubscriptionManager(client).open_stream(
        "ak.persistent.overflow",
        queue_size=1,
    )
    handler = client.handlers[0]

    handler.emit({"sequence": 1})
    handler.emit({"sequence": 2})

    with pytest.raises(SubscriptionStreamOverflow) as caught:
        stream.poll(timeout=0.01)

    assert caught.value.error_code == "SUBSCRIPTION_STREAM_OVERFLOW"
    assert caught.value.topic == "ak.persistent.overflow"
    assert caught.value.queue_size == 1
    assert stream.close() is True


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    (
        ({"text": "x" * 128}, "RESULT_TOO_LARGE"),
        ({"invalid": {1, 2}}, "RESULT_NOT_JSON"),
    ),
)
def test_persistent_stream_rejects_invalid_payload_before_buffering(
    payload: Any,
    expected_code: str,
) -> None:
    client = FakeSubscriptionClient()
    stream = SubscriptionManager(client).open_stream(
        "ak.persistent.ingress",
        queue_size=3,
        max_event_bytes=32,
    )
    handler = client.handlers[0]

    handler.emit(payload)
    handler.emit({"ignored_after_failure": True})

    with pytest.raises(SubscriptionStreamIngressError) as caught:
        stream.poll(timeout=0.01)

    assert caught.value.error_code == expected_code
    assert caught.value.topic == "ak.persistent.ingress"
    assert caught.value.limit_bytes == 32
    assert stream.event_queue.empty()
    assert stream.close() is True


@pytest.mark.parametrize("queue_size", (0, -1, True, 1.5))
def test_persistent_stream_rejects_invalid_queue_size_before_subscribing(
    queue_size: object,
) -> None:
    client = FakeSubscriptionClient()

    with pytest.raises(ValueError, match="positive integer"):
        SubscriptionManager(client).open_stream(
            "ak.persistent.invalid",
            queue_size=queue_size,  # type: ignore[arg-type]
        )

    assert client.handlers == []


@pytest.mark.parametrize("max_event_bytes", (0, -1, True, 1.5))
def test_persistent_stream_rejects_invalid_event_byte_limit_before_subscribing(
    max_event_bytes: object,
) -> None:
    client = FakeSubscriptionClient()

    with pytest.raises(ValueError, match="max_event_bytes must be a positive integer"):
        SubscriptionManager(client).open_stream(
            "ak.persistent.invalid-limit",
            max_event_bytes=max_event_bytes,  # type: ignore[arg-type]
        )

    assert client.handlers == []


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

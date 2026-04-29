"""Bounded WAAPI topic subscription helpers."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

DEFAULT_WAIT_TIMEOUT = 5.0
DEFAULT_QUEUE_SIZE = 1
DEFAULT_LISTENER_QUEUE_SIZE = 64
DEFAULT_CANCEL_JOIN_TIMEOUT = 1.0
DEFAULT_LISTENER_POLL_INTERVAL = 0.05
DEFAULT_CALLBACK_ERROR_LIMIT = 1
DEFAULT_CALLBACK_EXECUTOR = "waapi.SequentialThreadExecutor"


class SubscriptionError(RuntimeError):
    """Base error for bounded subscription failures."""


class SubscriptionUnavailable(SubscriptionError):
    """Raised when the WAAPI client cannot create a subscription."""


class SubscriptionTimeout(SubscriptionError):
    """Raised when a bounded wait expires before an event arrives."""


class SubscriptionCallbackError(SubscriptionError):
    """Raised by listener checks when the user callback failed."""


@dataclass(slots=True, frozen=True)
class SubscriptionEvent:
    """Event data transferred out of the WAAPI callback thread."""

    topic: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def payload(self) -> Any:
        """Return the common single positional payload, or kwargs when no positional payload exists."""

        if len(self.args) == 1:
            return self.args[0]
        if self.args:
            return self.args
        return self.kwargs


class EventHandlerProtocol(Protocol):
    """Small waapi-client EventHandler surface used for cleanup."""

    def unsubscribe(self) -> bool:
        """Unsubscribe this handler."""
        ...


class WaapiSubscriptionClient(Protocol):
    """WAAPI client methods needed by the subscription manager."""

    def subscribe(self, uri: str, callback_or_handler: Callable[..., None] | None = None, *args: Any, **kwargs: Any) -> Any:
        """Subscribe to a topic and return a waapi EventHandler or None."""
        ...

    def unsubscribe(self, event_handler: Any) -> bool:
        """Unsubscribe a previously returned EventHandler."""
        ...


@dataclass(slots=True)
class SubscriptionHandle:
    """Idempotent owner for one WAAPI event subscription."""

    topic: str
    handler: Any
    client: WaapiSubscriptionClient | None = None
    active_topics: set[str] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _unsubscribed: bool = field(default=False, init=False, repr=False)

    @property
    def unsubscribed(self) -> bool:
        """Whether cleanup has already run."""

        return self._unsubscribed

    def unsubscribe(self) -> bool:
        """Unsubscribe exactly once; repeated calls are safe and return False."""

        with self._lock:
            if self._unsubscribed:
                return False
            self._unsubscribed = True
            if self.active_topics is not None:
                self.active_topics.discard(self.topic)

        return self._unsubscribe_handler()

    def _unsubscribe_handler(self) -> bool:
        if self.handler is None:
            return True
        unsubscribe = getattr(self.handler, "unsubscribe", None)
        if callable(unsubscribe):
            return bool(unsubscribe())
        if self.client is not None:
            return bool(self.client.unsubscribe(self.handler))
        return True

    def __enter__(self) -> "SubscriptionHandle":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.unsubscribe()


@dataclass(slots=True)
class BackgroundSubscription(SubscriptionHandle):
    """Background listener that drains queued WAAPI events until cancelled."""

    event_queue: queue.Queue[SubscriptionEvent] = field(default_factory=lambda: queue.Queue(maxsize=DEFAULT_LISTENER_QUEUE_SIZE))
    callback: Callable[[SubscriptionEvent], None] | None = None
    join_timeout: float = DEFAULT_CANCEL_JOIN_TIMEOUT
    poll_interval: float = DEFAULT_LISTENER_POLL_INTERVAL
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _callback_errors: list[BaseException] = field(default_factory=list, init=False, repr=False)

    def start(self) -> "BackgroundSubscription":
        """Start the bounded listener thread."""

        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name=f"waapi-subscription:{self.topic}", daemon=False)
        self._thread.start()
        return self

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def callback_errors(self) -> tuple[BaseException, ...]:
        return tuple(self._callback_errors)

    def raise_if_callback_failed(self) -> None:
        if self._callback_errors:
            raise SubscriptionCallbackError(str(self._callback_errors[0])) from self._callback_errors[0]

    def cancel(self) -> bool:
        """Stop the listener and unsubscribe once."""

        self._stop.set()
        unsubscribed_now = self.unsubscribe()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self.join_timeout)
        return unsubscribed_now

    def unsubscribe(self) -> bool:
        self._stop.set()
        return SubscriptionHandle.unsubscribe(self)

    def _run(self) -> None:
        while not self._stop.is_set() or not self.event_queue.empty():
            try:
                event = self.event_queue.get(timeout=self.poll_interval)
            except queue.Empty:
                continue
            try:
                if self.callback is not None:
                    self.callback(event)
            except BaseException as exc:  # pragma: no cover - exact exception asserted through public state
                if len(self._callback_errors) < DEFAULT_CALLBACK_ERROR_LIMIT:
                    self._callback_errors.append(exc)
            finally:
                self.event_queue.task_done()

    def __enter__(self) -> "BackgroundSubscription":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.cancel()


@dataclass(slots=True)
class SubscriptionManager:
    """Bounded WAAPI subscription runtime.

    waapi-client already defaults to ``SequentialThreadExecutor`` for event callbacks;
    this manager assumes that strategy and keeps the WAAPI callback itself limited to a
    queue handoff so user code never calls client APIs from the callback thread.
    """

    client: WaapiSubscriptionClient | None = None
    active_topics: set[str] = field(default_factory=set)

    def subscribe(self, topic: str, callback: Callable[..., None] | None = None, options: dict[str, Any] | None = None) -> SubscriptionHandle | None:
        """Subscribe to ``topic`` and return a cleanup handle when a client is configured.

        A client-less manager preserves the original lightweight registry contract used by
        scaffold tests: topics are recorded and can later be discarded with ``unsubscribe``.
        """

        if self.client is None:
            self.active_topics.add(topic)
            return None
        handler = self._subscribe_client(topic, callback, options)
        self.active_topics.add(topic)
        return SubscriptionHandle(topic=topic, handler=handler, client=self.client, active_topics=self.active_topics)

    def wait_for_event(
        self,
        topic: str,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        options: dict[str, Any] | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> SubscriptionEvent:
        """Block for one topic event, bounded by ``timeout``, and always unsubscribe."""

        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        event_queue: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=max(1, queue_size))

        def callback(*args: Any, **kwargs: Any) -> None:
            _put_bounded(event_queue, SubscriptionEvent(topic=topic, args=args, kwargs=dict(kwargs)))

        handle = self.subscribe(topic, callback=callback, options=options)
        if handle is None:
            raise SubscriptionUnavailable("A WAAPI client is required for bounded topic waits")
        try:
            return event_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise SubscriptionTimeout(f"Timed out waiting {timeout:.3f}s for WAAPI topic {topic}") from exc
        finally:
            handle.unsubscribe()

    def listen(
        self,
        topic: str,
        callback: Callable[[SubscriptionEvent], None] | None = None,
        options: dict[str, Any] | None = None,
        queue_size: int = DEFAULT_LISTENER_QUEUE_SIZE,
        join_timeout: float = DEFAULT_CANCEL_JOIN_TIMEOUT,
    ) -> BackgroundSubscription:
        """Subscribe and process events on an explicit, cancellable background listener."""

        if self.client is None:
            raise SubscriptionUnavailable("A WAAPI client is required for background listeners")
        event_queue: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=max(1, queue_size))

        def waapi_callback(*args: Any, **kwargs: Any) -> None:
            _put_bounded(event_queue, SubscriptionEvent(topic=topic, args=args, kwargs=dict(kwargs)))

        handler = self._subscribe_client(topic, waapi_callback, options)
        self.active_topics.add(topic)
        return BackgroundSubscription(
            topic=topic,
            handler=handler,
            client=self.client,
            active_topics=self.active_topics,
            event_queue=event_queue,
            callback=callback,
            join_timeout=join_timeout,
        ).start()

    def unsubscribe(self, topic: str) -> None:
        """Discard a client-less registry topic; handle objects own real cleanup."""

        self.active_topics.discard(topic)

    def clear(self) -> None:
        """Clear client-less topic bookkeeping."""

        self.active_topics.clear()

    def _subscribe_client(self, topic: str, callback: Callable[..., None] | None, options: dict[str, Any] | None) -> Any:
        if self.client is None:
            raise SubscriptionUnavailable("A WAAPI client is required for subscriptions")
        options = dict(options or {})
        handler = self.client.subscribe(topic, callback, options) if options else self.client.subscribe(topic, callback)
        if handler is None:
            raise SubscriptionUnavailable(f"WAAPI did not create a subscription for {topic}")
        return handler


def _put_bounded(event_queue: queue.Queue[SubscriptionEvent], event: SubscriptionEvent) -> None:
    try:
        event_queue.put_nowait(event)
        return
    except queue.Full:
        pass
    try:
        event_queue.get_nowait()
        event_queue.task_done()
    except queue.Empty:
        pass
    try:
        event_queue.put_nowait(event)
    except queue.Full:
        pass

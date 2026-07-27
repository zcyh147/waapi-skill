"""Bounded WAAPI topic subscription helpers."""

from __future__ import annotations

import json
import math
import os
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

DEFAULT_WAIT_TIMEOUT = 5.0
DEFAULT_QUEUE_SIZE = 1
DEFAULT_LISTENER_QUEUE_SIZE = 64
DEFAULT_STREAM_EVENT_BYTES = 1024 * 1024
DEFAULT_STREAM_FAILURE_POLL_INTERVAL = 0.05
MAX_WAIT_EVENT_COUNT = 64
DEFAULT_CANCEL_JOIN_TIMEOUT = 1.0
DEFAULT_LISTENER_POLL_INTERVAL = 0.05
DEFAULT_CALLBACK_ERROR_LIMIT = 1
DEFAULT_CALLBACK_EXECUTOR = "waapi.SequentialThreadExecutor"
SUBSCRIPTION_ACK_CONTRACT = "waapi-skill.broker-subscription-ack/v2"
SUBSCRIPTION_ACK_PATH_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_PATH"
SUBSCRIPTION_ACK_NONCE_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_NONCE"
SUBSCRIPTION_ACK_TOPIC_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_TOPIC"
SUBSCRIPTION_ACK_STEP_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_STEP"
SUBSCRIPTION_ACK_EVIDENCE_DIR_ENV = "WWISE_EVIDENCE_DIR"
SUBSCRIPTION_ACK_ENV_NAMES = frozenset(
    {
        SUBSCRIPTION_ACK_PATH_ENV,
        SUBSCRIPTION_ACK_NONCE_ENV,
        SUBSCRIPTION_ACK_TOPIC_ENV,
        SUBSCRIPTION_ACK_STEP_ENV,
    }
)
_SUBSCRIPTION_ACK_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class SubscriptionError(RuntimeError):
    """Base error for bounded subscription failures."""


class SubscriptionUnavailable(SubscriptionError):
    """Raised when the WAAPI client cannot create a subscription."""


class SubscriptionAcknowledgementError(SubscriptionUnavailable):
    """Raised when a trusted broker subscription ACK cannot be published."""


class SubscriptionTimeout(SubscriptionError):
    """Raised when a bounded wait expires before an event arrives."""


class SubscriptionCallbackError(SubscriptionError):
    """Raised by listener checks when the user callback failed."""


class SubscriptionStreamOverflow(SubscriptionError):
    """Raised when a persistent stream cannot retain every received event."""

    error_code = "SUBSCRIPTION_STREAM_OVERFLOW"

    def __init__(self, topic: str, queue_size: int) -> None:
        super().__init__(
            f"Persistent WAAPI topic stream overflowed its {queue_size}-event "
            f"queue for {topic}; event delivery is no longer complete"
        )
        self.topic = topic
        self.queue_size = queue_size


class SubscriptionStreamIngressError(SubscriptionError):
    """A permanent strict-JSON or byte-ceiling failure at stream ingress."""

    def __init__(
        self,
        *,
        error_code: str,
        topic: str,
        limit_bytes: int,
    ) -> None:
        if error_code == "RESULT_TOO_LARGE":
            message = "Persistent WAAPI topic event exceeded its JSON byte limit"
            reason = "too_large"
        elif error_code == "RESULT_NOT_JSON":
            message = "Persistent WAAPI topic event is not a strict JSON value"
            reason = "not_json"
        else:  # pragma: no cover - construction is private and closed below
            raise ValueError("unsupported stream ingress error code")
        super().__init__(message)
        self.error_code = error_code
        self.topic = topic
        self.limit_bytes = limit_bytes
        self.reason = reason

    def as_dict(self) -> dict[str, Any]:
        """Return bounded structured details for gateway normalization."""

        details: dict[str, Any] = {
            "topic": self.topic,
            "limit_bytes": self.limit_bytes,
            "reason": self.reason,
        }
        if self.error_code == "RESULT_TOO_LARGE":
            details["observed_at_least_bytes"] = self.limit_bytes + 1
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": details,
        }


class SubscriptionCleanupError(SubscriptionError):
    """Raised when a bounded wait cannot prove that unsubscribe succeeded."""

    def __init__(
        self,
        message: str,
        *,
        primary_error: BaseException | None = None,
        reason: str,
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.reason = reason


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
    _unsubscribe_in_progress: bool = field(default=False, init=False, repr=False)

    @property
    def unsubscribed(self) -> bool:
        """Whether cleanup has already run."""

        return self._unsubscribed

    def unsubscribe(self) -> bool:
        """Record cleanup only after the client explicitly returns ``True``.

        A ``False`` result is not successful cleanup: the handle remains active
        and its topic remains registered so a later close/unsubscribe attempt
        can retry without claiming that the WAAPI subscription was removed.
        """

        with self._lock:
            if self._unsubscribed or self._unsubscribe_in_progress:
                return False
            self._unsubscribe_in_progress = True
        try:
            succeeded = self._unsubscribe_handler()
        except BaseException:
            with self._lock:
                self._unsubscribe_in_progress = False
            raise
        with self._lock:
            self._unsubscribe_in_progress = False
            if succeeded:
                self._unsubscribed = True
                if self.active_topics is not None:
                    self.active_topics.discard(self.topic)
        return succeeded

    def _unsubscribe_handler(self) -> bool:
        if self.handler is None:
            return True
        unsubscribe = getattr(self.handler, "unsubscribe", None)
        if callable(unsubscribe):
            return unsubscribe() is True
        if self.client is not None:
            return self.client.unsubscribe(self.handler) is True
        return True

    def __enter__(self) -> "SubscriptionHandle":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.unsubscribe()


@dataclass(slots=True)
class _TopicStreamIngressState:
    """Share the callback's first permanent ingress failure with the poller."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _error: SubscriptionStreamIngressError | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def fail(self, error: SubscriptionStreamIngressError) -> None:
        with self._lock:
            if self._error is None:
                self._error = error

    def current_error(self) -> SubscriptionStreamIngressError | None:
        with self._lock:
            return self._error


@dataclass(slots=True)
class TopicEventStream:
    """One persistent WAAPI subscription with fail-closed queued delivery."""

    handle: SubscriptionHandle
    event_queue: queue.Queue[SubscriptionEvent]
    overflowed: threading.Event
    queue_size: int
    max_event_bytes: int
    ingress_state: _TopicStreamIngressState

    @property
    def topic(self) -> str:
        """Return the topic owned by the single subscription handle."""

        return self.handle.topic

    def poll(self, timeout: float | None = None) -> SubscriptionEvent | None:
        """Return the next event, ``None`` on timeout, or fail on any overflow."""

        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError("timeout must be a non-negative finite number or None")
            if not math.isfinite(timeout) or timeout < 0:
                raise ValueError("timeout must be a non-negative finite number or None")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self._raise_if_failed()
            wait_seconds = DEFAULT_STREAM_FAILURE_POLL_INTERVAL
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        event = self.event_queue.get_nowait()
                    except queue.Empty:
                        self._raise_if_failed()
                        return None
                    self._raise_if_failed()
                    return event
                wait_seconds = min(wait_seconds, remaining)
            try:
                event = self.event_queue.get(timeout=wait_seconds)
            except queue.Empty:
                continue
            self._raise_if_failed()
            return event

    def close(self) -> bool:
        """Unsubscribe this stream; successful cleanup is idempotent."""

        return self.handle.unsubscribe()

    def _raise_if_failed(self) -> None:
        ingress_error = self.ingress_state.current_error()
        if ingress_error is not None:
            raise ingress_error
        if self.overflowed.is_set():
            raise SubscriptionStreamOverflow(self.topic, self.queue_size)

    def __enter__(self) -> "TopicEventStream":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


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
        handle = SubscriptionHandle(
            topic=topic,
            handler=handler,
            client=self.client,
            active_topics=self.active_topics,
        )
        try:
            _publish_subscription_ack(topic)
        except SubscriptionAcknowledgementError as exc:
            try:
                cleanup_succeeded = handle.unsubscribe()
            except BaseException as cleanup_exc:  # noqa: BLE001 - preserve both fail-closed facts
                raise SubscriptionAcknowledgementError(
                    f"{exc}; subscription cleanup also failed: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                ) from cleanup_exc
            if not cleanup_succeeded:
                raise SubscriptionAcknowledgementError(
                    f"{exc}; subscription cleanup returned false and remains active"
                ) from exc
            raise
        return handle

    def wait_for_event(
        self,
        topic: str,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        options: dict[str, Any] | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        predicate: Callable[[SubscriptionEvent], bool] | None = None,
    ) -> SubscriptionEvent:
        """Block for one matching event, bounded by ``timeout``, and always unsubscribe."""

        return self._wait_for_events(
            topic,
            event_count=1,
            timeout=timeout,
            options=options,
            queue_size=max(1, queue_size),
            predicate=predicate,
        )[0]

    def wait_for_events(
        self,
        topic: str,
        event_count: int,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        options: dict[str, Any] | None = None,
        predicate: Callable[[SubscriptionEvent], bool] | None = None,
    ) -> tuple[SubscriptionEvent, ...]:
        """Collect an exact bounded count of matching events, then unsubscribe.

        ``timeout`` is one deadline shared by subscription setup and the entire
        collection.  Candidate events that fail ``predicate`` do not count
        toward ``event_count``.  The public multi-event lane is deliberately
        capped so a caller cannot turn this helper into an unbounded listener.
        """

        if not isinstance(event_count, int) or isinstance(event_count, bool):
            raise ValueError("event_count must be an integer")
        if not 1 <= event_count <= MAX_WAIT_EVENT_COUNT:
            raise ValueError(f"event_count must be between 1 and {MAX_WAIT_EVENT_COUNT}")
        return self._wait_for_events(
            topic,
            event_count=event_count,
            timeout=timeout,
            options=options,
            queue_size=MAX_WAIT_EVENT_COUNT,
            predicate=predicate,
        )

    def _wait_for_events(
        self,
        topic: str,
        *,
        event_count: int,
        timeout: float,
        options: dict[str, Any] | None,
        queue_size: int,
        predicate: Callable[[SubscriptionEvent], bool] | None,
    ) -> tuple[SubscriptionEvent, ...]:
        """Internal shared implementation for single- and multi-event waits."""

        if math.isnan(timeout) or timeout < 0:
            raise ValueError("timeout must be non-negative or positive infinity")
        event_queue: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=max(1, queue_size))
        matched: list[SubscriptionEvent] = []

        def callback(*args: Any, **kwargs: Any) -> None:
            _put_bounded(event_queue, SubscriptionEvent(topic=topic, args=args, kwargs=dict(kwargs)))

        # Subscription setup is part of the advertised timeout; starting the
        # deadline afterward could wait ``setup + timeout`` wall-clock time.
        deadline = None if math.isinf(timeout) else time.monotonic() + timeout
        handle = self.subscribe(topic, callback=callback, options=options)
        if handle is None:
            raise SubscriptionUnavailable("A WAAPI client is required for bounded topic waits")
        primary_error: BaseException | None = None
        try:
            while len(matched) < event_count:
                try:
                    if deadline is None:
                        event = event_queue.get()
                    else:
                        remaining = max(0.0, deadline - time.monotonic())
                        event = event_queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise SubscriptionTimeout(
                        f"Timed out waiting {timeout:.3f}s for {event_count} matching "
                        f"WAAPI topic event(s) on {topic}; received {len(matched)}"
                    ) from exc
                if predicate is None or predicate(event):
                    matched.append(event)
        except BaseException as exc:  # cleanup must also run for Ctrl-C/SystemExit
            primary_error = exc

        try:
            cleanup_succeeded = handle.unsubscribe()
        except Exception as cleanup_exc:
            message = (
                f"Subscription cleanup raised {type(cleanup_exc).__name__}: {cleanup_exc}"
            )
            if primary_error is not None:
                message = f"{primary_error}; {message}"
            raise SubscriptionCleanupError(
                message,
                primary_error=primary_error,
                reason="unsubscribe_raised",
            ) from cleanup_exc
        if not cleanup_succeeded:
            message = "Subscription cleanup returned false and remains active"
            if primary_error is not None:
                message = f"{primary_error}; {message}"
            raise SubscriptionCleanupError(
                message,
                primary_error=primary_error,
                reason="unsubscribe_returned_false",
            ) from primary_error
        if primary_error is not None:
            raise primary_error
        return tuple(matched)

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

    def open_stream(
        self,
        topic: str,
        options: dict[str, Any] | None = None,
        queue_size: int = DEFAULT_LISTENER_QUEUE_SIZE,
        max_event_bytes: int = DEFAULT_STREAM_EVENT_BYTES,
    ) -> TopicEventStream:
        """Open one persistent subscription whose events are polled by the caller.

        Unlike the background-listener compatibility lane, this stream never
        discards an old event to make room for a new one. Any full queue marks
        the stream permanently incomplete, and the next poll fails closed.
        """

        if (
            isinstance(queue_size, bool)
            or not isinstance(queue_size, int)
            or queue_size <= 0
        ):
            raise ValueError("queue_size must be a positive integer")
        if (
            isinstance(max_event_bytes, bool)
            or not isinstance(max_event_bytes, int)
            or max_event_bytes <= 0
        ):
            raise ValueError("max_event_bytes must be a positive integer")
        if self.client is None:
            raise SubscriptionUnavailable(
                "A WAAPI client is required for persistent topic streams"
            )
        event_queue: queue.Queue[SubscriptionEvent] = queue.Queue(
            maxsize=queue_size
        )
        overflowed = threading.Event()
        ingress_state = _TopicStreamIngressState()

        def waapi_callback(*args: Any, **kwargs: Any) -> None:
            if (
                overflowed.is_set()
                or ingress_state.current_error() is not None
            ):
                return
            event = SubscriptionEvent(
                topic=topic,
                args=args,
                kwargs=dict(kwargs),
            )
            probe = _probe_strict_stream_payload(
                event.payload,
                max_event_bytes,
            )
            if probe != "ok":
                ingress_state.fail(
                    SubscriptionStreamIngressError(
                        error_code=(
                            "RESULT_TOO_LARGE"
                            if probe == "too_large"
                            else "RESULT_NOT_JSON"
                        ),
                        topic=topic,
                        limit_bytes=max_event_bytes,
                    )
                )
                return
            try:
                event_queue.put_nowait(event)
            except queue.Full:
                overflowed.set()

        handle = self.subscribe(topic, callback=waapi_callback, options=options)
        if handle is None:  # Defensive: the configured-client check above is authoritative.
            raise SubscriptionUnavailable(
                "A WAAPI client is required for persistent topic streams"
            )
        return TopicEventStream(
            handle=handle,
            event_queue=event_queue,
            overflowed=overflowed,
            queue_size=queue_size,
            max_event_bytes=max_event_bytes,
            ingress_state=ingress_state,
        )

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


def _publish_subscription_ack(topic: str) -> Mapping[str, Any] | None:
    """Atomically publish one broker-only proof after subscribe succeeds.

    Normal production use does not set any ACK environment variable and takes
    the immediate ``None`` path.  The fresh-Codex broker supplies all four
    values only to one packaged ``wait-topic`` runner.  A partial, stale,
    duplicated, wrong-topic, or out-of-evidence request fails closed before the
    bounded wait can continue.
    """

    values = {name: os.environ.get(name) for name in SUBSCRIPTION_ACK_ENV_NAMES}
    configured = {name: value for name, value in values.items() if value not in {None, ""}}
    if not configured:
        return None
    if len(configured) != len(SUBSCRIPTION_ACK_ENV_NAMES):
        missing = sorted(SUBSCRIPTION_ACK_ENV_NAMES.difference(configured))
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK environment is incomplete: " + ", ".join(missing)
        )

    path_text = str(values[SUBSCRIPTION_ACK_PATH_ENV])
    nonce = str(values[SUBSCRIPTION_ACK_NONCE_ENV])
    expected_topic = str(values[SUBSCRIPTION_ACK_TOPIC_ENV])
    step_name = str(values[SUBSCRIPTION_ACK_STEP_ENV])
    if expected_topic != topic:
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK topic does not match the successful subscription."
        )
    if not step_name.strip() or len(step_name.encode("utf-8")) > 256:
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK step identity is invalid."
        )
    if _SUBSCRIPTION_ACK_NONCE_RE.fullmatch(nonce) is None:
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK nonce is invalid."
        )

    evidence_text = os.environ.get(SUBSCRIPTION_ACK_EVIDENCE_DIR_ENV, "")
    target = Path(path_text)
    evidence_directory = Path(evidence_text)
    if not target.is_absolute() or not evidence_directory.is_absolute():
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK requires absolute target and evidence paths."
        )
    try:
        real_evidence = evidence_directory.resolve(strict=True)
        real_parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise SubscriptionAcknowledgementError(
            f"Broker subscription ACK evidence directory is unavailable: {exc}"
        ) from exc
    if (
        evidence_directory.is_symlink()
        or not real_evidence.is_dir()
        or target.parent != evidence_directory
        or real_parent != real_evidence
        or target.name in {"", ".", ".."}
        or not target.name.startswith("subscription-ack-")
        or not target.name.endswith(".json")
    ):
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK target is outside its exact real evidence directory."
        )
    if target.is_symlink() or target.exists():
        raise SubscriptionAcknowledgementError(
            "Broker subscription ACK target is not fresh and exclusive."
        )

    payload = {
        "contract": SUBSCRIPTION_ACK_CONTRACT,
        "step_name": step_name,
        "topic": topic,
        "nonce": nonce,
        "runner_parent_process_id": os.getppid(),
        "gateway_process_id": os.getpid(),
        "subscribed_at_unix_ns": time.time_ns(),
        "subscribed_at_monotonic_ns": time.monotonic_ns(),
    }
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    temporary = real_evidence / (
        f".{target.name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise OSError("subscription ACK write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        # A same-directory hard link is an atomic, no-overwrite publication.
        # It cannot replace a forged/pre-existing target as os.replace could.
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
        try:
            directory_descriptor = os.open(real_evidence, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except OSError as exc:
        raise SubscriptionAcknowledgementError(
            f"Broker subscription ACK could not be published exclusively: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return payload


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


class _StreamJsonSizeExceeded(Exception):
    """The strict stream payload crossed its configured byte ceiling."""


class _StreamJsonEncodingRejected(Exception):
    """The stream payload is outside the strict JSON value set."""


class _BoundedStreamJsonSizer:
    """Count compact strict-JSON UTF-8 bytes without materializing the document."""

    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        self.observed_bytes = 0
        self._active_container_ids: set[int] = set()

    def add_bytes(self, byte_count: int) -> None:
        if byte_count > self.limit_bytes - self.observed_bytes:
            raise _StreamJsonSizeExceeded
        self.observed_bytes += byte_count

    def measure(self, value: Any) -> None:
        if value is None:
            self.add_bytes(4)
            return
        if value is True:
            self.add_bytes(4)
            return
        if value is False:
            self.add_bytes(5)
            return
        if isinstance(value, str):
            self._measure_string(value)
            return
        if isinstance(value, int):
            self.add_bytes(len(int.__repr__(value)))
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise _StreamJsonEncodingRejected
            self.add_bytes(len(float.__repr__(value)))
            return
        if isinstance(value, (list, tuple)):
            self._measure_array(value)
            return
        if isinstance(value, dict):
            self._measure_object(value)
            return
        raise _StreamJsonEncodingRejected

    def _measure_string(self, value: str) -> None:
        self.add_bytes(2)
        for character in value:
            codepoint = ord(character)
            if character in {'"', "\\"} or character in {
                "\b",
                "\f",
                "\n",
                "\r",
                "\t",
            }:
                self.add_bytes(2)
            elif codepoint <= 0x1F:
                self.add_bytes(6)
            elif codepoint <= 0x7F:
                self.add_bytes(1)
            elif codepoint <= 0x7FF:
                self.add_bytes(2)
            elif 0xD800 <= codepoint <= 0xDFFF:
                raise _StreamJsonEncodingRejected
            elif codepoint <= 0xFFFF:
                self.add_bytes(3)
            else:
                self.add_bytes(4)

    def _measure_array(self, value: list[Any] | tuple[Any, ...]) -> None:
        self.add_bytes(1)
        if not value:
            self.add_bytes(1)
            return
        # One byte per smallest value, one comma between values, and ``]``.
        if (2 * len(value)) > self.limit_bytes - self.observed_bytes:
            raise _StreamJsonSizeExceeded
        self._enter_container(value)
        try:
            for index, item in enumerate(value):
                if index:
                    self.add_bytes(1)
                self.measure(item)
            self.add_bytes(1)
        finally:
            self._leave_container(value)

    def _measure_object(self, value: dict[Any, Any]) -> None:
        self.add_bytes(1)
        if not value:
            self.add_bytes(1)
            return
        # Each compact member needs at least ``"":0`` plus separators/``}``.
        if (5 * len(value)) > self.limit_bytes - self.observed_bytes:
            raise _StreamJsonSizeExceeded
        self._enter_container(value)
        try:
            for index, (key, item) in enumerate(value.items()):
                if index:
                    self.add_bytes(1)
                self._measure_string(self._object_key_string(key))
                self.add_bytes(1)
                self.measure(item)
            self.add_bytes(1)
        finally:
            self._leave_container(value)

    def _object_key_string(self, key: Any) -> str:
        if isinstance(key, str):
            return key
        if key is True:
            return "true"
        if key is False:
            return "false"
        if key is None:
            return "null"
        if isinstance(key, int):
            return int.__repr__(key)
        if isinstance(key, float):
            if not math.isfinite(key):
                raise _StreamJsonEncodingRejected
            return float.__repr__(key)
        raise _StreamJsonEncodingRejected

    def _enter_container(self, value: Any) -> None:
        identity = id(value)
        if identity in self._active_container_ids:
            raise _StreamJsonEncodingRejected
        self._active_container_ids.add(identity)

    def _leave_container(self, value: Any) -> None:
        self._active_container_ids.remove(id(value))


def _probe_strict_stream_payload(value: Any, limit_bytes: int) -> str:
    """Return ``ok``, ``too_large``, or ``not_json`` using bounded work."""

    sizer = _BoundedStreamJsonSizer(limit_bytes)
    try:
        sizer.measure(value)
    except _StreamJsonSizeExceeded:
        return "too_large"
    except (
        _StreamJsonEncodingRejected,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return "not_json"
    return "ok"


def payload_matches(payload: Any, expected: Any) -> bool:
    """Return whether ``payload`` recursively contains the expected JSON subset."""

    if isinstance(expected, Mapping):
        if not isinstance(payload, Mapping):
            return False
        return all(key in payload and payload_matches(payload[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(payload, (list, tuple)) or len(payload) != len(expected):
            return False
        return all(payload_matches(actual, wanted) for actual, wanted in zip(payload, expected))
    return payload == expected

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

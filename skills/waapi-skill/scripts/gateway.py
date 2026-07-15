#!/usr/bin/env python3
"""Stable JSON gateway from agent commands to the WAAPI Skill runtime."""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from wwise_waapi.capabilities import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CapabilityCatalog,
    CapabilityNotFoundError,
    CapabilityRecord,
    FIXED_COMMANDS_BY_URI,
)
from wwise_waapi.builders.common import SemanticValidationError  # noqa: E402  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.metadata import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MetadataBuilder,
    parse_get_attenuation_curve_result,
    parse_get_property_info_result,
    parse_get_types_result,
    parse_is_property_enabled_result,
    parse_property_and_reference_names_result,
)
from wwise_waapi.builders.query import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_QUERY_TAKE,
    SUPPORTED_SELECTS,
    build_object_get_query,
)
from wwise_waapi.builders.schema import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    validate_semantic_event,
    validate_semantic_payload,
    validate_semantic_result,
)
from wwise_waapi.config import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    PROJECT_MODIFICATION_POLICIES,
    ResolvedSkillConfig,
    SkillConfig,
    load_effective_skill_config,
    resolve_external_config_path,
)
from wwise_waapi.dispatcher import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    WwiseDispatcher,
    _normalize_exception as normalize_dispatcher_exception,
    _safe_exception_attribute as safe_exception_attribute,
    _safe_type_name as safe_type_name,
)
from wwise_waapi.execution_contracts import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    PROJECT_GUARD_INVARIANT,
    PROJECT_GUARD_MODES,
    PROJECT_GUARD_TRANSITION_TO_PATH,
)
from wwise_waapi.operation_registry import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    PACKAGED_TRANSACTION_READBACK_URIS,
    OperationContractError,
    VerificationResult,
    build_undo_group_execution_plan,
    describe_operation,
    list_operation_specs,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.safety import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    BOUNDED_CALL_CANDIDATES,
    EXPLICIT_UNSUPPORTED_LIVE_URIS,
    EXPLICIT_UNSUPPORTED_TOPIC_URIS,
    REVIEWED_TOPIC_URIS,
)
from wwise_waapi.transaction_runtime import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DEFAULT_PREVIEW_TTL_SECONDS,
    PROJECT_GUARD_PHASE_POST_VERIFICATION,
    TransactionGuardError,
    build_project_guard,
    build_transaction_artifact,
    validate_transaction_guards,
)
from wwise_waapi.transaction_cleanup import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CLEANUP_PROJECTION_CONTRACT,
    CLEANUP_SPEC_CONTRACT,
    TransactionCleanupError,
    project_transaction_cleanup,
)
from wwise_waapi.transactions import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    STATE_DIRECTORY_ENV,
    InvalidTransition,
    TransactionState,
    TransactionStore,
)
from wwise_waapi.versions import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    SUPPORTED_WWISE_VERSION_KEYS,
    version_key_from_get_info,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_TIMEOUT = 10.0
DEFAULT_TRANSACTION_TIMEOUT = 150.0
TRANSPORT_CLEANUP_GRACE_SECONDS = 0.05
TOPIC_CLEANUP_RESERVE_MAX_SECONDS = 0.25
TOPIC_CLEANUP_RESERVE_RATIO = 0.20
GET_INFO_URI = "ak.wwise.core.getInfo"
GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
OBJECT_GET_URI = "ak.wwise.core.object.get"
GET_SELECTED_URI = "ak.wwise.ui.getSelectedObjects"
ENV_HOST = "WWISE_WAAPI_HOST"
ENV_PORT = "WWISE_WAAPI_PORT"
ENV_VERSION = "WWISE_VERSION"
ENV_EVIDENCE_DIR = "WWISE_EVIDENCE_DIR"
OFFLINE_COMMANDS = frozenset(
    {
        "capabilities",
        "describe",
        "operations",
        "operation-schema",
        "config-show",
        "config-set",
        "transaction-show",
        "confirm",
        "reject",
    }
)
GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
GATEWAY_CONFIG_CONTRACT = "waapi-skill.config/v1"
GATEWAY_SESSION_CONTEXT_CONTRACT = "waapi-skill.session-context/v1"
GATEWAY_DEADLINE_PROVENANCE = "waapi-skill.gateway-deadline/v1"
GATEWAY_RESULT_CEILING_PROVENANCE = "waapi-skill.gateway-live-result-json-ceiling/v1"
PROJECT_IDENTITY_FIELDS = ("id", "name", "path")
EXPANDING_QUERY_SELECTS = frozenset({"descendants", "ancestors", "referencesTo", "children"})
MAX_GATEWAY_RESULT_JSON_BYTES = 1024 * 1024
MAX_GATEWAY_JSON_INPUT_BYTES = 256 * 1024
MAX_GATEWAY_JSON_DEPTH = 32
MAX_GATEWAY_JSON_NODES = 10_000
MAX_GATEWAY_JSON_STRING_BYTES = 64 * 1024
UNDO_GROUP_CANCEL_RESERVE_MIN_SECONDS = 2.0
UNDO_GROUP_CANCEL_RESERVE_MAX_SECONDS = 10.0
UNDO_GROUP_CANCEL_RESERVE_RATIO = 0.20
# Keep the authoritative pretty-printed phase document well below the public
# 1 MiB gateway envelope.  The remaining space is reserved for the transaction
# identity, project/role guard summaries, cleanup projection, and JSON framing.
UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES = 256 * 1024
REFLECTION_INVENTORY_CALLS = {
    "ak.wwise.waapi.getFunctions": ("functions", "function"),
    "ak.wwise.waapi.getTopics": ("topics", "topic"),
}
MAX_REFLECTION_INVENTORY_ITEMS = 4096
MAX_REFLECTION_URI_BYTES = 512


class GatewayInputError(ValueError):
    """Raised for invalid gateway input before a WAAPI call is attempted."""


class GatewayResultShapeError(ValueError):
    """Raised when a successful response violates one public gateway contract."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any],
        error_code: str = "INVALID_QUERY_RESULT",
    ) -> None:
        super().__init__(message)
        self.details = dict(details)
        self.error_code = error_code

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


class GatewayTimeoutError(TimeoutError):
    """Structured end-to-end gateway deadline failure."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        configured_timeout: float,
        elapsed: float,
        operation_timeout: float | None = None,
        cleanup_pending: bool = False,
        abort_requested: bool = False,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.configured_timeout = configured_timeout
        self.elapsed = elapsed
        self.operation_timeout = operation_timeout
        self.cleanup_pending = cleanup_pending
        self.abort_requested = abort_requested

    def mark_cleanup_pending(self, *, abort_requested: bool = False) -> None:
        self.cleanup_pending = True
        self.abort_requested = self.abort_requested or abort_requested

    def as_dict(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "provenance": GATEWAY_DEADLINE_PROVENANCE,
            "phase": self.phase,
            "configured_timeout_seconds": self.configured_timeout,
            "elapsed_seconds": self.elapsed,
            "deadline_exhausted": self.elapsed >= self.configured_timeout,
            "cleanup_pending": self.cleanup_pending,
            "abort_requested": self.abort_requested,
        }
        if self.operation_timeout is not None:
            details["operation_timeout_seconds"] = self.operation_timeout
        return {
            "error_code": "TIMEOUT",
            "message": str(self),
            "details": details,
        }


@dataclass(frozen=True, slots=True)
class GatewayDeadline:
    """One monotonic wall-clock budget shared by the complete live command."""

    timeout: float
    started_at: float
    expires_at: float

    @classmethod
    def start(cls, timeout: float) -> "GatewayDeadline":
        started_at = time.monotonic()
        return cls(timeout=timeout, started_at=started_at, expires_at=started_at + timeout)

    @property
    def cleanup_expires_at(self) -> float:
        return self.expires_at + TRANSPORT_CLEANUP_GRACE_SECONDS

    def remaining(self, *, cleanup: bool = False) -> float:
        expires_at = self.cleanup_expires_at if cleanup else self.expires_at
        return max(0.0, expires_at - time.monotonic())

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def timeout_error(
        self,
        phase: str,
        *,
        operation_timeout: float | None = None,
        cleanup_pending: bool = False,
        abort_requested: bool = False,
    ) -> GatewayTimeoutError:
        elapsed = self.elapsed()
        return GatewayTimeoutError(
            f"Gateway timed out after {elapsed:.3f}s during {phase}",
            phase=phase,
            configured_timeout=self.timeout,
            elapsed=elapsed,
            operation_timeout=operation_timeout,
            cleanup_pending=cleanup_pending,
            abort_requested=abort_requested,
        )

    def require_remaining(self, phase: str) -> float:
        remaining = self.remaining()
        if remaining <= 0:
            raise self.timeout_error(phase)
        return remaining


@dataclass(frozen=True, slots=True)
class GatewayConnection:
    host: str
    port: int
    version_hint: str | None
    evidence_dir: Path | None
    timeout: float
    deadline: GatewayDeadline

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/waapi"


ClientFactory = Callable[[str], Any]


@dataclass(frozen=True, slots=True)
class _TransportRequest:
    request_id: str
    phase: str
    operation: str
    args: tuple[Any, ...]
    kwargs: Mapping[str, Any]
    response: queue.Queue[tuple[bool, Any]]
    expires_at: float
    cancelled: threading.Event


@dataclass(frozen=True, slots=True)
class _TransportSubscription:
    """Opaque reference to an EventHandler owned by the transport thread."""

    token: int


class GatewayTransport:
    """Own one WAAPI client and all of its operations on one caller thread.

    ``waapi-client`` stores an asyncio event loop on the client and mutates global
    txaio loop state. Creating or using clients from the dispatcher's short-lived
    timeout threads can therefore close a loop still referenced by another client.
    This transport serializes every synchronous client operation through one owner
    thread. Every request shares the gateway's monotonic deadline; an expired
    caller abandons its own response queue, so a late result can never satisfy a
    later request. The owner remains daemonized only for the unavoidable case of
    an injected third-party callable that neither returns nor exposes cancellation.
    """

    def __init__(
        self,
        url: str,
        client_factory: ClientFactory,
        *,
        deadline: GatewayDeadline | None = None,
    ) -> None:
        self.url = url
        self.client_factory = client_factory
        self.deadline = deadline or GatewayDeadline.start(DEFAULT_TIMEOUT)
        self._requests: queue.Queue[_TransportRequest] = queue.Queue()
        self._ready: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._abandoned = threading.Event()
        self._client: Any = None
        self._last_timeout: GatewayTimeoutError | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"waapi-gateway-owner:{uuid.uuid4().hex[:8]}",
            daemon=True,
        )
        self._thread.start()
        ready_timeout = self.deadline.remaining()
        if ready_timeout <= 0:
            self._abandoned.set()
            self._closed.set()
            self._requests.put(self._close_request())
            error = self.deadline.timeout_error("transport.connect", cleanup_pending=True)
            self._last_timeout = error
            raise error
        try:
            ok, payload = self._ready.get(timeout=ready_timeout)
        except queue.Empty as exc:
            self._abandoned.set()
            self._closed.set()
            self._requests.put(self._close_request())
            abort_requested = self._abort_pending_client()
            error = self.deadline.timeout_error(
                "transport.connect",
                cleanup_pending=self._thread.is_alive(),
                abort_requested=abort_requested,
            )
            self._last_timeout = error
            raise error from exc
        if not ok:
            raise payload

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._request("call", uri, args, options=options, phase=f"WAAPI call {uri}")

    def call_with_timeout(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        *,
        phase: str | None = None,
    ) -> Any:
        """Call without the dispatcher's extra helper thread.

        ``WwiseDispatcher`` feature-detects this method. The request gets the
        smaller of its local timeout and the end-to-end gateway deadline.
        """

        operation_timeout = self.deadline.remaining() if timeout is None else max(0.0, float(timeout))
        return self._request(
            "call",
            uri,
            args,
            options=options,
            phase=phase or f"WAAPI call {uri}",
            timeout=operation_timeout,
        )

    def subscribe(self, uri: str, callback: Any, options: Mapping[str, Any] | None = None) -> Any:
        return self._request("subscribe", uri, callback, options=options, phase=f"WAAPI subscribe {uri}")

    def unsubscribe(self, subscription: Any) -> Any:
        return self._request("unsubscribe", subscription, phase="WAAPI unsubscribe", cleanup=True)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        request = self._close_request()
        self._requests.put(request)
        try:
            ok, payload = request.response.get(timeout=self.deadline.remaining(cleanup=True))
        except queue.Empty as exc:
            abort_requested = self._abort_pending_client()
            error = self._last_timeout or self.deadline.timeout_error(
                "transport.close",
                cleanup_pending=True,
                abort_requested=abort_requested,
            )
            error.mark_cleanup_pending(abort_requested=abort_requested)
            self._last_timeout = error
            raise error from exc
        self._thread.join(timeout=self.deadline.remaining(cleanup=True))
        if self._thread.is_alive():
            abort_requested = self._abort_pending_client()
            error = self._last_timeout or self.deadline.timeout_error(
                "transport.close",
                cleanup_pending=True,
                abort_requested=abort_requested,
            )
            error.mark_cleanup_pending(abort_requested=abort_requested)
            self._last_timeout = error
            raise error
        if self._last_timeout is not None:
            self._last_timeout.cleanup_pending = False
        if not ok:
            raise payload

    def _request(
        self,
        operation: str,
        *args: Any,
        phase: str,
        timeout: float | None = None,
        cleanup: bool = False,
        **kwargs: Any,
    ) -> Any:
        if self._closed.is_set():
            raise RuntimeError("WAAPI gateway transport is closed")
        now = time.monotonic()
        global_expires_at = self.deadline.cleanup_expires_at if cleanup else self.deadline.expires_at
        local_expires_at = global_expires_at if timeout is None else now + timeout
        expires_at = min(global_expires_at, local_expires_at)
        operation_timeout = max(0.0, expires_at - now)
        if operation_timeout <= 0:
            error = self.deadline.timeout_error(
                phase,
                operation_timeout=operation_timeout,
                cleanup_pending=self._thread.is_alive(),
            )
            self._last_timeout = error
            raise error
        response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        request = _TransportRequest(
            request_id=uuid.uuid4().hex,
            phase=phase,
            operation=operation,
            args=args,
            kwargs=kwargs,
            response=response,
            expires_at=expires_at,
            cancelled=threading.Event(),
        )
        self._requests.put(request)
        try:
            ok, payload = response.get(timeout=max(0.0, expires_at - time.monotonic()))
        except queue.Empty as exc:
            request.cancelled.set()
            abort_requested = self._abort_pending_client()
            error = self.deadline.timeout_error(
                phase,
                operation_timeout=operation_timeout,
                cleanup_pending=self._thread.is_alive(),
                abort_requested=abort_requested,
            )
            self._last_timeout = error
            raise error from exc
        if ok:
            return payload
        raise payload

    def _close_request(self) -> _TransportRequest:
        return _TransportRequest(
            request_id=uuid.uuid4().hex,
            phase="transport.close",
            operation="close",
            args=(),
            kwargs={},
            response=queue.Queue(maxsize=1),
            expires_at=self.deadline.cleanup_expires_at,
            cancelled=threading.Event(),
        )

    def _abort_pending_client(self) -> bool:
        """Best-effort, non-blocking cancellation for the packaged waapi-client.

        waapi-client 0.8.x has no public RPC cancellation API. Stopping its
        private event loop closes the WAMP transport and releases the owner call;
        no arbitrary injected method is invoked because that could itself block.
        """

        client = self._client
        loop = getattr(client, "_loop", None)
        call_soon_threadsafe = getattr(loop, "call_soon_threadsafe", None)
        stop = getattr(loop, "stop", None)
        if not callable(call_soon_threadsafe) or not callable(stop):
            return False
        try:
            call_soon_threadsafe(stop)
        except BaseException:  # noqa: BLE001 - abort must never mask the timeout
            return False
        return True

    @staticmethod
    def _deliver(request: _TransportRequest, payload: tuple[bool, Any]) -> None:
        if request.cancelled.is_set():
            return
        try:
            request.response.put_nowait(payload)
        except queue.Full:
            return

    def _run(self) -> None:
        try:
            client = self.client_factory(self.url)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the creating thread
            if not self._abandoned.is_set():
                self._ready.put((False, exc))
            return
        self._client = client
        subscriptions: dict[int, Any] = {}
        next_subscription_token = 1
        if self._abandoned.is_set():
            _close_transport_client(client, subscriptions)
            return
        self._ready.put((True, None))
        while True:
            request = self._requests.get()
            if request.operation != "close" and (
                request.cancelled.is_set() or time.monotonic() >= request.expires_at
            ):
                continue
            try:
                if request.operation == "close":
                    self._deliver(request, _close_transport_client(client, subscriptions))
                    return
                if request.operation == "call":
                    uri, args = request.args
                    options = request.kwargs.get("options")
                    if args is None and options is None:
                        result = client.call(uri)
                    elif options is None:
                        result = client.call(uri, args)
                    elif args is None:
                        result = client.call(uri, options=options)
                    else:
                        result = client.call(uri, args, options=options)
                elif request.operation == "subscribe":
                    uri, callback = request.args
                    options = request.kwargs.get("options")
                    result = client.subscribe(uri, callback) if options is None else client.subscribe(uri, callback, options)
                    if result is not None:
                        token = next_subscription_token
                        next_subscription_token += 1
                        subscriptions[token] = result
                        result = _TransportSubscription(token)
                elif request.operation == "unsubscribe":
                    (subscription,) = request.args
                    if not isinstance(subscription, _TransportSubscription):
                        raise TypeError("GatewayTransport.unsubscribe requires an opaque transport subscription")
                    handler = subscriptions.pop(subscription.token, None)
                    result = False if handler is None else _unsubscribe_event_handler(client, handler)
                else:
                    method = getattr(client, request.operation)
                    result = method(*request.args, **dict(request.kwargs))
                self._deliver(request, (True, result))
            except BaseException as exc:  # noqa: BLE001 - transferred to the requesting thread
                self._deliver(request, (False, exc))


def _close_transport_client(client: Any, subscriptions: dict[int, Any]) -> tuple[bool, Any]:
    """Clean one owner-thread client and preserve the first cleanup failure."""

    cleanup_error: BaseException | None = None
    for token, handler in tuple(subscriptions.items()):
        try:
            _unsubscribe_event_handler(client, handler)
        except BaseException as exc:  # noqa: BLE001 - transferred to the closing thread
            if cleanup_error is None:
                cleanup_error = exc
        finally:
            subscriptions.pop(token, None)
    try:
        disconnect = getattr(client, "disconnect", None)
        result = disconnect() if callable(disconnect) else None
    except BaseException as exc:  # noqa: BLE001 - transferred to the closing thread
        if cleanup_error is None:
            cleanup_error = exc
        result = None
    return cleanup_error is None, result if cleanup_error is None else cleanup_error


def _unsubscribe_event_handler(client: Any, handler: Any) -> Any:
    """Unsubscribe one raw handler while executing on the transport owner thread."""

    unsubscribe = getattr(handler, "unsubscribe", None)
    if callable(unsubscribe):
        return unsubscribe()
    client_unsubscribe = getattr(client, "unsubscribe", None)
    if callable(client_unsubscribe):
        return client_unsubscribe(handler)
    raise RuntimeError("WAAPI subscription handler cannot be unsubscribed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway.py",
        description="Call the manifest-backed WAAPI Skill gateway and print one JSON result.",
    )
    parser.add_argument("--host", help=f"WAAPI host; defaults to ${ENV_HOST}, then saved config")
    parser.add_argument("--port", type=int, help=f"WAAPI port; defaults to ${ENV_PORT}, then saved config")
    parser.add_argument(
        "--version",
        "--wwise-version",
        dest="version",
        help=f"Expected Wwise year.major; defaults to ${ENV_VERSION}, then saved config, then live detection",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            f"Whole-command deadline in seconds; defaults to {DEFAULT_TIMEOUT:g} for reads/topics "
            f"and {DEFAULT_TRANSACTION_TIMEOUT:g} for preview/execute/verify transactions"
        ),
    )
    parser.add_argument("--evidence-dir", help=f"Dispatcher evidence directory; defaults to ${ENV_EVIDENCE_DIR}")
    parser.add_argument("--state-dir", help=f"Transaction state directory; defaults to ${STATE_DIRECTORY_ENV}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Return live Wwise version and current project information")
    subparsers.add_parser("buses", help="Return all Bus objects with id, name, type, and path")
    subparsers.add_parser("selected", help="Return current UI selection or a clear command-line/UI boundary")

    query_object = subparsers.add_parser(
        "query-object",
        help="Run a source-grounded read-only object query without composing WAAPI code",
    )
    query_source = query_object.add_mutually_exclusive_group(required=True)
    query_source.add_argument("--path")
    query_source.add_argument("--object-id")
    query_source.add_argument("--type", dest="object_type")
    query_source.add_argument("--search")
    query_source.add_argument(
        "--query",
        metavar="QUERY_PATH_OR_GUID",
        help=(
            "Query Editor object specifier: canonical {GUID} or absolute "
            r"\Queries\... path; raw WAQL is not accepted"
        ),
    )
    query_object.add_argument("--where-json")
    query_object.add_argument(
        "--select",
        action="append",
        choices=SUPPORTED_SELECTS,
        help="Append one supported read-only WAQL select transform",
    )
    query_bound = query_object.add_mutually_exclusive_group()
    query_bound.add_argument(
        "--take",
        type=int,
        metavar=f"0..{MAX_QUERY_TAKE}",
        help=f"Bound returned rows to at most {MAX_QUERY_TAKE}; larger values fail closed",
    )
    query_bound.add_argument(
        "--all-results",
        action="store_true",
        help="Explicitly allow an unbounded broad query; otherwise broad sources/selects require --take",
    )
    query_object.add_argument("--return-field", action="append", dest="return_fields")

    metadata = subparsers.add_parser(
        "metadata",
        help="Run one fixed property/reference metadata query through its semantic builder",
    )
    metadata.add_argument(
        "operation",
        choices=("types", "names", "property-info", "property-enabled", "attenuation-curve"),
    )
    metadata.add_argument("--object")
    metadata.add_argument("--class-id", type=int)
    metadata.add_argument("--property")
    metadata.add_argument("--platform")
    metadata.add_argument("--curve-type")
    metadata.add_argument(
        "--summary-only",
        action="store_true",
        help=(
            "For metadata types only, omit the normalized type inventory and return "
            "the packaged count/ActorMixer projection"
        ),
    )

    wait_topic = subparsers.add_parser(
        "wait-topic",
        help="Wait once for a manifest topic, with a bounded timeout, optional payload match, and guaranteed cleanup",
    )
    wait_topic.add_argument("api")
    wait_topic.add_argument("--options-json", default="{}")
    wait_topic.add_argument("--match-json", default="{}")

    capabilities = subparsers.add_parser(
        "capabilities",
        help="List a compact packaged version-aware capability matrix without connecting to Wwise",
        description=(
            "Start with --summary-only for a broad overview, then add filters for compact rows. "
            "Use describe <uri> for one known capability."
        ),
    )
    capabilities.add_argument("--all-versions", action="store_true")
    capabilities.add_argument("--category")
    capabilities.add_argument("--item-type", choices=("function", "topic"))
    capabilities.add_argument("--family")
    capabilities.add_argument("--route")
    capabilities.add_argument("--query", help="Case-insensitive URI substring filter")
    capabilities.add_argument(
        "--summary-only",
        action="store_true",
        help="Return aggregate counts without any capability rows",
    )
    capabilities.add_argument(
        "--detail",
        action="store_true",
        help="Expand returned rows with interface, schema-summary, policy, and evidence detail",
    )
    capabilities.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum returned rows; defaults to 50, while 0 explicitly returns every match",
    )

    describe = subparsers.add_parser(
        "describe",
        help="Describe one URI, its schema, stable route, safety gate, and evidence boundary offline",
    )
    describe.add_argument("api")
    describe.add_argument("--all-versions", action="store_true")
    describe.add_argument(
        "--full-schema",
        action="store_true",
        help="Include the complete reflected schema; defaults to a compact schema summary",
    )

    operations = subparsers.add_parser(
        "operations",
        help="List compact transaction operations and explicit non-executable boundaries offline",
        description=(
            "Return the compact broad operation inventory. For one named operation, use "
            "operation-schema <name> directly."
        ),
    )
    operations.add_argument(
        "--detail",
        action="store_true",
        help="Expand inventory rows with nested request contracts, constraints, and identity rules",
    )
    operation_schema = subparsers.add_parser(
        "operation-schema",
        help="Describe one closed operation request shape and its execution boundary offline",
    )
    operation_schema.add_argument("operation")

    subparsers.add_parser(
        "config-show",
        help="Show effective public config and its external/legacy source without connecting to Wwise",
    )
    config_set = subparsers.add_parser(
        "config-set",
        help="Atomically save public config outside the Skill checkout without connecting to Wwise",
    )
    config_set.add_argument(
        "--reset",
        action="store_true",
        help="Replace an unreadable or invalid external config with validated defaults before applying changes",
    )
    config_set.add_argument("--wwise-version")
    config_set.add_argument("--clear-wwise-version", action="store_true")
    config_set.add_argument("--waapi-host")
    config_set.add_argument("--waapi-port")
    config_set.add_argument("--clear-waapi-port", action="store_true")
    config_set.add_argument("--project-modification-policy")

    transaction_show = subparsers.add_parser(
        "transaction-show",
        help="Show one immutable preview, durable state, and hash-chained event journal offline",
    )
    transaction_show.add_argument("transaction_id")
    transaction_show.add_argument(
        "--summary-only",
        action="store_true",
        help="Return the request, prepared change summary, guard fingerprints, and event-chain summary without raw artifact internals",
    )

    confirm = subparsers.add_parser(
        "confirm",
        help="Bind explicit confirmation to one immutable preview hash without connecting to Wwise",
    )
    confirm.add_argument("transaction_id")
    confirm.add_argument("--artifact-hash", required=True)

    reject = subparsers.add_parser("reject", help="Reject one awaiting transaction without connecting to Wwise")
    reject.add_argument("transaction_id")
    reject.add_argument("--reason", default="rejected by user")

    preview = subparsers.add_parser(
        "preview",
        help="Live-resolve a closed operation, persist an immutable preview, and await confirmation",
    )
    preview.add_argument("--request-json", required=True)
    preview.add_argument("--ttl", type=int, default=DEFAULT_PREVIEW_TTL_SECONDS)

    execute = subparsers.add_parser(
        "execute",
        help="Execute exactly one confirmed immutable transaction after guard and role revalidation",
    )
    execute.add_argument("transaction_id")

    verify = subparsers.add_parser(
        "verify",
        help="Verify one executed transaction with its operation-specific readback",
    )
    verify.add_argument("transaction_id")

    call = subparsers.add_parser(
        "call",
        help="Dispatch one reviewed manifest-dispatch read-only WAAPI function",
    )
    call.add_argument("api")
    call.add_argument("--args-json", default="{}")
    call.add_argument("--options-json", default="{}")
    call.add_argument("--dry-run", action="store_true")
    call.add_argument("--allow-destructive", action="store_true", help=argparse.SUPPRESS)
    call.add_argument("--topic-mode", default="wait")
    call.add_argument("--live-behavior", action="store_true")
    return parser


def execute_gateway(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> tuple[int, dict[str, Any]]:
    exit_code, payload = _execute_gateway_unconstrained(
        argv,
        env=env,
        client_factory=client_factory,
    )
    if payload.get("command") in OFFLINE_COMMANDS:
        return exit_code, payload
    return constrain_live_gateway_result(exit_code, payload)


def _execute_gateway_unconstrained(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> tuple[int, dict[str, Any]]:
    args = build_parser().parse_args(argv)
    source_env = dict(os.environ if env is None else env)
    runtime_endpoint: dict[str, Any] | None = None
    runtime_detected_version: str | None = None

    def finish(exit_code: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        enriched = dict(payload)
        if runtime_endpoint is not None and "endpoint" not in enriched:
            enriched["endpoint"] = dict(runtime_endpoint)
        if runtime_detected_version is not None and "detected_version" not in enriched:
            enriched["detected_version"] = runtime_detected_version
        return exit_code, attach_gateway_session_context(
            enriched,
            args=args,
            env=source_env,
        )

    cleanup_failure: BaseException | None = None
    post_result_cleanup_failed = False
    try:
        if args.command == "execute":
            require_project_modification_policy(env=source_env, action="execution")
        route_boundary = preflight_public_route(args, env=source_env)
        if route_boundary is not None:
            return finish(2, route_boundary)
        preflight_json_inputs(args)
        if args.command == "query-object":
            preflight_query_object_input(args, env=source_env)
        if args.command == "metadata":
            preflight_metadata_input(args)
        if args.command in OFFLINE_COMMANDS:
            payload = dispatch_offline_command(args, env=source_env)
            return finish(0 if payload.get("ok") else 2, payload)
        connection = resolve_connection(args, env=source_env)
        runtime_endpoint = {
            "host": connection.host,
            "port": connection.port,
            "url": connection.url,
        }
        factory = client_factory or default_client_factory
        transport = GatewayTransport(connection.url, factory, deadline=connection.deadline)
        try:
            live_info = transport.call_with_timeout(
                GET_INFO_URI,
                timeout=connection.deadline.require_remaining("version_detection.getInfo"),
                phase="version_detection.getInfo",
            )
            detected_version = version_key_from_get_info(require_mapping(live_info, "getInfo response"))
            runtime_detected_version = detected_version
            if connection.version_hint and connection.version_hint != detected_version:
                raise GatewayInputError(
                    f"Connected Wwise is {detected_version}, but the requested version is {connection.version_hint}"
                )
            dispatcher = WwiseDispatcher(client=transport)
            payload = dispatch_command(
                args,
                env=source_env,
                connection=connection,
                detected_version=detected_version,
                live_info=require_mapping(live_info, "getInfo response"),
                dispatcher=dispatcher,
            )
            if payload.get("ok"):
                connection.deadline.require_remaining(f"finalize {args.command}")
        except Exception as primary_exc:
            try:
                transport.close()
                if isinstance(primary_exc, GatewayTimeoutError):
                    primary_exc.cleanup_pending = False
            except BaseException as cleanup_exc:  # noqa: BLE001 - cleanup never masks the primary error
                cleanup_failure = cleanup_exc
                if isinstance(primary_exc, GatewayTimeoutError):
                    primary_exc.mark_cleanup_pending(
                        abort_requested=isinstance(cleanup_exc, GatewayTimeoutError)
                        and cleanup_exc.abort_requested
                    )
            raise
        else:
            try:
                transport.close()
            except BaseException as cleanup_exc:  # noqa: BLE001 - preserve completed business facts
                payload = attach_cleanup_failure(payload, cleanup_exc)
                post_result_cleanup_failed = True
            else:
                _finalize_timeout_cleanup(payload)
    except Exception as exc:  # noqa: BLE001 - the CLI always returns structured failure JSON
        normalized = normalize_gateway_exception(exc)
        details = normalized.get("details")
        if cleanup_failure is not None:
            merged_details = dict(details) if isinstance(details, Mapping) else {}
            merged_details["cleanup_failure"] = cleanup_failure_evidence(cleanup_failure)
            details = merged_details
        return finish(2, {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": False,
            "status": "error",
            "command": getattr(args, "command", None),
            "error_code": normalized["error_code"],
            "message": normalized["message"],
            "details": details,
        })
    # ``ok`` describes the completed WAAPI/business operation. A non-zero exit
    # with ``ok: true`` means only post-result cleanup failed; callers must keep
    # mutation execution facts and must not infer that retrying is safe.
    exit_code = 2 if post_result_cleanup_failed else (0 if payload.get("ok") else 2)
    return finish(exit_code, payload)


def constrain_live_gateway_result(
    exit_code: int,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Bound the complete live gateway document, including its outer envelope."""

    probe = probe_gateway_json_document_size(payload, MAX_GATEWAY_RESULT_JSON_BYTES)
    if probe == "ok":
        return exit_code, payload
    error_code = "RESULT_TOO_LARGE" if probe == "too_large" else "RESULT_NOT_JSON"
    reason = (
        "The final live gateway result exceeded the public JSON size limit"
        if probe == "too_large"
        else "The final live gateway result is not a strict JSON document"
    )
    details: dict[str, Any] = {
        "provenance": GATEWAY_RESULT_CEILING_PROVENANCE,
        "original_ok": payload.get("ok") is True,
        "original_status": bounded_gateway_label(payload.get("status"), 80),
    }
    if probe == "too_large":
        details.update(
            {
                "limit_bytes": MAX_GATEWAY_RESULT_JSON_BYTES,
                "observed_at_least_bytes": MAX_GATEWAY_RESULT_JSON_BYTES + 1,
            }
        )
    result: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "error",
        "command": bounded_gateway_label(payload.get("command"), 80),
        "error_code": error_code,
        "message": reason,
        "details": details,
    }
    session_context = payload.get("session_context")
    if isinstance(session_context, Mapping):
        result["session_context"] = dict(session_context)
    for key, maximum in (
        ("detected_version", 32),
        ("transaction_id", 128),
        ("state", 80),
        ("artifact_hash", 128),
    ):
        value = bounded_gateway_label(payload.get(key), maximum)
        if value is not None:
            result[key] = value
    for key in ("executed", "verified", "automatic_retry"):
        if isinstance(payload.get(key), bool):
            result[key] = payload[key]
    return 2, result


def probe_gateway_json_document_size(value: Any, limit_bytes: int) -> str:
    """Return ok/too_large/not_json for the exact pretty stdout document."""

    encoder = gateway_stdout_json_encoder()
    observed = 0
    try:
        for chunk in encoder.iterencode(value):
            observed += len(chunk.encode("utf-8"))
            if observed > limit_bytes:
                return "too_large"
        observed += 1  # print() appends one newline
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        return "not_json"
    return "too_large" if observed > limit_bytes else "ok"


def gateway_stdout_json_encoder() -> json.JSONEncoder:
    """Build the strict, insertion-ordered encoder used for gateway stdout."""

    return json.JSONEncoder(
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        allow_nan=False,
        check_circular=True,
    )


def bounded_gateway_label(value: Any, maximum_bytes: int) -> str | None:
    if not isinstance(value, str) or len(value) > maximum_bytes:
        return None
    try:
        return value if len(value.encode("utf-8")) <= maximum_bytes else None
    except UnicodeEncodeError:
        return None


def cleanup_failure_evidence(exc: BaseException) -> dict[str, Any]:
    """Attach cleanup failure evidence without replacing the primary failure."""

    normalized = normalize_gateway_exception(exc)
    evidence: dict[str, Any] = {
        "error_code": normalized["error_code"],
        "message": normalized["message"],
    }
    details = normalized.get("details")
    if isinstance(details, dict):
        evidence["details"] = details
    return evidence


def normalize_gateway_exception(exc: BaseException) -> dict[str, Any]:
    """Normalize one gateway exception without trusting its string or metadata hooks."""

    if isinstance(exc, SemanticValidationError):
        error_code = safe_type_name(exc, "Exception")
    elif isinstance(exc, TimeoutError):
        error_code = "TIMEOUT"
    else:
        has_error_code, candidate = safe_exception_attribute(exc, "error_code")
        error_code = (
            candidate
            if has_error_code and isinstance(candidate, str) and candidate
            else None
        )
        if error_code is None:
            error_code = safe_type_name(exc, "Exception")
    try:
        return normalize_dispatcher_exception(exc, error_code=error_code)
    except BaseException:  # noqa: BLE001 - the public CLI must fail closed on hostile exceptions
        return {
            "error_code": "ERROR_NORMALIZATION_FAILED",
            "message": "The underlying error could not be normalized safely",
        }


def attach_cleanup_failure(payload: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    """Preserve one completed business result and append bounded close evidence."""

    result = dict(payload)
    current_details = result.get("details")
    details = current_details.copy() if type(current_details) is dict else {}
    details["cleanup_failure"] = cleanup_failure_evidence(exc)
    result["details"] = details
    return result


def _finalize_timeout_cleanup(value: Any) -> None:
    """Mark copied timeout evidence complete after transport.close succeeds."""

    if isinstance(value, dict):
        details = value.get("details")
        if (
            value.get("error_code") == "TIMEOUT"
            and isinstance(details, dict)
            and details.get("provenance") == GATEWAY_DEADLINE_PROVENANCE
        ):
            details["cleanup_pending"] = False
        for item in value.values():
            _finalize_timeout_cleanup(item)
    elif isinstance(value, list):
        for item in value:
            _finalize_timeout_cleanup(item)


def query_object_required_payload(*, common: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "query_object_required",
        "command": "call",
        "api": OBJECT_GET_URI,
        "error_code": "QUERY_OBJECT_REQUIRED",
        "message": (
            "The public generic call path does not accept ak.wwise.core.object.get. "
            "Use query-object so WAQL sources, result bounds, and exact-identity "
            "normalization remain inside the packaged query contract."
        ),
        "required_command": "query-object",
        "executed": False,
    }
    if common is not None:
        payload.update(dict(common))
    return payload


def fixed_command_required_payload(
    api: str,
    commands: Sequence[str],
    *,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep reviewed fixed-function URIs inside their packaged command contracts."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "fixed_command_required",
        "command": "call",
        "api": api,
        "error_code": "FIXED_COMMAND_REQUIRED",
        "message": (
            f"The public generic call path does not accept {api}. "
            f"Use its packaged fixed command: {', '.join(commands)}."
        ),
        "required_commands": list(commands),
        "executed": False,
    }
    if len(commands) == 1:
        payload["required_command"] = commands[0]
    if common is not None:
        payload.update(dict(common))
    return payload


def wait_topic_required_payload(api: str, *, common: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Keep reviewed topic observation inside the bounded wait contract."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "wait_topic_required",
        "command": "call",
        "api": api,
        "error_code": "WAIT_TOPIC_REQUIRED",
        "message": (
            f"The public generic call path does not accept topic {api}. "
            "Use wait-topic so the observation is deadline-bounded and always unsubscribed."
        ),
        "required_command": "wait-topic",
        "executed": False,
    }
    if common is not None:
        payload.update(dict(common))
    return payload


def unsupported_interface_payload(
    api: str,
    reason: str,
    *,
    command: str,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject one catalog safety boundary before business dispatch or subscription."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "unsupported_by_skill_interface",
        "command": command,
        "api": api,
        "error_code": "UNSUPPORTED_BY_SKILL_INTERFACE",
        "message": reason,
        "executed": False,
    }
    if common is not None:
        payload.update(dict(common))
    return payload


def unreflected_interface_payload(
    api: str,
    version: str,
    *,
    command: str,
    common: Mapping[str, Any] | None = None,
    safety_context: str | None = None,
) -> dict[str, Any]:
    """Return the public unsupported boundary for a URI absent from one manifest."""

    message = (
        f"WAAPI URI {api!r} is not reflected by Wwise {version} and has no "
        "packaged executable route in the Skill interface."
    )
    if safety_context:
        message += f" The immutable Skill safety policy also blocks this URI: {safety_context}"
    return unsupported_interface_payload(
        api,
        message,
        command=command,
        common=common,
    )


def transaction_required_payload(
    api: str,
    *,
    capability: CapabilityRecord | None = None,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep a closed mutation URI out of generic call, including dry-run."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "transaction_required",
        "command": "call",
        "api": api,
        "error_code": "TRANSACTION_REQUIRED",
        "message": (
            "This URI is available only through the packaged preview, confirmation, execution, "
            "and verification transaction interface; generic call and --dry-run cannot bypass it."
        ),
        "executed": False,
        "verified": False,
    }
    if capability is not None:
        payload["capability"] = capability.as_dict(detail=False)
    if common is not None:
        payload.update(dict(common))
    return payload


def catalog_route_boundary_payload(
    capability: CapabilityRecord,
    *,
    command: str,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Translate the catalog's one public route into a gateway boundary payload."""

    if command == "wait-topic":
        if capability.item_type != "topic":
            raise GatewayInputError(
                f"wait-topic requires a reflected topic URI, got {capability.item_type}: {capability.uri}"
            )
        if capability.safety.interface_status == "unsupported_by_skill_interface":
            return unsupported_interface_payload(
                capability.uri,
                capability.safety.reason,
                command="wait-topic",
                common=common,
            )
        if capability.preferred_route != "bounded_topic_wait":
            return unsupported_interface_payload(
                capability.uri,
                "This topic has no reviewed bounded wait route in the packaged Skill interface.",
                command="wait-topic",
                common=common,
            )
        return None

    if command != "call":
        return None
    if capability.item_type == "topic":
        if capability.safety.interface_status == "unsupported_by_skill_interface":
            return unsupported_interface_payload(
                capability.uri,
                capability.safety.reason,
                command="call",
                common=common,
            )
        return wait_topic_required_payload(capability.uri, common=common)
    if capability.safety.interface_status == "unsupported_by_skill_interface":
        return unsupported_interface_payload(
            capability.uri,
            capability.safety.reason,
            command="call",
            common=common,
        )
    if capability.preferred_route == "fixed_command":
        if capability.uri == OBJECT_GET_URI:
            return query_object_required_payload(common=common)
        return fixed_command_required_payload(
            capability.uri,
            capability.fixed_commands,
            common=common,
        )
    if capability.preferred_route == "transaction_operation":
        return transaction_required_payload(
            capability.uri,
            capability=capability,
            common=common,
        )
    if capability.preferred_route == "manifest_dispatch":
        return None
    return unsupported_interface_payload(
        capability.uri,
        "The catalog does not expose a public generic-call route for this URI.",
        command="call",
        common=common,
    )


def preflight_public_route(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> dict[str, Any] | None:
    """Fail closed before connecting when the requested public route is already known."""

    if args.command not in {"call", "wait-topic"}:
        return None
    api = args.api

    # When a version is already known, the versioned packaged manifest is the
    # first authority. Cross-version safety/route allowlists intentionally
    # contain APIs that do not exist in every release; consulting them first
    # could otherwise recommend a fixed command or topic wait for an API that
    # this exact Wwise version does not reflect.
    config = load_gateway_config(env).config
    version = args.version or env.get(ENV_VERSION) or config.wwise_version
    if version is not None:
        if version not in SUPPORTED_WWISE_VERSION_KEYS:
            raise GatewayInputError(
                f"Unsupported Wwise version {version!r}; supported versions: "
                f"{', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
            )
        try:
            capability = CapabilityCatalog().describe(str(version), api)
        except CapabilityNotFoundError:
            safety_context = None
            if args.command == "call":
                safety_context = (
                    EXPLICIT_UNSUPPORTED_LIVE_URIS.get(api)
                    or BOUNDED_CALL_CANDIDATES.get(api)
                    or EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(api)
                )
            elif args.command == "wait-topic":
                safety_context = EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(api)
            return unreflected_interface_payload(
                api,
                str(version),
                command=args.command,
                safety_context=safety_context,
            )
        return catalog_route_boundary_payload(capability, command=args.command)

    # With no configured version, retain the static bootstrap boundaries that
    # can reject or redirect a request without opening WAAPI. If no such
    # boundary applies, live getInfo detection selects the manifest later.
    if args.command == "call":
        if api == OBJECT_GET_URI:
            return query_object_required_payload()
        fixed_commands = FIXED_COMMANDS_BY_URI.get(api)
        if fixed_commands is not None:
            return fixed_command_required_payload(api, fixed_commands)
        explicit_function_boundary = (
            EXPLICIT_UNSUPPORTED_LIVE_URIS.get(api)
            or BOUNDED_CALL_CANDIDATES.get(api)
        )
        if explicit_function_boundary is not None:
            return unsupported_interface_payload(
                api,
                explicit_function_boundary,
                command="call",
            )
        if api in REVIEWED_TOPIC_URIS:
            return wait_topic_required_payload(api)
        explicit_topic_boundary = EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(api)
        if explicit_topic_boundary is not None:
            return unsupported_interface_payload(
                api,
                explicit_topic_boundary,
                command="call",
            )
    else:
        explicit_topic_boundary = EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(api)
        if explicit_topic_boundary is not None:
            return unsupported_interface_payload(
                api,
                explicit_topic_boundary,
                command="wait-topic",
            )
    return None


def preflight_query_object_input(args: argparse.Namespace, *, env: Mapping[str, str]) -> None:
    """Reject closed query input errors before opening a WAAPI transport."""

    where = parse_optional_json(args.where_json, "--where-json")
    return_fields = tuple(args.return_fields or ("id", "name", "type", "path"))
    _require_exact_identity_return_field(args, return_fields)
    (preflight_version,) = resolve_catalog_versions(args, env=env)
    build_object_get_query(
        path=args.path,
        object_id=args.object_id,
        type=args.object_type,
        search=args.search,
        query=args.query,
        where=where,
        select=tuple(args.select or ()),
        take=args.take,
        return_fields=return_fields,
        version=preflight_version,
    )
    _require_explicit_query_bound(args)


def preflight_metadata_input(args: argparse.Namespace) -> None:
    """Reject metadata projection modes that have no packaged result contract."""

    if args.summary_only and args.operation != "types":
        raise GatewayInputError("metadata --summary-only is supported only for the types operation")


def preflight_json_inputs(args: argparse.Namespace) -> None:
    """Validate every command-line JSON document before opening WAAPI."""

    if args.command == "call":
        parse_json_object(args.args_json, "--args-json")
        parse_json_object(args.options_json, "--options-json")
    elif args.command == "wait-topic":
        parse_json_object(args.options_json, "--options-json")
        parse_json_object(args.match_json, "--match-json")
    elif args.command == "preview":
        parse_json_object(args.request_json, "--request-json")


def dispatch_offline_command(args: argparse.Namespace, *, env: Mapping[str, str]) -> dict[str, Any]:
    """Run catalog commands without requiring a WAAPI port or live Wwise."""

    if args.command == "config-show":
        return config_result_payload("config-show", load_gateway_config(env))
    if args.command == "config-set":
        changes = parse_config_set_changes(args)
        if args.reset:
            try:
                external_path = resolve_external_config_path(env, skill_root=SKILL_ROOT)
            except ValueError as exc:
                raise GatewayInputError(f"Public WAAPI Skill config path is invalid: {exc}") from exc
            config = SkillConfig(SKILL_ROOT)
            resolution = ResolvedSkillConfig(
                config=config,
                source="reset_defaults",
                external_path=external_path,
                legacy_path=config.config_path,
                legacy_fallback_used=False,
            )
        else:
            resolution = load_gateway_config(env)
        config = resolution.config
        for field, value in changes.items():
            setattr(config, field, value)
        try:
            config.save(resolution.external_path)
        except (OSError, ValueError) as exc:
            raise GatewayInputError(f"Could not save public WAAPI Skill config: {exc}") from exc
        saved = load_gateway_config(env)
        return config_result_payload(
            "config-set",
            saved,
            changed_fields=tuple(changes),
            migrated_from_legacy=resolution.legacy_fallback_used,
            reset=bool(args.reset),
        )

    if args.command == "capabilities":
        catalog = CapabilityCatalog()
        versions = resolve_catalog_versions(args, env=env)
        if args.limit < 0:
            raise GatewayInputError("--limit must be zero or greater")
        selected = []
        for version in versions:
            selected.extend(
                catalog.select(
                    version,
                    category=args.category,
                    item_type=args.item_type,
                    semantic_family=args.family,
                    preferred_route=args.route,
                    query=args.query,
                )
            )
        total_matches = len(selected)
        visible = selected[: args.limit] if args.limit else selected
        payload: dict[str, Any] = {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "capabilities",
            "offline": True,
            "versions": list(versions),
            "summary": catalog.summary(versions),
            "filters": {
                "category": args.category,
                "item_type": args.item_type,
                "semantic_family": args.family,
                "preferred_route": args.route,
                "query": args.query,
            },
            "match_count": total_matches,
            "returned_count": 0 if args.summary_only else len(visible),
            "truncated": (not args.summary_only) and len(visible) < total_matches,
        }
        if not args.summary_only:
            payload["capabilities"] = [
                entry.as_dict(detail=False) if args.detail else entry.as_compact_dict()
                for entry in visible
            ]
        return payload
    if args.command == "describe":
        catalog = CapabilityCatalog()
        versions = resolve_catalog_versions(args, env=env)
        availability: dict[str, Any] = {}
        found = 0
        for version in versions:
            try:
                entry = catalog.describe(version, args.api)
            except CapabilityNotFoundError:
                availability[version] = {
                    "available": False,
                    "status": "absent_from_version_manifest",
                    "fallback_allowed": False,
                }
            else:
                found += 1
                availability[version] = {
                    "available": True,
                    "capability": entry.as_dict(detail=bool(args.full_schema)),
                }
        if found == 0:
            raise CapabilityNotFoundError(
                f"WAAPI URI {args.api!r} is not reflected by requested versions: {', '.join(versions)}"
            )
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "describe",
            "offline": True,
            "api": args.api,
            "versions": list(versions),
            "schema_detail": "full" if args.full_schema else "summary",
            "availability": availability,
        }
    if args.command == "operations":
        operations = [
            spec.as_dict() if args.detail else spec.as_compact_dict()
            for spec in list_operation_specs()
        ]
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "operations",
            "offline": True,
            "count": len(operations),
            "implemented_count": sum(item["implemented"] is True for item in operations),
            "operations": operations,
        }
    if args.command == "operation-schema":
        spec = describe_operation(args.operation)
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok" if spec.implemented else "unsupported_boundary",
            "command": "operation-schema",
            "offline": True,
            "operation": spec.as_dict(),
        }
    if args.command in {"transaction-show", "confirm", "reject"}:
        store = resolve_transaction_store(args, env=env)
        transaction_id = args.transaction_id
        if args.command == "transaction-show":
            record = store.load(transaction_id)
            preview = store.load_preview(transaction_id)
            events = store.read_events(transaction_id)
            payload = {
                "contract": GATEWAY_RESULT_CONTRACT,
                "ok": True,
                "status": "ok",
                "command": "transaction-show",
                "offline": True,
                "transaction_id": transaction_id,
                "state": record.state.value,
                "artifact_hash": preview.artifact_hash,
            }
            if args.summary_only:
                payload.update(transaction_show_summary(preview.artifact, events))
            else:
                payload.update({"artifact": preview.artifact, "events": list(events)})
            return payload
        if args.command == "confirm":
            require_project_modification_policy(env=env, action="confirmation")
            record = store.confirm(transaction_id, artifact_hash=args.artifact_hash)
            return transaction_state_payload("confirm", record, offline=True)
        record = store.reject(transaction_id, details={"reason": args.reason})
        return transaction_state_payload("reject", record, offline=True)
    raise GatewayInputError(f"unsupported offline command: {args.command}")


def load_gateway_config(env: Mapping[str, str]) -> ResolvedSkillConfig:
    """Resolve the one public external-first config source used by the gateway."""

    try:
        return load_effective_skill_config(SKILL_ROOT, env=env)
    except (OSError, RecursionError, ValueError) as exc:
        raise GatewayInputError(f"Public WAAPI Skill config is invalid: {exc}") from exc


def attach_gateway_session_context(
    payload: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    env: Mapping[str, str],
) -> dict[str, Any]:
    """Attach bounded onboarding facts without opening another WAAPI connection."""

    agent_result = payload.get("agent_result")
    result = {key: value for key, value in payload.items() if key != "agent_result"}
    result["session_context"] = build_gateway_session_context(
        args=args,
        env=env,
        payload=payload,
    )
    if "agent_result" in payload:
        # Machine-readable callers rely on this projection remaining the final
        # insertion-ordered field so it can be emitted verbatim and then stop.
        result["agent_result"] = agent_result
    return result


def build_gateway_session_context(
    *,
    args: argparse.Namespace,
    env: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the user-facing address, adapter version, and mutation policy."""

    base: dict[str, Any] = {
        "contract": GATEWAY_SESSION_CONTEXT_CONTRACT,
        "available": False,
        "endpoint": {"host": None, "port": None, "url": None},
        "adapter_version": None,
        "adapter_version_source": "unavailable",
        "project_modification_policy": None,
        "available_project_modification_policies": list(PROJECT_MODIFICATION_POLICIES),
    }
    try:
        config = load_gateway_config(env).config
        effective = config.as_dict()
    except GatewayInputError:
        return base

    payload_endpoint = payload.get("endpoint")
    host: str | None = None
    port: int | None = None
    url: str | None = None
    if isinstance(payload_endpoint, Mapping):
        candidate_host = payload_endpoint.get("host")
        candidate_port = payload_endpoint.get("port")
        candidate_url = payload_endpoint.get("url")
        if isinstance(candidate_host, str) and candidate_host:
            host = candidate_host
        if isinstance(candidate_port, int) and not isinstance(candidate_port, bool):
            port = candidate_port
        if isinstance(candidate_url, str) and candidate_url:
            url = candidate_url

    if host is None:
        raw_host = args.host or env.get(ENV_HOST) or effective["waapi_host"] or DEFAULT_HOST
        try:
            host = SkillConfig(SKILL_ROOT, waapi_host=str(raw_host)).as_dict()["waapi_host"]
        except ValueError:
            host = None
    if port is None:
        raw_port: Any = args.port if args.port is not None else env.get(ENV_PORT)
        if raw_port is None:
            raw_port = effective["waapi_port"]
        try:
            candidate_port = int(raw_port) if raw_port is not None else None
        except (TypeError, ValueError):
            candidate_port = None
        if candidate_port is not None and 1 <= candidate_port <= 65535:
            port = candidate_port
    if url is None and host is not None and port is not None:
        url = f"ws://{host}:{port}/waapi"

    detected_version = payload.get("detected_version")
    configured_version = args.version or env.get(ENV_VERSION) or effective["wwise_version"]
    payload_versions = payload.get("versions")
    command_version = (
        str(payload_versions[0])
        if isinstance(payload_versions, Sequence)
        and not isinstance(payload_versions, (str, bytes, bytearray))
        and len(payload_versions) == 1
        and payload_versions[0] in SUPPORTED_WWISE_VERSION_KEYS
        else None
    )
    if detected_version in SUPPORTED_WWISE_VERSION_KEYS:
        adapter_version = str(detected_version)
        adapter_version_source = "live_detection"
    elif configured_version in SUPPORTED_WWISE_VERSION_KEYS:
        adapter_version = str(configured_version)
        adapter_version_source = "configured"
    elif command_version is not None:
        adapter_version = command_version
        adapter_version_source = "command_resolution"
    else:
        adapter_version = None
        adapter_version_source = "unavailable"

    policy = effective["project_modification_policy"]
    available = (
        host is not None
        and port is not None
        and url is not None
        and adapter_version is not None
        and policy is not None
    )

    return {
        "contract": GATEWAY_SESSION_CONTEXT_CONTRACT,
        "available": available,
        "endpoint": {"host": host, "port": port, "url": url},
        "adapter_version": adapter_version,
        "adapter_version_source": adapter_version_source,
        "project_modification_policy": policy,
        "available_project_modification_policies": list(PROJECT_MODIFICATION_POLICIES),
    }


def require_project_modification_policy(*, env: Mapping[str, str], action: str) -> None:
    """Re-read the external policy at both confirmation and execution boundaries."""

    policy = load_gateway_config(env).config.project_modification_policy
    if policy == "never":
        raise GatewayInputError(
            f"project_modification_policy=never blocks transaction {action}"
        )


def parse_config_set_changes(args: argparse.Namespace) -> dict[str, Any]:
    """Normalize one explicit config update before any filesystem write."""

    if args.wwise_version is not None and args.clear_wwise_version:
        raise GatewayInputError("--wwise-version and --clear-wwise-version are mutually exclusive")
    if args.waapi_port is not None and args.clear_waapi_port:
        raise GatewayInputError("--waapi-port and --clear-waapi-port are mutually exclusive")

    changes: dict[str, Any] = {}
    if args.wwise_version is not None:
        changes["wwise_version"] = args.wwise_version
    elif args.clear_wwise_version:
        changes["wwise_version"] = None
    if args.waapi_host is not None:
        changes["waapi_host"] = args.waapi_host
    if args.waapi_port is not None:
        try:
            changes["waapi_port"] = int(args.waapi_port)
        except (TypeError, ValueError) as exc:
            raise GatewayInputError(f"waapi_port must be an integer, got {args.waapi_port!r}") from exc
    elif args.clear_waapi_port:
        changes["waapi_port"] = None
    if args.project_modification_policy is not None:
        changes["project_modification_policy"] = args.project_modification_policy
    if not changes and not args.reset:
        raise GatewayInputError("config-set requires at least one public config change")
    return changes


def config_result_payload(
    command: str,
    resolution: ResolvedSkillConfig,
    *,
    changed_fields: Sequence[str] = (),
    migrated_from_legacy: bool = False,
    reset: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "config_contract": GATEWAY_CONFIG_CONTRACT,
        "ok": True,
        "status": "ok",
        "command": command,
        "offline": True,
        "effective": resolution.config.as_dict(),
        "source": resolution.source,
        "external_path": str(resolution.external_path),
        "legacy_fallback_used": resolution.legacy_fallback_used,
    }
    if command == "config-set":
        payload.update(
            {
                "saved": True,
                "changed_fields": list(changed_fields),
                "migrated_from_legacy": migrated_from_legacy,
                "reset": reset,
            }
        )
    return payload


def resolve_catalog_versions(args: argparse.Namespace, *, env: Mapping[str, str]) -> tuple[str, ...]:
    if bool(getattr(args, "all_versions", False)):
        return tuple(SUPPORTED_WWISE_VERSION_KEYS)
    config = load_gateway_config(env).config
    version = args.version or env.get(ENV_VERSION) or config.wwise_version or "2022.1"
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise GatewayInputError(
            f"Unsupported Wwise version {version!r}; supported versions: {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    return (str(version),)


def resolve_connection(args: argparse.Namespace, *, env: Mapping[str, str]) -> GatewayConnection:
    config = load_gateway_config(env).config
    host = args.host or env.get(ENV_HOST) or config.waapi_host or DEFAULT_HOST
    try:
        host = SkillConfig(SKILL_ROOT, waapi_host=str(host)).as_dict()["waapi_host"]
    except ValueError as exc:
        raise GatewayInputError(str(exc)) from exc
    raw_port: int | str | None = args.port if args.port is not None else env.get(ENV_PORT)
    if raw_port is None:
        raw_port = config.waapi_port
    if raw_port is None:
        raise GatewayInputError(
            f"WAAPI port is required via --port, ${ENV_PORT}, or saved config; "
            "use config-show/config-set to inspect or change saved values"
        )
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise GatewayInputError(f"WAAPI port must be an integer, got {raw_port!r}") from exc
    if not 1 <= port <= 65535:
        raise GatewayInputError(f"WAAPI port must be between 1 and 65535, got {port}")
    version_hint = args.version or env.get(ENV_VERSION) or config.wwise_version
    if version_hint is not None and version_hint not in SUPPORTED_WWISE_VERSION_KEYS:
        raise GatewayInputError(
            f"Unsupported Wwise version {version_hint!r}; supported versions: "
            f"{', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    evidence_text = args.evidence_dir or env.get(ENV_EVIDENCE_DIR)
    evidence_dir = (
        resolve_external_runtime_directory(
            evidence_text,
            label="--evidence-dir" if args.evidence_dir else f"${ENV_EVIDENCE_DIR}",
        )
        if evidence_text
        else None
    )
    raw_timeout = (
        args.timeout
        if args.timeout is not None
        else (
            DEFAULT_TRANSACTION_TIMEOUT
            if args.command in {"preview", "execute", "verify"}
            else DEFAULT_TIMEOUT
        )
    )
    if not math.isfinite(raw_timeout) or raw_timeout <= 0:
        raise GatewayInputError("timeout must be finite and greater than zero")
    timeout = float(raw_timeout)
    return GatewayConnection(
        host=host,
        port=port,
        version_hint=str(version_hint) if version_hint else None,
        evidence_dir=evidence_dir,
        timeout=timeout,
        deadline=GatewayDeadline.start(timeout),
    )


def dispatch_command(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
) -> dict[str, Any]:
    common = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "command": args.command,
        "endpoint": {"host": connection.host, "port": connection.port, "url": connection.url},
        "detected_version": detected_version,
        "is_command_line": bool(live_info.get("isCommandLine")),
    }
    if args.command == "status":
        info = dispatch(
            dispatcher,
            GET_INFO_URI,
            connection=connection,
            version=detected_version,
        )
        info_payload = (
            require_status_info(
                strict_call_result_mapping(
                    info,
                    command="status getInfo",
                    error_code="INVALID_STATUS_RESULT",
                ),
                expected_version=detected_version,
            )
            if info.get("ok")
            else None
        )
        if detected_version == "2021.1":
            project_call = dispatch(
                dispatcher,
                OBJECT_GET_URI,
                connection=connection,
                version=detected_version,
                args={"waql": "from type Project take 1"},
                options={"return": ["id", "name", "type", "path"]},
            )
            project_rows = (
                strict_object_get_rows(
                    project_call,
                    command="status project",
                    maximum_rows=1,
                    error_code="INVALID_STATUS_RESULT",
                )
                if project_call.get("ok")
                else []
            )
            project = (
                require_single_result_row(
                    project_rows,
                    command="status project",
                    error_code="INVALID_STATUS_RESULT",
                )
                if project_call.get("ok")
                else None
            )
        else:
            project_call = dispatch(
                dispatcher,
                GET_PROJECT_INFO_URI,
                connection=connection,
                version=detected_version,
            )
            project = (
                strict_call_result_mapping(
                    project_call,
                    command="status getProjectInfo",
                    error_code="INVALID_STATUS_RESULT",
                )
                if project_call.get("ok")
                else None
            )
        if project is not None:
            project = require_project_identity(
                project,
                command="status project",
                error_code="INVALID_STATUS_RESULT",
            )
        ok = bool(info.get("ok") and project_call.get("ok") and project is not None)
        return {
            "ok": ok,
            "status": "ok" if ok else "error",
            **common,
            "calls": [dispatch_call_summary(info), dispatch_call_summary(project_call)],
            "wwise": status_wwise_summary(info_payload),
            "project": status_project_summary(project),
        }
    if args.command == "buses":
        preview = build_object_get_query(
            type="Bus",
            take=MAX_QUERY_TAKE,
            return_fields=("id", "name", "type", "path"),
            version=detected_version,
        )
        envelope = preview.envelope
        result = dispatch(
            dispatcher,
            envelope.uri,
            connection=connection,
            version=detected_version,
            args=envelope.args,
            options=envelope.options,
        )
        rows = (
            strict_object_get_rows(
                result,
                command="buses",
                maximum_rows=MAX_QUERY_TAKE,
                required_string_fields=("id", "name", "type", "path"),
            )
            if result.get("ok")
            else []
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "semantic_preview": preview.as_dict(),
            "query_bound": {
                "mode": "take",
                "value": MAX_QUERY_TAKE,
                "source": "fixed-command-default",
            },
            "call": dispatch_call_summary(result),
            "count": len(rows) if result.get("ok") else None,
            "buses": rows if result.get("ok") else None,
            "possibly_truncated": (
                len(rows) == MAX_QUERY_TAKE if result.get("ok") else None
            ),
        }
    if args.command == "selected":
        result = dispatch(
            dispatcher,
            GET_SELECTED_URI,
            connection=connection,
            version=detected_version,
            args={},
            options={"return": ["id", "name", "type", "path"]},
        )
        if not result.get("ok") and selected_ui_boundary(result, live_info=live_info):
            absent = result.get("error_code") == "API_NOT_FOUND"
            return {
                "ok": True,
                "status": "unsupported_boundary",
                **common,
                "api_attempted": GET_SELECTED_URI,
                "call": dispatch_call_summary(result),
                "message": (
                    "ak.wwise.ui.getSelectedObjects is absent from this version's packaged manifest."
                    if absent
                    else (
                        "The connected Wwise instance is command-line/headless, so "
                        "ak.wwise.ui.getSelectedObjects is unavailable."
                    )
                ),
                "count": None,
                "objects": None,
            }
        rows = strict_selected_rows(result) if result.get("ok") else []
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "api_attempted": GET_SELECTED_URI,
            "call": dispatch_call_summary(result),
            "count": len(rows) if result.get("ok") else None,
            "objects": rows if result.get("ok") else None,
        }
    if args.command == "query-object":
        where = parse_optional_json(args.where_json, "--where-json")
        return_fields = tuple(args.return_fields or ("id", "name", "type", "path"))
        _require_exact_identity_return_field(args, return_fields)
        preview = build_object_get_query(
            path=args.path,
            object_id=args.object_id,
            type=args.object_type,
            search=args.search,
            query=args.query,
            where=where,
            select=tuple(args.select or ()),
            take=args.take,
            return_fields=return_fields,
            version=detected_version,
        )
        _require_explicit_query_bound(args)
        envelope = preview.envelope
        result = dispatch(
            dispatcher,
            envelope.uri,
            connection=connection,
            version=detected_version,
            args=envelope.args,
            options=envelope.options,
            exact_object_lookup=_canonical_exact_query_request(args),
        )
        rows = (
            strict_object_get_rows(
                result,
                command="query-object",
                maximum_rows=_query_result_maximum(args),
            )
            if result.get("ok")
            else []
        )
        if result.get("ok"):
            validate_exact_query_identity(args, rows)
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "semantic_preview": preview.as_dict(),
            "query_bound": _query_bound_summary(args),
            "call": dispatch_call_summary(result),
            "count": len(rows) if result.get("ok") else None,
            "objects": rows if result.get("ok") else None,
        }
    if args.command == "metadata":
        preview = build_metadata_command_preview(args, version=detected_version)
        envelope = preview.envelope
        result = dispatch(
            dispatcher,
            envelope.uri,
            connection=connection,
            version=detected_version,
            args=envelope.args,
            options=envelope.options,
        )
        normalized = normalize_metadata_result(args.operation, result) if result.get("ok") else None
        payload = {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "operation": args.operation,
            "semantic_preview": preview.as_dict(),
            "call": dispatch_call_summary(result),
        }
        if args.summary_only:
            payload["summary_only"] = True
            if result.get("ok"):
                if not isinstance(normalized, list):
                    raise GatewayResultShapeError(
                        "metadata types summary requires a normalized type array.",
                        details={"operation": args.operation},
                        error_code="INVALID_METADATA_RESULT",
                    )
                payload["agent_result"] = {
                    "count": len(normalized),
                    "contains_actor_mixer": any(
                        row.get("name") == "ActorMixer" or row.get("type") == "ActorMixer"
                        for row in normalized
                    ),
                }
            return payload
        payload["normalized"] = normalized
        return payload
    if args.command == "wait-topic":
        request_options = parse_json_object(args.options_json, "--options-json")
        match = parse_json_object(args.match_json, "--match-json")
        try:
            capability = CapabilityCatalog().describe(detected_version, args.api)
        except CapabilityNotFoundError:
            return unreflected_interface_payload(
                args.api,
                detected_version,
                command="wait-topic",
                common=common,
            )
        route_boundary = catalog_route_boundary_payload(
            capability,
            command="wait-topic",
            common=common,
        )
        if route_boundary is not None:
            return route_boundary
        result = dispatch(
            dispatcher,
            args.api,
            connection=connection,
            version=detected_version,
            options=request_options,
            topic_match=match or None,
            operation_timeout=min(
                reserved_topic_wait_timeout(connection),
                float(capability.execution_contract["timeout_seconds"]),
            ),
            result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
        )
        event = normalize_topic_event_result(result, expected_topic=args.api) if result.get("ok") else None
        event_validation = (
            validate_semantic_event(args.api, event, version=detected_version)
            if event is not None
            else None
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "topic": args.api,
            "match": match or None,
            "call": dispatch_call_summary(result),
            "event": event,
            "event_validation": event_validation.as_dict() if event_validation is not None else None,
            "cleanup": (
                "unsubscribed"
                if result.get("ok")
                or result.get("error_code") in {"TIMEOUT", "RESULT_NOT_JSON", "RESULT_TOO_LARGE"}
                else "unknown"
            ),
        }
    if args.command in {"preview", "execute", "verify"}:
        return dispatch_transaction_command(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "call":
        request_args = parse_json_object(args.args_json, "--args-json")
        request_options = parse_json_object(args.options_json, "--options-json")
        try:
            capability = CapabilityCatalog().describe(detected_version, args.api)
        except CapabilityNotFoundError:
            return unreflected_interface_payload(
                args.api,
                detected_version,
                command="call",
                common=common,
            )
        route_boundary = catalog_route_boundary_payload(
            capability,
            command="call",
            common=common,
        )
        if route_boundary is not None:
            return route_boundary
        validation = validate_semantic_payload(
            args.api,
            request_args,
            request_options,
            version=detected_version,
        )
        result = dispatch(
            dispatcher,
            args.api,
            connection=connection,
            version=detected_version,
            args=request_args,
            options=request_options,
            dry_run=args.dry_run,
            allow_destructive=False,
            topic_mode=args.topic_mode,
            live_behavior=args.live_behavior,
            operation_timeout=float(capability.execution_contract["timeout_seconds"]),
            result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
        )
        result_validation = (
            validate_semantic_result(
                args.api,
                result.get("result"),
                version=detected_version,
            )
            if result.get("ok") and not args.dry_run
            else None
        )
        inventory = (
            normalize_reflection_inventory_result(
                args.api,
                result,
                version=detected_version,
            )
            if result.get("ok") and args.api in REFLECTION_INVENTORY_CALLS
            else None
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "call": dispatch_call_summary(result),
            "schema_validation": validation.as_dict(),
            "result_validation": result_validation.as_dict() if result_validation is not None else None,
            "agent_result": inventory if inventory is not None else result.get("result"),
            "inventory": inventory,
        }
    raise GatewayInputError(f"unsupported command: {args.command}")


def dispatch_transaction_command(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    read_call = transaction_read_call(
        dispatcher,
        connection=connection,
        version=detected_version,
    )
    if args.command == "preview":
        request_payload = parse_json_object(args.request_json, "--request-json")
        project_guard_mode, target_project_path = transaction_project_guard_spec(
            request_payload,
            version=detected_version,
        )
        project, project_call = current_project(
            dispatcher,
            connection=connection,
            version=detected_version,
            allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
        )
        state_dir = resolve_transaction_state_directory(args, env=env)
        if project is not None:
            require_runtime_directory_outside_project(state_dir, project=project)
        if target_project_path is not None:
            require_runtime_directory_outside_project(
                state_dir,
                project={"path": target_project_path},
            )
        store = TransactionStore(state_dir)
        project_guard = build_project_guard(
            endpoint=common["endpoint"],
            version=detected_version,
            live_info=live_info,
            project=project,
            project_guard_mode=project_guard_mode,
            target_project_path=target_project_path,
        )
        artifact = build_transaction_artifact(
            request_payload,
            live_version=detected_version,
            read_call=read_call,
            project_guard=project_guard,
            skill_root=SKILL_ROOT,
            ttl_seconds=args.ttl,
        ).as_dict()
        transaction_id = new_transaction_id()
        created = store.create_preview(transaction_id, artifact)
        awaiting = store.submit_for_confirmation(transaction_id)
        prepared = artifact["prepared_operation"]
        cleanup = transaction_cleanup_payload(prepared, phase="preview")
        agent_result = transaction_agent_result(
            request=require_mapping(artifact.get("request"), "transaction request"),
            transaction_id=transaction_id,
            artifact_hash=created.artifact_hash,
            state=awaiting.state.value,
            executed=False,
            cleanup=cleanup,
        )
        return {
            "ok": True,
            "status": "awaiting_confirmation",
            **common,
            "transaction_id": transaction_id,
            "state": awaiting.state.value,
            "artifact_hash": created.artifact_hash,
            "preview_summary": {
                "request": artifact["request"],
                "dispatch": prepared["dispatch"],
                "resolved_roles": prepared["resolved_roles"],
                "pre_state": prepared["pre_state"],
                "verification_plan": prepared["verification_plan"],
                "cleanup": cleanup,
                "project_guard_fingerprint": project_guard["fingerprint"],
                "runtime_guard_fingerprint": artifact["runtime_guard"]["fingerprint"],
                "expires_at": artifact["expires_at"],
            },
            "project_call": project_call,
            "executed": False,
            "verified": False,
            "cleanup": cleanup,
            "agent_result": agent_result,
        }

    store = resolve_transaction_store(args, env=env)
    transaction_id = args.transaction_id
    record = store.load(transaction_id)
    preview = store.load_preview(transaction_id)
    artifact = preview.artifact
    if not isinstance(artifact, Mapping):
        raise GatewayInputError("transaction preview artifact must be a JSON object")
    prepared = require_mapping(artifact.get("prepared_operation"), "prepared operation")
    if record.state is TransactionState.EXECUTING:
        recovered = store.mark_execution_indeterminate(
            transaction_id,
            details={
                "reason": "A previous process stopped after execution_started without recording a result.",
                "automatic_retry": False,
            },
        )
        return {
            "ok": False,
            "status": "indeterminate",
            **common,
            "transaction_id": transaction_id,
            "state": recovered.state.value,
            "message": "The previous execution attempt is indeterminate and will not be retried automatically.",
            "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
            "automatic_retry": False,
        }

    if args.command == "execute":
        if record.state is not TransactionState.CONFIRMED:
            raise InvalidTransition(
                f"Transaction {transaction_id!r} must be confirmed before execution; current state is {record.state.value!r}."
            )
        request_payload = require_mapping(artifact.get("request"), "transaction request")
        project_guard_mode, target_project_path = transaction_project_guard_spec(
            request_payload,
            version=detected_version,
        )
        project, project_call = current_project(
            dispatcher,
            connection=connection,
            version=detected_version,
            allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
        )
        current_guard = build_project_guard(
            endpoint=common["endpoint"],
            version=detected_version,
            live_info=live_info,
            project=project,
            project_guard_mode=project_guard_mode,
            target_project_path=target_project_path,
        )
        try:
            guard_validation = validate_transaction_guards(
                artifact,
                current_project_guard=current_guard,
                skill_root=SKILL_ROOT,
            )
        except TransactionGuardError as exc:
            repreview = store.require_repreview(transaction_id, details=exc.as_dict())
            return {
                "ok": False,
                "status": "repreview_required",
                **common,
                "transaction_id": transaction_id,
                "state": repreview.state.value,
                "error_code": exc.error_code,
                "message": str(exc),
                "details": exc.details,
                "guard_validation": exc.as_dict(),
                "executed": False,
                "verified": False,
                "cleanup": transaction_cleanup_payload(prepared, phase="preview"),
            }
        role_validation = validate_prepared_roles(prepared, read_call=read_call)
        if role_validation.get("ok") is not True:
            repreview = store.require_repreview(
                transaction_id,
                details={"error_code": "ROLE_GUARD_MISMATCH", "role_validation": role_validation},
            )
            return {
                "ok": False,
                "status": "repreview_required",
                **common,
                "transaction_id": transaction_id,
                "state": repreview.state.value,
                "error_code": "ROLE_GUARD_MISMATCH",
                "role_validation": role_validation,
                "executed": False,
                "verified": False,
                "cleanup": transaction_cleanup_payload(prepared, phase="preview"),
            }
        dispatch_payload = require_mapping(prepared.get("dispatch"), "prepared dispatch")
        operation = str(request_payload.get("operation"))
        spec = describe_operation(operation)
        call_uri = dispatch_payload.get("uri")
        if not isinstance(call_uri, str):
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "Immutable prepared dispatch lacks a WAAPI URI.",
            )
        if operation != "waapi.call" and call_uri != spec.uri:
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "Immutable prepared dispatch URI does not match its closed operation registry entry.",
                details={"operation": operation, "expected": spec.uri, "actual": dispatch_payload.get("uri")},
            )
        capability = CapabilityCatalog().describe(detected_version, call_uri)
        if operation == "waapi.call" and capability.preferred_route != "transaction_operation":
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "waapi.call preview no longer resolves to a reviewed transaction route.",
                details={"operation": operation, "uri": call_uri, "route": capability.preferred_route},
            )
        if operation == "waapi.undoGroup":
            request_arguments = request_payload.get("arguments")
            if not isinstance(request_arguments, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Immutable waapi.undoGroup request lacks its arguments object.",
                )
            execution_plan = build_undo_group_execution_plan(
                detected_version,
                request_arguments,
            )
            stored_pre_state = prepared.get("pre_state")
            stored_plan = (
                stored_pre_state.get("execution_plan")
                if isinstance(stored_pre_state, Mapping)
                else None
            )
            if stored_plan != execution_plan:
                raise OperationContractError(
                    "PREVIEW_DISPATCH_MISMATCH",
                    "Immutable waapi.undoGroup execution plan no longer matches its request.",
                )
            role_validation_output = undo_group_role_validation_summary(role_validation)
            require_project_modification_policy(env=env, action="execution")
            store.begin_execution(transaction_id)
            try:
                compound = dispatch_undo_group_execution_plan(
                    dispatcher,
                    connection=connection,
                    version=detected_version,
                    execution_plan=execution_plan,
                )
            except Exception as exc:  # noqa: BLE001 - begin may already have reached Wwise
                indeterminate = store.mark_execution_indeterminate(
                    transaction_id,
                    details={
                        "reason": "exception during same-connection Undo Group execution",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "automatic_retry": False,
                    },
                )
                return {
                    "ok": False,
                    "status": "indeterminate",
                    **common,
                    "transaction_id": transaction_id,
                    "state": indeterminate.state.value,
                    "message": str(exc),
                    "same_connection": True,
                    "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                    "automatic_retry": False,
                }
            if compound["status"] == "execution_cancelled":
                cancelled = store.mark_execution_cancelled(
                    transaction_id,
                    details={"compound_execution": compound, "automatic_retry": False},
                )
                return {
                    "ok": False,
                    "status": "execution_cancelled",
                    **common,
                    "transaction_id": transaction_id,
                    "state": cancelled.state.value,
                    "artifact_hash": preview.artifact_hash,
                    "compound_execution": compound,
                    "role_validation": role_validation_output,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    "executed": True,
                    "cancelled": True,
                    "rollback_verified": False,
                    "verified": False,
                    "cleanup": transaction_cleanup_payload(prepared, phase="execution_cancelled"),
                    "automatic_retry": False,
                }
            if compound["status"] == "indeterminate":
                indeterminate = store.mark_execution_indeterminate(
                    transaction_id,
                    details={"compound_execution": compound, "automatic_retry": False},
                )
                return {
                    "ok": False,
                    "status": "indeterminate",
                    **common,
                    "transaction_id": transaction_id,
                    "state": indeterminate.state.value,
                    "artifact_hash": preview.artifact_hash,
                    "compound_execution": compound,
                    "role_validation": role_validation_output,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    "executed": True,
                    "verified": False,
                    "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                    "automatic_retry": False,
                }
            result = require_mapping(compound.get("dispatch_result"), "Undo Group dispatch result")
            compound_summary = {
                "status": compound["status"],
                "same_connection": compound["same_connection"],
                "automatic_retry": compound["automatic_retry"],
                "phase_count": len(
                    require_mapping(result.get("result"), "Undo Group result").get("phases", ())
                ),
                "authoritative_phases": "dispatch_result.result.phases",
            }
            try:
                executed = store.mark_executed_unverified(
                    transaction_id,
                    details={"dispatch_result": result, "automatic_retry": False},
                )
            except Exception as exc:  # noqa: BLE001 - same-session success must not become replayable
                persistence_payload = execution_success_persistence_failure_payload(
                    common,
                    store=store,
                    transaction_id=transaction_id,
                    artifact_hash=preview.artifact_hash,
                    prepared=prepared,
                    dispatch_result=result,
                    exc=exc,
                )
                persistence_payload.update(
                    {
                        "compound_execution": compound_summary,
                        "role_validation": role_validation_output,
                        "guard_validation": guard_validation,
                        "project_call": project_call,
                        "same_connection": True,
                    }
                )
                return persistence_payload
            return {
                "ok": True,
                "status": "executed_unverified",
                **common,
                "transaction_id": transaction_id,
                "state": executed.state.value,
                "artifact_hash": preview.artifact_hash,
                "dispatch_result": result,
                "compound_execution": compound_summary,
                "role_validation": role_validation_output,
                "guard_validation": guard_validation,
                "project_call": project_call,
                "executed": True,
                "verified": False,
                "same_connection": True,
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=result,
                ),
                "automatic_retry": False,
            }
        call_args = require_mapping(dispatch_payload.get("args", {}), "prepared dispatch args")
        call_options = require_mapping(dispatch_payload.get("options", {}), "prepared dispatch options")
        schema_validation = validate_semantic_payload(
            call_uri,
            call_args,
            call_options,
            version=detected_version,
        )
        # Re-read at the final mutation boundary as well as before connecting.
        # A policy change during live guard validation must still stop execution.
        require_project_modification_policy(env=env, action="execution")
        store.begin_execution(transaction_id)
        try:
            result = dispatch(
                dispatcher,
                call_uri,
                connection=connection,
                version=detected_version,
                args=call_args,
                options=call_options,
                allow_destructive=True,
                operation_timeout=float(capability.execution_contract["timeout_seconds"]),
                result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
            )
        except Exception as exc:  # noqa: BLE001 - execution may already have reached Wwise
            indeterminate = store.mark_execution_indeterminate(
                transaction_id,
                details={
                    "reason": "exception after execution_started",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "automatic_retry": False,
                },
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "message": str(exc),
                "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                "automatic_retry": False,
            }
        if result.get("ok") is not True:
            indeterminate = store.mark_execution_indeterminate(
                transaction_id,
                details={"dispatch_result": result, "automatic_retry": False},
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "dispatch_result": result,
                "role_validation": role_validation,
                "guard_validation": guard_validation,
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="indeterminate",
                    execution_result=result,
                ),
                "automatic_retry": False,
            }
        try:
            executed = store.mark_executed_unverified(
                transaction_id,
                details={"dispatch_result": result, "automatic_retry": False},
            )
        except Exception as exc:  # noqa: BLE001 - WAAPI success must survive a local journal failure
            persistence_payload = execution_success_persistence_failure_payload(
                common,
                store=store,
                transaction_id=transaction_id,
                artifact_hash=preview.artifact_hash,
                prepared=prepared,
                dispatch_result=result,
                exc=exc,
            )
            persistence_payload.update(
                {
                    "schema_validation": schema_validation.as_dict(),
                    "role_validation": role_validation,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                }
            )
            return persistence_payload
        return {
            "ok": True,
            "status": "executed_unverified",
            **common,
            "transaction_id": transaction_id,
            "state": executed.state.value,
            "artifact_hash": preview.artifact_hash,
            "dispatch_result": result,
            "schema_validation": schema_validation.as_dict(),
            "role_validation": role_validation,
            "guard_validation": guard_validation,
            "project_call": project_call,
            "executed": True,
            "verified": False,
            "cleanup": transaction_cleanup_payload(
                prepared,
                phase="executed",
                execution_result=result,
            ),
            "automatic_retry": False,
        }

    if args.command == "verify":
        if record.state is not TransactionState.EXECUTED_UNVERIFIED:
            raise InvalidTransition(
                f"Transaction {transaction_id!r} must be executed_unverified before verification; "
                f"current state is {record.state.value!r}."
            )
        request_payload = require_mapping(artifact.get("request"), "transaction request")
        project_guard_mode, target_project_path = transaction_project_guard_spec(
            request_payload,
            version=detected_version,
        )
        # Load the immutable execution evidence before any live verification
        # probe.  A guard/readback failure must not discard a result-bound
        # lifecycle identity such as the ID returned by transport.create.
        events = store.read_events(transaction_id)
        execution_events = [event for event in events if event.get("event_type") == "execution_completed"]
        event_details = execution_events[-1].get("details") if execution_events else None
        execution_result = event_details.get("dispatch_result") if isinstance(event_details, Mapping) else None
        if not isinstance(execution_result, Mapping):
            execution_result = {}
        try:
            project, project_call = current_project(
                dispatcher,
                connection=connection,
                version=detected_version,
                allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
            )
            current_guard = build_project_guard(
                endpoint=common["endpoint"],
                version=detected_version,
                live_info=live_info,
                project=project,
                project_guard_mode=project_guard_mode,
                target_project_path=target_project_path,
            )
            guard_validation = validate_transaction_guards(
                artifact,
                current_project_guard=current_guard,
                skill_root=SKILL_ROOT,
                check_expiry=False,
                project_phase=PROJECT_GUARD_PHASE_POST_VERIFICATION,
            )
        except TransactionGuardError as exc:
            return {
                "ok": False,
                "status": "verification_deferred",
                **common,
                "transaction_id": transaction_id,
                "state": record.state.value,
                "error_code": exc.error_code,
                "message": str(exc),
                "guard_validation": exc.as_dict(),
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=execution_result,
                ),
                "automatic_retry": False,
                "manual_verification_retry_allowed": True,
            }
        except Exception as exc:  # noqa: BLE001 - read-only verification may be retried manually
            return verification_deferred_payload(
                common,
                transaction_id=transaction_id,
                state=record.state.value,
                exc=exc,
                cleanup=transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=execution_result,
                ),
            )
        if not execution_events:
            indeterminate = store.record_verification(
                transaction_id,
                TransactionState.INDETERMINATE,
                details={"error_code": "EXECUTION_EVIDENCE_MISSING"},
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "error_code": "EXECUTION_EVIDENCE_MISSING",
                "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                "automatic_retry": False,
            }
        try:
            verification = verify_prepared_operation(
                prepared,
                execution_result=execution_result,
                read_call=read_call,
            )
            if project_guard_mode != PROJECT_GUARD_INVARIANT:
                verification = strengthen_project_transition_verification(
                    verification,
                    guard_validation=guard_validation,
                    project_call=project_call,
                )
        except Exception as exc:  # noqa: BLE001 - read-only verification may be retried manually
            return verification_deferred_payload(
                common,
                transaction_id=transaction_id,
                state=record.state.value,
                exc=exc,
                cleanup=transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=execution_result,
                ),
            )
        outcome = {
            "verified": TransactionState.VERIFIED,
            "result_schema_checked": TransactionState.RESULT_SCHEMA_CHECKED,
            "verification_failed": TransactionState.VERIFICATION_FAILED,
            "indeterminate": TransactionState.INDETERMINATE,
        }[verification.status]
        final_record = store.record_verification(
            transaction_id,
            outcome,
            details={"verification": verification.as_dict()},
        )
        payload = {
            "ok": verification.ok,
            "status": verification.status,
            **common,
            "transaction_id": transaction_id,
            "state": final_record.state.value,
            "artifact_hash": preview.artifact_hash,
            "verification": verification.as_dict(),
            "guard_validation": guard_validation,
            "project_call": project_call,
            "executed": True,
            "verified": verification.business_state_verified and verification.ok,
            "result_schema_checked": verification.status == "result_schema_checked",
            "verification_strength": verification.verification_strength,
            "cleanup": transaction_cleanup_payload(
                prepared,
                phase="verified",
                execution_result=execution_result,
            ),
            "automatic_retry": False,
        }
        if verification.ok:
            agent_result = transaction_agent_result(
                request=require_mapping(artifact.get("request"), "transaction request"),
                transaction_id=transaction_id,
                artifact_hash=preview.artifact_hash,
                state=final_record.state.value,
                executed=True,
                verified=verification.business_state_verified,
                cleanup=payload["cleanup"],
            )
            if agent_result["operation"] in {"waapi.call", "waapi.undoGroup"}:
                agent_result["result"] = execution_result.get("result")
            payload["agent_result"] = agent_result
        return payload
    raise GatewayInputError(f"unsupported transaction command: {args.command}")


def dispatch_undo_group_execution_plan(
    dispatcher: WwiseDispatcher,
    *,
    connection: GatewayConnection,
    version: str,
    execution_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one reviewed Undo Group plan on the existing dispatcher/client.

    No phase is retried.  Only an inner-call failure attempts ``cancelGroup``;
    uncertainty in begin/end/cancel is terminal because replay could duplicate a
    mutation or close a different session-scoped group.
    """

    if execution_plan.get("kind") != "same_connection_undo_group":
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Undo Group execution plan kind is missing or unsupported.",
        )
    if execution_plan.get("version") != version:
        raise OperationContractError(
            "VERSION_MISMATCH",
            "Undo Group execution plan version does not match live Wwise.",
        )
    begin = require_mapping(execution_plan.get("begin"), "Undo Group begin phase")
    inner_calls = execution_plan.get("calls")
    end = require_mapping(execution_plan.get("end"), "Undo Group end phase")
    cancel = require_mapping(execution_plan.get("cancel"), "Undo Group cancel phase")
    if not isinstance(inner_calls, list):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Undo Group execution plan calls must be a JSON array.",
        )

    phases: list[dict[str, Any]] = []

    def run_phase(
        phase_name: str,
        phase: Mapping[str, Any],
        *,
        index: int | None = None,
        reserve_cancel_budget: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        uri_value = phase.get("uri", phase.get("api"))
        args_value = phase.get("args", {})
        options_value = phase.get("options", {})
        if (
            not isinstance(uri_value, str)
            or not isinstance(args_value, Mapping)
            or not isinstance(options_value, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"Undo Group {phase_name} phase is malformed.",
            )
        validate_semantic_payload(
            uri_value,
            args_value,
            options_value,
            version=version,
        )
        capability = CapabilityCatalog().describe(version, uri_value)
        remaining = connection.deadline.require_remaining(
            f"Undo Group {phase_name} {uri_value}"
        )
        cancel_reserve = 0.0
        if reserve_cancel_budget:
            cancel_reserve = min(
                UNDO_GROUP_CANCEL_RESERVE_MAX_SECONDS,
                max(
                    UNDO_GROUP_CANCEL_RESERVE_MIN_SECONDS,
                    remaining * UNDO_GROUP_CANCEL_RESERVE_RATIO,
                ),
            )
        operation_timeout = min(
            float(capability.execution_contract["timeout_seconds"]),
            max(0.001, remaining - cancel_reserve),
        )
        result = dispatch(
            dispatcher,
            uri_value,
            connection=connection,
            version=version,
            args=args_value,
            options=options_value,
            allow_destructive=True,
            operation_timeout=operation_timeout,
            result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
        )
        row: dict[str, Any] = {
            "phase": phase_name,
            "uri": uri_value,
            "dispatch_result": result,
            "operation_timeout_seconds": operation_timeout,
            "cancel_reserve_seconds": cancel_reserve,
        }
        if index is not None:
            row["index"] = index
        try:
            accumulated_size = len(
                json.dumps(
                    [*phases, row],
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            accumulated_size = UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES + 1
        if accumulated_size > UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES:
            row["dispatch_result"] = dispatch_call_summary(result)
            row["failure"] = {
                "kind": "compound_result_limit_exceeded",
                "limit_bytes": UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES,
                "observed_at_least_bytes": accumulated_size,
            }
            phases.append(row)
            return row, False
        if result.get("ok") is not True:
            row["failure"] = {
                "kind": "dispatch_failed",
                "error_code": result.get("error_code"),
                "message": result.get("message"),
            }
            phases.append(row)
            return row, False
        try:
            validate_semantic_result(
                uri_value,
                result.get("result"),
                version=version,
            )
        except SemanticValidationError as exc:
            row["failure"] = {
                "kind": "result_schema_mismatch",
                "validation": exc.as_dict(),
            }
            phases.append(row)
            return row, False
        # The immutable request plan already records request validation, and
        # verification re-validates every recorded dispatch result.  Avoid
        # copying both validation documents into the live phase envelope.
        phases.append(row)
        return row, True

    def best_effort_cancel() -> tuple[Mapping[str, Any], bool]:
        try:
            return run_phase("cancel", cancel)
        except Exception as exc:  # noqa: BLE001 - evidence only; caller remains indeterminate
            return (
                {
                    "phase": "cancel",
                    "failure": {
                        "kind": "cancel_exception",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
                False,
            )

    try:
        begin_row, begin_ok = run_phase("begin", begin, reserve_cancel_budget=True)
    except Exception as exc:  # noqa: BLE001 - begin may have reached Wwise
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "beginGroup raised and is not safely replayable",
            "failed_phase": {
                "phase": "begin",
                "failure": {
                    "kind": "begin_exception",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            },
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }
    if not begin_ok:
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "beginGroup outcome is not safely replayable",
            "failed_phase": begin_row,
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }

    for index, inner in enumerate(inner_calls):
        if not isinstance(inner, Mapping):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"Undo Group inner call {index} is malformed.",
            )
        try:
            inner_row, inner_ok = run_phase(
                "inner",
                inner,
                index=index,
                reserve_cancel_budget=True,
            )
        except Exception as exc:  # noqa: BLE001 - inner mutation outcome is uncertain
            cancel_row, cancel_ok = best_effort_cancel()
            return {
                "status": "indeterminate",
                "same_connection": True,
                "automatic_retry": False,
                "reason": "an inner Undo Group mutation raised and is not safely replayable",
                "failed_phase": {
                    "phase": "inner",
                    "index": index,
                    "failure": {
                        "kind": "inner_exception",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
                "cancel_phase": cancel_row,
                "cancel_succeeded": cancel_ok,
                "phases": phases,
            }
        if inner_ok:
            continue
        cancel_row, cancel_ok = best_effort_cancel()
        if not cancel_ok:
            return {
                "status": "indeterminate",
                "same_connection": True,
                "automatic_retry": False,
                "reason": "cancelGroup outcome is uncertain after an inner-call failure",
                "failed_phase": inner_row,
                "cancel_phase": cancel_row,
                "phases": phases,
            }
        return {
            "status": "execution_cancelled",
            "same_connection": True,
            "automatic_retry": False,
            "failed_phase": inner_row,
            "cancel_phase": cancel_row,
            "phases": phases,
            "rollback_verified": False,
            "message": "The open Undo Group was cancelled on the same connection; rollback state was not verified.",
        }

    try:
        end_row, end_ok = run_phase("end", end, reserve_cancel_budget=True)
    except Exception as exc:  # noqa: BLE001 - best-effort cancel cannot make end certain
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "endGroup raised and is not safely replayable",
            "failed_phase": {
                "phase": "end",
                "failure": {
                    "kind": "end_exception",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            },
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }
    if not end_ok:
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "endGroup outcome is not safely replayable",
            "failed_phase": end_row,
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }
    dispatch_result = {
        "ok": True,
        "api": "waapi.undoGroup",
        "version": version,
        "result": {"same_connection": True, "phases": phases},
        "error_code": None,
        "message": "ok",
    }
    return {
        "status": "completed",
        "same_connection": True,
        "automatic_retry": False,
        "dispatch_result": dispatch_result,
    }


def undo_group_role_validation_summary(
    role_validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the successful Undo guard facts without duplicating its plan."""

    raw_assertions = role_validation.get("assertions")
    assertions = raw_assertions if isinstance(raw_assertions, list) else []
    return {
        "contract": role_validation.get("contract"),
        "operation": role_validation.get("operation"),
        "ok": role_validation.get("ok") is True,
        "status": role_validation.get("status"),
        "assertions": [
            {
                "name": assertion.get("name"),
                "passed": assertion.get("passed") is True,
            }
            for assertion in assertions
            if isinstance(assertion, Mapping)
        ],
        "readbacks": [],
        "evidence_location": "immutable transaction preview artifact",
    }


def dispatch(
    dispatcher: WwiseDispatcher,
    api: str,
    *,
    connection: GatewayConnection,
    version: str,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    allow_destructive: bool = False,
    topic_mode: str = "wait",
    topic_match: Mapping[str, Any] | None = None,
    live_behavior: bool = False,
    exact_object_lookup: bool = False,
    operation_timeout: float | None = None,
    result_limit_bytes: int = MAX_GATEWAY_RESULT_JSON_BYTES,
) -> dict[str, Any]:
    remaining = connection.deadline.require_remaining(f"dispatch {api}")
    dispatch_timeout = (
        remaining
        if operation_timeout is None
        else min(remaining, max(0.0, float(operation_timeout)))
    )
    result = dispatcher.dispatch(
        api,
        version=version,
        args=args,
        options=options,
        timeout=dispatch_timeout,
        dry_run=dry_run,
        allow_destructive=allow_destructive,
        evidence_dir=connection.evidence_dir,
        topic_mode=topic_mode,
        topic_match=topic_match,
        live_behavior=live_behavior,
        result_limit_bytes=result_limit_bytes,
    )
    if result.get("error_code") == "TIMEOUT":
        result = dict(result)
        details = dict(result.get("details") or {})
        elapsed = connection.deadline.elapsed()
        details.setdefault("phase", f"dispatch {api}")
        details.setdefault("configured_timeout_seconds", connection.timeout)
        details.setdefault("operation_timeout_seconds", dispatch_timeout)
        details.setdefault("elapsed_seconds", elapsed)
        details.setdefault("deadline_exhausted", elapsed >= connection.timeout)
        details.setdefault("cleanup_pending", False)
        details.setdefault("abort_requested", False)
        result["details"] = details
    return normalize_exact_object_absence(
        api=api,
        args=args,
        result=result,
        exact_object_lookup=exact_object_lookup,
    )


def reserved_topic_wait_timeout(connection: GatewayConnection) -> float:
    """Leave bounded in-deadline time for unsubscribe, evidence, and close."""

    remaining = connection.deadline.require_remaining("prepare bounded topic wait")
    reserve = min(
        TOPIC_CLEANUP_RESERVE_MAX_SECONDS,
        remaining * TOPIC_CLEANUP_RESERVE_RATIO,
    )
    return max(0.0, remaining - reserve)


def normalize_exact_object_absence(
    *,
    api: str,
    args: Mapping[str, Any] | None,
    result: Mapping[str, Any],
    exact_object_lookup: bool = False,
) -> dict[str, Any]:
    """Normalize Wwise's unknown-object error for one exact object.get lookup.

    Wwise versions differ on whether a missing GUID/path returns an empty
    ``return`` array or ``ak.wwise.query.unknown_object``.  For an exact
    single-identity lookup these mean the same thing.  Broader WAQL/search
    failures remain errors and are never swallowed.
    """

    if (
        result.get("ok") is True
        or api != OBJECT_GET_URI
        or not (exact_object_lookup or _single_exact_lookup(args))
        or result.get("error_code") != "WaapiRequestFailed"
    ):
        return dict(result)
    error_uri = result.get("waapi_error_uri")
    error_details = result.get("waapi_error_details")
    if error_uri == "ak.wwise.query.unknown_object":
        source = "ak.wwise.query.unknown_object"
    elif error_uri == "ak.wwise.query.invalid_query" and _structured_contains_object_not_found(error_details):
        source = "ak.wwise.query.invalid_query:object-not-found"
    else:
        return dict(result)
    message = str(result.get("message") or "")
    original = {
        "error_code": result.get("error_code"),
        "waapi_error_uri": error_uri,
        "waapi_error_details": error_details,
        "message": message,
        "evidence_path": result.get("evidence_path"),
    }
    return {
        **dict(result),
        "ok": True,
        "result": {"return": []},
        "error_code": None,
        "message": "Exact object identity is absent; normalized to an empty object.get result.",
        "normalization": {
            "kind": "exact-object-absence",
            "source": source,
            "original": original,
        },
    }


def _single_exact_lookup(args: Mapping[str, Any] | None) -> bool:
    if not isinstance(args, Mapping):
        return False
    if set(args) != {"from"}:
        return False
    source = args.get("from")
    if not isinstance(source, Mapping) or set(source) not in ({"id"}, {"path"}):
        return False
    values = source.get("id", source.get("path"))
    if not (
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], str)
    ):
        return False
    value = values[0]
    if "id" in source:
        return _canonical_guid(value)
    return _canonical_wwise_path(value)


def _canonical_exact_query_request(args: argparse.Namespace) -> bool:
    """Trust exactness from parsed CLI fields, never by reparsing generated WAQL."""

    if args.where_json is not None or args.select or args.take is not None:
        return False
    if args.path is not None:
        return _canonical_wwise_path(args.path)
    if args.object_id is not None:
        return _canonical_guid(args.object_id)
    return False


def _require_explicit_query_bound(args: argparse.Namespace) -> None:
    broad_source = args.object_type is not None or args.search is not None or args.query is not None
    transformed = bool(args.select)
    if (broad_source or transformed) and args.take is None and not args.all_results:
        raise GatewayInputError(
            "Broad query-object sources and --select transforms require an explicit --take limit "
            "or the explicit --all-results opt-in."
        )


def _require_exact_identity_return_field(
    args: argparse.Namespace,
    return_fields: Sequence[str],
) -> None:
    """Keep an untransformed exact lookup independently identity-verifiable."""

    if args.select:
        return
    required_field: str | None = None
    source_option: str | None = None
    if args.path is not None:
        required_field = "path"
        source_option = "--path"
    elif args.object_id is not None:
        required_field = "id"
        source_option = "--object-id"
    if required_field is None or required_field in return_fields:
        return
    raise GatewayInputError(
        f"Exact {source_option} query-object lookups require --return-field {required_field} "
        "so the packaged gateway can verify the returned identity."
    )


def _query_result_maximum(args: argparse.Namespace) -> int | None:
    """Return the strongest applicable result bound for one closed query."""

    take = args.take
    exact_source = args.path is not None or args.object_id is not None
    expanding = any(value in EXPANDING_QUERY_SELECTS for value in (args.select or ()))
    semantic_maximum = 1 if exact_source and not expanding else None
    if take is None:
        return semantic_maximum
    if semantic_maximum is None:
        return take
    return min(take, semantic_maximum)


def validate_exact_query_identity(
    args: argparse.Namespace,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Reject a successful exact lookup whose returned identity drifted."""

    if args.select:
        return
    if args.path is not None:
        expected = _normalize_wwise_identity_path(args.path)
        mismatches = [
            {
                "index": index,
                "actual": row.get("path"),
            }
            for index, row in enumerate(rows)
            if _normalize_wwise_identity_path(row.get("path")) != expected
        ]
        identity_field = "path"
    elif args.object_id is not None:
        expected = args.object_id.casefold()
        mismatches = [
            {
                "index": index,
                "actual": row.get("id"),
            }
            for index, row in enumerate(rows)
            if not isinstance(row.get("id"), str)
            or not _canonical_guid(row.get("id"))
            or str(row.get("id")).casefold() != expected
        ]
        identity_field = "id"
    else:
        return
    if mismatches:
        raise GatewayResultShapeError(
            "query-object exact lookup returned an object with a different identity.",
            details={
                "command": "query-object",
                "identity_field": identity_field,
                "expected": args.path if args.path is not None else args.object_id,
                "mismatches": mismatches,
            },
        )


def _normalize_wwise_identity_path(value: Any) -> str | None:
    """Normalize hierarchy separators and case for exact-path identity checks."""

    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("/", "\\")
    if not normalized.startswith("\\"):
        return None
    segments = [segment for segment in normalized.split("\\") if segment]
    if not segments:
        return "\\"
    return ("\\" + "\\".join(segments)).casefold()


def _query_bound_summary(args: argparse.Namespace) -> dict[str, Any]:
    if args.take is not None:
        return {"mode": "take", "value": args.take}
    if args.all_results:
        return {"mode": "all-results-explicit"}
    return {"mode": "exact-object"}


def _canonical_wwise_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("\\"):
        return False
    if value != "\\" and (value.startswith("\\\\") or value.endswith("\\") or "\\\\" in value):
        return False
    if "/" in value or '"' in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 or character in {"\u2028", "\u2029"} for character in value):
        return False
    return value == "\\" or all(segment for segment in value[1:].split("\\"))


def _canonical_guid(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 38 or value[0] != "{" or value[-1] != "}":
        return False
    body = value[1:-1]
    if tuple(index for index, character in enumerate(body) if character == "-") != (8, 13, 18, 23):
        return False
    return all(character in "0123456789abcdefABCDEF-" for character in body)


def _structured_contains_object_not_found(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    message = value.get("message")
    return isinstance(message, str) and "object not found" in message.casefold()


def default_client_factory(url: str) -> Any:
    from waapi import WaapiClient  # type: ignore[import-not-found]  # noqa: PLC0415

    # Structured dispatcher errors are more reliable than waapi-client's default
    # behavior of logging failures to stderr and returning ``None`` as success data.
    return WaapiClient(url=url, allow_exception=True)


def selected_ui_boundary(result: Mapping[str, Any], *, live_info: Mapping[str, Any]) -> bool:
    if result.get("error_code") == "API_NOT_FOUND":
        return True
    unavailable_uri = "ak.wwise.unavailable"
    message = str(result.get("message") or "").casefold()
    error_code = str(result.get("error_code") or "").casefold()
    structured_uri = str(result.get("waapi_error_uri") or "").casefold()
    unavailable = (
        structured_uri == unavailable_uri
        or error_code == unavailable_uri
        or unavailable_uri in message
    )
    return unavailable and bool(live_info.get("isCommandLine"))


def dispatch_call_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep audit identity and evidence without duplicating a potentially huge WAAPI result."""

    keys = (
        "api",
        "item_type",
        "category",
        "version",
        "ok",
        "dry_run",
        "risk_level",
        "error_code",
        "message",
        "details",
        "normalization",
        "evidence_path",
        "timeout",
    )
    summary = {key: result.get(key) for key in keys if key in result}
    if "normalization" in result and result.get("result") == {"return": []}:
        summary["result"] = {"return": []}
    return summary


def status_wwise_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    keys = (
        "apiVersion",
        "displayName",
        "isCommandLine",
        "processId",
        "processPath",
        "sessionId",
        "version",
    )
    return {key: value.get(key) for key in keys if key in value}


def status_project_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    keys = (
        "id",
        "name",
        "type",
        "path",
        "displayTitle",
        "isDirty",
        "currentLanguageId",
        "currentPlatformId",
    )
    return {key: value.get(key) for key in keys if key in value}


def strict_call_result_mapping(
    result: Mapping[str, Any],
    *,
    command: str,
    error_code: str,
) -> dict[str, Any]:
    """Require a successful call result to be one JSON object."""

    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayResultShapeError(
            f"{command} expected the successful WAAPI result to be a JSON object.",
            details={
                "command": command,
                "expected": "object",
                "actual_result_type": type(payload).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    return dict(payload)


def strict_object_get_rows(
    result: Mapping[str, Any],
    *,
    command: str,
    maximum_rows: int | None = None,
    required_string_fields: Sequence[str] = (),
    error_code: str = "INVALID_QUERY_RESULT",
) -> list[dict[str, Any]]:
    """Validate the public object.get result shape without converting drift to absence."""

    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayResultShapeError(
            f"{command} expected object.get result to be a JSON object.",
            details={
                "command": command,
                "expected": {"return": "array<object>"},
                "actual_result_type": type(payload).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    rows = payload.get("return")
    if not isinstance(rows, list):
        raise GatewayResultShapeError(
            f"{command} expected object.get result.return to be an array.",
            details={
                "command": command,
                "expected": {"return": "array<object>"},
                "actual_return_type": type(rows).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    invalid_indices = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    if invalid_indices:
        raise GatewayResultShapeError(
            f"{command} expected every object.get result.return row to be a JSON object.",
            details={
                "command": command,
                "expected": {"return": "array<object>"},
                "invalid_row_indices": invalid_indices,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    if maximum_rows is not None and len(rows) > maximum_rows:
        raise GatewayResultShapeError(
            f"{command} returned {len(rows)} rows, exceeding its maximum of {maximum_rows}.",
            details={
                "command": command,
                "maximum_rows": maximum_rows,
                "actual_count": len(rows),
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    invalid_field_rows = {
        index: [
            field
            for field in required_string_fields
            if not isinstance(row.get(field), str) or not str(row.get(field)).strip()
        ]
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
    }
    invalid_field_rows = {
        index: fields for index, fields in invalid_field_rows.items() if fields
    }
    if invalid_field_rows:
        raise GatewayResultShapeError(
            f"{command} returned rows without the required string fields.",
            details={
                "command": command,
                "required_string_fields": list(required_string_fields),
                "invalid_rows": invalid_field_rows,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    return [dict(row) for row in rows]


def strict_selected_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Require the exact documented selected-object success shape."""

    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayResultShapeError(
            "selected expected the successful WAAPI result to be a JSON object.",
            details={
                "command": "selected",
                "expected": {"objects": "array<object>"},
                "actual_result_type": type(payload).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    rows = payload.get("objects")
    if not isinstance(rows, list):
        raise GatewayResultShapeError(
            "selected expected result.objects to be an array.",
            details={
                "command": "selected",
                "expected": {"objects": "array<object>"},
                "actual_objects_type": type(rows).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    invalid_indices = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    if invalid_indices:
        raise GatewayResultShapeError(
            "selected expected every result.objects row to be a JSON object.",
            details={
                "command": "selected",
                "expected": {"objects": "array<object>"},
                "invalid_row_indices": invalid_indices,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    invalid_field_rows = {
        index: [
            field
            for field in ("id", "name", "type", "path")
            if not isinstance(row.get(field), str) or not str(row.get(field)).strip()
        ]
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
    }
    invalid_field_rows = {
        index: fields for index, fields in invalid_field_rows.items() if fields
    }
    if invalid_field_rows:
        raise GatewayResultShapeError(
            "selected returned rows without id, name, type, and path strings.",
            details={
                "command": "selected",
                "required_string_fields": ["id", "name", "type", "path"],
                "invalid_rows": invalid_field_rows,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    return [dict(row) for row in rows]


def require_single_result_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    command: str,
    error_code: str,
) -> dict[str, Any]:
    if len(rows) != 1:
        raise GatewayResultShapeError(
            f"{command} expected exactly one row, received {len(rows)}.",
            details={
                "command": command,
                "expected_count": 1,
                "actual_count": len(rows),
            },
            error_code=error_code,
        )
    return dict(rows[0])


def require_project_identity(
    value: Mapping[str, Any],
    *,
    command: str,
    error_code: str = "INVALID_PROJECT_RESULT",
) -> dict[str, Any]:
    """Require the stable canonical-id/name/path identity shared by all supported versions."""

    project = dict(value)
    invalid_fields: list[str] = []
    if not _canonical_guid(project.get("id")):
        invalid_fields.append("id")
    invalid_fields.extend(
        field
        for field in ("name", "path")
        if not isinstance(project.get(field), str) or not str(project.get(field)).strip()
    )
    if invalid_fields:
        raise GatewayResultShapeError(
            f"{command} requires a canonical project GUID and non-empty name and path fields.",
            details={
                "command": command,
                "required_fields": list(PROJECT_IDENTITY_FIELDS),
                "id_format": "{8-4-4-4-12}",
                "invalid_fields": invalid_fields,
            },
            error_code=error_code,
        )
    return project


def require_status_info(
    value: Mapping[str, Any],
    *,
    expected_version: str,
) -> dict[str, Any]:
    """Require the stable getInfo fields used by the public status contract."""

    info = dict(value)
    invalid_fields: list[str] = []
    if not isinstance(info.get("displayName"), str) or not str(info.get("displayName")).strip():
        invalid_fields.append("displayName")
    if not isinstance(info.get("isCommandLine"), bool):
        invalid_fields.append("isCommandLine")
    actual_version: str | None = None
    if not isinstance(info.get("version"), Mapping):
        invalid_fields.append("version")
    else:
        try:
            actual_version = version_key_from_get_info(info)
        except (TypeError, ValueError):
            invalid_fields.append("version")
    if invalid_fields:
        raise GatewayResultShapeError(
            "status getInfo requires displayName, isCommandLine, and version fields.",
            details={
                "command": "status getInfo",
                "required_fields": ["displayName", "isCommandLine", "version"],
                "invalid_fields": invalid_fields,
            },
            error_code="INVALID_STATUS_RESULT",
        )
    if actual_version != expected_version:
        raise GatewayResultShapeError(
            "status getInfo version does not match the detected live version.",
            details={
                "command": "status getInfo",
                "expected_version": expected_version,
                "actual_version": actual_version,
            },
            error_code="INVALID_STATUS_RESULT",
        )
    return info


def resolve_transaction_store(args: argparse.Namespace, *, env: Mapping[str, str]) -> TransactionStore:
    return TransactionStore(resolve_transaction_state_directory(args, env=env))


def resolve_transaction_state_directory(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> Path:
    configured = args.state_dir or env.get(STATE_DIRECTORY_ENV)
    if not configured:
        raise GatewayInputError(
            f"Transaction commands require --state-dir or ${STATE_DIRECTORY_ENV}; state is never written into the Skill checkout implicitly."
        )
    return resolve_external_runtime_directory(
        str(configured),
        label="--state-dir" if args.state_dir else f"${STATE_DIRECTORY_ENV}",
    )


def resolve_external_runtime_directory(value: str, *, label: str) -> Path:
    """Resolve one explicit runtime directory without ambient-home expansion."""

    if not isinstance(value, str) or not value.strip():
        raise GatewayInputError(f"{label} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise GatewayInputError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=False)
    skill_root = SKILL_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(skill_root)
    except ValueError:
        return resolved
    raise GatewayInputError(f"{label} must be outside the Skill checkout: {resolved}")


def require_runtime_directory_outside_project(
    runtime_dir: Path,
    *,
    project: Mapping[str, Any],
) -> None:
    """Reject preview state inside the live project when paths share a flavor."""

    project_value = project.get("path")
    if not isinstance(project_value, str) or not project_value:
        return
    project_file = Path(project_value)
    if not project_file.is_absolute():
        # Wwise under Wine can return a Windows path to a POSIX gateway.  Those
        # paths cannot contain the already-absolute POSIX runtime directory.
        return
    project_root = project_file.resolve(strict=False).parent
    try:
        runtime_dir.relative_to(project_root)
    except ValueError:
        return
    raise GatewayInputError(
        f"Transaction state directory must be outside the live Wwise project: {runtime_dir}"
    )


def transaction_state_payload(command: str, record: Any, *, offline: bool) -> dict[str, Any]:
    return {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": record.state.value,
        "command": command,
        "offline": offline,
        "transaction_id": record.transaction_id,
        "state": record.state.value,
        "artifact_hash": record.artifact_hash,
    }


def transaction_agent_result(
    *,
    request: Mapping[str, Any],
    transaction_id: str,
    artifact_hash: str,
    state: str,
    executed: bool,
    verified: bool | None = None,
    cleanup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project an immutable transaction artifact into the agent JSON contract.

    The request is the exact object loaded from the immutable preview artifact;
    callers must not reconstruct it from command arguments or verification
    evidence.  Only successful preview and successful terminal verification
    responses expose this projection.
    """

    operation = request.get("operation")
    if not isinstance(operation, str) or not operation:
        raise GatewayInputError("transaction request must contain a non-empty operation")
    result: dict[str, Any] = {
        "operation": operation,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": state,
        "executed": executed,
        "request": request,
    }
    if verified is not None:
        result["verified"] = verified
    if cleanup is not None:
        result["cleanup"] = dict(cleanup)
    return result


def transaction_cleanup_payload(
    prepared: Mapping[str, Any],
    *,
    phase: str,
    execution_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve the immutable cleanup spec and add an honest phase status."""

    raw_spec = prepared.get("cleanup")
    spec = dict(raw_spec) if isinstance(raw_spec, Mapping) else {"kind": "none"}
    if spec.get("contract") == CLEANUP_SPEC_CONTRACT:
        try:
            projection = project_transaction_cleanup(
                spec,
                phase=phase,
                execution_result=execution_result,
            )
        except TransactionCleanupError as exc:
            projection = {
                "contract": CLEANUP_PROJECTION_CONTRACT,
                "phase": phase,
                "status": "unknown",
                "automatic_cleanup": False,
                "automatic_retry": False,
                "error": exc.as_dict(),
            }
        return {
            "spec": spec,
            "status": projection["status"],
            "projection": projection,
        }

    kind = spec.get("kind")
    if phase == "indeterminate":
        status = "unknown"
    elif kind in {None, "none", "none-after-delete"}:
        status = "not_required"
    elif kind == "same_connection_cancel_on_inner_failure":
        status = (
            "armed_during_execution"
            if phase == "preview"
            else "handled_same_connection"
            if phase == "execution_cancelled"
            else "not_required"
        )
    elif phase == "preview":
        status = "not_started"
    else:
        status = "pending"
    projection = {
        "contract": CLEANUP_PROJECTION_CONTRACT,
        "phase": phase,
        "status": status,
        "kind": kind,
        "automatic_cleanup": bool(spec.get("automatic_cleanup") is True),
        "automatic_retry": False,
    }
    return {"spec": spec, "status": status, "projection": projection}


def transaction_show_summary(
    artifact: Any,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the review-relevant immutable preview without runtime hash bulk."""

    artifact_map = dict(artifact) if isinstance(artifact, Mapping) else {}
    prepared_raw = artifact_map.get("prepared_operation")
    prepared = dict(prepared_raw) if isinstance(prepared_raw, Mapping) else {}
    project_guard_raw = artifact_map.get("project_guard")
    project_guard = dict(project_guard_raw) if isinstance(project_guard_raw, Mapping) else {}
    runtime_guard_raw = artifact_map.get("runtime_guard")
    runtime_guard = dict(runtime_guard_raw) if isinstance(runtime_guard_raw, Mapping) else {}
    event_rows = [
        {
            key: event.get(key)
            for key in ("sequence", "event_type", "from_state", "to_state", "event_hash")
            if event.get(key) is not None
        }
        for event in events
    ]
    current_state = next(
        (
            str(event.get("to_state"))
            for event in reversed(events)
            if isinstance(event.get("to_state"), str)
        ),
        TransactionState.DRAFT.value,
    )
    cleanup_phase = {
        TransactionState.EXECUTING.value: "indeterminate",
        TransactionState.INDETERMINATE.value: "indeterminate",
        TransactionState.EXECUTED_UNVERIFIED.value: "executed",
        TransactionState.VERIFIED.value: "verified",
        TransactionState.RESULT_SCHEMA_CHECKED.value: "verified",
        TransactionState.VERIFICATION_FAILED.value: "verified",
        TransactionState.EXECUTION_CANCELLED.value: "execution_cancelled",
    }.get(current_state, "preview")
    execution_result: Mapping[str, Any] | None = None
    for event in reversed(events):
        if event.get("event_type") != "execution_completed":
            continue
        details = event.get("details")
        candidate = details.get("dispatch_result") if isinstance(details, Mapping) else None
        if isinstance(candidate, Mapping):
            execution_result = candidate
        break
    cleanup = transaction_cleanup_payload(
        prepared,
        phase=cleanup_phase,
        execution_result=execution_result,
    )
    return {
        "summary_only": True,
        "preview_summary": {
            "contract": artifact_map.get("contract"),
            "request": artifact_map.get("request"),
            "dispatch": prepared.get("dispatch"),
            "resolved_roles": prepared.get("resolved_roles"),
            "pre_state": prepared.get("pre_state"),
            "verification_plan": prepared.get("verification_plan"),
            "cleanup": cleanup,
            "project_guard_fingerprint": project_guard.get("fingerprint"),
            "runtime_guard_fingerprint": runtime_guard.get("fingerprint"),
            "expires_at": artifact_map.get("expires_at"),
        },
        "event_count": len(event_rows),
        "events": event_rows,
    }


def verification_deferred_payload(
    common: Mapping[str, Any],
    *,
    transaction_id: str,
    state: str,
    exc: Exception,
    cleanup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    structured = exc.as_dict() if hasattr(exc, "as_dict") and callable(exc.as_dict) else {}
    error_code = structured.get("error_code") if isinstance(structured, Mapping) else None
    details = structured.get("details") if isinstance(structured, Mapping) else None
    payload = {
        "ok": False,
        "status": "verification_deferred",
        **common,
        "transaction_id": transaction_id,
        "state": state,
        "error_code": error_code or type(exc).__name__,
        "message": str(exc),
        "details": details,
        "automatic_retry": False,
        "manual_verification_retry_allowed": True,
    }
    if cleanup is not None:
        payload["cleanup"] = dict(cleanup)
    return payload


def execution_success_persistence_failure_payload(
    common: Mapping[str, Any],
    *,
    store: TransactionStore,
    transaction_id: str,
    artifact_hash: str,
    prepared: Mapping[str, Any],
    dispatch_result: Mapping[str, Any],
    exc: BaseException,
) -> dict[str, Any]:
    """Preserve a completed mutation when its terminal journal write fails.

    Retrying a successful WAAPI mutation merely because the local completion
    record failed can duplicate work.  This response therefore keeps the
    execution and cleanup evidence, reports the best durable state we can read,
    and explicitly forbids automatic replay.
    """

    persistence_error = normalize_gateway_exception(exc)
    observed_state: str | None = None
    observation_error: dict[str, Any] | None = None
    try:
        observed_state = store.load(transaction_id).state.value
    except BaseException as state_exc:  # noqa: BLE001 - report, never mask, the primary write failure
        observation_error = normalize_gateway_exception(state_exc)
    details: dict[str, Any] = {
        "attempted_transition": TransactionState.EXECUTED_UNVERIFIED.value,
        "persistence_error": persistence_error,
        "durable_state_observed": observed_state is not None,
        "retry_warning": "The WAAPI call succeeded; replay could duplicate the mutation.",
    }
    if observed_state is not None:
        details["observed_durable_state"] = observed_state
    if observation_error is not None:
        details["state_observation_error"] = observation_error
    payload: dict[str, Any] = {
        "ok": False,
        "status": "execution_succeeded_persistence_failed",
        **common,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "error_code": "TRANSACTION_PERSISTENCE_FAILED",
        "message": (
            "The WAAPI mutation succeeded, but its durable transaction completion "
            "could not be recorded. Do not retry it automatically."
        ),
        "details": details,
        "dispatch_result": dict(dispatch_result),
        "executed": True,
        "verified": False,
        "cleanup": transaction_cleanup_payload(
            prepared,
            phase="executed",
            execution_result=dispatch_result,
        ),
        "automatic_retry": False,
    }
    if observed_state is not None:
        payload["state"] = observed_state
    return payload


def transaction_project_guard_spec(
    request: Mapping[str, Any],
    *,
    version: str,
) -> tuple[str, str | None]:
    """Resolve the immutable project guard mode from the public API contract."""

    if request.get("operation") != "waapi.call":
        return PROJECT_GUARD_INVARIANT, None
    arguments = request.get("arguments")
    if not isinstance(arguments, Mapping):
        return PROJECT_GUARD_INVARIANT, None
    api = arguments.get("api")
    if not isinstance(api, str):
        return PROJECT_GUARD_INVARIANT, None
    capability = CapabilityCatalog().describe(version, api)
    mode = capability.execution_contract.get("project_guard_mode", PROJECT_GUARD_INVARIANT)
    if not isinstance(mode, str) or mode not in PROJECT_GUARD_MODES:
        raise GatewayInputError(
            f"Execution contract for {api!r} has unsupported project_guard_mode {mode!r}"
        )
    target_project_path: str | None = None
    if mode == PROJECT_GUARD_TRANSITION_TO_PATH:
        call_args = arguments.get("args")
        target_value = call_args.get("path") if isinstance(call_args, Mapping) else None
        if not isinstance(target_value, str) or not target_value.strip():
            raise GatewayInputError(
                f"Project transition {api!r} requires an explicit target WPROJ path"
            )
        target_project_path = target_value
    return mode, target_project_path


def strengthen_project_transition_verification(
    verification: VerificationResult,
    *,
    guard_validation: Mapping[str, Any],
    project_call: Mapping[str, Any],
) -> VerificationResult:
    """Upgrade a generic result-schema receipt after a proven project transition."""

    if not verification.ok:
        return verification
    transition = guard_validation.get("project_transition")
    if not isinstance(transition, Mapping) or transition.get("matched") is not True:
        raise GatewayInputError(
            "Project transition verification requires one matched structured postcondition"
        )
    assertion = {
        "name": "live project matches the immutable transition postcondition",
        "passed": True,
        "evidence": dict(transition),
    }
    readback = {
        "kind": "project-transition-observation",
        "call": dispatch_call_summary(project_call),
        "project": transition.get("actual"),
    }
    return VerificationResult(
        operation=verification.operation,
        status="verified",
        assertions=(*verification.assertions, assertion),
        readbacks=(*verification.readbacks, readback),
        message="The returned WAAPI payload and live project transition postcondition both passed.",
        verification_strength=f"{verification.verification_strength}+project_transition_readback",
        business_state_verified=True,
    )


def current_project(
    dispatcher: WwiseDispatcher,
    *,
    connection: GatewayConnection,
    version: str,
    allow_none: bool = False,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
    if allow_none:
        # A successful bounded object query with zero Project rows is the only
        # accepted no-project observation.  WAAPI errors and malformed payloads
        # stay failures because their cross-version no-project shape is not a
        # safe contract to guess.
        project_call = dispatch(
            dispatcher,
            OBJECT_GET_URI,
            connection=connection,
            version=version,
            args={"waql": "from type Project take 2"},
            options={"return": ["id", "name", "type", "path"]},
        )
        if project_call.get("ok") is not True:
            raise GatewayInputError(
                "Project transition probe failed; refusing to infer that no project is open"
            )
        rows = strict_object_get_rows(
            project_call,
            command="transaction project transition guard",
            maximum_rows=1,
            error_code="INVALID_PROJECT_RESULT",
        )
        if not rows:
            return None, project_call
        project = require_single_result_row(
            rows,
            command="transaction project transition guard",
            error_code="INVALID_PROJECT_RESULT",
        )
        return require_project_identity(
            project,
            command="transaction project transition guard",
        ), project_call
    if version == "2021.1":
        project_call = dispatch(
            dispatcher,
            OBJECT_GET_URI,
            connection=connection,
            version=version,
            args={"waql": "from type Project take 1"},
            options={"return": ["id", "name", "type", "path"]},
        )
        rows = (
            strict_object_get_rows(
                project_call,
                command="transaction project guard",
                maximum_rows=1,
                error_code="INVALID_PROJECT_RESULT",
            )
            if project_call.get("ok")
            else []
        )
        if project_call.get("ok") is not True:
            raise GatewayInputError("2021.1 project guard object.get call failed")
        project = require_single_result_row(
            rows,
            command="transaction project guard",
            error_code="INVALID_PROJECT_RESULT",
        )
        return require_project_identity(project, command="transaction project guard"), project_call
    project_call = dispatch(
        dispatcher,
        GET_PROJECT_INFO_URI,
        connection=connection,
        version=version,
    )
    if project_call.get("ok") is not True:
        raise GatewayInputError("getProjectInfo failed while building the transaction project guard")
    project = strict_call_result_mapping(
        project_call,
        command="transaction project guard getProjectInfo",
        error_code="INVALID_PROJECT_RESULT",
    )
    return require_project_identity(project, command="transaction project guard"), project_call


def transaction_read_call(
    dispatcher: WwiseDispatcher,
    *,
    connection: GatewayConnection,
    version: str,
) -> Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]:
    def read(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri not in PACKAGED_TRANSACTION_READBACK_URIS:
            raise OperationContractError(
                "UNREVIEWED_READBACK_URI",
                f"Transaction readback URI {uri!r} is not in the packaged read-only allowlist.",
                details={"uri": uri},
            )
        result = dispatch(
            dispatcher,
            uri,
            connection=connection,
            version=version,
            args=args,
            options=options,
            # These exact URIs are operation-owned readbacks.  Some are routed
            # as confirmed transactions for public use, so the generic
            # dispatcher gate must be bypassed internally without broadening
            # the public direct-call surface.
            allow_destructive=True,
        )
        if result.get("ok") is not True:
            raise OperationContractError(
                "READBACK_FAILED",
                f"Read-only transaction preflight failed for {uri}.",
                details={"call": result},
            )
        payload = result.get("result")
        if not isinstance(payload, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                f"Read-only transaction preflight for {uri} did not return a JSON object.",
                details={"call": result},
            )
        return dict(payload)

    return read


def new_transaction_id() -> str:
    return f"tx-{uuid.uuid4().hex}"


def parse_json_object(text: str, option_name: str) -> dict[str, Any]:
    payload = parse_strict_json(text, option_name)
    if not isinstance(payload, dict):
        raise GatewayInputError(f"{option_name} must decode to a JSON object")
    return payload


def parse_optional_json(text: str | None, option_name: str) -> Any:
    if text is None:
        return None
    return parse_strict_json(text, option_name)


def parse_strict_json(text: str, option_name: str) -> Any:
    """Parse one bounded strict JSON document and validate its value graph."""

    if not isinstance(text, str):
        raise GatewayInputError(f"{option_name} must be a JSON string")
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise GatewayInputError(f"{option_name} must contain valid Unicode") from exc
    if encoded_size > MAX_GATEWAY_JSON_INPUT_BYTES:
        raise GatewayInputError(
            f"{option_name} exceeds the {MAX_GATEWAY_JSON_INPUT_BYTES}-byte JSON input limit"
        )
    try:
        payload = json.loads(
            text,
            parse_constant=_reject_non_json_constant,
            parse_float=_parse_strict_json_float,
            object_pairs_hook=_reject_duplicate_gateway_json_keys,
        )
    except json.JSONDecodeError as exc:
        raise GatewayInputError(f"{option_name} must be valid JSON: {exc.msg}") from exc
    except RecursionError as exc:
        raise GatewayInputError(
            f"{option_name} exceeds the {MAX_GATEWAY_JSON_DEPTH}-level JSON depth limit"
        ) from exc
    except ValueError as exc:
        raise GatewayInputError(f"{option_name} must be strict JSON: {exc}") from exc
    _validate_gateway_json_graph(payload, option_name=option_name)
    return payload


def _reject_non_json_constant(token: str) -> Any:
    raise ValueError(f"non-finite number {token!r} is not JSON")


def _parse_strict_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"non-finite number {token!r} is not JSON")
    return value


def _reject_duplicate_gateway_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _validate_gateway_json_graph(value: Any, *, option_name: str) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        if depth > MAX_GATEWAY_JSON_DEPTH:
            raise GatewayInputError(
                f"{option_name} exceeds the {MAX_GATEWAY_JSON_DEPTH}-level JSON depth limit"
            )
        nodes += 1
        if nodes > MAX_GATEWAY_JSON_NODES:
            raise GatewayInputError(
                f"{option_name} exceeds the {MAX_GATEWAY_JSON_NODES}-node JSON input limit"
            )
        if isinstance(current, str):
            _validate_gateway_json_string(current, option_name=option_name)
            continue
        if isinstance(current, float) and not math.isfinite(current):
            raise GatewayInputError(f"{option_name} must not contain non-finite numbers")
        if isinstance(current, dict):
            nodes += len(current)
            if nodes > MAX_GATEWAY_JSON_NODES:
                raise GatewayInputError(
                    f"{option_name} exceeds the {MAX_GATEWAY_JSON_NODES}-node JSON input limit"
                )
            for key, item in current.items():
                _validate_gateway_json_string(key, option_name=option_name)
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _validate_gateway_json_string(value: str, *, option_name: str) -> None:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise GatewayInputError(f"{option_name} must contain valid Unicode") from exc
    if size > MAX_GATEWAY_JSON_STRING_BYTES:
        raise GatewayInputError(
            f"{option_name} contains a string longer than the "
            f"{MAX_GATEWAY_JSON_STRING_BYTES}-byte string limit"
        )


def build_metadata_command_preview(args: argparse.Namespace, *, version: str) -> Any:
    builder = MetadataBuilder(version=version)
    if args.operation == "types":
        return builder.get_types()
    if args.operation == "names":
        return builder.get_property_and_reference_names(object=args.object, class_id=args.class_id)
    if args.operation == "property-info":
        return builder.get_property_info(property=args.property, object=args.object, class_id=args.class_id)
    if args.operation == "property-enabled":
        return builder.is_property_enabled(object=args.object, property=args.property, platform=args.platform)
    if args.operation == "attenuation-curve":
        return builder.get_attenuation_curve(
            object=args.object,
            curve_type=args.curve_type,
            platform=args.platform,
        )
    raise GatewayInputError(f"unsupported metadata operation: {args.operation}")


def normalize_metadata_result(operation: str, result: Mapping[str, Any]) -> Any:
    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayInputError(f"metadata {operation} result must be a JSON object")
    if operation == "types":
        return [record.as_dict() for record in parse_get_types_result(payload)]
    if operation == "names":
        return [record.as_dict() for record in parse_property_and_reference_names_result(payload)]
    if operation == "property-info":
        return parse_get_property_info_result(payload).as_dict()
    if operation == "property-enabled":
        return parse_is_property_enabled_result(payload).as_dict()
    if operation == "attenuation-curve":
        record = parse_get_attenuation_curve_result(payload, allow_documented_empty=True)
        return record.as_dict() if record is not None else None
    raise GatewayInputError(f"unsupported metadata operation: {operation}")


def normalize_topic_event_result(
    result: Mapping[str, Any],
    *,
    expected_topic: str,
) -> Any:
    """Unwrap and validate the dispatcher's SubscriptionEvent envelope."""

    wrapper = result.get("result")
    if not isinstance(wrapper, Mapping) or set(wrapper) != {"topic", "payload", "args", "kwargs"}:
        raise GatewayResultShapeError(
            "wait-topic requires the exact dispatcher event envelope.",
            details={
                "expected_fields": ["topic", "payload", "args", "kwargs"],
                "actual_fields": sorted(str(key) for key in wrapper) if isinstance(wrapper, Mapping) else None,
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    if wrapper.get("topic") != expected_topic:
        raise GatewayResultShapeError(
            "wait-topic dispatcher result changed the subscribed topic.",
            details={
                "expected_topic": expected_topic,
                "actual_topic": wrapper.get("topic"),
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    event_args = wrapper.get("args")
    event_kwargs = wrapper.get("kwargs")
    if not isinstance(event_args, (list, tuple)) or not isinstance(event_kwargs, Mapping):
        raise GatewayResultShapeError(
            "wait-topic dispatcher event args/kwargs have invalid shapes.",
            details={
                "args_type": type(event_args).__name__,
                "kwargs_type": type(event_kwargs).__name__,
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    expected_payload: Any
    if len(event_args) == 1:
        expected_payload = event_args[0]
    elif event_args:
        expected_payload = event_args
    else:
        expected_payload = event_kwargs
    payload = wrapper.get("payload")
    if payload != expected_payload:
        raise GatewayResultShapeError(
            "wait-topic dispatcher payload disagrees with its callback args/kwargs.",
            details={"topic": expected_topic},
            error_code="INVALID_TOPIC_RESULT",
        )
    return payload


def normalize_reflection_inventory_result(
    api: str,
    result: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    """Validate and normalize the two zero-input public reflection lists."""

    field, item_type = REFLECTION_INVENTORY_CALLS[api]
    payload = result.get("result")
    if not isinstance(payload, Mapping) or set(payload) != {field}:
        raise GatewayResultShapeError(
            f"{api} requires an exact result object containing only {field!r}.",
            details={
                "api": api,
                "expected_fields": [field],
                "actual_fields": sorted(str(key) for key in payload) if isinstance(payload, Mapping) else None,
            },
            error_code="INVALID_REFLECTION_RESULT",
        )
    raw_entries = payload.get(field)
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_REFLECTION_INVENTORY_ITEMS:
        raise GatewayResultShapeError(
            f"{api} requires a bounded JSON string array.",
            details={
                "api": api,
                "field": field,
                "maximum_items": MAX_REFLECTION_INVENTORY_ITEMS,
                "actual_count": len(raw_entries) if isinstance(raw_entries, list) else None,
            },
            error_code="INVALID_REFLECTION_RESULT",
        )
    live_uris: list[str] = []
    for index, uri in enumerate(raw_entries):
        if not isinstance(uri, str) or not uri or uri != uri.strip() or not uri.startswith("ak."):
            raise GatewayResultShapeError(
                f"{api} returned an invalid URI at index {index}.",
                details={"api": api, "field": field, "invalid_index": index},
                error_code="INVALID_REFLECTION_RESULT",
            )
        try:
            uri_size = len(uri.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise GatewayResultShapeError(
                f"{api} returned invalid Unicode at index {index}.",
                details={"api": api, "field": field, "invalid_index": index},
                error_code="INVALID_REFLECTION_RESULT",
            ) from exc
        if uri_size > MAX_REFLECTION_URI_BYTES:
            raise GatewayResultShapeError(
                f"{api} returned an oversized URI at index {index}.",
                details={
                    "api": api,
                    "field": field,
                    "invalid_index": index,
                    "maximum_uri_bytes": MAX_REFLECTION_URI_BYTES,
                },
                error_code="INVALID_REFLECTION_RESULT",
            )
        live_uris.append(uri)
    if len(set(live_uris)) != len(live_uris):
        raise GatewayResultShapeError(
            f"{api} returned duplicate URIs.",
            details={"api": api, "field": field, "actual_count": len(live_uris)},
            error_code="INVALID_REFLECTION_RESULT",
        )

    normalized = sorted(live_uris)
    packaged = sorted(
        entry.uri
        for entry in CapabilityCatalog().select(version, item_type=item_type)
    )
    live_set = set(normalized)
    packaged_set = set(packaged)
    missing = sorted(packaged_set - live_set)
    extra = sorted(live_set - packaged_set)
    return {
        "kind": item_type,
        "count": len(normalized),
        "uris": normalized,
        "packaged_manifest": {
            "count": len(packaged),
            "matches": not missing and not extra,
            "missing_count": len(missing),
            "extra_count": len(extra),
            "missing_sample": missing[:20],
            "extra_sample": extra[:20],
        },
    }


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GatewayInputError(f"{label} must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = execute_gateway(argv)
    print(gateway_stdout_json_encoder().encode(payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

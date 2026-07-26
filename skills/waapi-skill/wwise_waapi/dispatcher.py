"""Generic manifest-backed dispatcher for Wwise WAAPI calls and topics."""

from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .category_policy import (  # pyright: ignore[reportMissingImports]
    is_policy_exempt_category,
    is_unsafe_debug_live_uri,
    unsupported_live_behavior_message,
)
from .deferred_registry import ApiClassifier
from .manifest import ManifestResourceMissingError, ManifestStore
from .safety import requires_destructive_gate  # pyright: ignore[reportMissingImports]
from .subscriptions import (
    MAX_WAIT_EVENT_COUNT,
    SubscriptionCleanupError,
    SubscriptionEvent,
    SubscriptionManager,
    SubscriptionTimeout,
    SubscriptionUnavailable,
    payload_matches,
)

DEFAULT_WWISE_VERSION = "2022.1"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_LIVE_RESULT_JSON_BYTES = 1024 * 1024
LIVE_RESULT_CEILING_PROVENANCE = "waapi-skill.dispatcher.live-result-json-ceiling/v1"
SUBSCRIPTION_CLEANUP_DETAILS_KEY = "subscription_cleanup"
SUBSCRIPTION_CLEANUP_UNSUBSCRIBED = "unsubscribed"
SUBSCRIPTION_CLEANUP_FAILED = "unsubscribe_failed"
MAX_EXCEPTION_MESSAGE_BYTES = 2048
MAX_EXCEPTION_URI_BYTES = 512
MAX_EXCEPTION_METADATA_DEPTH = 16
MAX_EXCEPTION_METADATA_NODES = 256
MAX_EXCEPTION_METADATA_STRING_BYTES = 8192
ENV_ALLOW_DESTRUCTIVE = "WWISE_DESTRUCTIVE"
MANIFEST_ROOT = Path(__file__).resolve().parents[1] / "resources" / "manifest"
# Compatibility-only export for historical coverage-resource builders.  Runtime
# gating no longer uses this incomplete token set; see ``wwise_waapi.safety``.
DESTRUCTIVE_TOKENS = frozenset(
    {
        "close",
        "create",
        "createnewproject",
        "delete",
        "execute",
        "import",
        "migrate",
        "move",
        "open",
        "post",
        "rename",
        "reset",
        "set",
    }
)


class WaapiDispatchClient(Protocol):
    """Minimal injectable WAAPI client surface for function calls."""

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> Any:
        """Call a WAAPI function."""
        ...


@dataclass(slots=True, frozen=True)
class DispatcherRequest:
    """Normalized input accepted by :class:`WwiseDispatcher`."""

    api: str
    version: str = DEFAULT_WWISE_VERSION
    args: Mapping[str, Any] | None = None
    options: Mapping[str, Any] | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    dry_run: bool = False
    allow_destructive: bool = False
    evidence_dir: Path | None = None
    topic_mode: str = "wait"
    topic_match: Mapping[str, Any] | None = None
    live_behavior: bool = False
    result_limit_bytes: int = MAX_LIVE_RESULT_JSON_BYTES
    topic_event_count: int = 1


@dataclass(slots=True, frozen=True)
class ManifestApiEntry:
    """One reflected function or topic loaded from generated manifests."""

    uri: str
    item_type: str
    category: str
    risk_level: str


@dataclass(slots=True, frozen=True)
class _JsonSizeProbe:
    """Bounded result of measuring one deterministic JSON document."""

    size_bytes: int | None = None
    observed_at_least_bytes: int | None = None
    encoding_failed: bool = False


def _subscription_event_envelope(event: SubscriptionEvent) -> dict[str, Any]:
    """Keep one callback event in the dispatcher's private exact envelope."""

    return {
        "topic": event.topic,
        "payload": event.payload,
        "args": event.args,
        "kwargs": event.kwargs,
    }


def _subscription_cleanup_details(result: Mapping[str, Any]) -> dict[str, Any] | None:
    details = result.get("details")
    cleanup = (
        details.get(SUBSCRIPTION_CLEANUP_DETAILS_KEY)
        if isinstance(details, Mapping)
        else None
    )
    return dict(cleanup) if isinstance(cleanup, Mapping) else None


def _with_subscription_cleanup(
    result: Mapping[str, Any],
    *,
    status: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Attach one explicit bounded topic-cleanup fact to a dispatcher result."""

    published = dict(result)
    current_details = published.get("details")
    details = dict(current_details) if isinstance(current_details, Mapping) else {}
    cleanup: dict[str, Any] = {"status": status}
    if reason is not None:
        cleanup["reason"] = reason
    details[SUBSCRIPTION_CLEANUP_DETAILS_KEY] = cleanup
    published["details"] = details
    return published


@dataclass(slots=True)
class WwiseDispatcher:
    """Dispatch WAAPI functions and topics through generated manifests.

    The dispatcher is intentionally generic: a single manifest lookup validates every
    reflected WAAPI URI, then functions route to an injectable ``client.call`` and
    topics route to the existing bounded ``SubscriptionManager`` runtime.
    """

    client: WaapiDispatchClient | None = None
    manifest_store: ManifestStore = field(default_factory=lambda: ManifestStore(root=MANIFEST_ROOT))
    subscription_manager: SubscriptionManager | None = None
    classifier: ApiClassifier = field(default_factory=ApiClassifier)

    def dispatch(
        self,
        api: str | DispatcherRequest,
        *,
        version: str = DEFAULT_WWISE_VERSION,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        dry_run: bool = False,
        allow_destructive: bool = False,
        evidence_dir: str | Path | None = None,
        topic_mode: str = "wait",
        topic_match: Mapping[str, Any] | None = None,
        topic_event_count: int = 1,
        live_behavior: bool = False,
        result_limit_bytes: int = MAX_LIVE_RESULT_JSON_BYTES,
    ) -> dict[str, Any]:
        """Dispatch one WAAPI function or topic and return a structured result."""

        request = self._coerce_request(
            api,
            version=version,
            args=args,
            options=options,
            timeout=timeout,
            dry_run=dry_run,
            allow_destructive=allow_destructive,
            evidence_dir=evidence_dir,
            topic_mode=topic_mode,
            topic_match=topic_match,
            topic_event_count=topic_event_count,
            live_behavior=live_behavior,
            result_limit_bytes=result_limit_bytes,
        )
        try:
            result = self._dispatch(request)
        except Exception as exc:  # noqa: BLE001 - callers need structured WAAPI errors
            result = self._exception_result(request, exc)
        return self._publish_result(result, request)

    def _dispatch(self, request: DispatcherRequest) -> dict[str, Any]:
        if not request.api.strip():
            return self._error_result(request.api, request.version, "INVALID_API", "api must be a non-empty WAAPI URI")
        if math.isnan(request.timeout) or request.timeout < 0:
            return self._error_result(
                request.api,
                request.version,
                "INVALID_TIMEOUT",
                "timeout must be non-negative; positive infinity is allowed only for topics",
            )
        if not isinstance(request.result_limit_bytes, int) or isinstance(request.result_limit_bytes, bool) or request.result_limit_bytes <= 0:
            return self._error_result(
                request.api,
                request.version,
                "INVALID_RESULT_LIMIT",
                "result_limit_bytes must be a positive integer",
            )
        if (
            not isinstance(request.topic_event_count, int)
            or isinstance(request.topic_event_count, bool)
            or not 1 <= request.topic_event_count <= MAX_WAIT_EVENT_COUNT
        ):
            return self._error_result(
                request.api,
                request.version,
                "INVALID_TOPIC_EVENT_COUNT",
                f"topic_event_count must be an integer between 1 and {MAX_WAIT_EVENT_COUNT}",
            )

        entry = self._lookup_entry(request.version, request.api)
        if entry is None:
            return self._error_result(
                request.api,
                request.version,
                "API_NOT_FOUND",
                f"WAAPI URI {request.api!r} is not present in generated manifest {request.version}",
            )
        if entry.item_type != "topic" and not math.isfinite(request.timeout):
            return self._error_result(
                request.api,
                request.version,
                "INVALID_TIMEOUT",
                "timeout must be finite and non-negative for functions",
                item_type=entry.item_type,
                category=entry.category,
                risk_level=entry.risk_level,
            )
        if self._unsupported_live_behavior(request, entry):
            return self._error_result(
                request.api,
                request.version,
                "UNSUPPORTED_LIVE_BEHAVIOR",
                unsupported_live_behavior_message(request.api, entry.category),
                item_type=entry.item_type,
                category=entry.category,
                risk_level=entry.risk_level,
            )
        if request.dry_run:
            return self._success_result(
                request,
                entry,
                {
                    "dry_run": True,
                    "would_dispatch": entry.item_type,
                    "args": dict(request.args or {}),
                    "options": dict(request.options or {}),
                },
            )
        if self._is_destructive(entry) and not self._destructive_allowed(request):
            return self._error_result(
                request.api,
                request.version,
                "DESTRUCTIVE_BLOCKED",
                "Destructive WAAPI calls are blocked unless allow_destructive=True or WWISE_DESTRUCTIVE=1 is set",
                item_type=entry.item_type,
                category=entry.category,
                risk_level=entry.risk_level,
            )
        if entry.item_type == "function":
            return self._dispatch_function(request, entry)
        return self._dispatch_topic(request, entry)

    def _dispatch_function(self, request: DispatcherRequest, entry: ManifestApiEntry) -> dict[str, Any]:
        if self.client is None:
            return self._error_result(request.api, request.version, "CLIENT_UNAVAILABLE", "A WAAPI client is required for function calls")
        try:
            payload = _call_with_timeout(self.client, request.api, request.args, request.options, request.timeout)
        except TimeoutError as exc:
            return self._exception_result(request, exc, item_type=entry.item_type, error_code="TIMEOUT")
        except Exception as exc:  # noqa: BLE001 - preserve client error type in machine field
            return self._exception_result(request, exc, item_type=entry.item_type)
        return self._success_result(request, entry, payload)

    def _dispatch_topic(self, request: DispatcherRequest, entry: ManifestApiEntry) -> dict[str, Any]:
        if request.topic_mode != "wait":
            return self._error_result(
                request.api,
                request.version,
                "UNSUPPORTED_TOPIC_MODE",
                "topic_mode must be 'wait'; long-running listeners are owned by SubscriptionManager",
                item_type=entry.item_type,
            )
        manager = self.subscription_manager or SubscriptionManager(self.client)  # type: ignore[arg-type]
        try:
            wait_kwargs: dict[str, Any] = {
                "timeout": request.timeout,
                "options": dict(request.options or {}),
            }
            if request.topic_match is not None:
                expected = dict(request.topic_match)
                wait_kwargs["predicate"] = lambda event: payload_matches(event.payload, expected)
            if request.topic_event_count == 1:
                event = manager.wait_for_event(request.api, **wait_kwargs)
                payload: Any = _subscription_event_envelope(event)
            else:
                events = manager.wait_for_events(
                    request.api,
                    event_count=request.topic_event_count,
                    **wait_kwargs,
                )
                payload = {
                    "requested_event_count": request.topic_event_count,
                    "events": [_subscription_event_envelope(event) for event in events],
                }
        except SubscriptionCleanupError as exc:
            primary = exc.primary_error
            if isinstance(primary, KeyboardInterrupt):
                # Cancellation must remain cancellation even when the first
                # unsubscribe attempt fails. The gateway owns the transport
                # close/retry and the final structured cancellation result.
                raise primary from exc
            if isinstance(primary, SubscriptionTimeout):
                result = self._exception_result(
                    request,
                    primary,
                    item_type=entry.item_type,
                    error_code="TIMEOUT",
                )
            else:
                result = self._exception_result(
                    request,
                    exc,
                    item_type=entry.item_type,
                    error_code="SUBSCRIPTION_CLEANUP_FAILED",
                )
            return _with_subscription_cleanup(
                result,
                status=SUBSCRIPTION_CLEANUP_FAILED,
                reason=exc.reason,
            )
        except SubscriptionTimeout as exc:
            return _with_subscription_cleanup(
                self._exception_result(
                    request,
                    exc,
                    item_type=entry.item_type,
                    error_code="TIMEOUT",
                ),
                status=SUBSCRIPTION_CLEANUP_UNSUBSCRIBED,
            )
        except SubscriptionUnavailable as exc:
            return self._exception_result(
                request,
                exc,
                item_type=entry.item_type,
                error_code="SUBSCRIPTION_UNAVAILABLE",
            )
        return _with_subscription_cleanup(
            self._success_result(
                request,
                entry,
                payload,
            ),
            status=SUBSCRIPTION_CLEANUP_UNSUBSCRIBED,
        )

    def _lookup_entry(self, version: str, api: str) -> ManifestApiEntry | None:
        manifest = self.manifest_store.load(version)
        for item_type, section_name in (("function", "functions"), ("topic", "topics")):
            section = manifest.get(section_name, [])
            if not isinstance(section, list):
                continue
            for payload in section:
                if not isinstance(payload, Mapping) or payload.get("uri") != api:
                    continue
                classification = self.classifier.classify(api, item_type)
                return ManifestApiEntry(
                    uri=api,
                    item_type=item_type,
                    category=classification.category,
                    risk_level=classification.risk_level,
                )
        return None

    def _success_result(self, request: DispatcherRequest, entry: ManifestApiEntry, payload: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "api": request.api,
            "version": request.version,
            "item_type": entry.item_type,
            "category": entry.category,
            "risk_level": entry.risk_level,
            "timeout": "unbounded" if math.isinf(request.timeout) else request.timeout,
            "dry_run": request.dry_run,
            "result": payload,
            "error_code": None,
            "message": "ok",
            "evidence_path": None,
        }

    def _error_result(
        self,
        api: str,
        version: str,
        error_code: str,
        message: str,
        *,
        item_type: str | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        details: Mapping[str, Any] | None = None,
        waapi_error_uri: Any = None,
        waapi_error_details: Any = None,
    ) -> dict[str, Any]:
        result = {
            "ok": False,
            "api": api,
            "version": version,
            "item_type": item_type,
            "category": category,
            "risk_level": risk_level,
            "result": None,
            "error_code": error_code,
            "message": message or error_code,
            "evidence_path": None,
        }
        if isinstance(waapi_error_uri, str) and waapi_error_uri:
            result["waapi_error_uri"] = waapi_error_uri
        if details is not None:
            result["details"] = dict(details)
        if waapi_error_details is not None:
            result["waapi_error_details"] = waapi_error_details
        return result

    def _exception_result(
        self,
        request: DispatcherRequest,
        exc: Exception,
        *,
        item_type: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        """Normalize an untrusted exception without letting its hooks escape."""

        try:
            normalized = _normalize_exception(exc, error_code=error_code or self._error_code(exc))
            return self._error_result(
                request.api,
                request.version,
                normalized["error_code"],
                normalized["message"],
                item_type=item_type,
                details=normalized.get("details"),
                waapi_error_uri=normalized.get("waapi_error_uri"),
                waapi_error_details=normalized.get("waapi_error_details"),
            )
        except BaseException:  # noqa: BLE001 - hostile exception hooks must not cross dispatch
            return self._error_result(
                _bounded_public_string(request.api, "<omitted>", MAX_EXCEPTION_URI_BYTES),
                _bounded_public_string(request.version, "<omitted>", 80),
                "ERROR_NORMALIZATION_FAILED",
                "The underlying error could not be normalized safely",
                item_type=_bounded_public_string(item_type, None, 80),
            )

    def _publish_result(self, result: dict[str, Any], request: DispatcherRequest) -> dict[str, Any]:
        """Apply the live public ceiling before returning or recording evidence."""

        published_result = result if request.dry_run else self._constrain_live_result(result, request)
        evidence_dir = request.evidence_dir
        if evidence_dir is None:
            return published_result
        evidence_dir.mkdir(parents=True, exist_ok=True)
        safe_api = _bounded_public_string(published_result.get("api"), "unknown", 160)
        safe_api = safe_api.replace(".", "_").replace("/", "_") or "unknown"
        while True:
            path = evidence_dir / f"{time.time_ns()}-{uuid.uuid4().hex}-{safe_api}.json"
            recorded_result = dict(published_result)
            recorded_result["evidence_path"] = str(path)
            if not request.dry_run:
                recorded_result = self._constrain_live_result(recorded_result, request)
                recorded_result["evidence_path"] = str(path)
            payload = json.dumps(
                recorded_result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=request.dry_run,
            ) + "\n"
            try:
                with path.open("x", encoding="utf-8") as evidence_file:
                    evidence_file.write(payload)
            except FileExistsError:
                continue
            return recorded_result

    def _constrain_live_result(
        self,
        result: dict[str, Any],
        request: DispatcherRequest,
    ) -> dict[str, Any]:
        effective_limit = min(MAX_LIVE_RESULT_JSON_BYTES, request.result_limit_bytes)
        probe = _probe_json_document_size(result, effective_limit)
        common = {
            "item_type": _bounded_public_string(result.get("item_type"), None, 80),
            "category": _bounded_public_string(result.get("category"), None, 80),
            "risk_level": _bounded_public_string(result.get("risk_level"), None, 80),
        }
        bounded_api = _bounded_public_string(request.api, "<omitted>", 512)
        bounded_version = _bounded_public_string(request.version, "<omitted>", 80)
        cleanup_details = _subscription_cleanup_details(result)
        if probe.encoding_failed:
            details: dict[str, Any] = {
                "provenance": LIVE_RESULT_CEILING_PROVENANCE,
                "reason": "not_json_serializable",
            }
            if cleanup_details is not None:
                details[SUBSCRIPTION_CLEANUP_DETAILS_KEY] = cleanup_details
            return self._error_result(
                bounded_api,
                bounded_version,
                "RESULT_NOT_JSON",
                "Live WAAPI result is not a strict JSON document",
                details=details,
                **common,
            )
        if probe.observed_at_least_bytes is not None:
            details = {
                "limit_bytes": effective_limit,
                "observed_at_least_bytes": probe.observed_at_least_bytes,
                "provenance": LIVE_RESULT_CEILING_PROVENANCE,
            }
            if cleanup_details is not None:
                details[SUBSCRIPTION_CLEANUP_DETAILS_KEY] = cleanup_details
            return self._error_result(
                bounded_api,
                bounded_version,
                "RESULT_TOO_LARGE",
                "Live WAAPI result exceeded the public JSON size limit",
                details=details,
                **common,
            )
        return result

    def _coerce_request(self, api: str | DispatcherRequest, **kwargs: Any) -> DispatcherRequest:
        if isinstance(api, DispatcherRequest):
            return api
        evidence = kwargs["evidence_dir"]
        return DispatcherRequest(
            api=api,
            version=kwargs["version"],
            args=kwargs["args"],
            options=kwargs["options"],
            timeout=float(kwargs["timeout"]),
            dry_run=bool(kwargs["dry_run"]),
            allow_destructive=bool(kwargs["allow_destructive"]),
            evidence_dir=Path(evidence) if evidence is not None else None,
            topic_mode=str(kwargs["topic_mode"]),
            topic_match=kwargs["topic_match"],
            topic_event_count=kwargs["topic_event_count"],
            live_behavior=bool(kwargs["live_behavior"]),
            result_limit_bytes=int(kwargs["result_limit_bytes"]),
        )

    def _destructive_allowed(self, request: DispatcherRequest) -> bool:
        return request.allow_destructive or os.getenv(ENV_ALLOW_DESTRUCTIVE) == "1"

    def _is_destructive(self, entry: ManifestApiEntry) -> bool:
        return requires_destructive_gate(entry.uri, entry.item_type, entry.category)

    def _unsupported_live_behavior(self, request: DispatcherRequest, entry: ManifestApiEntry) -> bool:
        if request.dry_run:
            return False
        if is_unsafe_debug_live_uri(request.api, entry.category):
            return True
        return request.live_behavior and is_policy_exempt_category(entry.category)

    def _error_code(self, exc: Exception) -> str:
        if isinstance(exc, ManifestResourceMissingError):
            return "MANIFEST_NOT_FOUND"
        if isinstance(exc, TimeoutError):
            return "TIMEOUT"
        if isinstance(exc, ValueError):
            return "INVALID_REQUEST"
        return _safe_type_name(exc, "Exception")


def _safe_exception_attribute(exc: Exception, name: str) -> tuple[bool, Any]:
    """Read an optional third-party exception attribute without masking it."""

    try:
        return True, getattr(exc, name, None)
    except BaseException:  # noqa: BLE001 - a broken third-party property is not evidence
        return False, None


def _bounded_public_string(value: Any, fallback: Any, max_bytes: int) -> Any:
    """Keep trusted envelope labels bounded without serializing large inputs."""

    if not isinstance(value, str) or len(value) > max_bytes:
        return fallback
    try:
        return value if len(value.encode("utf-8")) <= max_bytes else fallback
    except UnicodeEncodeError:
        return fallback


def _safe_type_name(value: Any, fallback: str = "object") -> str:
    """Return a small type label without invoking instance ``repr`` or ``str``."""

    try:
        name = type.__getattribute__(type(value), "__name__")
    except BaseException:  # noqa: BLE001 - even hostile metaclasses are untrusted
        return fallback
    return _bounded_public_string(name, fallback, 160)


def _safe_exception_message(exc: Exception) -> str | None:
    try:
        message = str(exc)
    except BaseException:  # noqa: BLE001 - Exception.__str__ may call hostile repr hooks
        return None
    return _truncate_utf8(message, MAX_EXCEPTION_MESSAGE_BYTES)


def _normalize_exception(exc: Exception, *, error_code: str) -> dict[str, Any]:
    """Extract only bounded, JSON-safe fields from a third-party exception."""

    safe_code = _bounded_public_string(error_code, "ERROR_NORMALIZATION_FAILED", 160)
    message = _safe_exception_message(exc)
    if message is None:
        return {
            "error_code": "ERROR_NORMALIZATION_FAILED",
            "message": "The underlying error could not be normalized safely",
        }

    normalized: dict[str, Any] = {"error_code": safe_code, "message": message or safe_code}

    as_dict_ok, as_dict = _safe_exception_attribute(exc, "as_dict")
    if as_dict_ok and callable(as_dict):
        try:
            structured = as_dict()
            raw_details = structured.get("details") if isinstance(structured, Mapping) else None
            safe_details = _json_safe_exception_value(raw_details)
            if isinstance(safe_details, dict):
                normalized["details"] = safe_details
        except BaseException:  # noqa: BLE001 - optional metadata never masks the error
            pass

    uri_ok, uri = _safe_exception_attribute(exc, "uri")
    if uri_ok:
        safe_uri = _bounded_public_string(uri, None, MAX_EXCEPTION_URI_BYTES)
        if safe_uri:
            normalized["waapi_error_uri"] = safe_uri

    kwargs_ok, kwargs = _safe_exception_attribute(exc, "kwargs")
    if kwargs_ok and kwargs is not None:
        try:
            normalized["waapi_error_details"] = _json_safe_exception_value(kwargs)
        except BaseException:  # noqa: BLE001 - sanitizer failures are optional metadata loss
            pass
    return normalized


def _truncate_utf8(value: str, byte_budget: int) -> str:
    """Copy at most ``byte_budget`` valid UTF-8 bytes without a large encode."""

    if byte_budget <= 0:
        return ""
    parts: list[str] = []
    used = 0
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            character = "\ufffd"
            codepoint = 0xFFFD
        width = 1 if codepoint <= 0x7F else 2 if codepoint <= 0x7FF else 3 if codepoint <= 0xFFFF else 4
        if width > byte_budget - used:
            break
        parts.append(character)
        used += width
    return "".join(parts)


@dataclass(slots=True)
class _ExceptionMetadataSanitizer:
    """Budgeted copier for optional third-party exception metadata."""

    nodes_remaining: int = MAX_EXCEPTION_METADATA_NODES
    string_bytes_remaining: int = MAX_EXCEPTION_METADATA_STRING_BYTES
    active_ids: set[int] = field(default_factory=set)

    def sanitize(self, value: Any, *, depth: int = 0) -> Any:
        if self.nodes_remaining <= 0:
            return {"truncated": "node_budget"}
        self.nodes_remaining -= 1
        if depth > MAX_EXCEPTION_METADATA_DEPTH:
            return {"truncated": "depth_budget"}
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else {"type": "float", "reason": "non_finite"}
        if isinstance(value, str):
            return self._copy_string(value)
        if isinstance(value, Mapping):
            return self._sanitize_mapping(value, depth)
        if isinstance(value, (list, tuple)):
            return self._sanitize_sequence(value, depth)
        return {"type": _safe_type_name(value)}

    def _copy_string(self, value: str) -> str:
        copied = _truncate_utf8(value, self.string_bytes_remaining)
        self.string_bytes_remaining -= len(copied.encode("utf-8"))
        return copied

    def _sanitize_mapping(self, value: Mapping[Any, Any], depth: int) -> dict[str, Any]:
        identity = id(value)
        if identity in self.active_ids:
            return {"truncated": "circular_reference"}
        self.active_ids.add(identity)
        result: dict[str, Any] = {}
        try:
            try:
                iterator = iter(value.items())
            except BaseException:  # noqa: BLE001 - hostile Mapping implementation
                return {"type": _safe_type_name(value), "unavailable": "items"}
            while self.nodes_remaining > 0:
                try:
                    key, item = next(iterator)
                except StopIteration:
                    break
                except BaseException:  # noqa: BLE001 - partial safe metadata is sufficient
                    result["_metadata_unavailable"] = "items"
                    break
                safe_key = self._safe_key(key)
                result[safe_key] = self.sanitize(item, depth=depth + 1)
            else:
                result["_metadata_truncated"] = "node_budget"
            return result
        finally:
            self.active_ids.remove(identity)

    def _sanitize_sequence(self, value: list[Any] | tuple[Any, ...], depth: int) -> list[Any]:
        identity = id(value)
        if identity in self.active_ids:
            return [{"truncated": "circular_reference"}]
        self.active_ids.add(identity)
        result: list[Any] = []
        try:
            for item in value:
                if self.nodes_remaining <= 0:
                    result.append({"truncated": "node_budget"})
                    break
                result.append(self.sanitize(item, depth=depth + 1))
            return result
        finally:
            self.active_ids.remove(identity)

    def _safe_key(self, key: Any) -> str:
        if isinstance(key, str):
            return self._copy_string(key)
        if key is None:
            return "null"
        if key is True:
            return "true"
        if key is False:
            return "false"
        if isinstance(key, int):
            return int.__repr__(key)
        if isinstance(key, float) and math.isfinite(key):
            return float.__repr__(key)
        return f"<key-type:{_safe_type_name(key)}>"


def _json_safe_exception_value(value: Any) -> Any:
    """Copy third-party error metadata into a deterministic JSON-safe shape."""

    return _ExceptionMetadataSanitizer().sanitize(value)


def _probe_json_document_size(value: Any, limit_bytes: int) -> _JsonSizeProbe:
    """Measure deterministic UTF-8 JSON without materializing the document.

    The counter matches evidence and gateway rendering: UTF-8, sorted keys,
    two-space indentation, strict JSON numbers, and one trailing newline. It
    walks at most the configured byte budget, so a single untrusted string or
    a very wide container cannot force a second full-size serialization.
    """

    sizer = _BoundedJsonDocumentSizer(limit_bytes)
    try:
        sizer.measure(value)
        sizer.add_bytes(1)  # newline written by the public JSON document renderer
    except _JsonSizeExceeded:
        return _JsonSizeProbe(observed_at_least_bytes=limit_bytes + 1)
    except Exception:  # noqa: BLE001 - encoder failures become a stable public result
        return _JsonSizeProbe(encoding_failed=True)
    return _JsonSizeProbe(size_bytes=sizer.observed_bytes)


class _JsonSizeExceeded(Exception):
    """The deterministic JSON document crossed its configured byte ceiling."""


class _JsonEncodingRejected(Exception):
    """A value is not representable by the strict public JSON contract."""


class _BoundedJsonDocumentSizer:
    """Exact byte counter for the JSON subset emitted by the dispatcher."""

    def __init__(self, limit_bytes: int) -> None:
        if limit_bytes < 0:
            raise ValueError("JSON byte limit must be non-negative")
        self.limit_bytes = limit_bytes
        self.observed_bytes = 0
        self._active_container_ids: set[int] = set()

    def add_bytes(self, byte_count: int) -> None:
        if byte_count > self.limit_bytes - self.observed_bytes:
            raise _JsonSizeExceeded
        self.observed_bytes += byte_count

    def measure(self, value: Any, *, indent_level: int = 0) -> None:
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
                raise _JsonEncodingRejected
            self.add_bytes(len(float.__repr__(value)))
            return
        if isinstance(value, (list, tuple)):
            self._measure_array(value, indent_level)
            return
        if isinstance(value, dict):
            self._measure_object(value, indent_level)
            return
        raise _JsonEncodingRejected

    def _measure_string(self, value: str) -> None:
        self.add_bytes(2)
        for character in value:
            codepoint = ord(character)
            if character in {'"', "\\"} or character in {"\b", "\f", "\n", "\r", "\t"}:
                self.add_bytes(2)
            elif codepoint <= 0x1F:
                self.add_bytes(6)
            elif codepoint <= 0x7F:
                self.add_bytes(1)
            elif codepoint <= 0x7FF:
                self.add_bytes(2)
            elif 0xD800 <= codepoint <= 0xDFFF:
                raise _JsonEncodingRejected
            elif codepoint <= 0xFFFF:
                self.add_bytes(3)
            else:
                self.add_bytes(4)

    def _measure_array(self, value: list[Any] | tuple[Any, ...], indent_level: int) -> None:
        self.add_bytes(1)
        if not value:
            self.add_bytes(1)
            return
        next_indent = indent_level + 1
        item_indent_bytes = 1 + (2 * next_indent)
        separator_bytes = 2 + (2 * next_indent)
        closing_bytes = 2 + (2 * indent_level)
        minimum_size = item_indent_bytes + len(value) + (separator_bytes * (len(value) - 1)) + closing_bytes
        if minimum_size > self.limit_bytes - self.observed_bytes:
            raise _JsonSizeExceeded
        self._enter_container(value)
        try:
            self.add_bytes(item_indent_bytes)
            for index, item in enumerate(value):
                if index:
                    self.add_bytes(separator_bytes)
                self.measure(item, indent_level=next_indent)
            self.add_bytes(closing_bytes)
        finally:
            self._leave_container(value)

    def _measure_object(self, value: dict[Any, Any], indent_level: int) -> None:
        self.add_bytes(1)
        if not value:
            self.add_bytes(1)
            return
        next_indent = indent_level + 1
        item_indent_bytes = 1 + (2 * next_indent)
        separator_bytes = 2 + (2 * next_indent)
        closing_bytes = 2 + (2 * indent_level)
        minimum_item_bytes = 5  # empty quoted key, ': ', and a one-byte value
        minimum_size = (
            item_indent_bytes
            + (minimum_item_bytes * len(value))
            + (separator_bytes * (len(value) - 1))
            + closing_bytes
        )
        if minimum_size > self.limit_bytes - self.observed_bytes:
            raise _JsonSizeExceeded
        self._enter_container(value)
        try:
            keys = sorted(value)
            self.add_bytes(item_indent_bytes)
            for index, key in enumerate(keys):
                if index:
                    self.add_bytes(separator_bytes)
                self._measure_string(self._object_key_string(key))
                self.add_bytes(2)
                self.measure(value[key], indent_level=next_indent)
            self.add_bytes(closing_bytes)
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
                raise _JsonEncodingRejected
            return float.__repr__(key)
        raise _JsonEncodingRejected

    def _enter_container(self, value: Any) -> None:
        identity = id(value)
        if identity in self._active_container_ids:
            raise _JsonEncodingRejected
        self._active_container_ids.add(identity)

    def _leave_container(self, value: Any) -> None:
        self._active_container_ids.remove(id(value))


def _call_with_timeout(
    client: WaapiDispatchClient,
    api: str,
    args: Mapping[str, Any] | None,
    options: Mapping[str, Any] | None,
    timeout: float,
) -> Any:
    bounded_call = getattr(client, "call_with_timeout", None)
    if callable(bounded_call):
        return bounded_call(api, args, options=options, timeout=timeout)

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put((True, client.call(api, args, options=options)))
        except BaseException as exc:  # noqa: BLE001 - transferred to caller thread
            result_queue.put((False, exc))

    thread = threading.Thread(target=target, name=f"waapi-dispatch:{api}", daemon=True)
    thread.start()
    try:
        ok, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"Timed out after {timeout:.3f}s calling WAAPI function {api}") from exc
    if ok:
        return payload
    raise payload

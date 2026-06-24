"""Generic manifest-backed dispatcher for Wwise WAAPI calls and topics."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
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
from .subscriptions import SubscriptionManager, SubscriptionTimeout, SubscriptionUnavailable

DEFAULT_WWISE_VERSION = "2022.1"
DEFAULT_TIMEOUT_SECONDS = 10.0
ENV_ALLOW_DESTRUCTIVE = "WWISE_DESTRUCTIVE"
MANIFEST_ROOT = Path(__file__).resolve().parents[1] / "resources" / "manifest"
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
    live_behavior: bool = False


@dataclass(slots=True, frozen=True)
class ManifestApiEntry:
    """One reflected function or topic loaded from generated manifests."""

    uri: str
    item_type: str
    category: str
    risk_level: str


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
        live_behavior: bool = False,
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
            live_behavior=live_behavior,
        )
        try:
            result = self._dispatch(request)
        except Exception as exc:  # noqa: BLE001 - callers need structured WAAPI errors
            result = self._error_result(
                request.api,
                request.version,
                self._error_code(exc),
                str(exc),
            )
        return self._record_evidence(result, request.evidence_dir)

    def _dispatch(self, request: DispatcherRequest) -> dict[str, Any]:
        if not request.api.strip():
            return self._error_result(request.api, request.version, "INVALID_API", "api must be a non-empty WAAPI URI")
        if request.timeout < 0:
            return self._error_result(request.api, request.version, "INVALID_TIMEOUT", "timeout must be non-negative")

        entry = self._lookup_entry(request.version, request.api)
        if entry is None:
            return self._error_result(
                request.api,
                request.version,
                "API_NOT_FOUND",
                f"WAAPI URI {request.api!r} is not present in generated manifest {request.version}",
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
            return self._error_result(request.api, request.version, "TIMEOUT", str(exc), item_type=entry.item_type)
        except Exception as exc:  # noqa: BLE001 - preserve client error type in machine field
            return self._error_result(request.api, request.version, type(exc).__name__, str(exc), item_type=entry.item_type)
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
            event = manager.wait_for_event(request.api, timeout=request.timeout, options=dict(request.options or {}))
        except SubscriptionTimeout as exc:
            return self._error_result(request.api, request.version, "TIMEOUT", str(exc), item_type=entry.item_type)
        except SubscriptionUnavailable as exc:
            return self._error_result(request.api, request.version, "SUBSCRIPTION_UNAVAILABLE", str(exc), item_type=entry.item_type)
        return self._success_result(
            request,
            entry,
            {"topic": event.topic, "payload": event.payload, "args": event.args, "kwargs": event.kwargs},
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
            "timeout": request.timeout,
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
    ) -> dict[str, Any]:
        return {
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

    def _record_evidence(self, result: dict[str, Any], evidence_dir: Path | None) -> dict[str, Any]:
        if evidence_dir is None:
            return result
        evidence_dir.mkdir(parents=True, exist_ok=True)
        safe_api = result["api"].replace(".", "_").replace("/", "_") or "unknown"
        path = evidence_dir / f"{int(time.time() * 1000)}-{safe_api}.json"
        result = dict(result)
        result["evidence_path"] = str(path)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
            live_behavior=bool(kwargs["live_behavior"]),
        )

    def _destructive_allowed(self, request: DispatcherRequest) -> bool:
        return request.allow_destructive or os.getenv(ENV_ALLOW_DESTRUCTIVE) == "1"

    def _is_destructive(self, entry: ManifestApiEntry) -> bool:
        if entry.item_type != "function":
            return False
        operation = entry.uri.rsplit(".", 1)[-1].lower()
        return entry.risk_level == "high" or any(operation.startswith(token) for token in DESTRUCTIVE_TOKENS)

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
        return type(exc).__name__


def _call_with_timeout(
    client: WaapiDispatchClient,
    api: str,
    args: Mapping[str, Any] | None,
    options: Mapping[str, Any] | None,
    timeout: float,
) -> Any:
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

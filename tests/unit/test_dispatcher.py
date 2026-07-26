from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.dispatcher as dispatcher_module  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import DispatcherRequest, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.subscriptions import (  # pyright: ignore[reportMissingImports]
    SubscriptionCleanupError,
    SubscriptionEvent,
    SubscriptionTimeout,
)


class FakeWaapiClient:
    def __init__(self, *, result: Any | None = None, delay: float = 0.0, error: Exception | None = None) -> None:
        self.result = {"ok": "client"} if result is None else result
        self.delay = delay
        self.error = error
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> Any:
        self.calls.append((uri, args, options))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


class FakeSubscriptionManager:
    def __init__(self) -> None:
        self.waits: list[tuple[str, float, dict[str, Any] | None]] = []

    def wait_for_event(
        self,
        topic: str,
        timeout: float = 5.0,
        options: dict[str, Any] | None = None,
        queue_size: int = 1,
    ) -> SubscriptionEvent:
        self.waits.append((topic, timeout, options))
        return SubscriptionEvent(topic=topic, args=({"event": "payload"},), kwargs={"sequence": 1})


class PredicateSubscriptionManager:
    def __init__(self) -> None:
        self.predicate_result: bool | None = None

    def wait_for_event(
        self,
        topic: str,
        timeout: float = 5.0,
        options: dict[str, Any] | None = None,
        predicate: Any | None = None,
    ) -> SubscriptionEvent:
        event = SubscriptionEvent(topic=topic, args=({"object": {"id": "wanted", "name": "UI"}},))
        self.predicate_result = predicate(event) if predicate is not None else None
        return event


class MultiEventSubscriptionManager:
    def __init__(self) -> None:
        self.waits: list[tuple[str, int, float, dict[str, Any] | None]] = []
        self.predicate_results: list[bool] = []

    def wait_for_events(
        self,
        topic: str,
        event_count: int,
        timeout: float = 5.0,
        options: dict[str, Any] | None = None,
        predicate: Any | None = None,
    ) -> tuple[SubscriptionEvent, ...]:
        self.waits.append((topic, event_count, timeout, options))
        events = tuple(
            SubscriptionEvent(
                topic=topic,
                args=({"object": {"id": "wanted"}, "sequence": sequence},),
            )
            for sequence in range(1, event_count + 1)
        )
        self.predicate_results = [predicate(event) for event in events] if predicate is not None else []
        return events


class KeywordOnlyOptionsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, *, options: Mapping[str, Any] | None = None) -> Any:
        self.calls.append((uri, args, options))
        return {"ok": "keyword-options"}


def manifest_store() -> ManifestStore:
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "functions": [
                {"uri": "ak.wwise.core.getInfo"},
                {"uri": "ak.wwise.core.object.delete"},
                {"uri": "ak.wwise.core.object.setName"},
            ],
            "topics": [{"uri": "ak.wwise.core.object.created"}],
        },
    )
    return store


def streamed_json_document_size(value: Any) -> int:
    """Measure small boundary fixtures without materializing one JSON string."""

    encoder = json.JSONEncoder(ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    return sum(len(chunk.encode("utf-8")) for chunk in encoder.iterencode(value)) + 1


def test_dispatch_function_validates_manifest_and_calls_injected_client() -> None:
    client = FakeWaapiClient(result={"displayName": "Wwise"})
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = dispatcher.dispatch(
        "ak.wwise.core.getInfo",
        args={"platform": "Mac"},
        options={"return": ["displayName"]},
        timeout=0.5,
    )

    assert result["ok"] is True
    assert result["api"] == "ak.wwise.core.getInfo"
    assert result["item_type"] == "function"
    assert result["category"] == "core"
    assert result["result"] == {"displayName": "Wwise"}
    assert client.calls == [("ak.wwise.core.getInfo", {"platform": "Mac"}, {"return": ["displayName"]})]


def test_dispatch_function_passes_options_as_keyword_argument() -> None:
    client = KeywordOnlyOptionsClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = dispatcher.dispatch(
        "ak.wwise.core.getInfo",
        args={"platform": "Mac"},
        options={"return": ["displayName"]},
        timeout=0.5,
    )

    assert result["ok"] is True
    assert result["result"] == {"ok": "keyword-options"}
    assert client.calls == [("ak.wwise.core.getInfo", {"platform": "Mac"}, {"return": ["displayName"]})]


def test_unknown_api_returns_machine_readable_error_without_calling_client() -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.missing")

    assert result == {
        "ok": False,
        "api": "ak.wwise.core.missing",
        "version": "2022.1",
        "item_type": None,
        "category": None,
        "risk_level": None,
        "result": None,
        "error_code": "API_NOT_FOUND",
        "message": "WAAPI URI 'ak.wwise.core.missing' is not present in generated manifest 2022.1",
        "evidence_path": None,
    }
    assert client.calls == []


def test_destructive_function_is_blocked_by_default_and_dry_run_is_safe() -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    blocked = dispatcher.dispatch("ak.wwise.core.object.delete")
    dry_run = dispatcher.dispatch("ak.wwise.core.object.delete", dry_run=True)

    assert blocked["ok"] is False
    assert blocked["error_code"] == "DESTRUCTIVE_BLOCKED"
    assert dry_run["ok"] is True
    assert dry_run["result"]["dry_run"] is True
    assert dry_run["result"]["would_dispatch"] == "function"


@pytest.mark.parametrize(
    "uri",
    (
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.removeAssignment",
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.undo.endGroup",
        "ak.wwise.core.undo.undo",
    ),
)
def test_non_read_operations_missed_by_the_old_verb_heuristic_are_blocked(uri: str) -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client)

    result = dispatcher.dispatch(uri)

    assert result["ok"] is False
    assert result["error_code"] == "DESTRUCTIVE_BLOCKED"
    assert client.calls == []


def test_destructive_function_requires_explicit_opt_in() -> None:
    client = FakeWaapiClient(result={"deleted": 1})
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.object.delete", allow_destructive=True)

    assert result["ok"] is True
    assert result["result"] == {"deleted": 1}
    assert client.calls[0][0] == "ak.wwise.core.object.delete"


def test_topic_dispatch_uses_subscription_manager_without_reimplementing_subscriptions() -> None:
    manager = FakeSubscriptionManager()
    dispatcher = WwiseDispatcher(manifest_store=manifest_store(), subscription_manager=manager)  # type: ignore[arg-type]

    result = dispatcher.dispatch("ak.wwise.core.object.created", timeout=0.25, options={"filter": "fixture"})

    assert result["ok"] is True
    assert result["item_type"] == "topic"
    assert result["result"] == {
        "topic": "ak.wwise.core.object.created",
        "payload": {"event": "payload"},
        "args": ({"event": "payload"},),
        "kwargs": {"sequence": 1},
    }
    assert result["details"]["subscription_cleanup"] == {"status": "unsubscribed"}
    assert manager.waits == [("ak.wwise.core.object.created", 0.25, {"filter": "fixture"})]


def test_topic_cleanup_false_preserves_timeout_and_marks_cleanup_failure() -> None:
    class FailedCleanupManager:
        def wait_for_event(self, *args: Any, **kwargs: Any) -> SubscriptionEvent:
            del args, kwargs
            timeout = SubscriptionTimeout("Timed out waiting for topic")
            raise SubscriptionCleanupError(
                f"{timeout}; cleanup returned false",
                primary_error=timeout,
                reason="unsubscribe_returned_false",
            )

    dispatcher = WwiseDispatcher(
        manifest_store=manifest_store(),
        subscription_manager=FailedCleanupManager(),  # type: ignore[arg-type]
    )

    result = dispatcher.dispatch("ak.wwise.core.object.created", timeout=0.25)

    assert result["ok"] is False
    assert result["error_code"] == "TIMEOUT"
    assert result["details"]["subscription_cleanup"] == {
        "status": "unsubscribe_failed",
        "reason": "unsubscribe_returned_false",
    }


def test_topic_dispatch_supports_a_recursive_payload_match() -> None:
    manager = PredicateSubscriptionManager()
    dispatcher = WwiseDispatcher(manifest_store=manifest_store(), subscription_manager=manager)  # type: ignore[arg-type]

    result = dispatcher.dispatch(
        "ak.wwise.core.object.created",
        timeout=0.25,
        topic_match={"object": {"id": "wanted"}},
    )

    assert result["ok"] is True
    assert manager.predicate_result is True


def test_topic_dispatch_collects_a_bounded_matching_event_count() -> None:
    manager = MultiEventSubscriptionManager()
    dispatcher = WwiseDispatcher(manifest_store=manifest_store(), subscription_manager=manager)  # type: ignore[arg-type]

    result = dispatcher.dispatch(
        "ak.wwise.core.object.created",
        timeout=0.25,
        options={"return": ["id"]},
        topic_match={"object": {"id": "wanted"}},
        topic_event_count=3,
    )

    assert result["ok"] is True
    assert result["result"]["requested_event_count"] == 3
    assert [event["payload"]["sequence"] for event in result["result"]["events"]] == [1, 2, 3]
    assert manager.waits == [
        ("ak.wwise.core.object.created", 3, 0.25, {"return": ["id"]})
    ]
    assert manager.predicate_results == [True, True, True]


@pytest.mark.parametrize("event_count", (0, 65, True))
def test_dispatcher_rejects_invalid_topic_event_count(event_count: object) -> None:
    manager = MultiEventSubscriptionManager()
    dispatcher = WwiseDispatcher(manifest_store=manifest_store(), subscription_manager=manager)  # type: ignore[arg-type]

    result = dispatcher.dispatch(
        "ak.wwise.core.object.created",
        topic_event_count=event_count,  # type: ignore[arg-type]
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_TOPIC_EVENT_COUNT"
    assert manager.waits == []


def test_function_timeout_returns_structured_error() -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(delay=0.05), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo", timeout=0.001)

    assert result["ok"] is False
    assert result["error_code"] == "TIMEOUT"
    assert "Timed out" in result["message"]


@pytest.mark.parametrize("timeout", (float("nan"), float("inf"), float("-inf")))
def test_dispatcher_rejects_non_finite_timeout_without_calling_client(timeout: float) -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo", timeout=timeout)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_TIMEOUT"
    assert result["message"] == "timeout must be finite and non-negative"
    assert client.calls == []


def test_deadline_aware_client_avoids_helper_thread_and_preserves_timeout_details() -> None:
    class StructuredTimeout(TimeoutError):
        def as_dict(self) -> dict[str, Any]:
            return {
                "error_code": "TIMEOUT",
                "details": {
                    "phase": "WAAPI call ak.wwise.core.getInfo",
                    "cleanup_pending": True,
                },
            }

    class DeadlineAwareClient:
        def __init__(self) -> None:
            self.thread_ident: int | None = None
            self.timeout: float | None = None

        def call_with_timeout(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
            timeout: float | None = None,
        ) -> Any:
            del uri, args, options
            self.thread_ident = threading.get_ident()
            self.timeout = timeout
            raise StructuredTimeout("bounded timeout")

        def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
            raise AssertionError("deadline-aware clients must not use the helper-thread call path")

    client = DeadlineAwareClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())
    caller_ident = threading.get_ident()

    result = dispatcher.dispatch("ak.wwise.core.getInfo", timeout=0.125)

    assert result["ok"] is False
    assert result["error_code"] == "TIMEOUT"
    assert result["details"] == {
        "phase": "WAAPI call ak.wwise.core.getInfo",
        "cleanup_pending": True,
    }
    assert client.thread_ident == caller_ident
    assert client.timeout == 0.125


def test_client_error_preserves_exception_type_as_error_code() -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(error=RuntimeError("waapi exploded")), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "RuntimeError"
    assert result["message"] == "waapi exploded"


def test_client_error_preserves_structured_waapi_failure_metadata() -> None:
    class WaapiRequestFailed(Exception):
        def __init__(self) -> None:
            super().__init__("untrusted rendered application error")
            self.uri = "ak.wwise.query.invalid_query"
            self.kwargs = {"details": {"message": "Object not found (13)"}, "opaque": object()}

    dispatcher = WwiseDispatcher(client=FakeWaapiClient(error=WaapiRequestFailed()), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "WaapiRequestFailed"
    assert result["waapi_error_uri"] == "ak.wwise.query.invalid_query"
    assert result["waapi_error_details"]["details"] == {"message": "Object not found (13)"}
    assert result["waapi_error_details"]["opaque"] == {"type": "object"}
    json.dumps(result)


def test_exception_with_broken_as_dict_preserves_safe_standard_error() -> None:
    class BrokenAsDictError(Exception):
        def as_dict(self) -> dict[str, Any]:
            raise RuntimeError("broken as_dict")

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=BrokenAsDictError("safe message")),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "BrokenAsDictError"
    assert result["message"] == "safe message"
    assert "details" not in result
    assert len(json.dumps(result)) < 2048


def test_exception_with_broken_str_becomes_small_normalization_error() -> None:
    class BrokenStrError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("broken __str__")

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=BrokenStrError()),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "ERROR_NORMALIZATION_FAILED"
    assert result["message"] == "The underlying error could not be normalized safely"
    assert "waapi_error_uri" not in result
    assert "waapi_error_details" not in result
    assert len(json.dumps(result)) < 2048


def test_exception_with_broken_uri_and_kwargs_properties_preserves_standard_error() -> None:
    class BrokenMetadataPropertiesError(Exception):
        @property
        def uri(self) -> str:
            raise RuntimeError("broken uri")

        @property
        def kwargs(self) -> dict[str, Any]:
            raise RuntimeError("broken kwargs")

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=BrokenMetadataPropertiesError("safe message")),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["error_code"] == "BrokenMetadataPropertiesError"
    assert result["message"] == "safe message"
    assert "waapi_error_uri" not in result
    assert "waapi_error_details" not in result


def test_exception_metadata_depth_is_bounded_before_python_recursion_limit() -> None:
    metadata: dict[str, Any] = {}
    cursor = metadata
    for _ in range(2000):
        child: dict[str, Any] = {}
        cursor["next"] = child
        cursor = child

    class DeepMetadataError(Exception):
        def __init__(self) -> None:
            super().__init__("deep metadata")
            self.kwargs = metadata

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=DeepMetadataError()),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["error_code"] == "DeepMetadataError"
    assert result["message"] == "deep metadata"
    rendered = json.dumps(result, sort_keys=True)
    assert "depth_budget" in rendered
    assert len(rendered.encode("utf-8")) < 16 * 1024


@pytest.mark.parametrize("huge", (False, True))
def test_exception_metadata_never_invokes_unknown_object_repr(huge: bool) -> None:
    class ReprTrap:
        called = False

        def __repr__(self) -> str:
            type(self).called = True
            if huge:
                return "x" * (16 * 1024 * 1024)
            raise RuntimeError("repr must not be called")

    trap = ReprTrap()

    class OpaqueMetadataError(Exception):
        def __init__(self) -> None:
            super().__init__("opaque metadata")
            self.kwargs = {"opaque": trap}

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=OpaqueMetadataError()),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["error_code"] == "OpaqueMetadataError"
    assert result["waapi_error_details"] == {"opaque": {"type": "ReprTrap"}}
    assert ReprTrap.called is False
    assert len(json.dumps(result)) < 2048


def test_exception_metadata_string_and_node_budgets_are_explicitly_bounded() -> None:
    class WideMetadataError(Exception):
        def __init__(self) -> None:
            super().__init__("wide metadata")
            self.kwargs = {
                "huge": "z" * (dispatcher_module.MAX_EXCEPTION_METADATA_STRING_BYTES * 4),
                "wide": list(range(dispatcher_module.MAX_EXCEPTION_METADATA_NODES * 4)),
            }

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=WideMetadataError()),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["error_code"] == "WideMetadataError"
    assert len(result["waapi_error_details"]["huge"].encode("utf-8")) <= dispatcher_module.MAX_EXCEPTION_METADATA_STRING_BYTES
    assert "node_budget" in json.dumps(result["waapi_error_details"])
    assert len(json.dumps(result).encode("utf-8")) < 32 * 1024


def test_huge_live_success_is_replaced_by_bounded_error_without_returning_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert dispatcher_module.MAX_LIVE_RESULT_JSON_BYTES == 1024 * 1024
    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", 1024)
    sentinel = "HUGE_SUCCESS_SENTINEL_MUST_NOT_ESCAPE"
    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(result={"blob": sentinel + ("x" * 4096)}),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo", evidence_dir=tmp_path)

    assert result["ok"] is False
    assert result["error_code"] == "RESULT_TOO_LARGE"
    assert result["result"] is None
    assert result["details"] == {
        "limit_bytes": 1024,
        "observed_at_least_bytes": 1025,
        "provenance": dispatcher_module.LIVE_RESULT_CEILING_PROVENANCE,
    }
    assert sentinel not in json.dumps(result)
    evidence_path = Path(result["evidence_path"])
    evidence_bytes = evidence_path.read_bytes()
    assert evidence_path.stat().st_size <= 1024
    assert sentinel.encode("utf-8") not in evidence_bytes


def test_huge_waapi_error_details_are_not_written_to_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", 1024)
    sentinel = "HUGE_ERROR_SENTINEL_MUST_NOT_BE_RECORDED"

    class HugeWaapiError(Exception):
        def __init__(self) -> None:
            super().__init__("WAAPI rejected the request")
            self.uri = "ak.wwise.query.invalid_query"
            self.kwargs = {"details": {"blob": sentinel + ("y" * 4096)}}

    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=HugeWaapiError()),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo", evidence_dir=tmp_path)

    assert result["ok"] is False
    assert result["error_code"] == "RESULT_TOO_LARGE"
    assert result["details"] == {
        "limit_bytes": 1024,
        "observed_at_least_bytes": 1025,
        "provenance": dispatcher_module.LIVE_RESULT_CEILING_PROVENANCE,
    }
    assert "waapi_error_details" not in result
    evidence_path = Path(result["evidence_path"])
    evidence_bytes = evidence_path.read_bytes()
    assert evidence_path.stat().st_size <= 1024
    assert sentinel.encode("utf-8") not in evidence_bytes
    assert json.loads(evidence_bytes)["error_code"] == "RESULT_TOO_LARGE"


def test_live_result_ceiling_is_inclusive_at_and_below_the_exact_document_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(result={"displayName": "Wwise"}),
        manifest_store=manifest_store(),
    )
    baseline = dispatcher.dispatch("ak.wwise.core.getInfo")
    exact_size = streamed_json_document_size(baseline)
    assert exact_size < 4096

    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", exact_size + 1)
    below_limit = dispatcher.dispatch("ak.wwise.core.getInfo")
    assert below_limit["ok"] is True

    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", exact_size)
    at_limit = dispatcher.dispatch("ak.wwise.core.getInfo")
    assert at_limit["ok"] is True

    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", exact_size - 1)
    above_limit = dispatcher.dispatch("ak.wwise.core.getInfo")
    assert above_limit["error_code"] == "RESULT_TOO_LARGE"
    assert above_limit["details"]["observed_at_least_bytes"] == exact_size


@pytest.mark.parametrize("payload_factory", (object, lambda: float("nan")))
def test_non_json_live_results_fail_as_a_small_structured_result(payload_factory: Any) -> None:
    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(result=payload_factory()),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "RESULT_NOT_JSON"
    assert result["details"] == {
        "provenance": dispatcher_module.LIVE_RESULT_CEILING_PROVENANCE,
        "reason": "not_json_serializable",
    }


def test_mixed_unorderable_json_keys_match_sort_keys_serialization_failure() -> None:
    payload = {1: "integer", "2": "string"}
    with pytest.raises(TypeError):
        json.dumps(payload, sort_keys=True)
    dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(result=payload),
        manifest_store=manifest_store(),
    )

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "RESULT_NOT_JSON"
    assert result["details"]["reason"] == "not_json_serializable"


@pytest.mark.parametrize(
    "payload",
    (
        {2: "two", 1: "one"},
        {2: "integer", 1.5: "float"},
        {None: "none"},
        {False: "false"},
    ),
)
def test_size_probe_matches_sort_keys_json_for_supported_non_string_keys(payload: dict[Any, Any]) -> None:
    expected_size = streamed_json_document_size(payload)

    probe = dispatcher_module._probe_json_document_size(payload, expected_size)

    assert probe.encoding_failed is False
    assert probe.observed_at_least_bytes is None
    assert probe.size_bytes == expected_size


def test_circular_live_success_and_error_metadata_fail_structurally() -> None:
    circular_success: list[Any] = []
    circular_success.append(circular_success)
    success_dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(result=circular_success),
        manifest_store=manifest_store(),
    )

    success_result = success_dispatcher.dispatch("ak.wwise.core.getInfo")

    assert success_result["error_code"] == "RESULT_NOT_JSON"

    class CircularWaapiError(Exception):
        def __init__(self) -> None:
            super().__init__("cyclic metadata")
            details: dict[str, Any] = {}
            details["self"] = details
            self.kwargs = details

    error_dispatcher = WwiseDispatcher(
        client=FakeWaapiClient(error=CircularWaapiError()),
        manifest_store=manifest_store(),
    )

    error_result = error_dispatcher.dispatch("ak.wwise.core.getInfo")

    assert error_result["error_code"] == "CircularWaapiError"
    assert error_result["waapi_error_details"]["self"] == {"truncated": "circular_reference"}


def test_dry_run_metadata_is_not_subject_to_the_live_result_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", 128)
    metadata = "z" * 4096
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(), manifest_store=manifest_store())

    result = dispatcher.dispatch(
        "ak.wwise.core.object.delete",
        args={"metadata": metadata},
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["result"]["args"] == {"metadata": metadata}


def test_evidence_path_writes_success_or_error_payload(tmp_path: Path) -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo", evidence_dir=tmp_path)

    evidence_path = Path(result["evidence_path"])

    assert evidence_path.exists()
    assert evidence_path.parent == tmp_path
    assert '"ok": true' in evidence_path.read_text(encoding="utf-8")


def test_evidence_files_use_exclusive_creation_when_clock_and_uuid_candidates_collide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(), manifest_store=manifest_store())
    uuid_candidates = iter((UUID(int=1), UUID(int=1), UUID(int=2)))
    monkeypatch.setattr(dispatcher_module.time, "time_ns", lambda: 123456789)
    monkeypatch.setattr(dispatcher_module.uuid, "uuid4", lambda: next(uuid_candidates))

    first = dispatcher.dispatch("ak.wwise.core.getInfo", evidence_dir=tmp_path)
    first_path = Path(first["evidence_path"])
    first_payload_before_second_dispatch = first_path.read_bytes()
    second = dispatcher.dispatch("ak.wwise.core.getInfo", evidence_dir=tmp_path)
    second_path = Path(second["evidence_path"])

    assert first_path != second_path
    assert first_path.read_bytes() == first_payload_before_second_dispatch
    assert sorted(tmp_path.glob("*.json")) == sorted((first_path, second_path))
    for result, evidence_path in ((first, first_path), (second, second_path)):
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert payload["ok"] is True
        assert payload["api"] == "ak.wwise.core.getInfo"
        assert payload["evidence_path"] == result["evidence_path"]


def test_dispatcher_request_object_is_accepted() -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(result={"from": "request"}), manifest_store=manifest_store())

    result = dispatcher.dispatch(DispatcherRequest(api="ak.wwise.core.getInfo", timeout=0.5))

    assert result["ok"] is True
    assert result["result"] == {"from": "request"}

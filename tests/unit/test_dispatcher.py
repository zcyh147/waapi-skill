from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.dispatcher import DispatcherRequest, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.subscriptions import SubscriptionEvent  # pyright: ignore[reportMissingImports]


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
    assert manager.waits == [("ak.wwise.core.object.created", 0.25, {"filter": "fixture"})]


def test_function_timeout_returns_structured_error() -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(delay=0.05), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo", timeout=0.001)

    assert result["ok"] is False
    assert result["error_code"] == "TIMEOUT"
    assert "Timed out" in result["message"]


def test_client_error_preserves_exception_type_as_error_code() -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(error=RuntimeError("waapi exploded")), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo")

    assert result["ok"] is False
    assert result["error_code"] == "RuntimeError"
    assert result["message"] == "waapi exploded"


def test_evidence_path_writes_success_or_error_payload(tmp_path: Path) -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(), manifest_store=manifest_store())

    result = dispatcher.dispatch("ak.wwise.core.getInfo", evidence_dir=tmp_path)

    evidence_path = Path(result["evidence_path"])


    assert evidence_path.exists()
    assert evidence_path.parent == tmp_path
    assert '"ok": true' in evidence_path.read_text(encoding="utf-8")


def test_dispatcher_request_object_is_accepted() -> None:
    dispatcher = WwiseDispatcher(client=FakeWaapiClient(result={"from": "request"}), manifest_store=manifest_store())

    result = dispatcher.dispatch(DispatcherRequest(api="ak.wwise.core.getInfo", timeout=0.5))

    assert result["ok"] is True
    assert result["result"] == {"from": "request"}

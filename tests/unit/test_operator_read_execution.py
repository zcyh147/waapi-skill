from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.config import SkillConfig  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.operator import execute_operator_read  # pyright: ignore[reportMissingImports]


class FakeWaapiClient:
    def __init__(self, result: Any | None = None) -> None:
        self.result = {"return": []} if result is None else result
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> Any:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return {"version": "2022.1"}
        return self.result


def ready_config(tmp_path: Path) -> SkillConfig:
    return SkillConfig(tmp_path, wwise_version="2022.1", waapi_host="127.0.0.1", waapi_port=8080)


def manifest_store() -> ManifestStore:
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "functions": [
                {"uri": "ak.wwise.core.getInfo"},
                {"uri": "ak.wwise.core.object.get"},
            ],
            "topics": [],
        },
    )
    return store


def test_ready_bus_listing_dispatches_object_get_before_research_and_returns_rows(tmp_path: Path) -> None:
    client = FakeWaapiClient(
        {
            "return": [
                {"id": "{bus-1}", "name": "Master Audio Bus", "type": "Bus", "path": "\\Master-Mixer Hierarchy\\Default Work Unit"}
            ]
        }
    )
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    def research_hook() -> None:
        raise AssertionError("research must not run before live read dispatch")

    result = execute_operator_read(
        "list buses",
        config=ready_config(tmp_path),
        dispatcher=dispatcher,
        evidence_dir=tmp_path,
        research_hook=research_hook,
        connection_available=True,
    )

    assert result.status == "ok"
    assert result.rows == ({"id": "{bus-1}", "name": "Master Audio Bus", "type": "Bus", "path": "\\Master-Mixer Hierarchy\\Default Work Unit"},)
    assert "Master Audio Bus" in result.summary
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": "from type Bus"},
            {"return": ["id", "name", "type", "path"]},
        )
    ]
    assert result.evidence["research_called"] is False
    assert result.evidence["no_research_proof"] == "research_hook_not_invoked"
    assert result.evidence["dispatcher_result"]["ok"] is True
    assert Path(result.evidence["dispatcher_evidence_path"]).exists()


def test_waql_descendant_prompt_dispatches_read_only_object_get_with_explicit_returns(tmp_path: Path) -> None:
    client = FakeWaapiClient({"return": [{"id": "{sound-1}", "name": "Tone", "path": "\\Actor-Mixer Hierarchy\\Tone"}]})
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = execute_operator_read(
        "run WAQL descendants",
        config=ready_config(tmp_path),
        waql='"\\Actor-Mixer Hierarchy" select descendants',
        return_fields=("id", "name", "path"),
        dispatcher=dispatcher,
        connection_available=True,
    )

    assert result.status == "ok"
    assert result.policy.intent_family == "operator_waql"
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": '"\\Actor-Mixer Hierarchy" select descendants'},
            {"return": ["id", "name", "path"]},
        )
    ]
    assert result.evidence["dispatcher_request"]["dry_run"] is False
    assert result.evidence["dispatcher_request"]["allow_destructive"] is False


def test_prompt_only_descendant_query_uses_builder_path_select_and_name_prefix(tmp_path: Path) -> None:
    client = FakeWaapiClient({"return": [{"id": "{bus-1}", "name": "UI_Click", "path": "\\Master-Mixer Hierarchy\\UI_Click"}]})
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = execute_operator_read(
        "Find every descendant under Master-Mixer Hierarchy whose name starts with UI_",
        config=ready_config(tmp_path),
        dispatcher=dispatcher,
        connection_available=True,
    )

    assert result.status == "ok"
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {
                "waql": (
                    r'from object "\Master-Mixer Hierarchy" '
                    'select descendants where name : "UI_*"'
                )
            },
            {"return": ["id", "name", "type", "path"]},
        )
    ]
    assert result.evidence["dispatcher_request"]["allow_destructive"] is False
    assert result.evidence["dispatcher_request"]["dry_run"] is False


def test_blocked_setup_reports_missing_precondition_without_research_substitute(tmp_path: Path) -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    def research_hook() -> None:
        raise AssertionError("research must not substitute for blocked live setup")

    result = execute_operator_read(
        "list buses",
        config=SkillConfig(tmp_path),
        dispatcher=dispatcher,
        research_hook=research_hook,
        connection_available=False,
    )

    assert result.status == "blocked_setup"
    assert result.blockers == (
        "wwise_version is not configured",
        "waapi_port is not configured",
        "live WAAPI connection is unavailable",
    )
    assert "wwise_version is not configured" in result.summary
    assert result.evidence == {"research_called": False, "dispatcher_called": False}
    assert client.calls == []


def test_live_probe_failure_is_blocked_setup_without_research_substitute(tmp_path: Path) -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=ManifestStore())

    result = execute_operator_read(
        "list buses",
        config=ready_config(tmp_path),
        dispatcher=dispatcher,
        connection_available=None,
    )

    assert result.status == "blocked_setup"
    assert result.blockers == ("live WAAPI probe failed: API_NOT_FOUND",)
    assert result.evidence["research_called"] is False
    assert "probe_result" in result.evidence
    assert client.calls == []


def test_mutating_waql_is_rejected_without_dispatcher_live_call(tmp_path: Path) -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = execute_operator_read(
        "run this WAQL query",
        config=ready_config(tmp_path),
        waql="from type Sound; delete",
        dispatcher=dispatcher,
        connection_available=True,
    )

    assert result.status == "read_only_violation"
    assert result.blockers == ("Mutating WAQL is rejected by the read-only operator: delete",)
    assert result.evidence["dispatcher_called"] is False
    assert result.evidence["research_called"] is False
    assert client.calls == []


def test_mutation_shaped_prompt_is_read_only_violation_without_dispatcher_live_call(tmp_path: Path) -> None:
    client = FakeWaapiClient()
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = execute_operator_read(
        "create a new bus",
        config=ready_config(tmp_path),
        dispatcher=dispatcher,
        connection_available=True,
    )

    assert result.status == "read_only_violation"
    assert result.policy.intent_family == "operator_mutation_preview"
    assert result.evidence == {"research_called": False, "dispatcher_called": False}
    assert client.calls == []

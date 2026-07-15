from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT
from wwise_waapi.transactions import TransactionState, TransactionStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_transaction_gateway_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PARENT_GUID = "{22222222-2222-2222-2222-222222222222}"
OBJECT_GUID = "{33333333-3333-3333-3333-333333333333}"
CREATED_GUID = "{44444444-4444-4444-4444-444444444444}"
PROJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
PARENT_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Sandbox"
OBJECT_PATH = PARENT_PATH + r"\Existing"


class FakeClient:
    """A thread-safe-enough scripted client for the gateway owner thread."""

    def __init__(
        self,
        responses: Mapping[str, Sequence[Any]],
        *,
        errors: Mapping[str, Sequence[BaseException]] | None = None,
    ) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.errors = {uri: deque(values) for uri, values in (errors or {}).items()}
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []
        self.call_thread_idents: list[int] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        self.call_thread_idents.append(threading.get_ident())
        failures = self.errors.get(uri)
        if failures:
            raise failures.popleft()
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"Unexpected or exhausted WAAPI call: {uri} args={args!r} options={options!r}")
        return values.popleft()

    def disconnect(self) -> None:
        self.disconnected = True


def live_info(*, year: int = 2022, major: int = 1) -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "version": {
            "year": year,
            "major": major,
            "minor": 19,
            "build": 8584,
            "displayName": f"v{year}.{major}.19",
        },
    }


def project(
    *,
    project_id: str = PROJECT_GUID,
    name: str = "SampleProject",
    path: str = r"Y:\sandbox\SampleProject.wproj",
) -> dict[str, Any]:
    return {"id": project_id, "name": name, "path": path}


def parent_row() -> dict[str, Any]:
    return {
        "id": PARENT_GUID,
        "name": "WAAPI Sandbox",
        "type": "WorkUnit",
        "path": PARENT_PATH,
        "parent": {"id": "{actor-mixer-hierarchy}"},
        "notes": "",
    }


def object_row(*, path: str = OBJECT_PATH, notes: str = "before") -> dict[str, Any]:
    return {
        "id": OBJECT_GUID,
        "name": path.rsplit("\\", 1)[-1],
        "type": "Sound",
        "path": path,
        "parent": {"id": PARENT_GUID},
        "notes": notes,
    }


def created_row() -> dict[str, Any]:
    return {
        "id": CREATED_GUID,
        "name": "CreatedByGateway",
        "type": "PropertyContainer",
        "path": PARENT_PATH + r"\CreatedByGateway",
        "parent": {"id": PARENT_GUID},
        "notes": "created in transaction test",
    }


def create_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.create",
        "arguments": {
            "parent": {"kind": "id", "value": PARENT_GUID},
            "type": "ActorMixer",
            "name": "CreatedByGateway",
            "notes": "created in transaction test",
        },
    }


def set_notes_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_GUID},
            "value": "after",
        },
    }


def gateway_env(
    tmp_path: Path,
    *,
    state_dir: Path | None = None,
    version: str = "2022.1",
) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "wwise_version": None,
                    "waapi_host": "127.0.0.1",
                    "waapi_port": None,
                    "project_modification_policy": "preview_then_confirm",
                }
            ),
            encoding="utf-8",
        )
    result = {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }
    if state_dir is not None:
        result["WAAPI_SKILL_STATE_DIR"] = str(state_dir)
    return result


def execute(
    argv: Sequence[str],
    *,
    tmp_path: Path,
    state_dir: Path | None = None,
    env_state_dir: bool = False,
    client: FakeClient | None = None,
    version: str = "2022.1",
) -> tuple[int, dict[str, Any]]:
    arguments = list(argv)
    if state_dir is not None and not env_state_dir:
        arguments = ["--state-dir", str(state_dir), *arguments]
    env = gateway_env(
        tmp_path,
        state_dir=state_dir if env_state_dir else None,
        version=version,
    )

    def factory(url: str) -> FakeClient:
        if client is None:
            raise AssertionError(f"Offline transaction command unexpectedly connected to {url}")
        return client

    return waapi_gateway.execute_gateway(arguments, env=env, client_factory=factory)


def preview(
    request: Mapping[str, Any],
    *,
    tmp_path: Path,
    state_dir: Path,
    client: FakeClient,
    ttl: int = 300,
) -> dict[str, Any]:
    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(request), "--ttl", str(ttl)],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )
    assert exit_code == 0, payload
    assert payload["ok"] is True
    assert payload["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert isinstance(payload["transaction_id"], str) and payload["transaction_id"]
    assert isinstance(payload["artifact_hash"], str) and len(payload["artifact_hash"]) == 64
    assert isinstance(payload["preview_summary"], Mapping)
    return payload


def confirm(
    transaction_id: str,
    artifact_hash: str,
    *,
    tmp_path: Path,
    state_dir: Path,
) -> dict[str, Any]:
    exit_code, payload = execute(
        ["confirm", transaction_id, "--artifact-hash", artifact_hash],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.CONFIRMED.value
    return payload


def execute_set_notes_successfully(*, tmp_path: Path, state_dir: Path) -> dict[str, Any]:
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )
    transaction = preview(set_notes_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
            "ak.wwise.core.object.setNotes": [{}],
        }
    )
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return transaction


def test_operations_and_operation_schema_are_offline_closed_contracts(tmp_path: Path) -> None:
    exit_code, catalog = execute(["operations"], tmp_path=tmp_path)

    assert exit_code == 0
    assert catalog["ok"] is True
    assert catalog["offline"] is True
    operations = {item["name"]: item for item in catalog["operations"]}
    assert set(operations["object.create"]) == {
        "name",
        "uri",
        "family",
        "summary",
        "implemented",
        "boundary",
        "supported_versions",
        "required_arguments",
        "optional_arguments",
    }
    assert operations["object.create"]["implemented"] is True
    assert operations["object.copy"]["implemented"] is False
    assert "returned copy GUID" in operations["object.copy"]["boundary"]
    assert "argument_contract" not in operations["object.create"]
    compact_json = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    assert len(compact_json) < 12_000

    exit_code, detail_catalog = execute(["operations", "--detail"], tmp_path=tmp_path)

    assert exit_code == 0
    detailed = {item["name"]: item for item in detail_catalog["operations"]}
    assert detailed["object.create"]["additional_properties"] is False
    assert "argument_contract" in detailed["object.create"]
    assert "constraints" in detailed["object.create"]
    assert "identity_contract" in detailed["object.create"]

    exit_code, schema = execute(["operation-schema", "object.setNotes"], tmp_path=tmp_path)

    assert exit_code == 0
    assert schema["ok"] is True
    assert schema["offline"] is True
    assert schema["operation"]["name"] == "object.setNotes"
    assert schema["operation"]["required_arguments"] == ["object", "value"]
    assert schema["operation"]["additional_properties"] is False
    assert "argument_contract" in schema["operation"]
    assert "identity_contract" in schema["operation"]


def test_transaction_show_reads_immutable_artifact_and_journal_without_wwise(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    artifact = {"contract": "test-preview/v1", "prepared_operation": {"operation": "object.setNotes"}}
    created = store.create_preview("tx-show", artifact)
    store.submit_for_confirmation("tx-show")

    exit_code, payload = execute(
        ["transaction-show", "tx-show"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["transaction_id"] == "tx-show"
    assert payload["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert payload["artifact_hash"] == created.artifact_hash
    assert payload["artifact"] == artifact
    assert [event["event_type"] for event in payload["events"]] == [
        "preview_created",
        "confirmation_requested",
    ]


def test_transaction_show_summary_omits_raw_artifact_bulk_but_keeps_review_evidence(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    artifact = {
        "contract": "waapi-skill.transaction-preview/v1",
        "request": {"operation": "object.setNotes"},
        "prepared_operation": {
            "dispatch": {"uri": "ak.wwise.core.object.setNotes"},
            "resolved_roles": {"object": {"id": "fixture"}},
            "pre_state": {"notes": "before"},
            "verification_plan": [{"read": "notes"}],
            "cleanup": {"required": False},
        },
        "project_guard": {"fingerprint": "project-fingerprint", "large": "x" * 4096},
        "runtime_guard": {"fingerprint": "runtime-fingerprint", "files": {"large": "y" * 4096}},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    created = store.create_preview("tx-summary", artifact)
    store.submit_for_confirmation("tx-summary")

    exit_code, payload = execute(
        ["transaction-show", "tx-summary", "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["artifact_hash"] == created.artifact_hash
    assert payload["summary_only"] is True
    assert "artifact" not in payload
    assert payload["preview_summary"]["request"] == {"operation": "object.setNotes"}
    assert payload["preview_summary"]["project_guard_fingerprint"] == "project-fingerprint"
    assert payload["preview_summary"]["runtime_guard_fingerprint"] == "runtime-fingerprint"
    assert [event["event_type"] for event in payload["events"]] == [
        "preview_created",
        "confirmation_requested",
    ]


def test_confirm_uses_environment_state_dir_and_never_connects_to_wwise(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview("tx-confirm", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-confirm")

    exit_code, payload = execute(
        ["confirm", "tx-confirm", "--artifact-hash", created.artifact_hash],
        tmp_path=tmp_path,
        state_dir=state_dir,
        env_state_dir=True,
    )

    assert exit_code == 0
    assert payload["contract"] == "waapi-skill.gateway-result/v1"
    assert payload["ok"] is True
    assert payload["offline"] is True
    assert payload["command"] == "confirm"
    assert payload["transaction_id"] == "tx-confirm"
    assert payload["state"] == TransactionState.CONFIRMED.value
    assert payload["artifact_hash"] == created.artifact_hash
    assert store.load("tx-confirm").state is TransactionState.CONFIRMED


def test_execute_rechecks_external_never_policy_after_prior_confirmation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview("tx-policy-drift", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-policy-drift")

    confirm_code, confirmed = execute(
        ["confirm", "tx-policy-drift", "--artifact-hash", created.artifact_hash],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert confirm_code == 0
    assert confirmed["state"] == TransactionState.CONFIRMED.value

    config_path = tmp_path / "config" / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "never",
            }
        ),
        encoding="utf-8",
    )
    exit_code, payload = execute(
        ["execute", "tx-policy-drift"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["message"] == "project_modification_policy=never blocks transaction execution"
    assert store.load("tx-policy-drift").state is TransactionState.CONFIRMED


def test_confirm_rejects_tampered_hash_and_preserves_awaiting_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    store.create_preview("tx-hash", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-hash")

    exit_code, payload = execute(
        ["confirm", "tx-hash", "--artifact-hash", "0" * 64],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "ArtifactIntegrityError"
    assert store.load("tx-hash").state is TransactionState.AWAITING_CONFIRMATION


def test_reject_persists_reason_and_is_an_offline_terminal_transition(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview("tx-reject", {"operation": "object.delete"})
    store.submit_for_confirmation("tx-reject")

    exit_code, payload = execute(
        ["reject", "tx-reject", "--reason", "target is outside the sandbox"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["transaction_id"] == "tx-reject"
    assert payload["state"] == TransactionState.REJECTED.value
    assert payload["artifact_hash"] == created.artifact_hash
    events = store.read_events("tx-reject")
    assert events[-1]["event_type"] == "rejected"
    assert events[-1]["details"] == {"reason": "target is outside the sandbox"}


def test_preview_live_resolves_and_persists_immutable_awaiting_artifact_with_ttl(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [parent_row()]}],
        }
    )

    payload = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=client, ttl=90)

    store = TransactionStore(state_dir)
    stored = store.load_preview(payload["transaction_id"])
    record = store.load(payload["transaction_id"])
    assert record.state is TransactionState.AWAITING_CONFIRMATION
    assert stored.artifact_hash == payload["artifact_hash"]
    assert stored.artifact["request"] == create_request()
    assert payload["agent_result"] == {
        "operation": "object.create",
        "transaction_id": payload["transaction_id"],
        "artifact_hash": payload["artifact_hash"],
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "request": stored.artifact["request"],
    }
    assert stored.artifact["prepared_operation"]["dispatch"]["uri"] == "ak.wwise.core.object.create"
    created_at = datetime.fromisoformat(stored.artifact["created_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(stored.artifact["expires_at"].replace("Z", "+00:00"))
    assert (expires_at - created_at).total_seconds() == 90
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
    ]
    assert not any(call[0] == "ak.wwise.core.object.create" for call in client.calls)


def test_preview_agent_result_preserves_quotes_backslashes_and_unicode_from_artifact(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    request = set_notes_request()
    request["arguments"]["value"] = '中文“引号” / JSON "quote" / path \\尾部'
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )

    payload = preview(request, tmp_path=tmp_path, state_dir=state_dir, client=client)
    stored_request = TransactionStore(state_dir).load_preview(payload["transaction_id"]).artifact["request"]

    assert payload["agent_result"] == {
        "operation": "object.setNotes",
        "transaction_id": payload["transaction_id"],
        "artifact_hash": payload["artifact_hash"],
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "request": stored_request,
    }
    encoded = json.dumps(payload["agent_result"], ensure_ascii=False, separators=(",", ":"))
    assert json.loads(encoded) == payload["agent_result"]
    assert payload["agent_result"]["request"]["arguments"]["value"] == request["arguments"]["value"]


def test_preview_rejects_transaction_state_inside_live_project_before_state_write(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "live-project"
    project_root.mkdir()
    state_dir = project_root / ".waapi-state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [
                project(path=str(project_root / "SampleProject.wproj"))
            ],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(create_request())],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "outside the live Wwise project" in payload["message"]
    assert not state_dir.exists()
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


@pytest.mark.parametrize(
    "invalid_project",
    (
        {},
        {"id": "", "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"},
        {"id": "{project}", "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"},
        {"id": PROJECT_GUID, "name": "", "path": r"Y:\sandbox\SampleProject.wproj"},
        {"id": PROJECT_GUID, "name": "SampleProject", "path": ""},
    ),
)
def test_preview_rejects_project_without_stable_id_name_path_guard(
    tmp_path: Path,
    invalid_project: Mapping[str, Any],
) -> None:
    state_dir = tmp_path / "state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [invalid_project],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(create_request())],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_PROJECT_RESULT"
    assert payload["details"]["invalid_fields"]
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert not any(path.is_file() for path in state_dir.rglob("*"))


@pytest.mark.parametrize(
    "project_rows",
    (
        [{}],
        [{"id": "{project}", "name": "SampleProject", "type": "Project", "path": "\\"}],
        [
            {"id": PROJECT_GUID, "name": "One", "type": "Project", "path": "\\"},
            {"id": "{55555555-5555-5555-5555-555555555555}", "name": "Two", "type": "Project", "path": "\\"},
        ],
    ),
)
def test_2021_preview_rejects_malformed_or_multiple_project_rows(
    tmp_path: Path,
    project_rows: list[Mapping[str, Any]],
) -> None:
    state_dir = tmp_path / "state"
    request = dict(create_request())
    request["version"] = "2021.1"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2021, major=1)],
            "ak.wwise.core.object.get": [{"return": project_rows}],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(request)],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
        version="2021.1",
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_PROJECT_RESULT"
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.object.get",
    ]
    assert not any(path.is_file() for path in state_dir.rglob("*"))


def test_execute_is_blocked_before_mutation_without_confirmation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [parent_row()]}],
        }
    )
    transaction = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert not any(call[0] == "ak.wwise.core.object.create" for call in execute_client.calls)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.AWAITING_CONFIRMATION


def test_execute_project_drift_requires_repreview_without_role_read_or_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [parent_row()]}],
        }
    )
    transaction = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project(name="OtherProject", path=r"Y:\other\OtherProject.wproj")],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.REPREVIEW_REQUIRED.value
    assert "agent_result" not in payload
    assert payload["guard_validation"]["error_code"] == "PROJECT_GUARD_MISMATCH"
    assert [call[0] for call in execute_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.REPREVIEW_REQUIRED


def test_execute_role_drift_requires_repreview_before_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )
    transaction = preview(set_notes_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    moved_path = PARENT_PATH + r"\MovedElsewhere"
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row(path=moved_path)]}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.REPREVIEW_REQUIRED.value
    assert "agent_result" not in payload
    assert payload["role_validation"]["status"] == "repreview_required"
    assert not any(call[0] == "ak.wwise.core.object.setNotes" for call in execute_client.calls)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.REPREVIEW_REQUIRED


def test_create_execute_persists_result_and_verify_reads_back_returned_guid(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [parent_row()]}],
        }
    )
    transaction = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [parent_row()]}],
            "ak.wwise.core.object.create": [{"id": CREATED_GUID}],
        }
    )

    exit_code, executed = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["dispatch_result"]["result"] == {"id": CREATED_GUID}
    mutation_calls = [call for call in execute_client.calls if call[0] == "ak.wwise.core.object.create"]
    assert len(mutation_calls) == 1
    assert mutation_calls[0][1] == {
        "parent": PARENT_GUID,
        "type": "ActorMixer",
        "name": "CreatedByGateway",
        "onNameConflict": "fail",
        "notes": "created in transaction test",
        "autoAddToSourceControl": False,
    }

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [created_row()]}],
        }
    )
    exit_code, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert exit_code == 0, verified
    assert verified["state"] == TransactionState.VERIFIED.value
    assert verified["verification"]["status"] == "verified"
    assert verified["agent_result"] == {
        "operation": "object.create",
        "transaction_id": transaction["transaction_id"],
        "artifact_hash": transaction["artifact_hash"],
        "state": TransactionState.VERIFIED.value,
        "executed": True,
        "verified": True,
        "request": create_request(),
    }
    readback = next(call for call in verify_client.calls if call[0] == "ak.wwise.core.object.get")
    assert readback[1] == {"from": {"id": [CREATED_GUID]}}
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.VERIFIED


def test_verify_failed_postcondition_becomes_terminal_verification_failed(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    transaction = execute_set_notes_successfully(tmp_path=tmp_path, state_dir=state_dir)
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row(notes="not the requested value")]}],
        }
    )

    exit_code, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.VERIFICATION_FAILED.value
    assert payload["verification"]["status"] == "verification_failed"
    assert "agent_result" not in payload
    assert any(
        assertion["name"] == "notes match exactly" and assertion["passed"] is False
        for assertion in payload["verification"]["assertions"]
    )
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.VERIFICATION_FAILED


def test_verify_readback_exception_is_deferred_for_explicit_manual_retry(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    transaction = execute_set_notes_successfully(tmp_path=tmp_path, state_dir=state_dir)
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [],
        },
        errors={"ak.wwise.core.object.get": [RuntimeError("readback connection failed")]},
    )

    exit_code, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert payload["status"] == "verification_deferred"
    assert "agent_result" not in payload
    assert payload["automatic_retry"] is False
    assert payload["manual_verification_retry_allowed"] is True
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.EXECUTED_UNVERIFIED


def test_execute_exception_is_indeterminate_and_a_second_execute_never_retries(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )
    transaction = preview(set_notes_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    first_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
            "ak.wwise.core.object.setNotes": [],
        },
        errors={"ak.wwise.core.object.setNotes": [RuntimeError("connection lost after dispatch")]},
    )

    first_exit, first_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=first_client,
    )

    assert first_exit == 2
    assert first_payload["state"] == TransactionState.INDETERMINATE.value
    assert "agent_result" not in first_payload
    assert len([call for call in first_client.calls if call[0] == "ak.wwise.core.object.setNotes"]) == 1
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.INDETERMINATE

    second_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    second_exit, second_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=second_client,
    )

    assert second_exit == 2
    assert second_payload["ok"] is False
    assert "agent_result" not in second_payload
    assert not any(call[0] == "ak.wwise.core.object.setNotes" for call in second_client.calls)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.INDETERMINATE

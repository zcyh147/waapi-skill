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

from wwise_waapi.execution_contracts import (  # pyright: ignore[reportMissingImports]
    PROJECT_GUARD_TRANSITION_TO_NONE,
    PROJECT_GUARD_TRANSITION_TO_PATH,
    ExecutionContractRegistry,
)
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

PROJECT_TRANSITION_ROWS = tuple(
    (entry.version, entry.uri, entry.project_guard_mode)
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
    for entry in ExecutionContractRegistry().entries(version)
    if entry.uri.startswith(("ak.wwise.ui.project.", "ak.wwise.console.project."))
)


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


def generic_manifest_call_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.project.save",
            "args": {},
            "options": {},
        },
    }


def generic_public_call_request(
    api: str,
    args: Mapping[str, Any],
    *,
    version: str = "2025.1",
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": dict(args),
            "options": {},
        },
    }


def generic_isolated_call_request(io_root: Path) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2023.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.debug.generateToneWAV",
            "args": {"path": str(io_root / "tone.wav")},
            "options": {},
            "io_root": str(io_root),
        },
    }


def undo_group_request(*, version: str = "2023.1") -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.undoGroup",
        "arguments": {
            "display_name": "Program Undo Group",
            "calls": [
                {
                    "api": "ak.wwise.core.object.setNotes",
                    "args": {"object": OBJECT_GUID, "value": "after"},
                    "options": {},
                }
            ],
        },
    }


def preview_and_confirm_undo_group(*, tmp_path: Path, state_dir: Path) -> dict[str, Any]:
    transaction = preview(
        undo_group_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    return transaction


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
        version=str(request.get("version", "2022.1")),
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


def preview_and_confirm_public_call(
    request: Mapping[str, Any],
    *,
    tmp_path: Path,
    state_dir: Path,
) -> dict[str, Any]:
    version = str(request["version"])
    year = int(version.split(".", 1)[0])
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=year)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    return transaction


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
        "cleanup": payload["cleanup"],
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
        "cleanup": payload["cleanup"],
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
        "cleanup": verified["cleanup"],
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


def test_generic_manifest_call_runs_full_preview_confirm_execute_verify_chain(tmp_path: Path) -> None:
    state_dir = tmp_path / "generic-state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    transaction = preview(
        generic_manifest_call_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    assert transaction["preview_summary"]["dispatch"] == {
        "uri": "ak.wwise.core.project.save",
        "args": {},
        "options": {},
    }
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.project.save": [{}],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [call[0] for call in execute_client.calls].count("ak.wwise.core.project.save") == 1

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["verified"] is False
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verification_strength"] == "complete_reflected_schema"
    assert verify_payload["agent_result"]["result"] == {}
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == generic_manifest_call_request()


def test_lifecycle_opener_cleanup_spec_survives_the_full_gateway_chain(tmp_path: Path) -> None:
    state_dir = tmp_path / "load-bank-state"
    sound_bank = {"name": "Main", "ids": [1, 2]}
    request = generic_public_call_request(
        "ak.soundengine.loadBank",
        {"soundBank": sound_bank},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    preview_cleanup = transaction["cleanup"]

    assert transaction["preview_summary"]["cleanup"] == preview_cleanup
    assert transaction["agent_result"]["cleanup"] == preview_cleanup
    assert preview_cleanup["status"] == "not_started"
    assert preview_cleanup["projection"]["status"] == "not_started"
    assert preview_cleanup["spec"]["companion_request"] == {
        "api": "ak.soundengine.unloadBank",
        "args": {"soundBank": sound_bank},
        "options": {},
    }

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.soundengine.loadBank": [{}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "pending"
    assert execute_payload["cleanup"]["projection"]["status"] == "pending"

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["cleanup"]["status"] == "pending"
    assert verify_payload["cleanup"]["projection"]["status"] == "pending"
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]

    cleanup_payloads = (
        preview_cleanup,
        transaction["preview_summary"]["cleanup"],
        transaction["agent_result"]["cleanup"],
        execute_payload["cleanup"],
        verify_payload["cleanup"],
        verify_payload["agent_result"]["cleanup"],
    )
    expected_spec = preview_cleanup["spec"]
    expected_digest = expected_spec["spec_sha256"]
    assert len(expected_digest) == 64
    assert all(cleanup["spec"] == expected_spec for cleanup in cleanup_payloads)
    assert all(
        cleanup["projection"]["cleanup_spec_sha256"] == expected_digest
        for cleanup in cleanup_payloads
    )
    stored_spec = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact["prepared_operation"]["cleanup"]
    assert stored_spec == expected_spec


def test_load_bank_cleanup_binding_cannot_be_overridden_by_execution_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "load-bank-result-override-state"
    confirmed_sound_bank = {"name": "Confirmed", "ids": [7, 8]}
    request = generic_public_call_request(
        "ak.soundengine.loadBank",
        {"soundBank": confirmed_sound_bank},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    real_dispatch = waapi_gateway.dispatch

    def injected_dispatch(
        dispatcher: Any,
        api: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if api == "ak.soundengine.loadBank":
            return {
                "ok": True,
                "api": api,
                "version": "2025.1",
                "result": {
                    "soundBank": {"name": "Injected", "ids": [99]},
                    "transport": 73,
                },
                "error_code": None,
                "message": "program-injected result",
            }
        return real_dispatch(dispatcher, api, **kwargs)

    monkeypatch.setattr(waapi_gateway, "dispatch", injected_dispatch)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=execute_client,
    )

    assert execute_exit == 0, execute_payload
    assert execute_payload["dispatch_result"]["result"]["soundBank"]["name"] == "Injected"
    assert execute_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.soundengine.unloadBank",
        "args": {"soundBank": confirmed_sound_bank},
        "options": {},
    }
    assert execute_payload["cleanup"]["spec"]["companion_request"]["args"] == {
        "soundBank": confirmed_sound_bank
    }
    assert not any(call[0] == "ak.soundengine.loadBank" for call in execute_client.calls)
    stored_spec = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact["prepared_operation"]["cleanup"]
    assert stored_spec == transaction["cleanup"]["spec"]
    assert stored_spec["companion_request"]["args"] == {"soundBank": confirmed_sound_bank}


def test_transport_create_materializes_destroy_request_in_execute_verify_and_agent_result(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-state"
    transport_id = 73
    request = generic_public_call_request(
        "ak.wwise.core.transport.create",
        {"object": OBJECT_GUID},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    immutable_spec = transaction["cleanup"]["spec"]

    assert transaction["cleanup"]["status"] == "not_started"
    assert immutable_spec["binding"]["materialized"] is False
    assert transaction["cleanup"]["projection"]["companion_request"]["args"] == {}

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.transport.create": [{"transport": transport_id}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "pending"
    assert execute_payload["cleanup"]["spec"] == immutable_spec
    assert execute_payload["cleanup"]["spec"]["binding"]["materialized"] is False
    assert execute_payload["cleanup"]["projection"]["binding"]["materialized"] is True
    assert execute_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.wwise.core.transport.destroy",
        "args": {"transport": transport_id},
        "options": {},
    }

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.transport.getList": [
                {"list": [{"transport": transport_id, "object": OBJECT_GUID, "gameObject": 1}]}
            ],
            "ak.wwise.core.transport.getState": [{"state": "stopped"}],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=verify_client,
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["cleanup"]["spec"] == immutable_spec
    assert verify_payload["cleanup"]["projection"]["companion_request"]["args"] == {
        "transport": transport_id
    }
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]
    assert verify_payload["agent_result"]["cleanup"]["projection"]["binding"]["materialized"] is True
    assert (
        verify_payload["cleanup"]["projection"]["cleanup_spec_sha256"]
        == immutable_spec["spec_sha256"]
    )
    assert (
        TransactionStore(state_dir)
        .load_preview(transaction["transaction_id"])
        .artifact["prepared_operation"]["cleanup"]
        == immutable_spec
    )
    assert (
        "ak.wwise.core.transport.getState",
        {"transport": transport_id},
        {},
    ) in verify_client.calls


def test_transport_verify_guard_failure_keeps_result_bound_destroy_request(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-guard-failure-state"
    transport_id = 73
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.create",
            {"object": OBJECT_GUID},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.transport.create": [{"transport": transport_id}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [
                    project(
                        project_id="{99999999-9999-9999-9999-999999999999}",
                        name="DifferentProject",
                        path=r"Y:\other\DifferentProject.wproj",
                    )
                ],
            }
        ),
    )

    assert verify_exit == 2
    assert verify_payload["status"] == "verification_deferred"
    assert verify_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert verify_payload["automatic_retry"] is False
    assert verify_payload["manual_verification_retry_allowed"] is True
    assert verify_payload["cleanup"]["status"] == "pending"
    assert verify_payload["cleanup"]["projection"]["binding"]["materialized"] is True
    assert verify_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.wwise.core.transport.destroy",
        "args": {"transport": transport_id},
        "options": {},
    }


def test_successful_mutation_with_journal_failure_keeps_execution_and_cleanup_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "post-success-journal-failure-state"
    transport_id = 73
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.create",
            {"object": OBJECT_GUID},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    def fail_after_waapi_success(
        _store: TransactionStore,
        _transaction_id: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> Any:
        assert details is not None
        assert details["dispatch_result"]["result"] == {"transport": transport_id}
        raise OSError("disk full after WAAPI success")

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "mark_executed_unverified",
        fail_after_waapi_success,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.transport.create": [{"transport": transport_id}],
        }
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=execute_client,
    )

    assert execute_exit == 2
    assert execute_payload["ok"] is False
    assert execute_payload["status"] == "execution_succeeded_persistence_failed"
    assert execute_payload["error_code"] == "TRANSACTION_PERSISTENCE_FAILED"
    assert execute_payload["state"] == TransactionState.EXECUTING.value
    assert execute_payload["executed"] is True
    assert execute_payload["verified"] is False
    assert execute_payload["automatic_retry"] is False
    assert execute_payload["dispatch_result"]["result"] == {"transport": transport_id}
    assert execute_payload["details"]["attempted_transition"] == (
        TransactionState.EXECUTED_UNVERIFIED.value
    )
    assert execute_payload["details"]["observed_durable_state"] == (
        TransactionState.EXECUTING.value
    )
    assert execute_payload["cleanup"]["status"] == "pending"
    assert execute_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.wwise.core.transport.destroy",
        "args": {"transport": transport_id},
        "options": {},
    }
    assert [call[0] for call in execute_client.calls].count(
        "ak.wwise.core.transport.create"
    ) == 1
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is (
        TransactionState.EXECUTING
    )


def test_transaction_readback_rejects_an_unreviewed_uri_before_dispatch(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.project.save": [{}]})
    dispatcher = waapi_gateway.WwiseDispatcher(client=client)
    connection = waapi_gateway.GatewayConnection(
        host="127.0.0.1",
        port=31337,
        version_hint="2025.1",
        evidence_dir=tmp_path / "evidence",
        timeout=10.0,
        deadline=waapi_gateway.GatewayDeadline.start(10.0),
    )
    read_call = waapi_gateway.transaction_read_call(
        dispatcher,
        connection=connection,
        version="2025.1",
    )

    with pytest.raises(waapi_gateway.OperationContractError) as caught:
        read_call("ak.wwise.core.project.save", {}, {})

    assert caught.value.error_code == "UNREVIEWED_READBACK_URI"
    assert caught.value.details == {"uri": "ak.wwise.core.project.save"}
    assert client.calls == []


def test_lifecycle_opener_execution_exception_reports_unknown_cleanup(tmp_path: Path) -> None:
    state_dir = tmp_path / "indeterminate-cleanup-state"
    request = generic_public_call_request(
        "ak.soundengine.loadBank",
        {"soundBank": "Main"},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.soundengine.loadBank": [],
            },
            errors={
                "ak.soundengine.loadBank": [RuntimeError("connection lost after dispatch")]
            },
        ),
    )

    assert execute_exit == 2
    assert execute_payload["state"] == TransactionState.INDETERMINATE.value
    assert execute_payload["cleanup"]["status"] == "unknown"
    assert execute_payload["cleanup"]["projection"]["phase"] == "indeterminate"
    assert execute_payload["cleanup"]["projection"]["status"] == "unknown"
    assert execute_payload["cleanup"]["spec"] == transaction["cleanup"]["spec"]
    assert "agent_result" not in execute_payload


def test_work_unit_load_is_available_reversal_through_the_full_gateway_chain(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "work-unit-load-state"
    request = generic_public_call_request(
        "ak.wwise.core.workUnit.load",
        {"object": OBJECT_GUID},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert transaction["cleanup"]["status"] == "available_reversal"
    assert transaction["cleanup"]["spec"]["cleanup_requirement"] == "available_reversal"
    assert transaction["cleanup"]["spec"]["lifecycle_strategy"] == "reversible_state_change"
    assert transaction["agent_result"]["cleanup"] == transaction["cleanup"]

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.workUnit.load": [{}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "available_reversal"
    assert execute_payload["cleanup"]["status"] not in {"pending", "required"}

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["cleanup"]["status"] == "available_reversal"
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]


def test_lifecycle_closer_is_not_reported_as_needing_more_cleanup(tmp_path: Path) -> None:
    state_dir = tmp_path / "unload-bank-state"
    request = generic_public_call_request(
        "ak.soundengine.unloadBank",
        {"soundBank": "Main"},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert transaction["cleanup"]["status"] == "not_required"
    assert transaction["cleanup"]["spec"]["lifecycle_action"] == "closer"
    assert transaction["cleanup"]["spec"]["companion_request"] is None

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.soundengine.unloadBank": [{}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "not_required"

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["cleanup"]["status"] == "not_required"
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]


def test_generic_isolated_call_runs_full_chain_with_bound_io_audit(tmp_path: Path) -> None:
    state_dir = tmp_path / "isolated-state"
    io_root = (tmp_path / "io-sandbox").resolve()
    request = generic_isolated_call_request(io_root)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    io_audit = transaction["preview_summary"]["pre_state"]["execution_contract"]["io_audit"]
    assert io_audit["io_root"] == str(io_root)
    assert io_audit["explicit_write_confinement_proven"] is True
    assert io_audit["paths"][0]["resolved_path"] == str((io_root / "tone.wav").resolve())
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.debug.generateToneWAV": [{}],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )
    assert execute_exit == 0, execute_payload
    assert [call[0] for call in execute_client.calls].count("ak.wwise.debug.generateToneWAV") == 1

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        version="2023.1",
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["verified"] is False
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verification_strength"] == "complete_reflected_schema"
    assert verify_payload["agent_result"]["result"] == {}
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == request


@pytest.mark.parametrize(
    ("version", "api", "guard_mode"),
    PROJECT_TRANSITION_ROWS,
    ids=lambda value: str(value),
)
def test_every_project_transition_row_runs_one_complete_program_chain(
    tmp_path: Path,
    version: str,
    api: str,
    guard_mode: str,
) -> None:
    year = int(version.split(".", 1)[0])
    state_dir = tmp_path / "state"
    io_root = (tmp_path / "io-root").resolve()
    target_path = io_root / "TargetProject.wproj"
    current_path = (tmp_path / "current-project" / "CurrentProject.wproj").resolve()
    contract = ExecutionContractRegistry().describe(version, api)
    call_args: dict[str, Any] = {}
    arguments: dict[str, Any] = {"api": api, "args": call_args, "options": {}}
    if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH:
        call_args["path"] = str(target_path)
    if contract.route == "isolated_transaction":
        arguments["io_root"] = str(io_root)
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": arguments,
    }
    before_rows = (
        []
        if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH
        else [
            {
                **project(path=str(current_path)),
                "type": "Project",
            }
        ]
    )
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.object.get": [{"return": before_rows}],
        }
    )
    transaction = preview(request, tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    stored_guard = TransactionStore(state_dir).load_preview(transaction["transaction_id"]).artifact[
        "project_guard"
    ]
    assert stored_guard["project_guard_mode"] == guard_mode
    assert stored_guard["project"]["state"] == ("none" if not before_rows else "open")
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    result = {"hadProjectOpen": True} if api.endswith(".close") else {}
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.object.get": [{"return": before_rows}],
            api: [result],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version=version,
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [call[0] for call in execute_client.calls].count(api) == 1

    after_rows = (
        [
            {
                **project(name="TargetProject", path=str(target_path)),
                "type": "Project",
            }
        ]
        if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH
        else []
    )
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.object.get": [{"return": after_rows}],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        version=version,
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["verified"] is True
    assert verify_payload["result_schema_checked"] is False
    assert verify_payload["verification"]["business_state_verified"] is True
    assert verify_payload["verification"]["readbacks"][-1]["kind"] == "project-transition-observation"
    assert verify_payload["guard_validation"]["project_transition"]["matched"] is True
    assert verify_payload["agent_result"]["verified"] is True


def test_project_transition_mismatch_stays_executed_unverified_for_manual_verify(
    tmp_path: Path,
) -> None:
    version = "2022.1"
    api = "ak.wwise.ui.project.open"
    state_dir = tmp_path / "state"
    io_root = (tmp_path / "io-root").resolve()
    target_path = io_root / "TargetProject.wproj"
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {"path": str(target_path)},
            "options": {},
            "io_root": str(io_root),
        },
    }
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.object.get": [{"return": []}],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_exit, _ = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.object.get": [{"return": []}],
                api: [{}],
            }
        ),
        version=version,
    )
    assert execute_exit == 0

    wrong_path = (io_root / "OtherProject.wproj").resolve()
    verify_exit, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            {
                                **project(name="OtherProject", path=str(wrong_path)),
                                "type": "Project",
                            }
                        ]
                    }
                ],
            }
        ),
        version=version,
    )
    assert verify_exit == 2
    assert payload["status"] == "verification_deferred"
    assert payload["error_code"] == "PROJECT_TRANSITION_MISMATCH"
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert "agent_result" not in payload


def test_undo_group_success_uses_one_client_and_verifies_only_result_schemas(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{}],
        }
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert execute_payload["same_connection"] is True
    assert execute_payload["compound_execution"] == {
        "status": "completed",
        "same_connection": True,
        "automatic_retry": False,
        "phase_count": 3,
        "authoritative_phases": "dispatch_result.result.phases",
    }
    assert json.dumps(execute_payload, ensure_ascii=False).count('"phases"') == 1
    compound_calls = [
        call
        for call in execute_client.calls
        if call[0].startswith("ak.wwise.core.undo.")
        or call[0] == "ak.wwise.core.object.setNotes"
    ]
    assert compound_calls == [
        ("ak.wwise.core.undo.beginGroup", {}, {}),
        (
            "ak.wwise.core.object.setNotes",
            {"object": OBJECT_GUID, "value": "after"},
            {},
        ),
        ("ak.wwise.core.undo.endGroup", {"displayName": "Program Undo Group"}, {}),
    ]
    assert len({execute_client.call_thread_idents[execute_client.calls.index(call)] for call in compound_calls}) == 1

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
        version="2023.1",
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["verified"] is False
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verification"]["business_state_verified"] is False
    assert verify_payload["agent_result"]["verified"] is False


def test_undo_group_success_keeps_one_phase_copy_below_the_final_gateway_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)

    class AcceptedResultValidation:
        unresolved_refs: tuple[str, ...] = ()

        def as_dict(self) -> dict[str, Any]:
            return {"section": "result", "unresolved_refs": []}

    monkeypatch.setattr(
        waapi_gateway,
        "validate_semantic_result",
        lambda *args, **kwargs: AcceptedResultValidation(),
    )
    # This ceiling is deliberately below the old three-copy response size but
    # comfortably above the new single authoritative phase document.
    monkeypatch.setattr(waapi_gateway, "MAX_GATEWAY_RESULT_JSON_BYTES", 250 * 1024)
    large_inner_result = {"program_payload": "x" * 100_000}
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [large_inner_result],
            "ak.wwise.core.undo.endGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 0, payload
    assert payload["status"] == "executed_unverified"
    assert payload.get("error_code") != "RESULT_TOO_LARGE"
    assert payload["dispatch_result"]["result"]["phases"][1]["dispatch_result"]["result"] == (
        large_inner_result
    )
    assert "phases" not in payload["compound_execution"]
    assert "dispatch_result" not in payload["compound_execution"]
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    assert len(encoded) < waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES
    assert encoded.count(b'"phases"') == 1


def test_undo_group_success_with_journal_failure_is_not_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "undo-post-success-journal-failure-state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)

    def fail_after_same_connection_success(
        _store: TransactionStore,
        _transaction_id: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> Any:
        assert details is not None
        assert details["dispatch_result"]["result"]["same_connection"] is True
        raise OSError("disk full after same-connection success")

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "mark_executed_unverified",
        fail_after_same_connection_success,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["status"] == "execution_succeeded_persistence_failed"
    assert payload["error_code"] == "TRANSACTION_PERSISTENCE_FAILED"
    assert payload["state"] == TransactionState.EXECUTING.value
    assert payload["executed"] is True
    assert payload["automatic_retry"] is False
    assert payload["same_connection"] is True
    assert payload["compound_execution"]["authoritative_phases"] == (
        "dispatch_result.result.phases"
    )
    assert json.dumps(payload, ensure_ascii=False).count('"phases"') == 1
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.endGroup",
    ]


def test_undo_group_inner_timeout_reserves_budget_cancels_and_never_retries(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        },
        errors={"ak.wwise.core.object.setNotes": [TimeoutError("program timeout")]},
    )

    execute_exit, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert execute_exit == 2
    assert payload["state"] == TransactionState.EXECUTION_CANCELLED.value
    assert payload["rollback_verified"] is False
    assert payload["automatic_retry"] is False
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert execute_client.calls[-1][1] == {"undo": True}
    inner_phase = payload["compound_execution"]["failed_phase"]
    assert inner_phase["dispatch_result"]["error_code"] == "TIMEOUT"
    assert inner_phase["cancel_reserve_seconds"] >= 2.0

    retry_client = FakeClient({"ak.wwise.core.getInfo": [live_info(year=2023)]})
    retry_exit, retry_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=retry_client,
        version="2023.1",
    )
    assert retry_exit == 2
    assert retry_payload["error_code"] == "InvalidTransition"
    assert [call[0] for call in retry_client.calls] == ["ak.wwise.core.getInfo"]


def test_undo_group_cancel_failure_is_terminal_indeterminate(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
        },
        errors={
            "ak.wwise.core.object.setNotes": [RuntimeError("inner failed")],
            "ak.wwise.core.undo.cancelGroup": [RuntimeError("cancel failed")],
        },
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["automatic_retry"] is False
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert "ak.wwise.core.undo.endGroup" not in [call[0] for call in execute_client.calls]


def test_undo_group_malformed_begin_result_best_effort_cancels_but_stays_indeterminate(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{"unexpected": True}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["compound_execution"]["cancel_succeeded"] is True
    assert [call[0] for call in execute_client.calls][-2:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert "ak.wwise.core.object.setNotes" not in [call[0] for call in execute_client.calls]


def test_undo_group_malformed_end_result_best_effort_cancels_but_stays_indeterminate(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{"unexpected": True}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["compound_execution"]["cancel_succeeded"] is True
    assert [call[0] for call in execute_client.calls][-4:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.endGroup",
        "ak.wwise.core.undo.cancelGroup",
    ]


@pytest.mark.parametrize(
    "failing_uri",
    [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.endGroup",
    ],
)
def test_undo_group_phase_exception_best_effort_cancels_and_remains_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_uri: str,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )
    original_dispatch = waapi_gateway.dispatch
    raised = False

    def dispatch_then_raise(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal raised
        result = original_dispatch(*args, **kwargs)
        api = args[1] if len(args) > 1 else kwargs.get("api")
        if api == failing_uri and not raised:
            raised = True
            raise RuntimeError("program post-dispatch exception")
        return result

    monkeypatch.setattr(waapi_gateway, "dispatch", dispatch_then_raise)
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["automatic_retry"] is False
    assert payload["compound_execution"]["cancel_succeeded"] is True
    assert [call[0] for call in execute_client.calls][-1] == "ak.wwise.core.undo.cancelGroup"


def test_undo_group_accumulated_result_limit_stops_inner_and_attempts_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    monkeypatch.setattr(waapi_gateway, "UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES", 8 * 1024)

    class AcceptedResultValidation:
        unresolved_refs: tuple[str, ...] = ()

        def as_dict(self) -> dict[str, Any]:
            return {"section": "result", "unresolved_refs": []}

    monkeypatch.setattr(
        waapi_gateway,
        "validate_semantic_result",
        lambda *args, **kwargs: AcceptedResultValidation(),
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{"program_payload": "x" * 32_000}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.EXECUTION_CANCELLED.value
    assert payload["status"] == "execution_cancelled"
    assert payload.get("error_code") != "RESULT_TOO_LARGE"
    assert payload["compound_execution"]["failed_phase"]["failure"]["kind"] == (
        "compound_result_limit_exceeded"
    )
    assert payload["compound_execution"]["cancel_phase"]["dispatch_result"]["ok"] is True
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert "ak.wwise.core.undo.endGroup" not in [call[0] for call in execute_client.calls]

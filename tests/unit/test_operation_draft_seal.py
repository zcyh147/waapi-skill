from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    OperationDraftSealReplayMismatch,
    OperationDraftState,
    OperationDraftStore,
)
from wwise_waapi.transactions import (  # pyright: ignore[reportMissingImports]
    TransactionStore,
    new_transaction_id,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_operation_draft_seal_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


OBJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
PARENT_GUID = "{22222222-2222-2222-2222-222222222222}"
PROJECT_GUID = "{33333333-3333-3333-3333-333333333333}"
EXPECTED_REQUEST = {
    "contract": "waapi-skill.operation-request/v1",
    "version": "2022.1",
    "operation": "object.set",
    "arguments": {
        "objects": [
            {
                "object": {"kind": "id", "value": OBJECT_GUID},
                "properties": [{"name": "Volume", "value": -3}],
            }
        ]
    },
}


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(
                f"Unexpected or exhausted WAAPI call: {uri} {args!r} {options!r}"
            )
        return values.popleft()

    def disconnect(self) -> None:
        self.disconnected = True


def gateway_env(tmp_path: Path, *, policy: str = "ask_before_changes") -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": policy,
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": "2022.1",
    }


def live_info() -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "processId": 4242,
        "processPath": "/Applications/Wwise/WwiseConsole",
        "apiVersion": 1,
        "platform": "macosx",
        "configuration": "release",
        "version": {
            "year": 2022,
            "major": 1,
            "minor": 0,
            "build": 1,
            "displayName": "v2022.1.0",
        },
    }


def project_row() -> dict[str, Any]:
    return {
        "id": PROJECT_GUID,
        "name": "SampleProject",
        "path": "/project/SampleProject.wproj",
    }


def object_row(*, volume: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": OBJECT_GUID,
        "name": "Target",
        "type": "Sound",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
        "parent": {"id": PARENT_GUID},
        "notes": "before",
    }
    if volume is not None:
        row["Volume"] = volume
    return row


def expected_preview_calls() -> list[
    tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
]:
    identity_fields = ["id", "name", "type", "path", "parent", "notes"]
    return [
        ("ak.wwise.core.getInfo", None, None),
        ("ak.wwise.core.getProjectInfo", None, None),
        ("ak.wwise.core.object.getTypes", {}, {}),
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [OBJECT_GUID]}},
            {"return": identity_fields},
        ),
        (
            "ak.wwise.core.object.getPropertyInfo",
            {"property": "Volume", "object": OBJECT_GUID},
            {},
        ),
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [OBJECT_GUID]}},
            {"return": [*identity_fields, "Volume"]},
        ),
        (
            "ak.wwise.core.object.get",
            {
                "from": {"id": [OBJECT_GUID]},
                "transform": [{"select": ["children"]}],
            },
            {"return": identity_fields},
        ),
    ]


def preview_client(
    *,
    info: Mapping[str, Any] | None = None,
    project: Mapping[str, Any] | None = None,
    pre_state_volume: float = 0.0,
) -> FakeClient:
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info() if info is None else info],
            "ak.wwise.core.getProjectInfo": [
                project_row() if project is None else project
            ],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -96.3, "max": 12.0},
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {"return": [object_row(volume=pre_state_volume)]},
                {"return": []},
            ],
        }
    )


def offline_execute(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, Any]]:
    def fail_if_connected(url: str) -> None:
        raise AssertionError(f"Offline Draft command connected to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *arguments],
        env=gateway_env(tmp_path),
        client_factory=fail_if_connected,
    )


def apply_action(
    tmp_path: Path,
    draft_id: str,
    authority: str,
    revision: int,
    action: Mapping[str, Any],
) -> dict[str, Any]:
    code, payload = offline_execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--action-json",
        json.dumps(
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                **dict(action),
            }
        ),
    )
    assert code == 0, payload
    return payload


def checked_draft(tmp_path: Path) -> tuple[str, str]:
    _code, started = offline_execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    targeted = apply_action(
        tmp_path,
        draft_id,
        authority,
        1,
        {
            "action": "add_target",
            "selector": {"kind": "id", "value": OBJECT_GUID},
        },
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    apply_action(
        tmp_path,
        draft_id,
        authority,
        2,
        {
            "action": "set_property",
            "target_handle": handle,
            "name": "Volume",
            "value": -3,
        },
    )
    client = preview_client()
    code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, json.dumps(checked, indent=2)
    assert checked["draft"]["revision"] == 4
    return draft_id, authority


def seal_arguments(
    draft_id: str,
    authority: str,
    *,
    expected_revision: int = 4,
) -> list[str]:
    return [
        "--state-dir",
        "STATE_DIR_PLACEHOLDER",
        "preview-from-draft",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(expected_revision),
        "--apply",
        "--ttl",
        "300",
    ]


def seal_checked_draft(
    tmp_path: Path,
    draft_id: str,
    authority: str,
    *,
    client: FakeClient | None = None,
    policy: str = "ask_before_changes",
    expected_revision: int = 4,
    env: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any], FakeClient]:
    actual_client = preview_client() if client is None else client
    arguments = seal_arguments(
        draft_id,
        authority,
        expected_revision=expected_revision,
    )
    arguments[1] = str(tmp_path / "state")
    code, payload = waapi_gateway.execute_gateway(
        arguments,
        env=(gateway_env(tmp_path, policy=policy) if env is None else env),
        client_factory=lambda _url: actual_client,
    )
    return code, payload, actual_client


def draft_record_path(tmp_path: Path, draft_id: str) -> Path:
    return (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )


def test_preview_from_checked_draft_seals_one_canonical_transaction(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    client = preview_client()

    code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "4",
            "--apply",
            "--ttl",
            "300",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0
    assert previewed["ok"] is True
    assert previewed["command"] == "preview-from-draft"
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["change_requested"] is True
    assert previewed["executed"] is False
    assert previewed["verified"] is False
    assert previewed["agent_result"]["request"] == EXPECTED_REQUEST
    assert list(previewed)[-1] == "agent_result"
    assert client.calls == expected_preview_calls()
    assert all(call[0] != "ak.wwise.core.object.set" for call in client.calls)

    transaction_id = previewed["transaction_id"]
    transaction_store = TransactionStore(tmp_path / "state")
    stored_preview = transaction_store.load_preview(transaction_id)
    assert stored_preview.artifact["request"] == EXPECTED_REQUEST
    assert [event["event_type"] for event in transaction_store.read_events(transaction_id)] == [
        "preview_created",
        "confirmation_requested",
    ]

    inspect_code, inspected = offline_execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspect_code == 0
    assert inspected["draft"]["lifecycle_state"] == "sealed"
    assert inspected["draft"]["revision"] == 6
    assert inspected["draft"]["allowed_actions"] == []
    assert inspected["draft"]["seal"] == {
        "status": "sealed",
        "source_revision": 4,
        "transaction_id": transaction_id,
        "artifact_hash": previewed["artifact_hash"],
    }


def test_sealed_draft_replays_the_same_preview_without_another_transition(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    first_code, first, _client = seal_checked_draft(tmp_path, draft_id, authority)
    assert first_code == 0, first
    transaction_store = TransactionStore(tmp_path / "state")
    before_events = transaction_store.read_events(first["transaction_id"])

    replay_code, replay, replay_client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
    )

    assert replay_code == 0, json.dumps(replay, indent=2)
    assert replay["transaction_id"] == first["transaction_id"]
    assert replay["artifact_hash"] == first["artifact_hash"]
    assert transaction_store.read_events(first["transaction_id"]) == before_events
    assert [call[0] for call in replay_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert list(replay)[-1] == "agent_result"


def test_sealed_draft_with_missing_transaction_fails_without_recreating_artifact(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    first_code, first, _client = seal_checked_draft(tmp_path, draft_id, authority)
    assert first_code == 0, first
    transaction_dir = (
        tmp_path / "state" / "transactions" / first["transaction_id"]
    )
    shutil.rmtree(transaction_dir)
    replay_client = preview_client()

    replay_code, replay, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
        client=replay_client,
    )

    assert replay_code == 2
    assert replay["error_code"] == "OPERATION_DRAFT_SEAL_REPLAY_MISMATCH"
    assert not transaction_dir.exists()
    assert [call[0] for call in replay_client.calls] == [
        "ak.wwise.core.getInfo",
    ]


@pytest.mark.parametrize(
    ("apply", "policy", "invalid_state"),
    (
        (False, "ask_before_changes", "policy_authorized"),
        (True, "ask_before_changes", "policy_authorized"),
        (False, "allow_changes", "policy_authorized"),
        (True, "allow_changes", "awaiting_confirmation"),
    ),
)
def test_seal_commit_authorization_state_is_bound_to_apply_and_policy(
    tmp_path: Path,
    apply: bool,
    policy: str,
    invalid_state: str,
) -> None:
    case_root = tmp_path / f"{apply}-{policy}"
    draft_id, authority = checked_draft(case_root)
    store = OperationDraftStore(case_root / "state")
    checked = store.inspect(draft_id, task_authority=authority)
    reservation = store.reserve_seal(
        draft_id,
        task_authority=authority,
        expected_revision=checked.revision,
        schema_digest=checked.schema_digest,
        composer_digest=str(checked.composer_digest),
        transaction_id=new_transaction_id(),
        apply=apply,
        ttl_seconds=300,
        policy=policy,
    )

    with pytest.raises(OperationDraftSealReplayMismatch):
        store.commit_seal(
            draft_id,
            task_authority=authority,
            source_revision=reservation.source_revision,
            transaction_id=reservation.transaction_id,
            artifact_hash="0" * 64,
            transaction_state=invalid_state,
        )

    unchanged = store.inspect(draft_id, task_authority=authority)
    assert unchanged.state is OperationDraftState.SEAL_RESERVED
    assert unchanged.revision == 5
    assert unchanged.seal is not None
    assert unchanged.seal["artifact_hash"] is None
    assert unchanged.seal["transaction_state"] is None


def test_crash_after_reservation_reuses_one_transaction_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    original_create = waapi_gateway.TransactionStore.create_preview

    def crash_before_transaction(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("crash after reservation")

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "create_preview",
        crash_before_transaction,
    )
    failed_code, failed, _client = seal_checked_draft(tmp_path, draft_id, authority)
    assert failed_code == 2
    assert failed["error_code"] == "RuntimeError"
    reserved = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert reserved.state is OperationDraftState.SEAL_RESERVED
    assert reserved.seal is not None
    transaction_id = reserved.seal["transaction_id"]
    assert not (tmp_path / "state" / "transactions" / transaction_id).exists()

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "create_preview",
        original_create,
    )
    retry_code, retry, _client = seal_checked_draft(tmp_path, draft_id, authority)

    assert retry_code == 0, json.dumps(retry, indent=2)
    assert retry["transaction_id"] == transaction_id
    assert len(TransactionStore(tmp_path / "state").read_events(transaction_id)) == 2


def test_crash_after_preview_create_recovers_draft_transaction_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    original_submit = waapi_gateway.TransactionStore.submit_for_confirmation

    def crash_before_authorization(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("crash after immutable Preview create")

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "submit_for_confirmation",
        crash_before_authorization,
    )
    failed_code, failed, _client = seal_checked_draft(tmp_path, draft_id, authority)
    assert failed_code == 2
    assert failed["error_code"] == "RuntimeError"
    reserved = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert reserved.state is OperationDraftState.SEAL_RESERVED
    assert reserved.seal is not None
    transaction_id = reserved.seal["transaction_id"]
    transaction_store = TransactionStore(tmp_path / "state")
    assert transaction_store.load(transaction_id).state.value == "draft"
    assert [event["event_type"] for event in transaction_store.read_events(transaction_id)] == [
        "preview_created"
    ]

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "submit_for_confirmation",
        original_submit,
    )
    retry_code, retry, _client = seal_checked_draft(tmp_path, draft_id, authority)

    assert retry_code == 0, json.dumps(retry, indent=2)
    assert retry["transaction_id"] == transaction_id
    assert [event["event_type"] for event in transaction_store.read_events(transaction_id)] == [
        "preview_created",
        "confirmation_requested",
    ]
    assert OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    ).state is OperationDraftState.SEALED


@pytest.mark.parametrize("drift", ("session", "project"))
def test_guard_drift_fails_before_reservation_or_transaction_store(
    tmp_path: Path,
    drift: str,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    record_path = draft_record_path(tmp_path, draft_id)
    before = record_path.read_bytes()
    changed_info = live_info()
    changed_project = project_row()
    if drift == "session":
        changed_info["sessionId"] = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
    else:
        changed_project["path"] = "/project/OtherProject.wproj"
    client = preview_client(info=changed_info, project=changed_project)

    code, payload, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_BINDING_DRIFT"
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


def test_prepared_prestate_drift_fails_before_reservation_or_transaction_store(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    record_path = draft_record_path(tmp_path, draft_id)
    before = record_path.read_bytes()
    client = preview_client(pre_state_volume=1.0)

    code, payload, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_BINDING_DRIFT"
    assert record_path.read_bytes() == before
    transactions_dir = tmp_path / "state" / "transactions"
    assert transactions_dir.is_dir()
    assert list(transactions_dir.iterdir()) == []
    assert all(call[0] != "ak.wwise.core.object.set" for call in client.calls)


@pytest.mark.parametrize(
    "binding_function",
    ("operation_request_schema_digest", "operation_composer_digest"),
)
def test_registry_or_composer_drift_is_byte_atomic_before_live_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_function: str,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    record_path = draft_record_path(tmp_path, draft_id)
    before = record_path.read_bytes()
    monkeypatch.setattr(
        waapi_gateway,
        binding_function,
        lambda *_args, **_kwargs: "0" * 64,
    )
    client = preview_client()

    code, payload, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_BINDING_DRIFT"
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize(
    ("authority", "revision", "error_code"),
    (
        ("da1-" + ("0" * 40), 4, "OPERATION_DRAFT_NOT_AVAILABLE"),
        (None, 3, "OPERATION_DRAFT_REVISION_CONFLICT"),
    ),
)
def test_wrong_task_or_revision_cannot_reserve_or_create_a_transaction(
    tmp_path: Path,
    authority: str | None,
    revision: int,
    error_code: str,
) -> None:
    draft_id, actual_authority = checked_draft(tmp_path)
    record_path = draft_record_path(tmp_path, draft_id)
    before = record_path.read_bytes()
    client = preview_client()

    code, payload, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        actual_authority if authority is None else authority,
        client=client,
        expected_revision=revision,
    )

    assert code == 2
    assert payload["error_code"] == error_code
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


def test_detected_version_drift_cannot_reserve_or_create_a_transaction(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    record_path = draft_record_path(tmp_path, draft_id)
    before = record_path.read_bytes()
    changed_info = live_info()
    changed_info["version"] = {
        "year": 2025,
        "major": 1,
        "minor": 0,
        "build": 1,
        "displayName": "v2025.1.0",
    }
    client = preview_client(info=changed_info)
    env = gateway_env(tmp_path)
    env.pop("WWISE_VERSION")

    code, payload, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
        client=client,
        env=env,
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_BINDING_DRIFT"
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


def test_crash_after_transaction_authorization_resumes_without_new_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    original_commit = waapi_gateway.OperationDraftStore.commit_seal

    def crash_before_draft_commit(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("crash before Draft commit")

    monkeypatch.setattr(
        waapi_gateway.OperationDraftStore,
        "commit_seal",
        crash_before_draft_commit,
    )
    failed_code, failed, _client = seal_checked_draft(tmp_path, draft_id, authority)
    assert failed_code == 2
    assert failed["error_code"] == "RuntimeError"
    reserved = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert reserved.state is OperationDraftState.SEAL_RESERVED
    assert reserved.seal is not None
    transaction_id = reserved.seal["transaction_id"]
    transaction_store = TransactionStore(tmp_path / "state")
    before_events = transaction_store.read_events(transaction_id)

    monkeypatch.setattr(
        waapi_gateway.OperationDraftStore,
        "commit_seal",
        original_commit,
    )
    retry_code, retry, retry_client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
    )

    assert retry_code == 0, retry
    assert retry["transaction_id"] == transaction_id
    assert transaction_store.read_events(transaction_id) == before_events
    assert [call[0] for call in retry_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


@pytest.mark.parametrize("mismatch", ("prepared", "runtime"))
def test_existing_same_id_mismatch_never_advances_draft_transaction(
    tmp_path: Path,
    mismatch: str,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    draft_store = OperationDraftStore(tmp_path / "state")
    checked = draft_store.inspect(draft_id, task_authority=authority)
    reservation = draft_store.reserve_seal(
        draft_id,
        task_authority=authority,
        expected_revision=checked.revision,
        schema_digest=checked.schema_digest,
        composer_digest=str(checked.composer_digest),
        transaction_id=new_transaction_id(),
        apply=True,
        ttl_seconds=300,
        policy="ask_before_changes",
    )
    artifact_client = preview_client()
    artifact = waapi_gateway.build_transaction_preview_artifact(
        EXPECTED_REQUEST,
        live_version="2022.1",
        read_call=lambda uri, args, options: artifact_client.call(uri, args, options),
        project_guard=reservation.project_guard,
        skill_root=waapi_gateway.SKILL_ROOT,
        ttl_seconds=300,
    ).as_dict()
    if mismatch == "prepared":
        artifact["prepared_operation"] = {
            **dict(artifact["prepared_operation"]),
            "collision_marker": True,
        }
    else:
        artifact["runtime_guard"] = {
            **dict(artifact["runtime_guard"]),
            "fingerprint": "0" * 64,
        }
    transaction_store = TransactionStore(tmp_path / "state")
    transaction_store.create_preview(reservation.transaction_id, artifact)
    before_events = transaction_store.read_events(reservation.transaction_id)
    before_draft = draft_record_path(tmp_path, draft_id).read_bytes()
    client = preview_client()

    code, payload, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_SEAL_REPLAY_MISMATCH"
    assert transaction_store.load(reservation.transaction_id).state.value == "draft"
    assert transaction_store.read_events(reservation.transaction_id) == before_events
    assert draft_record_path(tmp_path, draft_id).read_bytes() == before_draft


def test_crash_after_draft_commit_replays_the_sealed_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    original_dispatch = waapi_gateway.dispatch_operation_draft_preview

    def crash_after_commit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        original_dispatch(*args, **kwargs)
        raise RuntimeError("crash after durable Draft commit")

    monkeypatch.setattr(
        waapi_gateway,
        "dispatch_operation_draft_preview",
        crash_after_commit,
    )
    failed_code, failed, _client = seal_checked_draft(tmp_path, draft_id, authority)
    assert failed_code == 2
    assert failed["error_code"] == "RuntimeError"
    sealed = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert sealed.state is OperationDraftState.SEALED
    assert sealed.seal is not None
    transaction_id = sealed.seal["transaction_id"]
    transaction_store = TransactionStore(tmp_path / "state")
    before_events = transaction_store.read_events(transaction_id)

    monkeypatch.setattr(
        waapi_gateway,
        "dispatch_operation_draft_preview",
        original_dispatch,
    )
    retry_code, retry, _client = seal_checked_draft(tmp_path, draft_id, authority)

    assert retry_code == 0, json.dumps(retry, indent=2)
    assert retry["transaction_id"] == transaction_id
    assert transaction_store.read_events(transaction_id) == before_events


def test_concurrent_seal_reservations_choose_exactly_one_transaction_id(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    checked = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    candidate_ids = (new_transaction_id(), new_transaction_id())

    def reserve(transaction_id: str) -> Any:
        return OperationDraftStore(tmp_path / "state").reserve_seal(
            draft_id,
            task_authority=authority,
            expected_revision=checked.revision,
            schema_digest=checked.schema_digest,
            composer_digest=str(checked.composer_digest),
            transaction_id=transaction_id,
            apply=True,
            ttl_seconds=300,
            policy="ask_before_changes",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = tuple(executor.map(reserve, candidate_ids))

    assert len({item.transaction_id for item in reservations}) == 1
    assert sum(not item.replayed for item in reservations) == 1
    assert reservations[0].source_revision == reservations[1].source_revision == 4


def test_composer_seal_and_legacy_preview_produce_identical_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = waapi_gateway.build_transaction_preview_artifact
    fixed_now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    def deterministic_builder(*args: Any, **kwargs: Any) -> Any:
        kwargs["now"] = fixed_now
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        waapi_gateway,
        "build_transaction_preview_artifact",
        deterministic_builder,
    )
    composer_root = tmp_path / "composer"
    draft_id, authority = checked_draft(composer_root)
    composer_code, composer_payload, composer_client = seal_checked_draft(
        composer_root,
        draft_id,
        authority,
    )
    assert composer_code == 0, composer_payload
    composer_artifact = TransactionStore(composer_root / "state").load_preview(
        composer_payload["transaction_id"]
    ).artifact

    legacy_root = tmp_path / "legacy"
    legacy_client = preview_client()
    legacy_code, legacy_payload = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(legacy_root / "state"),
            "legacy-preview",
            "--request-json",
            json.dumps(EXPECTED_REQUEST),
            "--apply",
            "--ttl",
            "300",
        ],
        env=gateway_env(legacy_root),
        client_factory=lambda _url: legacy_client,
    )
    assert legacy_code == 0, legacy_payload
    legacy_artifact = TransactionStore(legacy_root / "state").load_preview(
        legacy_payload["transaction_id"]
    ).artifact

    assert composer_artifact == legacy_artifact
    assert composer_payload["artifact_hash"] == legacy_payload["artifact_hash"]
    assert composer_payload["preview_summary"] == legacy_payload["preview_summary"]
    assert {
        key: value
        for key, value in composer_payload["project_call"].items()
        if key != "timeout"
    } == {
        key: value
        for key, value in legacy_payload["project_call"].items()
        if key != "timeout"
    }
    assert composer_payload["authorization"] == legacy_payload["authorization"]
    assert composer_payload["cleanup"] == legacy_payload["cleanup"]
    assert composer_artifact["request"] == EXPECTED_REQUEST
    assert composer_artifact["prepared_operation"]["dispatch"] == {
        "uri": "ak.wwise.core.object.set",
        "args": {
            "objects": [
                {
                    "object": OBJECT_GUID,
                    "@Volume": -3,
                }
            ],
            "onNameConflict": "fail",
            "listMode": "append",
            "autoAddToSourceControl": False,
        },
        "options": {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "parent",
                "notes",
                "owner",
            ]
        },
    }
    assert composer_client.calls == legacy_client.calls
    assert composer_client.calls == expected_preview_calls()
    assert list(composer_payload)[-1] == list(legacy_payload)[-1] == "agent_result"

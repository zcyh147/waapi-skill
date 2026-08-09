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
    operation_draft_authority_digest,
    parse_operation_draft_archive_bytes,
)
from wwise_waapi.canonical import (  # pyright: ignore[reportMissingImports]
    canonical_json_bytes,
    canonical_sha256,
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


def gateway_env(
    tmp_path: Path,
    *,
    policy: str = "ask_before_changes",
    version: str = "2022.1",
) -> dict[str, str]:
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
        "WWISE_VERSION": version,
    }


def live_info(version: str = "2022.1") -> dict[str, Any]:
    year, major = (int(part) for part in version.split("."))
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
            "year": year,
            "major": major,
            "minor": 0,
            "build": 1,
            "displayName": f"v{version}.0",
        },
    }


WEATHER_ACTIONS = (
    ("Rain_Bed", 0.25, 0.0),
    ("Wind_Bed", 0.4, 0.1),
    ("Thunder_Near", 0.05, 0.0),
    ("Thunder_Mid", 0.12, 0.08),
    ("Thunder_Far", 0.25, 0.16),
)


def weather_request(version: str) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "direct-child",
                        "parent": {
                            "kind": "path",
                            "value": rf"\Events\Default Work Unit\Integration Weather\Play_{name}",
                        },
                        "type": "Action",
                    },
                    "properties": [
                        {"name": "FadeTime", "value": fade_time},
                        {"name": "Delay", "value": delay},
                    ],
                }
                for name, fade_time, delay in WEATHER_ACTIONS
            ],
            "on_name_conflict": "fail",
        },
    }


class WeatherClient:
    def __init__(self, version: str) -> None:
        self.version = version
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False
        self._events: dict[str, dict[str, Any]] = {}
        self._actions: dict[str, dict[str, Any]] = {}
        for index, (name, _fade_time, _delay) in enumerate(
            WEATHER_ACTIONS,
            start=1,
        ):
            event_path = rf"\Events\Default Work Unit\Integration Weather\Play_{name}"
            event_id = f"{{20000000-0000-0000-0000-{index:012d}}}"
            action_id = f"{{30000000-0000-0000-0000-{index:012d}}}"
            self._events[event_path] = {
                "id": event_id,
                "name": f"Play_{name}",
                "type": "Event",
                "path": event_path,
                "parent": {"id": PARENT_GUID},
                "notes": "",
            }
            self._actions[event_path] = {
                "id": action_id,
                "name": "Action",
                "type": "Action",
                "path": f"{event_path}\\Action",
                "parent": {"id": event_id},
                "notes": "",
                "FadeTime": 0.0,
                "Delay": 0.0,
            }

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        call_args = dict(args or {})
        if uri == "ak.wwise.core.getInfo":
            return live_info(self.version)
        if uri == "ak.wwise.core.getProjectInfo":
            return project_row()
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": 9, "name": "Action", "type": "Action"}]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            return {
                "name": call_args["property"],
                "type": "Real32",
                "restriction": {"type": "range", "min": 0.0, "max": 10.0},
            }
        if uri != "ak.wwise.core.object.get":
            raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")
        source = call_args.get("from")
        transform = call_args.get("transform")
        if isinstance(source, Mapping) and "path" in source:
            path = source["path"][0]
            return {"return": [dict(self._events[path])]}
        if "waql" in call_args:
            waql = str(call_args["waql"])
            for event_path, action in self._actions.items():
                if f'from object "{event_path}"' in waql:
                    return {"return": [dict(action)]}
            raise AssertionError(f"Unknown Weather WAQL: {waql}")
        if isinstance(source, Mapping) and "id" in source:
            object_id = source["id"][0]
            action = next(
                row for row in self._actions.values() if row["id"] == object_id
            )
            if transform:
                return {"return": []}
            return {"return": [dict(action)]}
        raise AssertionError(f"Unexpected object.get shape: {args!r} {options!r}")

    def disconnect(self) -> None:
        self.disconnected = True


WEAPONS_TARGETS = (
    (
        "{41000000-0000-0000-0000-000000000001}",
        "Rifle_Close_Old",
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle_Close_Old",
    ),
    (
        "{41000000-0000-0000-0000-000000000002}",
        "Rifle_Tail",
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle_Tail",
    ),
    (
        "{41000000-0000-0000-0000-000000000003}",
        "Rifle_Mechanical",
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle_Mechanical",
    ),
)
WEAPONS_BUS_ID = "{42000000-0000-0000-0000-000000000001}"
WEAPONS_BUS_PATH = r"\Master-Mixer Hierarchy\Default Work Unit\Weapons"


def weapons_request(version: str) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": WEAPONS_TARGETS[0][0]},
                    "name": "RFL_Close",
                    "notes": "release-ready | close",
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {"kind": "path", "value": WEAPONS_BUS_PATH},
                        }
                    ],
                },
                {
                    "object": {"kind": "id", "value": WEAPONS_TARGETS[1][0]},
                    "properties": [{"name": "Volume", "value": -3.0}],
                },
                {
                    "object": {"kind": "id", "value": WEAPONS_TARGETS[2][0]},
                    "notes": "release-ready | mechanical",
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {"kind": "path", "value": WEAPONS_BUS_PATH},
                        }
                    ],
                },
            ],
            "on_name_conflict": "fail",
        },
    }


class WeaponsClient:
    def __init__(self, version: str) -> None:
        self.version = version
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False
        self._targets = {
            object_id: {
                "id": object_id,
                "name": name,
                "type": "Sound",
                "path": path,
                "parent": {"id": PARENT_GUID},
                "notes": "before",
                "Volume": 0.0,
                "OverrideOutput": False,
                "OutputBus": {"id": "{master-bus}"},
            }
            for object_id, name, path in WEAPONS_TARGETS
        }
        self._bus = {
            "id": WEAPONS_BUS_ID,
            "name": "Weapons",
            "type": "Bus",
            "path": WEAPONS_BUS_PATH,
            "parent": {"id": "{master-work-unit}"},
            "notes": "",
        }

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        call_args = dict(args or {})
        if uri == "ak.wwise.core.getInfo":
            return live_info(self.version)
        if uri == "ak.wwise.core.getProjectInfo":
            return project_row()
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            token = call_args["property"]
            if token == "Volume":
                return {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -96.3, "max": 12.0},
                }
            if token == "OutputBus":
                return {
                    "name": "OutputBus",
                    "type": "Reference",
                    "supports": {"reference": True},
                    "dependencies": [
                        {
                            "type": "override",
                            "action": "Enable",
                            "context": "Self",
                            "property": "OverrideOutput",
                        }
                    ],
                }
            if token == "OverrideOutput":
                return {"name": "OverrideOutput", "type": "Boolean"}
            raise AssertionError(f"Unexpected property metadata token: {token}")
        if uri != "ak.wwise.core.object.get":
            raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")
        source = call_args.get("from")
        if isinstance(source, Mapping) and "path" in source:
            if source["path"] == [WEAPONS_BUS_PATH]:
                return {"return": [dict(self._bus)]}
            expected_renamed_path = str(WEAPONS_TARGETS[0][2]).rsplit("\\", 1)[0]
            expected_renamed_path += r"\RFL_Close"
            assert source["path"] == [expected_renamed_path]
            return {"return": []}
        if isinstance(source, Mapping) and "id" in source:
            object_id = source["id"][0]
            row = self._targets[object_id]
            if call_args.get("transform"):
                return {"return": []}
            return {"return": [dict(row)]}
        raise AssertionError(f"Unexpected object.get shape: {args!r} {options!r}")

    def disconnect(self) -> None:
        self.disconnected = True


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


def test_archive_parser_binds_authority_and_canonical_request_to_composition(
    tmp_path: Path,
) -> None:
    draft_id, authority = checked_draft(tmp_path)
    code, previewed, _client = seal_checked_draft(
        tmp_path,
        draft_id,
        authority,
    )
    assert code == 0, previewed
    record_path = draft_record_path(tmp_path, draft_id)

    parsed = parse_operation_draft_archive_bytes(
        record_path.read_bytes(),
        expected_draft_id=draft_id,
    )

    assert parsed.state is OperationDraftState.SEALED
    assert parsed.authority_digest == operation_draft_authority_digest(authority)
    assert parsed.seal is not None
    assert parsed.seal["request"] == EXPECTED_REQUEST

    tampered = json.loads(record_path.read_text(encoding="utf-8"))
    tampered_request = tampered["seal"]["request"]
    tampered_request["arguments"]["objects"][0]["properties"][0]["value"] = -2
    tampered_digest = canonical_sha256(tampered_request)
    tampered["seal"]["request_digest"] = tampered_digest
    tampered["check"]["request_digest"] = tampered_digest
    digest_material = dict(tampered)
    del digest_material["record_digest"]
    tampered["record_digest"] = canonical_sha256(
        {
            "contract": "waapi-skill.operation-draft-record-digest/v1",
            "record": digest_material,
        }
    )

    with pytest.raises(ValueError, match="canonical request.*composition"):
        parse_operation_draft_archive_bytes(
            canonical_json_bytes(tampered),
            expected_draft_id=draft_id,
        )


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


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_weather_batch_composer_matches_legacy_preview_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
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
    expected_request = weather_request(version)
    composer_root = tmp_path / "composer"
    _code, started = offline_execute(
        composer_root,
        "--version",
        version,
        "draft-start",
        "object.set",
    )
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1
    request_option = apply_action(
        composer_root,
        draft_id,
        authority,
        revision,
        {"action": "set_request_option", "name": "on_name_conflict", "value": "fail"},
    )
    revision = request_option["draft"]["revision"]
    for expected_row in expected_request["arguments"]["objects"]:
        targeted = apply_action(
            composer_root,
            draft_id,
            authority,
            revision,
            {"action": "add_target", "selector": expected_row["object"]},
        )
        revision = targeted["draft"]["revision"]
        target_handle = targeted["draft"]["current_facts"][-1]["handle"]
        for property_row in expected_row["properties"]:
            changed = apply_action(
                composer_root,
                draft_id,
                authority,
                revision,
                {
                    "action": "set_property",
                    "target_handle": target_handle,
                    "name": property_row["name"],
                    "value": property_row["value"],
                },
            )
            revision = changed["draft"]["revision"]

    check_client = WeatherClient(version)
    check_code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(composer_root / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
        ],
        env=gateway_env(composer_root, version=version),
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, checked
    checked_revision = checked["draft"]["revision"]
    composer_client = WeatherClient(version)
    composer_code, composer_payload = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(composer_root / "state"),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked_revision),
            "--apply",
            "--ttl",
            "300",
        ],
        env=gateway_env(composer_root, version=version),
        client_factory=lambda _url: composer_client,
    )
    assert composer_code == 0, composer_payload
    composer_artifact = TransactionStore(composer_root / "state").load_preview(
        composer_payload["transaction_id"]
    ).artifact

    legacy_root = tmp_path / "legacy"
    legacy_client = WeatherClient(version)
    legacy_code, legacy_payload = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(legacy_root / "state"),
            "legacy-preview",
            "--request-json",
            json.dumps(expected_request),
            "--apply",
            "--ttl",
            "300",
        ],
        env=gateway_env(legacy_root, version=version),
        client_factory=lambda _url: legacy_client,
    )
    assert legacy_code == 0, legacy_payload
    legacy_artifact = TransactionStore(legacy_root / "state").load_preview(
        legacy_payload["transaction_id"]
    ).artifact

    assert composer_artifact == legacy_artifact
    assert composer_artifact["request"] == expected_request
    assert composer_payload["artifact_hash"] == legacy_payload["artifact_hash"]
    assert composer_payload["preview_summary"] == legacy_payload["preview_summary"]
    assert composer_payload["authorization"] == legacy_payload["authorization"]
    assert composer_payload["cleanup"] == legacy_payload["cleanup"]
    assert composer_artifact["prepared_operation"]["dispatch"]["uri"] == (
        "ak.wwise.core.object.set"
    )
    assert composer_client.calls == legacy_client.calls
    assert check_client.disconnected is composer_client.disconnected is True
    assert legacy_client.disconnected is True
    assert list(composer_payload)[-1] == list(legacy_payload)[-1] == "agent_result"


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_weapons_mixed_batch_composer_matches_legacy_preview_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
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
    expected_request = weapons_request(version)
    composer_root = tmp_path / "composer"
    _code, started = offline_execute(
        composer_root,
        "--version",
        version,
        "draft-start",
        "object.set",
    )
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1
    configured = apply_action(
        composer_root,
        draft_id,
        authority,
        revision,
        {"action": "set_request_option", "name": "on_name_conflict", "value": "fail"},
    )
    revision = configured["draft"]["revision"]
    for expected_row in expected_request["arguments"]["objects"]:
        targeted = apply_action(
            composer_root,
            draft_id,
            authority,
            revision,
            {"action": "add_target", "selector": expected_row["object"]},
        )
        revision = targeted["draft"]["revision"]
        target_handle = targeted["draft"]["current_facts"][-1]["handle"]
        for field_name in ("name", "notes"):
            if field_name in expected_row:
                changed = apply_action(
                    composer_root,
                    draft_id,
                    authority,
                    revision,
                    {
                        "action": "set_target_field",
                        "target_handle": target_handle,
                        "name": field_name,
                        "value": expected_row[field_name],
                    },
                )
                revision = changed["draft"]["revision"]
        for property_row in expected_row.get("properties", []):
            changed = apply_action(
                composer_root,
                draft_id,
                authority,
                revision,
                {
                    "action": "set_property",
                    "target_handle": target_handle,
                    "name": property_row["name"],
                    "value": property_row["value"],
                },
            )
            revision = changed["draft"]["revision"]
        for reference_row in expected_row.get("references", []):
            changed = apply_action(
                composer_root,
                draft_id,
                authority,
                revision,
                {
                    "action": "set_reference",
                    "owner_handle": target_handle,
                    "name": reference_row["name"],
                    "target": reference_row["target"],
                },
            )
            revision = changed["draft"]["revision"]

    check_client = WeaponsClient(version)
    check_code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(composer_root / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
        ],
        env=gateway_env(composer_root, version=version),
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, json.dumps(
        {"result": checked, "calls": check_client.calls},
        indent=2,
        sort_keys=True,
    )
    checked_revision = checked["draft"]["revision"]
    composer_client = WeaponsClient(version)
    composer_code, composer_payload = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(composer_root / "state"),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked_revision),
            "--apply",
            "--ttl",
            "300",
        ],
        env=gateway_env(composer_root, version=version),
        client_factory=lambda _url: composer_client,
    )
    assert composer_code == 0, composer_payload
    composer_artifact = TransactionStore(composer_root / "state").load_preview(
        composer_payload["transaction_id"]
    ).artifact

    legacy_root = tmp_path / "legacy"
    legacy_client = WeaponsClient(version)
    legacy_code, legacy_payload = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(legacy_root / "state"),
            "legacy-preview",
            "--request-json",
            json.dumps(expected_request),
            "--apply",
            "--ttl",
            "300",
        ],
        env=gateway_env(legacy_root, version=version),
        client_factory=lambda _url: legacy_client,
    )
    assert legacy_code == 0, legacy_payload
    legacy_artifact = TransactionStore(legacy_root / "state").load_preview(
        legacy_payload["transaction_id"]
    ).artifact

    assert composer_artifact == legacy_artifact
    assert composer_artifact["request"] == expected_request
    assert composer_payload["artifact_hash"] == legacy_payload["artifact_hash"]
    assert composer_payload["preview_summary"] == legacy_payload["preview_summary"]
    assert composer_payload["authorization"] == legacy_payload["authorization"]
    assert composer_payload["cleanup"] == legacy_payload["cleanup"]
    dispatch = composer_artifact["prepared_operation"]["dispatch"]
    assert dispatch["uri"] == "ak.wwise.core.object.set"
    assert dispatch["args"]["objects"][0]["@OutputBus"] == WEAPONS_BUS_ID
    assert dispatch["args"]["objects"][0]["@OverrideOutput"] is True
    assert dispatch["args"]["objects"][2]["@OutputBus"] == WEAPONS_BUS_ID
    assert composer_client.calls == legacy_client.calls
    assert check_client.disconnected is composer_client.disconnected is True
    assert legacy_client.disconnected is True
    assert list(composer_payload)[-1] == list(legacy_payload)[-1] == "agent_result"

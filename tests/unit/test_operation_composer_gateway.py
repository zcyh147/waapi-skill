from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    OperationDraftStore,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    LEGACY_JSON_INPUT_MODE,
    operation_input_mode,
)

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_operation_composer_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


TARGET_HANDLE_RE = re.compile(r"^odh1-[0-9a-f]{24}$")
TARGET_ID = "{01234567-89AB-CDEF-0123-456789ABCDEF}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
PROJECT_ID = "{22222222-2222-2222-2222-222222222222}"


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


def gateway_env(tmp_path: Path) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "ask_before_changes",
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


def execute(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, Any]]:
    def fail_if_connected(url: str) -> None:
        raise AssertionError(f"Offline Composer command connected to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *arguments],
        env=gateway_env(tmp_path),
        client_factory=fail_if_connected,
    )


def action(action_name: str, **fields: Any) -> str:
    return json.dumps(
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": action_name,
            **fields,
        }
    )


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
        "id": PROJECT_ID,
        "name": "SampleProject",
        "path": "/project/SampleProject.wproj",
    }


def target_row(*, volume: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": TARGET_ID,
        "name": "Target",
        "type": "Sound",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
        "parent": {"id": PARENT_ID},
        "notes": "before",
    }
    if volume is not None:
        row["Volume"] = volume
    return row


def check_client() -> FakeClient:
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project_row()],
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
                {"return": [target_row()]},
                {"return": [target_row(volume=0.0)]},
                {"return": []},
            ],
        }
    )


def complete_draft(tmp_path: Path, *, value: float = -3.0) -> tuple[str, str, str]:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    code, completed = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=value,
        ),
    )
    assert code == 0
    assert completed["draft"]["revision"] == 3
    return draft_id, authority, handle


def test_object_set_typed_actions_build_one_target_scalar_fact_offline(
    tmp_path: Path,
) -> None:
    start_code, started = execute(tmp_path, "draft-start", "object.set")
    assert start_code == 0
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    target_code, target = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action(
            "add_target",
            selector={"kind": "id", "value": TARGET_ID},
        ),
    )

    assert target_code == 0
    assert target["command"] == "draft-apply"
    assert target["offline"] is True
    target_fact = target["draft"]["current_facts"][0]
    handle = target_fact["handle"]
    assert TARGET_HANDLE_RE.fullmatch(handle)
    assert target["draft"]["revision"] == 2
    assert target_fact == {
        "handle": handle,
        "selector": {"kind": "id", "value": TARGET_ID},
        "properties": [],
    }
    assert target["draft"]["missing_fields"] == [
        f"targets[{handle}].properties"
    ]

    property_code, property_result = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-6.0,
        ),
    )

    assert property_code == 0
    assert property_result["draft"]["revision"] == 3
    assert property_result["draft"]["current_facts"] == [
        {
            "handle": handle,
            "selector": {"kind": "id", "value": TARGET_ID},
            "properties": [{"name": "Volume", "value": -6.0}],
        }
    ]
    assert property_result["draft"]["missing_fields"] == []
    assert property_result["draft"]["missing_fields_status"] == "complete"
    assert "check" in property_result["draft"]["allowed_actions"]
    assert not (tmp_path / "state" / "transactions").exists()


def test_property_correction_and_removal_are_ordered_typed_edits(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    _code, initial = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-6,
        ),
    )
    _code, corrected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-3,
        ),
    )
    assert initial["draft"]["revision"] == 3
    assert corrected["draft"]["revision"] == 4
    assert corrected["draft"]["current_facts"][0]["properties"] == [
        {"name": "Volume", "value": -3}
    ]

    _code, removed_property = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--action-json",
        action("remove_property", target_handle=handle, name="Volume"),
    )
    assert removed_property["draft"]["revision"] == 5
    assert removed_property["draft"]["current_facts"][0]["properties"] == []
    assert removed_property["draft"]["missing_fields"] == [
        f"targets[{handle}].properties"
    ]

    _code, removed_target = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "5",
        "--action-json",
        action("remove_target", target_handle=handle),
    )
    assert removed_target["draft"]["revision"] == 6
    assert removed_target["draft"]["current_facts"] == []
    assert removed_target["draft"]["allowed_actions"][0] == "add_target"


def test_invalid_action_is_byte_atomic_and_rejects_complete_request_injection(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    exit_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        json.dumps(
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                "action": "add_target",
                "selector": {"kind": "id", "value": TARGET_ID},
                "request": {
                    "contract": "waapi-skill.operation-request/v1",
                    "version": "2022.1",
                    "operation": "object.set",
                    "arguments": {"objects": []},
                },
            }
        ),
    )

    assert exit_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before
    _code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspected["draft"] == started["draft"]


def test_invalid_target_selectors_are_registry_rejected_without_any_revision(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    for selector in (
        {"kind": "id", "value": True},
        {"kind": "path", "value": 7},
        {"kind": "path", "value": "not-an-absolute-wwise-path"},
    ):
        exit_code, rejected = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--action-json",
            action("add_target", selector=selector),
        )
        assert exit_code == 2
        assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
        assert record_path.read_bytes() == before

    _code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspected["draft"] == started["draft"]


def test_public_facts_result_budget_rejects_before_durable_revision(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    revision = 2
    for property_name in ("NotesA", "NotesB"):
        code, payload = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(
                "set_property",
                target_handle=handle,
                name=property_name,
                value="x" * 30_000,
            ),
        )
        assert code == 0
        revision = payload["draft"]["revision"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    rejected_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="NotesC",
            value="y" * 30_000,
        ),
    )

    assert rejected_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_LIMIT_EXCEEDED"
    assert rejected["details"]["result_limit_bytes"] == 256 * 1024
    assert record_path.read_bytes() == before


def test_legacy_record_is_readable_but_composer_requires_recreate_without_write(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest=(
            "2b6d3903c5b3e11618c3eaf0a3d5a26aa0045db26750320f3a8ce8c7da004cee"
        ),
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    inspect_code, inspected = execute(
        tmp_path,
        "draft-inspect",
        started.draft_id,
        "--task-authority",
        started.task_authority,
    )
    apply_code, rejected = execute(
        tmp_path,
        "draft-apply",
        started.draft_id,
        "--task-authority",
        started.task_authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )

    assert inspect_code == 0
    assert inspected["draft"]["missing_fields_status"] == "no_operation_adapter"
    assert apply_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_RECREATE_REQUIRED"
    assert record_path.read_bytes() == before


def test_composer_is_exactly_isolated_from_shared_uri_operations(
    tmp_path: Path,
) -> None:
    assert operation_input_mode("object.set", "2022.1") == LEGACY_JSON_INPUT_MODE
    assert operation_input_mode("object.setRTPC", "2022.1") == LEGACY_JSON_INPUT_MODE
    _code, started = execute(tmp_path, "draft-start", "object.setRTPC")
    draft_id = started["draft"]["draft_id"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    exit_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )

    assert exit_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ADAPTER_UNAVAILABLE"
    assert record_path.read_bytes() == before


def test_live_check_is_bounded_durable_and_any_edit_invalidates_it(
    tmp_path: Path,
) -> None:
    draft_id, authority, handle = complete_draft(tmp_path)
    client = check_client()

    check_code, checked = waapi_gateway.execute_gateway(
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

    assert check_code == 0
    assert checked["command"] == "draft-check"
    assert checked["offline"] is False
    assert checked["draft"]["revision"] == 4
    assert checked["draft"]["check"]["status"] == "passed"
    assert checked["draft"]["check"]["source_revision"] == 3
    assert checked["draft"]["check"]["request_digest"]
    assert "preview-from-draft" in checked["draft"]["allowed_actions"]
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.get",
    ]
    assert client.disconnected is True
    assert not (tmp_path / "state" / "transactions").exists()

    edit_code, edited = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-2.0,
        ),
    )
    assert edit_code == 0
    assert edited["draft"]["revision"] == 5
    assert edited["draft"]["check"] is None
    assert "preview-from-draft" not in edited["draft"]["allowed_actions"]
    assert "check" in edited["draft"]["allowed_actions"]

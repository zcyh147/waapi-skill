from __future__ import annotations

import os
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for 2023.1 destructive sandbox tests",
        allow_module_level=True,
    )
if os.getenv("WWISE_VERSION") != "2023.1":
    pytest.skip("WWISE_VERSION=2023.1 is required for 2023.1 destructive sandbox tests", allow_module_level=True)

from wwise_waapi.destructive_2023_sandbox import (  # pyright: ignore[reportMissingImports]
    Destructive2023SandboxRuntime,
    DestructiveSandboxUnavailable,
    unique_2023_name,
)
from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]

ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-2023-test-parity" / "destructive"


@contextmanager
def _destructive_sandbox(*, track_generated_outputs: bool = False) -> Iterator[Destructive2023SandboxRuntime]:
    try:
        with Destructive2023SandboxRuntime(track_generated_outputs=track_generated_outputs) as runtime:
            yield runtime
    except DestructiveSandboxUnavailable as exc:
        skip_or_fail_unavailable(exc)


def _create_object(client: Any, parent: str, object_type: str, name: str) -> str:
    result = client.call(
        "ak.wwise.core.object.create",
        {"parent": parent, "type": object_type, "name": name, "onNameConflict": "fail"},
        options={},
    )
    assert isinstance(result, Mapping), f"object.create must return a mapping: {result!r}"
    object_id = result.get("id")
    assert isinstance(object_id, str) and object_id, f"object.create did not return an id: {result!r}"
    return object_id


def _read_one(client: Any, object_id: str) -> Mapping[str, Any]:
    rows = _read_rows(client, object_id)
    assert len(rows) == 1, f"expected one object for {object_id}, got {rows!r}"
    return rows[0]


def _read_rows(client: Any, object_id: str) -> list[Mapping[str, Any]]:
    result = client.call("ak.wwise.core.object.get", {"from": {"id": [object_id]}}, options={"return": READBACK_FIELDS})
    if result is None:
        return []
    assert isinstance(result, Mapping), f"object.get must return a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"object.get must return an array: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


SWITCH_PARENT = r"\Switches\Default Work Unit"
SWITCH_REFERENCE = "SwitchGroupOrStateGroup"


@pytest.mark.live
@pytest.mark.destructive
def test_2023_switchcontainer_assignment_add_get_remove_uses_copied_sandbox_fixture() -> None:
    with _destructive_sandbox() as runtime:
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)
        client = runtime.require_client()
        created_roots: list[str] = []
        switch_id: str | None = None
        target_id: str | None = None
        try:
            switch_container_id = _create_object(client, ACTOR_PARENT, "SwitchContainer", unique_2023_name("WAAPI_2023_SWITCH_", "container"))
            created_roots.append(switch_container_id)
            switch_group_id = _create_object(client, SWITCH_PARENT, "SwitchGroup", unique_2023_name("WAAPI_2023_SWITCH_", "group"))
            created_roots.append(switch_group_id)
            switch_id = _create_object(client, switch_group_id, "Switch", unique_2023_name("WAAPI_2023_SWITCH_", "state"))
            client.call(
                "ak.wwise.core.object.setReference",
                {"object": switch_container_id, "reference": SWITCH_REFERENCE, "value": switch_group_id},
                options={},
            )
            target_id = _create_object(client, switch_container_id, "Sound", unique_2023_name("WAAPI_2023_SWITCH_", "target"))

            assignments_before = _assignment_records(client, switch_container_id)
            client.call(
                "ak.wwise.core.switchContainer.addAssignment",
                {"child": target_id, "stateOrSwitch": switch_id},
                options={},
            )
            assignments_after_add = _assignment_records(client, switch_container_id)
            assert _contains_pair(assignments_after_add, target_id, switch_id), {
                "before": assignments_before,
                "after_add": assignments_after_add,
            }

            client.call(
                "ak.wwise.core.switchContainer.removeAssignment",
                {"child": target_id, "stateOrSwitch": switch_id},
                options={},
            )
            assignments_after_remove = _assignment_records(client, switch_container_id)
            assert not _contains_pair(assignments_after_remove, target_id, switch_id), assignments_after_remove

            _delete_if_present(client, target_id)
            read_after_delete = _read_rows(client, target_id)
            assert read_after_delete == []
            _write_destructive_evidence(
                "switchcontainer_assignment_add_get_remove_cleanup",
                [
                    "ak.wwise.core.switchContainer.addAssignment",
                    "ak.wwise.core.switchContainer.getAssignments",
                    "ak.wwise.core.switchContainer.removeAssignment",
                ],
                {
                    "switch_container_id": switch_container_id,
                    "switch_group_id": switch_group_id,
                    "switch_id": switch_id,
                    "target_id": target_id,
                    "assignments_before": assignments_before,
                    "assignments_after_add": assignments_after_add,
                    "assignments_after_remove": assignments_after_remove,
                    "read_after_target_delete": read_after_delete,
                    "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                    "sandbox_project": str(sandbox.sandbox_project),
                    "source_immutability_guard": "Destructive2023SandboxRuntime.assert_source_unchanged runs on exit",
                },
            )
            target_id = None
        finally:
            if target_id is not None:
                _remove_assignment_if_present(client, created_roots[0], target_id, switch_id or "")
                _delete_if_present(client, target_id)
            for object_id in reversed(created_roots):
                _delete_if_present(client, object_id)


def _assignment_records(client: Any, switch_container_id: str) -> list[dict[str, Any]]:
    result = client.call("ak.wwise.core.switchContainer.getAssignments", {"id": switch_container_id}, options={})
    assert isinstance(result, Mapping), f"getAssignments must return a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"getAssignments must return an array: {result!r}"
    records: list[dict[str, Any]] = []
    for row in rows:
        assert isinstance(row, Mapping), row
        record = dict(row)
        record["child"] = _object_arg_id(row.get("child"))
        record["stateOrSwitch"] = _object_arg_id(row.get("stateOrSwitch"))
        records.append(record)
    return records


def _contains_pair(rows: Sequence[Mapping[str, Any]], child_id: str, switch_id: str) -> bool:
    return any(row.get("child") == child_id and row.get("stateOrSwitch") == switch_id for row in rows)


def _object_arg_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        object_id = value.get("id")
        assert isinstance(object_id, str), value
        return object_id
    raise AssertionError(f"unexpected assignment object value: {value!r}")


def _remove_assignment_if_present(client: Any, container_id: str, child_id: str, switch_id: str) -> None:
    if not switch_id:
        return
    if _contains_pair(_assignment_records(client, container_id), child_id, switch_id):
        client.call(
            "ak.wwise.core.switchContainer.removeAssignment",
            {"child": child_id, "stateOrSwitch": switch_id},
            options={},
        )


def _write_destructive_evidence(case_id: str, uris: list[str], details: Mapping[str, Any]) -> None:
    path = EVIDENCE_ROOT / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "status": "passed",
                "uris": uris,
                "details": _json_safe(details),
                "cleanup": "assignment is removed and disposable objects are deleted before test exit",
                "source_project_mutation_allowed": False,
                "sandbox_required": True,
                "recorded_at_unix": int(time.time()),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

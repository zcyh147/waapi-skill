from __future__ import annotations

import os
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for 2023.1 destructive sandbox tests",
        allow_module_level=True,
    )
if os.getenv("WWISE_VERSION") != "2023.1":
    pytest.skip("WWISE_VERSION=2023.1 is required for 2023.1 destructive sandbox tests", allow_module_level=True)

from tests.destructive.support.destructive_2023_sandbox import (  # pyright: ignore[reportMissingImports]
    Destructive2023SandboxRuntime,
    DestructiveSandboxUnavailable,
    unique_2023_name,
)
from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]

ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-2023-test-parity" / "destructive"


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


@pytest.mark.live
@pytest.mark.destructive
def test_2023_object_create_set_delete_readbacks_against_per_test_sandbox() -> None:
    with _destructive_sandbox() as runtime:
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)

        client = runtime.require_client()
        object_id: str | None = None
        try:
            name = unique_2023_name("WAAPI_2023_MUTATION_", "actor")
            notes = f"2023.1 destructive sandbox notes {name}"
            object_id = _create_object(client, ACTOR_PARENT, "ActorMixer", name)
            created = _read_one(client, object_id)
            assert created["id"] == object_id
            assert created["name"] == name
            assert created["type"] == "ActorMixer"

            client.call(
                "ak.wwise.core.object.set",
                {"objects": [{"object": object_id, "notes": notes}]},
                options={"return": READBACK_FIELDS},
            )
            updated = _read_one(client, object_id)
            assert updated["notes"] == notes

            client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
            read_after_delete = _read_rows(client, object_id)
            assert read_after_delete == []
            _write_destructive_evidence(
                "object_create_set_delete_readback",
                [
                    "ak.wwise.core.object.create",
                    "ak.wwise.core.object.set",
                    "ak.wwise.core.object.delete",
                ],
                {
                    "created_name": name,
                    "created_id": object_id,
                    "notes_readback": updated["notes"],
                    "read_after_delete": read_after_delete,
                    "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                    "sandbox_project": str(sandbox.sandbox_project),
                    "source_immutability_guard": "Destructive2023SandboxRuntime.assert_source_unchanged runs on exit",
                },
            )
            object_id = None
        finally:
            if object_id is not None:
                _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_2023_undo_group_rolls_back_created_object_in_per_test_sandbox() -> None:
    with _destructive_sandbox() as runtime:
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)

        client = runtime.require_client()
        object_id: str | None = None
        group_open = False
        try:
            name = unique_2023_name("WAAPI_2023_UNDO_", "actor")
            client.call("ak.wwise.core.undo.beginGroup", {}, options={})
            group_open = True
            object_id = _create_object(client, ACTOR_PARENT, "ActorMixer", name)
            created = _read_one(client, object_id)
            assert created["id"] == object_id
            assert created["name"] == name

            client.call("ak.wwise.core.undo.endGroup", {"displayName": f"2023.1 {name}"}, options={})
            group_open = False
            assert _read_one(client, object_id)["name"] == name

            client.call("ak.wwise.core.undo.undo", {}, options={})
            read_after_undo = _read_rows(client, object_id)
            assert read_after_undo == []
            _write_destructive_evidence(
                "undo_group_create_then_undo_readback",
                [
                    "ak.wwise.core.undo.beginGroup",
                    "ak.wwise.core.undo.endGroup",
                    "ak.wwise.core.undo.undo",
                ],
                {
                    "created_name": name,
                    "created_id": object_id,
                    "read_after_undo": read_after_undo,
                    "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                    "sandbox_project": str(sandbox.sandbox_project),
                    "source_immutability_guard": "Destructive2023SandboxRuntime.assert_source_unchanged runs on exit",
                },
            )
            object_id = None
        finally:
            if group_open:
                try:
                    client.call("ak.wwise.core.undo.cancelGroup", {}, options={})
                except BaseException:
                    pass
            if object_id is not None:
                _delete_if_present(client, object_id)


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
                "cleanup": "objects are removed and read back absent before test exit",
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

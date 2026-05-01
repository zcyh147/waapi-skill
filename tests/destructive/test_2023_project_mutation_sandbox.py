from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

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

ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]


@contextmanager
def _destructive_sandbox(*, track_generated_outputs: bool = False) -> Iterator[Destructive2023SandboxRuntime]:
    try:
        with Destructive2023SandboxRuntime(track_generated_outputs=track_generated_outputs) as runtime:
            yield runtime
    except DestructiveSandboxUnavailable as exc:
        pytest.skip(str(exc))


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
            assert _read_rows(client, object_id) == []
            object_id = None
        finally:
            if object_id is not None:
                _delete_if_present(client, object_id)

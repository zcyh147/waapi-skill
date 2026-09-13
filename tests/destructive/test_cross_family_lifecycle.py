"""Small real-Gateway CRUD tracers outside the ordinary Sound object family.

These are Console sandbox tests, not Fresh Agent or music-playback acceptance.
All identities and effects are observed through the public Gateway. The shared
fixture owns source-integrity checks, evidence sealing, and sandbox disposal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object,
    _complete_business_draft,
    _complete_object_lifecycle_business_transaction,
    _created_object_id,
    _discover_business_type,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)


pytestmark = [pytest.mark.live, pytest.mark.destructive]


def _query_one(runtime: Any, *, object_id: str | None = None,
               segments: Sequence[str] = ()) -> Mapping[str, Any]:
    assert (object_id is None) != (not segments)
    selector = ["--exact-id", object_id] if object_id is not None else [
        item for segment in segments for item in ("--path-segment", segment)
    ]
    result = runtime.gateway(["query-object", *selector], live=True)
    assert result["count"] == 1, result
    assert len(result["objects"]) == 1, result
    return result["objects"][0]


def _new_draft(runtime: Any, *, parent_id: str, object_type: str,
               name: str) -> Any:
    draft = _start_business_draft(runtime, "object.create")
    parent = _bind_business_object(runtime, draft, object_id=parent_id)
    kind = _discover_business_type(
        runtime, draft, meaning=object_type, role="object",
        expected_label=object_type,
    )
    _update_business_draft(runtime, draft, "draft-declare-new", [
        "--declaration-id", "new-object", "--parent-handle", parent,
        "--kind", kind, "--name", name,
    ], live=False)
    return draft


def _create(runtime: Any, transactions: list[str], *,
            parent: Mapping[str, Any], object_type: str,
            name: str) -> Mapping[str, Any]:
    draft = _new_draft(
        runtime, parent_id=parent["id"], object_type=object_type, name=name,
    )
    completed = _complete_business_draft(runtime, draft)
    transactions.append(completed["verify"]["transaction_id"])
    row = _query_one(runtime, object_id=_created_object_id(completed["execute"]))
    assert row["type"] == object_type, row
    assert row["name"] == name, row
    assert row["path"] == parent["path"] + "\\" + name, row
    return row


def _change(runtime: Any, transactions: list[str], **kwargs: Any) -> Any:
    completed = _complete_object_lifecycle_business_transaction(runtime, **kwargs)
    transactions.append(completed["verify"]["transaction_id"])
    return completed


def _assert_missing(runtime: Any, object_id: str) -> None:
    result = runtime.gateway(["query-object", "--exact-id", object_id], live=True)
    assert result["count"] == 0, result
    assert result["objects"] == [], result


def _record(runtime: Any, category: str, transactions: list[str]) -> None:
    runtime.category_results.append({
        "category": "cross-family-" + category,
        "status": "PASS",
        "verifier_strength": "gateway_business_full_chain_and_exact_identity_readback",
        "transaction_ids": transactions,
    })


def test_cross_family_bus_auxbus_nested_create_rename_delete(
    workflow_sandbox_runtime: Any,
) -> None:
    runtime = workflow_sandbox_runtime
    transactions: list[str] = []
    suffix = uuid.uuid4().hex[:10]
    hierarchy = "Busses" if runtime.version == "2025.1" else "Master-Mixer Hierarchy"
    master_name = "Main Audio Bus" if runtime.version == "2025.1" else "Master Audio Bus"
    master = _query_one(runtime, segments=(hierarchy, "Default Work Unit", master_name))
    bus = _create(runtime, transactions, parent=master, object_type="Bus",
                  name="CrossFamilyBus_" + suffix)
    auxiliary = _create(runtime, transactions, parent=bus, object_type="AuxBus",
                        name="CrossFamilyAux_" + suffix)
    renamed = "CrossFamilyAuxRenamed_" + suffix
    _change(runtime, transactions, operation="object.setName",
            object_id=auxiliary["id"], new_name=renamed)
    after = _query_one(runtime, object_id=auxiliary["id"])
    assert after["type"] == "AuxBus" and after["name"] == renamed, after
    assert after["path"] == bus["path"] + "\\" + renamed, after
    _change(runtime, transactions, operation="object.delete", object_id=auxiliary["id"])
    _assert_missing(runtime, auxiliary["id"])
    assert _query_one(runtime, object_id=bus["id"]) == bus
    assert _query_one(runtime, object_id=master["id"]) == master
    _record(runtime, "bus-auxbus", transactions)


@pytest.mark.parametrize("hierarchy,group_type,child_type", [
    ("States", "StateGroup", "State"),
    ("Switches", "SwitchGroup", "Switch"),
])
def test_cross_family_group_child_versioned_move_boundary_and_rename(
    workflow_sandbox_runtime: Any, hierarchy: str, group_type: str, child_type: str,
) -> None:
    """Real probes: cross-group move succeeds in 2021/22, fails in 2023–25."""
    runtime = workflow_sandbox_runtime
    transactions: list[str] = []
    suffix = uuid.uuid4().hex[:10]
    root = _query_one(runtime, segments=(hierarchy, "Default Work Unit"))
    invalid = _start_business_draft(runtime, "object.create")
    parent = _bind_business_object(runtime, invalid, object_id=root["id"])
    kind = _discover_business_type(runtime, invalid, meaning=child_type,
                                  role="object", expected_label=child_type)
    exit_code, rejected = runtime.raw_gateway([
        "draft-declare-new", invalid.draft_id, "--task-authority", invalid.task_authority,
        "--expected-revision", str(invalid.revision),
        "--declaration-id", "invalid", "--parent-handle", parent,
        "--kind", kind, "--name", "MustNotExist_" + suffix,
    ])
    assert exit_code != 0 and rejected["ok"] is False, rejected
    assert rejected["error_code"] == "INVALID_CREATE_PARENT_TYPE_FOR_CHILD", rejected
    absent = runtime.gateway([
        "query-object", "--path-segment", hierarchy, "--path-segment", "Default Work Unit",
        "--path-segment", "MustNotExist_" + suffix,
    ], live=True)
    assert absent["count"] == 0 and absent["objects"] == [], absent

    source = _create(runtime, transactions, parent=root, object_type=group_type,
                     name="CrossFamilySource_" + suffix)
    destination = _create(runtime, transactions, parent=root, object_type=group_type,
                          name="CrossFamilyDestination_" + suffix)
    moved = _create(runtime, transactions, parent=source, object_type=child_type,
                    name="MovingChild")
    sibling = _create(runtime, transactions, parent=source, object_type=child_type,
                      name="PreservedChild")
    if runtime.version in {"2021.1", "2022.1"}:
        _change(runtime, transactions, operation="object.move", object_id=moved["id"],
                parent_id=destination["id"], name_conflict="fail")
        expected_parent = destination
        move_scope = "cross_group_move_executed_and_verified"
    else:
        blocked_move = _start_business_draft(runtime, "object.move")
        _bind_business_object(runtime, blocked_move, object_id=moved["id"], role="object")
        _bind_business_object(runtime, blocked_move, object_id=destination["id"], role="parent")
        _update_business_draft(runtime, blocked_move, "draft-declare-object-change",
                               ["--name-conflict", "fail"], live=False)
        code, boundary = runtime.raw_gateway([
            "draft-check", blocked_move.draft_id,
            "--task-authority", blocked_move.task_authority,
            "--expected-revision", str(blocked_move.revision),
        ])
        assert code == 2 and boundary["error_code"] == "GAME_SYNC_REPARENT_UNSUPPORTED", boundary
        assert not boundary.get("transaction_id"), boundary
        assert _query_one(runtime, object_id=moved["id"]) == moved
        expected_parent = source
        move_scope = "cross_group_move_rejected_before_preview_not_move_execution"
    _change(runtime, transactions, operation="object.setName", object_id=moved["id"],
            new_name="RenamedChild")
    after = _query_one(runtime, object_id=moved["id"])
    assert after["name"] == "RenamedChild" and after["type"] == child_type, after
    assert after["path"] == expected_parent["path"] + "\\RenamedChild", after
    assert _query_one(runtime, object_id=sibling["id"]) == sibling
    assert _query_one(runtime, object_id=source["id"]) == source
    assert _query_one(runtime, object_id=destination["id"]) == destination
    runtime.category_results.append({
        "category": "cross-family-" + child_type.casefold() + "-group-child",
        "status": "PASS",
        "verifier_strength": "created_and_renamed_same_guid_parent_and_sibling_preserved",
        "move_scope": move_scope,
        "transaction_ids": transactions,
    })


def test_cross_family_attenuation_copy_rename_delete_preserves_original(
    workflow_sandbox_runtime: Any,
) -> None:
    runtime = workflow_sandbox_runtime
    transactions: list[str] = []
    suffix = uuid.uuid4().hex[:10]
    root = _query_one(runtime, segments=("Attenuations", "Default Work Unit"))
    original = _create(runtime, transactions, parent=root, object_type="Attenuation",
                       name="CrossFamilyAttenuation_" + suffix)
    copied = _change(runtime, transactions, operation="object.copy",
                     object_id=original["id"], parent_id=root["id"], name_conflict="rename")
    copied_id = _created_object_id(copied["execute"])
    assert copied_id != original["id"]
    renamed = "CrossFamilyAttenuationCopy_" + suffix
    _change(runtime, transactions, operation="object.setName", object_id=copied_id,
            new_name=renamed)
    after = _query_one(runtime, object_id=copied_id)
    assert after["type"] == "Attenuation" and after["name"] == renamed, after
    assert after["path"] == root["path"] + "\\" + renamed, after
    _change(runtime, transactions, operation="object.delete", object_id=copied_id)
    _assert_missing(runtime, copied_id)
    assert _query_one(runtime, object_id=original["id"]) == original
    _record(runtime, "attenuation-copy", transactions)


def test_cross_family_music_segment_move_between_music_containers(
    workflow_sandbox_runtime: Any,
) -> None:
    """Hierarchy ownership only: no transition, playlist order, or playback claim."""
    runtime = workflow_sandbox_runtime
    transactions: list[str] = []
    suffix = uuid.uuid4().hex[:10]
    hierarchy = "Containers" if runtime.version == "2025.1" else "Interactive Music Hierarchy"
    root = _query_one(runtime, segments=(hierarchy, "Default Work Unit"))
    source = _create(runtime, transactions, parent=root, object_type="MusicSwitchContainer",
                     name="CrossFamilyMusicSource_" + suffix)
    destination = _create(runtime, transactions, parent=root, object_type="MusicPlaylistContainer",
                          name="CrossFamilyMusicDestination_" + suffix)
    segment = _create(runtime, transactions, parent=source, object_type="MusicSegment",
                      name="MovingSegment")
    _change(runtime, transactions, operation="object.move", object_id=segment["id"],
            parent_id=destination["id"], name_conflict="fail")
    after = _query_one(runtime, object_id=segment["id"])
    assert after["name"] == "MovingSegment" and after["type"] == "MusicSegment", after
    assert after["path"] == destination["path"] + "\\MovingSegment", after
    assert _query_one(runtime, object_id=source["id"]) == source
    assert _query_one(runtime, object_id=destination["id"]) == destination
    _record(runtime, "music-container-ownership-not-playback", transactions)

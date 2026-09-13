"""Public Gateway checks for Wwise-owned, non-intrinsically named objects.

The fixed GUIDs below are shared by the five committed SampleProject lanes.
They are fixture inputs, not identities inferred from display names or paths.
These tests do not claim playlist ordering, transition, or Stinger playback.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object,
    _complete_object_metadata_business_transaction,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)


# Provenance: Events/Music.wwu, Interactive Music Hierarchy/{Music,MIDI}.wwu
# (Containers/Music/{Music,MIDI}.wwu in 2025.1). The Work Unit XML carries
# these exact IDs and empty intrinsic names in every supported fixture lane.
ACTION = "{73987E03-C964-45B6-83FC-656E55884994}"
STINGER = "{B8D45849-AF76-4770-BE7B-5A6553B1337B}"
PLAYLIST_ITEM = "{7CCDF5F2-1747-48E5-A0C2-96D3707A3980}"
RTPC = "{764CAA28-CA72-4B8D-B0BB-151FABE8DA93}"
BONUS_TRIGGER = "{25D1ACE1-D5FA-450D-826B-745E8B0838BB}"
BACKUP_TRIGGER = "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}"
STINGER_SEGMENT = "{B54923CD-4369-451A-8E64-C142D368037E}"


def _exact_identity(runtime, object_id: str) -> Mapping[str, Any]:
    payload = runtime.gateway(
        ["query-object", "--exact-id", object_id], live=True,
    )
    assert payload["count"] == 1, payload
    rows = payload["objects"]
    assert len(rows) == 1 and rows[0]["id"] == object_id, payload
    row = rows[0]
    assert isinstance(row["name"], str), row
    assert isinstance(row["path"], str) and row["path"], row
    return row


def _expect_check_boundary(runtime, draft, error_code: str) -> None:
    code, rejected = runtime.raw_gateway([
        "draft-check", draft.draft_id,
        "--task-authority", draft.task_authority,
        "--expected-revision", str(draft.revision),
    ])
    assert code == 2, rejected
    assert rejected["error_code"] == error_code, rejected
    assert not rejected.get("transaction_id"), rejected


@pytest.mark.live
@pytest.mark.destructive
@pytest.mark.parametrize(
    ("object_id", "object_type"),
    (
        pytest.param(ACTION, "Action", id="action"),
        pytest.param(STINGER, "MusicStinger", id="stinger"),
        pytest.param(PLAYLIST_ITEM, "MusicPlaylistItem", id="playlist-item"),
        pytest.param(RTPC, "RTPC", id="rtpc"),
    ),
)
def test_cross_family_derived_identity_binds_but_rejects_rename(
    workflow_sandbox_runtime, object_id: str, object_type: str,
) -> None:
    runtime = workflow_sandbox_runtime
    before = _exact_identity(runtime, object_id)
    assert before["type"] == object_type, before
    draft = _start_business_draft(runtime, "object.setName")
    bound = _update_business_draft(
        runtime, draft, "draft-bind-object", ["--object-id", object_id],
        live=True,
    )["bound_object"]
    assert bound["type"] == before["type"], bound
    assert bound["name"] == before["name"], bound
    assert isinstance(bound["handle"], str) and bound["handle"], bound
    _update_business_draft(
        runtime, draft, "draft-declare-object-change",
        ["--new-name", "Must_Not_Rename_Derived_Object"], live=False,
    )
    _expect_check_boundary(runtime, draft, "DERIVED_OBJECT_NAME_BOUNDARY")
    assert _exact_identity(runtime, object_id) == before
    runtime.category_results.append({
        "category": "cross-family-derived-identity-" + object_type,
        "status": "PASS",
        "verifier_strength": "exact_guid_binding_and_no_preview_rename_boundary",
        "object_id": object_id,
        "transaction_ids": [],
    })


@pytest.mark.live
@pytest.mark.destructive
def test_cross_family_rtpc_direct_delete_stops_before_preview(
    workflow_sandbox_runtime,
) -> None:
    runtime = workflow_sandbox_runtime
    before = _exact_identity(runtime, RTPC)
    draft = _start_business_draft(runtime, "object.delete")
    _bind_business_object(runtime, draft, object_id=RTPC)
    _update_business_draft(
        runtime, draft, "draft-declare-object-change", live=False,
    )
    _expect_check_boundary(runtime, draft, "EMBEDDED_OBJECT_DELETE_BOUNDARY")
    assert _exact_identity(runtime, RTPC) == before
    runtime.category_results.append({
        "category": "cross-family-rtpc-direct-delete-boundary",
        "status": "PASS",
        "verifier_strength": "exact_guid_readback_unchanged_no_preview",
        "object_id": RTPC,
        "transaction_ids": [],
    })


def _stinger_state(runtime) -> Mapping[str, Any]:
    payload = runtime.gateway([
        "query-object", "--exact-id", STINGER,
        "--include-field", "Trigger", "--include-field", "Segment",
    ], live=True)
    rows = payload["agent_result"]
    assert isinstance(rows, list) and len(rows) == 1, payload
    assert rows[0]["id"] == STINGER, payload
    return rows[0]


@pytest.mark.live
@pytest.mark.destructive
def test_cross_family_existing_stinger_versioned_reference_boundary_and_change(
    workflow_sandbox_runtime,
) -> None:
    """2021/22 do not expose these references; 2023–25 allow the scoped edit.

    Matching installed WObjects.xml MusicStinger definitions omit both
    references in 2021.1.14 (line 2790) and 2022.1.19 (line 2810), but include
    Trigger/Segment in 2023.1.19 (2792/2799), 2024.1.13 (2760/2767), and
    2025.1.7 (2836/2843). Live metadata, not that offline list, is asserted here.
    """
    runtime = workflow_sandbox_runtime
    if runtime.version in {"2021.1", "2022.1"}:
        before = _exact_identity(runtime, STINGER)
        queried = runtime.gateway([
            "query-object", "--exact-id", STINGER,
            "--include-field", "Trigger", "--include-field", "Segment",
        ], live=True)
        unavailable = queried["agent_result"]
        assert isinstance(unavailable, Mapping), queried
        unresolved = {row["meaning"]: row["candidate_names"] for row in unavailable["unresolved"]}
        assert unresolved["Trigger"] == [], queried
        assert "Segment" in unresolved and "Segment" not in unresolved["Segment"], queried
        draft = _start_business_draft(runtime, "object.setReference")
        owner = _bind_business_object(runtime, draft, object_id=STINGER)
        code, discovered = runtime.raw_gateway([
            "draft-discover-fields", draft.draft_id,
            "--task-authority", draft.task_authority,
            "--expected-revision", str(draft.revision),
            "--object-handle", owner, "--meaning", "Trigger",
        ])
        assert code == 2 and discovered["error_code"] == "GatewayInputError", discovered
        assert discovered["details"]["stage"] == "field_discovery", discovered
        assert discovered["details"]["draft_changed"] is False, discovered
        assert discovered["details"]["meaning_results"] == [{
            "meaning": "Trigger", "candidate_count": 0, "match_status": "no_matches",
        }], discovered
        assert _exact_identity(runtime, STINGER) == before
        runtime.category_results.append({
            "category": "cross-family-existing-stinger-trigger",
            "status": "PASS",
            "verifier_strength": "live_unexposed_reference_boundary_no_edit_or_playback",
            "reference_scope": "Trigger_zero_candidates_Segment_not_an_exact_reference",
            "object_id": STINGER,
            "transaction_ids": [],
        })
        return
    before = _stinger_state(runtime)
    assert before["type"] == "MusicStinger", before
    assert before["references"]["Trigger"]["id"] == BONUS_TRIGGER, before
    assert before["references"]["Segment"]["id"] == STINGER_SEGMENT, before
    target = _exact_identity(runtime, BACKUP_TRIGGER)
    assert target["type"] == "Trigger", target

    changed = _complete_object_metadata_business_transaction(
        runtime, operation="object.setReference", object_id=STINGER,
        field_name="Trigger", target_id=BACKUP_TRIGGER,
    )

    after = _stinger_state(runtime)
    assert after["id"] == before["id"]
    assert after["type"] == before["type"]
    assert after["references"]["Trigger"]["id"] == BACKUP_TRIGGER, after
    assert after["references"]["Segment"] == before["references"]["Segment"], after
    runtime.category_results.append({
        "category": "cross-family-existing-stinger-trigger",
        "status": "PASS",
        "verifier_strength": "reference_execution_and_live_segment_preservation_not_playback",
        "object_id": STINGER,
        "transaction_ids": [changed["verify"]["transaction_id"]],
    })

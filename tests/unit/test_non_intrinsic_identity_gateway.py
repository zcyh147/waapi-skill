"""Exact-GUID binding for Wwise-owned objects with derived display paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import (
    FIRST, SECOND, FieldTask, VERSIONS,
)
from wwise_waapi.business_declarations import (
    BusinessDeclarationError,
    revalidate_live_objects,
)
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.operation_registry import validate_prepared_roles
from wwise_waapi.transactions import TransactionStore


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize(
    ("object_type", "path"),
    (
        ("MusicStinger", "[Stinger : Bonus,Stinger Bonus - Fight]"),
        ("MusicPlaylistItem", "[MusicPlaylistItem : Intro]"),
        ("MusicTrackSequence", "[MusicTrackSequence : 0]"),
        ("Action", "[Play - Rain]"),
        ("EffectSlot", "[Effect Slot 0]"),
    ),
)
def test_set_reference_binds_and_revalidates_derived_display_identity(
    tmp_path: Path, version: str, object_type: str, path: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.setReference")
    task.objects[FIRST] = {
        "id": FIRST, "name": "", "type": object_type, "path": path,
    }

    handle = task.bind(FIRST)

    record = OperationDraftStore(tmp_path / "state").inspect(
        task.draft, task_authority=task.authority,
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"],
    )
    bound = session.handles.resolve_object(handle)
    assert bound.name == ""
    assert bound.path == path
    assert revalidate_live_objects(
        session.handles, (bound,), read_call=task.call,
    ) == (bound,)

    task.objects[FIRST]["path"] = "[Changed display identity]"
    with pytest.raises(BusinessDeclarationError) as error:
        revalidate_live_objects(session.handles, (bound,), read_call=task.call)
    assert error.value.error_code == "OBJECT_HANDLE_STALE"


@pytest.mark.parametrize("version", VERSIONS)
def test_stinger_reference_reaches_immutable_preview_by_guid(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.setReference")
    task.objects[FIRST] = {
        "id": FIRST, "name": "", "type": "MusicStinger",
        "path": "[Stinger : Bonus,Stinger Bonus - Fight]", "Trigger": None,
    }
    task.objects[SECOND] = {
        "id": SECOND, "name": "Backup_Team_Arrives", "type": "Trigger",
        "path": r"\Triggers\Music\Backup_Team_Arrives",
    }
    task.metadata = {
        "Trigger": {"name": "Trigger", "type": "Reference",
                    "supports": {"reference": True}},
    }
    source, target = task.bind(FIRST), task.bind(SECOND)
    field = task.discover(source, "Trigger")
    code, declared = task.step(
        "draft-declare-field-change", "--object-handle", source,
        "--field-handle", field, "--target-handle", target,
    )
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert preview["transaction_id"].startswith("tx1-")
    artifact = TransactionStore(tmp_path / "state").load_preview(
        preview["transaction_id"],
    ).artifact
    prepared = artifact["prepared_operation"]
    assert prepared["dispatch"]["args"] == {
        "object": FIRST, "reference": "Trigger", "value": SECOND,
    }
    assert validate_prepared_roles(prepared, read_call=task.call)["ok"] is True
    task.objects[FIRST]["path"] = "[Stinger : Different,Stinger Bonus - Fight]"
    assert validate_prepared_roles(prepared, read_call=task.call)["ok"] is False
    for uri, args, _options in task.calls:
        if uri.endswith("object.get") and "from" in args:
            assert set(args["from"]) == {"id"}
    assert not any(uri.endswith("setReference") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize(
    "changes",
    (
        {"name": None},
        {"name": 0},
        {"name": False},
        {"name": []},
        {"name": " "},
        {"type": "Sound", "name": "Named Sound"},
        {"type": "UnknownType", "name": "Named Unknown"},
        {"type": "Sound", "path": r"\Fixture\Sound"},
        {"type": "UnknownType", "path": r"\Fixture\Unknown"},
        {"path": "relative/path"},
        {"path": "[unclosed"},
        {"path": "[]"},
        {"path": "[ ]"},
        {"path": "[Stinger]\u0000"},
        {"path": "[Stinger\nnewline]"},
        {"path": "[Stinger]\\"},
        {"id": "not-a-guid"},
    ),
)
def test_binding_rejects_malformed_or_unreviewed_display_identity_atomically(
    tmp_path: Path, version: str, changes: dict[str, object],
) -> None:
    task = FieldTask(tmp_path, version, "object.setReference")
    task.objects[FIRST] = {
        "id": FIRST, "name": "", "type": "MusicStinger",
        "path": "[Stinger : Bonus,Stinger Bonus - Fight]", **changes,
    }
    code, rejected = task.step("draft-bind-object", "--object-id", FIRST)
    assert code == 2, rejected
    assert rejected["error_code"] == "BUSINESS_OBJECT_BINDING_MISMATCH"
    assert task.revision == 1
    record = OperationDraftStore(tmp_path / "state").inspect(
        task.draft, task_authority=task.authority,
    )
    assert record.revision == 1


@pytest.mark.parametrize("missing_field", ("id", "name", "type", "path"))
def test_binding_rejects_missing_identity_fields(
    tmp_path: Path, missing_field: str,
) -> None:
    task = FieldTask(tmp_path, "2025.1", "object.setReference")
    task.objects[FIRST] = {
        "id": FIRST, "name": "", "type": "MusicStinger", "path": "[Stinger]",
    }
    del task.objects[FIRST][missing_field]
    code, rejected = task.step("draft-bind-object", "--object-id", FIRST)
    assert code == 2, rejected
    assert rejected["error_code"] == "BUSINESS_OBJECT_BINDING_MISMATCH"
    assert task.revision == 1

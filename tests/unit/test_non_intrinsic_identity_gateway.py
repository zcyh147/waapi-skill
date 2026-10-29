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


# Exact retained 2025.1.7.9143 rows from the #195 owned-role survey
# observations.json (calls 8/9/10/18); the four Language rows also occur in
# 195-language-registration-native-634f9f13-r1's before.languages.
EXISTING_DISPLAY_ROWS_2025 = (
    {"id": "{273F02D0-F4F6-49D6-B2F2-B46585A2406B}", "classId": 4915216,
     "name": "English(US)", "path": "English(US)", "type": "Language"},
    {"id": "{85A66963-A627-476E-91C1-2770B39D245A}", "classId": 4915216,
     "name": "SFX", "path": "SFX", "type": "Language"},
    {"id": "{A16779F6-31AE-49D7-8073-75A9B6A7712E}", "classId": 4915216,
     "name": "External", "path": "External", "type": "Language"},
    {"id": "{E78A31D1-1469-4D88-86B4-45E6C18DF445}", "classId": 4915216,
     "name": "Mixed", "path": "Mixed", "type": "Language"},
    {"id": "{C7B4A1D9-E8F0-4B3C-9A1D-5F6E7D8C9B0A}", "classId": 5701648,
     "name": "Media Pool Query Root", "path": "Media Pool Query Root", "type": "MediaPoolQuery"},
    {"id": "{B618CBBD-04FA-4149-A36B-37B8A1F2B642}", "classId": 4128784,
     "name": "CC #0: Bank Select", "path": r"MIDI\CC 0-31\CC #0: Bank Select", "type": "MidiParameter",
     "parent": {"id": "{C6BA08D1-8AD0-4346-83EA-B58E43CDACBA}", "name": "CC 0-31"}},
    {"id": "{B618CBBE-04FA-4149-A36B-37B8A1F2B642}", "classId": 4128784,
     "name": "CC #1: Modulation", "path": r"MIDI\CC 0-31\CC #1: Modulation", "type": "MidiParameter",
     "parent": {"id": "{C6BA08D1-8AD0-4346-83EA-B58E43CDACBA}", "name": "CC 0-31"}},
    {"id": "{E4FAC352-C4BE-485E-9D1D-A14FC671EDE7}", "classId": 3342352,
     "name": "", "path": "<Unnamed Default Object Values>", "type": "UserProjectSettings"},
)


class ExistingDisplayTask(FieldTask):
    def call(self, uri, args=None, options=None):
        if uri.endswith("object.get") and "waql" in args:
            for object_id, row in self.objects.items():
                if args["waql"] == f'from object "{object_id}"':
                    self.calls.append((uri, args, options))
                    return {"return": self.project_rows([row], options)}
        return super().call(uri, args, options)


def existing_display_task(tmp_path, row, *, version="2025.1", operation="object.setProperty"):
    task = ExistingDisplayTask(tmp_path, version, operation)
    task.objects = {row["id"]: dict(row)}
    task.types = [{"name": row["type"], "classId": row["classId"], "type": "WObject"}]
    task.metadata = {}
    return task


@pytest.mark.parametrize("row", EXISTING_DISPLAY_ROWS_2025, ids=lambda row: row["type"] + ":" + row["name"])
@pytest.mark.parametrize("route", ["query", "metadata", "bind"])
def test_retained_2025_existing_display_identity_is_usable_by_exact_guid(tmp_path, row, route):
    task = existing_display_task(tmp_path, row)
    if route == "query":
        code, payload = task.run("query-object", "--exact-id", row["id"])
        assert code == 0, (payload, task.calls[-1])
        assert payload["agent_result"] == [{key: row[key] for key in ("id", "name", "type", "path")}]
    elif route == "metadata":
        code, payload = task.run("metadata", "list", "--exact-id", row["id"])
        assert code == 0, payload
        assert payload["agent_result"]["fields"] == []
    else:
        code, payload = task.step("draft-bind-object", "--object-id", row["id"])
        assert code == 0, payload
        assert payload["bound_object"]["handle"].startswith("boh1-")
        assert payload["bound_object"]["name"] == row["name"]
        assert payload["bound_object"]["type"] == row["type"]
    assert all(set(args["from"]) == {"id"} for uri, args, _ in task.calls
               if uri.endswith("object.get") and "from" in args)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("row,token", [
    (EXISTING_DISPLAY_ROWS_2025[0], "VolumeOffset"),
    (EXISTING_DISPLAY_ROWS_2025[5], "SimulationValue"),
    (EXISTING_DISPLAY_ROWS_2025[7], "DefaultSoundVolume"),
])
def test_existing_display_field_preview_preserves_exact_identity_across_supported_lanes(tmp_path, version, row, token):
    # Same registered classes/fields in five pinned WObjects definitions. Only
    # the 2025 identity shape is native-observed; older lanes test the invariant.
    task = existing_display_task(tmp_path, row, version=version)
    task.objects[row["id"]]["@" + token] = 0.0
    task.metadata = {token: {"name": token, "type": "Real64"}}
    target = task.bind(row["id"])
    field = task.discover(target, token)
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "1")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    code, shown = task.run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["dispatch"]["args"] == {"object": row["id"], "property": token, "value": 1}
    assert task.objects[row["id"]]["@" + token] == 0.0
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


@pytest.mark.parametrize("row", [EXISTING_DISPLAY_ROWS_2025[i] for i in (0, 4, 5, 7)])
@pytest.mark.parametrize("damage", ["guid", "different-guid", "wrong-type", "control", "missing-name"])
def test_existing_display_binding_rejects_invalid_identity_without_changing_draft(tmp_path, row, damage):
    task = existing_display_task(tmp_path, row)
    damaged = task.objects[row["id"]]
    if damage == "guid":
        damaged["id"] = "not-a-guid"
    elif damage == "different-guid":
        damaged["id"] = FIRST
    elif damage == "wrong-type":
        damaged["type"] = "Sound"
    elif damage == "control":
        damaged["path"] += "\x85"
    else:
        del damaged["name"]
    code, rejected = task.step("draft-bind-object", "--object-id", row["id"])
    assert code == 2 and rejected["error_code"] == "BUSINESS_OBJECT_BINDING_MISMATCH", rejected
    assert task.revision == 1


@pytest.mark.parametrize("row,token", [
    (EXISTING_DISPLAY_ROWS_2025[0], "VolumeOffset"),
    (EXISTING_DISPLAY_ROWS_2025[5], "SimulationValue"),
    (EXISTING_DISPLAY_ROWS_2025[7], "DefaultSoundVolume"),
])
@pytest.mark.parametrize("field,value", [("id", FIRST), ("name", "Changed"), ("type", "Sound"), ("path", "Changed")])
def test_existing_display_field_preview_stops_on_identity_readback_drift(tmp_path, row, token, field, value):
    task = existing_display_task(tmp_path, row)
    task.metadata = {token: {"name": token, "type": "Real64"}}
    task.objects[row["id"]]["@" + token] = 0.0
    target = task.bind(row["id"])
    selected = task.discover(target, token)
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", selected, "--business-value", "1")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    task.objects[row["id"]][field] = value
    revision = task.revision
    code, rejected = task.step("preview-from-draft")
    assert code == 2, rejected
    assert rejected["error_code"] == ("IDENTITY_MISMATCH" if field == "id" else "OPERATION_DRAFT_BINDING_DRIFT"), rejected
    assert task.revision == revision
    assert "transaction_id" not in rejected
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version,row,operation", [
    (version, EXISTING_DISPLAY_ROWS_2025[index], operation)
    for index in (0, 4, 5, 7) for version in VERSIONS
    for operation in ("object.setName", "object.set")
    if not (index == 0 and version == "2021.1")
    and (index != 4 or version == "2025.1")
    and (operation != "object.set" or version != "2021.1")
])
def test_existing_display_admission_does_not_authorize_rename(tmp_path, version, row, operation):
    task = existing_display_task(tmp_path, row, version=version, operation=operation)
    target = task.bind(row["id"])
    if operation == "object.set":
        code, rejected = task.step("draft-declare-existing", "--declaration-id", "selected",
            "--object-handle", target, "--field", "new_name", "Renamed")
    else:
        code, declared = task.step("draft-declare-object-change", "--new-name", "Renamed")
        assert code == 0, declared
        code, rejected = task.step("draft-check")
    assert code == 2 and rejected["error_code"] == "DISPLAY_IDENTITY_NAME_BOUNDARY", rejected
    assert not any(uri.endswith("setName") for uri, _, _ in task.calls)


def test_legacy_2021_language_name_preparation_remains_available(tmp_path):
    row = EXISTING_DISPLAY_ROWS_2025[0]
    task = existing_display_task(tmp_path, row, version="2021.1", operation="object.setName")
    task.bind(row["id"])
    code, declared = task.step("draft-declare-object-change", "--new-name", "EnglishAlt")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    code, shown = task.run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["dispatch"]["uri"] == "ak.wwise.core.object.setName"
    assert prepared["dispatch"]["args"] == {"object": row["id"], "value": "EnglishAlt"}
    assert task.objects[row["id"]]["name"] == "English(US)"
    assert not any(uri.endswith("setName") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[:-1])
def test_media_pool_display_shape_does_not_imply_older_class_support(tmp_path, version):
    row = EXISTING_DISPLAY_ROWS_2025[4]
    task = existing_display_task(tmp_path, row, version=version)
    code, rejected = task.step("draft-bind-object", "--object-id", row["id"])
    assert code == 2 and rejected["error_code"] == "BUSINESS_OBJECT_BINDING_MISMATCH", rejected
    assert task.revision == 1


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

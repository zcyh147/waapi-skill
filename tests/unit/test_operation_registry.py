from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    list_operation_specs,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


GUID = "{11111111-1111-1111-1111-111111111111}"
PARENT_GUID = "{22222222-2222-2222-2222-222222222222}"
TARGET_GUID = "{33333333-3333-3333-3333-333333333333}"


class ScriptedReader:
    def __init__(self, responses: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        return self.responses[uri].popleft()


def request(operation: str, arguments: Mapping[str, Any], version: str = "2022.1") -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def object_row(
    *,
    object_id: str = GUID,
    name: str = "OldName",
    object_type: str = "Sound",
    path: str = r"\Actor-Mixer Hierarchy\Default Work Unit\OldName",
    parent: str = PARENT_GUID,
    notes: str = "before",
    **values: Any,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": name,
        "type": object_type,
        "path": path,
        "parent": {"id": parent},
        "notes": notes,
        **values,
    }


def test_operation_catalog_is_truthful_about_closed_and_boundary_operations() -> None:
    specs = {spec.name: spec.as_dict() for spec in list_operation_specs()}

    assert len(specs) == 17
    assert specs["object.create"]["implemented"] is True
    assert specs["audio.import"]["implemented"] is True
    assert "identity_contract" not in specs["audio.import"]
    import_items = specs["audio.import"]["argument_contract"]["properties"]["imports"]["items"]
    assert import_items["required"] == ["object_path", "audio_file"]
    assert import_items["additionalProperties"] is False
    assert specs["soundbank.setInclusions"]["argument_contract"]["properties"]["mode"]["enum"] == [
        "add",
        "remove",
        "replace",
    ]
    assert specs["switchContainer.addAssignment"]["identity_contract"]["argument_fields"] == [
        "switch_container",
        "child",
        "state_or_switch",
    ]
    assert "rejects a child that already has any assignment" in specs["switchContainer.addAssignment"]["constraints"][-1]
    assert specs["object.set"]["implemented"] is False
    assert specs["object.set"]["supported_versions"] == ["2022.1", "2023.1", "2024.1", "2025.1"]
    assert "returned copy GUID" in specs["object.copy"]["boundary"]
    assert specs["object.setProperty"]["identity_contract"]["caller_rows_allowed"] is False
    assert specs["soundbank.convertExternalSources"]["supported_versions"] == [
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ]


def test_compact_operation_inventory_is_stable_and_keeps_boundary_text() -> None:
    specs = {spec.name: spec.as_compact_dict() for spec in list_operation_specs()}

    assert set(specs["object.create"]) == {
        "name",
        "uri",
        "family",
        "summary",
        "implemented",
        "boundary",
        "supported_versions",
        "required_arguments",
        "optional_arguments",
    }
    assert specs["object.create"]["implemented"] is True
    assert specs["object.create"]["boundary"] is None
    assert specs["object.copy"]["implemented"] is False
    assert "returned copy GUID" in specs["object.copy"]["boundary"]
    assert "argument_contract" not in specs["object.create"]


def test_request_contract_rejects_unknown_fields_metadata_injection_and_boundaries() -> None:
    parsed = parse_operation_request(
        request("object.setName", {"object": {"kind": "id", "value": GUID}, "value": "NewName"}),
        expected_version="2022.1",
    )
    assert parsed.operation == "object.setName"

    with pytest.raises(OperationContractError) as injected:
        parse_operation_request(
            request(
                "object.setProperty",
                {
                    "object": {"kind": "id", "value": GUID},
                    "property": "Volume",
                    "value": -6.0,
                    "property_info": {"name": "Volume", "type": "Real32"},
                },
            )
        )
    assert injected.value.error_code == "INVALID_REQUEST"
    assert injected.value.details["unknown_fields"] == ["property_info"]

    with pytest.raises(OperationContractError) as boundary:
        parse_operation_request(request("object.copy", {"object": {}, "parent": {}}))
    assert boundary.value.error_code == "OPERATION_BOUNDARY"

    with pytest.raises(OperationContractError) as mismatch:
        parse_operation_request(
            request("object.delete", {"object": {"kind": "id", "value": GUID}}),
            expected_version="2025.1",
        )
    assert mismatch.value.error_code == "VERSION_MISMATCH"

    with pytest.raises(OperationContractError) as nested_import:
        parse_operation_request(
            request(
                "audio.import",
                {
                    "imports": [
                        {
                            "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Imported",
                            "audio_file": "/tmp/import.wav",
                            "defaults": {"@Volume": -6},
                        }
                    ]
                },
            )
        )
    assert nested_import.value.error_code == "INVALID_REQUEST"
    assert nested_import.value.details["unknown_fields"] == ["defaults"]

    with pytest.raises(OperationContractError) as nested_inclusion:
        parse_operation_request(
            request(
                "soundbank.setInclusions",
                {
                    "soundbank": {"kind": "id", "value": GUID},
                    "mode": "add",
                    "inclusions": [
                        {
                            "object": {"kind": "id", "value": TARGET_GUID},
                            "filters": ["media"],
                            "existing": [],
                        }
                    ],
                },
            )
        )
    assert nested_inclusion.value.error_code == "INVALID_REQUEST"


def test_create_preflight_canonicalizes_parent_and_fixes_cross_version_source_control_default() -> None:
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Sandbox"
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        object_row(
                            object_id=PARENT_GUID,
                            name="WAAPI Sandbox",
                            object_type="WorkUnit",
                            path=parent_path,
                            parent="{hierarchy}",
                        )
                    ]
                }
            ]
        }
    )
    parsed = parse_operation_request(
        request(
            "object.create",
            {
                "parent": {"kind": "path", "value": parent_path},
                "type": "ActorMixer",
                "name": "CreatedByRegistry",
                "notes": "stable",
            },
        )
    )

    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.object.create",
        "args": {
            "parent": PARENT_GUID,
            "type": "ActorMixer",
            "name": "CreatedByRegistry",
            "onNameConflict": "fail",
            "notes": "stable",
            "autoAddToSourceControl": False,
        },
        "options": {},
    }
    assert prepared["resolved_roles"]["parent"]["object"] == PARENT_GUID
    assert prepared["verification_plan"]["result_id_required"] is True
    assert prepared["raw_dispatch_allowed"] is False
    assert reader.calls[0][1] == {"from": {"path": [parent_path]}}


def test_property_and_reference_metadata_are_live_runtime_inputs_not_request_fields() -> None:
    property_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {"return": [{"id": GUID, "path": object_row()["path"], "@Volume": -3.0}]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {"name": "Volume", "type": "Real32", "supports": {"randomizer": True}}
            ],
        }
    )
    property_request = parse_operation_request(
        request(
            "object.setProperty",
            {"object": {"kind": "id", "value": GUID}, "property": "Volume", "value": -6.0},
        )
    )
    prepared_property = prepare_operation(property_request, read_call=property_reader).as_dict()
    assert prepared_property["dispatch"]["args"] == {"object": GUID, "property": "Volume", "value": -6.0}
    assert prepared_property["pre_state"]["field_info"]["type"] == "Real32"

    reference_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {"return": [{"id": GUID, "path": object_row()["path"], "OutputBus": {"id": PARENT_GUID}}]},
                {
                    "return": [
                        object_row(
                            object_id=TARGET_GUID,
                            name="Master Audio Bus",
                            object_type="Bus",
                            path=r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
                        )
                    ]
                },
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {"name": "OutputBus", "type": "Reference", "supports": {"reference": True}}
            ],
        }
    )
    reference_request = parse_operation_request(
        request(
            "object.setReference",
            {
                "object": {"kind": "id", "value": GUID},
                "reference": "OutputBus",
                "target": {"kind": "id", "value": TARGET_GUID},
            },
        )
    )
    prepared_reference = prepare_operation(reference_request, read_call=reference_reader).as_dict()
    assert prepared_reference["dispatch"]["args"] == {
        "object": GUID,
        "reference": "OutputBus",
        "value": TARGET_GUID,
    }
    assert prepared_reference["resolved_roles"]["target"]["object"] == TARGET_GUID


def test_reference_target_is_checked_against_legacy_live_restrictions() -> None:
    source_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    group_id = "{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}"
    source_row = object_row(
        object_id=source_id,
        name="SwitchContainer",
        object_type="SwitchContainer",
    )
    group_row = object_row(
        object_id=group_id,
        name="Group",
        object_type="SwitchGroup",
        path=r"\Switches\Default Work Unit\Group",
    )
    metadata = {
        "name": "SwitchGroupOrStateGroup",
        "type": "",
        "supports": {"randomizer": False, "rtpc": "None", "unlink": False},
        "restriction": {
            "type": "reference",
            "restrictions": [{"type": ["Switch Group", "State Group"], "sharedOnlyTypes": []}],
        },
    }
    arguments = {
        "object": {"kind": "id", "value": source_id},
        "reference": "SwitchGroupOrStateGroup",
        "target": {"kind": "id", "value": group_id},
    }
    prepared = prepare_operation(
        parse_operation_request(request("object.setReference", arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [source_row]},
                    {"return": [{"id": source_id, "SwitchGroupOrStateGroup": None}]},
                    {"return": [group_row]},
                ],
                "ak.wwise.core.object.getPropertyInfo": [metadata],
            }
        ),
    ).as_dict()
    assert prepared["dispatch"]["args"] == {
        "object": source_id,
        "reference": "SwitchGroupOrStateGroup",
        "value": group_id,
    }

    wrong_target = object_row(object_id=group_id, name="NotAGroup", object_type="Sound")
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(request("object.setReference", arguments)),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [source_row]},
                        {"return": [{"id": source_id, "SwitchGroupOrStateGroup": None}]},
                        {"return": [wrong_target]},
                    ],
                    "ak.wwise.core.object.getPropertyInfo": [metadata],
                }
            ),
        )
    assert rejected.value.error_code == "INVALID_REFERENCE_TARGET"


def test_all_identities_are_live_resolved_and_ambiguous_or_protected_targets_fail_closed() -> None:
    ambiguous = ScriptedReader(
        {"ak.wwise.core.object.get": [{"return": [object_row(), object_row(object_id=TARGET_GUID)]}]}
    )
    parsed = parse_operation_request(
        request("object.delete", {"object": {"kind": "waql", "value": "from type Sound"}})
    )
    with pytest.raises(OperationContractError) as ambiguity:
        prepare_operation(parsed, read_call=ambiguous)
    assert ambiguity.value.error_code == "AMBIGUOUS_IDENTITY"

    protected = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        object_row(
                            object_id="{project}",
                            name="SampleProject",
                            object_type="Project",
                            path="\\",
                        )
                    ]
                }
            ]
        }
    )
    project_delete = parse_operation_request(
        request("object.delete", {"object": {"kind": "id", "value": "{project}"}})
    )
    with pytest.raises(OperationContractError) as target:
        prepare_operation(project_delete, read_call=protected)
    assert target.value.error_code == "PROTECTED_TARGET"


def test_rename_verifier_proves_same_guid_new_path_parent_and_old_path_absence() -> None:
    preview_reader = ScriptedReader({"ak.wwise.core.object.get": [{"return": [object_row()]}]})
    parsed = parse_operation_request(
        request("object.setName", {"object": {"kind": "path", "value": object_row()["path"]}, "value": "NewName"})
    )
    prepared = prepare_operation(parsed, read_call=preview_reader).as_dict()
    verification_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        object_row(
                            name="NewName",
                            path=r"\Actor-Mixer Hierarchy\Default Work Unit\NewName",
                        )
                    ]
                },
                {"return": []},
            ]
        }
    )

    result = verify_prepared_operation(prepared, execution_result={}, read_call=verification_reader)

    assert result.status == "verified"
    assert all(item["passed"] for item in result.assertions)
    assert len(result.readbacks) == 2
    assert verification_reader.calls[0][1] == {"from": {"id": [GUID]}}
    assert verification_reader.calls[1][1] == {"from": {"path": [object_row()["path"]]}}


def test_confirmed_execution_role_guard_requires_the_live_preview_snapshot_to_be_unchanged() -> None:
    parsed = parse_operation_request(
        request("object.setNotes", {"object": {"kind": "id", "value": GUID}, "value": "after"})
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [object_row()]}]}),
    ).as_dict()

    valid = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [object_row()]}]}),
    )
    drifted = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [object_row(path=r"\Actor-Mixer Hierarchy\Default Work Unit\MovedElsewhere")]}
                ]
            }
        ),
    )

    assert valid["status"] == "valid"
    assert valid["ok"] is True
    assert drifted["status"] == "repreview_required"
    assert any(item["name"] == "object.path unchanged" and not item["passed"] for item in drifted["assertions"])


def test_create_delete_property_and_reference_verifiers_have_typed_outcomes() -> None:
    created_id = "{44444444-4444-4444-4444-444444444444}"
    prepared_create = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.create",
        "verification_plan": {
            "kind": "created-guid-present",
            "expected": {
                "name": "Created",
                "requested_type": "ActorMixer",
                "parent_id": PARENT_GUID,
                "notes": "stable",
            },
        },
    }
    create_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        object_row(
                            object_id=created_id,
                            name="Created",
                            object_type="PropertyContainer",
                            path=r"\Actor-Mixer Hierarchy\Default Work Unit\Created",
                            notes="stable",
                        )
                    ]
                }
            ]
        }
    )
    created = verify_prepared_operation(
        prepared_create,
        execution_result={"result": {"id": created_id}},
        read_call=create_reader,
    )
    assert created.status == "verified"
    assert next(item for item in created.assertions if item["name"] == "created type is captured")["passed"] is True

    prepared_delete = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.delete",
        "verification_plan": {"kind": "guid-absent", "object_id": GUID},
    }
    deleted = verify_prepared_operation(
        prepared_delete,
        execution_result={},
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": []}]}),
    )
    assert deleted.status == "verified"

    prepared_property = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.setProperty",
        "verification_plan": {
            "kind": "same-guid-property",
            "object_id": GUID,
            "field": "Volume",
            "expected_value": -6.0,
            "metadata_type": "Real32",
        },
    }
    property_result = verify_prepared_operation(
        prepared_property,
        execution_result={},
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": [{"id": GUID, "@Volume": -5.999999}]}]}
        ),
    )
    assert property_result.status == "verified"

    prepared_reference = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.setReference",
        "verification_plan": {
            "kind": "same-guid-reference",
            "object_id": GUID,
            "field": "OutputBus",
            "expected_target_id": TARGET_GUID,
        },
    }
    reference_result = verify_prepared_operation(
        prepared_reference,
        execution_result={},
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": [{"id": GUID, "OutputBus": {"name": "No GUID"}}]}]}
        ),
    )
    assert reference_result.status == "indeterminate"
    assert reference_result.ok is False


def test_audio_import_closes_nested_fields_files_targets_defaults_and_verification(tmp_path: Any) -> None:
    audio_file = tmp_path / "source.wav"
    audio_file.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit"
    target_path = parent_path + r"\Imported"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="Default Work Unit",
        object_type="WorkUnit",
        path=parent_path,
        parent="{actor-root}",
    )
    parsed = parse_operation_request(
        request(
            "audio.import",
            {
                "imports": [
                    {
                        "object_path": parent_path + r"\<Sound>Imported",
                        "object_type": "Sound",
                        "audio_file": str(audio_file),
                        "notes": "closed import",
                    }
                ]
            },
            version="2023.1",
        )
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [parent_row]},
                    {"return": []},
                ]
            }
        ),
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.audio.import",
        "args": {
            "imports": [
                {
                    "objectPath": parent_path + r"\<Sound>Imported",
                    "objectType": "Sound",
                    "audioFile": str(audio_file.resolve()),
                    "notes": "closed import",
                }
            ],
            "importOperation": "createNew",
            "autoAddToSourceControl": False,
            "autoCheckOutToSourceControl": False,
        },
        "options": {"return": ["id", "name", "type", "path"]},
    }
    assert prepared["pre_state"]["audio_import_files"][0]["size"] == audio_file.stat().st_size
    assert len(prepared["pre_state"]["audio_import_files"][0]["sha256"]) == 64
    assert prepared["cleanup"]["automatic_retry"] is False

    created_id = "{44444444-4444-4444-4444-444444444444}"
    created_row = object_row(
        object_id=created_id,
        name="Imported",
        object_type="Sound",
        path=target_path,
        parent=PARENT_GUID,
        notes="closed import",
    )
    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "log": [],
                "files": [str(audio_file.resolve())],
                "objects": [created_row],
            }
        },
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [created_row]}]}),
    )
    assert verified.status == "verified"
    assert {item["name"] for item in verified.assertions} >= {
        "import result shape matches version",
        "audio import log entries are well formed",
        "audio import log has no errors",
        "import target returned exactly once",
        "imported GUID resolves exactly once",
        "imported path matches returned target",
        "imported notes match request",
    }

    audio_file.write_bytes(b"changed after preview")
    guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [parent_row]},
                    {"return": []},
                ]
            }
        ),
    )
    assert guard["status"] == "repreview_required"
    assert any(item["name"] == "imports[0].audio_file unchanged" and not item["passed"] for item in guard["assertions"])


@pytest.mark.parametrize("version", ["2021.1", "2022.1"])
def test_old_audio_import_result_uses_runtime_objects_list_without_new_log_contract(version: str) -> None:
    created_id = "{44444444-4444-4444-4444-444444444444}"
    target_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Imported"
    created_row = object_row(object_id=created_id, name="Imported", object_type="Sound", path=target_path)
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "audio.import",
        "verification_plan": {
            "kind": "audio-import-created-objects",
            "version": version,
            "targets": [
                {
                    "index": 0,
                    "canonical_target_path": target_path,
                    "requested_type": "Sound",
                }
            ],
        },
    }
    result = verify_prepared_operation(
        prepared,
        execution_result={"result": {"objects": [created_row]}},
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [created_row]}]}),
    )

    assert result.status == "verified"
    assert "audio import log has no errors" not in {item["name"] for item in result.assertions}


def test_new_audio_import_error_log_is_a_failed_postcondition() -> None:
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "audio.import",
        "verification_plan": {
            "kind": "audio-import-created-objects",
            "version": "2025.1",
            "targets": [],
        },
    }
    result = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "log": [{"severity": "Error", "message": "file rejected", "index": 0}],
                "files": [],
                "objects": [],
            }
        },
        read_call=ScriptedReader({}),
    )

    assert result.status == "verification_failed"
    assertion = next(item for item in result.assertions if item["name"] == "audio import log has no errors")
    assert assertion["passed"] is False


@pytest.mark.parametrize(
    "bad_log",
    (
        {"message": "missing severity", "index": 0},
        {"severity": "Mystery", "message": "unknown severity", "index": 0},
        {"severity": "Message", "index": 0},
        {"severity": "Message", "message": "bad index", "index": True},
    ),
)
def test_new_audio_import_malformed_log_fails_closed(bad_log: Mapping[str, Any]) -> None:
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "audio.import",
        "verification_plan": {
            "kind": "audio-import-created-objects",
            "version": "2025.1",
            "targets": [],
        },
    }
    result = verify_prepared_operation(
        prepared,
        execution_result={"result": {"log": [dict(bad_log)], "files": [], "objects": []}},
        read_call=ScriptedReader({}),
    )

    assert result.status == "verification_failed"
    assertion = next(item for item in result.assertions if item["name"] == "audio import log entries are well formed")
    assert assertion["passed"] is False


@pytest.mark.parametrize("unsupported_field", ["import_language", "originals_subfolder"])
def test_audio_import_rejects_optional_fields_without_cross_version_verifiers(
    unsupported_field: str,
) -> None:
    with pytest.raises(OperationContractError) as unsupported:
        parse_operation_request(
            request(
                "audio.import",
                {
                    "imports": [
                        {
                            "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Imported",
                            "audio_file": "/tmp/import.wav",
                            unsupported_field: "Unverified",
                        }
                    ]
                },
            )
        )
    assert unsupported.value.error_code == "INVALID_REQUEST"
    assert unsupported_field in unsupported.value.details["unknown_fields"]


def test_audio_import_uses_versioned_authoring_roots_for_2025_containers(tmp_path: Any) -> None:
    audio_file = tmp_path / "source.wav"
    audio_file.write_bytes(b"RIFFWAVE")
    parent_path = r"\Containers\Default Work Unit"
    parsed = parse_operation_request(
        request(
            "audio.import",
            {
                "imports": [
                    {
                        "object_path": parent_path + r"\<Sound>Imported2025",
                        "audio_file": str(audio_file),
                        "object_type": "Sound",
                    }
                ]
            },
            version="2025.1",
        )
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            object_row(
                                object_id=PARENT_GUID,
                                name="Default Work Unit",
                                object_type="WorkUnit",
                                path=parent_path,
                                parent="{containers-root}",
                            )
                        ]
                    },
                    {"return": []},
                ]
            }
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"]["imports"][0]["objectPath"].startswith(r"\Containers\Default Work Unit")
    assert prepared["dispatch"]["args"]["autoCheckOutToSourceControl"] is False

    parsed_2024 = parse_operation_request(
        request(
            "audio.import",
            {
                "imports": [
                    {
                        "object_path": parent_path + r"\<Sound>Rejected2024",
                        "audio_file": str(audio_file),
                    }
                ]
            },
            version="2024.1",
        )
    )
    with pytest.raises(OperationContractError) as wrong_root:
        prepare_operation(parsed_2024, read_call=ScriptedReader({}))
    assert wrong_root.value.error_code == "INVALID_TARGET"


def test_soundbank_inclusions_use_internal_prestate_exact_poststate_and_drift_guard() -> None:
    soundbank_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    soundbank_row = object_row(
        object_id=soundbank_id,
        name="ClosedBank",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\ClosedBank",
        parent="{soundbanks-workunit}",
    )
    inclusion_row = object_row(object_id=TARGET_GUID, name="Included", object_type="Sound")
    arguments = {
        "soundbank": {"kind": "id", "value": soundbank_id},
        "mode": "add",
        "inclusions": [
            {
                "object": {"kind": "id", "value": TARGET_GUID},
                "filters": ["structures", "media"],
            }
        ],
    }
    prepared = prepare_operation(
        parse_operation_request(request("soundbank.setInclusions", arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [soundbank_row]},
                    {"return": [inclusion_row]},
                ],
                "ak.wwise.core.soundbank.getInclusions": [{"inclusions": []}],
            }
        ),
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.soundbank.setInclusions",
        "args": {
            "soundbank": soundbank_id,
            "operation": "add",
            "inclusions": [{"object": TARGET_GUID, "filter": ["media", "structures"]}],
        },
        "options": {},
    }
    assert prepared["verification_plan"]["kind"] == "soundbank-inclusions-exact"
    assert prepared["cleanup"]["kind"] == "restore-soundbank-inclusions-from-prestate"

    normalized_after = {"inclusions": [{"object": {"id": TARGET_GUID}, "filter": ["structures", "media"]}]}
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader({"ak.wwise.core.soundbank.getInclusions": [normalized_after]}),
    )
    assert verified.status == "verified"

    valid_guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [soundbank_row]},
                    {"return": [inclusion_row]},
                ],
                "ak.wwise.core.soundbank.getInclusions": [{"inclusions": []}],
            }
        ),
    )
    assert valid_guard["status"] == "valid"
    drifted_guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [soundbank_row]},
                    {"return": [inclusion_row]},
                ],
                "ak.wwise.core.soundbank.getInclusions": [normalized_after],
            }
        ),
    )
    assert drifted_guard["status"] == "repreview_required"

    with pytest.raises(OperationContractError) as no_op:
        prepare_operation(
            parse_operation_request(request("soundbank.setInclusions", arguments)),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [soundbank_row]},
                        {"return": [inclusion_row]},
                    ],
                    "ak.wwise.core.soundbank.getInclusions": [normalized_after],
                }
            ),
        )
    assert no_op.value.error_code == "NO_OP"


def test_soundbank_replace_empty_is_a_closed_exact_clear_and_add_empty_is_rejected() -> None:
    soundbank_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    soundbank_row = object_row(
        object_id=soundbank_id,
        name="ClosedBank",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\ClosedBank",
        parent="{soundbanks-workunit}",
    )
    before = {"inclusions": [{"object": {"id": TARGET_GUID}, "filter": ["media"]}]}
    clear_arguments = {
        "soundbank": {"kind": "id", "value": soundbank_id},
        "mode": "replace",
        "inclusions": [],
    }
    prepared = prepare_operation(
        parse_operation_request(request("soundbank.setInclusions", clear_arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [{"return": [soundbank_row]}],
                "ak.wwise.core.soundbank.getInclusions": [before],
            }
        ),
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.soundbank.setInclusions",
        "args": {"soundbank": soundbank_id, "operation": "replace", "inclusions": []},
        "options": {},
    }
    assert prepared["verification_plan"]["expected"] == []
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader({"ak.wwise.core.soundbank.getInclusions": [{"inclusions": []}]}),
    )
    assert verified.status == "verified"

    with pytest.raises(OperationContractError) as empty_add:
        prepare_operation(
            parse_operation_request(
                request(
                    "soundbank.setInclusions",
                    {**clear_arguments, "mode": "add"},
                )
            ),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [{"return": [soundbank_row]}],
                    "ak.wwise.core.soundbank.getInclusions": [before],
                }
            ),
        )
    assert empty_add.value.error_code == "INVALID_ARGUMENT"


def test_soundbank_add_upserts_filter_row_and_remove_requires_exact_live_row() -> None:
    soundbank_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    soundbank_row = object_row(
        object_id=soundbank_id,
        name="ClosedBank",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\ClosedBank",
        parent="{soundbanks-workunit}",
    )
    inclusion_row = object_row(object_id=TARGET_GUID, name="Included", object_type="Sound")
    before = {"inclusions": [{"object": {"id": TARGET_GUID}, "filter": ["structures", "media"]}]}
    base_arguments = {
        "soundbank": {"kind": "id", "value": soundbank_id},
        "inclusions": [{"object": {"kind": "id", "value": TARGET_GUID}, "filters": ["events"]}],
    }
    upsert = prepare_operation(
        parse_operation_request(
            request("soundbank.setInclusions", {**base_arguments, "mode": "add"})
        ),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [{"return": [soundbank_row]}, {"return": [inclusion_row]}],
                "ak.wwise.core.soundbank.getInclusions": [before],
            }
        ),
    ).as_dict()
    assert upsert["verification_plan"]["expected"] == [
        {"object": TARGET_GUID.casefold(), "filters": ["events"]}
    ]

    with pytest.raises(OperationContractError) as mismatched_remove:
        prepare_operation(
            parse_operation_request(
                request("soundbank.setInclusions", {**base_arguments, "mode": "remove"})
            ),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [{"return": [soundbank_row]}, {"return": [inclusion_row]}],
                    "ak.wwise.core.soundbank.getInclusions": [before],
                }
            ),
        )
    assert mismatched_remove.value.error_code == "REMOVE_PRECONDITION_MISMATCH"

    exact_remove_arguments = {
        **base_arguments,
        "mode": "remove",
        "inclusions": [
            {
                "object": {"kind": "id", "value": TARGET_GUID},
                "filters": ["media", "structures"],
            }
        ],
    }
    removed = prepare_operation(
        parse_operation_request(request("soundbank.setInclusions", exact_remove_arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [{"return": [soundbank_row]}, {"return": [inclusion_row]}],
                "ak.wwise.core.soundbank.getInclusions": [before],
            }
        ),
    ).as_dict()
    assert removed["verification_plan"]["expected"] == []


@pytest.mark.parametrize(
    ("operation", "before_rows", "after_rows", "should_exist"),
    [
        ("switchContainer.addAssignment", [], "pair", True),
        ("switchContainer.removeAssignment", "pair", [], False),
    ],
)
def test_switch_assignment_validates_relationship_prestate_drift_and_exact_post_pair(
    operation: str,
    before_rows: Any,
    after_rows: Any,
    should_exist: bool,
) -> None:
    container_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    child_id = "{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}"
    state_id = "{cccccccc-cccc-cccc-cccc-cccccccccccc}"
    group_id = "{dddddddd-dddd-dddd-dddd-dddddddddddd}"
    container_row = object_row(
        object_id=container_id,
        name="ClosedSwitch",
        object_type="SwitchContainer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\ClosedSwitch",
        parent=PARENT_GUID,
    )
    child_row = object_row(
        object_id=child_id,
        name="Child",
        object_type="Sound",
        path=container_row["path"] + r"\Child",
        parent=container_id,
    )
    group_row = object_row(
        object_id=group_id,
        name="ClosedGroup",
        object_type="SwitchGroup",
        path=r"\Switches\Default Work Unit\ClosedGroup",
        parent="{switches-workunit}",
    )
    state_row = object_row(
        object_id=state_id,
        name="ClosedState",
        object_type="Switch",
        path=group_row["path"] + r"\ClosedState",
        parent=group_id,
    )
    pair = {"child": {"id": child_id}, "stateOrSwitch": {"id": state_id}}
    before = [pair] if before_rows == "pair" else before_rows
    after = [pair] if after_rows == "pair" else after_rows
    reference_row = {"id": container_id, "path": container_row["path"], "SwitchGroupOrStateGroup": {"id": group_id}}
    arguments = {
        "switch_container": {"kind": "id", "value": container_id},
        "child": {"kind": "id", "value": child_id},
        "state_or_switch": {"kind": "id", "value": state_id},
    }
    prepared = prepare_operation(
        parse_operation_request(request(operation, arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [container_row]},
                    {"return": [child_row]},
                    {"return": [state_row]},
                    {"return": [reference_row]},
                    {"return": [group_row]},
                ],
                "ak.wwise.core.switchContainer.getAssignments": [{"return": before}],
            }
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"] == {"child": child_id, "stateOrSwitch": state_id}
    assert prepared["verification_plan"] == {
        "kind": "switch-assignment-pair",
        "switch_container_id": container_id,
        "child_id": child_id,
        "state_or_switch_id": state_id,
        "should_exist": should_exist,
        "reference_id": group_id,
        "group_type": "SwitchGroup",
        "state_or_switch_type": "Switch",
        "expected_assignments": (
            [{"child": child_id.casefold(), "stateOrSwitch": state_id.casefold()}]
            if should_exist
            else []
        ),
    }
    assert prepared["cleanup"]["automatic_retry"] is False

    guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [container_row]},
                    {"return": [child_row]},
                    {"return": [state_row]},
                    {"return": [group_row]},
                    {"return": [reference_row]},
                ],
                "ak.wwise.core.switchContainer.getAssignments": [{"return": before}],
            }
        ),
    )
    assert guard["status"] == "valid"
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {
                "ak.wwise.core.switchContainer.getAssignments": [{"return": after}],
                "ak.wwise.core.object.get": [
                    {"return": [reference_row | {"type": "SwitchContainer"}]},
                    {"return": [child_row]},
                    {"return": [group_row]},
                    {"return": [state_row]},
                ],
            }
        ),
    )
    assert verified.status == "verified"
    assert any(item["name"] == ("assignment pair is present" if should_exist else "assignment pair is absent") for item in verified.assertions)
    assert any(
        item["name"] == "complete Switch Container assignment state matches expected post-state"
        for item in verified.assertions
    )

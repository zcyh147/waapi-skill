from __future__ import annotations

import base64
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import SemanticValidationError  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
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
SOUND_TYPE_RESULT = {
    "return": [
        {
            "classId": 65552,
            "name": "Sound",
            "type": "WObject",
        }
    ]
}


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


def project_info_row(project_root: Path) -> dict[str, Any]:
    project_root.mkdir(parents=True, exist_ok=True)
    originals = project_root / "Originals"
    originals.mkdir(parents=True, exist_ok=True)
    return {
        "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "name": "SampleProject",
        "displayTitle": "SampleProject",
        "path": str(project_root / "SampleProject.wproj"),
        "isDirty": False,
        "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "currentPlatformId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "originals": str(originals),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
            "commands": str(project_root / "Commands"),
            "properties": str(project_root / "Properties"),
        },
        "platforms": [
            {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks/Mac"),
                "copiedMediaPath": str(project_root / "GeneratedSoundBanks/Mac/Media"),
            }
        ],
        "languages": [
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "SFX",
                "shortId": 1,
            }
        ],
        "defaultConversion": {
            "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
            "name": "Default",
        },
    }


def test_operation_catalog_is_truthful_about_closed_and_boundary_operations() -> None:
    specs = {spec.name: spec.as_dict() for spec in list_operation_specs()}

    assert len(specs) == 34
    assert specs["ui.commands.execute"]["uri"] == (
        "ak.wwise.ui.commands.execute"
    )
    assert specs["ui.commands.register"]["required_arguments"] == ["commands"]
    assert specs["ui.commands.unregister"]["required_arguments"] == []
    assert set(specs["ui.commands.unregister"]["optional_arguments"]) == {
        "acknowledgement",
        "command_ids",
        "commands",
        "source_authority",
    }
    assert specs["waapi.undoGroup"]["implemented"] is True
    assert specs["waapi.undoGroup"]["family"] == "same-connection-compound"
    assert specs["waapi.undoGroup"]["required_arguments"] == ["display_name", "calls"]
    assert specs["waapi.undoGroup"]["argument_contract"]["properties"]["calls"]["maxItems"] == 32
    assert specs["waapi.call"]["implemented"] is True
    assert specs["waapi.call"]["uri"] == "manifest://waapi.call"
    assert specs["waapi.call"]["family"] == "public-execution-contract"
    assert specs["waapi.call"]["supported_versions"] == [
        "2021.1",
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    assert specs["waapi.call"]["argument_contract"] == {
        "type": "object",
        "required": ["api"],
        "optional": ["args", "options", "io_root"],
        "additionalProperties": False,
        "properties": {
            "api": {
                "type": "string",
                "pattern": r"^ak\.",
                "description": (
                    "Reflected WAAPI URI at $.arguments.api; sibling of args, "
                    "options, and io_root."
                ),
            },
            "args": {
                "type": "object",
                "description": (
                    "Only the reflected API arguments at $.arguments.args; "
                    "never place io_root or operation-envelope fields here."
                ),
            },
            "options": {
                "type": "object",
                "description": (
                    "Reflected API options at $.arguments.options; use an empty "
                    "object when the request needs no options."
                ),
            },
            "io_root": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Absolute isolated I/O root at $.arguments.io_root; it is a "
                    "sibling of api, args, and options and must never be nested "
                    "inside args."
                ),
            },
        },
    }
    assert "execution is bound to immutable preview authorization" in specs["waapi.call"]["constraints"]
    assert specs["object.create"]["implemented"] is True
    object_create_type = specs["object.create"]["argument_contract"]["properties"]["type"]
    child_type = specs["object.create"]["argument_contract"]["properties"]["children"]["items"]["properties"]["type"]
    for schema in (object_create_type, child_type):
        assert schema["description"] == (
            "Exact Wwise metadata token. Natural mappings: Actor Mixer -> ActorMixer; "
            "Random Container / 随机容器 -> RandomSequenceContainer (never RandomContainer); "
            "Blend Container / 混合容器 -> BlendContainer; Sound -> Sound."
        )
    assert specs["object.create"]["summary"].startswith("Create or merge one bounded recursive object tree")
    assert any(
        "remains an object.create request" in item
        for item in specs["object.create"]["constraints"]
    )
    assert specs["audio.import"]["implemented"] is True
    assert "identity_contract" not in specs["audio.import"]
    import_items = specs["audio.import"]["argument_contract"]["properties"]["imports"]["items"]
    assert import_items["required"] == []
    assert {
        "audio_file",
        "audio_file_base64",
        "dialogue_event",
        "import_location",
        "properties",
        "references",
        "switch_assignment",
    } <= set(import_items["optional"])
    assert import_items["additionalProperties"] is False
    assert specs["audio.import"]["argument_contract"][
        "maximumEffectiveAudioFileBase64EncodedCharacters"
    ] == 256 * 1024
    assert specs["object.set"]["argument_contract"][
        "maximumCanonicalRequestBytes"
    ] == 256 * 1024
    for operation in ("audio.import", "audio.importTabDelimited"):
        assert "auto_check_out_to_source_control" in specs[operation]["optional_arguments"]
        auto_check_out = specs[operation]["argument_contract"]["properties"][
            "auto_check_out_to_source_control"
        ]
        assert auto_check_out["type"] == "boolean"
        assert auto_check_out["default"] is False
        assert auto_check_out["supported_versions"] == ["2023.1", "2024.1", "2025.1"]
        assert any(
            "explicit use on 2021.1/2022.1 fails before connection" in constraint
            for constraint in specs[operation]["constraints"]
        )
    delete_auto_check_out = specs["object.delete"]["argument_contract"][
        "properties"
    ]["auto_check_out_to_source_control"]
    assert specs["object.delete"]["optional_arguments"] == [
        "auto_check_out_to_source_control"
    ]
    assert delete_auto_check_out["type"] == "boolean"
    assert delete_auto_check_out["default"] is False
    assert delete_auto_check_out["supported_versions"] == [
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    reference_target = specs["object.setReference"]["argument_contract"][
        "properties"
    ]["target"]
    assert reference_target["oneOf"][1]["type"] == "null"
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
    assert specs["object.set"]["implemented"] is True
    assert specs["object.set"]["supported_versions"] == ["2022.1", "2023.1", "2024.1", "2025.1"]
    create_plugin = specs["object.createPlugin"]
    assert create_plugin["implemented"] is True
    assert create_plugin["supported_versions"] == [
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    assert create_plugin["identity_contract"]["argument_fields"] == ["target"]
    plugin_schema = create_plugin["argument_contract"]["properties"]["plugin"]
    assert plugin_schema["required"] == ["kind", "name", "class_id"]
    assert plugin_schema["additionalProperties"] is False
    assert plugin_schema["properties"]["class_id"]["maximum"] == 4_294_967_295
    assert plugin_schema["properties"]["properties"]["maxItems"] == 32
    assert "language" in plugin_schema["optional"]
    assert plugin_schema["properties"]["language"]["minLength"] == 1
    assert any(
        "never guessed" in item
        for item in create_plugin["constraints"]
    )
    object_set_rows = specs["object.set"]["argument_contract"]["properties"]["objects"]
    object_set_children = object_set_rows["items"]["properties"]["children"]
    object_set_conflict = specs["object.set"]["argument_contract"]["properties"]["on_name_conflict"]
    assert "Each existing object" in object_set_rows["description"]
    assert "Only genuinely new direct children" in object_set_children["description"]
    assert "never to existing objects[] targets" in object_set_conflict["description"]
    assert "Use fail for children requested as new or absent" in object_set_conflict["description"]
    assert any(
        "separate objects[] target" in item
        for item in specs["object.set"]["constraints"]
    )
    assert any(
        "existing objects[] targets do not imply merge" in item
        for item in specs["object.set"]["constraints"]
    )
    assert specs["object.setLinked"]["supported_versions"] == ["2023.1", "2024.1", "2025.1"]
    assert specs["object.setRTPC"]["supported_versions"] == ["2022.1", "2023.1", "2024.1", "2025.1"]
    assert specs["object.setRTPC"]["argument_contract"]["properties"]["mode"]["enum"] == [
        "add",
        "add_or_replace",
    ]
    assert specs["object.set"]["argument_contract"]["properties"]["objects"]["items"]["properties"][
        "platform"
    ]["minLength"] == 1
    assert "returned copy GUID" in specs["object.copy"]["boundary"]
    assert specs["object.setProperty"]["identity_contract"]["caller_rows_allowed"] is False
    assert specs["soundbank.convertExternalSources"]["supported_versions"] == [
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    generate = specs["soundbank.generate"]
    assert generate["supported_versions"] == [
        "2021.1",
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    assert "attested_project_layout" not in generate["optional_arguments"]
    assert "attested_project_layout" not in generate["argument_contract"]["properties"]
    assert any("filePath" in constraint and "WPROJ" in constraint for constraint in generate["constraints"])


def test_operation_catalog_exposes_business_intent_selection_guidance() -> None:
    specs = {spec.name: spec.as_dict() for spec in list_operation_specs()}
    guided_operations = {
        "waapi.undoGroup",
        "audio.import",
        "audio.importTabDelimited",
        "object.create",
        "object.delete",
        "object.setName",
        "object.setNotes",
        "object.setProperty",
        "object.setReference",
        "object.setLinked",
        "object.createPlugin",
        "object.setRTPC",
        "object.set",
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "ui.commands.execute",
        "ui.captureScreen",
        "soundbank.setInclusions",
        "soundbank.generate",
        "soundbank.convertExternalSources",
        "soundbank.processDefinitionFiles",
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    }

    for name in guided_operations:
        guidance = specs[name]["selection_guidance"]
        assert set(guidance) == {
            "principle",
            "use_when",
            "avoid_when",
            "preferred_over",
            "choose_instead",
        }
        assert guidance["use_when"]
        assert all(isinstance(item, str) and item for item in guidance["use_when"])
        for relation in ("preferred_over", "choose_instead"):
            assert all(set(item) == {"target", "when"} for item in guidance[relation])

    direct_import = specs["audio.import"]["selection_guidance"]
    assert any("one row or a batch" in item for item in direct_import["use_when"])
    assert {
        item["target"] for item in direct_import["preferred_over"]
    } >= {"audio.importTabDelimited", "object.create", "object.set"}
    assert any(
        "invent an intermediate TSV" in item["when"]
        for item in direct_import["preferred_over"]
    )

    tab_import = specs["audio.importTabDelimited"]["selection_guidance"]
    assert any("existing absolute TSV" in item for item in tab_import["use_when"])
    assert any("many rows" in item for item in tab_import["avoid_when"])
    assert {item["target"] for item in tab_import["choose_instead"]} >= {
        "audio.import",
        "waapi.call",
    }

    object_set = specs["object.set"]["selection_guidance"]
    assert {
        item["target"] for item in object_set["choose_instead"]
    } >= {
        "object.create",
        "audio.import",
        "object.createPlugin",
        "object.setRTPC",
        "object.setLinked",
    }
    assert any(
        item["target"] == "audio.import"
        and "subordinate" in item["when"]
        for item in object_set["preferred_over"]
    )

    inclusions = specs["soundbank.setInclusions"]["selection_guidance"]
    definitions = specs["soundbank.processDefinitionFiles"]["selection_guidance"]
    assert inclusions["choose_instead"] == [
        {
            "target": "soundbank.processDefinitionFiles",
            "when": "existing caller-owned Definition TSV files are the requested source of truth",
        }
    ]
    assert definitions["choose_instead"][0]["target"] == "soundbank.setInclusions"

    undo_group = specs["waapi.undoGroup"]["selection_guidance"]
    assert any("one Wwise Undo step" in item for item in undo_group["use_when"])
    assert any(
        item["target"] == "the matching dedicated batch operation"
        for item in undo_group["choose_instead"]
    )

    generate = specs["soundbank.generate"]["selection_guidance"]
    assert any("generation-only" in item for item in generate["use_when"])
    assert any(
        item["target"] == "soundbank.setInclusions"
        for item in generate["choose_instead"]
    )

    assert "selection_guidance" not in specs["debug.setAutomationMode"]


@pytest.mark.parametrize("version", ["2021.1", "2022.1"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        (
            "audio.import",
            {
                "imports": [
                    {
                        "object_path": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit\CheckoutTarget"
                        ),
                        "audio_file": "/tmp/checkout.wav",
                    }
                ]
            },
        ),
        (
            "audio.importTabDelimited",
            {
                "import_file": "/tmp/checkout.tsv",
                "import_location": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
                },
                "import_language": "SFX",
            },
        ),
    ],
)
def test_import_auto_check_out_fails_at_the_old_version_request_boundary(
    operation: str,
    arguments: Mapping[str, Any],
    enabled: bool,
    version: str,
) -> None:
    payload_arguments = {
        **dict(arguments),
        "auto_check_out_to_source_control": enabled,
    }

    with pytest.raises(OperationContractError) as caught:
        parse_operation_request(
            request(operation, payload_arguments, version=version)
        )

    assert caught.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"
    assert caught.value.details["version"] == version
    assert caught.value.details["supported_versions"] == [
        "2023.1",
        "2024.1",
        "2025.1",
    ]


@pytest.mark.parametrize("value", [None, 0, "false"])
def test_import_auto_check_out_rejects_non_boolean_request_values(value: Any) -> None:
    with pytest.raises(OperationContractError) as caught:
        parse_operation_request(
            request(
                "audio.import",
                {
                    "imports": [
                        {
                            "object_path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\CheckoutTarget"
                            ),
                            "audio_file": "/tmp/checkout.wav",
                        }
                    ],
                    "auto_check_out_to_source_control": value,
                },
                version="2023.1",
            )
        )

    assert caught.value.error_code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("version", "cancel_args"),
    [
        ("2021.1", {}),
        ("2022.1", {}),
        ("2023.1", {"undo": True}),
        ("2024.1", {"undo": True}),
        ("2025.1", {"undo": True}),
    ],
)
def test_undo_group_builds_one_exact_versioned_immutable_plan(
    version: str,
    cancel_args: Mapping[str, Any],
) -> None:
    parsed = parse_operation_request(
        request(
            "waapi.undoGroup",
            {
                "display_name": "Batch edit",
                "calls": [
                    {
                        "api": "ak.wwise.core.object.setNotes",
                        "args": {"object": GUID, "value": "after"},
                    }
                ],
            },
            version=version,
        )
    )
    prepared = prepare_operation(parsed, read_call=lambda *_: {}).as_dict()
    plan = prepared["pre_state"]["execution_plan"]

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.undo.beginGroup",
        "args": {},
        "options": {},
    }
    assert plan["begin"]["uri"] == "ak.wwise.core.undo.beginGroup"
    assert plan["calls"][0]["api"] == "ak.wwise.core.object.setNotes"
    assert plan["end"]["args"] == {"displayName": "Batch edit"}
    assert plan["cancel"]["args"] == cancel_args
    assert plan["same_connection_required"] is True
    assert plan["automatic_retry"] is False


def test_undo_group_rejects_independent_members_version_drift_and_large_requests() -> None:
    with pytest.raises(OperationContractError) as independent:
        parse_operation_request(
            request(
                "waapi.call",
                {"api": "ak.wwise.core.undo.beginGroup", "args": {}, "options": {}},
            )
        )
    assert independent.value.error_code == "UNDO_GROUP_COMPOSITE_REQUIRED"
    assert independent.value.details["required_operation"] == "waapi.undoGroup"

    with pytest.raises(OperationContractError) as version_drift:
        parse_operation_request(
            request(
                "waapi.undoGroup",
                {
                    "display_name": "Not in 2022",
                    "calls": [
                        {
                            "api": "ak.wwise.core.object.setStateGroups",
                            "args": {},
                        }
                    ],
                },
                version="2022.1",
            )
        )
    assert version_drift.value.error_code == "UNDO_GROUP_INNER_NOT_ALLOWED"

    with pytest.raises(OperationContractError) as oversized:
        parse_operation_request(
            request(
                "waapi.undoGroup",
                {
                    "display_name": "Oversized",
                    "calls": [
                        {
                            "api": "ak.wwise.core.object.setNotes",
                            "args": {"object": GUID, "value": "x" * (129 * 1024)},
                        }
                    ],
                },
            )
        )
    assert oversized.value.error_code == "UNDO_GROUP_REQUEST_TOO_LARGE"


def test_undo_group_version_allowlist_is_exact_and_only_grows_at_reviewed_boundaries() -> None:
    assert {version: len(uris) for version, uris in UNDO_GROUP_INNER_URIS_BY_VERSION.items()} == {
        "2021.1": 9,
        "2022.1": 11,
        "2023.1": 14,
        "2024.1": 19,
        "2025.1": 19,
    }
    assert "ak.wwise.core.object.pasteProperties" not in UNDO_GROUP_INNER_URIS_BY_VERSION["2021.1"]
    assert "ak.wwise.core.object.pasteProperties" in UNDO_GROUP_INNER_URIS_BY_VERSION["2022.1"]
    assert "ak.wwise.core.object.setStateGroups" not in UNDO_GROUP_INNER_URIS_BY_VERSION["2022.1"]
    assert "ak.wwise.core.object.setStateGroups" in UNDO_GROUP_INNER_URIS_BY_VERSION["2023.1"]
    assert "ak.wwise.core.blendContainer.addTrack" not in UNDO_GROUP_INNER_URIS_BY_VERSION["2023.1"]
    assert "ak.wwise.core.blendContainer.addTrack" in UNDO_GROUP_INNER_URIS_BY_VERSION["2024.1"]
    assert UNDO_GROUP_INNER_URIS_BY_VERSION["2024.1"] == UNDO_GROUP_INNER_URIS_BY_VERSION["2025.1"]


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


@pytest.mark.parametrize(
    ("source_arguments", "field"),
    (
        (
            {
                "source-file": [
                    "/tmp/case/first.wsources",
                    "/tmp/case/second.wsources",
                ]
            },
            "source-file",
        ),
        (
            {
                "source-by-platform": [
                    ["Windows", "/tmp/case/first.wsources"],
                    ["Windows", "/tmp/case/second.wsources"],
                ]
            },
            "source-by-platform",
        ),
    ),
)
def test_2022_cli_external_source_rejects_proven_partial_multi_manifest_shapes(
    source_arguments: Mapping[str, Any],
    field: str,
) -> None:
    with pytest.raises(
        OperationContractError,
        match="partial-success shape",
    ) as boundary:
        parse_operation_request(
            request(
                "waapi.call",
                {
                    "api": "ak.wwise.cli.convertExternalSource",
                    "args": {
                        "project": "/tmp/case/SampleProject.wproj",
                        "platform": ["Windows"],
                        **dict(source_arguments),
                        "output": ["Windows", "/tmp/case/output"],
                    },
                    "options": {},
                    "io_root": "/tmp/case",
                },
            )
        )

    assert boundary.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"
    assert boundary.value.details["field"] == field
    assert boundary.value.details["supported_shape"] == (
        "one .wsources file per platform per transaction"
    )
    assert "caller-prepared union" in boundary.value.details["next_step"]


def audio_convert_request(
    *,
    version: str = "2024.1",
    objects: Any = None,
    platforms: Any = None,
    languages: Any = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "objects": (
            [
                r"\Actor-Mixer Hierarchy\Default Work Unit\SFX_B",
                r"\Actor-Mixer Hierarchy\Default Work Unit\SFX_A",
            ]
            if objects is None
            else objects
        ),
        "platforms": ["Mac", "Windows"] if platforms is None else platforms,
        "languages": ["SFX"] if languages is None else languages,
    }
    return request(
        "waapi.call",
        {
            "api": "ak.wwise.core.audio.convert",
            "args": args,
            "options": {},
            "io_root": "/tmp/waapi-audio-convert",
        },
        version=version,
    )


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_audio_convert_preserves_exact_non_empty_string_array_values_and_order(
    version: str,
) -> None:
    payload = audio_convert_request(version=version)

    parsed = parse_operation_request(payload, expected_version=version)

    assert parsed.arguments["args"] == payload["arguments"]["args"]


@pytest.mark.parametrize(
    ("field", "value", "invalid_index"),
    (
        ("objects", [], None),
        ("platforms", [], None),
        ("languages", [], None),
        ("objects", [{"object": r"\Actor-Mixer Hierarchy\Default Work Unit\SFX_A"}], 0),
        ("platforms", [""], 0),
        ("platforms", ["   "], 0),
        ("languages", [False], 0),
        ("languages", ["SFX", 1], 1),
    ),
)
@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_audio_convert_rejects_non_product_array_shapes(
    field: str,
    value: Any,
    invalid_index: int | None,
    version: str,
) -> None:
    kwargs = {
        "objects": None,
        "platforms": None,
        "languages": None,
        field: value,
    }

    with pytest.raises(OperationContractError) as boundary:
        parse_operation_request(
            audio_convert_request(version=version, **kwargs),
            expected_version=version,
        )

    assert boundary.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"
    assert boundary.value.details["field"] == field
    assert boundary.value.details["required_shape"] == (
        "non-empty ordered array of non-empty strings"
    )
    if invalid_index is not None:
        assert boundary.value.details["invalid_index"] == invalid_index


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_audio_convert_missing_languages_fails_reflected_required_field(
    version: str,
) -> None:
    payload = audio_convert_request(version=version)
    del payload["arguments"]["args"]["languages"]

    with pytest.raises(
        SemanticValidationError,
        match="missing required args: languages",
    ):
        parse_operation_request(payload, expected_version=version)


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
                },
                {"return": []},
                {"return": []},
            ],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 1, "name": "ActorMixer", "type": "ActorMixer"}]}
            ],
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
    assert prepared["verification_plan"]["kind"] == "object-create-graph"
    assert prepared["verification_plan"]["nodes"][0]["canonical_type"] == "ActorMixer"
    assert prepared["raw_dispatch_allowed"] is False
    assert reader.calls[0][1] == {"from": {"path": [parent_path]}}


def test_create_rename_verification_requires_the_full_collision_snapshot_unchanged() -> None:
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Sandbox"
    collision_path = parent_path + r"\CreatedByRegistry"
    collision_id = "{55555555-5555-5555-5555-555555555555}"
    created_id = "{66666666-6666-6666-6666-666666666666}"
    parent = object_row(
        object_id=PARENT_GUID,
        name="WAAPI Sandbox",
        object_type="WorkUnit",
        path=parent_path,
        parent="{hierarchy}",
    )
    collision = object_row(
        object_id=collision_id,
        name="CreatedByRegistry",
        object_type="ActorMixer",
        path=collision_path,
        parent=PARENT_GUID,
        notes="keep-me",
    )
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "object.create",
                {
                    "parent": {"kind": "id", "value": PARENT_GUID},
                    "type": "ActorMixer",
                    "name": "CreatedByRegistry",
                    "on_name_conflict": "rename",
                },
            )
        ),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [parent]},
                    {"return": [collision]},
                    {"return": [collision]},
                ],
                "ak.wwise.core.object.getTypes": [
                    {"return": [{"classId": 1, "name": "ActorMixer", "type": "ActorMixer"}]}
                ],
            }
        ),
    ).as_dict()
    created = object_row(
        object_id=created_id,
        name="CreatedByRegistry_1",
        object_type="ActorMixer",
        path=parent_path + r"\CreatedByRegistry_1",
        parent=PARENT_GUID,
    )
    changed_collision = {**collision, "notes": "unexpected-change"}

    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {"id": created_id, "name": "CreatedByRegistry_1"}},
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [created]},
                    {"return": [changed_collision]},
                ]
            }
        ),
    )

    unchanged = next(
        item
        for item in verified.assertions
        if item["name"] == "rename collision full identity snapshot is unchanged"
    )
    assert unchanged["passed"] is False
    assert verified.status == "verification_failed"


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


def test_reference_can_be_explicitly_cleared_and_null_is_verified() -> None:
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {
                    "return": [
                        {
                            "id": GUID,
                            "path": object_row()["path"],
                            "OutputBus": {"id": TARGET_GUID},
                        }
                    ]
                },
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "OutputBus",
                    "type": "Reference",
                    "supports": {"reference": True},
                    "restriction": {
                        "type": "reference",
                        "restrictions": [{"type": ["Bus"]}],
                    },
                }
            ],
        }
    )
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "object.setReference",
                {
                    "object": {"kind": "id", "value": GUID},
                    "reference": "OutputBus",
                    "target": None,
                },
            )
        ),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"]["args"] == {
        "object": GUID,
        "reference": "OutputBus",
        "value": None,
    }
    assert "target" not in prepared["resolved_roles"]
    assert prepared["verification_plan"]["expected_clear"] is True
    assert prepared["verification_plan"]["expected_target_id"] is None

    verified = verify_prepared_operation(
        prepared,
        execution_result={},
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [{"id": GUID, "OutputBus": None}]}
                ]
            }
        ),
    )
    assert verified.status == "verified"
    assert next(
        item for item in verified.assertions if item["name"] == "reference is cleared"
    )["passed"] is True


def test_reference_clear_rejects_live_not_null_restriction() -> None:
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {
                    "return": [
                        {
                            "id": GUID,
                            "path": object_row()["path"],
                            "OutputBus": {"id": TARGET_GUID},
                        }
                    ]
                },
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "OutputBus",
                    "type": "Reference",
                    "supports": {"reference": True},
                    "restriction": {
                        "type": "reference",
                        "restrictions": ["notNull"],
                    },
                }
            ],
        }
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "object.setReference",
                    {
                        "object": {"kind": "id", "value": GUID},
                        "reference": "OutputBus",
                        "target": None,
                    },
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "REFERENCE_NOT_CLEARABLE"


@pytest.mark.parametrize("enabled", (False, True))
def test_object_delete_exposes_versioned_auto_check_out(enabled: bool) -> None:
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "object.delete",
                {
                    "object": {"kind": "id", "value": GUID},
                    "auto_check_out_to_source_control": enabled,
                },
                version="2023.1",
            )
        ),
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": [object_row()]}]}
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"] == {
        "object": GUID,
        "autoCheckOutToSourceControl": enabled,
    }
    assert prepared["pre_state"]["source_control_policy"] == {
        "auto_check_out_to_source_control": enabled,
        "supported": True,
        "dispatched": True,
    }


def test_object_delete_defaults_auto_check_out_false_in_new_lanes() -> None:
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "object.delete",
                {"object": {"kind": "id", "value": GUID}},
                version="2025.1",
            )
        ),
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": [object_row()]}]}
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"]["autoCheckOutToSourceControl"] is False


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_object_delete_rejects_auto_check_out_in_old_lanes(version: str) -> None:
    with pytest.raises(OperationContractError) as rejected:
        parse_operation_request(
            request(
                "object.delete",
                {
                    "object": {"kind": "id", "value": GUID},
                    "auto_check_out_to_source_control": False,
                },
                version=version,
            )
        )

    assert rejected.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"


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
            "restrictions": [
                {"type": ["Switch Group", "State Group"], "sharedOnlyTypes": []},
                "notNull",
            ],
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


@pytest.mark.parametrize(
    ("restriction_entry", "error_code"),
    (
        ("playable", "CONSTRAINED_REFERENCE_BOUNDARY"),
        ("unknownFlag", "INVALID_METADATA"),
        (7, "INVALID_METADATA"),
    ),
)
def test_reference_restriction_flags_fail_closed_when_not_provable(
    restriction_entry: object,
    error_code: str,
) -> None:
    source_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    target_id = "{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}"
    arguments = {
        "object": {"kind": "id", "value": source_id},
        "reference": "OutputBus",
        "target": {"kind": "id", "value": target_id},
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        object_row(
                            object_id=source_id,
                            name="Container",
                            object_type="ActorMixer",
                        )
                    ]
                },
                {"return": [{"id": source_id, "OutputBus": None}]},
                {
                    "return": [
                        object_row(
                            object_id=target_id,
                            name="VO Bus",
                            object_type="Bus",
                            path=r"\Master-Mixer Hierarchy\Default Work Unit\VO Bus",
                        )
                    ]
                },
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "OutputBus",
                    "type": "Reference",
                    "supports": {"reference": True},
                    "restriction": {
                        "type": "reference",
                        "restrictions": [restriction_entry],
                    },
                }
            ],
        }
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(request("object.setReference", arguments)),
            read_call=reader,
        )

    assert rejected.value.error_code == error_code


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
    project_root = tmp_path / "SampleProject"
    project_info = project_info_row(project_root)
    copied_file = project_root / "Originals" / "SFX" / "source.wav"
    copied_file.parent.mkdir(parents=True)
    copied_file.write_bytes(audio_file.read_bytes())
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
                ],
                "auto_check_out_to_source_control": True,
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
                ],
                "ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT],
                "ak.wwise.core.getProjectInfo": [project_info],
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
            "autoCheckOutToSourceControl": True,
        },
        "options": {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "parent",
                "notes",
                "activeSource",
                "originalFilePath",
                "sound:originalWavFilePath",
                "audioSource:language",
            ]
        },
    }
    assert prepared["semantic_preview"]["envelope"]["metadata"][
        "source_control_policy"
    ] == {
        "auto_add_to_source_control": False,
        "auto_check_out_to_source_control": True,
        "auto_check_out_to_source_control_supported": True,
        "auto_check_out_to_source_control_dispatched": True,
    }
    closed_plan = prepared["pre_state"]["closed_import_plan"]
    assert closed_plan["file_proofs"][0]["size"] == audio_file.stat().st_size
    assert len(closed_plan["file_proofs"][0]["sha256"]) == 64
    assert prepared["cleanup"]["automatic_retry"] is False

    created_id = "{44444444-4444-4444-4444-444444444444}"
    created_row = object_row(
        object_id=created_id,
        name="Imported",
        object_type="Sound",
        path=target_path,
        parent=PARENT_GUID,
        notes="closed import",
        originalFilePath=str(copied_file.resolve()),
        originalRelativeFilePath="SFX/source.wav",
    )
    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "log": [],
                "files": [str(copied_file.resolve())],
                "objects": [created_row],
            }
        },
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [created_row]}]}),
    )
    assert verified.status == "verified"
    assert {item["name"] for item in verified.assertions} >= {
        "closed import result has the exact versioned shape",
        "closed import log entries are well formed",
        "closed import log contains no error",
        "import target 0 is returned exactly once",
        "import target 0 exact path resolves once",
        "import target 0 exact live path matches",
        "import target 0 notes match exactly",
        "import target 0 copied original WAV hash matches the source",
    }

    audio_file.write_bytes(b"changed after preview")
    guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [parent_row]},
                    {"return": []},
                ],
                "ak.wwise.core.getProjectInfo": [project_info],
            }
        ),
    )
    assert guard["status"] == "repreview_required"
    assert any(item["name"] == "file_proofs[0] unchanged since preview" and not item["passed"] for item in guard["assertions"])


def test_audio_import_materializes_defaults_base64_properties_references_and_row_location(
    tmp_path: Path,
) -> None:
    project_info = project_info_row(tmp_path / "SampleProject")
    import_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Imports"
    target_path = import_path + r"\Inline"
    import_parent = object_row(
        object_id=PARENT_GUID,
        name="Imports",
        object_type="ActorMixer",
        path=import_path,
        parent="{actor-root}",
    )
    output_bus = object_row(
        object_id=TARGET_GUID,
        name="Master Audio Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
        parent="{master-root}",
    )
    inline_wav = b"RIFF\x04\x00\x00\x00WAVE"
    inline_source = "SFX/inline.wav|" + base64.b64encode(inline_wav).decode("ascii")
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [import_parent]},
                {"return": [output_bus]},
                {"return": [import_parent]},
                {"return": []},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -200.0, "max": 200.0},
                },
                {
                    "name": "OutputBus",
                    "type": "Reference",
                    "restriction": {
                        "type": "reference",
                        "restrictions": [{"type": ["Bus"]}],
                    },
                },
            ],
            "ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT],
            "ak.wwise.core.getProjectInfo": [project_info],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "audio.import",
                {
                    "defaults": {
                        "object_type": "Sound",
                        "properties": [{"name": "Volume", "value": -12.0}],
                        "references": [
                            {
                                "name": "OutputBus",
                                "target": {"kind": "id", "value": TARGET_GUID},
                            }
                        ],
                    },
                    "imports": [
                        {
                            "object_path": r"<Sound>Inline",
                            "import_location": {
                                "kind": "path",
                                "value": import_path,
                            },
                            "audio_file_base64": inline_source,
                            # Per-row values replace same-token defaults.
                            "properties": [{"name": "Volume", "value": -6.0}],
                        }
                    ],
                    "auto_add_to_source_control": True,
                },
            )
        ),
        read_call=reader,
    ).as_dict()

    dispatch = prepared["dispatch"]
    assert dispatch["uri"] == "ak.wwise.core.audio.import"
    assert dispatch["args"]["autoAddToSourceControl"] is True
    assert dispatch["args"]["imports"] == [
        {
            "objectPath": r"<Sound>Inline",
            "importLocation": import_path,
            "audioFileBase64": (
                "SFX\\inline.wav|" + base64.b64encode(inline_wav).decode("ascii")
            ),
            "objectType": "Sound",
            "@Volume": -6.0,
            "@OutputBus": TARGET_GUID,
        }
    ]
    assert "@Volume" in dispatch["options"]["return"]
    assert "@OutputBus" in dispatch["options"]["return"]
    target = prepared["verification_plan"]["targets"][0]
    assert target["canonical_target_path"] == target_path
    assert target["metadata_object_type"] == "Sound"
    assert target["metadata_class_id"] == 65552
    assert target["validated_properties"] == [
        {
            "name": "Volume",
            "value": -6.0,
            "metadata_type": "Real32",
            "source": "request",
        }
    ]
    assert target["validated_references"] == [
        {
            "name": "OutputBus",
            "target_id": TARGET_GUID,
            "source": "request",
        }
    ]
    assert (
        prepared["resolved_roles"]["imports[0].import_location"]["object"]
        == PARENT_GUID
    )
    assert (
        prepared["resolved_roles"]["targets[0].references[0].target"]["object"]
        == TARGET_GUID
    )
    metadata_calls = [
        (args, options)
        for uri, args, options in reader.calls
        if uri == "ak.wwise.core.object.getPropertyInfo"
    ]
    assert metadata_calls == [
        ({"property": "Volume", "classId": 65552}, {}),
        ({"property": "OutputBus", "classId": 65552}, {}),
    ]
    assert [
        (args, options)
        for uri, args, options in reader.calls
        if uri == "ak.wwise.core.object.getTypes"
    ] == [({}, {})]


def test_audio_import_unknown_type_fails_from_live_type_catalog() -> None:
    reader = ScriptedReader(
        {"ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT]}
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "audio.import",
                    {
                        "imports": [
                            {
                                "object_path": (
                                    r"\Actor-Mixer Hierarchy\Default Work Unit"
                                    r"\<ImaginaryType>Closed"
                                ),
                                "object_type": "ImaginaryType",
                            }
                        ]
                    },
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "INVALID_OBJECT_TYPE"
    assert reader.calls == [
        ("ak.wwise.core.object.getTypes", {}, {})
    ]


def test_audio_import_does_not_fallback_to_packaged_type_when_live_host_omits_it() -> None:
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {
                            "classId": 1,
                            "name": "ActorMixer",
                            "type": "WObject",
                        }
                    ]
                }
            ]
        }
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "audio.import",
                    {
                        "imports": [
                            {
                                "object_path": (
                                    r"\Actor-Mixer Hierarchy\Default Work Unit"
                                    r"\<Sound>LiveTypeRequired"
                                ),
                                "object_type": "Sound",
                            }
                        ]
                    },
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "INVALID_OBJECT_TYPE"
    assert reader.calls == [
        ("ak.wwise.core.object.getTypes", {}, {})
    ]


def test_tab_import_validates_dynamic_property_and_reference_columns_before_preview(
    tmp_path: Path,
) -> None:
    import_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Imports"
    import_parent = object_row(
        object_id=PARENT_GUID,
        name="Imports",
        object_type="ActorMixer",
        path=import_path,
        parent="{actor-root}",
    )
    output_bus_path = (
        r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
    )
    output_bus = object_row(
        object_id=TARGET_GUID,
        name="Master Audio Bus",
        object_type="Bus",
        path=output_bus_path,
        parent="{master-root}",
    )
    import_file = tmp_path / "dynamic.tsv"
    import_file.write_text(
        "\t".join(
            (
                "Object Path",
                "Object Type",
                "Property[Volume]",
                "Reference[OutputBus]",
            )
        )
        + "\n"
        + "\t".join(
            (
                r"<Sound>Tabbed",
                "Sound",
                "-9.5",
                output_bus_path,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [import_parent]},
                {"return": [output_bus]},
                {"return": [import_parent]},
                {"return": []},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -200.0, "max": 200.0},
                },
                {
                    "name": "OutputBus",
                    "type": "Reference",
                    "restriction": {
                        "type": "reference",
                        "restrictions": [{"type": ["Bus"]}],
                    },
                },
            ],
            "ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "audio.importTabDelimited",
                {
                    "import_file": str(import_file),
                    "import_location": {"kind": "id", "value": PARENT_GUID},
                    "import_language": "SFX",
                    "auto_add_to_source_control": True,
                },
            )
        ),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.audio.importTabDelimited",
        "args": {
            "importFile": str(import_file.resolve()),
            "importLocation": PARENT_GUID,
            "importLanguage": "SFX",
            "importOperation": "createNew",
            "autoAddToSourceControl": True,
        },
        "options": {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "parent",
                "notes",
                "activeSource",
                "originalFilePath",
                "sound:originalWavFilePath",
                "audioSource:language",
                "@Volume",
                "@OutputBus",
            ]
        },
    }
    target = prepared["verification_plan"]["targets"][0]
    assert target["metadata_class_id"] == 65552
    assert target["validated_properties"] == [
        {
            "name": "Volume",
            "value": -9.5,
            "metadata_type": "Real32",
            "source": "tab",
        }
    ]
    assert target["validated_references"] == [
        {
            "name": "OutputBus",
            "target_id": TARGET_GUID,
            "source": "tab",
        }
    ]
    assert [
        (args, options)
        for uri, args, options in reader.calls
        if uri == "ak.wwise.core.object.getTypes"
    ] == [({}, {})]


def test_tab_import_rejects_duplicate_dynamic_field_before_metadata_read(
    tmp_path: Path,
) -> None:
    import_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Imports"
    import_parent = object_row(
        object_id=PARENT_GUID,
        name="Imports",
        object_type="ActorMixer",
        path=import_path,
        parent="{actor-root}",
    )
    import_file = tmp_path / "duplicate-dynamic.tsv"
    import_file.write_text(
        "Object Path\tObject Type\tProperty[Volume]\t@Volume\n"
        "<Sound>Duplicate\tSound\t-6\t-9\n",
        encoding="utf-8",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [{"return": [import_parent]}],
            "ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT],
        }
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "audio.importTabDelimited",
                    {
                        "import_file": str(import_file),
                        "import_location": {
                            "kind": "path",
                            "value": import_path,
                        },
                        "import_language": "SFX",
                    },
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "DUPLICATE_FIELD"
    assert all(
        uri != "ak.wwise.core.object.getPropertyInfo"
        for uri, _args, _options in reader.calls
    )


def test_tab_import_rejects_value_that_live_property_type_cannot_parse(
    tmp_path: Path,
) -> None:
    import_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Imports"
    import_parent = object_row(
        object_id=PARENT_GUID,
        name="Imports",
        object_type="ActorMixer",
        path=import_path,
        parent="{actor-root}",
    )
    import_file = tmp_path / "bad-property-type.tsv"
    import_file.write_text(
        "Object Path\tObject Type\tProperty[IsLoopingEnabled]\n"
        "<Sound>BadBool\tSound\tnot-a-boolean\n",
        encoding="utf-8",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [{"return": [import_parent]}],
            "ak.wwise.core.object.getPropertyInfo": [
                {"name": "IsLoopingEnabled", "type": "Bool"}
            ],
            "ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT],
        }
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "audio.importTabDelimited",
                    {
                        "import_file": str(import_file),
                        "import_location": {
                            "kind": "path",
                            "value": import_path,
                        },
                        "import_language": "SFX",
                    },
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "INVALID_PROPERTY_VALUE"
    assert reader.calls[-1][0] == "ak.wwise.core.object.getPropertyInfo"
    assert reader.calls[-1][1] == {
        "property": "IsLoopingEnabled",
        "classId": 65552,
    }


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


def test_audio_import_accepts_language_and_originals_subfolder_for_closed_verification() -> None:
    parsed = parse_operation_request(
        request(
            "audio.import",
            {
                "imports": [
                    {
                        "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound Voice>Imported",
                        "audio_file": "/tmp/import.wav",
                        "import_language": "Japanese",
                        "originals_subfolder": "Dialogue/Chapter06",
                    }
                ]
            },
        )
    )

    assert parsed.arguments["imports"][0]["import_language"] == "Japanese"
    assert parsed.arguments["imports"][0]["originals_subfolder"] == "Dialogue/Chapter06"


def test_audio_import_uses_versioned_authoring_roots_for_2025_containers(tmp_path: Any) -> None:
    audio_file = tmp_path / "source.wav"
    audio_file.write_bytes(b"RIFFWAVE")
    project_info = project_info_row(tmp_path / "SampleProject2025")
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
                ],
                "ak.wwise.core.object.getTypes": [SOUND_TYPE_RESULT],
                "ak.wwise.core.getProjectInfo": [project_info],
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


@pytest.mark.parametrize(
    ("api", "arguments", "expected_connected"),
    [
        ("ak.wwise.core.remote.connect", {"host": "127.0.0.1"}, True),
        ("ak.wwise.core.remote.disconnect", {}, False),
    ],
)
def test_public_remote_lifecycle_uses_connection_status_business_readback(
    api: str,
    arguments: Mapping[str, Any],
    expected_connected: bool,
) -> None:
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "waapi.call",
                {"api": api, "args": dict(arguments), "options": {}},
                version="2022.1",
            )
        ),
        read_call=ScriptedReader({}),
    ).as_dict()

    assert prepared["verification_plan"] == {
        "kind": "remote-connection-state",
        "uri": api,
        "version": "2022.1",
        "strategy": "operation_specific_readback",
        "base_result_strategy": "result_schema",
        "expected_connected": expected_connected,
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.remote.getConnectionStatus": [
                {
                    "isConnected": expected_connected,
                    "status": "Connected" if expected_connected else "Not connected",
                }
            ]
        }
    )
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=reader,
    )

    assert verified.status == "verified"
    assert verified.business_state_verified is True
    assert verified.verification_strength == "operation_specific_readback"
    assert verified.message == (
        "The WAAPI result schema and operation-specific business-state readbacks passed."
    )
    assert reader.calls == [("ak.wwise.core.remote.getConnectionStatus", {}, {})]
    assert all(item["passed"] for item in verified.assertions)

    mismatch = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {
                "ak.wwise.core.remote.getConnectionStatus": [
                    {"isConnected": not expected_connected, "status": "opposite"}
                ]
            }
        ),
    )
    assert mismatch.status == "verification_failed"
    assert mismatch.ok is False


def test_public_transport_create_requires_returned_id_list_membership_and_state_readback() -> None:
    transport_id = 73
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "waapi.call",
                {
                    "api": "ak.wwise.core.transport.create",
                    "args": {"object": GUID},
                    "options": {},
                },
                version="2025.1",
            )
        ),
        read_call=ScriptedReader({}),
    ).as_dict()
    assert prepared["verification_plan"] == {
        "kind": "transport-created",
        "uri": "ak.wwise.core.transport.create",
        "version": "2025.1",
        "strategy": "operation_specific_readback",
        "base_result_strategy": "result_schema",
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.transport.getList": [
                {"list": [{"transport": transport_id, "object": GUID, "gameObject": 1}]}
            ],
            "ak.wwise.core.transport.getState": [{"state": "stopped"}],
        }
    )
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {"transport": transport_id}},
        read_call=reader,
    )

    assert verified.status == "verified"
    assert verified.business_state_verified is True
    assert reader.calls == [
        ("ak.wwise.core.transport.getList", {}, {}),
        ("ak.wwise.core.transport.getState", {"transport": transport_id}, {}),
    ]
    assertion_names = {item["name"] for item in verified.assertions if item["passed"]}
    assert assertion_names >= {
        "transport.create returned a non-zero uint32 transport ID",
        "created transport ID appears exactly once in transport.getList",
        "created transport ID resolves through transport.getState",
    }


@pytest.mark.parametrize("invalid_id", [None, 0, True, -1, 0x100000000, "73"])
def test_public_transport_create_never_reads_or_claims_verified_for_invalid_returned_id(
    invalid_id: Any,
) -> None:
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "waapi.call",
                {
                    "api": "ak.wwise.core.transport.create",
                    "args": {"object": GUID},
                    "options": {},
                },
                version="2022.1",
            )
        ),
        read_call=ScriptedReader({}),
    ).as_dict()
    reader = ScriptedReader({})
    execution_payload = {} if invalid_id is None else {"transport": invalid_id}

    verification = verify_prepared_operation(
        prepared,
        execution_result={"result": execution_payload},
        read_call=reader,
    )

    assert verification.status == "verification_failed"
    assert verification.ok is False
    assert reader.calls == []
    transport_assertion = next(
        item
        for item in verification.assertions
        if item["name"] == "transport.create returned a non-zero uint32 transport ID"
    )
    assert transport_assertion["passed"] is False


def test_public_transport_create_fails_if_list_or_state_does_not_prove_existence() -> None:
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "waapi.call",
                {
                    "api": "ak.wwise.core.transport.create",
                    "args": {"object": GUID},
                    "options": {},
                },
            )
        ),
        read_call=ScriptedReader({}),
    ).as_dict()
    verification = verify_prepared_operation(
        prepared,
        execution_result={"result": {"transport": 73}},
        read_call=ScriptedReader(
            {
                "ak.wwise.core.transport.getList": [{"list": [{"transport": 74}]}],
                "ak.wwise.core.transport.getState": [{"state": "unknown"}],
            }
        ),
    )

    assert verification.status == "verification_failed"
    failed = {item["name"] for item in verification.assertions if not item["passed"]}
    assert failed >= {
        "created transport ID appears exactly once in transport.getList",
        "ak.wwise.core.transport.getState readback matches the packaged reflected schema",
        "created transport ID resolves through transport.getState",
    }


def test_public_transport_destroy_uses_request_id_and_proves_absence_from_get_list() -> None:
    transport_id = 73
    prepared = prepare_operation(
        parse_operation_request(
            request(
                "waapi.call",
                {
                    "api": "ak.wwise.core.transport.destroy",
                    "args": {"transport": transport_id},
                    "options": {},
                },
                version="2024.1",
            )
        ),
        read_call=ScriptedReader({}),
    ).as_dict()
    assert prepared["verification_plan"] == {
        "kind": "transport-destroyed",
        "uri": "ak.wwise.core.transport.destroy",
        "version": "2024.1",
        "strategy": "operation_specific_readback",
        "base_result_strategy": "result_schema",
        "transport_id": transport_id,
    }
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {"ak.wwise.core.transport.getList": [{"list": [{"transport": 74}]}]}
        ),
    )
    assert verified.status == "verified"
    assert verified.business_state_verified is True

    still_present = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {"ak.wwise.core.transport.getList": [{"list": [{"transport": transport_id}]}]}
        ),
    )
    assert still_present.status == "verification_failed"
    assert next(
        item
        for item in still_present.assertions
        if item["name"] == "destroyed transport ID is absent from transport.getList"
    )["passed"] is False


@pytest.mark.parametrize("invalid_id", [0, True, -1, 0x100000000, "73"])
def test_public_transport_destroy_rejects_invalid_transport_id_before_preview(invalid_id: Any) -> None:
    with pytest.raises(OperationContractError) as invalid:
        parse_operation_request(
            request(
                "waapi.call",
                {
                    "api": "ak.wwise.core.transport.destroy",
                    "args": {"transport": invalid_id},
                    "options": {},
                },
            )
        )

    assert invalid.value.error_code == "INVALID_ARGUMENT"

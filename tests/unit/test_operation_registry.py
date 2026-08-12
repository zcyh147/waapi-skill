from __future__ import annotations

import base64
import copy
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import SemanticValidationError  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_import import (  # pyright: ignore[reportMissingImports]
    allowed_import_hierarchy_roots,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    COMPOSER_INPUT_MODE,
    LEGACY_JSON_INPUT_MODE,
    OPERATION_INPUT_MODE_LANES,
    OPERATION_REQUEST_CONTRACT,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
    OperationContractError,
    OperationInputModeLane,
    _materialize_audio_import_dynamic_rows,
    describe_operation,
    list_operation_specs,
    operation_input_mode,
    operation_input_modes_by_version,
    operation_request_machine_contract,
    operation_request_schema_digest,
    parse_operation_request,
    prepare_operation,
    validate_operation_input_mode_lanes,
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
EXPECTED_IMPORT_HIERARCHY_ROOTS = {
    "2021.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2022.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2023.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2024.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2025.1": ["Containers", "Interactive Music Hierarchy"],
}
EXPECTED_DEFAULT_CONTAINER_WORK_UNIT_PATHS = {
    "2021.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2022.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2023.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2024.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2025.1": r"\Containers\Default Work Unit",
}
EXPECTED_ACTOR_MIXER_METADATA_TYPES = {
    "2021.1": "ActorMixer",
    "2022.1": "ActorMixer",
    "2023.1": "ActorMixer",
    "2024.1": "ActorMixer",
    "2025.1": "PropertyContainer",
}


def test_every_supported_operation_version_has_one_explicit_normal_input_mode() -> None:
    specs = {spec.name: spec for spec in list_operation_specs()}

    assert len(specs) == 34
    assert len(OPERATION_INPUT_MODE_LANES) == sum(
        len(spec.supported_versions) for spec in specs.values()
    )
    for name, spec in specs.items():
        expected_mode = (
            COMPOSER_INPUT_MODE
            if name
            in {
                "audio.import",
                "object.create",
                "object.createPlugin",
                "object.set",
                "object.setRTPC",
            }
            else "inline_typed"
            if name in {
                "object.setLinked",
                "object.setName",
                "object.setNotes",
                "object.setProperty",
                "object.setReference",
                "object.copy",
                "object.delete",
                "object.move",
            }
            else LEGACY_JSON_INPUT_MODE
        )
        assert operation_input_modes_by_version(name) == {
            version: expected_mode
            for version in spec.supported_versions
        }
        for version in spec.supported_versions:
            assert operation_input_mode(name, version) == expected_mode


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda lanes: lanes[1:], "missing"),
        (lambda lanes: (*lanes, lanes[0]), "duplicate"),
        (
            lambda lanes: (
                replace(lanes[0], input_mode="unreviewed_raw_json"),
                *lanes[1:],
            ),
            "unknown input mode",
        ),
        (
            lambda lanes: (
                *lanes,
                OperationInputModeLane(
                    operation="missing.operation",
                    version="2022.1",
                    input_mode=LEGACY_JSON_INPUT_MODE,
                ),
            ),
            "unknown operation",
        ),
        (
            lambda lanes: (
                *lanes,
                OperationInputModeLane(
                    operation="object.set",
                    version="2021.1",
                    input_mode=LEGACY_JSON_INPUT_MODE,
                ),
            ),
            "unsupported version lane",
        ),
    ],
)
def test_operation_input_mode_registry_rejects_missing_duplicate_unknown_and_extra_lanes(
    mutate: Any,
    message: str,
) -> None:
    invalid_lanes = tuple(mutate(OPERATION_INPUT_MODE_LANES))

    with pytest.raises(OperationContractError, match=message):
        validate_operation_input_mode_lanes(invalid_lanes)


def test_input_mode_selection_is_isolated_by_exact_operation_not_shared_native_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_object_set = {
        "object.set",
        "object.setRTPC",
        "object.createPlugin",
    }
    shared_core_lua = {
        "lua.executeCoreFile",
        "lua.executeCoreInline",
    }
    assert {
        describe_operation(name).uri for name in shared_object_set
    } == {"ak.wwise.core.object.set"}
    assert {
        describe_operation(name).uri for name in shared_core_lua
    } == {"ak.wwise.core.executeLuaScript"}

    migrated = tuple(
        replace(lane, input_mode=COMPOSER_INPUT_MODE)
        if lane.operation in {"object.set", "lua.executeCoreInline"}
        else lane
        for lane in OPERATION_INPUT_MODE_LANES
    )
    validate_operation_input_mode_lanes(migrated)

    import wwise_waapi.operation_registry as registry

    before_digests = {
        (spec.name, version): operation_request_schema_digest(spec.name, version)
        for spec in list_operation_specs()
        for version in spec.supported_versions
        if spec.implemented
    }
    monkeypatch.setattr(registry, "OPERATION_INPUT_MODE_LANES", migrated)

    assert operation_input_mode("object.set", "2022.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("object.setRTPC", "2022.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("object.createPlugin", "2022.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("lua.executeCoreInline", "2025.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("lua.executeCoreFile", "2025.1") == LEGACY_JSON_INPUT_MODE
    assert {
        (spec.name, version): operation_request_schema_digest(spec.name, version)
        for spec in list_operation_specs()
        for version in spec.supported_versions
        if spec.implemented and spec.name not in {"object.set", "lua.executeCoreInline"}
    } == {
        key: digest
        for key, digest in before_digests.items()
        if key[0] not in {"object.set", "lua.executeCoreInline"}
    }


def test_operation_request_schema_digest_owns_only_versioned_machine_contract() -> None:
    contract_2022 = operation_request_machine_contract("object.set", "2022.1")
    contract_2025 = operation_request_machine_contract("object.set", "2025.1")

    assert contract_2022["contract"] == "waapi-skill.operation-request-schema/v1"
    assert contract_2022["operation"] == "object.set"
    assert contract_2022["version"] == "2022.1"
    assert contract_2022["request_contract"] == OPERATION_REQUEST_CONTRACT
    assert "summary" not in contract_2022
    assert "selection_guidance" not in contract_2022
    assert "next_step" not in contract_2022
    assert operation_request_schema_digest("object.set", "2022.1") == (
        "2b6d3903c5b3e11618c3eaf0a3d5a26aa0045db26750320f3a8ce8c7da004cee"
    )
    assert operation_request_schema_digest("object.set", "2025.1") != (
        operation_request_schema_digest("object.set", "2022.1")
    )
    assert operation_request_schema_digest("audio.import", "2022.1") == (
        "b84f8a7a23a1b5944a45d4889eaf996b96beefa346671917550f71fdc90f8d8a"
    )
    assert operation_request_schema_digest("audio.import", "2025.1") == (
        "f1f5d15fb16db06a6a3d5bf1d3749a7f0cf7b8a0a3efcbfbbf09515b2b72967d"
    )
    assert operation_request_schema_digest(
        "audio.importTabDelimited", "2022.1"
    ) == "3380aa555705e7432d3cce8626e99a1de7e17155f1d552a34031d6f51f0c418d"
    assert operation_request_schema_digest(
        "audio.importTabDelimited", "2025.1"
    ) == "231a06eaa5f85cbd1b842af68e7ec93eb096dad57f918b85140a2a04642530c3"
    assert contract_2025["argument_contract"] != {}

    with pytest.raises(OperationContractError, match="Unknown closed operation"):
        operation_request_schema_digest("missing.operation", "2022.1")
    with pytest.raises(OperationContractError, match="Unsupported Wwise version"):
        operation_request_schema_digest("object.set", "2099.1")


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


def _legacy_created_guid_present_prepared_preview_compatibility_fixture(
    *,
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a verifier-only preview shape that current prepare code no longer emits."""

    return {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.create",
        "verification_plan": {
            "kind": "created-guid-present",
            "expected": dict(expected),
        },
    }


def _legacy_audio_import_created_objects_prepared_preview_compatibility_fixture(
    *,
    version: str,
    targets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a verifier-only preview shape that current prepare code no longer emits."""

    return {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "audio.import",
        "verification_plan": {
            "kind": "audio-import-created-objects",
            "version": version,
            "targets": [dict(target) for target in targets],
        },
    }


def _schema_contains_const(value: Any, expected: str) -> bool:
    if isinstance(value, Mapping):
        return value.get("const") == expected or any(
            _schema_contains_const(item, expected)
            for item in value.values()
        )
    if isinstance(value, list | tuple):
        return any(_schema_contains_const(item, expected) for item in value)
    return False


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
            "Exact Wwise request token. Natural mappings: Actor Mixer -> ActorMixer; "
            "Random Container / 随机容器 -> RandomSequenceContainer (never RandomContainer); "
            "Blend Container / 混合容器 -> BlendContainer; Sound -> Sound. "
            "Wwise 2025.1 reflects an Actor Mixer as PropertyContainer, but its "
            "object.create request token remains ActorMixer."
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
    assert "import_operation" not in import_items["properties"]
    inline_audio = import_items["properties"]["audio_file_base64"]
    assert inline_audio["verbatim_contract"] == {
        "contract": "waapi-skill.audio-file-base64-verbatim/v1",
        "opaque_segment": "characters_after_first_vertical_bar",
        "caller_provided_complete_value": "copy_character_for_character",
        "forbidden_transformations": [
            "reconstruct",
            "re-encode",
            "repair",
            "truncate",
            "splice",
        ],
        "on_unreliable_preservation": "stop_before_preview",
    }
    assert "character-for-character" in inline_audio["description"]
    assert (
        "import_operation"
        not in specs["audio.import"]["argument_contract"]["properties"]["defaults"][
            "properties"
        ]
    )
    assert specs["audio.import"]["argument_contract"][
        "maximumEffectiveAudioFileBase64EncodedCharacters"
    ] == 256 * 1024
    import_operation = specs["audio.import"]["argument_contract"]["properties"][
        "import_operation"
    ]
    assert import_operation["enum"] == [
        "createNew",
        "useExisting",
        "replaceExisting",
    ]
    assert import_operation["default"] == "createNew"
    assert "$.arguments.import_operation" in import_operation["description"]
    assert "omission means createNew" in import_operation["description"]
    assert "Never place it inside an imports[] row" in import_operation["description"]
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
    assert specs["switchContainer.addAssignment"]["identity_contract"][
        "exact_selector_goes_directly_to_preview"
    ] is True
    assert specs["switchContainer.addAssignment"]["identity_contract"][
        "separate_query_object_required"
    ] is False
    assert "Do not query merely to translate" in specs[
        "switchContainer.addAssignment"
    ]["identity_contract"]["separate_query_object_rule"]
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
    assert object_set_conflict["default"] == "fail"
    assert "Omission defaults to fail" in object_set_conflict["description"]
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
    assert specs["object.copy"]["implemented"] is True
    assert specs["object.move"]["implemented"] is True
    assert specs["object.copy"]["boundary"] is None
    assert "returned copy GUID" in specs["object.copy"]["constraints"][0]
    assert specs["object.setProperty"]["identity_contract"]["caller_rows_allowed"] is False
    assert specs["object.setProperty"]["identity_contract"]["one_of"] == [
        "id",
        "path",
        "exact-type-name",
        "direct-child",
        "scoped-name",
    ]
    exact_type_name_identity = specs["object.setNotes"]["argument_contract"][
        "properties"
    ]["object"]["oneOf"][2]
    assert exact_type_name_identity["required"] == ["kind", "type", "name"]
    assert exact_type_name_identity["additionalProperties"] is False
    assert exact_type_name_identity["properties"]["kind"] == {
        "const": "exact-type-name"
    }
    assert exact_type_name_identity["properties"]["type"]["pattern"] == (
        r"^[A-Za-z0-9_.]+$"
    )
    assert exact_type_name_identity["properties"]["name"]["maxLength"] == 255
    assert "caller-authored WAQL is not accepted" in exact_type_name_identity[
        "description"
    ]
    direct_child_identity = specs["object.setNotes"]["argument_contract"][
        "properties"
    ]["object"]["oneOf"][3]
    assert direct_child_identity["required"] == ["kind", "parent", "type"]
    assert direct_child_identity["additionalProperties"] is False
    assert direct_child_identity["properties"]["kind"] == {
        "const": "direct-child"
    }
    assert direct_child_identity["properties"]["type"]["maxLength"] == 128
    assert direct_child_identity["properties"]["parent"]["oneOf"][1][
        "properties"
    ]["value"]["maxLength"] == 4096
    scoped_name_identity = specs["object.setNotes"]["argument_contract"][
        "properties"
    ]["object"]["oneOf"][4]
    assert scoped_name_identity["required"] == ["kind", "name", "type", "parent"]
    assert scoped_name_identity["additionalProperties"] is False
    assert scoped_name_identity["properties"]["name"]["maxLength"] == 255
    assert scoped_name_identity["properties"]["type"]["maxLength"] == 128
    assert scoped_name_identity["properties"]["type"]["pattern"] == (
        r"^[A-Za-z0-9_.]+$"
    )
    assert scoped_name_identity["properties"]["parent"]["oneOf"][0][
        "properties"
    ]["value"]["oneOf"][0]["maxLength"] == 4096
    assert "caller-authored WAQL is not accepted" in scoped_name_identity[
        "description"
    ]
    assert "No caller-authored WAQL" in direct_child_identity["description"]
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


def test_all_public_operation_schemas_exclude_caller_authored_waql_identities() -> None:
    for spec in list_operation_specs():
        contract = spec.as_dict()["argument_contract"]
        assert not _schema_contains_const(contract, "waql"), spec.name


def test_soundbank_generate_schema_discloses_independent_false_rebuild_defaults() -> None:
    operation = describe_operation("soundbank.generate").as_dict(
        version="2025.1"
    )
    properties = operation["argument_contract"]["properties"]
    row_rebuild = properties["soundbanks"]["items"]["properties"]["rebuild"]
    batch_rebuild = properties["rebuild_soundbanks"]

    assert row_rebuild["default"] is False
    assert batch_rebuild["default"] is False
    assert properties["clear_audio_file_cache"]["default"] is False
    assert properties["rebuild_init_bank"]["default"] is False
    assert "Per-SoundBank rebuild control" in row_rebuild["description"]
    assert "separate batch-level control" in row_rebuild["description"]
    assert "Batch-level native rebuildSoundBanks control" in batch_rebuild[
        "description"
    ]
    assert "independent from soundbanks[].rebuild" in batch_rebuild[
        "description"
    ]
    assert any(
        "batch-level rebuild_soundbanks and per-Bank soundbanks[].rebuild are independent"
        in constraint
        for constraint in operation["constraints"]
    )


def test_tab_import_schema_discloses_path_only_preview_progression() -> None:
    spec = describe_operation("audio.importTabDelimited")
    operation = spec.as_dict(version="2025.1")

    assert operation["file_read_policy"] == "pass_path_without_reading"
    assert operation["next_step"] == "preview"
    assert operation["preview_owns"] == [
        "tsv_parsing",
        "tsv_hash_validation",
        "inline_base64_validation",
        "media_validation",
        "exact_path_conflict_validation",
    ]
    assert {
        "file_read_policy",
        "next_step",
        "preview_owns",
    }.isdisjoint(spec.as_compact_dict())
    assert "file_read_policy" not in describe_operation("audio.import").as_dict(
        version="2025.1"
    )


def test_audio_import_operation_schema_discloses_compact_batch_composition_contract() -> None:
    operation = describe_operation("audio.import").as_dict(version="2022.1")
    argument_contract = operation["argument_contract"]
    defaults = argument_contract["properties"]["defaults"]
    composition = argument_contract["request_composition_contract"]

    assert "batch/default/common baseline" in (
        defaults["description"]
    )
    assert "exceptional rows carrying exact overrides" in defaults[
        "description"
    ]
    assert "merely repeated by a subset without baseline intent" in defaults[
        "description"
    ]
    assert composition == {
        "contract": "waapi-skill.audio-import-request-composition/v1",
        "shared_values": {
            "placement": "$.arguments.defaults",
            "occurrences": "once",
            "promotion_conditions": [
                {
                    "kind": "explicit_batch_baseline",
                    "source": "explicit_user_semantics",
                    "matching": "semantic_intent_not_literal_token",
                    "semantic_examples": [
                        "default",
                        "common",
                        "默认",
                        "统一",
                        "共同",
                    ],
                    "row_overrides": {
                        "allowed": True,
                        "fixed_fields_match": "field_name",
                        "properties_references_match": "exact_name",
                    },
                },
                {
                    "kind": "identical_effective_value",
                    "coverage": "all_import_rows",
                    "applies_identically_to_every_import_row": True,
                    "row_overrides": {"allowed": False},
                },
            ],
            "subset_shared_without_explicit_baseline": (
                "keep_in_each_applicable_import_row"
            ),
            "defaults_scope": {
                "applies_to": "every_imports_row",
                "object_type_filtering": False,
                "mixed_structure_and_sound_rows": {
                    "sound_only_fields": [
                        "import_language",
                        "properties",
                        "references",
                        "event",
                    ],
                    "placement": "keep_on_each_applicable_sound_row",
                    "defaults_placement": "forbidden",
                },
                "rule": (
                    "defaults has no object-type filter and affects every "
                    "imports row; when structure-only and Sound rows are "
                    "mixed, keep import_language, properties, references, "
                    "and event on each applicable Sound row instead of "
                    "defaults"
                ),
            },
            "fixed_fields": [
                "object_path",
                "object_type",
                "audio_file",
                "audio_file_base64",
                "import_language",
                "import_location",
                "originals_subfolder",
                "notes",
                "audio_source_notes",
                "event",
                "dialogue_event",
                "switch_assignment",
            ],
            "named_fields": ["properties", "references"],
            "imports_row_policy": (
                "row_specific_fields_and_exact_overrides_only"
            ),
            "named_override_key": "name",
        },
        "metadata_dependency_closure": {
            "contract": "waapi-skill.live-metadata-dependency-closure/v1",
            "selection": {
                "source": "current_operation_request",
                "kinds": ["property", "reference"],
                "selected_fields_only": True,
            },
            "metadata_source": {
                "command": "metadata discover",
                "authority": "live-waapi",
                "same_result_required": True,
                "candidate_collections": [
                    "$.agent_result.candidates",
                    "$.agent_result.dependency_candidates",
                ],
                "requirements_field": "dependency_requirements",
                "unresolved_dependencies_path": (
                    "$.agent_result.unresolved_dependencies"
                ),
            },
            "traversal": {
                "recursive": True,
                "dependency_identity": "exact_returned_property_name",
            },
            "materialization": {
                "ordinary_dependencies": {
                    "owner": "request",
                    "required_values_count": 1,
                    "kind": "property",
                    "copy_name_from": (
                        "dependency_requirements[].property"
                    ),
                    "copy_value_from": (
                        "dependency_requirements[].required_values[0]"
                    ),
                    "scope": {
                        "inherit_selected_owner_scope": True,
                        "defaults": "$.arguments.defaults.properties",
                        "row": (
                            "$.arguments.imports"
                            "[owner_row_index].properties"
                        ),
                    },
                },
                "supported_reference_activation": {
                    "owner": "gateway",
                    "supported_shape": {
                        "dependency_type": "override",
                        "action": "Enable",
                        "context": "Self",
                        "property_type": ["bool", "boolean"],
                        "required_value": True,
                    },
                    "request_forms": {
                        "omitted": (
                            "accepted_and_derived_before_dispatch"
                        ),
                        "explicit_required_value": (
                            "accepted_and_deduplicated"
                        ),
                        "explicit_conflict": "rejected",
                    },
                    "scope": "same_object_as_reference",
                },
            },
            "failure_policy": {
                "phase": "before_preview",
                "action": "stop",
                "conditions": [
                    "required_values_missing",
                    "required_values_multiple",
                    "dependency_candidate_missing",
                    "dependency_unresolved",
                ],
                "guessing_allowed": False,
            },
        },
        "import_operation": {
            "contract": "waapi-skill.import-operation-intent/v1",
            "path": "$.arguments.import_operation",
            "matching": "semantic_user_intent_not_literal_token",
            "required_when_user_intent_is_explicit": True,
            "omission_value_when_user_intent_is_unstated": "createNew",
            "explicit_intent_values": [
                {
                    "intent": "create_or_new",
                    "semantic_examples": [
                        "create",
                        "new",
                        "createNew",
                        "新建",
                        "创建",
                    ],
                    "value": "createNew",
                },
                {
                    "intent": "reuse_existing",
                    "semantic_examples": [
                        "reuse",
                        "use existing",
                        "useExisting",
                        "使用现有",
                        "复用",
                    ],
                    "value": "useExisting",
                },
                {
                    "intent": "replace_existing",
                    "semantic_examples": [
                        "replace",
                        "replace existing",
                        "replaceExisting",
                        "替换",
                        "覆盖现有",
                    ],
                    "value": "replaceExisting",
                },
            ],
        },
    }


def test_audio_import_operation_schema_discloses_exact_object_type_tokens() -> None:
    operation = describe_operation("audio.import").as_dict(version="2022.1")
    properties = operation["argument_contract"]["properties"]
    row_type = properties["imports"]["items"]["properties"]["object_type"]
    default_type = properties["defaults"]["properties"]["object_type"]

    expected_description = (
        "Exact Wwise audio.import objectType wire token. Natural mappings: "
        "Sound SFX / SFX 声音 -> Sound SFX (do not shorten an explicitly requested "
        "Sound SFX to Sound); Random Container / 随机容器 -> "
        "RandomSequenceContainer (never RandomContainer). These spellings are "
        "request-shape guidance; RandomContainer and SequenceContainer remain "
        "distinct and are not semantic aliases."
    )
    assert row_type == default_type == {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "description": expected_description,
    }


def test_audio_import_operation_schema_discloses_native_switch_assignment_usage() -> None:
    operation = describe_operation("audio.import").as_dict(version="2022.1")
    properties = operation["argument_contract"]["properties"]
    row_assignment = properties["imports"]["items"]["properties"][
        "switch_assignment"
    ]
    default_assignment = properties["defaults"]["properties"][
        "switch_assignment"
    ]

    assert row_assignment == default_assignment
    assert row_assignment["type"] == "string"
    description = row_assignment["description"]
    assert "native Wwise Switch Assignation import directive" in description
    assert "not an object identity or object-path field" in description
    assert "exact Switch/State value name" in description
    assert "for example, Snow" in description
    assert "do not pass the value object's path" in description


def test_audio_import_schema_discloses_generic_live_dependency_closure() -> None:
    operation = describe_operation("audio.import").as_dict(version="2022.1")
    dependency = operation["argument_contract"][
        "request_composition_contract"
    ]["metadata_dependency_closure"]

    assert dependency["selection"] == {
        "source": "current_operation_request",
        "kinds": ["property", "reference"],
        "selected_fields_only": True,
    }
    assert dependency["metadata_source"]["authority"] == "live-waapi"
    assert dependency["metadata_source"]["same_result_required"] is True
    assert dependency["traversal"]["recursive"] is True
    ordinary = dependency["materialization"]["ordinary_dependencies"]
    activation = dependency["materialization"][
        "supported_reference_activation"
    ]
    assert ordinary["owner"] == "request"
    assert ordinary["required_values_count"] == 1
    assert ordinary["scope"] == {
        "inherit_selected_owner_scope": True,
        "defaults": "$.arguments.defaults.properties",
        "row": "$.arguments.imports[owner_row_index].properties",
    }
    assert activation == {
        "owner": "gateway",
        "supported_shape": {
            "dependency_type": "override",
            "action": "Enable",
            "context": "Self",
            "property_type": ["bool", "boolean"],
            "required_value": True,
        },
        "request_forms": {
            "omitted": "accepted_and_derived_before_dispatch",
            "explicit_required_value": "accepted_and_deduplicated",
            "explicit_conflict": "rejected",
        },
        "scope": "same_object_as_reference",
    }
    assert dependency["failure_policy"]["phase"] == "before_preview"
    assert dependency["failure_policy"]["action"] == "stop"
    assert dependency["failure_policy"]["guessing_allowed"] is False
    assert "OutputBus" not in repr(dependency)
    assert "OverrideOutput" not in repr(dependency)


def test_import_operation_schemas_share_explicit_import_mode_mapping() -> None:
    operation = describe_operation("audio.import").as_dict(version="2025.1")
    properties = operation["argument_contract"]["properties"]
    import_operation = properties["import_operation"]
    intent_contract = operation["argument_contract"][
        "request_composition_contract"
    ]["import_operation"]
    tab_operation = describe_operation("audio.importTabDelimited").as_dict(
        version="2025.1"
    )
    tab_argument_contract = tab_operation["argument_contract"]

    assert "import_operation" in tab_operation["optional_arguments"]
    assert tab_argument_contract["properties"]["import_operation"] == (
        import_operation
    )
    assert tab_argument_contract["import_operation_contract"] == intent_contract
    assert tab_operation["file_read_policy"] == "pass_path_without_reading"
    assert intent_contract["contract"] == (
        "waapi-skill.import-operation-intent/v1"
    )
    assert import_operation["default"] == "createNew"
    assert "meaning rather than requiring literal tokens" in (
        import_operation["description"]
    )
    assert "preserve the existing object's identity while updating its media" in (
        import_operation["description"]
    )
    assert "When mode is unstated, omission means createNew" in (
        import_operation["description"]
    )
    assert intent_contract["matching"] == (
        "semantic_user_intent_not_literal_token"
    )
    assert intent_contract["required_when_user_intent_is_explicit"] is True
    assert {
        row["intent"]: row["value"]
        for row in intent_contract["explicit_intent_values"]
    } == {
        "create_or_new": "createNew",
        "reuse_existing": "useExisting",
        "replace_existing": "replaceExisting",
    }
    assert {
        row["intent"]: row["semantic_examples"][-2:]
        for row in intent_contract["explicit_intent_values"]
    } == {
        "create_or_new": ["新建", "创建"],
        "reuse_existing": ["使用现有", "复用"],
        "replace_existing": ["替换", "覆盖现有"],
    }


@pytest.mark.parametrize(
    ("version", "expected_roots"),
    EXPECTED_IMPORT_HIERARCHY_ROOTS.items(),
)
def test_audio_import_operation_schema_discloses_runtime_hierarchy_roots(
    version: str,
    expected_roots: list[str],
) -> None:
    operation = describe_operation("audio.import").as_dict(version=version)
    properties = operation["argument_contract"]["properties"]
    row_path = properties["imports"]["items"]["properties"]["object_path"]
    default_path = properties["defaults"]["properties"]["object_path"]
    expected_path_contract = {
        "contract": "waapi-skill.audio-import-object-path/v1",
        "resolved_target": {
            "minimum_segments": 3,
            "hierarchy_root_case_sensitive": True,
            "wwise_version": version,
            "allowed_hierarchy_roots": expected_roots,
        },
        "absolute_form": True,
        "import_location_selection": {
            "wire_significant": True,
            "absolute_object_path": {
                "ordinary_action": "omit",
                "infer_from_common_parent": False,
                "include_only_when_user_explicitly_requests_native_field": True,
            },
            "relative_object_path": {
                "requires_effective_import_location": True,
                "effective_sources": [
                    "$.arguments.imports[].import_location",
                    "$.arguments.defaults.import_location",
                ],
            },
        },
        "relative_form": {
            "allowed": True,
            "requires_effective_import_location": True,
        },
    }

    assert list(allowed_import_hierarchy_roots(version)) == expected_roots
    assert row_path["path_contract"] == expected_path_contract
    assert default_path["path_contract"] == expected_path_contract


def test_audio_import_unversioned_detail_schema_discloses_complete_root_matrix() -> None:
    operation = describe_operation("audio.import").as_dict()
    path_contract = operation["argument_contract"]["properties"]["imports"][
        "items"
    ]["properties"]["object_path"]["path_contract"]

    assert path_contract["resolved_target"][
        "allowed_hierarchy_roots_by_version"
    ] == EXPECTED_IMPORT_HIERARCHY_ROOTS


@pytest.mark.parametrize(
    ("version", "default_work_unit_path"),
    EXPECTED_DEFAULT_CONTAINER_WORK_UNIT_PATHS.items(),
)
def test_object_create_versioned_schema_discloses_same_name_merge_path_contract(
    version: str,
    default_work_unit_path: str,
) -> None:
    operation = describe_operation("object.create").as_dict(version=version)
    merge_contract = operation["argument_contract"][
        "same_name_merge_path_contract"
    ]

    assert merge_contract == {
        "contract": "waapi-skill.object-create-same-name-merge-path/v1",
        "applies_when": (
            "Exactly one unchanged same-name existing request root below the "
            "current-version default container Work Unit receives only a "
            "recursive descendant merge."
        ),
        "resolved_target": {
            "wwise_version": version,
            "default_container_work_unit_path": default_work_unit_path,
        },
        "exact_path": {
            "base_path_source": "resolved_target",
            "separator": "\\",
            "append_user_stated_descendant_segments": True,
            "terminal_segment": "same_name_request_root",
        },
        "identity_query": {
            "route": "query-object",
            "must_follow_operation_schema_directly": True,
            "path_mode": "exact",
            "return_fields": ["id", "name", "type", "path"],
            "path_argument_contract": {
                "contract": (
                    "waapi-skill.shell-single-quoted-wwise-path/v1"
                ),
                "source_value": "decoded_gateway_json_string",
                "shell_quoting": "single_quotes",
                "literal_backslashes_per_path_separator": 1,
                "json_serialized_backslashes_per_path_separator": 2,
                "copy_json_escape_backslashes_as_literal_characters": False,
            },
        },
        "forbidden_intermediate_routes": ["project-default-work-units"],
    }


def test_object_create_unversioned_schema_discloses_complete_merge_path_matrix() -> None:
    operation = describe_operation("object.create").as_dict()
    merge_contract = operation["argument_contract"][
        "same_name_merge_path_contract"
    ]

    assert merge_contract["resolved_target"] == {
        "default_container_work_unit_path_by_version": (
            EXPECTED_DEFAULT_CONTAINER_WORK_UNIT_PATHS
        )
    }
    assert merge_contract["identity_query"] == {
        "route": "query-object",
        "must_follow_operation_schema_directly": True,
        "path_mode": "exact",
        "return_fields": ["id", "name", "type", "path"],
        "path_argument_contract": {
            "contract": "waapi-skill.shell-single-quoted-wwise-path/v1",
            "source_value": "decoded_gateway_json_string",
            "shell_quoting": "single_quotes",
            "literal_backslashes_per_path_separator": 1,
            "json_serialized_backslashes_per_path_separator": 2,
            "copy_json_escape_backslashes_as_literal_characters": False,
        },
    }
    assert merge_contract["forbidden_intermediate_routes"] == [
        "project-default-work-units"
    ]


@pytest.mark.parametrize(
    ("version", "default_work_unit_path"),
    EXPECTED_DEFAULT_CONTAINER_WORK_UNIT_PATHS.items(),
)
def test_object_create_versioned_schema_discloses_default_parent_and_metadata_scope(
    version: str,
    default_work_unit_path: str,
) -> None:
    operation = describe_operation("object.create").as_dict(version=version)
    parent_contract = operation["argument_contract"][
        "default_container_parent_contract"
    ]

    assert parent_contract["contract"] == (
        "waapi-skill.object-create-default-container-parent/v1"
    )
    assert parent_contract["resolved_target"] == {
        "wwise_version": version,
        "default_container_work_unit_path": default_work_unit_path,
    }
    assert parent_contract["parent_path"] == {
        "base_path_source": "resolved_target",
        "separator": "\\",
        "append_user_stated_parent_segments": True,
    }
    assert parent_contract["dynamic_actor_mixer_metadata_scope"] == {
        "kind": "object_type",
        "one_discovery_for_same_type_targets": True,
        "object_scope_is_for_one_existing_target_only": True,
        "wwise_version": version,
        "actor_mixer_object_type": EXPECTED_ACTOR_MIXER_METADATA_TYPES[version],
    }
    assert parent_contract["required_sequence"] == [
        "operation-schema object.create",
        "one metadata discover when a dynamic field token is unknown",
        "preview",
    ]
    assert parent_contract["forbidden_intermediate_routes"] == [
        "project-default-work-units"
    ]


@pytest.mark.parametrize(
    ("version", "default_work_unit_path"),
    EXPECTED_DEFAULT_CONTAINER_WORK_UNIT_PATHS.items(),
)
def test_object_set_versioned_schema_discloses_default_target_and_metadata_scope(
    version: str,
    default_work_unit_path: str,
) -> None:
    operation = describe_operation("object.set").as_dict(version=version)
    target_contract = operation["argument_contract"][
        "default_container_target_contract"
    ]

    assert target_contract["contract"] == (
        "waapi-skill.object-set-default-container-target/v1"
    )
    assert target_contract["resolved_target"] == {
        "wwise_version": version,
        "default_container_work_unit_path": default_work_unit_path,
    }
    assert target_contract["dynamic_actor_mixer_metadata_scope"] == {
        "kind": "object_type",
        "one_discovery_for_same_type_targets": True,
        "object_scope_is_for_one_existing_target_only": True,
        "wwise_version": version,
        "actor_mixer_object_type": EXPECTED_ACTOR_MIXER_METADATA_TYPES[version],
    }
    assert target_contract["required_sequence"] == [
        "operation-schema object.set",
        "one metadata discover when a dynamic field token is unknown",
        "preview",
    ]
    assert target_contract["forbidden_intermediate_routes"] == [
        "project-default-work-units"
    ]


def test_object_set_unversioned_schema_discloses_complete_target_matrix() -> None:
    operation = describe_operation("object.set").as_dict()
    target_contract = operation["argument_contract"][
        "default_container_target_contract"
    ]

    assert target_contract["resolved_target"] == {
        "default_container_work_unit_path_by_version": (
            EXPECTED_DEFAULT_CONTAINER_WORK_UNIT_PATHS
        )
    }
    assert target_contract["dynamic_actor_mixer_metadata_scope"] == {
        "kind": "object_type",
        "one_discovery_for_same_type_targets": True,
        "object_scope_is_for_one_existing_target_only": True,
        "actor_mixer_object_type_by_version": EXPECTED_ACTOR_MIXER_METADATA_TYPES,
    }


def test_switch_remove_schema_prefers_scoped_names_from_parent_evidence() -> None:
    remove = describe_operation("switchContainer.removeAssignment").as_dict()
    properties = remove["argument_contract"]["properties"]

    assert "canonical id already returned by the Gateway" in properties[
        "switch_container"
    ]["description"]
    assert "Never shorten" in properties["switch_container"]["description"]
    assert "use exact-type-name with type SwitchContainer" in properties[
        "switch_container"
    ]["description"]
    assert "\\Player_Footsteps is not a complete Wwise path" in properties[
        "switch_container"
    ]["description"]
    assert "use scoped-name" in properties["child"]["description"]
    assert "do not synthesize a full path" in properties["child"]["description"]
    assert "Group/Value" in properties["state_or_switch"]["description"]
    assert "does not add a Group display-name path segment" in properties[
        "state_or_switch"
    ]["description"]
    assert "description" not in describe_operation(
        "switchContainer.addAssignment"
    ).as_dict()["argument_contract"]["properties"]["child"]


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

    object_create = specs["object.create"]["selection_guidance"]
    assert (
        "Exactly one same-name existing root remains unchanged while only a "
        "descendant tree is merged below it."
    ) in object_create["use_when"]
    create_set_boundary = next(
        item["when"]
        for item in object_create["choose_instead"]
        if item["target"] == "object.set"
    )
    assert "descendant below the named request root" in create_set_boundary
    assert "direct insertion target" in create_set_boundary
    assert any(
        "named request root itself is not that descendant insertion target"
        in item
        for item in object_create["avoid_when"]
    )

    assert (
        "One atomic request changes fields, references, or lists on existing targets."
        in object_set["use_when"]
    )
    assert not any(
        "fields, references, children, or lists" in item
        for item in object_set["use_when"]
    )
    descendant_insertion_rule = next(
        item
        for item in object_set["use_when"]
        if "directly to an explicitly existing descendant container" in item
    )
    assert "below the named request root" in descendant_insertion_rule
    assert (
        "named request root itself is not that descendant insertion target"
        in descendant_insertion_rule
    )
    object_create_fallback = next(
        item["when"]
        for item in object_set["choose_instead"]
        if item["target"] == "object.create"
    )
    assert "one unchanged same-name existing request root" in object_create_fallback
    assert "only merges descendants" in object_create_fallback

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


@pytest.mark.parametrize("version", tuple(UNDO_GROUP_INNER_URIS_BY_VERSION))
def test_undo_group_public_schema_uses_the_runtime_version_allowlist(
    version: str,
) -> None:
    spec = next(
        item for item in list_operation_specs() if item.name == "waapi.undoGroup"
    ).as_dict(version=version)
    api_schema = spec["argument_contract"]["properties"]["calls"]["items"][
        "properties"
    ]["api"]
    expected = sorted(UNDO_GROUP_INNER_URIS_BY_VERSION[version])

    assert api_schema["enum"] == expected
    assert "pattern" not in api_schema
    assert [row["const"] for row in api_schema["value_contracts"]] == expected
    for row in api_schema["value_contracts"]:
        assert row["schema_pointer"] == {
            "gateway_argv": [
                "--version",
                version,
                "describe",
                row["const"],
                "--full-schema",
            ],
            "result_path": (
                f"$.availability.{version}.capability.schema.full"
            ),
        }


def test_ui_command_descriptor_schema_is_closed_and_shared_by_both_operations() -> None:
    specs = {spec.name: spec.as_dict() for spec in list_operation_specs()}
    register_item = specs["ui.commands.register"]["argument_contract"][
        "properties"
    ]["commands"]["items"]
    unregister_item = specs["ui.commands.unregister"]["argument_contract"][
        "properties"
    ]["commands"]["items"]
    register_commands = specs["ui.commands.register"]["argument_contract"][
        "properties"
    ]["commands"]
    unregister_commands = specs["ui.commands.unregister"]["argument_contract"][
        "properties"
    ]["commands"]

    assert unregister_item == register_item
    assert register_commands["caseInsensitiveUniqueBy"] == "$.id"
    assert unregister_commands["caseInsensitiveUniqueBy"] == "$.id"
    assert register_item["required"] == ["id", "display_name", "handler"]
    assert register_item["optional"] == [
        "context_menu",
        "default_shortcut",
        "main_menu",
    ]
    assert register_item["additionalProperties"] is False

    handlers = {
        branch["properties"]["kind"]["const"]: branch
        for branch in register_item["properties"]["handler"]["oneOf"]
    }
    assert set(handlers) == {"notification", "program", "lua_script"}
    assert handlers["notification"]["required"] == ["kind"]
    assert handlers["notification"]["optional"] == []
    assert handlers["program"]["required"] == ["kind", "program_path"]
    assert handlers["program"]["optional"] == [
        "argument_tokens",
        "redirect_outputs",
        "start_mode",
        "working_directory",
    ]
    assert handlers["program"]["properties"]["argument_tokens"]["maxItems"] == 0
    assert handlers["lua_script"]["required"] == ["kind", "lua_script_path"]
    assert handlers["lua_script"]["optional"] == [
        "argument_tokens",
        "lua_module_directories",
        "lua_selected_return",
        "start_mode",
        "working_directory",
    ]
    assert handlers["lua_script"]["supported_versions"] == [
        "2023.1",
        "2024.1",
        "2025.1",
    ]

    context_menu = register_item["properties"]["context_menu"]
    assert context_menu["required"] == []
    assert context_menu["optional"] == [
        "base_path",
        "enabled_for",
        "visible_for",
    ]
    assert context_menu["additionalProperties"] is False
    assert set(context_menu["properties"]) == {
        "base_path",
        "enabled_for",
        "visible_for",
    }
    assert context_menu["properties"]["base_path"]["items"]["pattern"] == (
        r"^[^/\\]+$"
    )
    for field_name in ("enabled_for", "visible_for"):
        field = context_menu["properties"][field_name]
        assert field["uniqueItems"] is True
        assert field["caseInsensitiveUniqueItems"] is True
        assert field["items"]["pattern"] == r"^[^,]+$"
    main_menu = register_item["properties"]["main_menu"]
    assert main_menu["required"] == ["base_path"]
    assert main_menu["optional"] == []
    assert main_menu["additionalProperties"] is False
    lua_properties = handlers["lua_script"]["properties"]
    for field_name in ("lua_module_directories", "lua_selected_return"):
        assert lua_properties[field_name]["uniqueItems"] is True
        assert lua_properties[field_name]["caseInsensitiveUniqueItems"] is True


@pytest.mark.parametrize(
    "handler",
    (
        {"kind": "notification"},
        {
            "kind": "program",
            "program_path": "/tmp/example-program",
            "argument_tokens": [],
            "redirect_outputs": False,
            "start_mode": "SingleSelectionSingleProcess",
            "working_directory": "/tmp",
        },
        {
            "kind": "lua_script",
            "lua_script_path": "/tmp/example.lua",
            "argument_tokens": ["--selection", "${id}"],
            "lua_module_directories": ["/tmp/lua"],
            "lua_selected_return": ["return"],
            "start_mode": "MultipleSelectionSingleProcessSpaceSeparated",
            "working_directory": "/tmp",
        },
    ),
)
def test_ui_command_descriptor_schema_fields_match_request_shape_validator(
    handler: Mapping[str, Any],
) -> None:
    arguments = {
        "commands": [
            {
                "id": "example.command",
                "display_name": "Example command",
                "handler": dict(handler),
                "context_menu": {
                    "base_path": [],
                    "enabled_for": ["Sound"],
                    "visible_for": ["Sound"],
                },
                "default_shortcut": "",
                "main_menu": {"base_path": ["WAAPI Skill"]},
            }
        ],
        "source_authority": "user_supplied_verbatim",
    }
    parsed = parse_operation_request(
        request("ui.commands.register", arguments, version="2024.1")
    )
    assert parsed.arguments == arguments
    arguments["commands"][0]["context_menu"] = {}
    parsed_empty_context = parse_operation_request(
        request("ui.commands.register", arguments, version="2024.1")
    )
    assert parsed_empty_context.arguments["commands"][0]["context_menu"] == {}

    invalid_arguments = copy.deepcopy(arguments)
    invalid_arguments["commands"][0]["handler"]["raw_native_field"] = True
    with pytest.raises(OperationContractError) as error:
        parse_operation_request(
            request(
                "ui.commands.register",
                invalid_arguments,
                version="2024.1",
            )
        )
    assert error.value.error_code == "INVALID_REQUEST"


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
    assert specs["object.copy"]["implemented"] is True
    assert specs["object.copy"]["boundary"] is None
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

    copied = parse_operation_request(
        request(
            "object.copy",
            {
                "object": {"kind": "id", "value": GUID},
                "parent": {"kind": "id", "value": TARGET_GUID},
            },
        )
    )
    assert copied.operation == "object.copy"

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
    io_root: Path,
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
            "io_root": str(io_root.resolve()),
        },
        version=version,
    )


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_audio_convert_preserves_exact_non_empty_string_array_values_and_order(
    version: str,
    tmp_path: Path,
) -> None:
    payload = audio_convert_request(io_root=tmp_path, version=version)

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
    tmp_path: Path,
) -> None:
    kwargs = {
        "objects": None,
        "platforms": None,
        "languages": None,
        field: value,
    }

    with pytest.raises(OperationContractError) as boundary:
        parse_operation_request(
            audio_convert_request(io_root=tmp_path, version=version, **kwargs),
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
    tmp_path: Path,
) -> None:
    payload = audio_convert_request(io_root=tmp_path, version=version)
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


def test_object_create_reuses_prepare_local_selector_and_class_property_metadata() -> None:
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Cache Tests"
    parent = object_row(
        object_id=PARENT_GUID,
        name="Cache Tests",
        object_type="WorkUnit",
        path=parent_path,
        parent="{hierarchy}",
    )
    output_bus = object_row(
        object_id=TARGET_GUID,
        name="Weapons",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weapons",
        parent="{master-workunit}",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [parent]},
                {"return": [output_bus]},
                {"return": [output_bus]},
                {"return": []},
                {"return": []},
            ],
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                        {"classId": 2, "name": "Sound", "type": "Sound"},
                    ]
                }
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {"name": "Volume", "type": "Real32"},
                {"name": "OutputBus", "type": "Reference"},
                {"name": "Volume", "type": "Real32"},
                {"name": "OutputBus", "type": "Reference"},
            ],
        }
    )
    repeated_fields = {
        "properties": [{"name": "Volume", "value": -3.0}],
        "references": [
            {
                "name": "OutputBus",
                "target": {"kind": "id", "value": TARGET_GUID},
            }
        ],
    }

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "object.create",
                {
                    "parent": {"kind": "id", "value": PARENT_GUID},
                    "type": "ActorMixer",
                    "name": "CacheRoot",
                    **repeated_fields,
                    "children": [
                        {"type": "Sound", "name": "A", **repeated_fields},
                        {
                            "type": "Sound",
                            "name": "B",
                            "properties": repeated_fields["properties"],
                            "references": [
                                {
                                    "name": "OutputBus",
                                    "target": {
                                        "kind": "path",
                                        "value": output_bus["path"],
                                    },
                                }
                            ],
                        },
                    ],
                },
            )
        ),
        read_call=reader,
    ).as_dict()

    target_reads = [
        call
        for call in reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1] == {"from": {"id": [TARGET_GUID]}}
    ]
    assert len(target_reads) == 1
    target_path_reads = [
        call
        for call in reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1] == {"from": {"path": [output_bus["path"]]}}
    ]
    assert len(target_path_reads) == 1
    assert [
        call[1]
        for call in reader.calls
        if call[0] == "ak.wwise.core.object.getPropertyInfo"
    ] == [
        {"property": "Volume", "classId": 1},
        {"property": "OutputBus", "classId": 1},
        {"property": "Volume", "classId": 2},
        {"property": "OutputBus", "classId": 2},
    ]
    reference_roles = [
        row
        for role, row in prepared["resolved_roles"].items()
        if role != "parent"
    ]
    assert len(reference_roles) == 3
    assert {row["object"] for row in reference_roles} == {TARGET_GUID}


def test_object_set_reuses_prepare_local_selector_and_resets_cache_next_prepare() -> None:
    target_path = r"\Actor-Mixer Hierarchy\Default Work Unit\CacheTarget"
    target = object_row(
        object_id=GUID,
        name="CacheTarget",
        object_type="ActorMixer",
        path=target_path,
    )
    output_bus = object_row(
        object_id=TARGET_GUID,
        name="Weapons",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weapons",
        parent="{master-workunit}",
    )
    target_snapshot = {**target, "OutputBus": None}
    payload = parse_operation_request(
        request(
            "object.set",
            {
                "objects": [
                    {
                        "object": {"kind": "id", "value": GUID},
                        "references": [
                            {
                                "name": "OutputBus",
                                "target": {"kind": "id", "value": TARGET_GUID},
                            }
                        ],
                        "children": [
                            {
                                "type": "ActorMixer",
                                "name": "Group",
                                "children": [
                                    {
                                        "type": "Sound",
                                        "name": "A",
                                        "properties": [
                                            {"name": "Volume", "value": -3.0}
                                        ],
                                        "references": [
                                            {
                                                "name": "OutputBus",
                                                "target": {
                                                    "kind": "id",
                                                    "value": TARGET_GUID,
                                                },
                                            }
                                        ],
                                    },
                                    {
                                        "type": "Sound",
                                        "name": "B",
                                        "properties": [
                                            {"name": "Volume", "value": -6.0}
                                        ],
                                        "references": [
                                            {
                                                "name": "OutputBus",
                                                "target": {
                                                    "kind": "id",
                                                    "value": TARGET_GUID,
                                                },
                                            }
                                        ],
                                    },
                                ],
                            },
                        ],
                    }
                ]
            },
        )
    )

    def make_reader() -> ScriptedReader:
        return ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target]},
                    {"return": [output_bus]},
                    {"return": []},
                    {"return": [target_snapshot]},
                    {"return": []},
                ],
                "ak.wwise.core.object.getTypes": [
                    {
                        "return": [
                            {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                            {"classId": 2, "name": "Sound", "type": "Sound"},
                        ]
                    }
                ],
                "ak.wwise.core.object.getPropertyInfo": [
                    {"name": "OutputBus", "type": "Reference"},
                    {"name": "Volume", "type": "Real32"},
                    {"name": "OutputBus", "type": "Reference"},
                ],
            }
        )

    readers = [make_reader(), make_reader()]
    prepared = [
        prepare_operation(payload, read_call=reader).as_dict()
        for reader in readers
    ]

    for reader in readers:
        target_reads = [
            call
            for call in reader.calls
            if call[0] == "ak.wwise.core.object.get"
            and call[1] == {"from": {"id": [TARGET_GUID]}}
        ]
        assert len(target_reads) == 1
        assert [
            call[1]
            for call in reader.calls
            if call[0] == "ak.wwise.core.object.getPropertyInfo"
        ] == [
            {"property": "OutputBus", "object": GUID},
            {"property": "Volume", "classId": 2},
            {"property": "OutputBus", "classId": 2},
        ]
    assert prepared[0]["dispatch"] == prepared[1]["dispatch"]


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
        request(
            "object.delete",
            {
                "object": {
                    "kind": "exact-type-name",
                    "type": "Sound",
                    "name": "OldName",
                }
            },
        )
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


@pytest.mark.parametrize(
    "payload",
    (
        request(
            "object.setNotes",
            {
                "object": {
                    "kind": "waql",
                    "value": "from type Sound take 2",
                },
                "value": "reviewed",
            },
        ),
        request(
            "object.create",
            {
                "parent": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
                },
                "type": "ActorMixer",
                "name": "ClosedRoot",
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {
                            "kind": "waql",
                            "value": "from type AuxBus take 2",
                        },
                    }
                ],
            },
        ),
        request(
            "object.set",
            {
                "objects": [
                    {
                        "object": {
                            "kind": "path",
                            "value": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit"
                                r"\ClosedRoot"
                            ),
                        },
                        "references": [
                            {
                                "name": "OutputBus",
                                "target": {
                                    "kind": "waql",
                                    "value": "from type AuxBus take 2",
                                },
                            }
                        ],
                    }
                ]
            },
            version="2022.1",
        ),
    ),
)
def test_raw_waql_identity_is_rejected_during_request_parse_before_any_live_read(
    payload: Mapping[str, Any],
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        parse_operation_request(payload)

    assert rejected.value.error_code == "INVALID_IDENTITY"


@pytest.mark.parametrize(
    "identity",
    (
        {
            "kind": "exact-type-name",
            "type": 'Sound where name = "Other"',
            "name": "OldName",
        },
        {
            "kind": "exact-type-name",
            "type": "Sound",
            "name": 'Old"Name',
        },
        {
            "kind": "exact-type-name",
            "type": "Sound",
            "name": "OldName",
            "value": "from type Sound",
        },
        {
            "kind": "exact-type-name",
            "type": "Sound",
            "name": "x" * 256,
        },
    ),
)
def test_exact_type_name_identity_rejects_open_or_unbounded_shapes_before_read(
    identity: Mapping[str, Any],
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        parse_operation_request(
            request(
                "object.setNotes",
                {"object": identity, "value": "reviewed"},
            )
        )

    assert rejected.value.error_code in {"INVALID_IDENTITY", "INVALID_REQUEST"}


def test_exact_type_name_identity_requires_one_exact_live_name_and_type() -> None:
    identity = {
        "kind": "exact-type-name",
        "type": "Sound",
        "name": "OldName",
    }
    for rows, error_code in (
        ([], "AMBIGUOUS_IDENTITY"),
        (
            [
                object_row(),
                object_row(object_id=TARGET_GUID),
            ],
            "AMBIGUOUS_IDENTITY",
        ),
        (
            [object_row(name="DifferentName")],
            "IDENTITY_MISMATCH",
        ),
        (
            [object_row(object_type="ActorMixer")],
            "IDENTITY_MISMATCH",
        ),
    ):
        reader = ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": rows}]}
        )
        with pytest.raises(OperationContractError) as rejected:
            prepare_operation(
                parse_operation_request(
                    request(
                        "object.setNotes",
                        {"object": identity, "value": "reviewed"},
                    )
                ),
                read_call=reader,
            )

        assert rejected.value.error_code == error_code
        assert reader.calls == [
            (
                "ak.wwise.core.object.get",
                {
                    "waql": (
                        'from type Sound where name = "OldName" take 2'
                    )
                },
                {
                    "return": [
                        "id",
                        "name",
                        "type",
                        "path",
                        "parent",
                        "notes",
                    ]
                },
            )
        ]


@pytest.mark.parametrize(
    "identity",
    (
        {
            "kind": "scoped-name",
            "type": 'Sound where name = "Other"',
            "name": "OldName",
            "parent": {"kind": "id", "value": PARENT_GUID},
        },
        {
            "kind": "scoped-name",
            "type": "Sound",
            "name": 'Old"Name',
            "parent": {"kind": "id", "value": PARENT_GUID},
        },
        {
            "kind": "scoped-name",
            "type": "Sound",
            "name": "x" * 256,
            "parent": {"kind": "id", "value": PARENT_GUID},
        },
        {
            "kind": "scoped-name",
            "type": "Sound",
            "name": "OldName",
            "parent": {"kind": "id", "value": "x" * 4097},
        },
        {
            "kind": "scoped-name",
            "type": "Sound",
            "name": "OldName",
            "parent": {
                "kind": "path",
                "value": '\\Actor-Mixer Hierarchy\\Bad"Parent',
            },
        },
    ),
)
def test_scoped_name_identity_rejects_open_or_unbounded_shapes_before_read(
    identity: Mapping[str, Any],
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        parse_operation_request(
            request(
                "object.setNotes",
                {"object": identity, "value": "reviewed"},
            )
        )

    assert rejected.value.error_code in {"INVALID_IDENTITY", "INVALID_REQUEST"}


@pytest.mark.parametrize(
    ("target_rows", "error_code"),
    (
        ([], "AMBIGUOUS_IDENTITY"),
        (
            [
                object_row(),
                object_row(object_id=TARGET_GUID),
            ],
            "AMBIGUOUS_IDENTITY",
        ),
        ([object_row(name="DifferentName")], "IDENTITY_MISMATCH"),
        ([object_row(object_type="ActorMixer")], "IDENTITY_MISMATCH"),
        (
            [object_row(parent="{99999999-9999-9999-9999-999999999999}")],
            "IDENTITY_MISMATCH",
        ),
        (
            [
                {
                    key: (
                        r"\Actor-Mixer Hierarchy\Other Work Unit\OldName"
                        if key == "path"
                        else value
                    )
                    for key, value in object_row().items()
                    if key != "parent"
                }
            ],
            "IDENTITY_MISMATCH",
        ),
    ),
)
def test_scoped_name_identity_requires_one_exact_live_child(
    target_rows: list[dict[str, Any]],
    error_code: str,
) -> None:
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="Default Work Unit",
        object_type="WorkUnit",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": target_rows},
            ]
        }
    )
    identity = {
        "kind": "scoped-name",
        "type": "Sound",
        "name": "OldName",
        "parent": {"kind": "id", "value": PARENT_GUID},
    }

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "object.setNotes",
                    {"object": identity, "value": "reviewed"},
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == error_code
    assert reader.calls[1][1] == {
        "waql": (
            f'from object "{PARENT_GUID}" select children '
            'where type = "Sound" and name = "OldName" take 2'
        )
    }


def test_direct_child_identity_builds_one_bounded_gateway_owned_selector() -> None:
    parent_path = r"\Events\Default Work Unit\Weather_Play"
    parent_id = "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    action_id = "{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}"
    parent_row = object_row(
        object_id=parent_id,
        name="Weather_Play",
        object_type="Event",
        path=parent_path,
        parent="{cccccccc-cccc-cccc-cccc-cccccccccccc}",
    )
    action_row = object_row(
        object_id=action_id,
        name="Action",
        object_type="Action",
        path=f"{parent_path}\\Action",
        parent=parent_id,
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": [action_row]},
            ]
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "object.setNotes",
                {
                    "object": {
                        "kind": "direct-child",
                        "parent": {"kind": "path", "value": parent_path},
                        "type": "Action",
                    },
                    "value": "reviewed",
                },
            )
        ),
        read_call=reader,
    ).as_dict()

    assert reader.calls[0][1] == {"from": {"path": [parent_path]}}
    assert reader.calls[1][1] == {
        "waql": (
            f'from object "{parent_path}" '
            'select children where type = "Action" take 2'
        )
    }
    assert reader.calls[1][2]["return"] == [
        "id",
        "name",
        "type",
        "path",
        "parent",
        "notes",
    ]
    assert prepared["dispatch"]["args"] == {
        "object": action_id,
        "value": "reviewed",
    }
    assert prepared["resolved_roles"]["object"]["resolution"] == (
        "live-direct-child"
    )


@pytest.mark.parametrize("child_rows", ([], [object_row(), object_row(object_id=TARGET_GUID)]))
def test_direct_child_identity_rejects_zero_or_multiple_rows(
    child_rows: list[dict[str, Any]],
) -> None:
    parent_path = r"\Events\Default Work Unit\Weather_Play"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="Weather_Play",
        object_type="Event",
        path=parent_path,
    )
    parsed = parse_operation_request(
        request(
            "object.setNotes",
            {
                "object": {
                    "kind": "direct-child",
                    "parent": {"kind": "path", "value": parent_path},
                    "type": "Action",
                },
                "value": "reviewed",
            },
        )
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parsed,
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [parent_row]},
                        {"return": child_rows},
                    ]
                }
            ),
        )

    assert rejected.value.error_code == "AMBIGUOUS_IDENTITY"
    assert rejected.value.details["row_count"] == len(child_rows)


@pytest.mark.parametrize(
    ("child_type", "child_parent"),
    (
        ("Sound", PARENT_GUID),
        ("Action", "{dddddddd-dddd-dddd-dddd-dddddddddddd}"),
    ),
)
def test_direct_child_identity_rejects_wrong_type_or_parent(
    child_type: str,
    child_parent: str,
) -> None:
    parent_path = r"\Events\Default Work Unit\Weather_Play"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="Weather_Play",
        object_type="Event",
        path=parent_path,
    )
    child_row = object_row(
        object_id=TARGET_GUID,
        name="Action",
        object_type=child_type,
        path=f"{parent_path}\\Action",
        parent=child_parent,
    )

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                request(
                    "object.setNotes",
                    {
                        "object": {
                            "kind": "direct-child",
                            "parent": {
                                "kind": "path",
                                "value": parent_path,
                            },
                            "type": "Action",
                        },
                        "value": "reviewed",
                    },
                )
            ),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [parent_row]},
                        {"return": [child_row]},
                    ]
                }
            ),
        )

    assert rejected.value.error_code == "IDENTITY_MISMATCH"


def test_direct_child_identity_quotes_valid_literal_content_without_query_splicing() -> None:
    parent_path = (
        r"\Events\Default Work Unit\Event where type = Sound select descendants"
    )
    object_type = "Action or type = Sound"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="Event where type = Sound select descendants",
        object_type="Event",
        path=parent_path,
    )
    child_row = object_row(
        object_id=TARGET_GUID,
        name="OddType",
        object_type=object_type,
        path=f"{parent_path}\\OddType",
        parent=PARENT_GUID,
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": [child_row]},
            ]
        }
    )

    prepare_operation(
        parse_operation_request(
            request(
                "object.setNotes",
                {
                    "object": {
                        "kind": "direct-child",
                        "parent": {"kind": "path", "value": parent_path},
                        "type": object_type,
                    },
                    "value": "reviewed",
                },
            )
        ),
        read_call=reader,
    )

    assert reader.calls[1][1] == {
        "waql": (
            f'from object "{parent_path}" select children where type = '
            f'"{object_type}" take 2'
        )
    }


@pytest.mark.parametrize(
    "identity",
    (
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": r"\Events\Default Work Unit\E"},
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "waql", "value": "from type Event"},
            "type": "Action",
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": r"\Events\Default Work Unit\E"},
            "type": "Action",
            "waql": "from type Sound",
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": "\\" + ("x" * 4096)},
            "type": "Action",
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": r"\Events\Default Work Unit\E"},
            "type": "x" * 129,
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": r'\Events\Default Work Unit\E"'},
            "type": "Action",
        },
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": r"\Events\Default Work Unit\E"},
            "type": 'Action" or type = "Sound',
        },
    ),
)
def test_direct_child_identity_rejects_malformed_or_unbounded_shapes(
    identity: Mapping[str, Any],
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        parse_operation_request(
            request(
                "object.setNotes",
                {"object": identity, "value": "reviewed"},
            )
        )

    assert rejected.value.error_code in {"INVALID_IDENTITY", "INVALID_REQUEST"}


def test_existing_identity_resolution_shapes_keep_their_original_queries() -> None:
    object_path = object_row()["path"]
    cases = (
        (
            {"kind": "id", "value": GUID},
            [{"return": [object_row()]}],
            [{"from": {"id": [GUID]}}],
        ),
        (
            {"kind": "path", "value": object_path},
            [{"return": [object_row()]}],
            [{"from": {"path": [object_path]}}],
        ),
        (
            {
                "kind": "exact-type-name",
                "type": "Sound",
                "name": "OldName",
            },
            [{"return": [object_row()]}],
            [
                {
                    "waql": (
                        'from type Sound where name = "OldName" take 2'
                    )
                }
            ],
        ),
        (
            {
                "kind": "scoped-name",
                "name": "OldName",
                "type": "Sound",
                "parent": {"kind": "id", "value": PARENT_GUID},
            },
            [
                {
                    "return": [
                        object_row(
                            object_id=PARENT_GUID,
                            name="Default Work Unit",
                            object_type="WorkUnit",
                            path=r"\Actor-Mixer Hierarchy\Default Work Unit",
                        )
                    ]
                },
                {"return": [object_row()]},
            ],
            [
                {"from": {"id": [PARENT_GUID]}},
                {
                    "waql": (
                        f'from object "{PARENT_GUID}" select children '
                        'where type = "Sound" and name = "OldName" take 2'
                    )
                },
            ],
        ),
    )

    for identity, responses, expected_args in cases:
        reader = ScriptedReader(
            {"ak.wwise.core.object.get": copy.deepcopy(responses)}
        )
        prepare_operation(
            parse_operation_request(
                request(
                    "object.setNotes",
                    {"object": identity, "value": "after"},
                )
            ),
            read_call=reader,
        )
        assert [call[1] for call in reader.calls] == expected_args


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


def test_confirmed_role_guard_deduplicates_guids_into_one_bounded_read() -> None:
    source = object_row()
    target = object_row(
        object_id=TARGET_GUID,
        name="Target",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Target",
        parent="{master-workunit}",
    )
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.set",
        "resolved_roles": {
            "objects[0].object": {"object": GUID, "row": source},
            "objects[0].references[0].target": {
                "object": TARGET_GUID,
                "row": target,
            },
            "objects[0].children[0].references[0].target": {
                "object": TARGET_GUID,
                "row": target,
            },
        },
    }
    reader = ScriptedReader(
        {"ak.wwise.core.object.get": [{"return": [target, source]}]}
    )

    validation = validate_prepared_roles(prepared, read_call=reader)

    assert validation["status"] == "valid"
    assert reader.calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [GUID, TARGET_GUID]}},
            {"return": ["id", "name", "type", "path", "parent", "notes"]},
        )
    ]
    assert next(
        item
        for item in validation["assertions"]
        if item["name"] == "resolved role GUID batch is exact"
    )["passed"] is True
    assert len(
        [
            item
            for item in validation["assertions"]
            if item["name"].endswith("resolves exactly once")
        ]
    ) == 3


@pytest.mark.parametrize(
    ("case", "rows", "evidence_field"),
    (
        ("missing", [object_row()], "missing_ids"),
        (
            "duplicate",
            [
                object_row(),
                object_row(object_id=TARGET_GUID, name="Target"),
                object_row(object_id=TARGET_GUID, name="Target"),
            ],
            "duplicate_ids",
        ),
        (
            "extra",
            [
                object_row(),
                object_row(object_id=TARGET_GUID, name="Target"),
                object_row(object_id=PARENT_GUID, name="Unexpected"),
            ],
            "extra_rows",
        ),
        (
            "malformed",
            [
                object_row(),
                object_row(object_id=TARGET_GUID, name="Target"),
                {"id": None, "name": "Malformed"},
            ],
            "malformed_rows",
        ),
    ),
)
def test_confirmed_role_guard_rejects_non_exact_batched_result_sets(
    case: str,
    rows: list[Mapping[str, Any]],
    evidence_field: str,
) -> None:
    del case
    target = object_row(object_id=TARGET_GUID, name="Target")
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.set",
        "resolved_roles": {
            "source": {"object": GUID, "row": object_row()},
            "target": {"object": TARGET_GUID, "row": target},
        },
    }

    validation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": rows}]}
        ),
    )

    assert validation["status"] == "repreview_required"
    assertion = next(
        item
        for item in validation["assertions"]
        if item["name"] == "resolved role GUID batch is exact"
    )
    assert assertion["passed"] is False
    assert assertion["evidence"][evidence_field]


def test_confirmed_role_guard_rejects_more_than_4096_unique_guids_before_read() -> None:
    roles = {}
    for index in range(1, 4098):
        object_id = f"{{00000000-0000-0000-0000-{index:012X}}}"
        roles[f"objects[{index - 1}]"] = {
            "object": object_id,
            "row": {"id": object_id},
        }
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.set",
        "resolved_roles": roles,
    }
    reader = ScriptedReader({})

    with pytest.raises(OperationContractError) as caught:
        validate_prepared_roles(prepared, read_call=reader)

    assert caught.value.error_code == "IDENTITY_READ_LIMIT_EXCEEDED"
    assert caught.value.details == {"count": 4097, "limit": 4096}
    assert reader.calls == []


def test_confirmed_role_guard_rejects_field_drift_after_exact_batched_read() -> None:
    target = object_row(object_id=TARGET_GUID, name="Target")
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.set",
        "resolved_roles": {
            "source": {"object": GUID, "row": object_row()},
            "target": {"object": TARGET_GUID, "row": target},
        },
    }
    drifted_target = {
        **target,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\MovedTarget",
    }

    validation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [object_row(), drifted_target]}
                ]
            }
        ),
    )

    assert validation["status"] == "repreview_required"
    assert next(
        item
        for item in validation["assertions"]
        if item["name"] == "resolved role GUID batch is exact"
    )["passed"] is True
    assert next(
        item
        for item in validation["assertions"]
        if item["name"] == "target.path unchanged"
    )["passed"] is False


def test_legacy_created_guid_present_prepared_preview_remains_verifiable_for_compatibility() -> None:
    created_id = "{44444444-4444-4444-4444-444444444444}"
    prepared_create = _legacy_created_guid_present_prepared_preview_compatibility_fixture(
        expected={
            "name": "Created",
            "requested_type": "ActorMixer",
            "parent_id": PARENT_GUID,
            "notes": "stable",
        }
    )
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


def test_delete_property_and_reference_verifiers_have_typed_outcomes() -> None:
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
            "objectType": "Sound",
            "@Volume": -6.0,
            "@OutputBus": TARGET_GUID,
        },
        {
            "objectPath": r"<Sound>Inline\<AudioFileSource>inline",
            "importLocation": import_path,
            "audioFileBase64": (
                "SFX\\inline.wav|" + base64.b64encode(inline_wav).decode("ascii")
            ),
        },
    ]
    preview_metadata = prepared["semantic_preview"]["envelope"]["metadata"]
    assert preview_metadata["target_count"] == 1
    assert preview_metadata["native_row_count"] == 2
    assert "@Volume" in dispatch["options"]["return"]
    assert "@OutputBus" in dispatch["options"]["return"]
    target = prepared["verification_plan"]["targets"][0]
    assert target["canonical_target_path"] == target_path
    assert target["metadata_object_type"] == "Sound"
    assert target["metadata_class_id"] == 65552
    assert target["explicit_audio_file_source_pre_state_rows"] == []
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


def test_audio_import_native_materializer_partitions_sound_and_source_fields() -> None:
    sound_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
        r"\<Random Container>Weapons\<Sound SFX>Rifle_Close"
    )
    source_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
        r"\Weapons\Rifle\Rifle_Close\weapon_rifle_close"
    )

    dispatch, mapping = _materialize_audio_import_dynamic_rows(
        dispatch_args={
            "importOperation": "createNew",
            "imports": [
                {
                    "objectPath": sound_path,
                    "objectType": "Sound SFX",
                    "audioFile": "/fixtures/weapon_rifle_close.wav",
                    "importLanguage": "SFX",
                    "originalsSubFolder": "Weapons/Rifle",
                    "notes": "Sound notes",
                    "audioSourceNotes": "Source notes",
                    "event": r"\Events\Default Work Unit\Play_Rifle_Close",
                    "dialogueEvent": "Dialogue directive",
                    "switchAssignation": "Switch directive",
                }
            ],
        },
        targets=[
            {
                "canonical_target_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit"
                    r"\Weapons\Rifle\Rifle_Close"
                ),
                "metadata_object_type": "Sound",
                "media_expected": True,
                "expected_audio_file_source_result_path": source_path,
                "requested_notes_destination": "target_object",
                "validated_properties": [
                    {
                        "name": "IsLoopingEnabled",
                        "value": True,
                        "metadata_type": "bool",
                    },
                    {
                        "name": "MaxSoundPerInstance",
                        "value": 5,
                        "metadata_type": "int16",
                    },
                ],
                "validated_references": [
                    {"name": "OutputBus", "target_id": TARGET_GUID}
                ],
            }
        ],
    )

    assert dispatch["imports"] == [
        {
            "objectPath": sound_path,
            "objectType": "Sound SFX",
            "notes": "Sound notes",
            "event": r"\Events\Default Work Unit\Play_Rifle_Close",
            "dialogueEvent": "Dialogue directive",
            "switchAssignation": "Switch directive",
            "@IsLoopingEnabled": True,
            "@MaxSoundPerInstance": 5,
            "@OutputBus": TARGET_GUID,
        },
        {
            "objectPath": sound_path
            + r"\<AudioFileSource>weapon_rifle_close",
            "audioFile": "/fixtures/weapon_rifle_close.wav",
            "importLanguage": "SFX",
            "originalsSubFolder": "Weapons/Rifle",
            "notes": "Source notes",
        },
    ]
    assert mapping == [
        {
            "logical_index": 0,
            "native_rows": [
                {
                    "native_index": 0,
                    "kind": "sound_structure",
                    "object_path": sound_path,
                },
                {
                    "native_index": 1,
                    "kind": "audio_file_source_media",
                    "object_path": sound_path
                    + r"\<AudioFileSource>weapon_rifle_close",
                    "canonical_result_path": source_path,
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    ("notes_destination", "expected_structure_notes", "expected_source_notes"),
    [
        ("target_object", "Logical notes", None),
        ("audio_file_source", None, "Logical notes"),
    ],
)
def test_audio_import_native_materializer_routes_notes_from_preflight(
    notes_destination: str,
    expected_structure_notes: str | None,
    expected_source_notes: str | None,
) -> None:
    target_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\Imported\NotesTarget"
    )
    object_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\Imported"
        r"\<Sound SFX>NotesTarget"
    )

    dispatch, _ = _materialize_audio_import_dynamic_rows(
        dispatch_args={
            "imports": [
                {
                    "objectPath": object_path,
                    "audioFile": "/fixtures/notes.wav",
                    "notes": "Logical notes",
                }
            ]
        },
        targets=[
            {
                "canonical_target_path": target_path,
                "metadata_object_type": "Sound",
                "media_expected": True,
                "expected_audio_file_source_result_path": target_path
                + r"\notes",
                "requested_notes_destination": notes_destination,
                "validated_properties": [
                    {
                        "name": "IsLoopingEnabled",
                        "value": True,
                        "metadata_type": "bool",
                    }
                ],
                "validated_references": [],
            }
        ],
    )

    structure, source = dispatch["imports"]
    assert structure.get("notes") == expected_structure_notes
    assert source.get("notes") == expected_source_notes
    assert "audioSourceNotes" not in structure
    assert "audioSourceNotes" not in source


def test_audio_import_native_materializer_keeps_structure_only_dynamic_row_single() -> None:
    object_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound SFX>Silent"
    )
    dispatch, mapping = _materialize_audio_import_dynamic_rows(
        dispatch_args={"imports": [{"objectPath": object_path}]},
        targets=[
            {
                "canonical_target_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit\Silent"
                ),
                "metadata_object_type": "Sound",
                "media_expected": False,
                "validated_properties": [
                    {"name": "Volume", "value": -6.0, "metadata_type": "Real32"}
                ],
                "validated_references": [],
            }
        ],
    )

    assert dispatch["imports"] == [
        {"objectPath": object_path, "@Volume": -6.0}
    ]
    assert mapping[0]["native_rows"][0]["kind"] == "single"


@pytest.mark.parametrize(
    ("metadata_type", "source_path"),
    [
        ("MusicTrack", r"\Interactive Music Hierarchy\Default Work Unit\Track\clip"),
        ("Sound", None),
    ],
)
def test_audio_import_native_materializer_rejects_unsealed_media_topology(
    metadata_type: str,
    source_path: str | None,
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        _materialize_audio_import_dynamic_rows(
            dispatch_args={
                "imports": [
                    {
                        "objectPath": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit"
                            r"\<Sound SFX>Unsafe"
                        ),
                        "audioFile": "/fixtures/unsafe.mid",
                    }
                ]
            },
            targets=[
                {
                    "canonical_target_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Unsafe"
                    ),
                    "metadata_object_type": metadata_type,
                    "media_expected": True,
                    "expected_audio_file_source_result_path": source_path,
                    "validated_properties": [
                        {
                            "name": "Volume",
                            "value": -6.0,
                            "metadata_type": "Real32",
                        }
                    ],
                    "validated_references": [],
                }
            ],
        )

    assert rejected.value.error_code == "IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED"


def test_audio_import_native_materializer_preserves_logical_order_for_two_rows() -> None:
    base = r"\Actor-Mixer Hierarchy\Default Work Unit\Batch"
    logical_rows = []
    targets = []
    for ordinal in (1, 2):
        logical_rows.append(
            {
                "objectPath": f"{base}\\<Sound SFX>Sound_{ordinal}",
                "audioFile": f"/fixtures/source_{ordinal}.wav",
            }
        )
        targets.append(
            {
                "canonical_target_path": f"{base}\\Sound_{ordinal}",
                "metadata_object_type": "Sound",
                "media_expected": True,
                "expected_audio_file_source_result_path": (
                    f"{base}\\Sound_{ordinal}\\source_{ordinal}"
                ),
                "requested_notes_destination": "target_object",
                "validated_properties": [
                    {
                        "name": "IsLoopingEnabled",
                        "value": True,
                        "metadata_type": "bool",
                    }
                ],
                "validated_references": [],
            }
        )

    dispatch, mapping = _materialize_audio_import_dynamic_rows(
        dispatch_args={"imports": logical_rows},
        targets=targets,
    )

    assert [row["objectPath"] for row in dispatch["imports"]] == [
        f"{base}\\<Sound SFX>Sound_1",
        f"{base}\\<Sound SFX>Sound_1\\<AudioFileSource>source_1",
        f"{base}\\<Sound SFX>Sound_2",
        f"{base}\\<Sound SFX>Sound_2\\<AudioFileSource>source_2",
    ]
    assert [
        row["native_index"]
        for item in mapping
        for row in item["native_rows"]
    ] == [0, 1, 2, 3]


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
def test_legacy_audio_import_prepared_preview_compatibility_uses_objects_only_result(
    version: str,
) -> None:
    created_id = "{44444444-4444-4444-4444-444444444444}"
    target_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Imported"
    created_row = object_row(object_id=created_id, name="Imported", object_type="Sound", path=target_path)
    prepared = _legacy_audio_import_created_objects_prepared_preview_compatibility_fixture(
        version=version,
        targets=[
            {
                "index": 0,
                "canonical_target_path": target_path,
                "requested_type": "Sound",
            }
        ],
    )
    result = verify_prepared_operation(
        prepared,
        execution_result={"result": {"objects": [created_row]}},
        read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [created_row]}]}),
    )

    assert result.status == "verified"
    assert "audio import log has no errors" not in {item["name"] for item in result.assertions}


def test_legacy_audio_import_prepared_preview_compatibility_rejects_error_log() -> None:
    prepared = _legacy_audio_import_created_objects_prepared_preview_compatibility_fixture(
        version="2025.1",
        targets=[],
    )
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
def test_legacy_audio_import_prepared_preview_compatibility_rejects_malformed_log(
    bad_log: Mapping[str, Any],
) -> None:
    prepared = _legacy_audio_import_created_objects_prepared_preview_compatibility_fixture(
        version="2025.1",
        targets=[],
    )
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


def test_audio_import_schema_requires_originals_subfolder_to_be_user_supplied() -> None:
    operation = describe_operation("audio.import").as_dict(version="2022.1")
    rows = operation["argument_contract"]["properties"]["imports"]
    description = rows["items"]["properties"]["originals_subfolder"]["description"]

    assert "supplied explicitly by the user" in description
    assert "otherwise omit this field" in description
    assert "Never infer it" in description


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


def test_audio_import_2025_accepts_property_container_as_deepest_path_anchor() -> None:
    parent_path = (
        r"\Containers\Default Work Unit\IntegrationLab"
    )
    target_path = parent_path + r"\Weather_Interactive"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="IntegrationLab",
        object_type="PropertyContainer",
        path=parent_path,
        parent="{containers-work-unit}",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {
                            "classId": 1,
                            "name": "PropertyContainer",
                            "type": "WObject",
                        }
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "audio.import",
                {
                    "imports": [
                        {
                            "object_path": target_path,
                            "object_type": "ActorMixer",
                        }
                    ]
                },
                version="2025.1",
            )
        ),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"]["args"]["imports"] == [
        {
            "objectPath": target_path,
            "objectType": "ActorMixer",
        }
    ]
    assert prepared["resolved_roles"]["targets[0].anchor"]["object"] == (
        PARENT_GUID
    )


@pytest.mark.parametrize("location_scope", ["defaults", "row"])
def test_audio_import_2025_accepts_property_container_import_location(
    location_scope: str,
) -> None:
    parent_path = (
        r"\Containers\Default Work Unit\IntegrationLab"
    )
    target_path = parent_path + r"\Weather_Interactive"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="IntegrationLab",
        object_type="PropertyContainer",
        path=parent_path,
        parent="{containers-work-unit}",
    )
    import_location = {"kind": "path", "value": parent_path}
    import_row: dict[str, Any] = {
        "object_path": r"<ActorMixer>Weather_Interactive",
        "object_type": "ActorMixer",
    }
    arguments: dict[str, Any] = {"imports": [import_row]}
    if location_scope == "defaults":
        arguments["defaults"] = {"import_location": import_location}
        role = "defaults.import_location"
    else:
        import_row["import_location"] = import_location
        role = "imports[0].import_location"
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {
                            "classId": 1,
                            "name": "PropertyContainer",
                            "type": "WObject",
                        }
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": [parent_row]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "audio.import",
                arguments,
                version="2025.1",
            )
        ),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"]["args"]["imports"] == [
        {
            "objectPath": r"<ActorMixer>Weather_Interactive",
            "objectType": "ActorMixer",
            "importLocation": parent_path,
        }
    ]
    assert prepared["verification_plan"]["targets"][0][
        "canonical_target_path"
    ] == target_path
    assert prepared["resolved_roles"][role]["object"] == PARENT_GUID


def test_tab_import_2025_accepts_property_container_import_location(
    tmp_path: Path,
) -> None:
    parent_path = (
        r"\Containers\Default Work Unit\IntegrationLab"
    )
    target_path = parent_path + r"\Weather_Interactive"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="IntegrationLab",
        object_type="PropertyContainer",
        path=parent_path,
        parent="{containers-work-unit}",
    )
    import_file = tmp_path / "structure.tsv"
    import_file.write_text(
        "Object Path\tObject Type\n"
        "<ActorMixer>Weather_Interactive\tActorMixer\n",
        encoding="utf-8",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {
                            "classId": 1,
                            "name": "PropertyContainer",
                            "type": "WObject",
                        }
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": [parent_row]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "audio.importTabDelimited",
                {
                    "import_file": str(import_file),
                    "import_location": {
                        "kind": "path",
                        "value": parent_path,
                    },
                    "import_language": "SFX",
                },
                version="2025.1",
            )
        ),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"]["args"]["importLocation"] == PARENT_GUID
    assert prepared["verification_plan"]["targets"][0][
        "canonical_target_path"
    ] == target_path
    assert prepared["resolved_roles"]["import_location"]["object"] == (
        PARENT_GUID
    )


@pytest.mark.parametrize(
    "version",
    ["2021.1", "2022.1", "2023.1", "2024.1"],
)
def test_audio_import_old_versions_reject_property_container_path_anchor(
    version: str,
) -> None:
    parent_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\IntegrationLab"
    )
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="IntegrationLab",
        object_type="PropertyContainer",
        path=parent_path,
        parent="{actor-work-unit}",
    )
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
            ],
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
            ],
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
                                    parent_path
                                    + r"\Weather_Interactive"
                                ),
                                "object_type": "ActorMixer",
                            }
                        ]
                    },
                    version=version,
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "INVALID_TARGET_TYPE"
    assert rejected.value.details["version"] == version
    assert "PropertyContainer" not in rejected.value.details[
        "allowed_types"
    ]


def test_audio_import_2025_resolves_actor_mixer_metadata_through_property_container() -> None:
    parent_path = r"\Containers\Default Work Unit"
    target_path = parent_path + r"\Weather_Interactive"
    parent_row = object_row(
        object_id=PARENT_GUID,
        name="Default Work Unit",
        object_type="WorkUnit",
        path=parent_path,
        parent="{containers-root}",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {
                            "classId": 1,
                            "name": "PropertyContainer",
                            "type": "WObject",
                        }
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [parent_row]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            request(
                "audio.import",
                {
                    "imports": [
                        {
                            "object_path": target_path,
                            "object_type": "ActorMixer",
                        }
                    ]
                },
                version="2025.1",
            )
        ),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"]["args"]["imports"] == [
        {
            "objectPath": target_path,
            "objectType": "ActorMixer",
        }
    ]
    target = prepared["verification_plan"]["targets"][0]
    assert target["requested_object_type"] == "ActorMixer"
    assert target["metadata_object_type"] == "PropertyContainer"
    assert target["metadata_class_id"] == 1
    assert reader.calls[0] == (
        "ak.wwise.core.object.getTypes",
        {},
        {},
    )


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
                    {"return": [soundbank_row, inclusion_row]},
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
                    {"return": [soundbank_row, inclusion_row]},
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
                    {
                        "return": [
                            container_row,
                            child_row,
                            state_row,
                            group_row,
                        ]
                    },
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

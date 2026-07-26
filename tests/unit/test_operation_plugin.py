from __future__ import annotations

import json
import math
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_plugin import (  # pyright: ignore[reportMissingImports]
    GET_PROPERTY_INFO_URI,
    OBJECT_SET_URI,
    PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS,
    PLUGIN_EFFECT_SLOT_READBACK_FIELDS,
    PLUGIN_LANGUAGE_READBACK_FIELD,
    PLUGIN_VERIFICATION_FIELDS,
    SUPPORTED_PLUGIN_VERSIONS,
    WWISE_2022_EFFECT_FIELDS,
    PluginOperationContractError,
    ValidatedPluginProperty,
    build_plugin_creation_plan,
    normalize_plugin_creation,
    plugin_property_metadata_requests,
    plugin_verification_fields,
    select_free_2022_effect_field,
    validate_plugin_property_metadata,
    verify_created_plugin_row,
)


TARGET_ID = "{11111111-1111-1111-1111-111111111111}"
SLOT_ID = "{22222222-2222-2222-2222-222222222222}"
PLUGIN_ID = "{33333333-3333-3333-3333-333333333333}"
OLD_PLUGIN_ID = "{44444444-4444-4444-4444-444444444444}"
OLD_SLOT_ID = "{55555555-5555-5555-5555-555555555555}"


def _source_request(
    *,
    properties: list[dict[str, Any]] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "source",
        "name": "Generated Tone",
        "class_id": 123_456,
        "notes": "created through the closed plug-in operation",
        "platform": "Windows",
    }
    if properties is not None:
        result["properties"] = properties
    if language is not None:
        result["language"] = language
    return result


def _effect_request(*, properties: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "effect",
        "name": "Room",
        "class_id": 7_733_251,
    }
    if properties is not None:
        result["properties"] = properties
    return result


def _empty_2022_slots(**overrides: Any) -> dict[str, Any]:
    result = {field: None for field in WWISE_2022_EFFECT_FIELDS}
    result.update(overrides)
    return result


def _readback_view(descriptor: Any) -> dict[str, Any]:
    return {
        "fields": list(plugin_verification_fields(descriptor)),
        "language": descriptor.language,
        "platform": descriptor.platform,
    }


def _source_placement() -> dict[str, Any]:
    return {"kind": "source_child"}


def _appended_effect_placement(
    *,
    slot_id: str = SLOT_ID,
    effect_id: str = PLUGIN_ID,
    preexisting_slot_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "effect_slot_append",
        "preexisting_effect_slot_ids": (
            [OLD_SLOT_ID]
            if preexisting_slot_ids is None
            else preexisting_slot_ids
        ),
        "created_effect_slot": {
            "id": slot_id,
            "name": "",
            "type": "EffectSlot",
            "parent": {"id": TARGET_ID},
            "owner": {"id": TARGET_ID},
            "@Effect": {"id": effect_id},
        },
    }


def _fixed_effect_placement(
    *,
    selected: str = "@Effect1",
    selected_effect_id: str = PLUGIN_ID,
    before: dict[str, Any] | None = None,
    post_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pre_state = (
        _empty_2022_slots(**{"@Effect0": {"id": OLD_PLUGIN_ID}})
        if before is None
        else before
    )
    post = {"id": TARGET_ID, **pre_state}
    post[selected] = {"id": selected_effect_id}
    if post_overrides:
        post.update(post_overrides)
    return {
        "kind": "fixed_effect_reference",
        "selected_effect_field": selected,
        "pre_effect_references": pre_state,
        "target_post_readback": post,
    }


@pytest.mark.parametrize("version", SUPPORTED_PLUGIN_VERSIONS)
@pytest.mark.parametrize("target_type", ("Sound", "Voice"))
def test_source_plugin_is_created_only_as_a_sound_or_voice_child(
    version: str,
    target_type: str,
) -> None:
    plan = build_plugin_creation_plan(
        version=version,
        target_id=TARGET_ID,
        target_type=target_type,
        request=_source_request(
            properties=[
                {"name": "Frequency", "value": 440.0},
                {"name": "Enabled", "value": True},
            ]
        ),
        property_metadata=[
            {"name": "Frequency", "type": "Real32"},
            {"name": "Enabled", "type": "Boolean"},
        ],
    ).as_dict()

    assert plan["dispatch"] == {
        "uri": OBJECT_SET_URI,
        "args": {
            "objects": [
                {
                    "object": TARGET_ID,
                    "onNameConflict": "fail",
                    "children": [
                        {
                            "type": "Source",
                            "name": "Generated Tone",
                            "classId": 123_456,
                            "notes": "created through the closed plug-in operation",
                            "platform": "Windows",
                            "@Frequency": 440.0,
                            "@Enabled": True,
                        }
                    ],
                }
            ],
            "autoAddToSourceControl": False,
        },
        "options": {},
    }
    assert plan["placement"] == {
        "kind": "source_child",
        "collection": "children",
        "create_only": True,
        "on_name_conflict": "fail",
        "raw_replace_all_allowed": False,
        "replace_existing_allowed": False,
    }
    assert plan["verification"]["readback_fields"] == [
        *PLUGIN_VERIFICATION_FIELDS,
        "notes",
        "@Frequency",
        "@Enabled",
    ]
    assert plan["verification"]["readback_view"] == {
        "language": None,
        "platform": "Windows",
    }
    assert plan["verification"]["expected_plugin"]["properties"] == [
        {
            "name": "Frequency",
            "value": 440.0,
            "metadata_type": "Real32",
        },
        {
            "name": "Enabled",
            "value": True,
            "metadata_type": "Boolean",
        },
    ]
    assert plan["verification"]["expected_plugin"]["parent"] == {
        "kind": "id",
        "value": TARGET_ID,
    }
    assert plan["verification"]["expected_plugin"]["owner"] == {
        "kind": "id",
        "value": TARGET_ID,
    }


@pytest.mark.parametrize("version", SUPPORTED_PLUGIN_VERSIONS)
def test_source_language_is_preserved_in_every_supported_version(
    version: str,
) -> None:
    plan = build_plugin_creation_plan(
        version=version,
        target_id=TARGET_ID,
        target_type="Voice",
        request=_source_request(language="English(US)"),
    ).as_dict()

    source = plan["dispatch"]["args"]["objects"][0]["children"][0]
    assert source["language"] == "English(US)"
    assert plan["plugin"]["language"] == "English(US)"
    assert plan["verification"]["readback_fields"] == [
        *PLUGIN_VERIFICATION_FIELDS,
        "notes",
        PLUGIN_LANGUAGE_READBACK_FIELD,
    ]
    assert plan["verification"]["readback_view"] == {
        "language": "English(US)",
        "platform": "Windows",
    }


def test_effect_language_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(
        PluginOperationContractError,
        match="only for Source",
    ) as caught:
        normalize_plugin_creation(
            {
                **_effect_request(),
                "language": "SFX",
            }
        )
    assert caught.value.error_code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("target_type", ("ActorMixer", "EffectSlot", "Bus"))
def test_source_plugin_rejects_non_sound_voice_targets(target_type: str) -> None:
    with pytest.raises(
        PluginOperationContractError,
        match="Sound or Voice",
    ) as caught:
        build_plugin_creation_plan(
            version="2025.1",
            target_id=TARGET_ID,
            target_type=target_type,
            request=_source_request(),
        )
    assert caught.value.error_code == "INVALID_SOURCE_TARGET"


def test_2022_effect_uses_first_proven_empty_fixed_slot_not_a_child() -> None:
    occupied = {"id": OLD_PLUGIN_ID}
    plan = build_plugin_creation_plan(
        version="2022.1",
        target_id=TARGET_ID,
        target_type="ActorMixer",
        request=_effect_request(),
        effect_slots_2022=_empty_2022_slots(**{"@Effect0": occupied}),
    ).as_dict()

    assert plan["dispatch"] == {
        "uri": OBJECT_SET_URI,
        "args": {
            "objects": [
                {
                    "object": TARGET_ID,
                    "@Effect1": {
                        "type": "Effect",
                        "name": "Room",
                        "classId": 7_733_251,
                    },
                }
            ],
            "autoAddToSourceControl": False,
        },
        "options": {},
    }
    object_spec = plan["dispatch"]["args"]["objects"][0]
    assert "children" not in object_spec
    assert "@Effects" not in object_spec
    assert "listMode" not in object_spec
    assert plan["placement"] == {
        "kind": "fixed_effect_reference",
        "collection": "@Effect1",
        "effect_slot": "@Effect1",
        "create_only": True,
        "requires_proven_empty_slot": True,
        "raw_replace_all_allowed": False,
        "replace_existing_allowed": False,
    }


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_2023_and_later_effect_appends_one_effect_slot(version: str) -> None:
    plan = build_plugin_creation_plan(
        version=version,
        target_id=TARGET_ID,
        target_type="ActorMixer",
        request=_effect_request(),
    ).as_dict()

    assert plan["dispatch"] == {
        "uri": OBJECT_SET_URI,
        "args": {
            "objects": [
                {
                    "object": TARGET_ID,
                    "listMode": "append",
                    "@Effects": [
                        {
                            "type": "EffectSlot",
                            "name": "",
                            "@Effect": {
                                "type": "Effect",
                                "name": "Room",
                                "classId": 7_733_251,
                            },
                        }
                    ],
                }
            ],
            "autoAddToSourceControl": False,
        },
        "options": {},
    }
    object_spec = plan["dispatch"]["args"]["objects"][0]
    assert "children" not in object_spec
    assert not any(field in object_spec for field in WWISE_2022_EFFECT_FIELDS)
    assert plan["placement"] == {
        "kind": "effect_slot_append",
        "collection": "@Effects",
        "list_mode": "append",
        "effect_slot_type": "EffectSlot",
        "create_only": True,
        "raw_replace_all_allowed": False,
        "replace_existing_allowed": False,
    }
    assert plan["verification"]["expected_plugin"]["parent"] == {
        "kind": "created_effect_slot"
    }
    assert plan["verification"]["expected_plugin"]["owner"] == {
        "kind": "id",
        "value": TARGET_ID,
    }


def test_2022_effect_requires_complete_snapshot_and_never_replaces() -> None:
    assert select_free_2022_effect_field(_empty_2022_slots()) == "@Effect0"

    with pytest.raises(
        PluginOperationContractError,
        match="requires all four",
    ) as missing:
        select_free_2022_effect_field(None)
    assert missing.value.error_code == "EFFECT_SLOT_SNAPSHOT_REQUIRED"

    with pytest.raises(
        PluginOperationContractError,
        match="incomplete",
    ) as partial:
        select_free_2022_effect_field(
            {
                "@Effect0": None,
                "@Effect1": None,
                "@Effect2": None,
            }
        )
    assert partial.value.error_code == "INVALID_EFFECT_SLOT_SNAPSHOT"

    occupied = {field: {"id": OLD_PLUGIN_ID} for field in WWISE_2022_EFFECT_FIELDS}
    with pytest.raises(
        PluginOperationContractError,
        match="never replaces",
    ) as full:
        select_free_2022_effect_field(occupied)
    assert full.value.error_code == "NO_FREE_EFFECT_SLOT"


def test_version_specific_effect_evidence_cannot_cross_lanes() -> None:
    with pytest.raises(PluginOperationContractError) as old:
        build_plugin_creation_plan(
            version="2021.1",
            target_id=TARGET_ID,
            target_type="ActorMixer",
            request=_effect_request(),
        )
    assert old.value.error_code == "UNAVAILABLE_IN_VERSION"

    with pytest.raises(PluginOperationContractError) as current:
        build_plugin_creation_plan(
            version="2025.1",
            target_id=TARGET_ID,
            target_type="ActorMixer",
            request=_effect_request(),
            effect_slots_2022=_empty_2022_slots(),
        )
    assert current.value.error_code == "UNEXPECTED_EFFECT_SLOT_SNAPSHOT"


def test_property_names_and_types_require_live_class_id_scoped_metadata() -> None:
    descriptor = normalize_plugin_creation(
        _effect_request(properties=[{"name": "WetDryMix", "value": 25.0}])
    )
    assert plugin_property_metadata_requests(descriptor) == (
        {
            "uri": GET_PROPERTY_INFO_URI,
            "args": {
                "classId": 7_733_251,
                "property": "WetDryMix",
            },
            "options": {},
        },
    )

    with pytest.raises(
        PluginOperationContractError,
        match="requires a live getPropertyInfo",
    ) as required:
        validate_plugin_property_metadata(descriptor, None)
    assert required.value.error_code == "PROPERTY_METADATA_REQUIRED"

    validated = validate_plugin_property_metadata(
        descriptor,
        [{"name": "WetDryMix", "type": "Real32"}],
    )
    assert [item.as_dict() for item in validated] == [
        {
            "name": "WetDryMix",
            "value": 25.0,
            "metadata_type": "Real32",
        }
    ]


@pytest.mark.parametrize(
    ("metadata", "error_code"),
    (
        ([{"name": "Other", "type": "Real32"}], "INVALID_PROPERTY_METADATA"),
        ([{"name": "WetDryMix"}], "INVALID_PROPERTY_METADATA"),
        ([{"name": "WetDryMix", "type": "Reference"}], "UNSUPPORTED_PROPERTY_TYPE"),
        ([{"name": "WetDryMix", "type": "Boolean"}], "INVALID_PROPERTY_VALUE"),
    ),
)
def test_property_metadata_mismatch_fails_before_materialization(
    metadata: list[dict[str, Any]],
    error_code: str,
) -> None:
    descriptor = normalize_plugin_creation(
        _effect_request(properties=[{"name": "WetDryMix", "value": 25.0}])
    )
    with pytest.raises(PluginOperationContractError) as caught:
        validate_plugin_property_metadata(descriptor, metadata)
    assert caught.value.error_code == error_code


def test_no_plan_contains_replace_all_or_replace_existing_effect_semantics() -> None:
    plans = [
        build_plugin_creation_plan(
            version="2022.1",
            target_id=TARGET_ID,
            target_type="Sound",
            request=_source_request(),
        ).as_dict(),
        build_plugin_creation_plan(
            version="2022.1",
            target_id=TARGET_ID,
            target_type="ActorMixer",
            request=_effect_request(),
            effect_slots_2022=_empty_2022_slots(),
        ).as_dict(),
        build_plugin_creation_plan(
            version="2025.1",
            target_id=TARGET_ID,
            target_type="ActorMixer",
            request=_effect_request(),
        ).as_dict(),
    ]
    encoded = json.dumps(plans, ensure_ascii=False)

    assert "replaceAll" not in encoded
    assert '"onNameConflict": "replace"' not in encoded
    assert all(
        plan["placement"]["replace_existing_allowed"] is False
        for plan in plans
    )


def test_verification_returns_exact_plugin_identity_state_view_and_slot() -> None:
    descriptor = normalize_plugin_creation(_effect_request())
    evidence = verify_created_plugin_row(
        descriptor,
        {
            "id": PLUGIN_ID,
            "name": "Room",
            "type": "Effect",
            "classId": 7_733_251,
            "parent": {"id": SLOT_ID, "name": ""},
            "owner": {"id": TARGET_ID, "name": "Owner"},
        },
        version="2025.1",
        expected_parent_id=SLOT_ID,
        expected_owner_id=TARGET_ID,
        validated_properties=(),
        preexisting_plugin_ids=(OLD_PLUGIN_ID,),
        readback_view=_readback_view(descriptor),
        placement_evidence=_appended_effect_placement(),
    )

    assert evidence.as_dict() == {
        "id": PLUGIN_ID,
        "name": "Room",
        "type": "Effect",
        "classId": 7_733_251,
        "parent": SLOT_ID,
        "owner": TARGET_ID,
        "readback_view": {
            "fields": list(PLUGIN_VERIFICATION_FIELDS),
            "language": None,
            "platform": None,
        },
        "requested_state": {
            "language": {"requested": False, "value": None},
            "notes": {"requested": False, "value": None},
            "platform": None,
            "properties": [],
        },
        "placement": {
            "kind": "effect_slot_append",
            "effect_slot_id": SLOT_ID,
            "preexisting_effect_slot_ids": [OLD_SLOT_ID],
            "target_id": TARGET_ID,
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("name", "Wrong"),
        ("type", "Source"),
        ("classId", 1),
        ("parent", {"id": TARGET_ID}),
        ("owner", {"id": SLOT_ID}),
    ),
)
def test_verification_rejects_any_plugin_identity_or_topology_mismatch(
    field: str,
    value: Any,
) -> None:
    descriptor = normalize_plugin_creation(_effect_request())
    row: dict[str, Any] = {
        "id": PLUGIN_ID,
        "name": "Room",
        "type": "Effect",
        "classId": 7_733_251,
        "parent": {"id": SLOT_ID},
        "owner": {"id": TARGET_ID},
    }
    row[field] = value

    with pytest.raises(
        PluginOperationContractError,
        match="did not match",
    ) as caught:
        verify_created_plugin_row(
            descriptor,
            row,
            version="2025.1",
            expected_parent_id=SLOT_ID,
            expected_owner_id=TARGET_ID,
            validated_properties=(),
            preexisting_plugin_ids=(),
            readback_view=_readback_view(descriptor),
            placement_evidence=_appended_effect_placement(),
        )
    assert caught.value.error_code == "PLUGIN_READBACK_MISMATCH"


def test_verification_rejects_a_preexisting_plugin_id() -> None:
    descriptor = normalize_plugin_creation(_source_request())
    with pytest.raises(
        PluginOperationContractError,
        match="pre-existing",
    ) as caught:
        verify_created_plugin_row(
            descriptor,
            {
                "id": PLUGIN_ID,
                "name": "Generated Tone",
                "type": "Source",
                "classId": 123_456,
                "parent": TARGET_ID,
                "owner": TARGET_ID,
                "notes": "created through the closed plug-in operation",
            },
            version="2025.1",
            expected_parent_id=TARGET_ID,
            expected_owner_id=TARGET_ID,
            validated_properties=(),
            preexisting_plugin_ids=(PLUGIN_ID.lower(),),
            readback_view=_readback_view(descriptor),
            placement_evidence=_source_placement(),
        )
    assert caught.value.error_code == "PLUGIN_ID_NOT_NEW"


def test_verification_proves_requested_notes_language_properties_and_platform_view() -> None:
    descriptor = normalize_plugin_creation(
        _source_request(
            language="English(US)",
            properties=[
                {"name": "Frequency", "value": 440.0},
                {"name": "Enabled", "value": True},
                {"name": "Seed", "value": 7},
                {"name": "Label", "value": "tone"},
            ],
        )
    )
    validated = validate_plugin_property_metadata(
        descriptor,
        [
            {"name": "Frequency", "type": "Real32"},
            {"name": "Enabled", "type": "Boolean"},
            {"name": "Seed", "type": "Int32"},
            {"name": "Label", "type": "String"},
        ],
    )
    evidence = verify_created_plugin_row(
        descriptor,
        {
            "id": PLUGIN_ID,
            "name": "Generated Tone",
            "type": "Source",
            "classId": 123_456,
            "parent": {"id": TARGET_ID},
            "owner": {"id": TARGET_ID},
            "notes": "created through the closed plug-in operation",
            PLUGIN_LANGUAGE_READBACK_FIELD: {
                "id": "{66666666-6666-6666-6666-666666666666}",
                "name": "English(US)",
                "type": "Language",
            },
            "@Frequency": 440.00003,
            "@Enabled": True,
            "@Seed": 7,
            "@Label": "tone",
        },
        version="2024.1",
        expected_parent_id=TARGET_ID,
        expected_owner_id=TARGET_ID,
        validated_properties=validated,
        preexisting_plugin_ids=(OLD_PLUGIN_ID,),
        readback_view=_readback_view(descriptor),
        placement_evidence=_source_placement(),
    )

    assert evidence.requested_state == {
        "language": {"requested": True, "value": "English(US)"},
        "notes": {
            "requested": True,
            "value": "created through the closed plug-in operation",
        },
        "platform": "Windows",
        "properties": [
            {
                "field": "@Frequency",
                "metadata_type": "Real32",
                "value": 440.00003,
            },
            {
                "field": "@Enabled",
                "metadata_type": "Boolean",
                "value": True,
            },
            {
                "field": "@Seed",
                "metadata_type": "Int32",
                "value": 7,
            },
            {
                "field": "@Label",
                "metadata_type": "String",
                "value": "tone",
            },
        ],
    }


@pytest.mark.parametrize(
    ("field", "actual"),
    (
        ("notes", "wrong"),
        (PLUGIN_LANGUAGE_READBACK_FIELD, {"name": "Japanese"}),
        ("@Frequency", 441.0),
        ("@Enabled", 1),
        ("@Seed", 7.0),
        ("@Label", "Tone"),
    ),
)
def test_verification_rejects_requested_state_mismatch(
    field: str,
    actual: Any,
) -> None:
    descriptor = normalize_plugin_creation(
        _source_request(
            language="English(US)",
            properties=[
                {"name": "Frequency", "value": 440.0},
                {"name": "Enabled", "value": True},
                {"name": "Seed", "value": 7},
                {"name": "Label", "value": "tone"},
            ],
        )
    )
    validated = validate_plugin_property_metadata(
        descriptor,
        [
            {"name": "Frequency", "type": "Real32"},
            {"name": "Enabled", "type": "Boolean"},
            {"name": "Seed", "type": "Int32"},
            {"name": "Label", "type": "String"},
        ],
    )
    row: dict[str, Any] = {
        "id": PLUGIN_ID,
        "name": "Generated Tone",
        "type": "Source",
        "classId": 123_456,
        "parent": TARGET_ID,
        "owner": TARGET_ID,
        "notes": "created through the closed plug-in operation",
        PLUGIN_LANGUAGE_READBACK_FIELD: {"name": "English(US)"},
        "@Frequency": 440.0,
        "@Enabled": True,
        "@Seed": 7,
        "@Label": "tone",
    }
    row[field] = actual

    with pytest.raises(PluginOperationContractError) as caught:
        verify_created_plugin_row(
            descriptor,
            row,
            version="2025.1",
            expected_parent_id=TARGET_ID,
            expected_owner_id=TARGET_ID,
            validated_properties=validated,
            preexisting_plugin_ids=(),
            readback_view=_readback_view(descriptor),
            placement_evidence=_source_placement(),
        )
    assert caught.value.error_code == "PLUGIN_REQUESTED_STATE_MISMATCH"


def test_verification_rejects_wrong_platform_or_language_readback_view() -> None:
    descriptor = normalize_plugin_creation(
        _source_request(language="English(US)")
    )
    row = {
        "id": PLUGIN_ID,
        "name": "Generated Tone",
        "type": "Source",
        "classId": 123_456,
        "parent": TARGET_ID,
        "owner": TARGET_ID,
        "notes": "created through the closed plug-in operation",
        PLUGIN_LANGUAGE_READBACK_FIELD: {"name": "English(US)"},
    }
    for wrong_view in (
        {
            **_readback_view(descriptor),
            "platform": "Mac",
        },
        {
            **_readback_view(descriptor),
            "language": "SFX",
        },
        {
            **_readback_view(descriptor),
            "fields": list(PLUGIN_VERIFICATION_FIELDS),
        },
    ):
        with pytest.raises(PluginOperationContractError) as caught:
            verify_created_plugin_row(
                descriptor,
                row,
                version="2025.1",
                expected_parent_id=TARGET_ID,
                expected_owner_id=TARGET_ID,
                validated_properties=(),
                preexisting_plugin_ids=(),
                readback_view=wrong_view,
                placement_evidence=_source_placement(),
            )
        assert caught.value.error_code == "PLUGIN_READBACK_VIEW_MISMATCH"


def test_2022_effect_verification_binds_full_target_reference_post_read() -> None:
    descriptor = normalize_plugin_creation(_effect_request())
    placement = _fixed_effect_placement()
    evidence = verify_created_plugin_row(
        descriptor,
        {
            "id": PLUGIN_ID,
            "name": "Room",
            "type": "Effect",
            "classId": 7_733_251,
            "parent": TARGET_ID,
            "owner": TARGET_ID,
        },
        version="2022.1",
        expected_parent_id=TARGET_ID,
        expected_owner_id=TARGET_ID,
        validated_properties=(),
        preexisting_plugin_ids=(OLD_PLUGIN_ID,),
        readback_view=_readback_view(descriptor),
        placement_evidence=placement,
    )

    assert list(
        placement["target_post_readback"]
    ) == list(PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS)
    assert evidence.placement == {
        "kind": "fixed_effect_reference",
        "selected_effect_field": "@Effect1",
        "target_id": TARGET_ID,
        "target_post_references": {
            "@Effect0": OLD_PLUGIN_ID,
            "@Effect1": PLUGIN_ID,
            "@Effect2": None,
            "@Effect3": None,
        },
    }


@pytest.mark.parametrize(
    "placement",
    (
        _fixed_effect_placement(selected_effect_id=OLD_PLUGIN_ID),
        _fixed_effect_placement(
            post_overrides={"@Effect0": None},
        ),
        _fixed_effect_placement(
            before=_empty_2022_slots(
                **{"@Effect1": {"id": OLD_PLUGIN_ID}}
            ),
        ),
    ),
)
def test_2022_effect_verification_rejects_wrong_or_collateral_reference_state(
    placement: dict[str, Any],
) -> None:
    descriptor = normalize_plugin_creation(_effect_request())
    with pytest.raises(PluginOperationContractError) as caught:
        verify_created_plugin_row(
            descriptor,
            {
                "id": PLUGIN_ID,
                "name": "Room",
                "type": "Effect",
                "classId": 7_733_251,
                "parent": TARGET_ID,
                "owner": TARGET_ID,
            },
            version="2022.1",
            expected_parent_id=TARGET_ID,
            expected_owner_id=TARGET_ID,
            validated_properties=(),
            preexisting_plugin_ids=(OLD_PLUGIN_ID,),
            readback_view=_readback_view(descriptor),
            placement_evidence=placement,
        )
    assert caught.value.error_code in {
        "EFFECT_REFERENCE_READBACK_MISMATCH",
        "PLUGIN_PLACEMENT_MISMATCH",
    }


def test_2023_effect_verification_rejects_preexisting_slot_or_wrong_binding() -> None:
    descriptor = normalize_plugin_creation(_effect_request())
    cases = (
        (
            _appended_effect_placement(
                preexisting_slot_ids=[SLOT_ID],
            ),
            "EFFECT_SLOT_ID_NOT_NEW",
        ),
        (
            _appended_effect_placement(effect_id=OLD_PLUGIN_ID),
            "EFFECT_SLOT_READBACK_MISMATCH",
        ),
    )
    for placement, error_code in cases:
        with pytest.raises(PluginOperationContractError) as caught:
            verify_created_plugin_row(
                descriptor,
                {
                    "id": PLUGIN_ID,
                    "name": "Room",
                    "type": "Effect",
                    "classId": 7_733_251,
                    "parent": SLOT_ID,
                    "owner": TARGET_ID,
                },
                version="2023.1",
                expected_parent_id=SLOT_ID,
                expected_owner_id=TARGET_ID,
                validated_properties=(),
                preexisting_plugin_ids=(OLD_PLUGIN_ID,),
                readback_view=_readback_view(descriptor),
                placement_evidence=placement,
            )
        assert caught.value.error_code == error_code


def test_verification_rejects_extra_readback_or_cross_lane_placement_fields() -> None:
    descriptor = normalize_plugin_creation(_effect_request())
    row = {
        "id": PLUGIN_ID,
        "name": "Room",
        "type": "Effect",
        "classId": 7_733_251,
        "parent": SLOT_ID,
        "owner": TARGET_ID,
        "notes": "unexpected",
    }
    with pytest.raises(PluginOperationContractError) as row_error:
        verify_created_plugin_row(
            descriptor,
            row,
            version="2025.1",
            expected_parent_id=SLOT_ID,
            expected_owner_id=TARGET_ID,
            validated_properties=(),
            preexisting_plugin_ids=(),
            readback_view=_readback_view(descriptor),
            placement_evidence=_appended_effect_placement(),
        )
    assert row_error.value.error_code == "INVALID_PLUGIN_READBACK"

    with pytest.raises(PluginOperationContractError) as placement_error:
        verify_created_plugin_row(
            descriptor,
            {key: value for key, value in row.items() if key != "notes"},
            version="2025.1",
            expected_parent_id=SLOT_ID,
            expected_owner_id=TARGET_ID,
            validated_properties=(),
            preexisting_plugin_ids=(),
            readback_view=_readback_view(descriptor),
            placement_evidence=_fixed_effect_placement(),
        )
    assert placement_error.value.error_code == "INVALID_VERIFICATION_INPUT"


def test_effect_slot_readback_fields_are_closed_and_complete() -> None:
    assert PLUGIN_EFFECT_SLOT_READBACK_FIELDS == (
        "id",
        "name",
        "type",
        "parent",
        "owner",
        "@Effect",
    )


def test_verification_rejects_unsealed_or_mismatched_property_validation() -> None:
    descriptor = normalize_plugin_creation(
        _effect_request(
            properties=[{"name": "WetDryMix", "value": 25.0}]
        )
    )
    row = {
        "id": PLUGIN_ID,
        "name": "Room",
        "type": "Effect",
        "classId": 7_733_251,
        "parent": SLOT_ID,
        "owner": TARGET_ID,
        "@WetDryMix": 25.0,
    }
    invalid_values: tuple[Any, ...] = (
        [{"name": "WetDryMix", "value": 25.0, "metadata_type": "Real32"}],
        (
            ValidatedPluginProperty(
                name="Other",
                value=25.0,
                metadata_type="Real32",
            ),
        ),
        (
            ValidatedPluginProperty(
                name="WetDryMix",
                value=25.0,
                metadata_type="Reference",
            ),
        ),
    )
    for invalid in invalid_values:
        with pytest.raises(PluginOperationContractError):
            verify_created_plugin_row(
                descriptor,
                row,
                version="2025.1",
                expected_parent_id=SLOT_ID,
                expected_owner_id=TARGET_ID,
                validated_properties=invalid,
                preexisting_plugin_ids=(),
                readback_view=_readback_view(descriptor),
                placement_evidence=_appended_effect_placement(),
            )


def test_plugin_request_rejects_guessed_or_unbounded_fields() -> None:
    invalid_payloads = [
        {"kind": "metadata", "name": "X", "class_id": 1},
        {"kind": "source", "name": "X", "class_id": True},
        {"kind": "source", "name": "X", "class_id": 0},
        {"kind": "source", "name": "X", "class_id": 2**32},
        {"kind": "source", "name": "A/B", "class_id": 1},
        {"kind": "source", "name": "X", "class_id": 1, "raw": {}},
    ]
    for payload in invalid_payloads:
        with pytest.raises(PluginOperationContractError):
            normalize_plugin_creation(payload)


def test_plugin_properties_reject_raw_keys_duplicates_and_non_finite_values() -> None:
    base = _effect_request()
    invalid_properties = [
        [{"name": "@WetDryMix", "value": 25}],
        [
            {"name": "WetDryMix", "value": 25},
            {"name": "wetdrymix", "value": 50},
        ],
        [{"name": "WetDryMix", "value": None}],
        [{"name": "WetDryMix", "value": {"nested": True}}],
        [{"name": "WetDryMix", "value": math.inf}],
        [{"name": "WetDryMix", "value": 25, "extra": True}],
    ]
    for properties in invalid_properties:
        with pytest.raises(PluginOperationContractError):
            normalize_plugin_creation({**base, "properties": properties})


def test_plugin_property_count_is_bounded() -> None:
    with pytest.raises(PluginOperationContractError, match="32 item ceiling"):
        normalize_plugin_creation(
            _source_request(
                properties=[
                    {"name": f"P{index}", "value": index}
                    for index in range(33)
                ]
            )
        )

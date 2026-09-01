from __future__ import annotations

import json

import pytest

from wwise_waapi import business_declarations as business_declarations_module
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    BusinessHandleRegistry,
    ExistingObjectTarget,
    NewDescendantTarget,
    SUPPORTED_BUSINESS_KINDS,
    SUPPORTED_WWISE_VERSIONS,
    bind_live_field,
    normalize_common_business_fields,
    normalize_live_object_identity,
    revalidate_live_field,
    revalidate_live_object,
    revalidate_live_objects,
    resolve_semantic_kind,
    semantic_kind_for_live_type,
    semantic_kinds_for_live_type,
)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
OTHER_PROJECT_ID = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"
BUS_ID = "{22222222-2222-2222-2222-222222222222}"
METADATA_DIGEST = "a" * 64


def _context(**overrides: str) -> BusinessContext:
    values = {
        "task_authority": "da1-" + "1" * 40,
        "project_id": PROJECT_ID,
        "project_path": "/fixtures/SampleProject.wproj",
        "wwise_version": "2022.1",
        "wwise_build": "2022.1.19.8584",
    }
    values.update(overrides)
    return BusinessContext.create(**values)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_semantic_kinds_are_closed_and_deterministic_for_every_version(
    version: str,
) -> None:
    sound = resolve_semantic_kind("sound-sfx", version=version)
    assert sound.path_segment_type == "Sound SFX"
    assert sound.native_object_type == "Sound SFX"
    assert sound.metadata_object_type == "Sound"
    assert sound.verifier_object_types == ("Sound", "Sound SFX")

    actor_mixer = resolve_semantic_kind("actor-mixer", version=version)
    assert actor_mixer.path_segment_type == "Actor-Mixer"
    assert actor_mixer.native_object_type == "ActorMixer"
    assert actor_mixer.metadata_object_type == (
        "PropertyContainer" if version == "2025.1" else "ActorMixer"
    )
    assert actor_mixer.verifier_object_types == (
        "ActorMixer",
        *(('PropertyContainer',) if version == "2025.1" else ()),
    )

    again = resolve_semantic_kind("actor-mixer", version=version)
    assert again == actor_mixer
    assert again.binding_digest == actor_mixer.binding_digest


def test_semantic_kind_repair_discloses_only_closed_choices() -> None:
    with pytest.raises(BusinessDeclarationError) as captured:
        resolve_semantic_kind("SFX Sound", version="2022.1")

    assert captured.value.repair == {
        "contract": "waapi-skill.business-repair/v1",
        "error_code": "BUSINESS_KIND_UNAVAILABLE",
        "field": "kind",
        "draft_changed": False,
        "choices": list(SUPPORTED_BUSINESS_KINDS),
        "action": "choose one disclosed semantic kind",
    }

    with pytest.raises(BusinessDeclarationError) as unsupported:
        resolve_semantic_kind("sound-sfx", version="2026.1")
    assert unsupported.value.repair["error_code"] == "WWISE_VERSION_UNSUPPORTED"
    assert unsupported.value.repair["choices"] == list(SUPPORTED_WWISE_VERSIONS)


@pytest.mark.parametrize(
    ("display_name", "stable_name"),
    (
        ("Sound SFX", "sound-sfx"),
        ("Sound Voice", "sound-voice"),
        ("Random Container", "random-container"),
        ("Sequence Container", "sequence-container"),
    ),
)
def test_semantic_kind_normalizes_unambiguous_wwise_display_names(
    display_name: str,
    stable_name: str,
) -> None:
    resolved = resolve_semantic_kind(display_name, version="2025.1")

    assert resolved.name == stable_name


def test_live_reflected_type_maps_back_to_one_unambiguous_business_kind() -> None:
    assert semantic_kind_for_live_type(
        "PropertyContainer",
        version="2025.1",
    ) == "actor-mixer"
    assert semantic_kind_for_live_type("ActorMixer", version="2022.1") == "actor-mixer"
    assert semantic_kind_for_live_type("Sound", version="2025.1") is None
    assert semantic_kind_for_live_type(
        "RandomSequenceContainer",
        version="2025.1",
    ) is None
    assert semantic_kinds_for_live_type(
        "RandomSequenceContainer",
        version="2025.1",
    ) == ("random-container", "sequence-container")


def test_new_descendant_uses_parent_handle_name_and_kind_only() -> None:
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda size: b"p" * size)
    parent = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )

    target = registry.new_descendant(
        parent_handle=parent.handle,
        name="Rain_Bed",
        kind="sound-sfx",
    )

    assert target == NewDescendantTarget(
        parent_handle=parent.handle,
        name="Rain_Bed",
        kind="sound-sfx",
    )
    assert not hasattr(target, "object_path")
    assert not hasattr(target, "object_type")


def test_existing_target_uses_one_exact_bound_object_handle() -> None:
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda size: b"e" * size)
    existing = registry.bind_object(
        object_id=OBJECT_ID,
        name="Rifle_Shot",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle_Shot",
    )

    assert registry.existing_target(existing.handle) == ExistingObjectTarget(
        object_handle=existing.handle
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_object_revalidation_requires_the_original_guid_quartet(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"j" * size,
    )
    bound = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )

    def exact(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        assert uri == "ak.wwise.core.object.get"
        assert args == {"from": {"id": [OBJECT_ID]}}
        assert options == {"return": ["id", "name", "type", "path"]}
        return {
            "return": [
                {
                    "id": OBJECT_ID,
                    "name": "Weather",
                    "type": "ActorMixer",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
                }
            ]
        }

    assert revalidate_live_object(registry, bound, read_call=exact) == bound

    def replaced_at_same_path(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        row = exact(uri, args, options)["return"][0]
        assert isinstance(row, dict)
        return {"return": [{**row, "id": OTHER_PROJECT_ID}]}

    with pytest.raises(BusinessDeclarationError) as stale:
        revalidate_live_object(
            registry,
            bound,
            read_call=replaced_at_same_path,
        )
    assert stale.value.repair["error_code"] == "OBJECT_HANDLE_STALE"
    assert stale.value.repair["rejected_handle"] == bound.handle


def test_live_object_revalidation_deduplicates_guids_into_one_bounded_read() -> None:
    tokens = iter((b"a" * 32, b"b" * 32, b"c" * 32))
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda _size: next(tokens))
    weather = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    weather_again = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    bus = registry.bind_object(
        object_id=BUS_ID,
        name="Master Audio Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
    )
    calls: list[tuple[object, object]] = []

    def read(_uri: str, args: dict[str, object], options: dict[str, object]) -> dict[str, object]:
        calls.append((args, options))
        return {
            "return": [
                {
                    "id": BUS_ID,
                    "name": "Master Audio Bus",
                    "type": "Bus",
                    "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
                },
                {
                    "id": OBJECT_ID,
                    "name": "Weather",
                    "type": "ActorMixer",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
                },
            ]
        }

    assert revalidate_live_objects(
        registry,
        (weather, weather_again, bus),
        read_call=read,
    ) == (weather, weather_again, bus)
    assert calls == [
        (
            {"from": {"id": [OBJECT_ID, BUS_ID]}},
            {"return": ["id", "name", "type", "path"]},
        )
    ]


def test_unnamed_action_handle_round_trips_and_revalidates_exactly() -> None:
    registry = BusinessHandleRegistry(
        _context(),
        token_bytes=lambda size: b"a" * size,
    )
    action = registry.bind_object(
        object_id=OBJECT_ID,
        name="",
        object_type="Action",
        path=r"\Events\Default Work Unit\Play_Rain\[Play - Rain]",
    )
    restored = BusinessHandleRegistry.from_dict(registry.as_dict())

    assert restored.resolve_object(action.handle).name == ""
    assert revalidate_live_objects(
        restored,
        (action,),
        read_call=lambda _uri, _args, _options: {
            "return": [
                {
                    "id": OBJECT_ID,
                    "name": "",
                    "type": "Action",
                    "path": r"\Events\Default Work Unit\Play_Rain\[Play - Rain]",
                }
            ]
        },
    ) == (action,)

    with pytest.raises(ValueError, match="name must be non-empty"):
        registry.bind_object(
            object_id=BUS_ID,
            name="",
            object_type="Bus",
            path=r"\Master-Mixer Hierarchy\Default Work Unit\Bus",
        )


@pytest.mark.parametrize(
    ("row", "expected_name"),
    (
        (
            {
                "id": OBJECT_ID.lower(),
                "name": "",
                "type": "Action",
                "path": r"\Events\Default Work Unit\Play_Rain\[Play - Rain]",
            },
            "",
        ),
        (
            {
                "id": BUS_ID,
                "name": "Music",
                "type": "Bus",
                "path": r"\Master-Mixer Hierarchy\Default Work Unit\Music",
            },
            "Music",
        ),
    ),
)
def test_live_object_identity_seam_normalizes_real_wwise_shapes(
    row: dict[str, str],
    expected_name: str,
) -> None:
    identity = normalize_live_object_identity(row)

    assert identity.object_id == row["id"].upper()
    assert identity.name == expected_name
    assert identity.object_type == row["type"]
    assert identity.path == row["path"]


@pytest.mark.parametrize(
    "row",
    (
        {
            "id": OBJECT_ID,
            "name": "",
            "type": "Sound",
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Sound",
        },
        {
            "id": "not-a-guid",
            "name": "Action",
            "type": "Action",
            "path": r"\Events\Default Work Unit\Action",
        },
        {
            "id": OBJECT_ID,
            "name": "Action",
            "type": "",
            "path": r"\Events\Default Work Unit\Action",
        },
        {
            "id": OBJECT_ID,
            "name": "Action",
            "type": "Action",
            "path": "Events/Action",
        },
    ),
)
def test_live_object_identity_seam_rejects_only_malformed_shapes(
    row: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        normalize_live_object_identity(row)


@pytest.mark.parametrize(
    "rows",
    (
        [],
        [
            {
                "id": OBJECT_ID,
                "name": "Weather",
                "type": "ActorMixer",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
            },
            {
                "id": OBJECT_ID,
                "name": "Weather",
                "type": "ActorMixer",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
            },
        ],
        [
            {
                "id": OBJECT_ID,
                "name": "Weather",
                "type": "ActorMixer",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
            },
            {
                "id": BUS_ID,
                "name": "Unexpected",
                "type": "Bus",
                "path": r"\Master-Mixer Hierarchy\Unexpected",
            },
        ],
        [{"id": "not-a-guid", "name": "Weather", "type": "ActorMixer", "path": "x"}],
    ),
)
def test_live_object_batch_revalidation_rejects_inexact_row_sets(
    rows: list[dict[str, object]],
) -> None:
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda size: b"r" * size)
    bound = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )

    with pytest.raises(BusinessDeclarationError) as invalid:
        revalidate_live_objects(
            registry,
            (bound,),
            read_call=lambda _uri, _args, _options: {"return": rows},
        )

    assert invalid.value.repair["error_code"] == "OBJECT_READBACK_INVALID"


def test_live_object_batch_revalidation_rejects_oversized_unique_set_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter((b"x" * 32, b"y" * 32))
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda _size: next(tokens))
    first = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    second = registry.bind_object(
        object_id=BUS_ID,
        name="Master Audio Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
    )
    monkeypatch.setattr(
        business_declarations_module,
        "MULTI_IDENTITY_READ_MAX_IDS",
        1,
    )

    with pytest.raises(BusinessDeclarationError) as limited:
        revalidate_live_objects(
            registry,
            (first, second),
            read_call=lambda *_args, **_kwargs: pytest.fail("oversized set dispatched"),
        )

    assert limited.value.repair["error_code"] == "OBJECT_READ_LIMIT_EXCEEDED"
    assert limited.value.repair["actual_count"] == 2
    assert limited.value.repair["limit"] == 1


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize(
    ("semantic_kind", "is_voice"),
    (("sound-sfx", False), ("sound-voice", True)),
)
def test_live_sound_revalidation_seals_the_exact_is_voice_subtype(
    version: str,
    semantic_kind: str,
    is_voice: bool,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"v" * size,
    )
    bound = registry.bind_object(
        object_id=OBJECT_ID,
        name="Line",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Line",
        semantic_kind=semantic_kind,
    )

    def read(
        _uri: str,
        _args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        assert options["return"] == ["id", "name", "type", "path", "@IsVoice"]
        return {
            "return": [
                {
                    "id": OBJECT_ID,
                    "name": "Line",
                    "type": "Sound",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Line",
                    "@IsVoice": is_voice,
                }
            ]
        }

    assert revalidate_live_object(registry, bound, read_call=read) == bound

    with pytest.raises(BusinessDeclarationError) as stale:
        revalidate_live_object(
            registry,
            bound,
            read_call=lambda uri, args, options: {
                "return": [
                    {
                        **read(uri, args, options)["return"][0],
                        "@IsVoice": not is_voice,
                    }
                ]
            },
        )
    assert stale.value.repair["error_code"] == "OBJECT_HANDLE_STALE"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize(
    ("semantic_kind", "random_or_sequence"),
    (("random-container", 1), ("sequence-container", 0)),
)
def test_live_random_sequence_revalidation_seals_the_exact_discriminator(
    version: str,
    semantic_kind: str,
    random_or_sequence: int,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"r" * size,
    )
    bound = registry.bind_object(
        object_id=OBJECT_ID,
        name="Rifle",
        object_type="RandomSequenceContainer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle",
        semantic_kind=semantic_kind,
    )

    def read(
        _uri: str,
        _args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        assert options["return"] == [
            "id",
            "name",
            "type",
            "path",
            "@RandomOrSequence",
        ]
        return {
            "return": [
                {
                    "id": OBJECT_ID,
                    "name": "Rifle",
                    "type": "RandomSequenceContainer",
                    "path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle"
                    ),
                    "@RandomOrSequence": random_or_sequence,
                }
            ]
        }

    assert revalidate_live_object(registry, bound, read_call=read) == bound

    with pytest.raises(BusinessDeclarationError) as stale:
        revalidate_live_object(
            registry,
            bound,
            read_call=lambda uri, args, options: {
                "return": [
                    {
                        **read(uri, args, options)["return"][0],
                        "@RandomOrSequence": 1 - random_or_sequence,
                    }
                ]
            },
        )
    assert stale.value.repair["error_code"] == "OBJECT_HANDLE_STALE"


@pytest.mark.parametrize(
    ("changed", "error_code"),
    (
        ({"task_authority": "da1-" + "2" * 40}, "HANDLE_TASK_MISMATCH"),
        ({"project_id": OTHER_PROJECT_ID}, "HANDLE_PROJECT_MISMATCH"),
        ({"wwise_version": "2023.1"}, "HANDLE_VERSION_MISMATCH"),
        ({"wwise_build": "2022.1.19.9999"}, "HANDLE_BUILD_MISMATCH"),
    ),
)
def test_object_handles_fail_closed_outside_their_live_binding(
    changed: dict[str, str],
    error_code: str,
) -> None:
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda size: b"o" * size)
    bound = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        registry.resolve_object(bound.handle, context=_context(**changed))

    assert captured.value.repair["error_code"] == error_code
    assert captured.value.repair["draft_changed"] is False
    assert captured.value.repair["rejected_handle"] == bound.handle


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_field_handle_binds_scope_token_type_restrictions_and_metadata_digest(
    version: str,
) -> None:
    context = _context(
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    registry = BusinessHandleRegistry(context, token_bytes=lambda size: b"f" * size)
    field = registry.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="Volume",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -200.0, "maximum": 200.0},
        metadata_digest=METADATA_DIGEST,
    )

    resolved = registry.resolve_field(
        field.handle,
        context=context,
        scope_kind="class",
        scope_value="Sound",
        metadata_digest=METADATA_DIGEST,
    )
    assert resolved.token == "Volume"
    assert resolved.value_type == "number"
    assert resolved.restrictions == {"maximum": 200.0, "minimum": -200.0}
    assert len(resolved.binding_digest) == 64

    for mismatch in (
        {"scope_kind": "class", "scope_value": "ActorMixer", "metadata_digest": METADATA_DIGEST},
        {"scope_kind": "class", "scope_value": "Sound", "metadata_digest": "b" * 64},
    ):
        with pytest.raises(BusinessDeclarationError) as captured:
            registry.resolve_field(field.handle, context=context, **mismatch)
        assert captured.value.repair["error_code"] in {
            "FIELD_HANDLE_SCOPE_MISMATCH",
            "FIELD_HANDLE_STALE",
        }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_field_value_validation_returns_exact_range_enum_and_reference_repairs(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        ),
        token_bytes=lambda size: b"v" * size,
    )
    volume = registry.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="Volume",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -200.0, "maximum": 200.0},
        metadata_digest=METADATA_DIGEST,
    )
    loop = registry.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="LoopMode",
        field_kind="property",
        value_type="string",
        restrictions={"enum_choices": ["Infinite", "Finite"]},
        metadata_digest="b" * 64,
    )
    output_bus = registry.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="OutputBus",
        field_kind="reference",
        value_type="reference",
        restrictions={"allowed_target_types": ["Bus", "AuxBus"]},
        metadata_digest="c" * 64,
    )
    wrong_target = registry.bind_object(
        object_id=OBJECT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    bus_target = registry.bind_object(
        object_id=BUS_ID,
        name="Weather_Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus",
    )

    assert registry.validate_field_value(volume, -4) == -4.0
    assert registry.validate_field_value(loop, "Infinite") == "Infinite"
    assert registry.validate_field_value(output_bus, bus_target.handle) == bus_target.handle

    with pytest.raises(BusinessDeclarationError) as out_of_range:
        registry.validate_field_value(volume, 201)
    assert out_of_range.value.repair["valid_range"] == {
        "minimum": -200.0,
        "maximum": 200.0,
    }

    with pytest.raises(BusinessDeclarationError) as bad_enum:
        registry.validate_field_value(loop, "Forever")
    assert bad_enum.value.repair["choices"] == ["Infinite", "Finite"]

    with pytest.raises(BusinessDeclarationError) as bad_reference:
        registry.validate_field_value(output_bus, wrong_target.handle)
    assert bad_reference.value.repair["allowed_target_types"] == ["AuxBus", "Bus"]


def test_repairs_are_bounded_and_do_not_echo_unbounded_input() -> None:
    registry = BusinessHandleRegistry(_context(), token_bytes=lambda size: b"z" * size)
    huge = "x" * 100_000

    with pytest.raises(BusinessDeclarationError) as captured:
        registry.resolve_object(huge)

    encoded = json.dumps(captured.value.repair, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= 16 * 1024
    assert huge not in encoded.decode("utf-8")
    assert captured.value.repair["error_code"] == "OBJECT_HANDLE_NOT_AVAILABLE"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_field_binding_uses_exact_metadata_and_dynamic_enabled_state(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"m" * size,
    )
    calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        calls.append((uri, dict(args), dict(options)))
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["Volume", "OutputBus"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "Volume",
                "type": "Real32",
                "restriction": {"type": "range", "min": -96.3, "max": 12.0},
                "dependencies": [
                    {
                        "type": "property",
                        "action": "Enable",
                        "context": "Self",
                        "property": "OverrideVolume",
                    }
                ],
            }
        if uri.endswith("isPropertyEnabled"):
            return {"return": True}
        raise AssertionError(uri)

    field = bind_live_field(
        registry,
        read_call=read,
        scope_kind="object",
        scope_value=OBJECT_ID,
        token="Volume",
        platform="Windows",
    )

    assert field.field_kind == "property"
    assert field.value_type == "number"
    assert field.platform == "Windows"
    assert field.restrictions == {"maximum": 12.0, "minimum": -96.3}
    assert [call[0].rsplit(".", 1)[-1] for call in calls] == [
        "getPropertyAndReferenceNames",
        "getPropertyInfo",
        "isPropertyEnabled",
    ]
    assert calls[-1][1] == {
        "object": OBJECT_ID,
        "property": "Volume",
        "platform": "Windows",
    }

    assert revalidate_live_field(registry, field, read_call=read) == field
    assert calls[-1][1]["platform"] == "Windows"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_reference_dependencies_never_use_property_enabled_api(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"o" * size,
    )
    calls: list[str] = []

    def read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        calls.append(uri)
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["OutputBus"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "OutputBus",
                "type": "Reference",
                "restriction": {
                    "type": "reference",
                    "restrictions": [{"type": ["Bus", "AuxBus"]}],
                },
                "dependencies": [{"property": "OverrideOutput"}],
            }
        raise AssertionError(uri)

    field = bind_live_field(
        registry,
        read_call=read,
        scope_kind="object",
        scope_value=OBJECT_ID,
        token="OutputBus",
        platform="Windows",
    )

    assert field.field_kind == "reference"
    assert field.platform == "Windows"
    assert revalidate_live_field(registry, field, read_call=read) == field
    assert not any(uri.endswith("isPropertyEnabled") for uri in calls)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_reference_handle_uses_shared_live_type_aliases(version: str) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"p" * size,
    )
    target = registry.bind_object(
        object_id=BUS_ID,
        name="SFX",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\SFX",
    )
    field = registry.bind_field(
        scope_kind="object",
        scope_value=OBJECT_ID,
        token="OutputBus",
        field_kind="reference",
        value_type="reference",
        restrictions={"allowed_target_types": ["Audio Bus"]},
        metadata_digest="a" * 64,
    )

    assert registry.validate_field_value(field, target.handle) == target.handle


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_field_binding_returns_exact_candidates_and_disabled_repair(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"d" * size,
    )

    def missing_read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        assert uri.endswith("getPropertyAndReferenceNames")
        return {"return": ["Volume", "OutputBus"]}

    with pytest.raises(BusinessDeclarationError) as missing:
        bind_live_field(
            registry,
            read_call=missing_read,
            scope_kind="class",
            scope_value=65552,
            token="Pitch",
        )
    assert missing.value.repair["error_code"] == "FIELD_TOKEN_NOT_AVAILABLE"
    assert missing.value.repair["candidates"] == ["Volume", "OutputBus"]

    def disabled_read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["Volume"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "Volume",
                "type": "Real32",
                "dependencies": [{"property": "OverrideVolume"}],
            }
        if uri.endswith("isPropertyEnabled"):
            return {"return": False}
        raise AssertionError(uri)

    with pytest.raises(BusinessDeclarationError) as disabled:
        bind_live_field(
            registry,
            read_call=disabled_read,
            scope_kind="object",
            scope_value=OBJECT_ID,
            token="Volume",
            platform="Windows",
        )
    assert disabled.value.repair["error_code"] == "FIELD_DISABLED"
    assert disabled.value.repair["dependency_fields"] == ["OverrideVolume"]
    assert disabled.value.repair["draft_changed"] is False


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_dependent_field_uses_unlinked_platform_when_business_platform_is_omitted(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"p" * size,
    )
    enabled_platforms: list[object] = []

    def read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["FadeTime"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "FadeTime",
                "type": "Real32",
                "dependencies": [{"property": "ActionType"}],
            }
        if uri.endswith("isPropertyEnabled"):
            enabled_platforms.append(args["platform"])
            return {"return": True}
        raise AssertionError(uri)

    field = bind_live_field(
        registry,
        read_call=read,
        scope_kind="object",
        scope_value=OBJECT_ID,
        token="FadeTime",
    )
    revalidated = revalidate_live_field(registry, field, read_call=read)

    assert field.platform is None
    assert revalidated == field
    assert enabled_platforms == [
        "{00000000-0000-0000-0000-000000000000}",
        "{00000000-0000-0000-0000-000000000000}",
    ]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_field_revalidation_detects_metadata_drift_before_preview(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        ),
        token_bytes=lambda size: b"r" * size,
    )

    def initial(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["Volume"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "Volume",
                "type": "Real32",
                "restriction": {"type": "range", "min": -96.3, "max": 12.0},
            }
        raise AssertionError(uri)

    field = bind_live_field(
        registry,
        read_call=initial,
        scope_kind="class",
        scope_value=65552,
        token="Volume",
    )

    def drifted(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["Volume"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "Volume",
                "type": "Real32",
                "restriction": {"type": "range", "min": -200.0, "max": 200.0},
            }
        raise AssertionError(uri)

    with pytest.raises(BusinessDeclarationError) as stale:
        revalidate_live_field(registry, field, read_call=drifted)
    assert stale.value.repair["error_code"] == "FIELD_HANDLE_STALE"
    assert stale.value.repair["rejected_handle"] == field.handle


def test_common_business_fields_preserve_omission_and_explicit_units() -> None:
    assert normalize_common_business_fields({"volume_db": -4}) == {
        "volume_db": -4.0
    }
    assert normalize_common_business_fields(
        {
            "fade_time_ms": 250,
            "delay_ms": 0,
            "max_instances": 4,
            "loop": "infinite",
        }
    ) == {
        "delay_ms": 0.0,
        "fade_time_ms": 250.0,
        "loop": "infinite",
        "max_instances": 4,
    }

    with pytest.raises(BusinessDeclarationError) as unitless:
        normalize_common_business_fields({"volume": -4})
    assert unitless.value.repair["error_code"] == "BUSINESS_FIELD_UNAVAILABLE"
    assert "volume_db" in unitless.value.repair["choices"]


@pytest.mark.parametrize(
    ("restriction_row", "error_code"),
    (
        ("playable", "CONSTRAINED_REFERENCE_BOUNDARY"),
        ("unknown", "INVALID_METADATA"),
        (7, "INVALID_METADATA"),
        ({"type": ["Bus", 7]}, "INVALID_METADATA"),
    ),
)
@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_reference_restrictions_fail_closed(
    restriction_row: object,
    error_code: str,
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"q" * size,
    )

    def read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["OutputBus"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "OutputBus",
                "type": "Reference",
                "restriction": {
                    "type": "reference",
                    "restrictions": [restriction_row],
                },
            }
        raise AssertionError(uri)

    with pytest.raises(BusinessDeclarationError) as captured:
        bind_live_field(
            registry,
            read_call=read,
            scope_kind="class",
            scope_value=65552,
            token="OutputBus",
        )
    assert captured.value.repair["error_code"] == error_code


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_dependent_field_requires_exact_object_scope_for_enabled_check(
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"c" * size,
    )

    def read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["Volume"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "Volume",
                "type": "Real32",
                "dependencies": [{"property": "OverrideVolume"}],
            }
        raise AssertionError(uri)

    with pytest.raises(BusinessDeclarationError) as captured:
        bind_live_field(
            registry,
            read_call=read,
            scope_kind="class",
            scope_value=65552,
            token="Volume",
            platform="Windows",
        )
    assert captured.value.repair["error_code"] == "FIELD_OBJECT_SCOPE_REQUIRED"
    assert captured.value.repair["dependency_fields"] == ["OverrideVolume"]


@pytest.mark.parametrize(
    "values",
    (
        [],
        ["Infinite"],
        [{"displayName": "Infinite"}],
        [{"value": "Infinite"}, {"value": 7}],
    ),
)
@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_property_enum_restrictions_fail_closed(
    values: object,
    version: str,
) -> None:
    registry = BusinessHandleRegistry(
        _context(wwise_version=version, wwise_build=f"{version}.fixture"),
        token_bytes=lambda size: b"u" * size,
    )

    def read(
        uri: str,
        args: dict[str, object],
        options: dict[str, object],
    ) -> dict[str, object]:
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": ["LoopMode"]}
        if uri.endswith("getPropertyInfo"):
            return {
                "name": "LoopMode",
                "type": "String",
                "restriction": {"type": "enum", "values": values},
            }
        raise AssertionError(uri)

    with pytest.raises(BusinessDeclarationError) as captured:
        bind_live_field(
            registry,
            read_call=read,
            scope_kind="class",
            scope_value=65552,
            token="LoopMode",
        )
    assert captured.value.repair["error_code"] == "INVALID_METADATA"

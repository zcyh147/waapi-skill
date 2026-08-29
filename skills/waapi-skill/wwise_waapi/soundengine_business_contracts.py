"""Closed business contracts for SoundEngine runtime commands."""

from __future__ import annotations

from typing import Any


SOUNDENGINE_CONTROL_BUSINESS_CONTRACT = (
    "waapi-skill.soundengine-control-business/v1"
)
POST_MONITOR_MESSAGE_URI = "ak.soundengine.postMsgMonitor"
POST_EVENT_URI = "ak.soundengine.postEvent"
EXECUTE_ACTION_ON_EVENT_URI = "ak.soundengine.executeActionOnEvent"
STOP_ALL_URI = "ak.soundengine.stopAll"
STOP_PLAYING_ID_URI = "ak.soundengine.stopPlayingID"
SEEK_ON_EVENT_URI = "ak.soundengine.seekOnEvent"
SET_STATE_URI = "ak.soundengine.setState"
SET_SWITCH_URI = "ak.soundengine.setSwitch"
POST_TRIGGER_URI = "ak.soundengine.postTrigger"
SET_GAME_PARAMETER_URI = "ak.soundengine.setRTPCValue"
RESET_GAME_PARAMETER_URI = "ak.soundengine.resetRTPCValue"
LOAD_BANK_URI = "ak.soundengine.loadBank"
UNLOAD_BANK_URI = "ak.soundengine.unloadBank"
SET_DEFAULT_LISTENERS_URI = "ak.soundengine.setDefaultListeners"
SET_LISTENERS_URI = "ak.soundengine.setListeners"
SET_POSITION_URI = "ak.soundengine.setPosition"
SET_MULTIPLE_POSITIONS_URI = "ak.soundengine.setMultiplePositions"
SET_OBSTRUCTION_OCCLUSION_URI = (
    "ak.soundengine.setObjectObstructionAndOcclusion"
)
SET_SCALING_FACTOR_URI = "ak.soundengine.setScalingFactor"
SET_OUTPUT_BUS_VOLUME_URI = "ak.soundengine.setGameObjectOutputBusVolume"
SET_LISTENER_SPATIALIZATION_URI = "ak.soundengine.setListenerSpatialization"
SET_AUX_SENDS_URI = "ak.soundengine.setGameObjectAuxSendValues"
GET_STATE_URI = "ak.soundengine.getState"
GET_SWITCH_URI = "ak.soundengine.getSwitch"
REGISTER_GAME_OBJECT_URI = "ak.soundengine.registerGameObj"
UNREGISTER_GAME_OBJECT_URI = "ak.soundengine.unregisterGameObj"
_ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")

_CONTRACTS: dict[str, dict[str, Any]] = {
    POST_MONITOR_MESSAGE_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("monitor_message",),
        "optional_fields": (),
        "field_types": {
            "monitor_message": "bounded_exact_monitor_message",
        },
        "input_forms": {
            "monitor_message": {
                "flag": "--monitor-message",
                "repeatable": False,
            },
        },
    },
    POST_EVENT_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("event",),
        "required_fields": ("event_handle",),
        "required_fields_by_version": {
            "2021.1": ("event_handle", "game_object_handle"),
            "2022.1": ("event_handle", "game_object_handle"),
            "2023.1": ("event_handle", "game_object_handle"),
        },
        "optional_fields": ("game_object_handle",),
        "optional_fields_by_version": {
            "2021.1": (),
            "2022.1": (),
            "2023.1": (),
        },
        "field_types": {
            "event_handle": "bound_event_handle",
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "event_handle": {
                "flag": "--event-handle",
                "repeatable": False,
            },
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
    EXECUTE_ACTION_ON_EVENT_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("event",),
        "required_fields": ("event_handle", "action"),
        "optional_fields": (
            "game_object_handle",
            "fade_duration_ms",
            "fade_curve",
        ),
        "field_types": {
            "event_handle": "bound_event_handle",
            "action": "wwise_event_action_name",
            "game_object_handle": "gateway_runtime_game_object_handle",
            "fade_duration_ms": "nonnegative_transition_duration_ms",
            "fade_curve": "wwise_fade_curve_name",
        },
        "input_forms": {
            "event_handle": {"flag": "--event-handle", "repeatable": False},
            "action": {"flag": "--action", "repeatable": False},
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
            "fade_duration_ms": {
                "flag": "--fade-duration-ms",
                "repeatable": False,
            },
            "fade_curve": {"flag": "--fade-curve", "repeatable": False},
        },
    },
    STOP_ALL_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": (),
        "optional_fields": ("game_object_handle",),
        "field_types": {
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
    SEEK_ON_EVENT_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("event",),
        "required_fields": ("event_handle",),
        "optional_fields": (
            "game_object_handle",
            "playing_handle",
            "position_ms",
            "position_percent",
            "nearest_marker",
        ),
        "field_types": {
            "event_handle": "bound_event_handle",
            "game_object_handle": "gateway_runtime_game_object_handle",
            "playing_handle": "gateway_runtime_playing_handle",
            "position_ms": "nonnegative_whole_milliseconds",
            "position_percent": "percentage_0_through_100",
            "nearest_marker": "boolean",
        },
        "input_forms": {
            "event_handle": {"flag": "--event-handle", "repeatable": False},
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
            "playing_handle": {
                "flag": "--playing-handle",
                "repeatable": False,
            },
            "position_ms": {"flag": "--position-ms", "repeatable": False},
            "position_percent": {
                "flag": "--position-percent",
                "repeatable": False,
            },
            "nearest_marker": {"flag": "--nearest-marker", "repeatable": False},
        },
        "constraints": {
            "exactly_one_of": [["position_ms", "position_percent"]],
            "playing_handle_event": "must_match_bound_event",
            "playing_handle_scope": "supersedes_game_object_scope",
        },
    },
    SET_STATE_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("state_group", "state"),
        "required_fields": ("state_group_handle", "state_handle"),
        "optional_fields": (),
        "field_types": {
            "state_group_handle": "bound_state_group_handle",
            "state_handle": "bound_state_handle",
        },
        "input_forms": {
            "state_group_handle": {
                "flag": "--state-group-handle",
                "repeatable": False,
            },
            "state_handle": {"flag": "--state-handle", "repeatable": False},
        },
        "constraints": {
            "state_relationship": "state_must_be_direct_child_of_state_group",
        },
    },
    SET_SWITCH_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("switch_group", "switch"),
        "required_fields": ("switch_group_handle", "switch_handle"),
        "required_fields_by_version": {
            "2021.1": (
                "switch_group_handle",
                "switch_handle",
                "game_object_handle",
            ),
            "2022.1": (
                "switch_group_handle",
                "switch_handle",
                "game_object_handle",
            ),
        },
        "optional_fields": ("game_object_handle",),
        "optional_fields_by_version": {"2021.1": (), "2022.1": ()},
        "field_types": {
            "switch_group_handle": "bound_switch_group_handle",
            "switch_handle": "bound_switch_handle",
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "switch_group_handle": {
                "flag": "--switch-group-handle",
                "repeatable": False,
            },
            "switch_handle": {"flag": "--switch-handle", "repeatable": False},
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
        "constraints": {
            "switch_relationship": "switch_must_be_direct_child_of_switch_group",
        },
    },
    POST_TRIGGER_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("trigger",),
        "required_fields": ("trigger_handle",),
        "required_fields_by_version": {
            "2021.1": ("trigger_handle", "game_object_handle"),
            "2022.1": ("trigger_handle", "game_object_handle"),
        },
        "optional_fields": ("game_object_handle",),
        "optional_fields_by_version": {"2021.1": (), "2022.1": ()},
        "field_types": {
            "trigger_handle": "bound_trigger_handle",
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "trigger_handle": {"flag": "--trigger-handle", "repeatable": False},
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
    SET_GAME_PARAMETER_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("game_parameter",),
        "required_fields": ("game_parameter_handle", "value"),
        "required_fields_by_version": {
            "2021.1": ("game_parameter_handle", "value", "game_object_handle"),
            "2022.1": ("game_parameter_handle", "value", "game_object_handle"),
        },
        "optional_fields": ("game_object_handle",),
        "optional_fields_by_version": {"2021.1": (), "2022.1": ()},
        "field_types": {
            "game_parameter_handle": "bound_game_parameter_handle",
            "value": "finite_game_parameter_value",
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "game_parameter_handle": {
                "flag": "--game-parameter-handle",
                "repeatable": False,
            },
            "value": {"flag": "--value", "repeatable": False},
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
    RESET_GAME_PARAMETER_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("game_parameter",),
        "required_fields": ("game_parameter_handle",),
        "required_fields_by_version": {
            "2021.1": ("game_parameter_handle", "game_object_handle"),
            "2022.1": ("game_parameter_handle", "game_object_handle"),
        },
        "optional_fields": ("game_object_handle",),
        "optional_fields_by_version": {"2021.1": (), "2022.1": ()},
        "field_types": {
            "game_parameter_handle": "bound_game_parameter_handle",
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "game_parameter_handle": {
                "flag": "--game-parameter-handle",
                "repeatable": False,
            },
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
    LOAD_BANK_URI: {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("sound_bank",),
        "required_fields": ("sound_bank_handle",),
        "optional_fields": (),
        "field_types": {"sound_bank_handle": "bound_sound_bank_handle"},
        "input_forms": {
            "sound_bank_handle": {
                "flag": "--sound-bank-handle",
                "repeatable": False,
            },
        },
    },
    UNLOAD_BANK_URI: {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("sound_bank",),
        "required_fields": ("sound_bank_handle",),
        "optional_fields": (),
        "field_types": {"sound_bank_handle": "bound_sound_bank_handle"},
        "input_forms": {
            "sound_bank_handle": {
                "flag": "--sound-bank-handle",
                "repeatable": False,
            },
        },
    },
    SET_DEFAULT_LISTENERS_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": (),
        "optional_fields": ("listener_handles", "clear_listeners"),
        "field_types": {
            "listener_handles": "gateway_runtime_game_object_handle_list",
            "clear_listeners": "explicit_boolean_intent",
        },
        "input_forms": {
            "listener_handles": {"flag": "--listener-handle", "repeatable": True},
            "clear_listeners": {"flag": "--clear-listeners", "repeatable": False},
        },
        "constraints": {
            "exactly_one_of": [["listener_handles", "clear_listeners"]],
        },
    },
    SET_LISTENERS_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("emitter_handle",),
        "optional_fields": ("listener_handles", "clear_listeners"),
        "field_types": {
            "emitter_handle": "gateway_runtime_game_object_handle",
            "listener_handles": "gateway_runtime_game_object_handle_list",
            "clear_listeners": "explicit_boolean_intent",
        },
        "input_forms": {
            "emitter_handle": {"flag": "--emitter-handle", "repeatable": False},
            "listener_handles": {"flag": "--listener-handle", "repeatable": True},
            "clear_listeners": {"flag": "--clear-listeners", "repeatable": False},
        },
        "constraints": {
            "exactly_one_of": [["listener_handles", "clear_listeners"]],
        },
    },
    SET_POSITION_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("game_object_handle", "position_frame"),
        "optional_fields": (),
        "field_types": {
            "game_object_handle": "gateway_runtime_game_object_handle",
            "position_frame": "position_front_top_nine_finite_numbers",
        },
        "input_forms": {
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
            "position_frame": {
                "flag": "--position-frame",
                "repeatable": False,
                "arity": 9,
                "order": ["x", "y", "z", "front_x", "front_y", "front_z", "top_x", "top_y", "top_z"],
            },
        },
    },
    SET_MULTIPLE_POSITIONS_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": (
            "game_object_handle",
            "position_frames",
            "multi_position_mode",
        ),
        "optional_fields": (),
        "field_types": {
            "game_object_handle": "gateway_runtime_game_object_handle",
            "position_frames": "bounded_position_front_top_frame_list",
            "multi_position_mode": "wwise_multi_position_type_name",
        },
        "input_forms": {
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
            "position_frames": {
                "flag": "--position-frame",
                "repeatable": True,
                "arity": 9,
            },
            "multi_position_mode": {
                "flag": "--multi-position-mode",
                "repeatable": False,
                "values": ["SingleSource", "MultiSources", "MultiDirections"],
            },
        },
    },
    SET_OBSTRUCTION_OCCLUSION_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": (
            "emitter_handle",
            "listener_handle",
            "obstruction_percent",
            "occlusion_percent",
        ),
        "optional_fields": (),
        "field_types": {
            "emitter_handle": "gateway_runtime_game_object_handle",
            "listener_handle": "gateway_runtime_game_object_handle",
            "obstruction_percent": "percentage_0_through_100",
            "occlusion_percent": "percentage_0_through_100",
        },
        "input_forms": {
            "emitter_handle": {"flag": "--emitter-handle", "repeatable": False},
            "listener_handle": {"flag": "--listener-handle", "repeatable": False},
            "obstruction_percent": {
                "flag": "--obstruction-percent",
                "repeatable": False,
            },
            "occlusion_percent": {
                "flag": "--occlusion-percent",
                "repeatable": False,
            },
        },
    },
    SET_SCALING_FACTOR_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("game_object_handle", "attenuation_scale_percent"),
        "optional_fields": (),
        "field_types": {
            "game_object_handle": "gateway_runtime_game_object_handle",
            "attenuation_scale_percent": "positive_finite_percentage",
        },
        "input_forms": {
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
            "attenuation_scale_percent": {
                "flag": "--attenuation-scale-percent",
                "repeatable": False,
            },
        },
    },
    SET_OUTPUT_BUS_VOLUME_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("emitter_handle", "listener_handle", "volume_db"),
        "optional_fields": (),
        "field_types": {
            "emitter_handle": "gateway_runtime_game_object_handle",
            "listener_handle": "gateway_runtime_game_object_handle",
            "volume_db": "finite_decibels",
        },
        "input_forms": {
            "emitter_handle": {"flag": "--emitter-handle", "repeatable": False},
            "listener_handle": {"flag": "--listener-handle", "repeatable": False},
            "volume_db": {"flag": "--volume-db", "repeatable": False},
        },
    },
    SET_LISTENER_SPATIALIZATION_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": (
            "listener_handle",
            "spatialization",
        ),
        "optional_fields": (
            "channel_layout",
            "channel_layout_kind",
            "channel_speakers",
            "channel_count",
            "speaker_offsets_db",
            "channel_offsets_db",
        ),
        "field_types": {
            "listener_handle": "gateway_runtime_game_object_handle",
            "spatialization": "enabled_or_disabled",
            "channel_layout": "wwise_standard_plane_channel_layout",
            "channel_layout_kind": "wwise_channel_config_type_name",
            "channel_speakers": "wwise_named_standard_speaker_set",
            "channel_count": "positive_wwise_channel_count",
            "speaker_offsets_db": "speaker_name_to_finite_decibels",
            "channel_offsets_db": "one_based_channel_index_to_finite_decibels",
        },
        "input_forms": {
            "listener_handle": {"flag": "--listener-handle", "repeatable": False},
            "spatialization": {
                "flag": "--spatialization",
                "repeatable": False,
                "values": ["enabled", "disabled"],
            },
            "channel_layout": {
                "flag": "--channel-layout",
                "repeatable": False,
                "values": [
                    "1.0", "1.1", "2.0", "2.1", "3.0", "3.1", "4.0",
                    "4.1", "5.0", "5.1", "6.0", "6.1", "7.0", "7.1",
                ],
            },
            "channel_layout_kind": {
                "flag": "--channel-layout-kind",
                "repeatable": False,
                "values": ["Standard", "Anonymous", "Ambisonic", "Objects"],
            },
            "channel_speakers": {
                "flag": "--channel-speaker",
                "repeatable": True,
                "values": [
                    "FL", "FR", "C", "LFE", "BL", "BR", "BC", "SL", "SR",
                    "TOP", "HFL", "HFC", "HFR", "HBL", "HBC", "HBR", "HSL", "HSR",
                ],
            },
            "channel_count": {
                "flag": "--channel-count",
                "repeatable": False,
            },
            "speaker_offsets_db": {
                "flag": "--speaker-offset-db",
                "repeatable": True,
                "arity": 2,
                "order": ["speaker", "decibels"],
            },
            "channel_offsets_db": {
                "flag": "--channel-offset-db",
                "repeatable": True,
                "arity": 2,
                "order": ["one_based_channel_index", "decibels"],
            },
        },
        "constraints": {
            "descriptor": (
                "exactly one preset --channel-layout, or one --channel-layout-kind; "
                "Standard requires named speakers, Anonymous and Ambisonic require "
                "channel-count, and Objects accepts neither"
            ),
            "offsets": (
                "standard descriptors accept speaker offsets; Anonymous and "
                "Ambisonic accept one-based channel offsets; Objects accepts none"
            ),
            "version_boundary": (
                "HSL and HSR are available only in Wwise 2024.1 and 2025.1"
            ),
        },
    },
    SET_AUX_SENDS_URI: {
        "versions": _ALL_VERSIONS,
        "roles": ("aux_bus",),
        "optional_roles": ("aux_bus",),
        "required_fields": ("emitter_handle",),
        "optional_fields": ("aux_sends", "clear_aux_sends"),
        "field_types": {
            "emitter_handle": "gateway_runtime_game_object_handle",
            "aux_sends": "bounded_listener_aux_bus_percentage_rows",
            "clear_aux_sends": "explicit_boolean_intent",
        },
        "input_forms": {
            "emitter_handle": {"flag": "--emitter-handle", "repeatable": False},
            "aux_sends": {
                "flag": "--aux-send",
                "repeatable": True,
                "arity": 3,
                "order": ["listener_handle", "bound_aux_bus_handle", "send_percent"],
            },
            "clear_aux_sends": {
                "flag": "--clear-aux-sends",
                "repeatable": False,
            },
        },
        "constraints": {
            "row_count": "1_through_4",
            "aux_bus_role_cardinality": "bind_1_through_4_before_declaration",
            "exactly_one_of": [["aux_sends", "clear_aux_sends"]],
        },
    },
    STOP_PLAYING_ID_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("playing_handle",),
        "optional_fields": ("fade_duration_ms", "fade_curve"),
        "field_types": {
            "playing_handle": "gateway_runtime_playing_handle",
            "fade_duration_ms": "nonnegative_transition_duration_ms",
            "fade_curve": "wwise_fade_curve_name",
        },
        "input_forms": {
            "playing_handle": {
                "flag": "--playing-handle",
                "repeatable": False,
            },
            "fade_duration_ms": {
                "flag": "--fade-duration-ms",
                "repeatable": False,
            },
            "fade_curve": {
                "flag": "--fade-curve",
                "repeatable": False,
            },
        },
    },
    REGISTER_GAME_OBJECT_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("game_object_name",),
        "optional_fields": (),
        "field_types": {
            "game_object_name": "exact_runtime_game_object_name",
        },
        "input_forms": {
            "game_object_name": {
                "flag": "--game-object-name",
                "repeatable": False,
            },
        },
    },
    UNREGISTER_GAME_OBJECT_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("game_object_handle",),
        "optional_fields": (),
        "field_types": {
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
    GET_STATE_URI: {
        "versions": ("2022.1", "2023.1", "2024.1", "2025.1"),
        "execution_shape": "bounded_read",
        "required_fields": ("state_group_id",),
        "optional_fields": (),
        "field_types": {"state_group_id": "exact_state_group_guid"},
        "input_forms": {
            "state_group_id": {"flag": "--state-group-id", "repeatable": False},
        },
    },
    GET_SWITCH_URI: {
        "versions": ("2022.1", "2023.1", "2024.1", "2025.1"),
        "execution_shape": "bounded_read",
        "required_fields": ("switch_group_id",),
        "required_fields_by_version": {
            "2022.1": ("switch_group_id", "game_object_handle"),
        },
        "optional_fields": ("game_object_handle",),
        "optional_fields_by_version": {"2022.1": ()},
        "field_types": {
            "switch_group_id": "exact_switch_group_guid",
            "game_object_handle": "gateway_runtime_game_object_handle",
        },
        "input_forms": {
            "switch_group_id": {
                "flag": "--switch-group-id",
                "repeatable": False,
            },
            "game_object_handle": {
                "flag": "--game-object-handle",
                "repeatable": False,
            },
        },
    },
}

_READ_OPERATIONS = frozenset({GET_STATE_URI, GET_SWITCH_URI})


def soundengine_control_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def soundengine_control_business_read_operations() -> frozenset[str]:
    return _READ_OPERATIONS


def soundengine_control_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    """List every deep SoundEngine route for offline intent selection."""

    intents = {
        GET_STATE_URI: "read the current runtime State for one exact State Group",
        GET_SWITCH_URI: "read the current runtime Switch for one exact Switch Group and optional game object",
        REGISTER_GAME_OBJECT_URI: "register one named runtime game object and return an opaque handle",
        UNREGISTER_GAME_OBJECT_URI: "unregister one Gateway-managed runtime game object",
        POST_EVENT_URI: "post one bound Event and return an opaque playing handle",
        STOP_PLAYING_ID_URI: "stop one opaque playing instance with an optional named fade",
        SET_POSITION_URI: "set one runtime game-object position and orientation frame",
        SET_MULTIPLE_POSITIONS_URI: "set bounded runtime position frames with one Wwise multi-position mode",
        SET_LISTENERS_URI: "replace one emitter's runtime listener set",
        SET_DEFAULT_LISTENERS_URI: "replace the runtime default listener set",
        SET_AUX_SENDS_URI: "replace one emitter's bounded listener and Aux Bus send rows",
    }
    return tuple(
        {
            "api": operation,
            "intent": intents.get(
                operation,
                "perform one closed SoundEngine runtime business operation",
            ),
            "supported_versions": list(
                soundengine_control_business_versions(operation)
            ),
            "host_requirement": "wwise-console-or-authoring",
        }
        for operation in sorted(_CONTRACTS)
    )


def soundengine_control_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported SoundEngine business operation") from exc


def soundengine_control_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported SoundEngine business operation") from exc
    if version not in row["versions"]:
        raise ValueError("SoundEngine operation is unavailable in this version")
    required_fields = tuple(
        row.get("required_fields_by_version", {}).get(
            version,
            row["required_fields"],
        )
    )
    optional_fields = tuple(
        row.get("optional_fields_by_version", {}).get(
            version,
            row["optional_fields"],
        )
    )
    exposed_fields = set(required_fields) | set(optional_fields)
    roles = tuple(row.get("roles", ()))
    optional_roles = set(row.get("optional_roles", ()))
    required_roles = tuple(role for role in roles if role not in optional_roles)
    bounded_read = row.get("execution_shape") == "bounded_read"
    return {
        "contract": SOUNDENGINE_CONTROL_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": "bounded_read" if bounded_read else "draft_mutation",
        "host_requirement": "wwise-console-or-authoring",
        "start": (
            {
                "subcommand": "core-call",
                "gateway_argv_prefix": ["core-call", operation],
                "append_only_disclosed_business_fields": True,
            }
            if bounded_read
            else {
                "subcommand": "draft-start",
                "gateway_argv": ["draft-start", operation],
                "copy_exactly": True,
                "append_arguments": "forbidden",
            }
        ),
        "declaration": {
            "subcommand": (
                "core-call" if bounded_read else "draft-declare-soundengine-plan"
            ),
            "required_fields": list(required_fields),
            "optional_fields": list(optional_fields),
            "field_types": {
                name: value
                for name, value in row["field_types"].items()
                if name in exposed_fields
            },
            "input_forms": {
                name: value
                for name, value in row["input_forms"].items()
                if name in exposed_fields
            },
            **(
                {"constraints": row["constraints"]}
                if "constraints" in row
                else {}
            ),
        },
        "binding": {
            "available": bool(roles),
            "roles": list(roles),
            "required_roles": list(required_roles),
            "role_fields": [
                {
                    "role": role,
                    "field": f"{role}_handle",
                    "cardinality": (
                        "one_to_four" if role in optional_roles else "exactly_one"
                    ),
                }
                for role in roles
            ],
            "role_required": bool(required_roles),
            "identity": "live_bound_object_handle" if roles else "none",
            "validation": "exact_guid_name_type_path" if roles else "none",
        },
        "gateway_derivations": [
            *(
                ["runtime_game_object_id", "unregister_cleanup"]
                if operation == REGISTER_GAME_OBJECT_URI
                else ["runtime_game_object_handle", "handle_retirement"]
                if operation == UNREGISTER_GAME_OBJECT_URI
                else ["runtime_playing_handle", "handle_retirement"]
                if operation == STOP_PLAYING_ID_URI
                else []
            ),
            "native_request",
            "result_projection",
            "result_bound",
            *([] if bounded_read else ["preview", "authorization", "verification"]),
            "continuation",
        ],
        "legacy_typed_call_public": False,
        "safety": {
            "preview": "not_applicable_read_only" if bounded_read else "immutable_before_execution",
            "authorization": "not_required_read_only" if bounded_read else "normal_transaction_policy",
            "automatic_retry": False,
            "lifecycle_cleanup": "packaged_when_operation_has_companion",
            "native_request_input": "forbidden",
        },
    }


__all__ = [
    "POST_MONITOR_MESSAGE_URI",
    "POST_EVENT_URI",
    "EXECUTE_ACTION_ON_EVENT_URI",
    "STOP_ALL_URI",
    "STOP_PLAYING_ID_URI",
    "SEEK_ON_EVENT_URI",
    "SET_STATE_URI",
    "SET_SWITCH_URI",
    "POST_TRIGGER_URI",
    "SET_GAME_PARAMETER_URI",
    "RESET_GAME_PARAMETER_URI",
    "LOAD_BANK_URI",
    "UNLOAD_BANK_URI",
    "SET_DEFAULT_LISTENERS_URI",
    "SET_LISTENERS_URI",
    "SET_POSITION_URI",
    "SET_MULTIPLE_POSITIONS_URI",
    "SET_OBSTRUCTION_OCCLUSION_URI",
    "SET_SCALING_FACTOR_URI",
    "SET_OUTPUT_BUS_VOLUME_URI",
    "SET_LISTENER_SPATIALIZATION_URI",
    "SET_AUX_SENDS_URI",
    "REGISTER_GAME_OBJECT_URI",
    "UNREGISTER_GAME_OBJECT_URI",
    "GET_STATE_URI",
    "GET_SWITCH_URI",
    "SOUNDENGINE_CONTROL_BUSINESS_CONTRACT",
    "soundengine_control_business_contract_data",
    "soundengine_control_business_operations",
    "soundengine_control_business_read_operations",
    "soundengine_control_business_catalog_rows",
    "soundengine_control_business_versions",
]

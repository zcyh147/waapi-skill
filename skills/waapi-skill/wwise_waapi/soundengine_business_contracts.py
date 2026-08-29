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
}


def soundengine_control_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


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
    return {
        "contract": SOUNDENGINE_CONTROL_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": "draft_mutation",
        "host_requirement": "wwise-console-or-authoring",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "declaration": {
            "subcommand": "draft-declare-soundengine-plan",
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
            "role_fields": [
                {
                    "role": role,
                    "field": f"{role}_handle",
                    "cardinality": "exactly_one",
                }
                for role in roles
            ],
            "role_required": bool(roles),
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
            "preview",
            "authorization",
            "verification",
            "continuation",
        ],
        "legacy_typed_call_public": False,
        "safety": {
            "preview": "immutable_before_execution",
            "authorization": "normal_transaction_policy",
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
    "REGISTER_GAME_OBJECT_URI",
    "UNREGISTER_GAME_OBJECT_URI",
    "SOUNDENGINE_CONTROL_BUSINESS_CONTRACT",
    "soundengine_control_business_contract_data",
    "soundengine_control_business_operations",
    "soundengine_control_business_versions",
]

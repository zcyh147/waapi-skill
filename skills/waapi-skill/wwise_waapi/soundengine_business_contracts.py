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
    "REGISTER_GAME_OBJECT_URI",
    "UNREGISTER_GAME_OBJECT_URI",
    "SOUNDENGINE_CONTROL_BUSINESS_CONTRACT",
    "soundengine_control_business_contract_data",
    "soundengine_control_business_operations",
    "soundengine_control_business_versions",
]

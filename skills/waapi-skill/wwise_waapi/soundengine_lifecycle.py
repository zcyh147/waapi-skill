"""Conservative control-authority consumption at the SoundEngine write boundary.

A queued stop or an indeterminate write cannot establish that audio ended.
Consuming the affected capabilities before dispatch prevents stale control from
crossing that uncertainty window; result-schema verification stays weaker than
native effect verification.
"""

from pathlib import Path
from typing import Any, Mapping

from .runtime_game_object_handles import RuntimeGameObjectContext, RuntimeGameObjectHandleStore
from .runtime_playing_handles import RuntimePlayingHandleStore
from .runtime_playing_handles import RuntimePlayingHandleError
from .soundengine_business_contracts import (
    EXECUTE_ACTION_ON_EVENT_URI,
    STOP_ALL_URI,
    STOP_PLAYING_ID_URI,
    UNREGISTER_GAME_OBJECT_URI,
)


def soundengine_resource_lease(state_dir: Path):
    """Serialize native control, capability consumption and publication."""
    from .transactions import TransactionStore

    return TransactionStore(state_dir / "soundengine-runtime-lease").execution_lease("soundengine-resources")


def soundengine_authority_snapshot(
    request: Mapping[str, Any],
    *,
    state_dir: Path,
    context: RuntimeGameObjectContext,
    declared_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the exact capability generation, not merely its reusable native ID."""
    operation = request.get("arguments", {}).get("api", "")
    args = request.get("arguments", {}).get("args", {})
    game_object_ids = []
    if operation != "ak.soundengine.registerGameObj":
        game_object_ids.extend(args.get(field) for field in ("gameObject", "emitter", "listener"))
        game_object_ids.extend(args.get("listeners", []))
        game_object_ids.extend(row["listener"] for row in args.get("auxSendValues", []))
    game_objects = RuntimeGameObjectHandleStore(state_dir)
    records = [
        game_objects.resolve_native_id(native_id, context=context).as_dict()
        for native_id in dict.fromkeys(game_object_ids)
        if isinstance(native_id, int) and not isinstance(native_id, bool) and 0 <= native_id <= 0xFFFFFFFFFFFFFFDF
    ]
    playing_id = args.get("playingId")
    playing = (
        RuntimePlayingHandleStore(state_dir).resolve_native_id(playing_id, context=context).as_dict()
        if isinstance(playing_id, int) and not isinstance(playing_id, bool) and playing_id > 0
        else None
    )
    if declared_settings is not None:
        expected = list(declared_settings.get("runtime_game_object_bindings", {}).values())
        singular = declared_settings.get("runtime_game_object_binding")
        if singular is not None:
            expected.append(singular)
        expected_playing = declared_settings.get("runtime_playing_binding")
        if any(record not in expected for record in records) or playing != expected_playing:
            raise RuntimePlayingHandleError(
                "SOUNDENGINE_AUTHORITY_GENERATION_DRIFT",
                "The declared runtime capability was retired or replaced before Draft check.",
            )
    return {
        "contract": "waapi-skill.soundengine-authority-snapshot/v1",
        "game_objects": [{"handle": record["handle"], "binding_digest": record["binding_digest"]} for record in records],
        "playing": None if playing is None else {"handle": playing["handle"], "binding_digest": playing["record_sha256"]},
    }


def consume_soundengine_control_authority(
    operation: str,
    args: Mapping[str, Any],
    *,
    state_dir: Path,
    context: RuntimeGameObjectContext,
) -> dict[str, int] | None:
    if operation == UNREGISTER_GAME_OBJECT_URI:
        game_objects = RuntimeGameObjectHandleStore(state_dir)
        retired = (
            game_objects.retire_all(context=context)
            if args["gameObject"] == 0xFFFFFFFFFFFFFFFF
            else game_objects.retire_native_id(args["gameObject"], context=context)
        )
        # Unregistering an in-use game object does not stop its playback.  The
        # still-independent playing authority must remain available.
        return {"retired_game_object_handle_count": len(retired)}
    if operation == STOP_PLAYING_ID_URI:
        selectors = {"playing_id": args["playingId"]}
    elif operation == STOP_ALL_URI:
        selectors = {}
    elif operation == EXECUTE_ACTION_ON_EVENT_URI and args.get("actionType") == 0:
        selectors = {"event_id": args["event"]}
    else:
        return None
    game_object_id = args.get("gameObject")
    if game_object_id is not None and game_object_id != 0xFFFFFFFFFFFFFFFF:
        selectors["game_object_id"] = game_object_id
    retired = RuntimePlayingHandleStore(state_dir).retire_scope(
        context=context, **selectors,
    )
    return {"retired_playing_handle_count": len(retired)}

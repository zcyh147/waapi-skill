"""C01: one localized reimport, with independent media and preservation evidence."""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, case_name, container_root, copy_asset,
    file_evidence, query_path, read_object, rows, wav_assets,
)


VOICE_INCLUDES = ("volume-db", "output-bus", "notes", "parent")
SOURCE_INCLUDES = ("source-language", "original-file-path", "parent", "notes")
C01_ASSERTIONS = frozenset({
    "requested_language_media_matches", "other_language_unchanged",
    "sound_identity_and_configuration_unchanged", "exact_language_set",
    "event_and_action_unchanged", "distractor_unchanged", "fixture_membership_unchanged",
    "requested_language_source_identity_preserved",
    "source_gain_unchanged",
})

_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


def _identity_notes_parent(row: Mapping[str, Any], kind: str) -> None:
    parent = row.get("parent")
    if (row.get("type") != kind or not isinstance(row.get("name"), str)
            or not isinstance(row.get("path"), str) or not row["path"]
            or not isinstance(row.get("notes"), str)
            or not isinstance(parent, Mapping) or not isinstance(parent.get("id"), str)
            or not _GUID.fullmatch(parent["id"])):
        raise CaseBoundaryError(f"C01 {kind} preservation projection is incomplete or malformed")


def _sound_state(row: Mapping[str, Any]) -> None:
    _identity_notes_parent(row, "Sound")
    volume = row.get("volume_db")
    bus = row.get("output_bus")
    if (type(volume) not in {int, float} or not math.isfinite(volume)
            or "output_bus" not in row or (bus is not None and (
                not isinstance(bus, Mapping) or not isinstance(bus.get("id"), str)
                or not _GUID.fullmatch(bus["id"])))):
        raise CaseBoundaryError("C01 Sound volume and routing projection is incomplete or malformed")


def _children(ctx: ExpansionCaseContext, object_id: str, includes: tuple[str, ...]) -> list[dict[str, Any]]:
    command = ["query-object", "--exact-id", object_id, "--relationship", "children",
               "--max-results", "16"]
    for include in includes:
        command.extend(("--include", include))
    return rows(ctx.gateway(command))


def _voice_snapshot(ctx: ExpansionCaseContext, *, sound_id: str, event_id: str,
                    decoy_id: str, parent_id: str) -> dict[str, Any]:
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C01 requires the fixed runner-owned source gain oracle")
    sources: dict[str, Any] = {}
    for source in _children(ctx, sound_id, SOURCE_INCLUDES):
        _identity_notes_parent(source, "AudioFileSource")
        language = source.get("source_language")
        parent = source.get("parent")
        if (source.get("type") != "AudioFileSource" or not isinstance(language, Mapping)
                or not isinstance(language.get("name"), str) or language["name"] in sources
                or not isinstance(parent, Mapping) or parent.get("id") != sound_id
                or not isinstance(source.get("original_file_path"), str)):
            raise CaseBoundaryError("Voice sources do not prove unique language and owner associations")
        sources[language["name"]] = {
            "object": source, "media": file_evidence(ctx, source["original_file_path"]),
        }
    source_ids = [entry["object"]["id"] for entry in sources.values()]
    if not source_ids:
        raise CaseBoundaryError("C01 has no language sources")
    gains = ctx.trusted_read("audio_source", source_ids)
    gains_by_id = {row.get("id"): row.get("@VolumeOffset") for row in gains}
    if (len(gains) != len(source_ids) or set(gains_by_id) != set(source_ids)
            or any(type(value) not in {int, float} or not math.isfinite(value)
                   for value in gains_by_id.values())):
        raise CaseBoundaryError("C01 source gain projection is incomplete or malformed")
    for source in sources.values():
        source["volume_offset_db"] = gains_by_id[source["object"]["id"]]
    actions = _children(ctx, event_id, ("action-type", "target", "parent", "notes"))
    if (len(actions) != 1 or actions[0].get("type") != "Action"
            or not isinstance(actions[0].get("target"), Mapping)
            or actions[0]["target"].get("id") != sound_id
            or not isinstance(actions[0].get("parent"), Mapping)
            or actions[0]["parent"].get("id") != event_id):
        raise CaseBoundaryError("Voice Event must own one Action targeting the exact Sound")
    _identity_notes_parent(actions[0], "Action")
    if type(actions[0].get("action_type")) is not int:
        raise CaseBoundaryError("C01 Action type projection is incomplete or malformed")
    sound = read_object(ctx, sound_id, includes=VOICE_INCLUDES)
    event = read_object(ctx, event_id, includes=("notes", "parent"))
    distractor = read_object(ctx, decoy_id, includes=VOICE_INCLUDES)
    _sound_state(sound)
    _sound_state(distractor)
    _identity_notes_parent(event, "Event")
    return {
        "sound": sound,
        "sources": sources,
        "event": event,
        "actions": actions,
        "distractor": distractor,
        "members": sorted(row["id"] for row in _children(ctx, parent_id, ())),
    }


def approve_c01_preview(artifact: Mapping[str, Any], *, version: str,
                        sound_id: str, sound_path: str, replacement: Path) -> bool:
    """Approve only the one language/media change; all other import fields fail closed."""
    request = artifact.get("request")
    prepared = artifact.get("prepared_operation")
    plan = prepared.get("verification_plan") if isinstance(prepared, Mapping) else None
    targets = plan.get("targets") if isinstance(plan, Mapping) else None
    if (not isinstance(request, Mapping) or not isinstance(plan, Mapping)
            or plan.get("kind") != "closed-audio-import"
            or not isinstance(targets, list) or len(targets) != 1
            or not isinstance(targets[0], Mapping) or targets[0].get("preexisting_id") != sound_id
            or plan.get("native_directive_boundaries", []) != []):
        return False
    arguments = request.get("arguments")
    if (request.get("operation") != "audio.import" or request.get("version") != version
            or not isinstance(arguments, Mapping)
            or set(arguments) - {"imports", "import_operation", "defaults", "auto_add_to_source_control"}
            or arguments.get("auto_add_to_source_control", False) is not False
            or arguments.get("import_operation") != "useExisting"):
        return False
    imports, defaults = arguments.get("imports"), arguments.get("defaults", {})
    allowed = {"object_path", "object_type", "audio_file", "import_language", "properties", "references"}
    if (not isinstance(imports, list) or len(imports) != 1
            or not isinstance(imports[0], Mapping) or not isinstance(defaults, Mapping)
            or set(imports[0]) - allowed or set(defaults) - allowed):
        return False
    row = {**defaults, **imports[0]}
    return (row.get("object_path") == sound_path and row.get("audio_file") == str(replacement)
            and row.get("import_language") == "Japanese"
            and row.get("object_type", "Sound Voice") == "Sound Voice"
            and row.get("properties", []) == [] and row.get("references", []) == [])


def verify_c01(before: Mapping[str, Any], after: Mapping[str, Any], *,
               replacement_sha256: str) -> dict[str, bool]:
    prior = before.get("sources", {})
    current = after.get("sources", {})
    return {
        "requested_language_media_matches": (
            isinstance(current, Mapping)
            and current.get("Japanese", {}).get("media", {}).get("sha256") == replacement_sha256
        ),
        "other_language_unchanged": (
            "English(US)" in prior and current.get("English(US)") == prior["English(US)"]
        ),
        "source_gain_unchanged": (
            set(prior) == set(current) == {"English(US)", "Japanese"}
            and all("volume_offset_db" in prior[language]
                    and "volume_offset_db" in current[language]
                    and prior[language]["volume_offset_db"] == current[language]["volume_offset_db"]
                    for language in prior)
        ),
        "requested_language_source_identity_preserved": (
            "Japanese" in prior and "Japanese" in current
            and all(prior["Japanese"]["object"].get(key) == current["Japanese"]["object"].get(key)
                    for key in ("id", "name", "type", "path", "parent", "source_language"))
        ),
        "sound_identity_and_configuration_unchanged": before.get("sound") == after.get("sound"),
        "exact_language_set": set(current) == set(prior) == {"English(US)", "Japanese"},
        "event_and_action_unchanged": (before.get("event") == after.get("event")
                                       and before.get("actions") == after.get("actions")),
        "distractor_unchanged": before.get("distractor") == after.get("distractor"),
        "fixture_membership_unchanged": before.get("members") == after.get("members"),
    }


def _read_failed_event_candidates(ctx: ExpansionCaseContext, event_name: str) -> None:
    """Preserve bounded read diagnostics without retrying the failed import."""
    from tests.semantic.support.codex_expansion_reconciliation import ReconciliationCleanupError
    commands = (
        ["query-object", "--path-segment", "Events", "--path-segment", "Default Work Unit",
         "--path-segment", event_name + "@Play", "--include", "parent"],
        ["query-object", "--path-segment", "Events", "--path-segment", "Default Work Unit",
         "--relationship", "children", "--max-results", "64", "--include", "parent"],
    )
    for command in commands:
        try:
            ctx.gateway(command)
        except ReconciliationCleanupError:
            raise
        except CaseBoundaryError:
            # The owned Gateway already persisted the complete bounded failure
            # receipt. Neither an absent candidate nor a read error is a PASS.
            continue


def _create_english_event_voice(ctx: ExpansionCaseContext, *, parent: Mapping[str, Any],
                                parent_segments: tuple[str, ...],
                                sound_name: str, event_name: str, media: Path) -> dict[str, Any]:
    """Create the Event with the Voice import, then set its scalar Volume separately."""
    draft = BusinessDraft(ctx, "audio.import")
    target = draft.bind(object_id=parent["id"])
    event_parent = draft.bind(segments=("Events", "Default Work Unit"))
    draft.step("draft-declare-import-batch", "--row-order", "voice",
               "--new-row", "voice", target, sound_name, "sound-voice",
               "--event", "voice", event_parent, event_name, "Play",
               "--media-directory", str(media.parent), "--media-file", "voice", media.name,
               "--field", "voice", "language", "English(US)")
    try:
        draft.finish()
    except CaseBoundaryError:
        _read_failed_event_candidates(ctx, event_name)
        raise
    sound = query_path(ctx, (*parent_segments, sound_name), includes=VOICE_INCLUDES)
    _sound_state(sound)

    volume = BusinessDraft(ctx, "object.setProperty")
    sound_handle = volume.bind(object_id=sound["id"])
    field = volume.discover_field(sound_handle, "Volume")
    volume.step("draft-declare-field-change", "--object-handle", sound_handle,
                "--field-handle", field, "--business-value", "-3")
    volume.finish()
    sound = read_object(ctx, sound["id"], includes=VOICE_INCLUDES)
    _sound_state(sound)
    if sound["volume_db"] != -3:
        raise CaseBoundaryError("C01 separate Volume setup did not verify the requested -3 dB readback")
    return sound


def prepare_c01(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    root = container_root(ctx)
    languages = {row.get("Name") for row in ET.parse(ctx.project_path).findall(".//LanguageList/Language")}
    if not {"English(US)", "Japanese"}.issubset(languages):
        raise CaseBoundaryError("C01 requires English(US) and Japanese in the copied project before launch")
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C01 cannot start without the fixed source gain oracle")
    existing = wav_assets(ctx, 3)
    english, japanese, replacement = tuple(
        copy_asset(ctx, source, directory, "C01_line.wav")
        for source, directory in zip(existing, ("english", "japanese", "replacement"), strict=True)
    )
    folder_name = case_name(ctx, "Voices")
    folder = BusinessDraft(ctx, "object.create")
    parent = folder.bind(segments=root)
    folder.step("draft-declare-new", "--declaration-id", "folder", "--parent-handle", parent,
                "--name", folder_name, "--kind", "actor-mixer")
    folder.finish()
    parent_segments = (*root, folder_name)
    parent_row = query_path(ctx, parent_segments)
    # Events use code identifiers: both native lanes normalize '-' to '_'.
    # Choose a stable fixture name up front; the exact Event verifier stays strict.
    sound_name, event_name = "Line_01", case_name(ctx, "Play_Line_01").replace("-", "_")
    sound = _create_english_event_voice(
        ctx, parent=parent_row, parent_segments=parent_segments,
        sound_name=sound_name, event_name=event_name, media=english,
    )
    draft = BusinessDraft(ctx, "audio.import")
    target = draft.bind(object_id=sound["id"])
    draft.step("draft-declare-import-batch", "--row-order", "voice",
               "--existing-row", "voice", target,
               "--media-directory", str(japanese.parent), "--media-file", "voice", japanese.name,
               "--field", "voice", "language", "Japanese")
    draft.finish()
    sound = query_path(ctx, (*parent_segments, sound_name))
    decoy = BusinessDraft(ctx, "object.create")
    target = decoy.bind(object_id=parent_row["id"])
    decoy.step("draft-declare-new", "--declaration-id", "decoy", "--parent-handle", target,
               "--name", "Line_01_Backup", "--kind", "sound-sfx", "--field", "volume_db", "-9")
    decoy.finish()
    decoy_row = query_path(ctx, (*root, folder_name, "Line_01_Backup"))
    event = query_path(ctx, ("Events", "Default Work Unit", event_name))

    def snapshot() -> Mapping[str, Any]:
        return _voice_snapshot(ctx, sound_id=sound["id"], event_id=event["id"],
                               decoy_id=decoy_row["id"], parent_id=parent_row["id"])

    before = snapshot()
    if set(before["sources"]) != {"English(US)", "Japanese"}:
        raise CaseBoundaryError("C01 baseline must have exactly two Voice language associations")
    replacement_sha = hashlib.sha256(replacement.read_bytes()).hexdigest()
    if replacement_sha in {row["media"]["sha256"] for row in before["sources"].values()}:
        raise CaseBoundaryError("C01 replacement must differ from both sealed language files")
    scope = {sound["id"], event["id"], decoy_row["id"], parent_row["id"],
             *(row["object"]["id"] for row in before["sources"].values()),
             *(row["id"] for row in before["actions"])}
    return PreparedExpansionCase(
        prompt=(f"声音 {sound['path']}（{sound['id']}）已有日文 Japanese 和英文 English(US) 对白。"
                f"请用 {replacement} 只更新日文版本，英文素材和语言关联保持不变。沿用现有声音对象，"
                f"音量、输出总线以及事件 {event['path']}（{event['id']}）的播放目标都不变；"
                f"不要修改备用对象 {decoy_row['path']}（{decoy_row['id']}）。"
                "先读取并核对当前状态，展示变更预览，等我确认后再执行；完成后说明两种语言实际关联的素材。"),
        operation="audio.import", policy="ask_before_changes", before=before,
        read_object_ids=frozenset(scope), relationship_sources=frozenset({sound["id"], event["id"], parent_row["id"]}),
        read_includes=frozenset((*VOICE_INCLUDES, *SOURCE_INCLUDES, "action-type", "target")),
        required_assertions=C01_ASSERTIONS,
        approve_preview=lambda artifact: approve_c01_preview(
            artifact, version=ctx.version, sound_id=sound["id"], sound_path=sound["path"], replacement=replacement),
        snapshot=snapshot,
        verify=lambda old, new: verify_c01(old, new, replacement_sha256=replacement_sha),
        archive_oracle_parameters={"replacement_sha256": replacement_sha},
        archive_preview_parameters={"version": ctx.version, "sound_id": sound["id"],
                                    "sound_path": sound["path"], "replacement": str(replacement)},
    )

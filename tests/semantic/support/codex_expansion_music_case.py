"""M01: two Music Tracks, exact media ownership and protected sibling state."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, case_name, copy_asset, file_evidence,
    query_path, read_object, rows, wav_assets,
)


M01_ASSERTIONS = frozenset({
    "parent_and_protected_sibling_unchanged", "exact_segment_track_source_topology",
    "each_track_has_one_sequence_and_clip", "media_hashes_match_each_requested_track",
    "clip_media_matches_its_source", "only_track_has_requested_volume",
})


def _children(ctx: ExpansionCaseContext, object_id: str) -> list[dict[str, Any]]:
    return rows(ctx.gateway(["query-object", "--exact-id", object_id,
                             "--relationship", "children", "--max-results", "16",
                             "--include", "parent"]))


def _one_ref(value: Any) -> str:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
        raise CaseBoundaryError("music fixture requires one complete Sequence/Clip association")
    result = value[0].get("id")
    if not isinstance(result, str):
        raise CaseBoundaryError("music association has no exact identity")
    return result


def _is_sfx(value: Any) -> bool:
    return value == "SFX" or (isinstance(value, Mapping) and value.get("name") == "SFX")


def _music_snapshot(ctx: ExpansionCaseContext, *, parent_id: str, protected_id: str,
                    segment_name: str) -> dict[str, Any]:
    if ctx.trusted_read is None:
        raise CaseBoundaryError("M01 requires the bounded runner-owned music oracle")
    children = _children(ctx, parent_id)
    matching = [row for row in children if row.get("name") == segment_name]
    if len(matching) > 1:
        raise CaseBoundaryError("new music Segment is ambiguous")
    result: dict[str, Any] = {
        "parent": read_object(ctx, parent_id, includes=("parent", "notes")),
        "protected": read_object(ctx, protected_id, includes=("parent", "notes")),
        "children": children, "segment": matching[0] if matching else None, "tracks": {},
    }
    if not matching:
        return result
    segment = matching[0]
    tracks = _children(ctx, segment["id"])
    if segment.get("type") != "MusicSegment" or len(tracks) != 2:
        raise CaseBoundaryError("M01 requires exactly one Segment with two tracks")
    for track in tracks:
        if track.get("type") != "MusicTrack" or track.get("name") in result["tracks"]:
            raise CaseBoundaryError("music Track identity is invalid or duplicated")
        sources = _children(ctx, track["id"])
        if len(sources) != 1 or sources[0].get("type") != "AudioFileSource":
            raise CaseBoundaryError("music Track must own exactly one imported source")
        track_row = dict(ctx.trusted_read("music_track", [track["id"]])[0])
        source = dict(ctx.trusted_read("audio_source", [sources[0]["id"]])[0])
        sequence = dict(ctx.trusted_read("music_sequence", [_one_ref(track_row.get("@Sequences"))])[0])
        clip = dict(ctx.trusted_read("music_clip", [_one_ref(sequence.get("@Clips"))])[0])
        if (sequence.get("type") != "MusicTrackSequence" or clip.get("type") != "MusicClip"
                or not isinstance(source.get("originalFilePath"), str)
                or not isinstance(clip.get("originalFilePath"), str)):
            raise CaseBoundaryError("music oracle cannot prove native types and exact media")
        result["tracks"][track["name"]] = {
            "track": track_row, "source": source, "sequence": sequence, "clip": clip,
            "source_media": file_evidence(ctx, source["originalFilePath"]),
            "clip_media": file_evidence(ctx, clip["originalFilePath"]),
        }
    return result


def approve_m01_preview(artifact: Mapping[str, Any], *, version: str, parent_path: str,
                        segment_name: str, media: Mapping[str, Path]) -> bool:
    request = artifact.get("request")
    if (not isinstance(request, Mapping) or request.get("operation") != "audio.import"
            or request.get("version") != version):
        return False
    args = request.get("arguments")
    if (not isinstance(args, Mapping)
            or set(args) - {"imports", "import_operation", "defaults", "auto_add_to_source_control"}
            or args.get("import_operation", "createNew") != "createNew"
            or args.get("auto_add_to_source_control", False) is not False):
        return False
    imports, defaults = args.get("imports"), args.get("defaults", {})
    if not isinstance(imports, list) or len(imports) != 3 or not isinstance(defaults, Mapping):
        return False
    allowed = {"object_path", "object_type", "audio_file", "import_language", "properties", "references"}
    if set(defaults) - allowed:
        return False
    segment_path = parent_path + "\\" + segment_name
    seen: set[str] = set()
    for item in imports:
        if not isinstance(item, Mapping) or set(item) - allowed:
            return False
        row = {**defaults, **item}
        raw_path = row.get("object_path")
        if not isinstance(raw_path, str):
            return False
        path = re.sub(r"<(?:MusicSegment|MusicTrack)>", "", raw_path)
        if path in seen or row.get("references", []) != []:
            return False
        seen.add(path)
        if path == segment_path:
            if (row.get("audio_file") is not None or row.get("object_type") != "MusicSegment"
                    or row.get("properties", []) != []):
                return False
        else:
            name = path.removeprefix(segment_path + "\\")
            if (name not in media or path != segment_path + "\\" + name
                    or row.get("object_type") != "MusicTrack"
                    or row.get("audio_file") != str(media[name])
                    or row.get("import_language", "SFX") != "SFX"
                    or row.get("properties", []) != ([{"name": "Volume", "value": -6.0}] if name == "Quiet" else [])):
                return False
    return seen == {segment_path, *(segment_path + "\\" + name for name in media)}


def verify_m01(before: Mapping[str, Any], after: Mapping[str, Any], *,
               expected_hashes: Mapping[str, str]) -> dict[str, bool]:
    tracks = after.get("tracks", {})
    segment = after.get("segment")
    complete = isinstance(tracks, Mapping) and set(tracks) == set(expected_hashes) == {"Quiet", "Full"}
    topology = (isinstance(segment, Mapping) and segment.get("type") == "MusicSegment"
                and segment.get("parent", {}).get("id") == before.get("parent", {}).get("id")
                and complete)
    if topology:
        topology = all(row["track"].get("parent", {}).get("id") == segment["id"]
                       and row["source"].get("parent", {}).get("id") == row["track"]["id"]
                       for row in tracks.values())
    old_children = before.get("children", [])
    current_children = after.get("children", [])
    preserved_children = ([row for row in current_children if not isinstance(segment, Mapping)
                           or row.get("id") != segment.get("id")] == old_children)
    return {
        "parent_and_protected_sibling_unchanged": (before.get("parent") == after.get("parent")
                                                   and before.get("protected") == after.get("protected")
                                                   and preserved_children),
        "exact_segment_track_source_topology": bool(topology),
        "each_track_has_one_sequence_and_clip": bool(complete and all(
            row["sequence"].get("type") == "MusicTrackSequence" and row["clip"].get("type") == "MusicClip"
            and _one_ref(row["track"].get("@Sequences")) == row["sequence"]["id"]
            and _one_ref(row["sequence"].get("@Clips")) == row["clip"]["id"]
            for row in tracks.values())),
        "media_hashes_match_each_requested_track": bool(complete and all(
            row["source_media"].get("sha256") == expected_hashes[name] for name, row in tracks.items())),
        "clip_media_matches_its_source": bool(complete and all(
            row["source_media"] == row["clip_media"] for row in tracks.values())),
        "only_track_has_requested_volume": bool(complete and all(
            row["track"].get("@Volume") == (-6 if name == "Quiet" else 0)
            and row["clip"].get("@Volume") == 0
            and row["source"].get("@VolumeOffset") == 0
            and _is_sfx(row["source"].get("audioSource:language"))
            for name, row in tracks.items())),
    }


def prepare_m01(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    if ctx.version not in {"2022.1", "2025.1"}:
        raise CaseBoundaryError("M01 supports the reviewed 2022.1/2025.1 lanes")
    root = ("Containers" if ctx.version == "2025.1" else "Interactive Music Hierarchy", "Default Work Unit")
    root_object = query_path(ctx, root)
    parent_name = case_name(ctx, "Music")
    draft = BusinessDraft(ctx, "object.create")
    parent = draft.bind(object_id=root_object["id"])
    draft.step("draft-declare-new", "--declaration-id", "parent", "--parent-handle", parent,
               "--name", parent_name, "--kind", "music-playlist-container")
    draft.finish()
    parent_object = query_path(ctx, (*root, parent_name))
    protected = BusinessDraft(ctx, "audio.import")
    owner = protected.bind(object_id=parent_object["id"])
    protected.step("draft-declare-import-batch", "--row-order", "keep",
                   "--new-row", "keep", owner, "Keep", "music-segment")
    protected.finish()
    keep = query_path(ctx, (*root, parent_name, "Keep"))
    sources = wav_assets(ctx, 2)
    media = {name: copy_asset(ctx, source, "music", name + ".wav")
             for name, source in zip(("Quiet", "Full"), sources, strict=True)}
    expected = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in media.items()}
    segment_name = "Imported"
    def snapshot():
        return _music_snapshot(ctx, parent_id=parent_object["id"], protected_id=keep["id"], segment_name=segment_name)
    before = snapshot()
    if before["segment"] is not None:
        raise CaseBoundaryError("M01 fixture unexpectedly already has the import target")
    return PreparedExpansionCase(
        prompt=(f"请通过一次批量导入，在 {parent_object['path']}（{parent_object['id']}）下建立音乐段 Imported，"
                f"其中建立 Quiet 和 Full 两条 Music Track，分别导入 {media['Quiet']} 和 {media['Full']}。"
                "只把 Quiet 的 Track 音量设为 -6 dB；Full 保持默认音量，不修改片段或源音量。"
                f"已有 Keep（{keep['id']}）与父级其他内容保持不变，不设置播放列表、Transition 或 Stinger。"
                "这是要实际完成的修改，请核对状态、告知变更并完成执行和核验；说明两条Track各自实际使用的素材。"),
        operation="audio.import", policy="allow_changes", before=before,
        read_object_ids=frozenset({parent_object["id"], keep["id"]}),
        relationship_sources=frozenset({parent_object["id"]}),
        read_includes=frozenset({"parent", "notes", "volume-db", "original-file-path", "source-language"}),
        required_assertions=M01_ASSERTIONS,
        approve_preview=lambda artifact: approve_m01_preview(artifact, version=ctx.version,
            parent_path=parent_object["path"], segment_name=segment_name, media=media),
        snapshot=snapshot,
        verify=lambda old, new: verify_m01(old, new, expected_hashes=expected),
        archive_oracle_parameters={"expected_hashes": expected},
        archive_preview_parameters={"version": ctx.version, "parent_path": parent_object["path"],
            "segment_name": segment_name, "media": {name: str(path) for name, path in media.items()}},
    )

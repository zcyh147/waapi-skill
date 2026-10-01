"""C03: exact-target reimport for equal basenames in distinct directories."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, case_name, container_root, copy_asset,
    file_evidence, query_path, read_object, rows, wav_assets,
)


SOUND_INCLUDES = ("volume-db", "output-bus", "notes", "parent")
SOURCE_INCLUDES = ("source-language", "original-file-path", "parent", "notes")
C03_ASSERTIONS = frozenset({
    "exact_media_mapping", "sound_identities_and_configuration_preserved",
    "source_identities_and_configuration_preserved", "media_destinations_preserved",
    "exact_target_set", "distractor_unchanged", "fixture_membership_unchanged",
})


def approve_c03_preview(artifact: Mapping[str, Any], *, version: str,
                        mappings: Mapping[str, Path], target_ids: Mapping[str, str]) -> bool:
    request = artifact.get("request")
    prepared = artifact.get("prepared_operation")
    plan = prepared.get("verification_plan") if isinstance(prepared, Mapping) else None
    targets = plan.get("targets") if isinstance(plan, Mapping) else None
    if (not isinstance(plan, Mapping) or plan.get("kind") != "closed-audio-import"
            or plan.get("native_directive_boundaries", []) != []
            or not isinstance(targets, list) or len(targets) != len(target_ids)
            or any(not isinstance(row, Mapping) for row in targets)
            or {row.get("canonical_target_path"): row.get("preexisting_id") for row in targets} != dict(target_ids)
            or set(target_ids) != set(mappings)):
        return False
    if (not isinstance(request, Mapping) or request.get("operation") != "audio.import"
            or request.get("version") != version):
        return False
    arguments = request.get("arguments")
    if not isinstance(arguments, Mapping):
        return False
    arguments = dict(arguments)
    if arguments.get("auto_add_to_source_control") is False:
        arguments.pop("auto_add_to_source_control")
    if set(arguments) - {"imports", "import_operation", "defaults"} or arguments.get("import_operation") != "useExisting":
        return False
    imports, defaults = arguments.get("imports"), arguments.get("defaults", {})
    allowed = {"object_path", "object_type", "audio_file", "import_language", "properties", "references"}
    if not isinstance(defaults, Mapping) or set(defaults) - allowed:
        return False
    if not isinstance(imports, list) or len(imports) != len(mappings):
        return False
    seen: set[str] = set()
    for item in imports:
        if not isinstance(item, Mapping) or set(item) - allowed:
            return False
        row = {**defaults, **item}
        row.setdefault("object_type", "Sound SFX")
        row.setdefault("import_language", "SFX")
        for name in ("properties", "references"):
            if row.get(name) == []:
                row.pop(name)
        path = row.get("object_path")
        if not isinstance(path, str) or path not in mappings or path in seen:
            return False
        seen.add(path)
        if row != {"object_path": path, "object_type": "Sound SFX",
                   "audio_file": str(mappings[path]), "import_language": "SFX"}:
            return False
    return seen == set(mappings)


def verify_c03(before: Mapping[str, Any], after: Mapping[str, Any], *,
               expected: Mapping[str, str]) -> dict[str, bool]:
    prior, current = before.get("sounds", {}), after.get("sounds", {})
    exact = (isinstance(prior, Mapping) and isinstance(current, Mapping)
             and set(prior) == set(current) == set(expected))
    def same(field: str) -> bool:
        return exact and all(prior[key].get(field) == current[key].get(field) for key in expected)
    return {
        "exact_target_set": exact,
        "exact_media_mapping": exact and all(
            current[key].get("media", {}).get("sha256") == digest for key, digest in expected.items()),
        "sound_identities_and_configuration_preserved": same("object"),
        "source_identities_and_configuration_preserved": (
            same("source") and same("source_volume_offset")
            and all(type(prior[key].get("source_volume_offset")) in {int, float} for key in expected)),
        "media_destinations_preserved": exact and all(
            prior[key].get("media", {}).get("path") == current[key].get("media", {}).get("path")
            for key in expected),
        "distractor_unchanged": before.get("distractor") == after.get("distractor"),
        "fixture_membership_unchanged": (
            sorted(before.get("members", [])) == sorted(after.get("members", []))),
    }


def _children(ctx: ExpansionCaseContext, object_id: str, includes=()) -> list[dict[str, Any]]:
    command = ["query-object", "--exact-id", object_id, "--relationship", "children",
               "--max-results", "16"]
    for include in includes:
        command.extend(("--include", include))
    return rows(ctx.gateway(command))


def prepare_c03(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C03 requires the independent source-volume oracle")
    root = container_root(ctx)
    assets = wav_assets(ctx, 4)
    initial_left, initial_right, replacement_left, replacement_right = (
        copy_asset(ctx, source, directory, "Hit.wav")
        for source, directory in zip(assets, ("initial_left", "initial_right", "replace_left", "replace_right"), strict=True)
    )
    folder_name = case_name(ctx, "SameBasename")
    draft = BusinessDraft(ctx, "object.create")
    parent = draft.bind(segments=root)
    draft.step("draft-declare-new", "--declaration-id", "folder", "--parent-handle", parent,
               "--name", folder_name, "--kind", "actor-mixer")
    draft.finish()
    folder = query_path(ctx, (*root, folder_name))
    sounds = {}
    for name, media, volume in (("Left", initial_left, "-3"), ("Right", initial_right, "-6")):
        draft = BusinessDraft(ctx, "audio.import")
        parent = draft.bind(object_id=folder["id"])
        draft.step("draft-declare-import-batch", "--row-order", "sound",
                   "--new-row", "sound", parent, name, "sound-sfx",
                   "--media-directory", str(media.parent), "--media-file", "sound", media.name,
                   "--field", "sound", "language", "SFX",
                   "--field", "sound", "volume_db", volume,
                   "--field", "sound", "originals_subfolder", f"Expansion/{ctx.scenario_id}/{name}")
        draft.finish()
        sounds[name] = query_path(ctx, (*root, folder_name, name))
    draft = BusinessDraft(ctx, "object.create")
    parent = draft.bind(object_id=folder["id"])
    draft.step("draft-declare-new", "--declaration-id", "spare", "--parent-handle", parent,
               "--name", "Hit_Backup", "--kind", "sound-sfx", "--field", "volume_db", "-9")
    draft.finish()
    decoy = query_path(ctx, (*root, folder_name, "Hit_Backup"))

    def snapshot() -> Mapping[str, Any]:
        captured = {}
        for sound in sounds.values():
            sources = _children(ctx, sound["id"], SOURCE_INCLUDES)
            if (len(sources) != 1 or sources[0].get("type") != "AudioFileSource"
                    or sources[0].get("parent", {}).get("id") != sound["id"]
                    or not {"id", "name", "type", "path", "source_language", "original_file_path", "parent", "notes"} <= set(sources[0])
                    or not isinstance(sources[0].get("notes"), str)
                    or not isinstance(sources[0].get("original_file_path"), str)):
                raise CaseBoundaryError("C03 requires one exact media source for each Sound")
            identity = read_object(ctx, sound["id"], includes=SOUND_INCLUDES)
            if (not {"id", "name", "type", "path", "volume_db", "output_bus", "notes", "parent"} <= set(identity)
                    or type(identity["volume_db"]) not in {int, float}
                    or not isinstance(identity["notes"], str)
                    or identity["parent"].get("id") != folder["id"]):
                raise CaseBoundaryError("C03 cannot seal missing Sound configuration fields")
            source_state = ctx.trusted_read("audio_source", [sources[0]["id"]])[0]
            source_offset = source_state.get("@VolumeOffset")
            if type(source_offset) not in {int, float}:
                raise CaseBoundaryError("C03 cannot seal a missing AudioFileSource volume offset")
            captured[sound["id"]] = {
                "object": identity,
                "source": sources[0], "media": file_evidence(ctx, sources[0]["original_file_path"]),
                "source_volume_offset": source_offset,
            }
        return {"sounds": captured, "members": sorted(row["id"] for row in _children(ctx, folder["id"])),
                "distractor": read_object(ctx, decoy["id"], includes=SOUND_INCLUDES)}

    before = snapshot()
    replacements = {sounds["Left"]["id"]: replacement_left, sounds["Right"]["id"]: replacement_right}
    expected = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in replacements.items()}
    mappings = {sound["path"]: replacements[sound["id"]] for sound in sounds.values()}
    target_ids = {sound["path"]: sound["id"] for sound in sounds.values()}
    scope = {folder["id"], decoy["id"], *replacements,
             *(row["source"]["id"] for row in before["sounds"].values())}
    return PreparedExpansionCase(
        prompt=(f"请在同一个批量导入预览中重新导入两份同名 Hit.wav：{replacement_left} 对应现有声音 {sounds['Left']['path']}"
                f"（{sounds['Left']['id']}）；{replacement_right} 对应 {sounds['Right']['path']}"
                f"（{sounds['Right']['id']}）。按完整来源路径和指定对象对应，不能只按文件名匹配。"
                "沿用声音和音频源的身份、现有 Originals 位置、音量和输出总线；不要改动备用对象 "
                f"{decoy['path']}（{decoy['id']}）。先给出变更预览，等我确认后执行，完成后核对实际媒体对应关系。"),
        operation="audio.import", policy="ask_before_changes", before=before,
        read_object_ids=frozenset(scope), relationship_sources=frozenset({folder["id"], *replacements}),
        read_includes=frozenset((*SOUND_INCLUDES, *SOURCE_INCLUDES)), required_assertions=C03_ASSERTIONS,
        approve_preview=lambda artifact: approve_c03_preview(artifact, version=ctx.version, mappings=mappings, target_ids=target_ids),
        snapshot=snapshot, verify=lambda old, new: verify_c03(old, new, expected=expected),
        archive_oracle_parameters={"expected": expected},
        archive_preview_parameters={"version": ctx.version, "target_ids": target_ids,
                                    "mappings": {path: str(media) for path, media in mappings.items()}},
    )

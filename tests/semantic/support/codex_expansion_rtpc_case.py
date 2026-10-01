"""C06: update a genuinely existing RTPC while retaining the complete sibling set."""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, case_name, container_root, copy_asset,
    file_evidence, query_path, read_object, rows, wav_assets,
)


TARGET_POINTS = (
    {"x": 0.0, "y": -48.0, "shape": "Linear"},
    {"x": 50.0, "y": -6.0, "shape": "Linear"},
    {"x": 100.0, "y": 0.0, "shape": "Linear"},
)
C06_ASSERTIONS = frozenset({
    "rtpc_identity_set_unchanged", "target_identity_and_binding_unchanged",
    "target_curve_matches", "sibling_curves_unchanged", "owner_configuration_unchanged",
    "media_unchanged", "control_identity_notes_and_parent_unchanged",
})

_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


def _reference_id(value: Any) -> str:
    result = value.get("id") if isinstance(value, Mapping) else value
    if not isinstance(result, str) or not _GUID.fullmatch(result):
        raise CaseBoundaryError("RTPC association lacks a canonical reference identity")
    return result


def _identity_projection(row: Mapping[str, Any], kind: str, *, notes: bool = True,
                         parent: bool = True) -> None:
    _reference_id(row)
    if (row.get("type") != kind or not isinstance(row.get("name"), str)
            or not isinstance(row.get("path"), str) or not row["path"]
            or (notes and not isinstance(row.get("notes"), str))):
        raise CaseBoundaryError(f"C06 {kind} preservation projection is incomplete or malformed")
    if parent:
        _reference_id(row.get("parent"))


def _rtpc_snapshot(ctx: ExpansionCaseContext, owner_id: str,
                   control_ids: tuple[str, str]) -> dict[str, Any]:
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C06 requires the existing runner-owned bounded RTPC oracle")
    owner_rows = ctx.trusted_read("rtpc_owner", [owner_id])
    if len(owner_rows) != 1 or owner_rows[0].get("id") != owner_id:
        raise CaseBoundaryError("RTPC owner oracle does not match the sealed Sound")
    owner = deepcopy(dict(owner_rows[0]))
    _identity_projection(owner, "Sound")
    if (type(owner.get("@Volume")) not in {int, float}
            or not math.isfinite(owner["@Volume"]) or "@OutputBus" not in owner):
        raise CaseBoundaryError("C06 owner volume and routing projection is incomplete or malformed")
    if owner["@OutputBus"] is not None:
        _reference_id(owner["@OutputBus"])
    references = owner.pop("@RTPC", None)
    if not isinstance(references, list) or not 1 <= len(references) <= 8:
        raise CaseBoundaryError("C06 requires a bounded complete nonempty RTPC list")
    ids = [_reference_id(row) for row in references]
    if len(set(ids)) != len(ids):
        raise CaseBoundaryError("RTPC owner contains duplicate associations")
    entries = ctx.trusted_read("rtpc", ids)
    rtpcs = {row["id"]: deepcopy(dict(row)) for row in entries}
    if len(rtpcs) != len(ids) or set(rtpcs) != set(ids):
        raise CaseBoundaryError("RTPC readback does not match the entire owner list")
    for row in rtpcs.values():
        # RTPCs are derived owner-list objects; parent hierarchy is not the binding oracle.
        _identity_projection(row, "RTPC", parent=False)
        curve = row.get("@Curve")
        if (row.get("type") != "RTPC" or not isinstance(row.get("@PropertyName"), str)
                or not isinstance(curve, Mapping) or not isinstance(curve.get("points"), list)
                or not 1 <= len(curve["points"]) <= 256):
            raise CaseBoundaryError("RTPC curve or property readback is unavailable")
        _reference_id(row.get("@ControlInput"))
        for point in curve["points"]:
            if (not isinstance(point, Mapping) or not isinstance(point.get("shape"), str)
                    or any(type(point.get(key)) not in {int, float}
                           or not math.isfinite(point[key]) for key in ("x", "y"))):
                raise CaseBoundaryError("C06 RTPC points are incomplete or malformed")
    source_rows = rows(ctx.gateway([
        "query-object", "--exact-id", owner_id, "--relationship", "children", "--max-results", "8",
        "--include", "source-language", "--include", "original-file-path", "--include", "parent",
    ]))
    if (len(source_rows) != 1 or source_rows[0].get("type") != "AudioFileSource"
            or not isinstance(source_rows[0].get("parent"), Mapping)
            or source_rows[0]["parent"].get("id") != owner_id):
        raise CaseBoundaryError("C06 fixture must own one unchanged audio source")
    source = source_rows[0]
    _identity_projection(source, "AudioFileSource", notes=False)
    if (not isinstance(source.get("original_file_path"), str) or not source["original_file_path"]
            or not isinstance(source.get("source_language"), Mapping)
            or not isinstance(source["source_language"].get("name"), str)):
        raise CaseBoundaryError("C06 source language and file projection is incomplete or malformed")
    controls = [read_object(ctx, item, includes=("notes", "parent")) for item in control_ids]
    for control in controls:
        _identity_projection(control, "GameParameter")
    return {
        "owner": owner, "rtpcs": rtpcs,
        "media": {"source": source_rows[0], "file": file_evidence(ctx, source_rows[0]["original_file_path"])},
        "controls": controls,
    }


def approve_c06_preview(artifact: Mapping[str, Any], *, version: str,
                        owner_id: str, control_id: str, target_id: str,
                        expected_notes: str) -> bool:
    request = artifact.get("request")
    prepared = artifact.get("prepared_operation")
    plan = prepared.get("verification_plan") if isinstance(prepared, Mapping) else None
    if (not isinstance(request, Mapping) or request.get("operation") != "object.setRTPC"
            or request.get("version") != version or not isinstance(plan, Mapping)
            or plan.get("kind") != "object-rtpc-state" or plan.get("action") != "update"
            or plan.get("existing_rtpc_id") != target_id or plan.get("object_id") != owner_id
            or plan.get("control_input_id") != control_id):
        return False
    arguments = request.get("arguments")
    if (not isinstance(arguments, Mapping)
            or set(arguments) - {"object", "property", "control_input", "points", "mode", "notes"}
            or not {"object", "property", "control_input", "points", "mode"}.issubset(arguments)
            or arguments.get("notes", expected_notes) != expected_notes):
        return False
    points = arguments["points"]
    if (not isinstance(points, list) or any(not isinstance(point, Mapping)
            or set(point) != {"x", "y", "shape"}
            or any(type(point[key]) not in {int, float} or not math.isfinite(point[key])
                   for key in ("x", "y")) for point in points)):
        return False
    return (arguments["object"] == {"kind": "id", "value": owner_id}
            and arguments["property"] == "Volume"
            and arguments["control_input"] == {"kind": "id", "value": control_id}
            and arguments["points"] == list(TARGET_POINTS)
            and arguments["mode"] == "add_or_replace")


def verify_c06(before: Mapping[str, Any], after: Mapping[str, Any], *,
               target_id: str) -> dict[str, bool]:
    prior, current = before.get("rtpcs", {}), after.get("rtpcs", {})
    old_target, new_target = prior.get(target_id), current.get(target_id)
    bound = isinstance(old_target, Mapping) and isinstance(new_target, Mapping)
    return {
        "rtpc_identity_set_unchanged": set(prior) == set(current) and target_id in current,
        "target_identity_and_binding_unchanged": bool(bound and
            {key: value for key, value in old_target.items() if key != "@Curve"}
            == {key: value for key, value in new_target.items() if key != "@Curve"}),
        "target_curve_matches": bool(bound and isinstance(new_target.get("@Curve"), Mapping)
                                      and new_target["@Curve"].get("points") == list(TARGET_POINTS)),
        "sibling_curves_unchanged": (len(prior) > 1 and
            {key: value for key, value in prior.items() if key != target_id}
            == {key: value for key, value in current.items() if key != target_id}),
        "owner_configuration_unchanged": before.get("owner") == after.get("owner"),
        "media_unchanged": before.get("media") == after.get("media"),
        # Range/default values are not projected; no full GameParameter-state claim.
        "control_identity_notes_and_parent_unchanged": before.get("controls") == after.get("controls"),
    }


def prepare_c06(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    root = container_root(ctx)
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C06 cannot start without its bounded trusted oracle")
    controls = tuple(query_path(ctx, ("Game Parameters", "Ambience", name))
                     for name in ("Rain_Intensity", "Time"))
    if any(row.get("type") != "GameParameter" for row in controls):
        raise CaseBoundaryError("C06 pinned baseline control objects are unavailable")
    media = copy_asset(ctx, wav_assets(ctx, 1)[0], "rtpc", "C06_bed.wav")
    name = case_name(ctx, "Bed")
    draft = BusinessDraft(ctx, "audio.import")
    parent = draft.bind(segments=root)
    draft.step("draft-declare-import-batch", "--row-order", "bed",
               "--new-row", "bed", parent, name, "sound-sfx",
               "--media-directory", str(media.parent), "--media-file", "bed", media.name,
               "--field", "bed", "volume_db", "-3")
    draft.finish()
    owner = query_path(ctx, (*root, name))
    for meaning, control, points in (
        ("volume", controls[0], ((0, -48), (50, -12), (100, 0))),
        ("pitch", controls[1], ((0, -100), (100, 100))),
    ):
        draft = BusinessDraft(ctx, "object.setRTPC")
        owner_handle = draft.bind(object_id=owner["id"])
        field = draft.discover_field(owner_handle, meaning)
        control_handle = draft.bind(object_id=control["id"])
        arguments = ["--object-handle", owner_handle, "--field-handle", field,
                     "--control-input-handle", control_handle, "--mode", "add-only",
                     "--notes", f"Preserve {meaning} association"]
        for x, y in points:
            arguments.extend(("--point", str(x), str(y), "Linear"))
        draft.step("draft-declare-rtpc", *arguments)
        draft.finish()
    control_ids = (controls[0]["id"], controls[1]["id"])

    def snapshot() -> Mapping[str, Any]:
        return _rtpc_snapshot(ctx, owner["id"], control_ids)

    before = snapshot()
    targets = [key for key, row in before["rtpcs"].items()
               if row["@PropertyName"] == "Volume"
               and _reference_id(row["@ControlInput"]) == control_ids[0]]
    if len(before["rtpcs"]) != 2 or len(targets) != 1:
        raise CaseBoundaryError("C06 needs one existing target and one distinct sibling curve")
    target_id = targets[0]
    if before["rtpcs"][target_id]["@Curve"]["points"] == list(TARGET_POINTS):
        raise CaseBoundaryError("C06 baseline already equals the requested update")
    return PreparedExpansionCase(
        prompt=(f"声音 {owner['path']}（{owner['id']}）已有 {controls[0]['path']}（{control_ids[0]}）"
                f"控制音量的曲线（关系对象 {target_id}）。只把这条曲线改为 (0,-48)、(50,-6)、(100,0)，"
                "各段线性。保留这条控制关系的身份和备注，其他控制曲线、声音、素材、路由均不变。"
                "这是要实际完成的修改，请核对当前状态、告知变更并完成执行和核验；不能表达或核验的部分请明确说明。"),
        operation="object.setRTPC", policy="allow_changes", before=before,
        read_object_ids=frozenset({owner["id"], *control_ids, *before["rtpcs"], before["media"]["source"]["id"]}),
        relationship_sources=frozenset({owner["id"]}),
        read_includes=frozenset({"notes", "volume-db", "pitch-cents", "output-bus", "parent", "source-language", "original-file-path"}),
        required_assertions=C06_ASSERTIONS,
        approve_preview=lambda artifact: approve_c06_preview(
            artifact, version=ctx.version, owner_id=owner["id"], control_id=control_ids[0],
            target_id=target_id, expected_notes=before["rtpcs"][target_id].get("notes", "")),
        snapshot=snapshot, verify=lambda old, new: verify_c06(old, new, target_id=target_id),
        archive_oracle_parameters={"target_id": target_id},
        archive_preview_parameters={"version": ctx.version, "owner_id": owner["id"],
                                    "control_id": control_ids[0], "target_id": target_id,
                                    "expected_notes": before["rtpcs"][target_id].get("notes", "")},
        read_fields=frozenset({"PropertyName", "ControlInput", "Curve"}),
    )

"""C08: a copied attenuation's dry-volume curve, independently read back."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, case_name, container_root, query_path, read_object,
)


C08_API = "ak.wwise.core.object.setAttenuationCurve"
C08_CURVE_ROLES = (
    "volume-dry", "game-defined-aux-send-volume", "user-defined-aux-send-volume",
    "low-pass-filter", "high-pass-filter", "spread", "focus",
)
_SOURCE_ID = "{D7B7A627-3D4A-4921-842E-0A38A2DB2492}"
_IDENTITY_INCLUDES = ("parent", "notes")


C08_ASSERTIONS = frozenset({
    "requested_curve_matches", "other_curves_unchanged",
    "attenuation_identity_unchanged", "users_and_references_unchanged",
    "source_attenuation_unchanged",
})


def _valid_points(points: Any) -> bool:
    return isinstance(points, list) and len(points) <= 256 and all(
        isinstance(point, Mapping) and set(point) == {"x", "y", "shape"}
        and all(type(point[key]) in {int, float} and math.isfinite(point[key]) for key in ("x", "y"))
        and isinstance(point["shape"], str) and bool(point["shape"])
        for point in points
    )


def approve_c08_preview(artifact: Mapping[str, Any], *, version: str, object_id: str,
                        expected_points: Sequence[Mapping[str, Any]]) -> bool:
    request = artifact.get("request")
    if not isinstance(request, Mapping):
        return False
    arguments = request.get("arguments")
    args = arguments.get("args") if isinstance(arguments, Mapping) else None
    return bool(request.get("operation") == "waapi.call" and request.get("version") == version
        and isinstance(args, Mapping) and _valid_points(args.get("points"))
        and arguments == {"api": C08_API, "options": {}, "args": {
            "object": object_id, "curveType": "VolumeDryUsage", "use": "Custom",
            "points": list(expected_points),
        }})


def verify_c08(before: Mapping[str, Any], after: Mapping[str, Any], *,
               expected_points: Sequence[Mapping[str, Any]]) -> dict[str, bool]:
    prior, current = before.get("curves"), after.get("curves")
    valid = isinstance(prior, Mapping) and isinstance(current, Mapping)
    return {
        "requested_curve_matches": bool(valid
            and isinstance(current.get("volume-dry"), Mapping)
            and _valid_points(current["volume-dry"].get("points"))
            and current.get("volume-dry") == {
            "use": "Custom", "points": list(expected_points),
        }),
        "other_curves_unchanged": bool(valid and "volume-dry" in prior
            and len(prior) > 1 and set(prior) == set(current)
            and all(current[role] == value for role, value in prior.items() if role != "volume-dry")),
        "attenuation_identity_unchanged": bool(before.get("attenuation")
            and before["attenuation"] == after.get("attenuation")),
        "users_and_references_unchanged": bool(before.get("users")
            and before["users"] == after.get("users")),
        "source_attenuation_unchanged": bool(before.get("source")
            and before["source"] == after.get("source")),
    }


def _curves(ctx: ExpansionCaseContext, object_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in C08_CURVE_ROLES:
        payload = ctx.gateway(["metadata", "attenuation", "--exact-id", object_id,
                               "--curve-role", role])
        curve = payload.get("agent_result")
        if (payload.get("ok") is not True or payload.get("status") != "ok"
                or not isinstance(curve, Mapping) or curve.get("curve_role") != role
                or not isinstance(curve.get("use"), str) or not _valid_points(curve.get("points"))):
            raise CaseBoundaryError("C08 requires every bounded attenuation curve read")
        result[role] = {"use": curve["use"], "points": curve["points"]}
    return result


def prepare_c08(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    root = container_root(ctx)
    source = read_object(ctx, _SOURCE_ID, includes=_IDENTITY_INCLUDES)
    if source.get("type") != "Attenuation":
        raise CaseBoundaryError("C08 requires the pinned SampleProject Horns attenuation")
    source_curves = _curves(ctx, _SOURCE_ID)
    if (source_curves["spread"]["use"] != "Custom" or not source_curves["spread"]["points"]):
        raise CaseBoundaryError("C08 needs a nonempty unrelated custom Spread curve to preserve")
    copy = BusinessDraft(ctx, "object.copy")
    copy.bind(object_id=_SOURCE_ID, role="object")
    copy.bind(segments=("Attenuations", "Default Work Unit"), role="parent")
    copy.step("draft-declare-object-change", "--name-conflict", "rename")
    copied = copy.finish()
    copied_id = copied["execute"].get("dispatch_result", {}).get("result", {}).get("id")
    if not isinstance(copied_id, str) or copied_id == _SOURCE_ID:
        raise CaseBoundaryError("C08 copy did not produce an independent attenuation identity")
    rename = BusinessDraft(ctx, "object.setName")
    rename.bind(object_id=copied_id, role="object")
    rename.step("draft-declare-object-change", "--new-name", case_name(ctx, "Attenuation"))
    rename.finish()

    sound_name = case_name(ctx, "AttenuatedSound")
    create = BusinessDraft(ctx, "object.create")
    parent = create.bind(segments=root)
    create.step("draft-declare-new", "--declaration-id", "sound", "--parent-handle", parent,
                "--name", sound_name, "--kind", "sound-sfx", "--field", "volume_db", "-3")
    create.finish()
    sound = query_path(ctx, (*root, sound_name))
    reference = BusinessDraft(ctx, "object.setReference")
    owner = reference.bind(object_id=sound["id"])
    target = reference.bind(object_id=copied_id)
    field = reference.discover_field(owner, "Attenuation")
    reference.step("draft-declare-field-change", "--object-handle", owner,
                   "--field-handle", field, "--target-handle", target)
    reference.finish()

    def snapshot() -> dict[str, Any]:
        user = read_object(ctx, sound["id"], includes=(*_IDENTITY_INCLUDES, "volume-db", "output-bus"),
                           fields=("Attenuation",))
        bound = user.get("references", {}).get("Attenuation")
        if not isinstance(bound, Mapping) or bound.get("id") != copied_id:
            raise CaseBoundaryError("C08 Sound no longer references the exact copied attenuation")
        return {
            "attenuation": read_object(ctx, copied_id, includes=_IDENTITY_INCLUDES),
            "curves": _curves(ctx, copied_id),
            "users": {sound["id"]: user},
            "source": {"object": read_object(ctx, _SOURCE_ID, includes=_IDENTITY_INCLUDES),
                       "curves": _curves(ctx, _SOURCE_ID)},
        }

    before = ctx.observe_before(snapshot)
    if before["source"] != {"object": source, "curves": source_curves}:
        raise CaseBoundaryError("C08 fixture setup changed the original attenuation")
    old_points = before["curves"]["volume-dry"]["points"]
    if len(old_points) < 2 or old_points[-1]["x"] <= old_points[0]["x"]:
        raise CaseBoundaryError("C08 baseline has no usable dry-volume distance domain")
    start, end = old_points[0]["x"], old_points[-1]["x"]
    points = [
        {"x": start, "y": 0.0, "shape": "Linear"},
        {"x": (start + end) / 2, "y": -12.0, "shape": "Linear"},
        {"x": end, "y": -48.0, "shape": "Linear"},
    ]
    if before["curves"]["volume-dry"] == {"use": "Custom", "points": points}:
        raise CaseBoundaryError("C08 requested curve must differ from the sealed baseline")
    attenuation = before["attenuation"]
    return PreparedExpansionCase(
        prompt=(f"请把衰减对象 {attenuation['path']}（{copied_id}）的干声音量曲线改为自定义线性曲线，"
                f"距离与分贝三个点为 ({start},0)、({(start + end) / 2},-12)、({end},-48)。"
                "只改这一条曲线，其余六条曲线及对象身份、备注都保持不变；"
                f"声音 {sound['path']}（{sound['id']}）的衰减引用、音量和路由保持不变，"
                f"原衰减 {source['path']}（{_SOURCE_ID}）也不要修改。"
                "这是要实际完成的修改，请核对当前状态、告知变更并完成执行和核验；"
                "按已保存的允许修改策略取得本次独立授权。请报告实际曲线数据，不评价听感。"),
        operation="waapi.call", request_schema_uri=C08_API, policy="allow_changes",
        accepted_verification_states=frozenset({"result_schema_checked"}), before=before,
        read_object_ids=frozenset({copied_id, sound["id"], _SOURCE_ID}),
        relationship_sources=frozenset(), read_includes=frozenset((*_IDENTITY_INCLUDES, "volume-db", "output-bus")),
        read_fields=frozenset({"Attenuation"}), read_curve_roles=frozenset(C08_CURVE_ROLES),
        required_assertions=C08_ASSERTIONS,
        approve_preview=lambda artifact: approve_c08_preview(
            artifact, version=ctx.version, object_id=copied_id, expected_points=points),
        snapshot=snapshot, verify=lambda old, new: verify_c08(old, new, expected_points=points),
        archive_oracle_parameters={"expected_points": points},
        archive_preview_parameters={"version": ctx.version, "object_id": copied_id, "expected_points": points},
    )

"""M05: existing Stinger Trigger maintenance, with a separate 2022 boundary."""

from __future__ import annotations

from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError, read_object


STINGER = "{B8D45849-AF76-4770-BE7B-5A6553B1337B}"
OWNER = "{20FA9A69-7ECC-4B05-BD6B-2C9527CD88C2}"
BONUS = "{25D1ACE1-D5FA-450D-826B-745E8B0838BB}"
TARGET = "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}"
SEGMENT = "{B54923CD-4369-451A-8E64-C142D368037E}"
PROTECTED_STINGER = "{ACA5AD21-9FBC-4DA6-BA3A-CDF7CB27F023}"
PROTECTED_OWNER = "{52B9FAC3-636E-44F8-9015-E5F24E30E39E}"
M05_ASSERTIONS = frozenset({
    "requested_trigger_matches", "segment_reference_preserved",
    "stinger_identity_and_other_configuration_preserved", "other_stingers_preserved",
    "target_and_segment_unchanged", "owner_unchanged",
})


def _without_trigger(row: Mapping[str, Any]) -> dict[str, Any]:
    # Wwise derives these display fields from the Trigger/Segment association.
    # GUID, type, owner and the actual remaining configuration stay authoritative.
    return {key: value for key, value in row.items() if key not in {"@Trigger", "name", "path"}}


def _owner_state(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if "@Stingers" in result:
        result["@Stingers"] = sorted(item["id"] for item in result["@Stingers"])
    return result


def verify_m05(before: Mapping[str, Any], after: Mapping[str, Any], *, target_id: str) -> dict[str, bool]:
    old, new = before.get("stinger", {}), after.get("stinger", {})
    def normalized_siblings(value):
        return sorted((_without_trigger(row) if row.get("id") == old.get("id") else row
                       for row in value), key=lambda row: row["id"])
    return {
        "requested_trigger_matches": new.get("@Trigger", {}).get("id") == target_id,
        "segment_reference_preserved": old.get("@Segment") is not None and old.get("@Segment") == new.get("@Segment"),
        "stinger_identity_and_other_configuration_preserved": bool(old) and _without_trigger(old) == _without_trigger(new),
        "other_stingers_preserved": (
            bool(before.get("protected")) and before["protected"] == after.get("protected")
            and normalized_siblings(before.get("siblings", [])) == normalized_siblings(after.get("siblings", []))),
        "target_and_segment_unchanged": before.get("target") == after.get("target") and before.get("segment") == after.get("segment"),
        "owner_unchanged": _owner_state(before.get("owner", {})) == _owner_state(after.get("owner", {})),
    }


def approve_m05_preview(artifact: Mapping[str, Any], *, version: str) -> bool:
    request = artifact.get("request")
    return isinstance(request, Mapping) and (
        request.get("operation") == "object.setReference" and request.get("version") == version
        and request.get("arguments") == {
            "object": {"kind": "id", "value": STINGER}, "reference": "Trigger",
            "target": {"kind": "id", "value": TARGET},
        })


def prepare_m05(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    if ctx.version not in {"2022.1", "2025.1"}:
        raise CaseBoundaryError("M05 has no reviewed version lane")
    if ctx.version == "2022.1":
        from tests.semantic.support.codex_expansion_cases import ExpectedCapabilityBoundary
        before = read_object(ctx, STINGER)
        observed = ctx.gateway(["query-object", "--exact-id", STINGER,
                                "--include-field", "Trigger", "--include-field", "Segment"])
        result = observed.get("agent_result")
        unresolved = ({row.get("meaning"): row.get("candidate_names") for row in result.get("unresolved", [])}
                      if isinstance(result, Mapping) else {})
        after = read_object(ctx, STINGER)
        if (observed.get("status") != "needs_clarification" or unresolved.get("Trigger") != []
                or "Segment" not in unresolved or "Segment" in unresolved["Segment"] or before != after):
            raise CaseBoundaryError("M05 expected reference boundary was not independently reproduced")
        raise ExpectedCapabilityBoundary("M05", ctx.version, {
            "public_observation": observed, "identity_before": before, "identity_after": after,
            "agent_executed": False, "business_effect_verified": False,
            "reason": "matching live metadata does not expose the required Stinger references",
        })
    if ctx.trusted_read is None:
        raise CaseBoundaryError("M05 requires the sealed independent read-only oracle")

    def snapshot() -> Mapping[str, Any]:
        owner = ctx.trusted_read("music_stinger_owner", [OWNER])[0]
        members = owner.get("@Stingers")
        if (not isinstance(members, list) or not 1 <= len(members) <= 16
                or any(not isinstance(row, Mapping) or not isinstance(row.get("id"), str) for row in members)):
            raise CaseBoundaryError("Stinger owner does not expose bounded exact membership")
        ids = [row["id"] for row in members]
        if STINGER not in ids or len(set(ids)) != len(ids):
            raise CaseBoundaryError("Stinger ownership is missing or duplicated")
        siblings = ctx.trusted_read("music_stinger", ids)
        by_id = {row["id"]: row for row in siblings}
        return {"stinger": by_id[STINGER], "siblings": list(siblings), "owner": owner,
                "target": ctx.trusted_read("identity", [TARGET])[0],
                "segment": ctx.trusted_read("identity", [SEGMENT])[0],
                "protected": {
                    "stinger": ctx.trusted_read("music_stinger", [PROTECTED_STINGER])[0],
                    "owner": ctx.trusted_read("music_stinger_owner", [PROTECTED_OWNER])[0],
                }}

    before = snapshot()
    stinger = before["stinger"]
    for row in (stinger, before["protected"]["stinger"]):
        if (not {"id", "name", "type", "path", "parent", "notes", "@Trigger", "@Segment", "@NumSegmentAdvance", "@PlaySegmentAt"} <= set(row)
                or any(type(row[key]) is not int for key in ("@NumSegmentAdvance", "@PlaySegmentAt"))
                or not isinstance(row["notes"], str)):
            raise CaseBoundaryError("M05 cannot seal missing Stinger timing/configuration fields")
    if (stinger.get("@Trigger", {}).get("id") != BONUS or stinger.get("@Segment", {}).get("id") != SEGMENT
            or before["target"].get("type") != "Trigger"):
        raise CaseBoundaryError("M05 fixed fixture references differ from the reviewed baseline")
    protected = before["protected"]
    if (protected["stinger"].get("type") != "MusicStinger"
            or PROTECTED_STINGER not in {row.get("id") for row in protected["owner"].get("@Stingers", [])}):
        raise CaseBoundaryError("M05 requires a real non-target Stinger preservation witness")
    return PreparedExpansionCase(
        prompt=(f"请将现有 Stinger {STINGER} 的触发器从 Bonus 改为 {before['target']['name']}（{TARGET}）。"
                f"保持关联音乐段 {SEGMENT} 不变，不修改 Stinger 的其他设置、所属 Stealth 容器 {OWNER}"
                f"及其他 Stinger，特别是 Stress 容器里的 {PROTECTED_STINGER}。"
                "读取并核对实际对象后完成预览、授权、执行和回读验收，不需要播放测试。"),
        operation="object.setReference", policy="allow_changes", before=before,
        read_object_ids=frozenset({STINGER, OWNER, BONUS, TARGET, SEGMENT, PROTECTED_STINGER, PROTECTED_OWNER}), relationship_sources=frozenset(),
        read_includes=frozenset({"parent", "notes"}), read_fields=frozenset({"Trigger", "Segment"}),
        required_assertions=M05_ASSERTIONS, approve_preview=lambda artifact: approve_m05_preview(artifact, version=ctx.version),
        snapshot=snapshot, verify=lambda old, new: verify_m05(old, new, target_id=TARGET),
        archive_oracle_parameters={"target_id": TARGET},
    )

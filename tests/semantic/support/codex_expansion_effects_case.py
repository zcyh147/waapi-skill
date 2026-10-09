"""C09: append one effect while independently preserving existing bindings."""

from __future__ import annotations

import re
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, case_name, container_root, query_path,
)


_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
_EMPTY_GUID = "{00000000-0000-0000-0000-000000000000}"
_REQUESTED_NOTES = "Expansion C09 appended gain"


C09_ASSERTIONS = frozenset({
    "owner_unchanged", "exactly_one_added_binding", "existing_effects_and_bindings_unchanged",
    "new_effect_matches", "unique_effect_identities",
    "new_effect_owned_by_target",
})


def approve_c09_preview(artifact: Mapping[str, Any], *, version: str, owner_id: str,
                        class_id: int, name: str, notes: str) -> bool:
    request = artifact.get("request")
    return bool(isinstance(request, Mapping) and request.get("operation") == "object.createPlugin"
        and request.get("version") == version and request.get("arguments") == {
            "target": {"kind": "id", "value": owner_id},
            "plugin": {"kind": "effect", "name": name, "class_id": class_id, "notes": notes},
        })


def _entries(snapshot: Mapping[str, Any], *, version: str) -> dict[str, Mapping[str, Any]] | None:
    entries = snapshot.get("entries")
    owner = snapshot.get("owner")
    if (version not in {"2022.1", "2025.1"} or not isinstance(owner, Mapping)
            or not isinstance(owner.get("id"), str)
            or not isinstance(entries, list) or not 1 <= len(entries) <= (4 if version == "2022.1" else 16)):
        return None
    result: dict[str, Mapping[str, Any]] = {}
    effect_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"slot", "slot_state", "effect"}:
            return None
        slot, effect = entry["slot"], entry["effect"]
        if (not isinstance(slot, str) or not slot or slot in result
                or not isinstance(effect, Mapping) or not isinstance(effect.get("id"), str)
                or effect["id"].casefold() in effect_ids):
            return None
        slot_state = entry["slot_state"]
        if version == "2022.1":
            if slot not in {"0", "1", "2", "3"} or slot_state is not None:
                return None
            expected_owner = owner["id"]
        else:
            if (not isinstance(slot_state, Mapping) or slot_state.get("id") != slot
                    or slot_state.get("type") != "EffectSlot"
                    or not isinstance(slot_state.get("owner"), Mapping)
                    or slot_state["owner"].get("id") != owner["id"]
                    or not isinstance(slot_state.get("@Effect"), Mapping)
                    or slot_state["@Effect"].get("id") != effect["id"]):
                return None
            expected_owner = slot
        if (not isinstance(effect.get("owner"), Mapping)
                or effect["owner"].get("id") != expected_owner
                or ("parent" in effect and (not isinstance(effect["parent"], Mapping)
                    or effect["parent"].get("id") != expected_owner))):
            return None
        result[slot] = entry
        effect_ids.add(effect["id"].casefold())
    order = snapshot.get("slot_order")
    if (not isinstance(order, list) or any(not isinstance(slot, str) for slot in order)
            or len(order) != len(result) or set(order) != set(result)
            or (version == "2022.1" and order != sorted(result, key=int))):
        return None
    return result


def verify_c09(before: Mapping[str, Any], after: Mapping[str, Any], *,
               version: str, expected_class_id: int, expected_name: str, expected_notes: str) -> dict[str, bool]:
    prior, current = _entries(before, version=version), _entries(after, version=version)
    valid = prior is not None and current is not None
    added = set(current) - set(prior) if valid else set()
    added_slot = next(iter(added)) if len(added) == 1 else None
    new = current[added_slot]["effect"] if added_slot is not None else {}
    appended = bool(valid and added_slot is not None
        and after["slot_order"] == before["slot_order"] + [added_slot])
    if appended and version == "2022.1":
        appended = added_slot == next((str(index) for index in range(4) if str(index) not in prior), None)
    return {
        "owner_unchanged": bool(before.get("owner") and before["owner"] == after.get("owner")),
        "exactly_one_added_binding": bool(appended and set(prior) <= set(current)),
        "existing_effects_and_bindings_unchanged": bool(valid and all(
            current.get(slot) == entry for slot, entry in prior.items())),
        "new_effect_matches": bool(new and new.get("type") == "Effect"
            and type(new.get("classId")) is int and new["classId"] == expected_class_id
            and new.get("name") == expected_name and new.get("notes") == expected_notes),
        "unique_effect_identities": valid,
        "new_effect_owned_by_target": bool(valid and new),
    }


def _reference_id(value: Any, *, empty_allowed: bool = False) -> str | None:
    if empty_allowed and value is None:
        return None
    identifier = value.get("id") if isinstance(value, Mapping) else value
    if empty_allowed and identifier == _EMPTY_GUID:
        return None
    if (not isinstance(identifier, str) or not _GUID.fullmatch(identifier)
            or identifier == _EMPTY_GUID):
        raise CaseBoundaryError("C09 effect collection has an invalid object reference")
    return identifier


def _effect_snapshot(ctx: ExpansionCaseContext, owner_id: str) -> dict[str, Any]:
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C09 requires the runner's fixed effect oracle projections")
    owner_rows = ctx.trusted_read("effect_owner", (owner_id,))
    if len(owner_rows) != 1:
        raise CaseBoundaryError("C09 owner read is not exact")
    owner = dict(owner_rows[0])
    required_owner = {"id", "name", "type", "path", "parent", "@Volume", "notes"}
    if (not required_owner <= set(owner) or owner["id"] != owner_id
            or owner["type"] != "Sound"):
        raise CaseBoundaryError("C09 owner projection is incomplete or has another identity")
    bindings: list[tuple[str, str, Mapping[str, Any] | None]] = []
    slot_order: list[str] = []
    if ctx.version == "2022.1":
        for index in range(4):
            field = f"@Effect{index}"
            if field not in owner:
                raise CaseBoundaryError("C09 fixed Effect reference projection is incomplete")
            plugin_id = _reference_id(owner.pop(field), empty_allowed=True)
            if plugin_id is not None:
                bindings.append((str(index), plugin_id, None))
                slot_order.append(str(index))
    elif ctx.version == "2025.1":
        slots = owner.pop("@Effects", None)
        if not isinstance(slots, list) or not 1 <= len(slots) <= 16:
            raise CaseBoundaryError("C09 requires a bounded nonempty EffectSlot list")
        slot_ids = tuple(_reference_id(slot) for slot in slots)
        slot_order = list(slot_ids)
        if len({identifier.upper() for identifier in slot_ids}) != len(slot_ids):
            raise CaseBoundaryError("C09 EffectSlot list contains duplicate identities")
        slot_rows = ctx.trusted_read("effect_slot", slot_ids)
        if len(slot_rows) != len(slot_ids) or {row.get("id") for row in slot_rows} != set(slot_ids):
            raise CaseBoundaryError("C09 EffectSlot read does not close the owner list")
        for slot in slot_rows:
            if (not {"id", "name", "type", "path", "owner", "@Effect"} <= set(slot)
                    or slot["type"] != "EffectSlot" or _reference_id(slot["owner"]) != owner_id):
                raise CaseBoundaryError("C09 EffectSlot ownership readback is incomplete")
            bindings.append((str(slot["id"]), str(_reference_id(slot["@Effect"])), dict(slot)))
    else:
        raise CaseBoundaryError("C09 has no reviewed effect topology in this version")
    plugin_ids = tuple(plugin_id for _, plugin_id, _ in bindings)
    if not plugin_ids or len({value.upper() for value in plugin_ids}) != len(plugin_ids):
        raise CaseBoundaryError("C09 effect bindings are empty or duplicated")
    plugin_rows = ctx.trusted_read("effect_plugin", plugin_ids)
    if len(plugin_rows) != len(plugin_ids) or {row.get("id") for row in plugin_rows} != set(plugin_ids):
        raise CaseBoundaryError("C09 effect plugin read does not close every slot binding")
    plugins = {row["id"]: dict(row) for row in plugin_rows}
    entries: list[dict[str, Any]] = []
    for slot_id, plugin_id, slot in bindings:
        plugin = plugins[plugin_id]
        if (not {"id", "name", "type", "path", "owner", "classId", "notes"} <= set(plugin)
                or plugin["type"] != "Effect" or type(plugin["classId"]) is not int
                or not isinstance(plugin["notes"], str) or _reference_id(plugin["owner"]) != (
                    owner_id if ctx.version == "2022.1" else slot_id)):
            raise CaseBoundaryError("C09 plugin identity, class or owner is incomplete")
        if "parent" in plugin and _reference_id(plugin["parent"]) != (
            owner_id if ctx.version == "2022.1" else slot_id
        ):
            raise CaseBoundaryError("C09 effect parent differs from its versioned slot topology")
        entries.append({"slot": slot_id, "slot_state": slot, "effect": plugin})
    # Multi-ID read order is incidental; only the owner projection owns order.
    entries.sort(key=lambda entry: entry["slot"])
    return {"owner": owner, "entries": entries, "slot_order": slot_order}


def prepare_c09(ctx: ExpansionCaseContext) -> PreparedExpansionCase:
    root = container_root(ctx)
    if ctx.trusted_read is None:
        raise CaseBoundaryError("C09 needs a fixed trusted effect oracle before any setup")
    owner_name = case_name(ctx, "EffectsOwner")
    create = BusinessDraft(ctx, "object.create")
    parent = create.bind(segments=root)
    create.step("draft-declare-new", "--declaration-id", "sound", "--parent-handle", parent,
                "--name", owner_name, "--kind", "sound-sfx", "--field", "volume_db", "-3")
    create.finish()
    owner = query_path(ctx, (*root, owner_name))
    for index in range(2):
        plugin = BusinessDraft(ctx, "object.createPlugin")
        target = plugin.bind(object_id=owner["id"])
        plugin_type = plugin.discover_type("Wwise Gain", role="effect")
        plugin.step("draft-declare-existing", "--declaration-id", "gain", "--object-handle", target,
                    "--field", "plugin_role", "effect", "--field", "plugin_name", f"Protected_Gain_{index}",
                    "--field", "plugin_type_handle", plugin_type,
                    "--field", "notes", f"protected effect {index}")
        plugin.finish()

    def snapshot() -> Mapping[str, Any]:
        return _effect_snapshot(ctx, owner["id"])

    before = ctx.observe_before(snapshot)
    entries = before["entries"]
    if (len(entries) != 2 or {row["effect"]["name"] for row in entries}
            != {"Protected_Gain_0", "Protected_Gain_1"}
            or len({row["effect"]["classId"] for row in entries}) != 1):
        raise CaseBoundaryError("C09 setup did not seal two distinct Wwise Gain effects")
    class_id = entries[0]["effect"]["classId"]
    name = case_name(ctx, "NewGain")
    scope = {owner["id"], *(row["effect"]["id"] for row in entries)}
    scope.update(row["slot"] for row in entries if row["slot_state"] is not None)
    return PreparedExpansionCase(
        prompt=(f"请在声音 {owner['path']}（{owner['id']}）的现有效果器后追加一个名为 {name} 的 Wwise Gain 效果器，"
                f"备注写“{_REQUESTED_NOTES}”。现有两个效果器的顺序、GUID、slot 绑定、类型、名称和备注都要保持，"
                "声音本身的音量、备注和父级也不变。不要替换现有效果器，不另设插件参数或平台值。"
                "这是要实际完成的修改，请先核对现状、告知变更，并按允许修改策略取得独立授权后执行和核验；"
                "只报告新增效果器及身份、绑定和配置顺序保持结果，不评价听感或播放效果。"),
        operation="object.createPlugin", policy="allow_changes", before=before,
        read_object_ids=frozenset(scope), relationship_sources=frozenset({owner["id"]}),
        read_includes=frozenset({"parent", "owner", "notes", "volume-db", "plugin-name"}),
        read_fields=frozenset({"Effect", "Effect 0", "Effect 1", "Effect 2", "Effect 3"}),
        required_assertions=C09_ASSERTIONS,
        approve_preview=lambda artifact: approve_c09_preview(
            artifact, version=ctx.version, owner_id=owner["id"], class_id=class_id,
            name=name, notes=_REQUESTED_NOTES),
        snapshot=snapshot, verify=lambda old, new: verify_c09(old, new,
            version=ctx.version, expected_class_id=class_id, expected_name=name, expected_notes=_REQUESTED_NOTES),
        archive_oracle_parameters={"version": ctx.version, "expected_class_id": class_id, "expected_name": name,
                                   "expected_notes": _REQUESTED_NOTES},
        archive_preview_parameters={"version": ctx.version, "owner_id": owner["id"],
                                    "class_id": class_id, "name": name, "notes": _REQUESTED_NOTES},
    )

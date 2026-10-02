"""Closed language roles for already attested semantic-notice operations.

These terms never resolve live classes, authorize changes, or prove effects.
Callers retain operation-specific identity, value and timing validation.
"""

import re
from typing import Any, Mapping, NamedTuple


def role_terms(live_type: str) -> tuple[str, ...]:
    """Human-language equivalents of one independently attested live role."""
    return {"Sound": ("sound", "声音"), "Attenuation": ("attenuation", "衰减对象", "衰减"),
            "MusicStinger": ("musicstinger", "stinger")}.get(live_type, ())


_CHANGE = r"(?:修改|变更|改动)"
_REFERENT = r"(?:该|此|本次|(?:这|此)(?:一)?项)(?:已授权)?|这个已授权的"
_NEGATION = r"不|未|非|\bnot\b|\bnever\b|\bwithout\b|n't"
_FUTURE = r"(?:接下来|下面|现在|即将|随后|然后|立即)(?:我)?(?:将|会)?|我(?:现在|即将|随后|将|会)"


class PlannedNoun(NamedTuple):
    role: str
    owner_prefix: str


class PrimaryTarget(NamedTuple):
    state: str
    identity: Mapping[str, Any] | None


def attested_primary_target(clause: str, identity: Mapping[str, Any]) -> PrimaryTarget:
    """A complete positive exact target assertion, never a prose identity lookup."""
    introduction = r"(?:已确认|已核实)目标是"
    if re.search(introduction, clause) is None:
        return PrimaryTarget("unrelated", None)
    values = "|".join(re.escape(identity[key].casefold()) for key in ("id", "name", "path"))
    summary = r"(?:[，,]\s*并(?:已)?(?:取得|获得)(?:本次|此项|这项)(?:独立)?(?:策略)?授权)?"
    if re.fullmatch(rf"\s*{introduction}\s*(?:{values})\s*{summary}\s*", clause):
        return PrimaryTarget("attested", identity)
    return PrimaryTarget("invalid", None)


def planned_change_noun(action: str, prefix: str, suffix: str) -> PlannedNoun | None:
    """Recognize a noun frame, preserving every preceding owner-bearing span."""
    if action in {"新增", "添加", "追加", "创建"}:
        verification = re.search(
            rf"(?:(?:{_FUTURE})执行(?:(?:{_REFERENT}){_CHANGE})?[，,]\s*)?(?:并)?(?:按返回的(?:核验|验证)结果)?(?:检查|核验)$", prefix)
        if verification and re.fullmatch(r"(?:效果器|项)(?:(?:及|和)原有[^。；;]*(?:身份|绑定|顺序|链路))?", suffix):
            return PlannedNoun("verification", prefix[:verification.start()])
        return None
    if re.fullmatch(_CHANGE, action) is None:
        return None
    frames = (
        ("execution", rf"(?:{_FUTURE})?(?:按(?:该)?授权)?(?:执行|应用)(?:{_REFERENT})(?:单字段|单一引用|单一)?$", r"(?=[，,]|并|$)"),
        ("authorization", rf"(?:已)?(?:获得|取得|针对|为)(?:{_REFERENT})$", r"的(?:独立)?授权(?=[，,]|$)"),
        ("authorization", rf"为(?:{_REFERENT})$", r"提供(?:独立|持久)?(?:策略)?授权(?=[，,]|$)"),
        ("authorization", rf"(?:已)?为(?:{_REFERENT})$", r"取得(?:独立)?授权(?=[，,]|$)"),
        ("authorization", rf"(?:预览(?:已)?|已)?将(?:{_REFERENT})$", r"(?:独立)?授权为\s*(?:allow_changes|策略)(?:\s*策略)?操作\s*$"),
    )
    for role, left, right in frames:
        match = re.search(left, prefix)
        if match and re.match(right, suffix):
            owner_prefix = prefix[:match.start()]
            if role == "authorization":
                provider = re.search(r"(?:已)?按(?:保存的|已保存的|当前)\s*(?:allow_changes|\*\*allow_changes\*\*)\s*策略\s*$", owner_prefix)
                if provider:
                    owner_prefix = owner_prefix[:provider.start()]
                elif re.search(r"按[^，,。；;]*策略\s*$", owner_prefix):
                    return PlannedNoun("invalid-provider", owner_prefix)
            return PlannedNoun(role, owner_prefix)
    return None


def prospective_intent(text: str, *, require_affirmative: bool = True, owners: tuple[str, ...] = ()) -> bool:
    """Owned execution polarity; this cannot promote a noun or prove an edit."""
    affirmative = False
    for clause in re.split(r"[，,。；;\n]|\bbut\b|但", text):
        for execution in re.finditer(r"执行|应用", clause):
            prefix, suffix = clause[:execution.start()], clause[execution.end():].strip()
            if re.match(rf"(?:(?:{_REFERENT})(?:预览|{_CHANGE})?)?(?=$|并|随后|[，,。；;])", suffix) is None:
                continue
            if re.fullmatch(r"\s*(?:尚未|还未|未)\s*", prefix):
                continue  # Pre-Execute status is not a prospective refusal.
            excluded_owner = re.fullmatch(r"\s*(?:不|不会)(?:在|向)\s*(.+?)\s*(?:上|下)?\s*", prefix)
            if excluded_owner and owners:
                owner = excluded_owner.group(1).strip()
                # Only a complete, single named foreign identifier proves
                # preservation. Qualified GUIDs, aliases and compound owners
                # remain owned or ambiguous and cannot exempt a refusal.
                if owner not in owners and re.fullmatch(r"[a-z_][a-z0-9_.-]*", owner):
                    continue
            if re.search(_NEGATION, prefix):
                return False
            if re.fullmatch(rf"\s*(?:{_FUTURE})(?:按授权|按预览)?\s*", prefix):
                affirmative = True
    return affirmative or not require_affirmative

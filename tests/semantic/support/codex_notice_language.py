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
_REFERENT = r"(?:该|此|本次|此次|这次|(?:这|此)(?:一)?(?:项|份))(?:已授权)?|这个已授权的"
_NEGATION = r"不|未|非|\bnot\b|\bnever\b|\bwithout\b|n't"
_FUTURE = r"(?:接下来|下面|现在|即将|随后|然后|立即)(?:我)?(?:将|会)?|我(?:现在|即将|随后|将|会)"
_PROVIDER = r"(?:已)?(?:按|依据)(?:保存的|已保存的|当前)?\s*(?:allow_changes|\*\*allow_changes\*\*)\s*策略\s*"
_GRANT = r"(?:已)?(?:取得|获得)"
_AUTHORIZATION = r"(?:的)?(?:独立)?(?:持久)?(?:策略)?授权(?:记录)?"


class PlannedNoun(NamedTuple):
    role: str
    owner_prefix: str


class PrimaryTarget(NamedTuple):
    state: str
    identity: Mapping[str, Any] | None


class AuthorizationClaim(NamedTuple):
    state: str
    start: int
    end: int
    owner_prefix: str


def notice_count(value: str) -> int | None:
    """Bounded Chinese/ASCII cardinal claims used by sealed notice adapters."""
    if value == "两":
        return 2
    if value.isascii() and value.isdigit():
        return int(value) if len(value) <= 2 else None
    digits = {character: index for index, character in enumerate("零一二三四五六七八九")}
    if value in digits:
        return digits[value]
    parts = value.split("十")
    if len(parts) == 2 and (not parts[0] or parts[0] in digits) and (not parts[1] or parts[1] in digits):
        return (digits[parts[0]] if parts[0] else 1) * 10 + (digits[parts[1]] if parts[1] else 0)
    return None


def authorization_claim(clause: str) -> AuthorizationClaim:
    """Classify active/passive ancillary claims, retaining their original span.

    A claim never grants authority or proves an expected effect. Its owner
    prefix must still agree with the caller's independently attested role.
    Unconsumed coordinated text remains available for action accounting.
    """
    change = rf"(?:{_REFERENT})(?:具体)?(?:独立)?{_CHANGE}"
    active = rf"(?:{_PROVIDER})?{_GRANT}{change}{_AUTHORIZATION}"
    policy_attribute = r"(?:当前)?\s*(?:allow_changes|\*\*allow_changes\*\*)\s*策略"
    passive = rf"{change}(?:{_PROVIDER})?{_GRANT}\s*(?:{policy_attribute})?{_AUTHORIZATION}"
    bare_grant = rf"(?:{_PROVIDER})?{_GRANT}(?:{_REFERENT}){_AUTHORIZATION}"
    beneficiary = rf"(?:已)?为{change}(?:{_GRANT}|提供){_AUTHORIZATION}"
    record = r"(?:预览(?:之后|后)|本次)(?:已)?记录(?:了)?(?:独立)?(?:的)?\s*(?P<record_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略授权(?:记录)?"
    inspection = r"(?:已)?确认(?:保存的)?授权记录包含独立于(?:修改|变更|改动)预览的\s*(?P<inspection_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略授权"
    preview = r"(?:(?:本次|当前|该|此)?(?:修改|变更|改动)?预览)?"
    attributed_grant = rf"{preview}{_GRANT}\s*(?:当前)?\s*(?P<grant_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略{_AUTHORIZATION}"
    provider_record = rf"(?:当前)?\s*(?P<provider_record_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*(?:策略)?(?:已)?(?:为(?:{_REFERENT})(?:具体)?{_CHANGE}(?:记录|保存|授予|提供)(?:了)?(?:独立)?(?:执行|策略)?授权|授予(?:{_REFERENT}){_CHANGE}(?:的)?(?:独立)?(?:执行)?授权)"
    coordinator = r"(?:并(?:且)?|且|同时|另外)"
    beginning = rf"\s*(?:{coordinator})?\s*(?P<owner>(?:在|向|对)[^，,。；;\n]+?(?:上|下)\s*[，,]?\s*)?"
    match = re.match(rf"{beginning}(?:{active}|{passive}|{beneficiary}|{bare_grant}|{record}|{inspection}|{provider_record}|{attributed_grant})(?=[，,。；;]|\s*$)", clause)
    if match:
        if match.group('grant_policy') is not None and match.group('grant_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('record_policy') is not None and match.group('record_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('inspection_policy') is not None and match.group('inspection_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('provider_record_policy') is not None and match.group('provider_record_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        consumed_end = match.end()
        for qualifier in re.finditer(r"[，,]([^，,。；;\n]+)", clause[match.end():]):
            policy = re.fullmatch(r"\s*(?:并(?:且)?)?(?:当前|本次)?策略(?:为|是)\s*(.+?)\s*", qualifier.group(1))
            if policy is None:
                continue
            if re.fullmatch(r"(?:allow_changes|\*\*allow_changes\*\*)", policy.group(1)) is None:
                return AuthorizationClaim("invalid", match.start(), len(clause), match.group("owner") or "")
            # Consume only adjacent known policy qualifiers. Never sweep an
            # intervening owner or action into the exempt authorization span.
            if match.end() + qualifier.start() == consumed_end:
                consumed_end = match.end() + qualifier.end()
        return AuthorizationClaim("ancillary", match.start(), consumed_end, match.group("owner") or "")
    # Restrict failure classification to an authorization claim about this
    # change. Existing operation descriptions continue through their parser.
    body = re.sub(rf"^\s*(?:{coordinator})?\s*", "", clause)
    relevant = re.search(change, body) is not None and "授权" in body
    recognized = re.match(rf"(?:(?:尚未|未|不|不能|可能|猜测|估计|不确定)\s*)?(?:{change}|(?:已)?(?:按|依据|取得|获得|为))|在|向|对|(?:当前)?\s*[a-z_]+\s*策略", body)
    if relevant and recognized:
        return AuthorizationClaim("invalid", 0, len(clause), "")
    return AuthorizationClaim("unrelated", 0, 0, "")


def _authorization_clause(clause: str) -> bool:
    """A coordinated notice summary using the same closed grant components."""
    claim = authorization_claim(clause)
    if claim.state == "ancillary" and not claim.owner_prefix and not clause[claim.end:].strip():
        return True
    return re.fullmatch(rf"\s*(?:并)?(?:{_PROVIDER})?{_GRANT}(?:{_REFERENT}){_AUTHORIZATION}\s*", clause) is not None


def attested_primary_target(clause: str, identity: Mapping[str, Any]) -> PrimaryTarget:
    """A complete positive exact target assertion, never a prose identity lookup."""
    introduction = r"(?:已确认|已核实)目标是"
    if re.search(introduction, clause) is None:
        return PrimaryTarget("unrelated", None)
    values = "|".join(re.escape(identity[key].casefold()) for key in ("id", "name", "path"))
    roles = "|".join(re.escape(term) for term in role_terms(identity["type"]))
    atom = rf"(?:(?:{values})|(?:{roles})\s+(?:{values})|(?:{values})\s+(?:{roles}))"
    parts = re.split(r"[，,]", clause, maxsplit=1)
    if (re.fullmatch(rf"\s*{introduction}\s*{atom}\s*", parts[0])
            and (len(parts) == 1 or _authorization_clause(parts[1]))):
        return PrimaryTarget("attested", identity)
    return PrimaryTarget("invalid", None)


def planned_change_noun(action: str, prefix: str, suffix: str) -> PlannedNoun | None:
    """Recognize a noun frame, preserving every preceding owner-bearing span."""
    if action == "写入":
        referent = re.search(rf"(?:{_REFERENT})$", prefix)
        if referent and re.fullmatch(r"(?:范围)?(?:仅|只)(?:涉及|包含)(?:这(?:一)?|该|此)条曲线\s*", suffix):
            return PlannedNoun("curve-range", prefix[:referent.start()])
        return None
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
        ("authorization", rf"(?:并)?(?:{_GRANT}|针对|为)(?:{_REFERENT})$", rf"{_AUTHORIZATION}(?=[，,]|$)"),
        ("authorization", rf"为(?:{_REFERENT})$", r"提供(?:独立|持久)?(?:策略)?授权(?=[，,]|$)"),
        ("authorization", rf"(?:已)?为(?:{_REFERENT})$", r"取得(?:独立)?授权(?=[，,]|$)"),
        ("authorization", rf"(?:预览(?:已)?|已)?将(?:{_REFERENT})$", r"(?:独立)?授权为\s*(?:allow_changes|策略)(?:\s*策略)?操作\s*$"),
        ("curve-range", rf"(?:{_REFERENT})?$", r"范围(?:仅|只)包含(?:这一|该|此)条曲线\s*$"),
    )
    for role, left, right in frames:
        match = re.search(left, prefix)
        if match and re.match(right, suffix):
            owner_prefix = prefix[:match.start()]
            if role == "authorization":
                provider = re.search(rf"(?:并)?{_PROVIDER}$", owner_prefix)
                if provider:
                    owner_prefix = owner_prefix[:provider.start()]
                elif re.search(r"按[^，,。；;]*策略\s*$", owner_prefix):
                    return PlannedNoun("invalid-provider", owner_prefix)
            return PlannedNoun(role, owner_prefix)
    return None


def prospective_intent(text: str, *, require_affirmative: bool = True, owners: tuple[str, ...] = (), operation_actions: str | None = None) -> bool:
    """Owned execution polarity; this cannot promote a noun or prove an edit."""
    affirmative = False
    for clause in re.split(r"[，,。；;\n]|\bbut\b|但", text):
        for execution in re.finditer(r"执行|应用", clause):
            prefix, suffix = clause[:execution.start()], clause[execution.end():].strip()
            legacy_referent = rf"(?:(?:{_REFERENT})(?:预览|{_CHANGE})?)?"
            operation = rf"|(?:{_REFERENT})?(?:{operation_actions})" if operation_actions else ""
            if re.match(rf"(?:{legacy_referent}{operation})(?=$|并|随后|[，,。；;])", suffix) is None:
                continue
            if re.fullmatch(r"\s*(?:项目)?(?:目前|当前|此刻|现在)?(?:尚未|还未|未)\s*", prefix):
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

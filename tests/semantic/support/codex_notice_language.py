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
_REFERENT = r"(?:该|此|本次|此次|这次|当前|(?:这|此)(?:一)?(?:项|份|个))(?:已授权)?|这个已授权的"
_NEGATION = r"不|未|非|\bnot\b|\bnever\b|\bwithout\b|n't"
_FUTURE = r"(?:接下来|下面|现在|即将|随后|然后|立即)(?:我)?(?:将|会)?|我(?:现在|即将|随后|将|会)"
_PROVIDER = r"(?:已)?(?:按|依据)(?:保存的|已保存的|当前)?\s*(?:allow_changes|\*\*allow_changes\*\*)\s*策略\s*"
_GRANT = r"(?:已)?(?:取得|获得)"
_AUTHORIZATION = r"(?:下的|的)?(?:独立)?(?:持久)?(?:策略)?授权(?:记录)?"


def operation_noun_pattern(operation_actions: str) -> str:
    """Adapter-approved heads, usable only inside a complete noun carrier."""
    return rf"(?:{_REFERENT})?[ \t]*(?:{operation_actions})[ \t]*(?:方案|计划|操作)?"


def change_noun_pattern(*, reference_change: bool = False, require_referent: bool = True,
                        operation_actions: str | None = None) -> str:
    """One bounded current-change noun shared by its surrounding predicates.

    A reference qualifier is legal only in a caller-attested reference context.
    Omitted current referents require an adapter head and a complete carrier,
    or the explicit Preview noun. A noun alone never exempts action text.
    operation_actions comes only from the adapter's sealed operation family.
    Neither the noun nor a qualifier proves an effect or permission.
    """
    referent = rf"(?:{_REFERENT})" + ("" if require_referent else "?")
    qualifier = r"(?:引用)?" if reference_change else ""
    head = r"(?:修改|变更|改动|更新)" if reference_change else _CHANGE
    if operation_actions:
        head = rf"(?:{head}|{operation_actions})"
    executable = r"(?:可执行)?" if not require_referent else ""
    abstract = rf"{referent}{executable}(?:具体)?(?:独立)?(?:单字段|单一)?{qualifier}{head}"
    return rf"(?:{abstract}|{operation_noun_pattern(operation_actions)})" if operation_actions else abstract


def preview_noun_pattern(*, reference_change: bool = False, operation_actions: str | None = None) -> str:
    change = change_noun_pattern(reference_change=reference_change, require_referent=False,
                                 operation_actions=operation_actions)
    return rf"(?:(?:{change})(?:的)?|(?:可执行|具体|本次|当前|这次|该|此))?预览"


class PlannedNoun(NamedTuple):
    role: str
    owner_prefix: str


class ProspectivePrefix(NamedTuple):
    """Complete local components, never identity or authorization evidence."""
    state: str
    scope: str
    modal: str
    recipient: str | None
    scope_span: tuple[int, int]
    modal_span: tuple[int, int]
    recipient_span: tuple[int, int]


_CURRENT_SCOPE = r"本次|此次|这次|当前"
_INCOMPATIBLE_SCOPE = r"下次|下一次|第二次|第2次|已经|已|可能|也许|或许|不确定(?:是否)?|不会|不"
_PROSPECTIVE_MODAL = r"即将|将|会"
_ACTION_SCOPE_HEAD = rf"{_CURRENT_SCOPE}|{_INCOMPATIBLE_SCOPE}"
_RECIPIENT_MARKER = r"向|在|把|对"


def prospective_action_prefix(prefix: str) -> ProspectivePrefix | None:
    """Compose reviewed scope/modal/recipient components without skipping text.

    None leaves the caller's existing closed owner grammar in charge. Only a
    complete omitted-recipient form can request action-local owner inheritance.
    Supplied operands remain opaque: scope-looking object names are identities,
    not grammatical qualifiers. Incompatible scope before the recipient stays
    visible rather than disappearing when the last preposition is extracted.
    """
    match = re.fullmatch(
        rf"\s*(?P<scope>{_CURRENT_SCOPE})?\s*"
        rf"(?P<qualifier>{_INCOMPATIBLE_SCOPE})?\s*"
        rf"(?P<modal>{_PROSPECTIVE_MODAL})?\s*"
        rf"(?:(?P<marker>{_RECIPIENT_MARKER})\s*(?P<recipient>.+?))?\s*", prefix)
    if match is None:
        # Recognition selects the same modal-or-recipient alternatives as
        # validation. An optional modal cannot be required to retain scope.
        started = re.match(
            rf"\s*(?P<scope>{_ACTION_SCOPE_HEAD}).*?"
            rf"(?:(?P<modal>{_PROSPECTIVE_MODAL})|(?:{_RECIPIENT_MARKER}))", prefix)
        if started is not None:
            # This finite action head has already selected the scope/modal class.
            # Unconsumed text cannot fall through to the legacy last-marker
            # projection, which would discard it before validating an owner.
            return ProspectivePrefix("invalid", started.group("scope"), started.group("modal") or "",
                                     None, started.span("scope"), started.span("modal"), (-1, -1))
        return None
    if not (match.group("modal") or match.group("marker")):
        return None
    return ProspectivePrefix(
        "invalid" if match.group("qualifier") else "prospective",
        match.group("scope") or "", match.group("modal") or "",
        match.group("recipient"), match.span("scope"), match.span("modal"), match.span("recipient"))


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


def authorization_claim(clause: str, *, reference_change: bool = False,
                        operation_actions: str | None = None) -> AuthorizationClaim:
    """Classify active/passive ancillary claims, retaining their original span.

    A claim never grants authority or proves an expected effect. Its owner
    prefix must still agree with the caller's independently attested role.
    Unconsumed coordinated text remains available for action accounting.
    """
    change = change_noun_pattern(reference_change=reference_change, operation_actions=operation_actions)
    active = rf"(?:{_PROVIDER})?{_GRANT}{change}{_AUTHORIZATION}"
    policy_attribute = r"(?:当前)?\s*(?:allow_changes|\*\*allow_changes\*\*)\s*策略"
    passive = rf"{change}(?:{_PROVIDER})?{_GRANT}\s*(?:{policy_attribute})?{_AUTHORIZATION}"
    bare_grant = rf"(?:{_PROVIDER})?{_GRANT}(?:{_REFERENT}){_AUTHORIZATION}"
    beneficiary = rf"(?:已)?为{change}(?:{_GRANT}|提供){_AUTHORIZATION}"
    record = r"(?:预览(?:之后|后)|本次)(?:已)?记录(?:了)?(?:独立)?(?:的)?\s*(?P<record_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略授权(?:记录)?"
    inspection = r"(?:已)?确认(?:保存的)?授权记录包含独立于(?:修改|变更|改动)预览的\s*(?P<inspection_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略授权"
    preview = rf"(?:{preview_noun_pattern(reference_change=reference_change, operation_actions=operation_actions)})?"
    attributed_grant = rf"{preview}{_GRANT}\s*(?:当前)?\s*(?P<grant_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略{_AUTHORIZATION}"
    provider_record = rf"(?:当前)?\s*(?P<provider_record_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*(?:策略)?(?:已)?(?:为{change}(?:记录|保存|授予|提供|签发)(?:了)?(?:独立)?(?:执行|策略)?授权|授予{change}(?:的)?(?:独立)?(?:执行)?授权)"
    provider_passive = rf"{change}(?:已)?由\s*(?P<provider_passive_policy>(?:\*\*)?[a-z_]+(?:\*\*)?)\s*策略(?:记录|保存|授予|提供|签发)(?:了)?(?:独立)?(?:执行|策略)?授权"
    gateway_record = rf"网关(?:已)?(?:按|依据)\s*(?P<gateway_policy>[a-z_]+)\s*策略{_AUTHORIZATION}"
    coordinator = r"(?:并(?:且)?|且|同时|另外)"
    beginning = rf"\s*(?:{coordinator})?\s*(?P<owner>(?:在|向|对)[^，,。；;\n]+?(?:上|下)\s*[，,]?\s*)?"
    match = re.match(rf"{beginning}(?:{active}|{passive}|{beneficiary}|{bare_grant}|{record}|{inspection}|{provider_record}|{provider_passive}|{attributed_grant}|{gateway_record})[ \t]*(?=[，,。；;]|\s*$)", clause)
    if match:
        if match.group('grant_policy') is not None and match.group('grant_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('record_policy') is not None and match.group('record_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('inspection_policy') is not None and match.group('inspection_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('provider_record_policy') is not None and match.group('provider_record_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('provider_passive_policy') is not None and match.group('provider_passive_policy') not in {'allow_changes', '**allow_changes**'}:
            return AuthorizationClaim("invalid", match.start(), match.end(), match.group("owner") or "")
        if match.group('gateway_policy') is not None and match.group('gateway_policy') != 'allow_changes':
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
    denied_grant = re.fullmatch(r"(?:尚未|未|不|不能|可能|猜测|估计|不确定)\s*(.+)", body)
    if denied_grant and re.fullmatch(attributed_grant, denied_grant.group(1)):
        return AuthorizationClaim("invalid", 0, len(clause), "")
    grant_component = re.split(r"[，,]", body, maxsplit=1)[0]
    relevant = re.search(change, grant_component) is not None and "授权" in grant_component
    recognized = re.match(rf"(?:(?:尚未|未|不|不能|可能|猜测|估计|不确定)\s*)?(?:{change}|(?:已)?(?:按|依据|取得|获得|为))|在|向|对|(?:当前)?\s*[a-z_]+\s*策略", body)
    if relevant and recognized:
        return AuthorizationClaim("invalid", 0, len(clause), "")
    if (operation_actions and re.match(rf"(?:{_REFERENT})[^，,。；;\n]+?(?:取得|获得|提供)", body)
            and "授权" in body):
        return AuthorizationClaim("invalid", 0, len(clause), "")
    if re.match(r"网关(?:已|未|尚未|没有|可能|不确定)?(?:按|依据)", body) and "策略" in body and "授权" in body:
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


def planned_change_noun(action: str, prefix: str, suffix: str, *, reference_change: bool = False,
                        operation_actions: str | None = None) -> PlannedNoun | None:
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
        if not operation_actions or re.fullmatch(operation_actions, action) is None:
            return None
    if re.fullmatch(_CHANGE, action) is None and (not operation_actions or re.fullmatch(operation_actions, action) is None):
        return None
    nominal_tail = re.match(r"[ \t]*(?:方案|计划|操作)?", suffix).group()
    execution = re.search(rf"(?:{_FUTURE})?(?:按(?:该)?授权)?(?:执行|应用){change_noun_pattern(reference_change=reference_change, operation_actions=operation_actions)}$", prefix + action + nominal_tail)
    if execution and re.match(r"(?=[，,]|并|$)", suffix[len(nominal_tail):]):
        return PlannedNoun("execution", prefix[:execution.start()])
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


def negated_foreign_owner(prefix: str, owners: tuple[str, ...]) -> bool:
    """Only one complete named foreign recipient establishes preservation.

    Qualified GUIDs, aliases, omitted and compound recipients remain owned or
    ambiguous; missing affirmative-owner proof cannot exempt a contradiction.
    """
    excluded = re.fullmatch(r"\s*(?:不|不会)(?:在|向)\s*(.+?)\s*(?:上|下)?\s*", prefix)
    if excluded is None or not owners:
        return False
    owner = excluded.group(1).strip()
    return owner not in owners and re.fullmatch(r"[a-z_][a-z0-9_.-]*", owner) is not None


def prospective_intent(text: str, *, require_affirmative: bool = True, owners: tuple[str, ...] = (), operation_actions: str | None = None,
                       reference_change: bool = False) -> bool:
    """Owned execution polarity; this cannot promote a noun or prove an edit."""
    affirmative = False
    for clause in re.split(r"[，,。；;\n]|\bbut\b|但", text):
        for execution in re.finditer(r"执行|应用", clause):
            prefix, suffix = clause[:execution.start()], clause[execution.end():].strip()
            legacy_referent = rf"(?:(?:{_REFERENT})(?:预览|{_CHANGE})?)?"
            current_change = change_noun_pattern(reference_change=reference_change, operation_actions=operation_actions)
            if (not reference_change and re.match(
                    rf"{change_noun_pattern(reference_change=True)}(?=$|并|随后|[，,。；;])", suffix)
                    and "引用" in suffix):
                return False  # An incompatible operation noun cannot hide a refusal.
            operation = rf"|(?:{_REFERENT})?(?:{operation_actions})" if operation_actions else ""
            if re.match(rf"(?:{current_change}|{legacy_referent}{operation})(?=$|并|随后|[，,。；;])", suffix) is None:
                continue
            if re.fullmatch(rf"\s*(?:{current_change})?(?:项目)?(?:目前|当前|此刻|现在)?(?:尚未|还未|未)\s*", prefix):
                continue  # Pre-Execute status is not a prospective refusal.
            if negated_foreign_owner(prefix, owners):
                continue
            if re.search(_NEGATION, prefix):
                return False
            if re.fullmatch(rf"\s*(?:{_FUTURE})(?:按授权|按预览)?\s*", prefix):
                affirmative = True
    return affirmative or not require_affirmative

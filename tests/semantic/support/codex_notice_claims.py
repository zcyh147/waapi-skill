"""Span-preserving semantic roles for the closed expansion notice domain.

Nothing here resolves objects, grants authorization, or verifies a live result.
Contexts are supplied only after the operation adapter independently attests
its immutable request and sealed project baseline.
"""

import math
import re
from typing import Any, Mapping, NamedTuple

from tests.semantic.support.codex_notice_language import _FUTURE, _REFERENT, change_noun_pattern, notice_count, operation_noun_pattern, preview_noun_pattern, prospective_intent, role_terms

FINITE_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


class NoticeRoleContext(NamedTuple):
    identity: Mapping[str, Any]
    quantity_terms: tuple[str, ...] = ()
    before_curve: Mapping[str, Any] | None = None
    protected_effect_count: int | None = None
    reference_change: bool = False
    parent: Mapping[str, Any] | None = None
    operation_actions: str | None = None


class NoticeClaim(NamedTuple):
    role: str
    start: int
    end: int
    text: str
    diagnostic: str = ""
    value: str = ""


class PlannedEffectReferent(NamedTuple):
    name: str
    owner_id: str
    native_class_id: int
    display_label: str | None


class StagedNoticeEvidence(NamedTuple):
    """A complete Agent plan, privately tied to the one attested Preview."""
    artifact_digest: str
    event_index: int
    referent: PlannedEffectReferent


def staged_operation_adoption(clause: NoticeClaim, action_pattern: str, referent: PlannedEffectReferent) -> NoticeClaim:
    """Specific prospective adoption never grants policy or proves the plan."""
    refusal = r"(?:我)?(?:不会|不|暂不|不能|不再)"
    match = re.fullmatch(rf"\s*(?P<intent>{_FUTURE}|{refusal})执行{operation_noun_pattern(action_pattern)}(?:\s+(?P<value>.+?))?\s*", clause.text)
    if match is None:
        return clause
    value = " ".join((match.group("value") or "").split())
    if value and value not in {referent.name, referent.display_label}:
        return clause._replace(role="invalid", diagnostic="conflicting-staged-descriptor")
    if re.fullmatch(refusal, match.group("intent")):
        return clause._replace(role="invalid", diagnostic="staged-adoption-refusal")
    return clause._replace(role="execution-summary")


def notice_clauses(text: str) -> tuple[NoticeClaim, ...]:
    """Separate clauses without splitting the comma inside a coordinate."""
    result = []
    start, depth = 0, 0
    for position, character in enumerate(text):
        if character in "(（":
            depth += 1
        elif character in ")）":
            depth = max(0, depth - 1)
        elif depth == 0 and character in "，,。；;\n":
            if text[start:position].strip():
                result.append(NoticeClaim("unclassified", start, position, text[start:position]))
            start = position + 1
    if text[start:].strip():
        result.append(NoticeClaim("unclassified", start, len(text), text[start:]))
    return tuple(result)


def primary_role_atom(value: str, context: NoticeRoleContext) -> bool:
    """Exact identities or a definite generic descriptor of the sealed role."""
    value = value.strip()
    row = context.identity
    if context.reference_change and row["type"] == "MusicStinger" and context.parent is not None:
        membership = re.fullmatch(r"(.+?)\s*中(?:的)?\s*(.+)", value)
        if membership:
            parent = context.parent
            members = parent.get("@Stingers")
            if (all(isinstance(parent.get(key), str) for key in ("id", "name", "type", "path"))
                    and parent["type"] == "MusicPlaylistContainer"
                    and re.fullmatch(r"\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}", parent["id"].casefold())
                    and isinstance(members, list)
                    and sum(isinstance(member, Mapping) and member.get("id") == row["id"] for member in members) == 1
                    and membership.group(1).strip()
                    and membership.group(1).strip() in {parent[key].casefold() for key in ("id", "name", "path") if parent[key]}):
                return primary_role_atom(membership.group(2), context._replace(parent=None))
            return False
    if value and value in {str(row[key]).casefold() for key in ("id", "name", "path")}:
        return True
    if re.fullmatch(r"(?:所)?指定\s*guid", value):
        return True  # A definite referent to the adapter's singleton sealed ID.
    if not context.reference_change and value in {"目标", "目标对象", "该对象", "此对象", "指定对象", "所指定对象"}:
        return True  # No source/destination ambiguity in this singleton role.
    terms = "|".join(re.escape(term) for term in role_terms(row["type"]))
    return re.fullmatch(rf"(?:目标|该|此|(?:所)?指定)(?:的)?\s*(?:{terms})(?:对象)?", value) is not None


def before_state_noun_pattern() -> str:
    """Temporal and configuration modifiers of one nonwriting snapshot noun."""
    return r"(?:当前|(?:执行|修改|变更|改动)前)?(?:的)?(?:配置)?(?:状态|(?:核验)?基线)(?:快照)?"


def _without_verification_purpose(text: str) -> str:
    """Remove only a complete trailing read-purpose component.

    The remaining complete clause must still validate as a baseline record.
    Its temporal modifier conveys purpose, never phase or verification proof.
    """
    return re.sub(r"(?:用于|供|以便)(?:执行后|后续|随后)?(?:比较|核验|验证|验收|检查)\s*$", "", text)


def _baseline_producer(text: str, context: NoticeRoleContext) -> bool:
    return re.fullmatch(
        rf"\s*(?:{preview_noun_pattern(reference_change=context.reference_change, operation_actions=context.operation_actions)}|预检)已(?:记录|保存|建立){before_state_noun_pattern()}\s*",
        _without_verification_purpose(text)) is not None


def baseline_read_role(text: str, context: NoticeRoleContext | None = None) -> str:
    """A complete coordinated read-state summary, with no owner/edit payload."""
    original_text = text
    text = _without_verification_purpose(text)
    record = r"(?:记录|保存|建立)"
    if re.fullmatch(rf"\s*并(?:为当前配置)?{record}(?:了)?{before_state_noun_pattern()}\s*", text):
        return "read-summary"
    if re.fullmatch(rf"\s*{before_state_noun_pattern()}已{record}\s*", text):
        return "read-summary"
    if context is not None and _baseline_producer(original_text, context):
        return "read-summary"  # Preview-local bookkeeping cannot prove an edit.
    if context is not None and context.reference_change:
        terms = "|".join(re.escape(term) for term in role_terms(context.identity["type"]))
        cardinal = r"(?:[0-9]{1,9}|[零一二两三四五六七八九十]{1,3})"
        if re.fullmatch(rf"\s*(?:并)?已?{record}\s*(?:全部\s*)?{cardinal}\s*(?:个\s*)?(?:{terms})\s*的\s*引用\s*(?:和|及|与)\s*设置\s*基线\s*", text):
            # The cardinal is descriptive syntax only. This noun does not
            # certify project-wide read counts, scope, effects or verification.
            return "read-summary"
    effects = re.fullmatch(r"\s*并(?:记录|保存|建立)(?:了)?原有([0-9零一二两三四五六七八九十]+)(?:个)?效果器的(?:状态|基线)(?:快照)?\s*", text)
    if effects:
        if (context is not None and context.identity["type"] == "Sound" and context.protected_effect_count is not None
                and notice_count(effects.group(1)) == context.protected_effect_count):
            return "read-summary"
        return "invalid"
    if re.match(r"\s*并(?:记录|保存|建立)", text) and re.search(r"原有.*效果器.*(?:状态|基线)", text):
        return "invalid"  # Unknown count/owner qualifiers retain their meaning.
    return "unclassified"


def primary_role_attribute(value: str, context: NoticeRoleContext) -> bool:
    attribute = re.fullmatch(r"(.+?)(?:的)?(?:身份|配置)", value.strip())
    return attribute is not None and primary_role_atom(attribute.group(1), context)


def _coordinated_attestations(clause: NoticeClaim, context: NoticeRoleContext) -> tuple[NoticeClaim, ...] | None:
    """One affirmative read predicate governs only independently closed roles.

    Keep each enumerated operand's original span. A display token remains
    lexical Effect context, never an owner or a label-to-native-class lookup.
    Unknown, negated and compound-owner operands invalidate the entire frame.
    Other noun lists, including later verification objects, are untouched.
    """
    frame = re.fullmatch(r"\s*(?:已)?(?:核对|核实|确认)(?P<values>.+?)\s*", clause.text)
    if context.identity["type"] != "Sound" or frame is None or "、" not in frame.group("values"):
        return None
    values = frame.group("values").split("、")
    if not any(re.fullmatch(r".+(?:身份|配置|类型)\s*", value) for value in values):
        return None  # Full coordinated predicates retain their existing parser.
    claims = []
    start = frame.start("values")
    for value in values:
        operand = NoticeClaim("unclassified", clause.start + start, clause.start + start + len(value), value)
        if primary_role_atom(value, context) or primary_role_attribute(value, context):
            claims.append(operand._replace(role="owner-attestation"))
        else:
            display = re.fullmatch(r"\s*实时\s*([a-z][a-z0-9_-]*(?:[ \t]+[a-z][a-z0-9_-]*){0,5})\s*类型\s*", value)
            if display and effect_kind_label(display.group(1)):
                claims.append(operand._replace(role="matched-display", value=" ".join(display.group(1).split())))
            else:
                claims.append(operand._replace(role="invalid", diagnostic="unclosed-coordinated-attestation"))
        start += len(value) + 1
    if len({claim.value for claim in claims if claim.role == "matched-display"}) > 1:
        return (clause._replace(role="invalid", diagnostic="conflicting-coordinated-display"),)
    return tuple(claims)


def owner_attestation(clause: NoticeClaim, context: NoticeRoleContext) -> NoticeClaim:
    """A complete affirmative generic/exact role assertion, with no lookup."""
    nonaffirmative = r"(?:尚未|还未|未|没有|不|不能|可能|也许|或许|不确定(?:是否)?)"
    denied = re.fullmatch(rf"\s*{nonaffirmative}(?:已)?(?:核对|核实|确认)\s*(.+?)\s*", clause.text)
    reverse_denied = re.fullmatch(rf"\s*(.+?)\s*{nonaffirmative}(?:已)?(?:核对|核实|确认)\s*", clause.text)
    if any(match is not None and (primary_role_atom(match.group(1), context)
           or primary_role_attribute(match.group(1), context)) for match in (denied, reverse_denied)):
        return clause._replace(role="invalid", diagnostic="nonaffirmative-owner-attestation")
    coordinated = _coordinated_attestations(clause, context)
    if coordinated is not None:
        if any(claim.role == "invalid" for claim in coordinated):
            return clause._replace(role="invalid", diagnostic="conflicting-coordinated-attestation")
        return clause._replace(role="owner-attestation") if any(claim.role == "owner-attestation" for claim in coordinated) else clause
    terms = "|".join(re.escape(term) for term in role_terms(context.identity["type"]))
    established = re.fullmatch(rf"\s*(?:目标已核对为请求中的\s*(?:{terms})|这个(?:{terms})已按\s*guid\s*核实)\s*", clause.text)
    if established:
        return clause._replace(role="owner-attestation")
    subject = re.fullmatch(r"\s*目标是\s*(.+?)\s*", clause.text)
    if subject:
        value = subject.group(1)
        if context.quantity_terms:
            field = "|".join(re.escape(term) for term in context.quantity_terms)
            value = re.sub(rf"\s*的(?:{field})\s*曲线$", "", value)
        return clause._replace(role="owner-attestation" if primary_role_atom(value, context)
                               else "invalid", diagnostic="conflicting-owner-attestation")
    match = re.fullmatch(r"\s*(?:已)?(?:核对|核实|确认)(.+?)\s*", clause.text)
    if match is None:
        reverse = re.fullmatch(r"\s*(.+?)\s*已(?:核对|核实|确认|匹配|绑定)\s*", clause.text)
        declared_object = re.match(r"(?:该|此|(?:所)?指定)对象(?:的|身份|配置|和|及|与|\s|$)", reverse.group(1)) if reverse else None
        if reverse and (reverse.group(1).startswith("目标") or declared_object or primary_role_atom(reverse.group(1), context)
                        or primary_role_attribute(reverse.group(1), context)):
            return clause._replace(role="owner-attestation" if (primary_role_atom(reverse.group(1), context)
                                   or primary_role_attribute(reverse.group(1), context))
                                   else "invalid", diagnostic="conflicting-owner-attestation")
        return clause
    from tests.semantic.support.codex_notice_language import attested_primary_target

    value = match.group(1).strip()
    coordinated = re.search(r"并", value)
    if coordinated:
        baseline_role = baseline_read_role(value[coordinated.start():], context)
        if baseline_role == "invalid":
            return clause._replace(role="invalid", diagnostic="conflicting-protected-baseline")
        if baseline_role == "read-summary":
            value = value[:coordinated.start()].strip()
    if primary_role_atom(re.sub(r"^目标(?:是|为)\s*", "", value), context) or primary_role_attribute(value, context):
        return clause._replace(role="owner-attestation")
    legacy = attested_primary_target(clause.text[:match.start(1)] + value, context.identity)
    if legacy.state == "attested":
        return clause._replace(role="owner-attestation")
    if legacy.state == "invalid":
        return clause._replace(role="invalid", diagnostic="conflicting-owner-attestation")
    if primary_role_atom(value, context):
        return clause._replace(role="owner-attestation")
    path_claim = re.fullmatch(r"目标\s*guid\s*对应路径\s+(.+?)", value)
    if path_claim:
        if path_claim.group(1) == str(context.identity["path"]).casefold():
            return clause._replace(role="owner-attestation")
        return clause._replace(role="invalid", diagnostic="conflicting-owner-attestation")
    # Other established identity constructions remain with the exact legacy
    # adapter. A narrow role assertion cannot silently introduce a new owner.
    if re.match(r"目标(?!是)", value):
        return clause._replace(role="invalid", diagnostic="conflicting-owner-attestation")
    return clause


def ancillary_claims(text: str, context: NoticeRoleContext) -> tuple[NoticeClaim, ...]:
    """Classify every local ancillary role, retaining source and owner spans.

    These claims never establish the requested effect or authorization. The
    operation adapter still checks their owner payload against its sealed role.
    """
    from tests.semantic.support.codex_notice_language import authorization_claim

    result = []
    for clause in notice_clauses(text):
        local = re.sub(r"^(\s*)且", r"\1并", clause.text)
        colon = re.search(r"[:：]", local)
        owner = owner_attestation(clause._replace(text=local[:colon.start()] if colon else local), context)
        if owner.role in {"owner-attestation", "invalid"}:
            result.append(owner._replace(text=clause.text, end=clause.start + colon.start() if colon else clause.end))
            continue
        status = preview_status_claim(clause._replace(text=local), reference_change=context.reference_change,
                                      operation_actions=context.operation_actions)
        if status.role == "preview-status":
            result.append(status._replace(text=clause.text))
            continue
        pending = pending_execution_claim(clause._replace(text=local), context)
        if pending.role == "execution-status":
            result.append(pending._replace(text=clause.text))
            continue
        if context.quantity_terms and re.fullmatch(r"\s*提交的(?:修改|变更|改动)范围(?:仅|只)(?:包含|涉及)(?:这一|该|此)条曲线\s*", local):
            result.append(clause._replace(role="curve-range"))
            continue
        baseline = baseline_read_role(local, context)
        if baseline in {"read-summary", "invalid"}:
            result.append(clause._replace(role=baseline, diagnostic="conflicting-baseline" if baseline == "invalid" else ""))
            continue
        verification = verification_basis_claim(clause._replace(text=local))
        if verification.role == "verification-basis":
            result.append(verification._replace(text=clause.text))
            continue
        if (context.identity["type"] == "Sound" and re.fullmatch(r"\s*(?:接下来)?核对追加位置和现有配置的保护条件\s*", local)):
            result.append(clause._replace(role="read-summary"))
            continue
        auth = authorization_claim(local, reference_change=context.reference_change, operation_actions=context.operation_actions)
        if auth.state == "invalid":
            result.append(clause._replace(role="invalid", diagnostic="conflicting-authorization"))
        elif auth.state == "ancillary" and not local[auth.end:].strip():
            result.append(clause._replace(role="authorization", start=clause.start + auth.start,
                                         end=clause.start + auth.end, value=auth.owner_prefix))
        else:
            policy = re.fullmatch(r"\s*(?:当前|本次|此次|这次)(?:修改)?策略(?:为|是)\s*(.+?)\s*", local)
            if policy:
                # These ancillary mutation-notice contexts already require
                # allow_changes for a policy grant. A standalone current-mode
                # contradiction cannot evade it by omitting an edit verb.
                result.append(clause._replace(role="authorization" if policy.group(1) == "allow_changes" else "invalid",
                                              diagnostic="conflicting-current-policy"))
            else:
                result.append(clause)
    return tuple(result)


def verification_basis_claim(clause: NoticeClaim) -> NoticeClaim:
    """A before-state noun is ancillary only inside a bounded verification frame.

    Consume the basis and verifier prefix, never the objects, fields or other
    predicates that follow it. This intent neither asserts baseline values nor
    supplies the prospective edit or permission.
    """
    match = re.match(rf"\s*(?:执行后|随后)?(?:会|将)?(?:对照|依据){before_state_noun_pattern()}(?:核验|检查|验证|验收)", clause.text)
    return clause._replace(role="verification-basis", end=clause.start + match.end()) if match else clause


def baseline_read_claim(clause: NoticeClaim, context: NoticeRoleContext) -> NoticeClaim:
    """An ancillary span follows a separately validated complete owner atom."""
    coordinator = re.search(r"并", clause.text)
    if coordinator:
        role = baseline_read_role(clause.text[coordinator.start():], context)
        if role == "invalid":
            return clause._replace(role="invalid", diagnostic="conflicting-protected-baseline")
        if role == "read-summary" and owner_attestation(clause, context).role == "owner-attestation":
            return clause._replace(role="read-summary", start=clause.start + coordinator.start())
    return clause


def matched_display_claim(clause: NoticeClaim, context: NoticeRoleContext) -> NoticeClaim:
    """An opaque display token is lexical context, never native class evidence."""
    coordinated = _coordinated_attestations(clause, context)
    if coordinated is not None:
        if any(claim.role == "invalid" for claim in coordinated):
            return clause._replace(role="invalid", diagnostic="conflicting-coordinated-attestation")
        return next((claim for claim in coordinated if claim.role == "matched-display"), clause)
    match = re.fullmatch(r"\s*(?:并匹配到|已从实时插件目录确认)\s*([a-z][a-z0-9_-]*(?:[ \t]+[a-z][a-z0-9_-]*){0,5})\s*", clause.text)
    reverse = re.fullmatch(r"\s*([a-z][a-z0-9_-]*(?:[ \t]+[a-z][a-z0-9_-]*){0,5})\s*类型已从实时(?:插件)?目录确认\s*", clause.text)
    match = match or reverse
    if match and context.identity["type"] == "Sound" and effect_kind_label(match.group(1)):
        return clause._replace(role="matched-display", value=" ".join(match.group(1).split()))
    if re.match(r"\s*(?:并匹配到|已从实时插件目录确认)", clause.text) or re.search(r"类型已从实时(?:插件)?目录确认", clause.text):
        return clause._replace(role="invalid", diagnostic="unclosed-matched-display")
    return clause


def effect_kind_label(label: str) -> bool:
    """Existing Effect-kind/display syntax, without any label/class-ID mapping."""
    return (re.fullmatch(r"(?:effect|效果器|效果|插件)", label) is not None
            or re.fullmatch(r"wwise\s+[a-z][a-z0-9._-]*(?:\s*(?:效果器|effect|插件))?", label) is not None)


def coordinate_points(text: str, *, decibels: bool) -> tuple[tuple[float, float], ...] | None:
    """Finite tuple/scalar renderings, preserving order and quantity units."""
    points = []
    unit = r"(?:\s*db)?" if decibels else ""
    for candidate in re.finditer(r"[（(]([^()（）]*)[)）]", text):
        if re.match(rf"\s*{FINITE_NUMBER}", candidate.group(1)) is None:
            continue
        point = re.fullmatch(rf"\s*({FINITE_NUMBER})\s*[,，]\s*({FINITE_NUMBER}){unit}\s*", candidate.group(1))
        if point is None:
            return None
        values = (float(point.group(1)), float(point.group(2)))
        if not all(math.isfinite(value) for value in values):
            return None
        points.append((candidate.start(), values))
    for candidate in re.finditer(rf"(?<![a-z0-9_.])({FINITE_NUMBER})\s*对应\s*([^、，,。；;\n]+)", text):
        y = re.fullmatch(rf"({FINITE_NUMBER}){unit}\s*", candidate.group(2))
        if y is None:
            return None
        values = float(candidate.group(1)), float(y.group(1))
        if not all(math.isfinite(value) for value in values):
            return None
        points.append((candidate.start(), values))
    return tuple(values for _, values in sorted(points))


def current_curve_claim(clause: NoticeClaim, context: NoticeRoleContext) -> NoticeClaim:
    """Only an exact sealed-before observation can be ancillary current data."""
    terms = "|".join(re.escape(term) for term in context.quantity_terms)
    header = re.match(rf"\s*(?:当前|原|修改前|执行前)\s*(.*?)(?:{terms})(?:曲线|curve)(?:为|是)\s*(.*)", clause.text)
    if header is None:
        return clause
    owner = re.sub(r"(?:的)?\s*$", "", header.group(1)).strip()
    if owner and not primary_role_atom(owner, context):
        return clause._replace(role="invalid", diagnostic="conflicting-current-owner")
    before = context.before_curve
    if not isinstance(before, Mapping) or not isinstance(before.get("points"), list):
        return clause._replace(role="invalid", diagnostic="missing-current-baseline")
    if any(not isinstance(point, Mapping) or not isinstance(point.get("shape"), str)
           or any(type(point.get(key)) not in {int, float} or not math.isfinite(point[key]) for key in ("x", "y"))
           for point in before["points"]):
        return clause._replace(role="invalid", diagnostic="malformed-current-baseline")
    expected = tuple((point["x"], point["y"]) for point in before["points"])
    body = header.group(2)
    points = coordinate_points(body, decibels="干声音量" in context.quantity_terms)
    source = str(before.get("use", "")).casefold()
    source_terms = {"custom": ("custom", "自定义"), "none": ("none",), "project": ("project",)}.get(source, (source,))
    source_matches = any(term and term in body for term in source_terms)
    shapes = {str(point["shape"]).casefold() for point in before["points"]}
    shape_matches = len(shapes) == 1 and (next(iter(shapes)) in body or shapes == {"linear"} and "线性" in body)
    if re.search(r"非线性|不.*线性|\bnon[- ]?linear\b|\bnot\s+linear\b", body):
        shape_matches = False
    if points != expected or not source_matches or not shape_matches:
        return clause._replace(role="invalid", diagnostic="contradictory-current-state")
    # Only a complete state descriptor and its validated coordinates are
    # ancillary. Unknown owner/action text is never swept into this span.
    residual = re.sub(rf"[（(]\s*{FINITE_NUMBER}\s*[,，]\s*{FINITE_NUMBER}(?:\s*db)?\s*[)）]", "", body)
    source_pattern = "|".join(re.escape(term) for term in source_terms)
    shape_terms = (*shapes, "线性") if shapes == {"linear"} else tuple(shapes)
    shape_pattern = "|".join(re.escape(term) for term in shape_terms)
    if re.fullmatch(rf"(?:{source_pattern})\s*(?:{shape_pattern})\s*(?:[0-9零一二两三四五六七八九十]+)?(?:点|points)[:：]?[、\s]*", residual) is None:
        return clause._replace(role="invalid", diagnostic="unaccounted-current-state-span")
    return clause._replace(role="current-state")


def masked_claims(text: str, claims: tuple[NoticeClaim, ...], roles: set[str]) -> str:
    """Mask only already validated spans; retain raw claims and all other text."""
    characters = list(text)
    for claim in claims:
        if claim.role in roles:
            characters[claim.start:claim.end] = " " * (claim.end - claim.start)
    return "".join(characters)


def owner_inheritance(text: str, context: NoticeRoleContext) -> tuple[tuple[int, int], ...] | None:
    """A complete owner assertion seeds only the next substantive clause.

    Coordinated read-baseline or authorization summaries carry no owner or
    effect authority; all other intervening text resets this local relation.
    """
    windows = []
    pending_owner = False
    # Both projections retain original offsets. Only complete, validated local
    # components can bridge the owner to one next substantive clause.
    for raw, claim in zip(notice_clauses(text), ancillary_claims(text, context)):
        if claim.role == "invalid":
            return None
        if claim.role == "owner-attestation":
            if claim.end < raw.end:
                windows.append((claim.end + 1, raw.end))
                pending_owner = False
            else:
                pending_owner = True
            continue
        if not pending_owner:
            continue
        if claim.role in {"authorization", "preview-status", "execution-status", "read-summary"}:
            if claim.value:
                owner = re.fullmatch(r"\s*(?:在|向|对)\s*(.+?)\s*(?:上|下)\s*[，,]?\s*", claim.value)
                if owner is None or not primary_role_atom(owner.group(1), context):
                    return None
            if not text[raw.start:claim.start].strip() and not text[claim.end:raw.end].strip():
                continue
        display = matched_display_claim(raw, context)
        if display.role == "invalid":
            return None
        if display.role == "matched-display":
            continue
        windows.append((raw.start, raw.end))
        pending_owner = False
    return tuple(windows)


def pending_execution_claim(clause: NoticeClaim, context: NoticeRoleContext) -> NoticeClaim:
    """A complete not-yet status cannot supply an edit or a future refusal."""
    change = change_noun_pattern(reference_change=context.reference_change, operation_actions=context.operation_actions)
    temporal = r"(?:目前|当前|此刻|现在)?"
    project = r"(?:工程|项目)?"
    pending = r"(?:尚未|还未|未)"
    status = rf"(?:{change})?{temporal}{project}{pending}(?:修改|执行){project}"
    return clause._replace(role="execution-status") if re.fullmatch(rf"\s*{status}\s*", clause.text) else clause


def pending_curve_claim(clause: NoticeClaim, context: NoticeRoleContext, source_terms: tuple[str, ...]) -> NoticeClaim:
    """A pending-change noun followed by its exact owned field/setter value."""
    field = "|".join(re.escape(term) for term in context.quantity_terms)
    source = "|".join(re.escape(term) for term in source_terms)
    pending = r"待(?:执行的(?:修改|变更|改动)(?:仅|只)涉及|提交的是)"
    match = re.fullmatch(rf"\s*{pending}\s*(.+?)\s*的(?:{field})曲线[:：]\s*(?:设为)?(?:{source})\s*", clause.text)
    if match is None:
        return clause
    if not primary_role_atom(match.group(1), context):
        return clause._replace(role="invalid", diagnostic="conflicting-pending-owner")
    return clause._replace(role="prospective-edit")


def prospective_role_owner(prefix: str, context: NoticeRoleContext) -> bool:
    """A future transitive clause supplies an explicit, complete sealed owner."""
    match = re.fullmatch(r"\s*(?:即将|将|现在|随后)(?:仅|只)?(?:向|把|对)\s*(.+?)\s*", prefix)
    return match is not None and primary_role_atom(match.group(1), context)


def historical_creation(prefix: str) -> bool:
    """Completed-state creation language cannot establish a prospective edit."""
    local = re.split(r"[，,。；;\n]", prefix)[-1]
    # Completion can precede the recipient or follow it. A Preview mention
    # elsewhere in the clause does not turn that completed event into intent;
    # affirmative Preview confirmation followed by 将 retains its future role.
    return re.search(r"(?:已经|已)(?:(?:向|在|对)\s*.+?(?:上|下)?\s*)?$", local) is not None


def uncertain_action_qualifier(prefix: str) -> bool:
    """Local possibility cannot declare a definite prospective operation.

    Like completion qualifiers, uncertainty may precede or follow the
    recipient. It concerns this action only, never another read sentence.
    """
    local = re.split(r"[，,。；;\n]", prefix)[-1].strip()
    return re.search(r"(?:可能|也许|或许|不确定(?:是否)?)(?:会|将)?\s*(?:(?:向|在|对)\s*.+?(?:上|下)?\s*)?$", local) is not None


def additional_action_qualifier(prefix: str, suffix: str) -> bool:
    """A second ordinal or paired repeat/count governs its local predicate.

    Discourse coordinators and a bare 再 can restate the same plan. Only an
    explicit second occurrence, or 再…一次 around this action, adds a write.
    """
    local = re.split(r"[，,。；;\n]", prefix)[-1].strip()
    future = rf"(?:{_FUTURE}|将|会)?"
    recipient = r"(?:(?:向|在|对)\s*.+?(?:上|下)?\s*)?"
    count = r"一次"
    additional = rf"(?:第二次|第2次|再{count})"
    ordinal = re.fullmatch(rf"(?:{future}{additional}{future}{recipient}|{future}{recipient}{additional})\s*", local)
    repeat = re.fullmatch(rf"(?:{future}再{future}{recipient}|{future}{recipient}再)\s*", local)
    return ordinal is not None or repeat is not None and re.match(rf"\s*{count}(?=\s|效果器|插件|wwise\b)", suffix) is not None


def preview_operation_claim(clause: NoticeClaim, action_pattern: str) -> NoticeClaim:
    """A nominal Preview introduces an operation, leaving its effect unconsumed."""
    change = r"(?:(?:本次|该|此)?(?:修改|变更|改动))"
    frame = rf"(?:(?:{change})?预览|预览(?:中)?的{change}|待执行(?:的)?{change})"
    match = re.match(rf"\s*{frame}(?:为|是|显示为)\s*(?={action_pattern})", clause.text)
    if match is None:
        return clause
    return clause._replace(role="prospective-operation", end=clause.start + match.end())


def append_placement_claim(clause: NoticeClaim, action_pattern: str, *, after_existing: bool,
                           existing_count: int | None = None, context: NoticeRoleContext | None = None) -> NoticeClaim:
    """Placement is an operation modifier, never an object-owner assertion."""
    match = re.match(rf"\s*(?:将|即将)(?:在|于)(?:(?P<owner>[^，,。；;]+?)的)?(?:现有|原有)(?:(?P<count>[0-9零一二两三四五六七八九十]+)(?:个)?)?效果器(?P<position>之前|之后|前|后)\s*(?={action_pattern})", clause.text)
    if match is None:
        ending = re.fullmatch(r"\s*作为(?:效果链(?:的)?)?(?:新)?(末项|首项|第一项)\s*", clause.text)
        if ending:
            return clause._replace(role="placement-modifier" if ending.group(1) == "末项" and after_existing else "invalid",
                                   diagnostic="conflicting-append-placement" if ending.group(1) != "末项" or not after_existing else "")
        return clause
    if (match.group("position") not in {"之后", "后"} or not after_existing
            or (match.group("owner") is not None and (context is None or context.identity["type"] != "Sound"
                or not primary_role_atom(match.group("owner"), context)))
            or (match.group("count") is not None and notice_count(match.group("count")) != existing_count)):
        return clause._replace(role="invalid", diagnostic="conflicting-append-placement")
    return clause._replace(role="placement-intro", end=clause.start + match.end())


def exclusion_claim(clause: NoticeClaim) -> NoticeClaim:
    """A complete negative change-scope statement is preservation, not an edit.

    The finite role nouns describe protected music/configuration scope. Extra
    names, verbs or mixed affirmative tails remain outside this closed frame.
    """
    nouns = r"(?:音乐段|segment|容器|container|其他设置)"
    match = re.fullmatch(rf"\s*(?:未|没有|不)包含{nouns}(?:(?:、|或|和|及){nouns})*(?:的)?(?:修改|变更|改动)\s*", clause.text)
    return clause._replace(role="exclusion") if match else clause


def effect_descriptor_value_claim(clause: NoticeClaim, *, name: str, notes: str) -> NoticeClaim:
    """A local copular field/value belongs to the closed Effect descriptor.

    Plain name, kind and notes assertions are validated separately from read,
    status, authorization and exclusion roles. Unknown fields are not silently
    added to the prepared create-only descriptor.
    """
    if re.match(r"\s*(?:不会|不|未|没有)(?:修改|改动|设置|改变|更新)", clause.text):
        return clause  # Its complete predicate still goes through polarity checks.
    if re.match(rf"\s*(?:{_FUTURE})?以", clause.text) and re.search(r"核验|验证|验收|检查", clause.text):
        return clause  # A verification basis is not a copular descriptor field.
    match = re.fullmatch(r"\s*(?:(?:并|且|同时|另外)\s*)?([a-z_][a-z0-9_-]*|[\u4e00-\u9fff]{1,16})\s*(?:为|是(?!否)|=)\s*(.+?)\s*", clause.text)
    if match is None:
        return clause
    field, value = match.groups()
    quotes = {'“': '”', '"': '"'}
    if value[0] in quotes:
        if len(value) < 2 or value[-1] != quotes[value[0]]:
            return clause._replace(role="invalid", diagnostic="unclosed-descriptor-value")
        value = value[1:-1]
    kind_value = re.sub(r"^(?:唯一匹配的|已匹配的)\s*", "", value)
    valid = ((field in {"名称", "名字", "名", "name"} and value == name)
             or (field in {"类型", "type"} and effect_kind_label(kind_value))
             or (field in {"备注", "notes"} and value == notes))
    return clause._replace(role="descriptor-value" if valid else "invalid", diagnostic="" if valid else "unapproved-descriptor-field-or-value")


def preview_status_claim(clause: NoticeClaim, *, reference_change: bool = False,
                         operation_actions: str | None = None) -> NoticeClaim:
    """Preview-generation status is ancillary and retains any explicit owner."""
    preview = preview_noun_pattern(reference_change=reference_change, operation_actions=operation_actions)
    generated = r"(?:已)?生成"
    owner = r"(?P<owner>(?:在|向|对)\s*[^，,。；;\n]+?(?:上|下)\s*)?"
    match = re.fullmatch(rf"\s*(?:并)?{owner}(?:{preview}{generated}|{generated}{preview})\s*", clause.text)
    return clause._replace(role="preview-status", value=match.group("owner") or "") if match else clause


def execution_operation_claim(clause: NoticeClaim, action_pattern: str) -> NoticeClaim:
    """A complete operation-matched summary; it never establishes the effect."""
    read = r"(?:并(?:读取|回读)(?:实际)?结果(?:核验|验收))?"
    match = re.fullmatch(rf"\s*(?:{_FUTURE})执行{operation_noun_pattern(action_pattern)}{read}\s*", clause.text)
    if match and prospective_intent(clause.text, operation_actions=action_pattern):
        return clause._replace(role="execution-summary")
    return clause


def deictic_effect_claim(clause: NoticeClaim, action_pattern: str, referent: PlannedEffectReferent | None) -> NoticeClaim:
    """A future summary may refer only to one earlier validated planned effect."""
    refusal = r"(?:我)?(?:不会|不|暂不|不能|不再)"
    match = re.fullmatch(rf"\s*(?P<intent>{_FUTURE}|{refusal})(?:再)?\s*(?:{action_pattern})\s*上述\s*(?P<value>.+?)\s*", clause.text)
    if match is None:
        return clause
    if referent is None:
        return clause._replace(role="invalid", diagnostic="missing-planned-effect-antecedent")
    value = " ".join(match.group("value").split())
    if value not in {referent.name, referent.display_label, "效果器", "effect"}:
        return clause._replace(role="invalid", diagnostic="conflicting-planned-effect-referent")
    if re.fullmatch(refusal, match.group("intent")):
        return clause._replace(role="invalid", diagnostic="planned-effect-execution-refusal")
    return clause._replace(role="execution-summary")

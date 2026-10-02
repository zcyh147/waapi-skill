"""Span-preserving semantic roles for the closed expansion notice domain.

Nothing here resolves objects, grants authorization, or verifies a live result.
Contexts are supplied only after the operation adapter independently attests
its immutable request and sealed project baseline.
"""

import math
import re
from typing import Any, Mapping, NamedTuple

from tests.semantic.support.codex_notice_language import role_terms

FINITE_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


class NoticeRoleContext(NamedTuple):
    identity: Mapping[str, Any]
    quantity_terms: tuple[str, ...] = ()
    before_curve: Mapping[str, Any] | None = None


class NoticeClaim(NamedTuple):
    role: str
    start: int
    end: int
    text: str
    diagnostic: str = ""


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
    if value in {str(row[key]).casefold() for key in ("id", "name", "path")}:
        return True
    terms = "|".join(re.escape(term) for term in role_terms(row["type"]))
    return re.fullmatch(rf"(?:目标|该|此|指定)\s*(?:{terms})(?:对象)?", value) is not None


def owner_attestation(clause: NoticeClaim, context: NoticeRoleContext) -> NoticeClaim:
    """A complete affirmative generic/exact role assertion, with no lookup."""
    match = re.fullmatch(r"\s*(?:已)?(?:核对|核实|确认)(.+?)\s*", clause.text)
    if match is None:
        return clause
    from tests.semantic.support.codex_notice_language import attested_primary_target

    legacy = attested_primary_target(clause.text, context.identity)
    if legacy.state == "attested":
        return clause._replace(role="owner-attestation")
    if legacy.state == "invalid":
        return clause._replace(role="invalid", diagnostic="conflicting-owner-attestation")
    value = match.group(1).strip()
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
    from tests.semantic.support.codex_notice_language import authorization_claim

    windows = []
    for sentence in re.finditer(r"[^。；;\n]+", text):
        clauses = notice_clauses(sentence.group())
        if not clauses:
            continue
        first = clauses[0]
        colon = re.search(r"[:：]", first.text)
        assertion = owner_attestation(first._replace(text=first.text[:colon.start()]) if colon else first, context)
        if assertion.role == "invalid":
            return None
        if assertion.role != "owner-attestation":
            continue
        if colon:
            start = sentence.start() + first.start + colon.end()
            windows.append((start, sentence.start() + first.end))
            continue
        compatible = True
        for tail in clauses[1:]:
            authorization = authorization_claim(tail.text)
            baseline = re.fullmatch(r"\s*并为当前配置建立执行前核验基线\s*", tail.text)
            if not baseline and not (authorization.state == "ancillary" and not authorization.owner_prefix
                                     and not tail.text[authorization.end:].strip()):
                compatible = False
        if compatible:
            following = re.match(r"[。；;\n]\s*([^，,。；;\n]+)", text[sentence.end():])
            if following:
                windows.append((sentence.end() + following.start(1), sentence.end() + following.end(1)))
    return tuple(windows)


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

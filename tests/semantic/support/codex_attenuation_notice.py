"""Closed attenuation notice proof; this is not a runtime state verifier."""

import math
import re
from typing import Any, Mapping, NamedTuple

from tests.semantic.support.codex_notice_language import attested_primary_target, planned_change_noun, prospective_intent, role_terms

from wwise_waapi.core_business_contracts import (
    _CURVE_KINDS, _CURVE_SHAPES, _CURVE_SOURCES, attenuation_curve_value_domains,
)

ATTENUATION_API = "ak.wwise.core.object.setAttenuationCurve"
_GUID = r"\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}"
_NUMBER = r"[+-]?\d+(?:\.\d+)?"
_ACTION = (r"设置为|设为|设成|改为|改成|更新|改动|变更|修改(?!范围|请求|策略|前|后|结果|状态)|替换|"
           r"提交|应用|写入|删除|移除|清空|重置|新增|添加|插入|创建|追加|"
           r"\b(?:set|change|update|replace|delete|remove|clear|reset|add|create)\b")
_NEGATION = r"不|未|非|没|\bnot\b|\bnever\b|\bwithout\b|n't"


def _owner_terms(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (row["id"], row["name"], row["path"], "该对象", "此对象", "目标对象", "this attenuation",
            *(prefix + term for prefix in ("该", "此", "指定", "目标", "这个") for term in role_terms(row["type"])))


class _CurveFrame(NamedTuple):
    start: int
    end: int


def _following_first_clause(text: str, assertion_end: int) -> tuple[int, int] | None:
    """One adjacent substantive clause; whitespace never changes the owner."""
    following = re.match(r"[。；;\n]\s*([^，,。；;\n]+)", text[assertion_end:])
    if following is None:
        return None
    return assertion_end + following.start(1), assertion_end + following.end(1)


def _curve_frames(text: str, context: Mapping[str, Any], owner: str, kind: str, source: str) -> list[_CurveFrame]:
    """Closed owner/quantity/source assertions; raw spans remain in the audit.

    Exact ordered coordinates, quantities and interpolation are validated
    before these grammatical frames are considered. No frame consumes an
    additional action or an unknown owner prefix.
    """
    owned_field = rf"(?:{owner})\s*的\s*(?:{kind})\s*(?:曲线|curve)(?:来源)?"
    owned_quantity = rf"(?:{owner})\s*的\s*(?:{kind})(?:曲线|curve)?"
    qualified = rf"attenuation\s+{re.escape(context['identity']['id'].casefold())}\s*的\s*(?:{kind})"
    intro = r"(?:(?:本次|这份)预览(?:只|将)?|预览(?:只会)?(?:确认)?(?:将)?|本次获授权的改动会|将)(?:只|仅)?(?:把|对|向|在)?"
    value = rf"(?:来源|source)?\s*(?:为)?\s*(?:{source})(?:来源)?"
    patterns = (
        rf"{intro}\s*修改{owned_field}[:：]{value}",
        rf"{intro}\s*{owned_field}(?:设为|设成|改为|改成|更新为){value}[:：]?",
        rf"预览确认将在\s*(?:{owner})\s*上应用\s*(?:{source})(?:{kind})曲线",
        rf"准备执行的只有(?:{kind})这一条[:：]把(?:{owner})的曲线来源设为{value}",
        rf"预览(?:的预期结果是|中唯一的曲线编辑是)[:：]?\s*{owned_quantity}(?:使用{value}|[:：]{value})",
        rf"预览限定的是\s*(?:{qualified})",
    )
    frames = []
    for clause in re.finditer(r"[^，,。；;\n]+", text):
        body = clause.group().strip()
        matched = any(re.fullmatch(pattern, body) for pattern in patterns)
        if re.fullmatch(rf"这份预览将(?:{kind})曲线更新为\s*(?:{source})[:：]从距离\s*{_NUMBER}\s*到\s*{_NUMBER}", body):
            domain = re.search(rf"从距离\s*({_NUMBER})\s*到\s*({_NUMBER})", body)
            matched = (domain is not None and (float(domain.group(1)), float(domain.group(2))) ==
                       (context["points"][0]["x"], context["points"][-1]["x"])
                       and re.search(rf"只作用于(?:{owner})(?=[，,。；;]|$)", text) is not None)
        if matched:
            # The source must occur in the same prospective sentence; a
            # different paragraph's authorization cannot supply its value.
            sentence = re.split(r"[。；;\n]", text[clause.end():], maxsplit=1)[0]
            if re.search(rf"(?:{source})(?![a-z0-9_])", body + sentence):
                frames.append(_CurveFrame(clause.start(), clause.end()))
    return frames


def prospective_preview_execution(text: str) -> bool:
    """A local execution clause must affirm the owned Preview, never refuse it."""
    return prospective_intent(text)


def normalize_attested_preview_target(text: str, identity: Mapping[str, Any]) -> tuple[str, bool] | None:
    """Normalize one adjacent Preview referent after a complete identity claim.

    The caller supplies an independently attested operation role. Recognized
    identity frames are checked even when they cannot seed inheritance; their
    original sentences remain present for subsequent contradiction checks.
    """
    sentences = re.split(r"([。\n])", text)
    attested = False
    for position in range(0, len(sentences), 2):
        sentence = sentences[position].strip()
        declaration = re.fullmatch(
            r"(?:核对确认|已核对(?:确认)?)该对象是指定路径下的\s*(.+?)\s*[，,、]且\s*guid\s*与你提供的一致", sentence)
        named = re.fullmatch(
            r"(?:当前绑定|该对象)已按所给\s*guid\s*(?:确认|核实)为名为\s*(.+?)\s*[、，,]类型为\s*(.+?)\s*的对象", sentence)
        recognized = re.match(r"(?:核对确认|已核对(?:确认)?)该对象是|(?:当前绑定|该对象)已按所给", sentence)
        if recognized:
            if declaration:
                valid = declaration.group(1).strip() == identity["type"].casefold()
            elif named:
                valid = (named.group(1).strip() == identity["name"].casefold()
                         and named.group(2).strip() == identity["type"].casefold())
            else:
                valid = False
            if not valid:
                return None
            if position == 0 and len(sentences) > 2 and sentences[2].strip().startswith("预览"):
                attested = True
    return "".join(sentences), attested


def _normalize_curve_expected_frame(text: str, context: Mapping[str, Any], attested: bool) -> str:
    """Consume only a complete owned prospective curve frame, not a verb."""
    if not attested:
        return text
    sentences = re.split(r"([。\n])", text)
    if len(sentences) < 3:
        return text
    frame = re.fullmatch(
        r"\s*预览(?:已)?(?:确认|显示)(?:本次)?(?:只|仅)(?:调用|提交)(?:其|该对象的)([^：:]+)曲线[:：]([^，,]+)[，,]([^。；;]+)([；;].*)?", sentences[2])
    if frame is None:
        return text
    kind = "干声音量" if context["kind"] == "volume-dry" else context["kind"]
    source = "自定义" if context["source"] == "custom" else context["source"]
    if frame.group(1).strip() != kind or frame.group(2).strip() not in {source, source + "源", source + "来源"}:
        return text
    # Coordinates and shapes are checked against the sealed ordered plan by
    # attenuation_notice_effect. Count is derived from that complete sequence.
    description = frame.group(3).strip()
    if re.match(r"(?:线性|linear)点\s*[（(]", description) is None:
        return text
    if not prospective_preview_execution(text):
        return text
    sentences[2] = (f"预览已确认仅向{context['identity']['id'].casefold()}提交{kind}曲线："
                    f"{source}来源、{len(context['points'])}{description}" + (frame.group(4) or ""))
    return "".join(sentences)


def attenuation_notice_context(artifact: Mapping[str, Any], before: Mapping[str, Any], version: str) -> Mapping[str, Any] | None:
    """Attest sealed target-plan agreement against the independent singleton."""
    request, prepared = artifact.get("request"), artifact.get("prepared_operation")
    if not isinstance(request, Mapping) or not isinstance(prepared, Mapping):
        return None
    arguments = request.get("arguments", {})
    if not isinstance(arguments, Mapping):
        return None
    args = arguments.get("args")
    plan = prepared.get("verification_plan", {})
    if (request.get("operation") != "waapi.call" or arguments.get("api") != ATTENUATION_API
            or version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}
            or request.get("version") != version or prepared.get("version") != version
            or prepared.get("operation") != "waapi.call" or prepared.get("request") != request
            or arguments.get("options") != {} or not isinstance(args, Mapping)
            or set(args) != {"object", "curveType", "use", "points"}
            or prepared.get("dispatch") != {"uri": ATTENUATION_API, "args": args, "options": {}}
            or plan != {"kind": "result-schema", "strategy": "result_schema", "uri": ATTENUATION_API, "version": version}):
        return None
    row = before.get("attenuation")
    if (not isinstance(row, Mapping) or row.get("type") != "Attenuation"
            or not isinstance(row.get("id"), str) or re.fullmatch(_GUID, row["id"].casefold()) is None
            or row["id"] != args["object"] or any(not isinstance(row.get(key), str) or not row[key] for key in ("name", "path"))):
        return None
    source = before.get("source", {})
    if not isinstance(source, Mapping) or not isinstance(source.get("object"), Mapping) or source["object"].get("id") == row["id"]:
        return None
    domains = attenuation_curve_value_domains(version)
    kind = next((key for key in domains["curve_kind"]["choices"] if _CURVE_KINDS[key] == args["curveType"]), None)
    use = next((key for key in domains["curve_source"]["choices"] if _CURVE_SOURCES[key] == args["use"]), None)
    points = args["points"]
    if kind is None or use is None or not isinstance(points, list) or len(points) > domains["points"]["maximum_items"]:
        return None
    if (use == "custom") != bool(points):
        return None
    for point in points:
        if (not isinstance(point, Mapping) or set(point) != {"x", "y", "shape"}
                or point["shape"] not in _CURVE_SHAPES.values()
                or any(type(point[key]) not in {int, float} or not math.isfinite(point[key]) for key in ("x", "y"))):
            return None
    return {"identity": row, "kind": kind, "source": use, "points": points}


def _has(text: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9_]){re.escape(token.casefold())}(?![a-z0-9_])", text) is not None


def _point_count(value: str) -> int | None:
    if value.isascii() and value.isdigit():
        return int(value) if len(value) <= 2 else None
    digits = {character: index for index, character in enumerate("零一二三四五六七八九")}
    if value in digits:
        return digits[value]
    parts = value.split("十")
    if len(parts) == 2 and (not parts[0] or parts[0] in digits) and (not parts[1] or parts[1] in digits):
        return (digits[parts[0]] if parts[0] else 1) * 10 + (digits[parts[1]] if parts[1] else 0)
    return None


def _point_description(text: str, context: Mapping[str, Any]) -> bool:
    """A complete quantity/count/shape label for already verified coordinates."""
    shapes = {point["shape"] for point in context["points"]}
    if len(shapes) != 1:
        return False
    native = next(iter(shapes))
    shape = next(key for key, value in _CURVE_SHAPES.items() if value == native)
    shape = rf"(?:{re.escape(shape)}|线性)" if shape == "linear" else re.escape(shape)
    unit = r"(?:\s*db)?" if context["kind"] == "volume-dry" else ""
    description = re.fullmatch(rf"(?:(?P<count>[0-9零一二三四五六七八九十]+)(?:个)?)?\s*{shape}(?:点|points)[:：]?[、\s]*{unit}\s*", text)
    return description is not None and (description.group("count") is None or _point_count(description.group("count")) == len(context["points"]))


def _prospective_submission(left: str, right: str, text: str, context: Mapping[str, Any], owner: str, kind: str, source: str) -> bool:
    """A complete owned-Preview result description with prospective execution."""
    if re.fullmatch(rf"预览(?:已)?(?:显示|确认|表明|限定)[:：]?(?:仅|只)?(?:将|会)?(?:向|对)(?:{owner})", left.strip()) is None:
        return False
    description = re.fullmatch(rf"(?:{kind})(?:曲线|curve)?[:：]\s*(?:{source})(?:来源|source)?[、，,\s]*(.+)", right)
    if description is None or not _point_description(description.group(1), context):
        return False
    intent = False
    for execution in re.finditer(r"(?:现在|即将|随后)(?:按授权|按预览)?(?:执行|应用)", text):
        qualifier = re.split(r"[，,、。；;\n]", text[:execution.start()])[-1]
        if re.search(_NEGATION, qualifier) is None:
            intent = True
    if re.search(r"(?:不|不会)(?:执行|应用)(?:本次|这项|此项|该预览)?(?:修改|变更|改动)?(?=[，,。；;]|$)", text):
        return False
    return intent


def _closed_mutation_claims(text: str, context: Mapping[str, Any], kind_aliases: list[str], source_aliases: list[str]) -> bool:
    """Every affirmative transitive edit must name this owner and curve role."""
    row = context["identity"]
    owner = "|".join(re.escape(value.casefold()) for value in _owner_terms(row))
    kind = "|".join(re.escape(value) for value in kind_aliases)
    field = rf"(?:的|'s|\s)*(?:{kind})(?:\s*(?:曲线|curve))?(?:的|:|：|\s)*(?:来源|source|形状|shape|点|points)?"
    source = "|".join(re.escape(value) for value in source_aliases)
    allowed_value = rf"(?:{source})(?:\s*(?:线性|linear))?(?:\s*(?:点|points|曲线|curve))?"
    introduction = r"(?:预览|已|核实|确认|修改范围|范围|仅|为|即将|只|把|将|对|同时|另外|我|会|:|：|\s|\b(?:i|will|shall|only|then|also|and)\b)*"
    # Coordinates have already been validated as the exact ordered plan.
    # Remove only their complete numeric syntax before parsing the source edit.
    text = re.sub(rf"[（(]\s*{_NUMBER}\s*[,，]\s*{_NUMBER}(?:\s*db)?\s*[)）]", "", text)
    text = re.sub(rf"{_NUMBER}\s*对应\s*{_NUMBER}(?:\s*db)?", "", text)
    text = re.sub(r"、(?=\s*(?:、|[，,。；;]|$))", "", text)
    frames = _curve_frames(text, context, owner, kind, source)
    base_owner = owner
    anaphor_spans = []
    target_assertion_spans = []
    inherited_target_spans = []
    for assertion in re.finditer(r"[^。；;\n]+", text):
        target = attested_primary_target(assertion.group(), row)
        if target.state == "invalid":
            return False
        if target.state == "attested":
            target_assertion_spans.append((assertion.start(), assertion.end()))
            following = _following_first_clause(text, assertion.end())
            if following is not None:
                inherited_target_spans.append(following)
        if re.fullmatch(r"\s*(?:目标已核对为请求中的 attenuation|这个衰减对象已按 guid 核实)\s*", assertion.group()):
            following = _following_first_clause(text, assertion.end())
            if following is not None:
                anaphor_spans.append(following)
    affirmative = bool(frames)
    antecedent = None
    clauses = re.split(r"([。；;,，\n]|\bbut\b|但)", text)
    for position in range(0, len(clauses), 2):
        clause = clauses[position]
        clause_start = sum(len(part) for part in clauses[:position])
        substantive_start = clause_start + len(clause) - len(clause.lstrip())
        owner = base_owner + "|其" if any(start <= substantive_start < end for start, end in anaphor_spans) else base_owner
        prior = antecedent if position > 0 and clauses[position - 1] in {",", "，"} else None
        antecedent = None
        subject = re.fullmatch(rf"{introduction}目标是\s*(.+?)\s*", clause)
        if subject:
            identity_only = any(start <= clause_start < end for start, end in target_assertion_spans)
            if not identity_only and re.fullmatch(rf"(?:{owner}){field}", subject.group(1)) is None:
                return False
            if not identity_only:
                antecedent = subject.group(1)
        actions = list(re.finditer(_ACTION, clause))
        positions = {action.start() for action in actions}
        for noun_action in re.finditer(r"修改|变更|改动", clause):
            noun = planned_change_noun(noun_action.group(), clause[:noun_action.start()], clause[noun_action.end():].strip())
            if noun_action.start() not in positions and noun is not None and noun.role == "curve-range":
                actions.append(noun_action)
        for action in sorted(actions, key=lambda action: action.start()):
            noun = planned_change_noun(action.group(), clause[:action.start()], clause[action.end():].strip())
            if noun is not None and noun.role == "invalid-provider":
                return False
            if any(frame.start <= clause_start + action.start() and clause_start + action.end() <= frame.end for frame in frames):
                continue
            if re.match(r"操作(?:没有|尚未|未)执行\s*$", clause[action.end():]):
                continue
            if re.search(_NEGATION, clause[:action.start()]):
                continue
            if noun is not None:
                # A grammatical noun may not conceal a different owner.
                if noun.owner_prefix.strip() and re.fullmatch(rf"\s*(?:在|向|对)\s*(?:{owner})\s*(?:上|下)?\s*", noun.owner_prefix) is None:
                    return False
                continue
            if (action.group() in {"修改", "变更", "改动"}
                    and re.search(r"执行(?:(?:这|此)(?:一)?项|本次)(?:单字段|单一引用|单一)?$", clause[:action.start()])
                    and not clause[action.end():].strip()):
                continue
            if action.group() == "应用" and prospective_intent(clause) and re.fullmatch(r"\s*(?:该|此|本次)预览\s*", clause[action.end():]):
                continue
            if action.group() in {"删除", "移除", "清空", "重置", "新增", "添加", "插入", "创建", "追加", "delete", "remove", "clear", "reset", "add", "create"}:
                return False
            left, right = clause[:action.start()], clause[action.end():].strip()
            if (any(start <= clause_start + action.start() < end for start, end in inherited_target_spans)
                    and action.group() in {"设置为", "设为", "设成", "改为", "改成"}
                    and re.fullmatch(rf"(?:即将|现在|随后)(?:仅|只)?(?:将|把)?(?:{kind})(?:曲线|curve)", left.strip())
                    and re.fullmatch(allowed_value, right)):
                affirmative = True
                continue
            # Chinese suffix verbs carry the subject on their left; English
            # transitive verbs carry it on their right. Neither may inherit an
            # arbitrary property or a second owner from the surrounding prose.
            if prior is not None and not left.strip() and action.group() in {"设置为", "设为", "改为", "改成"}:
                value = right
                if re.fullmatch(allowed_value, value.strip(" 、")) is None:
                    return False
                affirmative = True
                continue
            if action.group() in {"提交", "应用", "写入"}:
                if action.group() in {"提交", "写入"} and affirmative and left.strip() in {"", "并", "并按顺序"} and _point_description(right.strip(" 、"), context):
                    continue
                if not _prospective_submission(left, right, text, context, owner, kind, source):
                    return False
                affirmative = True
                continue
            matches = list(re.finditer(rf"(?<![a-z0-9_])(?:{owner})(?![a-z0-9_])", left))
            if (len(matches) == 1 and re.fullmatch(introduction, left[:matches[0].start()])
                    and re.fullmatch(field, left[matches[0].end():])):
                value = right
            else:
                if re.fullmatch(introduction, left) is None:
                    return False
                match = re.match(rf"(?:{owner})({field})(?:\s+(?:to|as)|为|成)\s*(.*)$", right)
                if match is None:
                    return False
                value = match.group(2)
            if re.fullmatch(allowed_value, value.strip(" 、")) is None:
                return False
            affirmative = True
    return affirmative


def attenuation_notice_effect(text: str, context: Mapping[str, Any]) -> bool:
    """Require exact ordered coordinates, disclosed shape and affirmative edit."""
    if len(text.encode("utf-8")) > 32 * 1024:
        return False
    text = re.sub(r"`([^`\n]+)`", r"\1", text.casefold()).replace("\u2212", "-")
    if not prospective_intent(text, require_affirmative=False, owners=tuple(term.casefold() for term in _owner_terms(context["identity"]))):
        return False
    row = context["identity"]
    normalized = normalize_attested_preview_target(text, row)
    if normalized is None:
        return False
    text, attested = normalized
    text = _normalize_curve_expected_frame(text, context, attested)
    for call in re.finditer(r"调用", text):
        suffix = text[call.end():]
        prefix = re.split(r"[，,。；;\n]", text[:call.start()])[-1]
        if (re.match(r"(?:回执|结果)(?=[，,。；;\s]|$)", suffix) is None
                or re.search(r"(?:核验|验证|检查)(?:(?:只|仅)?检查)?\s*$", prefix) is None):
            return False
    if any(value != row["id"].casefold() for value in re.findall(_GUID, text)):
        return False
    if not any(term.casefold() in text for term in _owner_terms(row)) and re.search(r"目标已核对为请求中的 attenuation", text) is None:
        return False
    kind_aliases = [context["kind"], context["kind"].replace("-", " ")]
    if context["kind"] == "volume-dry":
        kind_aliases += ["干声音量", "dry volume"]
    source_aliases = [context["source"]]
    if context["source"] == "custom":
        source_aliases.append("自定义")
    if not any(_has(text, token) for token in kind_aliases) or not any(_has(text, token) for token in source_aliases):
        return False
    for count in re.finditer(r"(?P<count>[+-]?[0-9零一二三四五六七八九十]+|若干|some)(?:个)?\s*(?:线性|linear)?点", text):
        if _point_count(count.group("count")) != len(context["points"]):
            return False
    for token in (*kind_aliases, *source_aliases):
        for match in re.finditer(rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])", text):
            prefix = re.split(r"[，,、。；;\n]", text[:match.start()])[-1]
            if re.search(_NEGATION, prefix):
                preservation = re.fullmatch(r"\s*不(?:会)?(?:修改|更新|改变)\s*([\w.-]+)\s*的\s*", prefix)
                primary = {value.casefold() for value in (row["id"], row["name"], row["path"],
                    "该对象", "此对象", "目标对象", "指定衰减对象", "该衰减对象", "该衰减")}
                if preservation is None or preservation.group(1) in primary:
                    return False
    for key in _CURVE_KINDS:
        if key != context["kind"] and _has(text, key):
            return False
    for key in _CURVE_SOURCES:
        if key not in {context["source"], context["kind"]} and _has(text, key):
            return False
    # Only the sealed dry-volume ordinate is a disclosed decibel quantity.
    # Units on x, other quantities, or unknown unit suffixes cannot disappear.
    y_unit = r"(?:\s*db)?" if context["kind"] == "volume-dry" else ""
    stated = []
    for candidate in re.finditer(r"[（(]([^()（）]*[,，][^()（）]*)[)）]", text):
        body = candidate.group(1)
        if re.match(rf"\s*{_NUMBER}", body) is None:
            continue
        point = re.fullmatch(rf"\s*({_NUMBER})\s*[,，]\s*({_NUMBER}){y_unit}\s*", body)
        if point is None:
            return False
        stated.append((candidate.start(), (float(point.group(1)), float(point.group(2)))))
    for scalar in re.finditer(rf"(?<![a-z0-9_.])({_NUMBER})\s*对应\s*([^、，,。；;\n]+)", text):
        ordinate = re.fullmatch(rf"({_NUMBER}){y_unit}\s*", scalar.group(2))
        if ordinate is None:
            return False
        stated.append((scalar.start(), (float(scalar.group(1)), float(ordinate.group(1)))))
    if [point for _, point in sorted(stated)] != [(point["x"], point["y"]) for point in context["points"]]:
        return False
    shapes = {point["shape"] for point in context["points"]}
    if shapes:
        if len(shapes) != 1:
            return False
        expected = next(iter(shapes))
        token = next(key for key, native in _CURVE_SHAPES.items() if native == expected)
        mentions = list(re.finditer(r"线性|(?<![a-z])linear(?![a-z])", text)) if token == "linear" else list(re.finditer(re.escape(token), text))
        if not mentions:
            return False
        for match in mentions:
            prefix = re.split(r"[，,、。；;\n]", text[:match.start()])[-1]
            if re.search(_NEGATION, prefix):
                return False
        if any(native != expected and (_has(text, key) or _has(text, native)) for key, native in _CURVE_SHAPES.items()):
            return False
    return _closed_mutation_claims(text, context, kind_aliases, source_aliases)

"""Closed attenuation notice proof; this is not a runtime state verifier."""

import math
import re
from typing import Any, Mapping

from wwise_waapi.core_business_contracts import (
    _CURVE_KINDS, _CURVE_SHAPES, _CURVE_SOURCES, attenuation_curve_value_domains,
)

ATTENUATION_API = "ak.wwise.core.object.setAttenuationCurve"
_GUID = r"\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}"
_NUMBER = r"[+-]?\d+(?:\.\d+)?"
_ACTION = (r"设置为|设为|改为|改成|更新|修改(?!范围|请求|策略|前|后|结果|状态)|替换|"
           r"删除|移除|清空|重置|新增|添加|"
           r"\b(?:set|change|update|replace|delete|remove|clear|reset|add|create)\b")
_NEGATION = r"不|未|非|\bnot\b|\bnever\b|\bwithout\b|n't"


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


def _closed_mutation_claims(text: str, context: Mapping[str, Any], kind_aliases: list[str], source_aliases: list[str]) -> bool:
    """Every affirmative transitive edit must name this owner and curve role."""
    row = context["identity"]
    owner = "|".join(re.escape(value.casefold()) for value in (
        row["id"], row["name"], row["path"], "该对象", "此对象", "目标对象", "该衰减对象", "该衰减", "this attenuation"))
    kind = "|".join(re.escape(value) for value in kind_aliases)
    field = rf"(?:的|'s|\s)*(?:{kind})(?:\s*(?:曲线|curve))?(?:的|:|：|\s)*(?:来源|source|形状|shape|点|points)?"
    source = "|".join(re.escape(value) for value in source_aliases)
    allowed_value = rf"(?:{source})(?:\s*(?:曲线|curve))?"
    introduction = r"(?:预览|已|核实|确认|修改范围|范围|仅|为|即将|只|把|将|同时|另外|我|会|\s|\b(?:i|will|shall|only|then|also|and)\b)*"
    affirmative = False
    for clause in re.split(r"[。；;,，\n]|\bbut\b|但", text):
        for action in re.finditer(_ACTION, clause):
            if re.match(r"操作(?:没有|尚未|未)执行\s*$", clause[action.end():]):
                continue
            if re.search(_NEGATION, clause[:action.start()]):
                continue
            if action.group() in {"删除", "移除", "清空", "重置", "新增", "添加", "delete", "remove", "clear", "reset", "add", "create"}:
                return False
            left, right = clause[:action.start()], clause[action.end():].strip()
            # Chinese suffix verbs carry the subject on their left; English
            # transitive verbs carry it on their right. Neither may inherit an
            # arbitrary property or a second owner from the surrounding prose.
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
            if re.fullmatch(allowed_value, value) is None:
                return False
            affirmative = True
    return affirmative


def attenuation_notice_effect(text: str, context: Mapping[str, Any]) -> bool:
    """Require exact ordered coordinates, disclosed shape and affirmative edit."""
    if len(text.encode("utf-8")) > 32 * 1024:
        return False
    text = re.sub(r"`([^`\n]+)`", r"\1", text.casefold()).replace("\u2212", "-")
    row = context["identity"]
    if any(value != row["id"].casefold() for value in re.findall(_GUID, text)):
        return False
    if not any(term.casefold() in text for term in (row["id"], row["name"], row["path"], "该对象", "此对象", "目标对象", "该衰减", "该衰减对象", "this attenuation")):
        return False
    kind_aliases = [context["kind"], context["kind"].replace("-", " ")]
    if context["kind"] == "volume-dry":
        kind_aliases += ["干声音量", "dry volume"]
    source_aliases = [context["source"]]
    if context["source"] == "custom":
        source_aliases.append("自定义")
    if not any(_has(text, token) for token in kind_aliases) or not any(_has(text, token) for token in source_aliases):
        return False
    for token in (*kind_aliases, *source_aliases):
        for match in re.finditer(rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])", text):
            prefix = re.split(r"[，,、。；;\n]", text[:match.start()])[-1]
            if re.search(_NEGATION, prefix):
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
        stated.append((float(point.group(1)), float(point.group(2))))
    if stated != [(point["x"], point["y"]) for point in context["points"]]:
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

"""Exact target authority for the 2024/25 closed Conversion setter.

Native acknowledgement is result-only evidence. ConversionPlugin enumeration
does not establish a platform-to-codec identity and is not used by this setter.
"""
from __future__ import annotations

import re
import uuid

from .canonical import canonical_json_bytes
from .builders.metadata import parse_get_types_result
from .business_declarations import normalize_live_object_identity

URI = "ak.wwise.core.audio.setConversionPlugin"
PLAN_CONTRACT = "waapi-skill.conversion-plugin-invocation/v2"
OBJECT_GET = "ak.wwise.core.object.get"
MAX_PLATFORMS = 64
MAX_BYTES = 256 * 1024


class ConversionPluginError(ValueError):
    pass


def _guid(value):
    if not isinstance(value, str) or re.fullmatch(
        r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}", value
    ) is None or uuid.UUID(value).int == 0:
        raise ConversionPluginError("Conversion observations require nonzero canonical GUIDs")
    return "{" + str(uuid.UUID(value)).upper() + "}"


def _bounded(value):
    try:
        size = len(canonical_json_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ConversionPluginError("Conversion authority observation requires bounded finite JSON") from exc
    if size > MAX_BYTES:
        raise ConversionPluginError("Conversion authority observation exceeds its byte ceiling")
    return value


def _platforms(read):
    rows = read("ak.wwise.core.getProjectInfo", {}, {}).get("platforms")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PLATFORMS:
        raise ConversionPluginError("Conversion requires the complete bounded live project platform catalog")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
            raise ConversionPluginError("Project platform identity is malformed")
        result.append({"id": _guid(row.get("id")), "name": row["name"]})
    if len({row["id"] for row in result}) != len(result) or len({row["name"] for row in result}) != len(result):
        raise ConversionPluginError("Project platforms must have unique exact identities and names")
    return sorted(result, key=lambda row: row["id"])


def observe(args, *, read, version):
    if version not in {"2024.1", "2025.1"}:
        raise ConversionPluginError("This codec setter is not reflected in the selected version")
    conversion_id = _guid(args["conversion"])
    rows = read(OBJECT_GET, {"from": {"id": [conversion_id]}},
        {"return": ["id", "name", "type", "path"]}).get("return")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ConversionPluginError("Conversion target must resolve exactly once")
    row = rows[0]
    try:
        identity = normalize_live_object_identity(row, version=version)
    except ValueError as exc:
        raise ConversionPluginError("Conversion target identity is malformed") from exc
    if identity.object_id != conversion_id or identity.object_type != "Conversion":
        raise ConversionPluginError("Codec selection requires one exact Conversion Settings object")
    platforms = _platforms(read)
    selected = [platform for platform in platforms if args["platform"] in (platform["id"], platform["name"])]
    if len(selected) != 1:
        raise ConversionPluginError("Choose one exact unique live project platform")
    try:
        types = parse_get_types_result(read("ak.wwise.core.object.getTypes", {}, {}))
    except ValueError as exc:
        raise ConversionPluginError("Installed Conversion class catalog is malformed") from exc
    classes = [item.as_dict() for item in types if item.type == "Conversion" and item.name == args["plugin"]]
    if len(classes) != 1:
        raise ConversionPluginError("Selected codec must name exactly one installed Conversion class")
    return _bounded({"conversion": {key: row[key] for key in ("id", "name", "type", "path")},
        "platforms": platforms, "selected_platform": selected[0], "selected_class": classes[0]})


def prepare(args, *, read, version):
    return {"contract": PLAN_CONTRACT, "before": observe(args, read=read, version=version)}


def notice(plan):
    return {"conversion": plan["before"]["conversion"],
        "platform": plan["before"]["selected_platform"],
        "installed_class": plan["before"]["selected_class"],
        "effect": "request codec replacement on the selected platform; prior codec properties may reset",
        "verification": "result_schema_checked",
        "business_state_verified": False,
        "unverified": ["actual codec replacement", "platform-to-codec GUID association",
            "other platform codec and field preservation"],
        "configuration": "no codec GUID is produced; a separately chosen exact live codec identity and live object.setProperty Field Handles require a separate Preview"}

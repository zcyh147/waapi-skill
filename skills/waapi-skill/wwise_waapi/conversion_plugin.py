"""Platform codec selection and observation for the 2024/25 closed setter.

The matching SDK's "Getting all Conversion Plug-ins" example owns the
ConversionPlugin source and pluginName/classId/owner projections. The normal
object.get platform option selects the observed platform. These expressions
are Gateway-owned; callers provide neither a query nor a native payload.
"""
from __future__ import annotations

from copy import deepcopy
import re
import uuid

from .canonical import canonical_json_bytes
from .builders.metadata import parse_get_types_result
from .business_declarations import normalize_live_object_identity

URI = "ak.wwise.core.audio.setConversionPlugin"
OBJECT_GET = "ak.wwise.core.object.get"
MAX_PLATFORMS = 64
MAX_FIELDS = 128
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
        raise ConversionPluginError("Codec observation requires bounded finite JSON") from exc
    if size > MAX_BYTES:
        raise ConversionPluginError("Complete platform codec observation exceeds its byte ceiling")
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


def _codec(conversion_id, platform, *, read):
    # Native take is a sentinel: a second matching codec is an ambiguity,
    # never an invitation to choose one by result order.
    query = f'$ from type ConversionPlugin where owner.id = "{conversion_id}" take 2'
    fields = ["id", "owner", "classId", "pluginName"]
    rows = read(OBJECT_GET, {"waql": query}, {"return": fields, "platform": platform["id"]}).get("return")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ConversionPluginError("Each Conversion/platform must expose exactly one attached codec")
    row = rows[0]
    codec_id = _guid(row.get("id"))
    owner = row.get("owner")
    if _guid(owner.get("id") if isinstance(owner, dict) else owner) != conversion_id:
        raise ConversionPluginError("Attached codec owner differs from the selected Conversion")
    if type(row.get("classId")) is not int or not 0 <= row["classId"] <= 0xFFFFFFFF or not isinstance(row.get("pluginName"), str) or not row["pluginName"].strip():
        raise ConversionPluginError("Attached codec requires an independent class ID and plug-in name")
    names = read("ak.wwise.core.object.getPropertyAndReferenceNames", {"object": codec_id}, {}).get("return")
    if (not isinstance(names, list) or len(names) > MAX_FIELDS
            or any(not isinstance(name, str) or re.fullmatch(r"[:_a-zA-Z0-9]{1,128}", name) is None for name in names)
            or len(set(names)) != len(names)):
        raise ConversionPluginError("Attached codec field catalog is missing, ambiguous or exceeds its bound")
    names = sorted(names)
    if names:
        values = read(OBJECT_GET, {"from": {"id": [codec_id]}},
            {"return": [*fields, *("@" + name for name in names)], "platform": platform["id"]}).get("return")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise ConversionPluginError("Attached codec fields require one exact identity readback")
        values = values[0]
        if (any(values.get(key) != row.get(key) for key in fields)
                or any("@" + name not in values for name in names)):
            raise ConversionPluginError("Attached codec identity changed or a required field was omitted")
    else:
        values = row
    return _bounded({"id": codec_id, "owner_id": conversion_id, "class_id": row["classId"],
        "plugin_name": row["pluginName"], "fields": {name: deepcopy(values["@" + name]) for name in names}})


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
        "platforms": platforms, "selected_platform": selected[0], "selected_class": classes[0],
        "codecs": {platform["id"]: _codec(conversion_id, platform, read=read) for platform in platforms}})


def prepare(args, *, read, version):
    before = observe(args, read=read, version=version)
    return {"before": before, "expected_class": before["selected_class"],
        "platform_id": before["selected_platform"]["id"]}


def notice(plan):
    return {"conversion": plan["before"]["conversion"],
        "platform": plan["before"]["selected_platform"], "installed_class": plan["expected_class"],
        "previous_codec": plan["before"]["codecs"][plan["platform_id"]],
        "effect": "select this platform codec; prior selected-platform codec properties may reset",
        "preserved": "all other platform codec identities, classes and returned fields",
        "configuration": "use verified codec GUID with live object.setProperty Field Handles in a separate Preview"}


def compare(plan, after):
    before = plan["before"]
    platform_id = plan["platform_id"]
    selected = after["codecs"].get(platform_id, {})
    return [{"name": "Conversion identity and exact project platform catalog remain unchanged",
             "passed": all(before[key] == after[key] for key in ("conversion", "platforms", "selected_platform", "selected_class"))},
        {"name": "Requested platform independently exposes the selected installed codec class and owner",
         "passed": selected.get("class_id") == plan["expected_class"]["classId"]
            and selected.get("plugin_name") == plan["expected_class"]["name"]
            and selected.get("owner_id") == before["conversion"]["id"],
         "evidence": {"expected": plan["expected_class"], "actual": selected}},
        {"name": "Every other platform codec identity, class and returned field is preserved",
         "passed": all(after["codecs"].get(key) == value for key, value in before["codecs"].items() if key != platform_id)}]

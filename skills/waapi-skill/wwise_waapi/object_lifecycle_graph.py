"""Bounded native graph snapshots for copy/move preparation and verification."""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from .builders.metadata import bind_get_property_info_result
from .metadata_discovery import metadata_typed_value_type


GET = "ak.wwise.core.object.get"
NAMES = "ak.wwise.core.object.getPropertyAndReferenceNames"
INFO = "ak.wwise.core.object.getPropertyInfo"
FIELDS = ("id", "name", "type", "path", "parent", "notes")
MAX_NODES = 128
MAX_FIELDS = 1024
MAX_PLATFORMS = 32
MAX_PLATFORM_FIELD_VALUES = 32768
_PLATFORM_VERSIONS = {"2022.1", "2023.1", "2024.1", "2025.1"}
_LINK_VERSIONS = {"2023.1", "2024.1", "2025.1"}
_GUID = re.compile(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}\Z")
_TOKEN = re.compile(r"[:_a-zA-Z0-9]+\Z")
Read = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


class LifecycleGraphError(ValueError):
    pass


def _rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("return")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise LifecycleGraphError("Lifecycle graph read requires a complete object array")
    return [dict(row) for row in rows]


def capture_lifecycle_graph(root_id: str, *, read: Read, version: str | None = None) -> list[dict[str, Any]]:
    """Capture bounded hierarchy and every certified project-platform field view."""
    platforms = None
    discovery = None
    raw_platforms = None
    if version == "2021.1":
        types = read("ak.wwise.core.object.getTypes", {}, {}).get("return")
        matches = [row for row in types if isinstance(row, Mapping) and row.get("name") == "Platform"] if isinstance(types, list) else []
        if (len(matches) != 1 or isinstance(matches[0].get("classId"), bool)
                or not isinstance(matches[0].get("classId"), int) or matches[0]["classId"] <= 0):
            raise LifecycleGraphError("Lifecycle platform discovery requires one exact live Platform class")
        discovery = {"source": "live_getTypes_and_fixed_ofType", "class": dict(matches[0])}
        raw_platforms = _rows(read(GET, {"from": {"ofType": ["Platform"]},
                                        "transform": [{"range": [0, MAX_PLATFORMS + 1]}]}, {"return": ["id", "name"]}))
    elif version in _PLATFORM_VERSIONS:
        result = read("ak.wwise.core.getProjectInfo", {}, {})
        raw_platforms = result.get("platforms")
        discovery = {"source": "live_getProjectInfo.platforms"}
    if discovery is not None:
        if not isinstance(raw_platforms, list) or len(raw_platforms) > MAX_PLATFORMS:
            raise LifecycleGraphError("Lifecycle platform inventory must be a complete array of at most 32 platforms")
        platforms = []
        ids, names = set(), set()
        for platform in raw_platforms:
            if (not isinstance(platform, Mapping) or not isinstance(platform.get("id"), str)
                    or not _GUID.fullmatch(platform["id"]) or not isinstance(platform.get("name"), str)
                    or not platform["name"] or platform["id"].upper() in ids or platform["name"].casefold() in names):
                raise LifecycleGraphError("Lifecycle platform inventory requires distinct exact GUID/name rows")
            ids.add(platform["id"].upper())
            names.add(platform["name"].casefold())
            platforms.append({"id": platform["id"].upper(), "name": platform["name"]})
        platforms.sort(key=lambda row: row["id"])
    platform_field_values = 0
    roots = _rows(read(GET, {"from": {"id": [root_id]}}, {"return": list(FIELDS)}))
    if len(roots) != 1 or str(roots[0].get("id", "")).upper() != root_id.upper():
        raise LifecycleGraphError("Lifecycle root must resolve exactly once to the bound GUID")
    descendants = _rows(read(GET, {"from": {"id": [root_id]}, "transform": [{"select": ["descendants"]}]},
                             {"return": list(FIELDS)}))
    rows = [*roots, *descendants]
    if len(rows) > MAX_NODES:
        raise LifecycleGraphError("Lifecycle subtree exceeds the complete 128-object snapshot bound")
    by_id: dict[str, dict[str, Any]] = {}
    by_path: dict[str, dict[str, Any]] = {}
    root_path = roots[0].get("path")
    if not isinstance(root_path, str) or not root_path.startswith("\\"):
        raise LifecycleGraphError("Lifecycle root lacks an absolute Wwise path")
    normalized = []
    for row in rows:
        object_id = row.get("id")
        path = row.get("path")
        if (not isinstance(object_id, str) or not _GUID.fullmatch(object_id)
                or not isinstance(path, str) or not path.startswith("\\")
                or not isinstance(row.get("name"), str) or not isinstance(row.get("type"), str)
                or not isinstance(row.get("notes"), str)):
            raise LifecycleGraphError("Lifecycle snapshot requires exact identity, topology and note fields")
        if object_id.upper() in by_id or path in by_path:
            raise LifecycleGraphError("Lifecycle snapshot contains duplicate GUIDs or paths")
        if object_id.upper() != root_id.upper() and not path.startswith(root_path.rstrip("\\") + "\\"):
            raise LifecycleGraphError("Lifecycle descendant lies outside the bound root")
        by_id[object_id.upper()], by_path[path] = row, row
        normalized.append({key: row.get(key) for key in FIELDS})
    for row in normalized[1:]:
        parent = row["parent"]
        parent_id = parent.get("id") if isinstance(parent, Mapping) else parent
        expected_parent = by_path.get(row["path"].rsplit("\\", 1)[0])
        if not isinstance(parent_id, str) or expected_parent is None or expected_parent["id"].upper() != parent_id.upper():
            raise LifecycleGraphError("Lifecycle descendant has a missing or inconsistent direct parent")
    for row in normalized:
        result = read(NAMES, {"object": row["id"]}, {})
        names = result.get("return")
        if (not isinstance(names, list) or len(names) > MAX_FIELDS
                or not all(isinstance(name, str) and _TOKEN.fullmatch(name) for name in names)
                or len(names) != len(set(names))):
            raise LifecycleGraphError("Lifecycle field discovery must be bounded, complete and unique")
        values: dict[str, Any] = {}
        reference_fields = []
        field_types = {}
        field_metadata = {}
        link_support = {}
        for name in sorted(names):
            try:
                info = bind_get_property_info_result(
                    read(INFO, {"object": row["id"], "property": name}, {}),
                    field_token=name, available_names=names,
                )
            except ValueError as exc:
                raise LifecycleGraphError("Lifecycle field metadata is malformed") from exc
            if info.name != name:
                raise LifecycleGraphError("Lifecycle field metadata does not match the discovered field")
            reference = (info.type or "").casefold() in {"reference", "objectreference"} or info.restriction.get("type") == "reference"
            if not reference and metadata_typed_value_type(info.type) is None:
                raise LifecycleGraphError("Lifecycle field metadata does not certify a supported scalar value type")
            field_types[name] = "reference" if reference else info.type
            link_support[name] = info.supports.get("unlink")
            field_metadata[name] = {**info.as_dict(include_raw=True), "scope": {"object": row["id"]}, "available_names": sorted(names)}
            if reference:
                reference_fields.append(name)
        for offset in range(0, len(names), 32):
            chunk = sorted(names)[offset:offset + 32]
            observed = _rows(read(GET, {"from": {"id": [row["id"]]}}, {"return": ["id", *("@" + name for name in chunk)]}))
            if len(observed) != 1 or str(observed[0].get("id", "")).upper() != row["id"].upper():
                raise LifecycleGraphError("Lifecycle field read lost its exact object identity")
            for name in chunk:
                if "@" + name not in observed[0]:
                    raise LifecycleGraphError("Lifecycle field read omitted a discovered field")
                values[name] = observed[0]["@" + name]
        row["field_values"] = values
        row["reference_fields"] = reference_fields
        row["field_types"] = field_types
        row["field_metadata"] = field_metadata
        if platforms is not None:
            platform_field_values += len(platforms) * len(names)
            if platform_field_values > MAX_PLATFORM_FIELD_VALUES:
                raise LifecycleGraphError("Lifecycle platform field observations exceed the complete bounded value budget")
            observation: dict[str, Any] = {"platforms": platforms, "discovery": discovery, "values": {}, "links": {}, "link_flags_complete": True}
            for platform in platforms:
                platform_id = platform["id"]
                platform_values, links = {}, {}
                for offset in range(0, len(names), 32):
                    chunk = sorted(names)[offset:offset + 32]
                    observed = _rows(read(GET, {"from": {"id": [row["id"]]}},
                        {"return": ["id", *("@" + name for name in chunk)], "platform": platform_id}))
                    if len(observed) != 1 or str(observed[0].get("id", "")).upper() != row["id"].upper():
                        raise LifecycleGraphError("Lifecycle platform field read lost its exact object identity")
                    for name in chunk:
                        if "@" + name not in observed[0]:
                            raise LifecycleGraphError("Lifecycle platform read omitted a discovered field")
                        platform_values[name] = observed[0]["@" + name]
                for name in sorted(names):
                    if link_support[name] is False:
                        continue
                    if link_support[name] is not True or version not in _LINK_VERSIONS:
                        observation["link_flags_complete"] = False
                        continue
                    linked = read("ak.wwise.core.object.isLinked",
                                  {"object": row["id"], "property": name, "platform": platform_id}, {}).get("linked")
                    if not isinstance(linked, bool):
                        raise LifecycleGraphError("Lifecycle platform link read requires an explicit Boolean")
                    links[name] = linked
                observation["values"][platform_id] = platform_values
                observation["links"][platform_id] = links
            row["platform_observation"] = observation
    return sorted(normalized, key=lambda row: (row["path"].count("\\"), row["path"]))


def lifecycle_graph_matches(source: list[dict[str, Any]], actual: list[dict[str, Any]], *, is_copy: bool) -> bool:
    """Compare relative topology and values, rebinding internal copied references."""
    if not source or not actual:
        return False
    source_root, actual_root = source[0]["path"], actual[0]["path"]
    expected = {row["path"][len(source_root):]: row for row in source}
    observed = {row["path"][len(actual_root):]: row for row in actual}
    if set(expected) != set(observed):
        return False
    mapping = {row["id"].upper(): observed[path]["id"].upper() for path, row in expected.items()}
    source_ids = set(mapping)
    actual_ids = {row["id"].upper() for row in actual}
    if is_copy and source_ids & actual_ids:
        return False
    if not is_copy and any(key != value for key, value in mapping.items()):
        return False

    def value(raw: Any, *, translate: bool) -> Any:
        if isinstance(raw, Mapping):
            # Reference projections may add display metadata; the GUID is authoritative.
            if isinstance(raw.get("id"), str) and _GUID.fullmatch(raw["id"]):
                return value(raw["id"], translate=translate)
            return {key: value(item, translate=translate) for key, item in raw.items()}
        if isinstance(raw, list):
            return [value(item, translate=translate) for item in raw]
        if isinstance(raw, str) and _GUID.fullmatch(raw):
            return mapping.get(raw.upper(), raw.upper()) if translate else raw.upper()
        return raw

    for path, row in expected.items():
        other = observed[path]
        if row["type"] != other["type"] or row["notes"] != other["notes"]:
            return False
        if path and row["name"] != other["name"]:
            return False
        if row["field_types"] != other["field_types"] or row["reference_fields"] != other["reference_fields"]:
            return False
        expected_values = {name: (value(raw, translate=True) if name in row["reference_fields"] else raw)
                           for name, raw in row["field_values"].items()}
        observed_values = {name: (value(raw, translate=False) if name in other["reference_fields"] else raw)
                           for name, raw in other["field_values"].items()}
        if expected_values != observed_values:
            return False
        platform_observation = row.get("platform_observation")
        other_observation = other.get("platform_observation")
        if platform_observation is not None:
            if (not isinstance(other_observation, Mapping)
                    or platform_observation["platforms"] != other_observation.get("platforms")
                    or platform_observation["discovery"] != other_observation.get("discovery")
                    or platform_observation["links"] != other_observation.get("links")
                    or platform_observation["link_flags_complete"] != other_observation.get("link_flags_complete")):
                return False
            translated = {platform: {name: value(raw, translate=True) if name in row["reference_fields"] else raw
                          for name, raw in values.items()} for platform, values in platform_observation["values"].items()}
            observed_values = {platform: {name: value(raw, translate=False) if name in other["reference_fields"] else raw
                               for name, raw in values.items()} for platform, values in other_observation.get("values", {}).items()}
            if translated != observed_values:
                return False
        elif other_observation is not None:
            return False
    return True

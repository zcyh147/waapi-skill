"""Independent state comparison for repair workflows; no Gateway PASS inference.

Inputs must be runner-owned complete snapshots of the declared sandbox scope.
This module is a comparison seam, not a live collector or an archive validator.
It cannot by itself establish authentication, Preview authorization, metadata
pagination, successful refinement, or final response truthfulness.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

_GUID = re.compile(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}")
_SHA = re.compile(r"[0-9a-f]{64}")


def _snapshot(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"objects", "source_integrity", "media", "complete"}:
        return False
    source = value["source_integrity"]
    rows = value["objects"]
    return (value["complete"] is True and isinstance(rows, Mapping) and bool(rows)
        and all(isinstance(key, str) and _GUID.fullmatch(key) and isinstance(row, Mapping)
                and row.get("id") == key for key, row in rows.items())
        and isinstance(source, Mapping) and set(source) == {"sha256", "mtime_ns"}
        and isinstance(source["sha256"], str) and bool(_SHA.fullmatch(source["sha256"]))
        and type(source["mtime_ns"]) is int and source["mtime_ns"] >= 0
        and isinstance(value["media"], Mapping)
        and all(isinstance(path, str) and isinstance(digest, str) and _SHA.fullmatch(digest)
                for path, digest in value["media"].items()))


def assess_repair_state(case_id: str, before: Mapping[str, Any], after: Mapping[str, Any], *,
                        target_id: str, expected: Mapping[str, Any]) -> dict[str, bool]:
    if case_id not in {"F1", "F2", "F3", "F4"}:
        raise ValueError("unreviewed repair case")
    valid = _snapshot(before) and _snapshot(after)
    checks = {"complete_snapshots": bool(valid), "source_unchanged": False,
              "media_unchanged": False, "other_objects_unchanged": False,
              "target_identity": False, "target_values": False, "target_cardinality": False}
    if not valid or not isinstance(target_id, str) or not _GUID.fullmatch(target_id):
        return checks
    old, new = before["objects"], after["objects"]
    checks["source_unchanged"] = before["source_integrity"] == after["source_integrity"]
    checks["media_unchanged"] = before["media"] == after["media"]
    checks["other_objects_unchanged"] = ({key: value for key, value in old.items() if key != target_id}
        == {key: value for key, value in new.items() if key != target_id})
    creation = case_id in {"F3", "F4"}
    checks["target_cardinality"] = (target_id in new and (target_id not in old if creation else target_id in old)
                                    and len(new) == len(old) + int(creation))
    row = new.get(target_id, {})
    identity_keys = {"name", "type", "path", "parent"}
    if not identity_keys.issubset(expected) or not isinstance(expected.get("properties", {}), Mapping):
        return checks
    checks["target_identity"] = all(row.get(key) == expected[key] for key in identity_keys)
    properties = expected.get("properties", {})
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in properties.values()):
        return checks
    actual = row.get("properties", {})
    checks["target_values"] = (isinstance(actual, Mapping)
        and all(type(actual.get(key)) in {int, float} and actual[key] == value for key, value in properties.items()))
    if case_id == "F1":
        previous = old.get(target_id, {})
        preserved = dict(previous)
        preserved["properties"] = {**previous.get("properties", {}), **properties}
        checks["target_values"] &= row == preserved and bool(properties)
    if case_id == "F2":
        checks["target_values"] &= old == new
    if case_id == "F3":
        checks["target_values"] &= set(properties) == {"Min", "Max", "InitialValue"}
    if case_id == "F4":
        checks["target_identity"] &= (type(expected.get("class_id")) is int
            and row.get("class_id") == expected["class_id"] and row.get("type") == "Effect"
            and not row.get("owner"))
    return checks

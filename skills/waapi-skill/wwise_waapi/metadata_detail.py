"""Lossless bounded projection of one live metadata field.

Pages preserve JSON pointers, empty containers and string fragments. A cursor
binds the complete live value as well as the scope-bound field selection; it
never confers mutation authority.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .canonical import canonical_json_bytes


def detail_entries(value: Any, pointer: str = "") -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        rows = [{"pointer": pointer, "kind": "object", "length": len(value)}]
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            rows.extend(detail_entries(child, pointer + "/" + escaped))
        return rows
    if isinstance(value, list):
        rows = [{"pointer": pointer, "kind": "array", "length": len(value)}]
        for index, child in enumerate(value):
            rows.extend(detail_entries(child, pointer + "/" + str(index)))
        return rows
    if isinstance(value, str) and len(value) > 1024:
        return [{"pointer": pointer, "kind": "string-fragment", "offset": offset,
                 "total_characters": len(value), "value": value[offset:offset + 1024]}
                for offset in range(0, len(value), 1024)]
    return [{"pointer": pointer, "kind": "value", "value": value}]


def detail_page(metadata: Mapping[str, Any], *, selection: str,
                scope: Mapping[str, Any], cursor: str | None,
                view: str = "raw") -> dict[str, Any]:
    from .metadata_discovery import MetadataDiscoveryError, _require_result_size
    if view not in {"raw", "choices", "dependencies"}:
        raise MetadataDiscoveryError("INVALID_METADATA_DETAIL_VIEW", "Choose raw, choices or dependencies metadata detail")
    snapshot = hashlib.sha256(canonical_json_bytes([selection, metadata, view])).hexdigest()
    restriction = metadata.get("restriction")
    choices = restriction.get("values", []) if isinstance(restriction, Mapping) else []
    choices = choices if isinstance(choices, list) else []
    dependencies = metadata.get("dependencies", [])
    dependencies = dependencies if isinstance(dependencies, list) else []
    rows = detail_entries(metadata) if view == "raw" else choices if view == "choices" else dependencies
    offset = 0
    if cursor is not None:
        try:
            prefix, index, digest = cursor.split(".")
            offset = int(index)
            valid = prefix == "md1" and digest == snapshot and str(offset) == index and 0 <= offset < len(rows)
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise MetadataDiscoveryError("METADATA_DETAIL_CHANGED", "The selected metadata detail or its scope changed, or its page is invalid; read the selected field again.")
    end = min(len(rows), offset + (64 if view == "raw" else 20))
    def typed_page(kind: str, values: list[Any]) -> dict[str, Any]:
        start, stop = (offset, end) if view == kind else (0, min(20, len(values)))
        digest = hashlib.sha256(canonical_json_bytes([selection, metadata, kind])).hexdigest()
        return {"items": values[start:stop], "offset": start, "total_count": len(values),
                "complete": stop == len(values),
                "next_detail_page": f"md1.{stop}.{digest}" if stop < len(values) else None,
                "detail_view": kind}
    field = {key: metadata[key] for key in ("name", "type", "default", "supports", "unit", "availability") if key in metadata}
    if isinstance(restriction, Mapping):
        field["constraints"] = {key: restriction[key] for key in ("type", "min", "max", "minInclusive", "maxInclusive") if key in restriction}
    field["dependencies"] = dependencies[:20]
    field["dependency_page"] = typed_page("dependencies", dependencies)
    field["choices"] = typed_page("choices", choices)
    while True:
        if view == "choices":
            field["choices"] = typed_page("choices", choices)
        elif view == "dependencies":
            field["dependency_page"] = typed_page("dependencies", dependencies)
            field["dependencies"] = dependencies[offset:end]
        result = {"contract": "waapi-skill.metadata-detail-page/v1", "selection": selection,
                  "scope": dict(scope), "snapshot": snapshot, "detail_view": view, "field": field,
                  ("entries" if view == "raw" else "items"): rows[offset:end],
                  "offset": offset, "total_entries": len(rows), "remaining_entries": len(rows) - end,
                  "complete": end == len(rows), "next_detail_page": f"md1.{end}.{snapshot}" if end < len(rows) else None,
                  "mutation_authority": False}
        try:
            # Leave room for the public Gateway's exact continuation and scope.
            _require_result_size(result, maximum_bytes=16 * 1024, pretty=True)
            return result
        except MetadataDiscoveryError:
            if end <= offset + 1:
                raise
            end -= 1


def fit_detail_continuations(result: dict[str, Any], decorate: Any) -> dict[str, Any]:
    """Budget the actual platform envelopes together with their live page."""
    from .metadata_discovery import MetadataDiscoveryError, _require_result_size
    while True:
        decorate(result)
        try:
            _require_result_size(result, maximum_bytes=28 * 1024, pretty=True)
            return result
        except MetadataDiscoveryError as exc:
            if exc.error_code != "DISCOVERY_RESULT_LIMIT_EXCEEDED":
                raise
            key = "entries" if result["detail_view"] == "raw" else "items"
            if len(result[key]) <= 1:
                raise
            result[key].pop()
            end = result["offset"] + len(result[key])
            result["remaining_entries"] = result["total_entries"] - end
            result["complete"] = end == result["total_entries"]
            result["next_detail_page"] = f"md1.{end}.{result['snapshot']}" if not result["complete"] else None
            if key == "items":
                page = result["field"]["choices" if result["detail_view"] == "choices" else "dependency_page"]
                page.update(items=list(result[key]), complete=result["complete"], next_detail_page=result["next_detail_page"])
            result.pop("next_command", None)

"""Lossless bounded projection of one live metadata field.

Pages preserve JSON pointers, empty containers and string fragments. A cursor
binds the complete live value as well as the scope-bound field selection; it
never confers mutation authority.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .canonical import canonical_json_bytes


def bounded_native_header(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Useful small facts with explicit previews; raw entries retain every byte."""
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if len(canonical_json_bytes(value)) <= 1024:
            result[key] = value
        else:
            if isinstance(value, str):
                result[key] = value[:128]
                result[key + "_characters"] = len(value)
            else:
                result[key + "_kind"] = "object" if isinstance(value, Mapping) else "array" if isinstance(value, list) else "value"
            result[key + "_complete"] = False
    return result


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
                view: str = "raw", item_index: int | None = None) -> dict[str, Any]:
    from .metadata_discovery import MetadataDiscoveryError, _require_result_size
    if view not in {"raw", "choices", "dependencies"}:
        raise MetadataDiscoveryError("INVALID_METADATA_DETAIL_VIEW", "Choose raw, choices or dependencies metadata detail")
    snapshot = hashlib.sha256(canonical_json_bytes([selection, metadata, view, item_index])).hexdigest()
    restriction = metadata.get("restriction")
    choices = restriction.get("values", []) if isinstance(restriction, Mapping) else []
    choices = choices if isinstance(choices, list) else []
    dependencies = metadata.get("dependencies", [])
    dependencies = dependencies if isinstance(dependencies, list) else []
    rows = detail_entries(metadata) if view == "raw" else choices if view == "choices" else dependencies
    if item_index is not None:
        if view == "raw" or isinstance(item_index, bool) or not isinstance(item_index, int) or not 0 <= item_index < len(rows):
            raise MetadataDiscoveryError("INVALID_METADATA_DETAIL_ITEM", "Copy an item index from the selected typed metadata page")
        rows = detail_entries(rows[item_index])
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
    raw_view = view == "raw" or item_index is not None
    end = min(len(rows), offset + (64 if raw_view else 20))
    def typed_item(row: Any, index: int, kind: str) -> Any:
        if len(canonical_json_bytes(row)) <= 1024:
            return row
        return {**({key: value for key, value in row.items()
                    if key in {"value", "type", "action", "context", "property", "displayName"}
                    and len(canonical_json_bytes(value)) <= 256} if isinstance(row, Mapping) else {}),
                "detail_required": True, "detail_item": index, "detail_view": kind}
    def typed_page(kind: str, values: list[Any]) -> dict[str, Any]:
        start, stop = (offset, end) if view == kind and not raw_view else (0, min(20, len(values)))
        items = [typed_item(values[index], index, kind) for index in range(start, stop)]
        while len(items) > 1 and len(canonical_json_bytes(items)) > 3 * 1024:
            items.pop()
            stop -= 1
        digest = hashlib.sha256(canonical_json_bytes([selection, metadata, kind, None])).hexdigest()
        return {"items": items, "offset": start, "total_count": len(values),
                "snapshot": digest,
                "complete": stop == len(values),
                "next_detail_page": f"md1.{stop}.{digest}" if stop < len(values) else None,
                "detail_view": kind}
    field = bounded_native_header({key: metadata[key] for key in ("name", "type", "classId", "default", "supports", "unit", "availability") if key in metadata})
    if isinstance(restriction, Mapping):
        field["constraints"] = {key: restriction[key] for key in ("type", "min", "max", "minInclusive", "maxInclusive") if key in restriction}
    field["dependency_page"] = typed_page("dependencies", dependencies)
    field["dependencies"] = field["dependency_page"]["items"]
    field["choices"] = typed_page("choices", choices)
    while True:
        if view == "choices" and not raw_view:
            field["choices"] = typed_page("choices", choices)
            end = offset + len(field["choices"]["items"])
        elif view == "dependencies" and not raw_view:
            field["dependency_page"] = typed_page("dependencies", dependencies)
            field["dependencies"] = field["dependency_page"]["items"]
            end = offset + len(field["dependencies"])
        page_rows = rows[offset:end] if raw_view else field["choices" if view == "choices" else "dependency_page"]["items"]
        result = {"contract": "waapi-skill.metadata-detail-page/v1", "selection": selection,
                  "scope": dict(scope), "snapshot": snapshot, "detail_view": view, "field": field,
                  **({"item_index": item_index} if item_index is not None else {}),
                  ("entries" if raw_view else "items"): page_rows,
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
            key = "entries" if "entries" in result else "items"
            if len(result[key]) <= 1:
                reduced = False
                for field_name in ("choices", "dependency_page"):
                    page = result["field"][field_name]
                    if len(page["items"]) <= 1:
                        continue
                    page["items"].pop()
                    stop = page["offset"] + len(page["items"])
                    page["complete"] = stop == page["total_count"]
                    page["next_detail_page"] = f"md1.{stop}.{page['snapshot']}"
                    if field_name == "dependency_page":
                        result["field"]["dependencies"] = page["items"]
                    reduced = True
                    break
                if reduced:
                    continue
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


def immutable_detail_page(value, *, scope, total_count, contract, prefix, label, cursor=None, max_entries=64):
    """Fixed read-only lossless detail page over one already sealed local value."""
    from .canonical import canonical_json_bytes
    import hashlib
    from .metadata_discovery import MetadataDiscoveryError, _require_result_size
    value_sha = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    rows = detail_entries(value)
    def locator(offset):
        digest = hashlib.sha256(canonical_json_bytes([scope, value_sha, offset])).hexdigest()
        return prefix + '.' + str(offset) + '.' + digest
    offset = 0
    if cursor is not None:
        try:
            _, raw_offset, _ = cursor.split('.')
            offset = int(raw_offset)
            valid = (str(offset) == raw_offset and 0 <= offset < len(rows)
                and cursor == locator(offset))
        except (ValueError, AttributeError, TypeError):
            valid = False
        if not valid:
            raise ValueError(label + ' page does not match this immutable transaction, artifact, view, event and value')
    end = min(len(rows), offset + min(64, max_entries))
    while True:
        result = {'contract': contract,
            'scope': scope, 'value_sha256': value_sha, 'total_count': total_count,
            'entries': rows[offset:end], 'entries_encoding': 'lossless_JSON_pointer_entries_with_string_fragments',
            'offset': offset, 'total_entries': len(rows), 'remaining_entries': len(rows) - end,
            'complete': end == len(rows), 'next_page': locator(end) if end < len(rows) else None,
            'mutation_authority': False, 'limits': {'page_entries': 64, 'page_bytes': 16 * 1024}}
        try:
            _require_result_size(result, maximum_bytes=16 * 1024, pretty=True)
            return result
        except MetadataDiscoveryError:
            if end <= offset + 1:
                raise ValueError(label + ' entry cannot fit the existing bounded detail projection')
            end -= 1

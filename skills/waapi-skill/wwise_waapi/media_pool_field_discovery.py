"""Bounded live Media Pool field-name discovery; no caller native request."""
from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes
from .metadata_discovery import MetadataDiscoveryError, _require_result_size


def media_pool_field_discovery_contract() -> dict[str, Any]:
    return {"contract": "waapi-skill.media-pool-field-discovery/v1", "supported_versions": ["2025.1"],
            "input_forms": {
                "meaning": {"flag": "--meaning", "repeatable": True, "maximum_items": 8,
                            "maximum_item_characters": 160, "maximum_total_characters": 640,
                            "meaning": "optional case-insensitive name-substring filters, combined with OR"},
                "page_size": {"flag": "--page-size", "minimum": 1, "maximum": 64, "default": 20},
                "page": {"flag": "--page", "input": "copy returned page continuation only"},
                "selection": {"flag": "--selection", "input": "copy a returned field-name selection only"},
                "detail_page": {"flag": "--detail-page", "input": "copy returned selected-name continuation only"}},
            "field_types": "native getFields reports names only; field value types remain unknown",
            "large_names": "bounded preview plus lossless typed string-fragment continuation",
            "bindings": ["configuration", "endpoint", "version", "live host session", "exact inventory", "lexical filters"],
            "expiry_seconds": 900, "page_and_command_output_limit_bytes": 28 * 1024,
            "absent_return": "partial native observation; never an empty inventory",
            "mutation_authority": False}


def browse_media_pool_fields(raw: Mapping[str, Any], *, context: Mapping[str, Any],
                             meanings: Sequence[str], page: str | None, page_size: int,
                             selection: str | None = None, detail_page: str | None = None,
                             fragment_size: int = 2048) -> dict[str, Any]:
    if "return" not in raw:
        return {"contract": "waapi-skill.media-pool-fields-page/v1", "projection_complete": False,
                "complete": False, "unavailable_fields": ["return"], "native_result": dict(raw),
                "mutation_authority": False}
    fields = raw["return"]
    if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
        raise MetadataDiscoveryError("MEDIA_POOL_FIELDS_INVALID", "Native Media Pool fields must be an array of strings")
    filters = [meaning.casefold() for meaning in meanings]
    matches = [field for field in fields if not filters or any(meaning in field.casefold() for meaning in filters)]
    snapshot = hashlib.sha256(canonical_json_bytes([context, fields, filters])).hexdigest()
    issued = now = int(time.time())
    offset = 0

    def locator(index: int, purpose: str = "mf1") -> str:
        digest = hashlib.sha256(canonical_json_bytes([snapshot, issued, index, purpose])).hexdigest()
        return f"{purpose}.{issued}.{index}.{digest}"

    token = selection or page
    purpose = "mfs1" if selection else "mf1"
    if token is not None:
        try:
            kind, stamp, position, _digest = token.split(".")
            issued, offset = int(stamp), int(position)
            valid = kind == purpose and token == locator(offset, purpose) and 0 <= offset < len(matches)
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise MetadataDiscoveryError("METADATA_SELECTION_SCOPE_CHANGED", "Media Pool fields, filter, configuration or host changed; list fields again")
        if issued > now or now - issued > 900:
            raise MetadataDiscoveryError("METADATA_SELECTION_EXPIRED", "Media Pool field page expired; list fields again")

    def field_summary(index: int) -> dict[str, Any]:
        name = matches[index]
        if len(name.encode("utf-8")) <= 1024:
            return {"name": name, "name_complete": True}
        return {"name_preview": name[:256], "name_complete": False, "name_utf8_bytes": len(name.encode("utf-8")),
                "selection": locator(index, "mfs1"), "detail_required": True}

    if selection is not None:
        name = matches[offset]
        fragment_offset = 0
        detail_snapshot = hashlib.sha256(canonical_json_bytes([snapshot, selection])).hexdigest()
        if detail_page is not None:
            try:
                prefix, position, digest = detail_page.split(".")
                fragment_offset = int(position)
                valid = (prefix == "mfn1" and str(fragment_offset) == position and digest == detail_snapshot
                         and 0 <= fragment_offset < len(name))
            except (ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                raise MetadataDiscoveryError("METADATA_DETAIL_CHANGED", "Selected Media Pool field name or detail page changed; select the field again")
        end = min(len(name), fragment_offset + fragment_size)
        return {"contract": "waapi-skill.media-pool-field-name-page/v1", "field": field_summary(offset),
                "selection": selection, "name_fragment": {"character_offset": fragment_offset, "value": name[fragment_offset:end]},
                "total_characters": len(name), "complete": end == len(name), "mutation_authority": False,
                "next_detail_page": f"mfn1.{end}.{detail_snapshot}" if end < len(name) else None}
    end = min(len(matches), offset + page_size)
    while True:
        result = {"contract": "waapi-skill.media-pool-fields-page/v1", "fields": [field_summary(index) for index in range(offset, end)],
                  "meanings": list(meanings), "filter_kind": "case-insensitive-field-name-substring",
                  "snapshot": snapshot, "available_count": len(fields), "total_count": len(matches),
                  "offset": offset, "remaining_count": len(matches) - end, "complete": end == len(matches),
                  "next_page": locator(end) if end < len(matches) else None,
                  "expires_at": issued + 900, "field_types": "not reported by native getFields", "mutation_authority": False}
        try:
            _require_result_size(result, maximum_bytes=16 * 1024, pretty=True)
            return result
        except MetadataDiscoveryError:
            if end <= offset + 1:
                raise
            end -= 1

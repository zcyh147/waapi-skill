"""Canonical structured creation identity shared by Gateway and receipt observers."""
from __future__ import annotations

from typing import Any, Mapping

from .business_declarations import normalize_live_object_identity


def ordinary_creation_fields(node: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Return materialized ordinary fields; richer graph unions need their own proof."""
    fields = []
    for kind, key in (("scalar", "properties"), ("reference", "references")):
        for item in node.get(key, []):
            if (not isinstance(item, Mapping) or not isinstance(item.get("name"), str)
                    or (kind == "reference" and ("target_id" not in item
                        or (item["target_id"] is not None and not isinstance(item["target_id"], str))))):
                return None
            fields.append({"kind": kind, **dict(item)})
    return fields


def capture_created_field_metadata(node: Mapping[str, Any], object_id: str, *, read: Any) -> list[dict[str, Any]]:
    """Retain optional exact-object facts without changing source-write verification."""
    from .operation_registry import OperationContractError
    fields = ordinary_creation_fields(node)
    if not fields:
        return []
    records = []
    requests = [("ak.wwise.core.object.getPropertyAndReferenceNames", {"object": object_id}),
        *(("ak.wwise.core.object.getPropertyInfo", {"object": object_id, "property": item["name"]}) for item in fields)]
    for uri, args in requests:
        record = {"role": "created-root-history-field-metadata", "uri": uri, "args": args, "options": {}}
        records.append(record)
        try:
            record["result"] = read(uri, args, {})
        except OperationContractError as exc:
            if exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK", "RESULT_TOO_LARGE"}:
                raise
            record["error"] = exc.as_dict()
            break
    return records


def verified_created_root_identity(verification: Mapping[str, Any]) -> dict[str, str] | None:
    """Use the verifier's structured identity witness, even if a field failed."""
    witnesses = [row.get("evidence") for row in verification.get("assertions", [])
                 if isinstance(row, Mapping) and row.get("kind") == "verified_created_root_identity"
                 and row.get("passed") is True]
    if len(witnesses) != 1 or not isinstance(witnesses[0], Mapping):
        return None
    try:
        value = normalize_live_object_identity(witnesses[0])
    except ValueError:
        return None
    return {"id": value.object_id, "name": value.name, "type": value.object_type, "path": value.path}

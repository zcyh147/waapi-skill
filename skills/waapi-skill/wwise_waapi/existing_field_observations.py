"""Source-time existing-field witnesses for selected history expectations.

These optional observations never replace a source operation's own verifier.
"""
from __future__ import annotations

from typing import Any, Mapping

from .canonical import canonical_sha256

CONTRACT = "waapi-skill.existing-field-source-observation/v1"
ROLE = "existing-field-history-source-after"


def materialized_fields(node: Mapping[str, Any], metadata: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    fields = []
    if node.get("requested_name") != node.get("original_name"):
        fields.append({"field": "name", "field_kind": "identity", "after": node.get("requested_name")})
    if node.get("notes_supplied"):
        fields.append({"field": "notes", "field_kind": "text", "after": node.get("requested_notes")})
    for kind, key in (("scalar", "properties"), ("reference", "references")):
        for item in node.get(key, []):
            token = item.get("name")
            info = metadata.get(str(token).casefold())
            if (not isinstance(token, str) or info is None or info.name != token
                    or kind == "reference" and ("target_id" not in item
                        or item["target_id"] is not None and not isinstance(item["target_id"], str))):
                return None
            fields.append({"field": token, "field_kind": kind,
                "after": item["value"] if kind == "scalar" else item["target_id"],
                "metadata_type": info.type, "field_info": info.as_dict(include_raw=True)})
    if len({field["field"] for field in fields}) != len(fields):
        return None
    return fields


def capture_before(node, metadata, *, version, catalog, read):
    """Certify a view before reading; unavailable evidence leaves source usable."""
    from .edit_history_business import capture_field_read_platform, _identity, _read_error, _reference_value
    from .operation_registry import OperationContractError, _has_field, _field_value

    proof = {"contract": CONTRACT, "version": version, "request_path": node["request_path"],
        "object_id": node["target_id"], "status": "unobserved", "readbacks": []}
    fields = materialized_fields(node, metadata)
    if not fields:
        return {**proof, "reason": "field_union_requires_its_complete_history_observer"}
    proof["fields"] = fields

    def retained(uri, args, options):
        record = {"uri": uri, "args": args, "options": options}
        proof["readbacks"].append(record)
        try:
            record["result"] = read(uri, args, options)
            return record["result"]
        except OperationContractError as exc:
            record["error"] = _read_error(exc)
            raise

    try:
        view = capture_field_read_platform(version, node.get("platform"), read=retained)
        proof["field_read_platform"] = view
        if view.get("status") != "certified":
            return {**proof, "reason": "original_read_platform_not_certified"}
        projection = ["id", "name", "type", "path", "classId", "parent", "notes",
            *(field["field"] for field in fields if field["field"] not in {"name", "notes"})]
        result = retained("ak.wwise.core.object.get", {"from": {"id": [node["target_id"]]}},
            {"return": projection, "platform": view["platform_id"]})
        rows = result.get("return") if isinstance(result, Mapping) else None
        if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping)
                or _identity(rows[0])["id"] != node["target_id"].upper()
                or type(rows[0].get("classId")) is not int
                or not all(_has_field(rows[0], field["field"]) for field in fields)):
            return {**proof, "reason": "complete_exact_identity_class_and_before_fields_not_observed"}
        proof.update(before=dict(rows[0]), projection=projection, reference_targets=[])
        classes = [item.as_dict() for item in catalog
            if item.class_id == rows[0]["classId"] and item.name == rows[0].get("type")]
        if len(classes) != 1:
            return {**proof, "reason": "exact_live_class_and_object_type_not_certified"}
        proof["class_type"] = classes[0]
        targets = set()
        for field in fields:
            if field["field_kind"] == "reference":
                targets.update(value for value in (_reference_value(_field_value(rows[0], field["field"])),
                    _reference_value(field["after"])) if value is not None)
        if targets:
            result = retained("ak.wwise.core.object.get", {"from": {"id": sorted(targets)}},
                {"return": ["id", "name", "type", "path", "classId"]})
            rows = result.get("return") if isinstance(result, Mapping) else None
            if (not isinstance(rows, list) or len(rows) != len(targets)
                    or {_identity(row)["id"] for row in rows} != targets
                    or any(type(row.get("classId")) is not int for row in rows)):
                return {**proof, "reason": "reference_target_identities_not_completely_observed"}
            proof["reference_targets"] = list(rows)
        return {**proof, "status": "certified"}
    except OperationContractError as exc:
        if exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK", "RESULT_TOO_LARGE"}:
            raise
        return {**proof, "reason": "optional_source_observation_failed", "error": _read_error(exc)}
    except ValueError as exc:
        return {**proof, "reason": "optional_source_observation_incomplete", "error": str(exc)}


def capture_after(proof, *, read):
    """Keep a controlled postread and raw metadata in the existing source journal."""
    from .edit_history_business import NAMES, INFO, GET, _read_error
    from .operation_registry import OperationContractError

    record = {"role": ROLE, "source_proof_sha256": canonical_sha256(proof),
        "request_path": proof["request_path"], "status": "unobserved", "readbacks": []}
    if proof.get("status") != "certified":
        return {**record, "reason": proof.get("reason", "source_before_not_certified")}

    def retained(uri, args, options):
        item = {"uri": uri, "args": args, "options": options}
        record["readbacks"].append(item)
        try:
            item["result"] = read(uri, args, options)
            return item["result"]
        except OperationContractError as exc:
            item["error"] = _read_error(exc)
            raise

    try:
        identity = proof["object_id"]
        retained(NAMES, {"object": identity}, {})
        for field in proof["fields"]:
            if "field_info" in field:
                retained(INFO, {"object": identity, "property": field["field"]}, {})
        retained(GET, {"from": {"id": [identity]}}, {"return": proof["projection"],
            "platform": proof["field_read_platform"]["platform_id"]})
        if proof["reference_targets"]:
            result = retained(GET, {"from": {"id": [row["id"] for row in proof["reference_targets"]]}},
                {"return": ["id", "name", "type", "path", "classId"]})
            record["reference_targets"] = result.get("return") if isinstance(result, Mapping) else None
        return {**record, "status": "observed"}
    except OperationContractError as exc:
        if exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK", "RESULT_TOO_LARGE"}:
            raise
        return {**record, "reason": "optional_source_postread_failed", "error": _read_error(exc)}


def receipt_observations(snapshot):
    """Associate every ordinary existing-field outcome with actual source reads."""
    from .edit_history_business import _identity, _scalar_matches, _reference_value, NAMES, INFO, GET
    from .builders.metadata import bind_get_property_info_result, parse_property_and_reference_names_result
    from .object_lifecycle_graph import lifecycle_snapshot_equal
    from .operation_registry import _has_field, _field_value

    prepared = snapshot.preview.artifact["prepared_operation"]
    plan, state = prepared["verification_plan"], prepared["pre_state"]
    nodes = plan.get("nodes", [])
    if (not nodes or any(node.get("existing_target") is not True or node.get("preexisting_id") is not None
            or node.get("import") or node.get("children_request_paths") or node.get("list_request_paths")
            or node.get("list_snapshots") for node in nodes)
            or plan.get("replaced_subtree_rows") or plan.get("replaced_list_subtree_rows")):
        raise ValueError("Graph/List/creation/restoration receipt observations remain implementation obligations")
    if state.get("effect_render_chains"):
        raise ValueError("Render history requires its complete ordered-chain observation")
    proofs = state.get("existing_field_observations", [])
    if len(proofs) != len(nodes) or len({proof.get("request_path") for proof in proofs}) != len(nodes):
        raise ValueError("Existing-field receipt lacks every original source observation")
    verification = next(event["details"]["verification"] for event in reversed(snapshot.events)
        if event.get("event_type") == "verification_recorded")
    captured = [record for record in verification.get("readbacks", []) if record.get("role") == ROLE]
    observations = []
    for node in nodes:
        proof, = [proof for proof in proofs if proof.get("request_path") == node["request_path"]]
        matches = [record for record in captured if record.get("request_path") == node["request_path"]]
        if (proof.get("status") != "certified" or len(matches) != 1 or matches[0].get("status") != "observed"
                or matches[0].get("source_proof_sha256") != canonical_sha256(proof)
                or proof.get("field_read_platform", {}).get("status") != "certified"):
            raise ValueError("Existing-field receipt original view/before/verified-after observations are unavailable")
        observed = matches[0]
        fields = proof["fields"]
        declared = {item["name"]: ("scalar", item["value"]) for item in node.get("properties", [])}
        for item in node.get("references", []):
            if "target_id" not in item or isinstance(item["target_id"], list):
                raise ValueError("Existing reference union requires its own complete history observation")
            declared[item["name"]] = ("reference", item["target_id"])
        if node.get("notes_supplied"):
            declared["notes"] = ("text", node["requested_notes"])
        if node.get("requested_name") != node.get("original_name"):
            declared["name"] = ("identity", node["requested_name"])
        if set(declared) != {field["field"] for field in fields} or len(fields) != len(declared):
            raise ValueError("Existing-field receipt does not cover every materialized source field exactly once")
        platform = proof["field_read_platform"]["platform_id"]
        identity = proof["object_id"]
        reads = observed["readbacks"]
        names_records = [record for record in reads if record.get("uri") == NAMES and record.get("args") == {"object": identity}]
        if len(names_records) != 1 or "result" not in names_records[0]:
            raise ValueError("Existing-field source names were not independently observed")
        names = [row.name for row in parse_property_and_reference_names_result(names_records[0]["result"])]
        rows_records = [record for record in reads if record.get("uri") == GET
            and record.get("args") == {"from": {"id": [identity]}}
            and record.get("options") == {"return": proof["projection"], "platform": platform}]
        rows = rows_records[0].get("result", {}).get("return") if len(rows_records) == 1 else None
        if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping)
                or _identity(rows[0])["id"] != identity.upper()
                or type(rows[0].get("classId")) is not int or rows[0]["classId"] != proof["before"]["classId"]):
            raise ValueError("Existing-field source postread lacks its exact original GUID/class")
        before, after = proof["before"], rows[0]
        targets_before, targets_after = proof["reference_targets"], observed.get("reference_targets", [])
        if (not isinstance(targets_after, list) or len(targets_before) != len(targets_after)
                or {row["id"].upper() for row in targets_before} != {row.get("id", "").upper() for row in targets_after}
                or any(not any(lifecycle_snapshot_equal(row, actual) for actual in targets_after) for row in targets_before)):
            raise ValueError("Existing-reference source target identities/classes were not preserved")
        expected_identity = _identity(before)
        if "name" in declared:
            expected_identity.update(name=declared["name"][1],
                path=before["path"].rsplit("\\", 1)[0] + "\\" + declared["name"][1])
        if _identity(after) != expected_identity:
            raise ValueError("Existing-field source postread identity differs from its declared outcome")
        for field in fields:
            token, kind = field["field"], field["field_kind"]
            if declared[token][0] != kind or not lifecycle_snapshot_equal(declared[token][1], field["after"]):
                raise ValueError("Existing-field source observation differs from materialized intent")
            old, new = _field_value(before, token), _field_value(after, token)
            if not _has_field(before, token) or not _has_field(after, token):
                raise ValueError("Existing-field source before/after projection omitted a field")
            extra = {}
            if "field_info" in field:
                metadata = [record for record in reads if record.get("uri") == INFO
                    and record.get("args") == {"object": identity, "property": token}]
                if len(metadata) != 1 or "result" not in metadata[0]:
                    raise ValueError("Existing-field source raw metadata was not independently observed")
                info = bind_get_property_info_result(metadata[0]["result"], field_token=token, available_names=names)
                if info.name != token or not lifecycle_snapshot_equal(info.as_dict(include_raw=True), field["field_info"]):
                    raise ValueError("Existing-field source raw/normalized metadata changed")
                extra.update(metadata_type=info.type, field_info=info.as_dict(include_raw=True))
            if kind == "reference":
                old, new = _reference_value(old), _reference_value(new)
                if new != _reference_value(field["after"]):
                    raise ValueError("Existing-field source reference outcome differs from its independent readback")
            elif kind == "scalar":
                if not _scalar_matches(old, old, field["metadata_type"]) or not _scalar_matches(new, field["after"], field["metadata_type"]):
                    raise ValueError("Existing-field source scalar outcome differs from its exact typed readback")
            elif not isinstance(old, str) or not isinstance(new, str) or new != field["after"]:
                raise ValueError("Existing-field source text outcome is not observed")
            observations.append({"kind": "existing_field", "object_before": _identity(before),
                "object_after": _identity(after), "class_id": before["classId"], "field": token,
                "field_kind": kind, "before": old, "after": new, "platform": platform,
                **({"reference_targets_before": targets_before, "reference_targets_after": targets_after}
                    if kind == "reference" else {}), **extra})
    return observations

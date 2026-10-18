"""Owned scoped expectations for a native latest-project-history action.

A receipt supplies observable before/after state, never a native history entry ID.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
from typing import Any, Callable, Mapping

from .business_declarations import BusinessContext, normalize_live_object_identity
from .canonical import canonical_json_bytes, canonical_sha256
from .builders.metadata import bind_get_property_info_result, parse_property_and_reference_names_result
from .metadata_discovery import metadata_typed_value_type
from .object_lifecycle_graph import lifecycle_snapshot_equal
from .transactions import TransactionState, TransactionStore
from .transaction_runtime import canonical_project_path

from .edit_history_contracts import HISTORY_VERSIONS

CONTRACT = "waapi-skill.owned-history-expectation/v1"
REFERENCE_CONTRACT = "waapi-skill.history-draft-reference/v1"
GET = "ak.wwise.core.object.get"
NAMES = "ak.wwise.core.object.getPropertyAndReferenceNames"
INFO = "ak.wwise.core.object.getPropertyInfo"
IDENTITY = ("id", "name", "type", "path")
MAX_OBSERVATIONS = 128
MAX_BINDING_BYTES = 64 * 1024
_GUID = re.compile(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}\Z")


class HistoryObservationError(ValueError):
    """Keep the original bounded read even when its observation is incomplete."""
    def __init__(self, message: str, readback: Mapping[str, Any] | list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.readbacks = [dict(readback)] if isinstance(readback, Mapping) else list(readback)


def _scalar_matches(actual: Any, expected: Any, metadata_type: str) -> bool:
    kind = metadata_typed_value_type(metadata_type)
    if kind == "number":
        try:
            return (not isinstance(actual, bool) and not isinstance(expected, bool)
                and isinstance(actual, (int, float)) and isinstance(expected, (int, float))
                and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-5))
        except (OverflowError, ValueError):
            return False
    value_type = {"string": str, "boolean": bool, "integer": int}.get(kind)
    return value_type is not None and type(actual) is value_type and type(expected) is value_type and actual == expected


def _read_error(exc: Exception) -> dict[str, Any]:
    from .operation_registry import OperationContractError
    if isinstance(exc, OperationContractError):
        return exc.as_dict()  # Already bounded/normalized by the owning read path.
    return {"type": type(exc).__name__, "message": str(exc)[:2048]}


def _reference_value(value: Any) -> str | None:
    # Reuse the owning reference primitive's null/identity representations,
    # then require the canonical GUID observation this history proof promises.
    from .operation_registry import _reference_identity, _reference_value_is_null
    if _reference_value_is_null(value):
        return None
    if isinstance(value, Mapping) and ("id" not in value or set(value) - {"id", "name", "type", "path"}
            or any(not isinstance(item, str) for item in value.values())):
        raise ValueError("History reference readback lacks a canonical object-reference shape")
    identity = _reference_identity(value)
    if not isinstance(identity, str) or not _GUID.fullmatch(identity):
        raise ValueError("History reference readback lacks a canonical target GUID or explicit null")
    return identity.upper()


def capture_field_read_platform(version: str, selector: str | None, *, read: Callable[..., Any]) -> dict[str, Any]:
    """Certify object.get's original view; never infer a mutation's omission meaning."""
    proof = {"contract": "waapi-skill.field-read-platform/v1", "version": version, "selector": selector}
    if isinstance(selector, str) and _GUID.fullmatch(selector) and selector != "{00000000-0000-0000-0000-000000000000}":
        return {**proof, "status": "certified", "platform_id": selector.upper(), "source": "explicit_object_get_platform_GUID"}
    if version not in {"2022.1", "2023.1", "2024.1", "2025.1"}:
        return {**proof, "status": "unobserved", "reason": "no_pinned_current_platform_observer_in_this_lane"}
    from .operation_registry import OperationContractError
    try:
        context = read("ak.wwise.core.getProjectInfo", {}, {})
    except OperationContractError as exc:
        if exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK"}:
            raise
        # This optional observer must not impose a new prerequisite on an
        # otherwise usable source write. Preserve its owned bounded failure;
        # only an uncertified history expectation becomes unavailable.
        return {**proof, "status": "unobserved", "reason": "project_platform_read_failed", "error": exc.as_dict()}
    rows = context.get("platforms") if isinstance(context, Mapping) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        return {**proof, "status": "unobserved", "reason": "complete_bounded_project_platform_inventory_not_exposed"}
    ids, names = set(), set()
    for row in rows:
        if (not isinstance(row, Mapping) or not isinstance(row.get("id"), str) or not _GUID.fullmatch(row["id"])
            or row["id"] == "{00000000-0000-0000-0000-000000000000}" or not isinstance(row.get("name"), str)
            or not row["name"] or row["id"].upper() in ids or row["name"].casefold() in names):
            return {**proof, "status": "unobserved", "reason": "project_platform_identity_or_uniqueness_not_exposed"}
        ids.add(row["id"].upper()); names.add(row["name"].casefold())
    matches = [row for row in rows if (row["id"].upper() == str(context.get("currentPlatformId")).upper()
        if selector is None else row["name"] == selector)]
    if len(matches) != 1:
        return {**proof, "status": "unobserved", "reason": "original_read_platform_not_uniquely_observed"}
    return {**proof, "status": "certified", "platform_id": matches[0]["id"].upper(),
        "platform_name": matches[0]["name"], "source": "live_getProjectInfo_and_object_get_platform_contract"}


def observe_field_read_platform(pre_state: Mapping[str, Any], *, read: Callable[..., Any]) -> dict[str, Any] | None:
    primary = _observe_field_read_platform_proof(pre_state, read=read)
    existing = pre_state.get("existing_field_observations")
    chains = pre_state.get("effect_render_chains")
    groups = ([proof for proof in existing if proof.get("status") == "certified"] if isinstance(existing, list) else [])
    groups.extend(chains if isinstance(chains, list) else [])
    outcomes = ([primary] if primary is not None else []) + [
        outcome for proof in groups
        if (outcome := _observe_field_read_platform_proof(proof, read=read)) is not None]
    if outcomes and (isinstance(existing, list) or groups):
        return {"matches": all(item["matches"] for item in outcomes), "views": [
            {key: value for key, value in item.items() if key != "readbacks"} for item in outcomes],
            "readbacks": [row for item in outcomes for row in item["readbacks"]]}
    return primary


def _observe_field_read_platform_proof(pre_state: Mapping[str, Any], *, read: Callable[..., Any]) -> dict[str, Any] | None:
    proof = pre_state.get("field_read_platform")
    if not isinstance(proof, Mapping) or proof.get("status") != "certified":
        return None  # An explicit receipt limitation, never a fabricated view.
    readbacks = []
    def retained(uri, args, options):
        record = {"uri": uri, "args": args, "options": options}
        readbacks.append(record)
        try:
            result = read(uri, args, options)
            record["result"] = result
            return result
        except Exception as exc:
            record["error"] = _read_error(exc)
            raise
    try:
        actual = capture_field_read_platform(proof["version"], proof["selector"], read=retained)
        return {"matches": lifecycle_snapshot_equal(proof, actual), "expected": dict(proof), "actual": actual, "readbacks": readbacks}
    except Exception as exc:
        return {"matches": False, "expected": dict(proof), "error": {"type": type(exc).__name__, "message": str(exc)[:2048]}, "readbacks": readbacks}


def _receipt_platform(plan: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    platform = plan.get("platform")
    if platform == "{00000000-0000-0000-0000-000000000000}":
        raise ValueError("Receipt null GUID is an unlink instruction, not a certified read platform; its original view remains unobserved")
    if isinstance(platform, str) and _GUID.fullmatch(platform):
        return platform
    proof = state.get("field_read_platform")
    if (not isinstance(proof, Mapping) or proof.get("status") != "certified" or proof.get("selector") != platform
        or not isinstance(proof.get("platform_id"), str) or not _GUID.fullmatch(proof["platform_id"])
        or plan.get("observation_platform") != proof["platform_id"]
        or state.get("field_before", {}).get("observation_platform") != proof["platform_id"]):
        raise ValueError("Receipt original current/named read platform is not certified; its missing source observation remains an implementation/evidence obligation")
    return proof["platform_id"]


def _identity(row: Any) -> dict[str, Any]:
    bound = normalize_live_object_identity(row)
    return {"id": bound.object_id, "name": bound.name, "type": bound.object_type, "path": bound.path}


def _receipt_observations(prepared: Mapping[str, Any]) -> list[dict[str, Any]]:
    plan, state = prepared.get("verification_plan"), prepared.get("pre_state")
    if not isinstance(plan, Mapping) or not isinstance(state, Mapping):
        raise ValueError("History expectation receipt lacks a prepared business observation")
    if plan.get("kind") == "undo-group-result-schemas":
        calls = state.get("execution_plan", {}).get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("Compound history receipt lacks its exact prepared children")
        observations = []
        for child in calls:
            if not isinstance(child, Mapping) or not isinstance(child.get("prepared_operation"), Mapping):
                raise ValueError("Compound history receipt lacks a recoverable child observation")
            observations.extend(_receipt_observations(child["prepared_operation"]))
        if not 1 <= len(observations) <= MAX_OBSERVATIONS:
            raise ValueError("Compound history receipt exceeds its observation bound")
        before_by_id, after_by_id = {}, {}
        outcomes = set()
        for row in observations:
            identity = row["object_before"]
            object_id = identity["id"]
            if object_id in before_by_id and before_by_id[object_id] != identity:
                raise ValueError("Compound history children disagree about their before identity")
            before_by_id[object_id] = identity
            key = (object_id, row["field"], row.get("platform"))
            if key in outcomes:
                raise ValueError("Compound history receipt has overlapping observed outcomes")
            outcomes.add(key)
            if row["field"] == "name":
                after_by_id[object_id] = row["object_after"]
        for row in observations:
            after = dict(after_by_id.get(row["object_before"]["id"], row["object_after"]))
            # A rename changes the native hierarchy path of observed descendants
            # too. Apply deepest ancestors first, always using the sealed before
            # path to distinguish hierarchy segments from matching name prefixes.
            for object_id in sorted(after_by_id, key=lambda key: len(before_by_id[key]["path"]), reverse=True):
                before_path = before_by_id[object_id]["path"]
                if row["object_before"]["path"].startswith(before_path + "\\"):
                    after["path"] = after_by_id[object_id]["path"] + after["path"][len(before_path):]
            row["object_after"] = after
        return observations
    if plan.get("kind") == "same-guid-reference":
        from .operation_registry import _has_field, _field_value
        identity = _identity(state.get("object"))
        field, platform = plan.get("field"), _receipt_platform(plan, state)
        before, info = state.get("field_before", {}), state.get("field_info", {})
        if (identity["id"] != str(plan.get("object_id")).upper() or not isinstance(field, str)
            or not isinstance(before, Mapping) or "value" not in before or before.get("field") != field
            or before.get("platform") != plan.get("platform") or not isinstance(before.get("row"), Mapping)
            or not _has_field(before["row"], field) or not isinstance(info, Mapping)
            or not ((info.get("type") or "").casefold() in {"reference", "objectreference"}
                    or str(info.get("restriction", {}).get("type", "")).casefold() == "reference"
                    or info.get("supports", {}).get("reference") is True)):
            raise ValueError("Reference receipt requires exact metadata, identity and an observed before value/platform")
        old = _reference_value(before["value"])
        if _reference_value(_field_value(before["row"], field)) != old:
            raise ValueError("Reference receipt before projection disagrees with its sealed value")
        new = None if plan.get("expected_clear") is True else _reference_value(plan.get("expected_target_id"))
        if new is None and plan.get("expected_clear") is not True:
            raise ValueError("Reference receipt lacks its canonical expected target")
        return [{"object_before": identity, "object_after": dict(identity), "field": field,
            "before": old, "after": new, "platform": platform, "field_kind": "reference",
            "metadata_type": info.get("type"), "field_info": dict(info)}]
    if plan.get("kind") == "same-guid-property":
        if any(chain.get("derived") for chain in state.get("effect_render_chains", [])):
            raise ValueError("Render chain side effects require a complete multi-field history observation; a single-field receipt cannot certify them")
        identity = _identity(state.get("object"))
        field, platform, metadata_type = plan.get("field"), _receipt_platform(plan, state), plan.get("metadata_type")
        field_before, info = state.get("field_before", {}), state.get("field_info", {})
        old, new = field_before.get("value"), plan.get("expected_value")
        if (identity["id"] != str(plan.get("object_id")).upper() or not isinstance(field, str)
            or field_before.get("field") != field or field_before.get("platform") != plan.get("platform")
            or not isinstance(info, Mapping) or info.get("type") != metadata_type
            or not _scalar_matches(old, old, metadata_type) or not _scalar_matches(new, new, metadata_type)):
            raise ValueError("Property receipt requires an exact typed before/after value and platform view")
        return [{"object_before": identity, "object_after": dict(identity), "field": field,
            "before": old, "after": new, "platform": platform, "metadata_type": metadata_type, "field_info": dict(info)}]
    if plan.get("kind") not in {"same-guid-notes", "same-guid-renamed"}:
        raise ValueError("This receipt observer is not yet implemented; it remains an edit-history implementation obligation")
    before = state.get("object")
    identity = _identity(before)
    field = "notes" if plan["kind"] == "same-guid-notes" else "name"
    old, new = before.get(field), plan.get("expected_" + field)
    after_identity = dict(identity)
    if field == "name" and isinstance(new, str):
        after_identity.update(name=new, path=identity["path"].rsplit("\\", 1)[0] + "\\" + new)
    if identity["id"] != str(plan.get("object_id")).upper() or not isinstance(old, str) or not isinstance(new, str):
        raise ValueError("History expectation requires an observed before value and an exact verified after value")
    return [{"object_before": identity, "object_after": after_identity, "field": field, "before": old, "after": new}]


def _snapshot_observations(snapshot: Any) -> list[dict[str, Any]]:
    prepared = snapshot.preview.artifact["prepared_operation"]
    plan = prepared.get("verification_plan", {})
    if (prepared.get("pre_state", {}).get("effect_render_chains")
            and plan.get("kind") in {"same-guid-property", "object-set-batch"}):
        from .render_history_observations import receipt_observations as render_observations
        observations, covered = render_observations(snapshot)
        if plan["kind"] == "object-set-batch":
            from .existing_field_observations import receipt_observations
            observations.extend(receipt_observations(snapshot, exclude_fields=covered))
        elif plan["field"] not in covered.get((str(plan["object_id"]).upper(), _receipt_platform(plan, prepared["pre_state"])), set()):
            raise ValueError("Render source selected field is missing from its complete chain observation")
        return observations
    if plan.get("kind") == "object-set-batch":
        from .existing_field_observations import receipt_observations
        return receipt_observations(snapshot)
    if any(chain.get("derived") for chain in prepared.get("pre_state", {}).get("effect_render_chains", [])):
        raise ValueError("Created Render chain effects require complete multi-field history observations")
    if plan.get("kind") != "object-create-graph":
        return _receipt_observations(prepared)
    # This first presence observer has one ordinary new child, never an
    # inferred graph/List/merge/replace restoration image.
    nodes = plan.get("nodes")
    if (prepared.get("operation") != "object.create" or not isinstance(nodes, list) or len(nodes) != 1
        or plan.get("on_name_conflict") != "fail" or plan.get("list") is not None
        or plan.get("preexisting_root_rows") != [] or plan.get("replaced_subtree_rows") != []):
        raise ValueError("Creation history currently requires one new fail-mode child; graph/List/merge/replace remain implementation obligations")
    node = nodes[0]
    if (not isinstance(node, Mapping) or node.get("request_path") != "$" or node.get("parent_request_path") is not None
        or node.get("collection") != "children" or node.get("existing_target") is not False
        or node.get("preexisting_id") is not None or node.get("requested_language") is not None):
        raise ValueError("Creation history lacks a supported ordinary leaf observation")
    from .creation_observations import verified_created_root_identity, ordinary_creation_fields
    materialized_fields = ordinary_creation_fields(node)
    if materialized_fields is None:
        raise ValueError("Creation history field union requires its own complete observation")
    if len(materialized_fields) + 1 > MAX_OBSERVATIONS or len({item["name"] for item in materialized_fields}) != len(materialized_fields):
        raise ValueError("Creation history fields exceed their combined bound or contain duplicate tokens")
    view = prepared.get("pre_state", {}).get("field_read_platform", {})
    platform = None
    if materialized_fields:
        if view.get("status") != "certified" or not _GUID.fullmatch(str(view.get("platform_id"))):
            raise ValueError("Creation receipt original read platform is not certified")
        platform = view["platform_id"]
    from .operation_object import flatten_create_result
    verification = next(event["details"]["verification"] for event in reversed(snapshot.events)
        if event.get("event_type") == "verification_recorded")
    identity = verified_created_root_identity(verification)
    execution = [event.get("details", {}).get("dispatch_result") for event in snapshot.events
        if event.get("event_type") == "execution_completed"]
    if identity is None or len(execution) != 1 or not isinstance(execution[0], Mapping) or execution[0].get("ok") is not True:
        raise ValueError("Creation history requires the actual successful result and one verified root witness")
    returned = flatten_create_result(execution[0].get("result"), max_nodes=1)
    if (len(returned) != 1 or returned[0].object.upper() != identity["id"] or returned[0].name != identity["name"]
        or identity["name"] != node.get("requested_name") or identity["type"] != node.get("canonical_type")):
        raise ValueError("Creation history root witness differs from its actual native result or declaration")
    paths = prepared.get("pre_state", {}).get("object_graph_guard", {}).get("path_snapshots", [])
    if len(paths) != 1 or paths[0].get("path") != identity["path"] or paths[0].get("rows") != []:
        raise ValueError("Creation history requires the exact sealed path absence before creation")
    fields = [*IDENTITY, "parent", "notes"]
    reads = [row for row in verification.get("readbacks", []) if isinstance(row, Mapping)
        and row.get("uri") == GET and row.get("args") == {"from": {"id": [identity["id"]]}}
        and isinstance(row.get("options"), Mapping) and set(row["options"].get("return", [])) >= set(fields)
        and not set(row["options"]) - {"return", "platform"}
        and row["options"].get("platform") == platform and "error" not in row]
    if len(reads) != 1:
        raise ValueError("Creation history requires one independent complete root readback")
    rows = reads[0].get("result", {}).get("return")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise ValueError("Creation history source root readback is incomplete")
    row = rows[0]
    if (_identity(row) != identity or not isinstance(row.get("notes"), str)
        or _reference_value(row.get("parent")) != str(plan.get("parent_id")).upper()
        or "parent" not in row or (node.get("notes_supplied") is True and row["notes"] != node.get("requested_notes"))):
        raise ValueError("Creation history source identity, parent or actual notes are incomplete")
    observation = {"kind": "creation_presence", "object": identity, "parent_id": str(plan["parent_id"]).upper(),
        "notes": row["notes"], "before": False, "after": True}
    if materialized_fields:
        if type(row.get("classId")) is not int or row["classId"] != node.get("class_id"):
            raise ValueError("Creation history requires the exact independently observed class ID")
        retained = [item for item in verification.get("readbacks", [])
            if item.get("role") == "created-root-history-field-metadata"]
        names_rows = [item for item in retained if item.get("uri") == NAMES and item.get("args") == {"object": identity["id"]}]
        if len(names_rows) != 1 or "result" not in names_rows[0]:
            raise ValueError("Creation history requires complete source object-scoped field names")
        names = [item.name for item in parse_property_and_reference_names_result(names_rows[0]["result"])]
        captured = []
        from .operation_registry import _has_field, _field_value
        for field in materialized_fields:
            token = field["name"]
            matches = [item for item in retained if item.get("uri") == INFO
                and item.get("args") == {"object": identity["id"], "property": token}]
            if len(matches) != 1 or "result" not in matches[0]:
                raise ValueError("Creation history requires exact source object-scoped field metadata")
            info = bind_get_property_info_result(matches[0]["result"], field_token=token, available_names=names)
            if info.name != token:
                raise ValueError("Creation history source metadata names a different field")
            if not _has_field(row, token):
                raise ValueError("Creation history source field projection is missing")
            actual = _field_value(row, token)
            target_identity = None
            if field["kind"] == "scalar":
                if info.type != field.get("metadata_type") or not _scalar_matches(actual, field["value"], info.type):
                    raise ValueError("Creation history source scalar does not match its exact metadata/value")
            else:
                if not ((info.type or "").casefold() in {"reference", "objectreference"}
                        or str(info.restriction.get("type", "")).casefold() == "reference"
                        or info.supports.get("reference") is True):
                    raise ValueError("Creation history source metadata does not certify a Reference")
                actual = _reference_value(actual)
                if actual != _reference_value(field["target_id"]):
                    raise ValueError("Creation history source reference differs from its verified outcome")
                if actual is not None:
                    targets = [_identity(role["row"]) for role in prepared.get("resolved_roles", {}).values()
                        if isinstance(role, Mapping) and str(role.get("object")).upper() == actual]
                    if not targets or any(target != targets[0] for target in targets):
                        raise ValueError("Creation reference requires its exact source existing-target role")
                    target_identity = targets[0]
            captured.append({"field": token, "field_kind": field["kind"], "value": actual,
                "metadata_type": info.type, "field_info": info.as_dict(include_raw=True),
                **({"reference_target": target_identity} if target_identity is not None else {})})
        observation.update(platform=platform, class_id=row["classId"])
        return [observation, *({"kind": "creation_field", "object_id": identity["id"], "before": False, "after": True,
            **item} for item in captured)]
    return [observation]


def _observe_presence(expected: Mapping[str, Any], present: bool, read: Callable[..., Any]) -> dict[str, Any]:
    identity = expected["object"]
    observations = []
    targets = {item["reference_target"]["id"]: item["reference_target"]
        for item in expected.get("fields", []) if "reference_target" in item}
    if targets:
        result = read(GET, {"from": {"id": list(targets)}}, {"return": list(IDENTITY)})
        rows = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(rows, list) or len(rows) != len(targets):
            raise ValueError("Created-reference history targets require complete exact identity readback")
        actual = [_identity(row) for row in rows]
        observations.append(len({row["id"] for row in actual}) == len(targets)
            and all(targets.get(row["id"]) == row for row in actual))
    fields = expected.get("fields", []) if present else []
    if fields:
        names = [item.name for item in parse_property_and_reference_names_result(read(NAMES, {"object": identity["id"]}, {}))]
        for field in fields:
            info = bind_get_property_info_result(read(INFO, {"object": identity["id"], "property": field["field"]}, {}),
                field_token=field["field"], available_names=names)
            if info.name != field["field"] or not lifecycle_snapshot_equal(info.as_dict(include_raw=True), field["field_info"]):
                raise ValueError("Created-object history field metadata changed")
    for selector in ({"id": [identity["id"]]}, {"path": [identity["path"]]}):
        result = read(GET, {"from": selector}, {"return": [*IDENTITY, "parent", "notes",
            *(["classId", *(item["field"] for item in fields)] if fields else [])],
            **({"platform": expected["platform"]} if fields else {})})
        if not isinstance(result, Mapping) or set(result) != {"return"} or not isinstance(result["return"], list):
            raise ValueError("History presence read requires a complete exact-selector result")
        rows = result["return"]
        if len(rows) > 1 or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("History presence read contains duplicate or malformed rows")
        if rows:
            row = rows[0]
            actual = _identity(row)
            if "parent" not in row or not isinstance(row.get("notes"), str):
                raise ValueError("History presence read lacks parent or notes projection")
            matches = (actual == identity and _reference_value(row["parent"]) == expected["parent_id"]
                and row["notes"] == expected["notes"])
            if fields:
                from .operation_registry import _has_field, _field_value
                matches = matches and type(row.get("classId")) is int and row["classId"] == expected["class_id"]
                for field in fields:
                    value = _field_value(row, field["field"])
                    matches = matches and _has_field(row, field["field"]) and (
                        _reference_value(value) == field["value"] if field["field_kind"] == "reference"
                        else _scalar_matches(value, field["value"], field["metadata_type"]))
        else:
            matches = False
        observations.append((len(rows) == 1 and matches) if present else not rows)
    return {"object": identity, "field": "presence", "expected": present, "passed": all(observations)}


def _verified_snapshot(store: TransactionStore, transaction_id: str) -> Any:
    snapshot = store.load_snapshot(transaction_id)
    if snapshot.record.state != TransactionState.VERIFIED:
        raise ValueError("History expectation requires an owned successfully business-verified receipt")
    verification = next((event.get("details", {}).get("verification") for event in reversed(snapshot.events)
                         if event.get("event_type") == "verification_recorded"), None)
    if not isinstance(verification, Mapping) or verification.get("business_state_verified") is not True:
        raise ValueError("A schema-only receipt is not an observed history-effect expectation")
    return snapshot


def capture_history_binding(uri: str, store: TransactionStore, transaction_id: str | None, *, current_guard: Mapping[str, Any]) -> dict[str, Any]:
    if transaction_id is None:
        binding = {"contract": CONTRACT, "uri": uri, "version": current_guard.get("version"),
            "scope": "latest_project_history", "source_context_fingerprint": current_guard.get("context_fingerprint"),
            "source_receipt": None, "observations": []}
        return validate_history_binding(uri, str(binding["version"]), binding)
    snapshot = _verified_snapshot(store, transaction_id)
    artifact = snapshot.preview.artifact
    source_guard = artifact.get("project_guard", {})
    before_project, current_project = source_guard.get("project", {}), current_guard.get("project", {})
    if (source_guard.get("context_fingerprint") != current_guard.get("context_fingerprint")
        or str(before_project.get("id")).upper() != str(current_project.get("id")).upper()
        or canonical_project_path(before_project.get("path")) != canonical_project_path(current_project.get("path"))):
        raise ValueError("History expectation receipt belongs to another project or Wwise runtime")
    version = current_guard.get("version")
    binding = {"contract": CONTRACT, "uri": uri, "version": version, "scope": "latest_project_history",
        "source_context_fingerprint": source_guard["context_fingerprint"],
        "source_receipt": {"state_dir": str(store.state_dir), "transaction_id": transaction_id,
            "artifact_hash": snapshot.preview.artifact_hash, "event_sequence": snapshot.record.event_sequence,
            "last_event_hash": snapshot.record.last_event_hash},
        "observations": _snapshot_observations(snapshot)}
    validate_history_binding(uri, str(version), binding)
    return binding


def validate_history_binding(uri: str, version: str, value: Any) -> dict[str, Any]:
    keys = {"contract", "uri", "version", "scope", "source_context_fingerprint", "source_receipt", "observations"}
    if (uri not in HISTORY_VERSIONS or version not in HISTORY_VERSIONS[uri] or not isinstance(value, Mapping)
        or set(value) != keys or value.get("contract") != CONTRACT or value.get("uri") != uri
        or value.get("version") != version or value.get("scope") != "latest_project_history"):
        raise ValueError("History actions require their closed latest-project-history expectation proof")
    if len(canonical_json_bytes(value)) > MAX_BINDING_BYTES:
        raise ValueError("History expectation exceeds its bounded proof size")
    receipt = value["source_receipt"]
    if receipt is None:
        if value["observations"] != [] or not isinstance(value["source_context_fingerprint"], str) or not value["source_context_fingerprint"]:
            raise ValueError("Unobserved latest-history action must not contain fabricated effect expectations")
        return dict(value)
    if not isinstance(receipt, Mapping) or set(receipt) != {"state_dir", "transaction_id", "artifact_hash", "event_sequence", "last_event_hash"}:
        raise ValueError("History expectation requires one exact owned receipt identity")
    snapshot = _verified_snapshot(TransactionStore(Path(receipt["state_dir"])), receipt["transaction_id"])
    if (snapshot.preview.artifact_hash != receipt["artifact_hash"] or snapshot.record.last_event_hash != receipt["last_event_hash"]
        or snapshot.record.event_sequence != receipt["event_sequence"]
        or snapshot.preview.artifact.get("project_guard", {}).get("context_fingerprint") != value["source_context_fingerprint"]):
        raise ValueError("History expectation receipt changed after it was selected")
    observations = _snapshot_observations(snapshot)
    if not any(row["before"] != row["after"] for row in observations):
        raise ValueError("History expectation receipt has no observable transition")
    if not 1 <= len(observations) <= MAX_OBSERVATIONS or not lifecycle_snapshot_equal(value["observations"], observations):
        raise ValueError("History expected states differ from their immutable owned receipt")
    return dict(value)


def history_draft_reference(binding, *, store, context):
    """Keep deep source metadata in its journal, not ordinary Draft JSON values."""
    receipt = binding["source_receipt"]
    if receipt is not None and receipt["state_dir"] != str(store.state_dir):
        raise ValueError("History reference requires its current owned transaction store")
    validate_history_binding(binding["uri"], binding["version"], binding)
    return {"contract": REFERENCE_CONTRACT, "uri": binding["uri"],
        "version": binding["version"], "scope": binding["scope"],
        "source_context_fingerprint": binding["source_context_fingerprint"],
        "source_receipt": None if receipt is None else {key: value for key, value in receipt.items() if key != "state_dir"},
        "owner_state_sha256": canonical_sha256(str(store.state_dir)), "draft_context": context.as_binding_dict(),
        "binding_sha256": canonical_sha256(binding)}


def validate_history_reference(uri: str, version: str, reference: Any) -> dict[str, Any]:
    """Validate the internal compact shape without opening any referenced path."""
    keys = {"contract", "uri", "version", "scope", "source_context_fingerprint", "source_receipt",
        "owner_state_sha256", "draft_context", "binding_sha256"}
    if (uri not in HISTORY_VERSIONS or version not in HISTORY_VERSIONS[uri]
            or not isinstance(reference, Mapping) or set(reference) != keys
            or reference["contract"] != REFERENCE_CONTRACT or reference["uri"] != uri
            or reference["version"] != version or reference["scope"] != "latest_project_history"):
        raise ValueError("History requires its closed original-receipt reference")
    for key in ("owner_state_sha256", "binding_sha256", "source_context_fingerprint"):
        if not isinstance(reference[key], str) or not re.fullmatch(r"[0-9a-f]{64}", reference[key]):
            raise ValueError("History reference digest is malformed")
    context = BusinessContext.from_binding_dict(reference["draft_context"])
    if context.wwise_version != version:
        raise ValueError("History reference version differs from its Draft context")
    receipt = reference["source_receipt"]
    if receipt is not None:
        if (not isinstance(receipt, Mapping) or set(receipt) != {"transaction_id", "artifact_hash", "event_sequence", "last_event_hash"}
                or not isinstance(receipt["transaction_id"], str)
                or type(receipt["event_sequence"]) is not int or receipt["event_sequence"] < 1
                or any(not isinstance(receipt[key], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[key])
                    for key in ("artifact_hash", "last_event_hash"))):
            raise ValueError("History reference requires its exact original source receipt")
    return dict(reference)


def materialize_history_reference(uri, version, reference, *, store, context):
    """Resolve only the supplied owner Store, retaining the originally selected tail."""
    validate_history_reference(uri, version, reference)
    if (store is None or reference["owner_state_sha256"] != canonical_sha256(str(store.state_dir))
            or reference["draft_context"] != context.as_binding_dict()):
        raise ValueError("History reference differs from its owned Draft store or context")
    receipt = reference["source_receipt"]
    observations = []
    if receipt is not None:
        snapshot = _verified_snapshot(store, receipt["transaction_id"])
        if (snapshot.preview.artifact_hash != receipt["artifact_hash"]
                or snapshot.record.event_sequence != receipt["event_sequence"]
                or snapshot.record.last_event_hash != receipt["last_event_hash"]
                or snapshot.preview.artifact.get("project_guard", {}).get("context_fingerprint") != reference["source_context_fingerprint"]):
            raise ValueError("History reference source changed after selection")
        observations = _snapshot_observations(snapshot)
    binding = {"contract": CONTRACT, "uri": uri, "version": version, "scope": reference["scope"],
        "source_context_fingerprint": reference["source_context_fingerprint"],
        "source_receipt": None if receipt is None else {"state_dir": str(store.state_dir), **receipt},
        "observations": observations}
    if canonical_sha256(binding) != reference["binding_sha256"]:
        raise ValueError("History reference full proof differs from its immutable selection")
    return validate_history_binding(uri, version, binding)


def owned_history_resolver(store: TransactionStore, project_guard: Mapping[str, Any]):
    """Inject store authority from the owning Gateway, never from receipt input."""
    def resolve(uri: str, version: str, reference: Mapping[str, Any]):
        validate_history_reference(uri, version, reference)
        context = BusinessContext.from_binding_dict(reference["draft_context"])
        if (reference["source_context_fingerprint"] != project_guard.get("context_fingerprint")
                or context.project_id != project_guard.get("project", {}).get("id")
                or canonical_project_path(context.project_path) != canonical_project_path(project_guard.get("project", {}).get("path"))
                or context.wwise_version != project_guard.get("version")
                or context.wwise_build != project_guard.get("wwise", {}).get("version", {}).get("displayName")):
            raise ValueError("History reference differs from its owning project/runtime context")
        return materialize_history_reference(uri, version, reference, store=store, context=context)
    return resolve


def resolved_prepared_history(prepared: Mapping[str, Any], resolver):
    """Bind the exact request reference to both complete sealed proof copies."""
    request = prepared.get("request", {})
    arguments = request.get("arguments", {})
    reference = arguments.get("history_binding")
    if isinstance(reference, Mapping) and reference.get("contract") == REFERENCE_CONTRACT:
        if resolver is None:
            raise ValueError("History reference requires its owning Gateway resolver")
        binding = resolver(arguments.get("api"), request.get("version"), reference)
    else:
        binding = validate_history_binding(arguments.get("api"), request.get("version"), reference)
    if (not lifecycle_snapshot_equal(binding, prepared.get("pre_state", {}).get("history_binding"))
            or not lifecycle_snapshot_equal(binding, prepared.get("verification_plan", {}).get("history_binding"))):
        raise ValueError("History request reference differs from its complete sealed proof")
    return binding


def observe_history_state(binding: Mapping[str, Any], *, after_action: bool, read: Callable[..., Any]) -> dict[str, Any]:
    uri, version = binding["uri"], binding["version"]
    validate_history_binding(uri, version, binding)
    if binding["source_receipt"] is None:
        raise ValueError("Latest-history action has no selected effect expectation to observe")
    side = ("before" if uri.endswith(".undo") else "after") if after_action else ("after" if uri.endswith(".undo") else "before")
    observations = binding["observations"]
    readbacks, checks = [], []
    def retained_read(uri, args, options):
        record = {"uri": uri, "args": args, "options": options}
        readbacks.append(record)
        try:
            result = read(uri, args, options)
            record["result"] = dict(result) if isinstance(result, Mapping) else result
            return result
        except Exception as exc:
            record["error"] = _read_error(exc)
            raise HistoryObservationError("History observation read failed", readbacks) from exc
    try:
        groups = {}
        metadata_cache = {}
        for expected in observations:
            if expected.get("kind") == "existing_render_chain":
                from .render_history_observations import observe_chain
                checks.append(observe_chain(expected, side, read=retained_read))
                continue
            if expected.get("kind") == "creation_presence":
                fields = [item for item in observations if item.get("kind") == "creation_field"
                    and item["object_id"] == expected["object"]["id"]]
                checks.append(_observe_presence({**expected, "fields": fields}, expected[side], retained_read))
                continue
            if expected.get("kind") == "creation_field":
                continue
            groups.setdefault(expected.get("platform"), []).append(expected)
            if "field_info" in expected:
                object_id, field = expected["object_" + side]["id"], expected["field"]
                key = (object_id, field)
                if key not in metadata_cache:
                    names = [row.name for row in parse_property_and_reference_names_result(retained_read(NAMES, {"object": object_id}, {}))]
                    info = bind_get_property_info_result(retained_read(INFO, {"object": object_id, "property": field}, {}),
                        field_token=field, available_names=names)
                    if info.name != field or info.type != expected["metadata_type"]:
                        raise ValueError("History property metadata does not match its exact field/type")
                    metadata_cache[key] = info.as_dict(include_raw="raw" in expected["field_info"])
                if not lifecycle_snapshot_equal(metadata_cache[key], expected["field_info"]):
                    raise ValueError("History property metadata changed since the owned receipt")
        for platform, group in groups.items():
            ids = list(dict.fromkeys(row["object_" + side]["id"] for row in group))
            args = {"from": {"id": ids}}
            options = {"return": list(dict.fromkeys([*IDENTITY,
                *(["classId"] if any("class_id" in row for row in group) else []), *(row["field"] for row in group)])),
                **({"platform": platform} if platform is not None else {})}
            result = retained_read(GET, args, options)
            rows = result.get("return") if isinstance(result, Mapping) else None
            if not isinstance(rows, list) or len(rows) != len(ids):
                raise ValueError("History observation must return every exact object GUID once")
            found = {}
            for row in rows:
                identity = _identity(row)
                if identity["id"] not in ids or identity["id"] in found:
                    raise ValueError("History observation contains duplicate or unrelated GUIDs")
                found[identity["id"]] = row
            for expected in group:
                identity = expected["object_" + side]
                row = found[identity["id"]]
                field = expected["field"]
                from .operation_registry import _has_field, _field_value
                actual = _field_value(row, field)
                equal = (_has_field(row, field) and _reference_value(actual) == expected[side]
                    if expected.get("field_kind") == "reference" else
                    _scalar_matches(actual, expected[side], expected["metadata_type"])
                    if "metadata_type" in expected else isinstance(actual, str) and actual == expected[side])
                checks.append({"object": identity, "field": field, "platform": platform,
                    "expected": expected[side], "actual": actual, "passed": _identity(row) == identity and equal
                    and ("class_id" not in expected or type(row.get("classId")) is int and row["classId"] == expected["class_id"])})
        targets = {}
        for expected in observations:
            for target in expected.get("reference_targets_" + side, []):
                if target["id"] in targets and not lifecycle_snapshot_equal(targets[target["id"]], target):
                    raise ValueError("History reference targets disagree about their exact identities")
                targets[target["id"]] = target
        if targets:
            result = retained_read(GET, {"from": {"id": list(targets)}}, {"return": [*IDENTITY, "classId"]})
            rows = result.get("return") if isinstance(result, Mapping) else None
            if not isinstance(rows, list) or len(rows) != len(targets) or len({row.get("id") for row in rows}) != len(targets):
                raise ValueError("History reference targets require complete exact readback")
            for row in rows:
                identity = _identity(row)
                expected = targets.get(identity["id"])
                checks.append({"object": identity, "field": "reference_target_identity", "expected": expected,
                    "actual": row, "passed": expected is not None and _identity(expected) == identity
                    and type(row.get("classId")) is int and row["classId"] == expected["classId"]})
    except ValueError as exc:
        raise HistoryObservationError(str(exc), readbacks) from exc
    # Put actual failed reads before successful diagnostic bulk so bounded
    # public error projection cannot spend its node budget before the cause.
    failed = [row for row in readbacks if "error" in row]
    return {**({"failed_reads": failed} if failed else {}), "scope": "owned_receipt_observation_only", "stack_head_observed": False,
        "outside_scope_preservation_observed": False, "matches": all(row["passed"] for row in checks),
        "checks": checks, "readbacks": readbacks}


def history_summary(binding: Mapping[str, Any]) -> dict[str, Any]:
    receipt = binding["source_receipt"]
    observations = []
    existing_groups = {}
    render_fields = {(str(field["scope"].get("object_id")).upper(), field["field"], row["platform"])
        for row in binding["observations"] if row.get("kind") == "existing_render_chain"
        for field in row["chain"]["metadata"]}
    for row in binding["observations"]:
        if row.get("kind") == "existing_render_chain":
            from .render_history_observations import summary
            observations.append(summary(row))
            continue
        if row.get("kind") == "existing_field":
            if (row["object_before"]["id"], row["field"], row["platform"]) in render_fields:
                continue  # Already disclosed exactly once in the complete chain view.
            common = {key: row[key] for key in ("object_before", "object_after", "class_id", "platform")}
            key = canonical_sha256(common)
            if key not in existing_groups:
                existing_groups[key] = {"kind": "existing_fields", **common, "fields": []}
                observations.append(existing_groups[key])
            field = {name: value for name, value in row.items()
                if name not in {"kind", "object_before", "object_after", "class_id", "platform", "field_info"}}
            if "field_info" in row:
                field["metadata_bound"] = True
            if ("reference_targets_before" in field
                    and lifecycle_snapshot_equal(field["reference_targets_before"], field["reference_targets_after"])):
                field["reference_targets_before_and_after"] = field.pop("reference_targets_before")
                del field["reference_targets_after"]
            existing_groups[key]["fields"].append(field)
            continue
        if row.get("kind") == "creation_field":
            continue
        compact = {**{key: value for key, value in row.items() if key != "field_info"},
            **({"metadata_bound": True} if "field_info" in row else {})}
        if row.get("kind") == "creation_presence":
            fields = [field for field in binding["observations"] if field.get("kind") == "creation_field"
                and field["object_id"] == row["object"]["id"]]
            if fields:
                compact["fields"] = [{**{key: value for key, value in field.items()
                    if key not in {"kind", "object_id", "before", "after", "field_info"}},
                    "metadata_bound": True} for field in fields]
        observations.append(compact)
    return {"scope": "latest_project_history", "action": binding["uri"].rsplit(".", 1)[-1],
        "expectation_receipt": receipt["transaction_id"] if receipt else None,
        "effect_expectation": "owned_receipt_scoped_state" if receipt else "none",
        "receipt_role": "scoped_effect_expectation_only; does_not_select_a_native_history_entry" if receipt else "none",
        "verification_boundary": "owned_receipt_scoped_state_only" if receipt else "result_schema_only; effect_and_preservation_unobserved",
        "stack_head_observed": False, "outside_scope_preservation_observed": False,
        "automatic_retry": False, "automatic_compensation": False,
        "expected_observations": observations}

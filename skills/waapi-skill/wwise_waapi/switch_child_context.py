"""Exact Switch-child property targets, independent of optional native type."""
from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import canonical_sha256

CONTRACT = "waapi-skill.switch-child-context/v1"
COMMAND = "draft-bind-switch-child-context"
GET = "ak.wwise.core.object.get"
FIELDS = ("id", "name", "type", "path", "classId", "owner", "parent", "notes", "switchContainerChildContext")


def _guid(value):
    import uuid
    if not isinstance(value, str) or not value.startswith("{") or not value.endswith("}") or uuid.UUID(value).int == 0:
        raise ValueError("Context proof needs a nonzero canonical GUID")
    return "{" + str(uuid.UUID(value)).upper() + "}"


def _edge(row, field):
    value = row.get(field)
    if not isinstance(value, Mapping):
        raise ValueError("Context proof lacks its actual " + field + " edge")
    return _guid(value.get("id"))


def _exact(read, ids):
    result = read(GET, {"from": {"id": ids}}, {"return": list(FIELDS)})
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ValueError("Context proof must return each requested GUID once")
    found = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Context proof returned a malformed row")
        key = _guid(row.get("id"))
        if key not in ids or key in found:
            raise ValueError("Context proof has duplicate or extra rows")
        found[key] = dict(row)
    return found


def _relationship_source(version):
    from .schema_inventory import load_definition_graph
    graph = load_definition_graph(version)
    document = "waapi_definitions.json"
    shape = graph.documents[document]["definitions"]["objectReturn"]
    properties = shape["properties"]
    names = ("switchContainerChildContext", "owner", "parent", "classId", "type")
    selected = {name: properties[name] for name in names}
    if selected["switchContainerChildContext"].get("type") != "object":
        raise ValueError("Matching reflection lacks the child context relationship")
    return {"version": version, "wwise_build": graph.wwise_build, "document": document,
        "pointer": "/definitions/objectReturn", "members": list(names),
        "sha256": canonical_sha256({"properties": selected, "required": shape.get("required", [])})}


def capture(version, owner_id, child_id, *, read, context_id=None):
    from .business_declarations import normalize_live_object_identity
    from .documented_list_fields import load_catalog
    owner_id, child_id = _guid(owner_id), _guid(child_id)
    if owner_id == child_id:
        raise ValueError("Owner and child must be distinct")
    ids = [owner_id, child_id, *([_guid(context_id)] if context_id else [])]
    if len(set(ids)) != len(ids):
        raise ValueError("Context, owner and child must be distinct")
    rows = _exact(read, ids)
    owner, child = rows[owner_id], rows[child_id]
    normalize_live_object_identity(owner)
    normalize_live_object_identity(child)
    if owner.get("type") != "SwitchContainer" or _edge(child, "parent") != owner_id:
        raise ValueError("The exact child must belong directly to the Switch Container")
    derived = _edge(child, "switchContainerChildContext")
    if derived in {owner_id, child_id} or context_id and derived != _guid(context_id):
        raise ValueError("The child context GUID changed")
    if derived not in rows:
        rows.update(_exact(read, [derived]))
    context = rows[derived]
    if (_edge(context, "owner") != owner_id or context.get("name") != ""
            or not isinstance(context.get("path"), str) or not context["path"].startswith("\\")):
        raise ValueError("The context needs its actual owner and display identity")
    if "type" in context and context["type"] != "ObjectSettingAssociation":
        raise ValueError("Unexpected native context type; no class/type alias is inferred")
    catalog = load_catalog(version)
    sources = [next(row for row in catalog["classes"] if row["name"] == token)
        for token in ("SwitchContainer", "ObjectSettingAssoc")]
    type_result = read("ak.wwise.core.object.getTypes", {}, {})
    actual_types = type_result.get("return") if isinstance(type_result, Mapping) else None
    if not isinstance(actual_types, list) or len(actual_types) > 2048:
        raise ValueError("Live class catalog is malformed")
    classes = []
    for row, source in zip((owner, context), sources):
        if type(row.get("classId")) is not int or row["classId"] != source["class_id"]:
            raise ValueError("Context or owner class differs from its matching source")
        matches = [t for t in actual_types if isinstance(t, Mapping) and t.get("classId") == source["class_id"]]
        if len(matches) != 1 or type(matches[0].get("classId")) is not int or matches[0].get("name") != source["name"] or matches[0].get("type") != "WObject":
            raise ValueError("Live exact class identity differs from the pinned source")
        classes.append(dict(matches[0]))
    return {"contract": CONTRACT, "version": version, "owner_id": owner_id, "child_id": child_id,
        "context_id": derived, "relationship_source": _relationship_source(version), "catalog_sha256": catalog["catalog_sha256"],
        "sources": [{key: row[key] for key in ("name", "class_id", "source_member", "source_sha256")} for row in sources],
        "classes": classes, "rows": {"owner": owner, "child": child, "context": context}}


def validate(proof, *, read):
    from .operation_registry import _native_snapshot_equal
    if not isinstance(proof, Mapping) or proof.get("contract") != CONTRACT:
        raise ValueError("Missing immutable Switch-child context proof; bind and Preview again")
    actual = capture(proof["version"], proof["owner_id"], proof["child_id"], read=read, context_id=proof["context_id"])
    if not _native_snapshot_equal(actual, proof):
        raise ValueError("Switch-child context identity, relationship, source or class drifted")
    return actual


def assertions(pre_state, *, read):
    proof = pre_state.get("switch_child_context") if isinstance(pre_state, Mapping) else None
    if proof is None:
        return []
    try:
        actual = validate(proof, read=read)
        passed = True
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        actual, passed = {"error": str(exc)}, False
    return [{"name": "Switch-child context identity and both ownership edges remain bound",
        "passed": passed, "evidence": {"expected": proof, "actual": actual}}]


@dataclass(frozen=True)
class BoundContext:
    handle: str
    context: Any
    proof: Mapping[str, Any]
    binding_digest: str

    @property
    def object_id(self):
        return self.proof["context_id"]

    def as_dict(self):
        return {"contract": CONTRACT, "handle": self.handle, "proof": dict(self.proof), "binding_digest": self.binding_digest}


def restore(payload, context):
    if not isinstance(payload, Mapping) or set(payload) != {"contract", "handle", "proof", "binding_digest"} or payload["contract"] != CONTRACT:
        raise ValueError("Malformed tagged context handle")
    proof = payload["proof"]
    if not isinstance(proof, Mapping) or proof.get("contract") != CONTRACT or proof.get("version") != context.wwise_version:
        raise ValueError("Tagged context proof differs from its version binding")
    import re
    digest = canonical_sha256({"context": context.as_binding_dict(), "proof": proof})
    if payload["binding_digest"] != digest or not isinstance(payload["handle"], str) or re.fullmatch(r"bsc1-[0-9a-f]{32}", payload["handle"]) is None:
        raise ValueError("Tagged context binding digest differs")
    return BoundContext(payload["handle"], context, proof, digest)

"""Exact review proposal, deliberately not an acceptance requirements document."""
from __future__ import annotations

from copy import deepcopy

from tests.maintenance.branch_coverage_audit import digest


def _kind(native_type):
    token = native_type.lower()
    if token == "bool":
        return "boolean"
    if "int" in token:
        return "integer"
    if token in {"real32", "real64"}:
        return "float"
    if token == "string":
        return "string"
    return "unreviewed:" + native_type


def _signature(group):
    metadata, field = group["model"]["metadata"], group["field"]
    # Keep every edge. Names are parameters, never an excuse to drop topology.
    roles = {field: "selected", **{name: "controller-" + str(index) for index, name in
             enumerate(sorted(name for name in metadata if name != field))}}
    graph, comparison_kinds, families = [], set(), set()
    for name, info in metadata.items():
        predicates = []
        for dependency in info.get("dependencies", []):
            restriction = dependency["conditions"][0]["restriction"]
            controller_type = metadata[dependency["property"]]["type"]
            comparison_kinds.add(_kind(controller_type))
            families.add(restriction["type"])
            predicates.append({"action": dependency["action"], "context": dependency["context"],
                "operator": restriction["type"], "controller_role": roles[dependency["property"]], "controller_source_type": controller_type,
                "enum_cardinality": ("single" if len(restriction["values"]) == 1 else "multiple")
                                    if restriction["type"] == "enum" else None})
        domain = info.get("restriction")
        own_domain = ({"operator": domain["type"],
                       "enum_cardinality": len(domain["values"]) if domain["type"] == "enum" else None}
                      if domain else None)
        graph.append({"role": roles[name], "source_type": info["type"], "own_value_domain": own_domain,
                      "predicates": sorted(predicates, key=digest)})
    actions = {d["action"] for d in metadata[field].get("dependencies", [])}
    return {"version": group["version"], "build": group["build"], "host": "wwise-console",
            "context": "Self", "operation_mode": "existing-object", "public_operation": "object.setProperty",
            "platform_scope": "default_only_no_cross_platform_credit",
            "dependent_source_type": metadata[field]["type"], "dependent_value_kind": _kind(metadata[field]["type"]),
            "source_predicate_types": sorted({m["source_predicate_type"] for m in group["members"]}),
            "predicate_families": sorted(families), "controller_comparison_kinds": sorted(comparison_kinds),
            "combined_show_enable": {"Show", "Enable"} <= actions,
            "recursive_controller_conditions": any(info.get("dependencies") for name, info in metadata.items() if name != field),
            "parameterized_graph": sorted(graph, key=digest)}


def requirements_proposal(plan):
    """Retain every ID and every missing fact; never infer witness equivalence."""
    members, mechanisms, live_metadata = {}, {}, {}
    for group in plan["groups"]:
        signature = _signature(group)
        key = "self-scalar-" + digest(signature)
        mechanism = mechanisms.setdefault(key, {"signature": signature, "review_status": "pending",
            "existing_native_witness_ids": [], "planned_native_witness_id": "planned-native:" + key,
            "native_witness_state": "missing", "exact_member_ids": [],
            "proposed_parameterization": ["field/controller tokens", "literal enum values", "range bounds"],
            "equivalence_justification": {
                "program_basis": "Each exact member must have its own actual public behavioral workflow, field metadata and verification; disclosure alone is insufficient.",
                "native_basis": "Missing. Proposed graph/type/context/host/build equality is only a review key. Require an original effect witness and explicit exact-member linkage before reuse.",
                "inheritance": "none"}})
        live_key = "effective-metadata:" + group["id"]
        live_metadata[live_key] = {"version": group["version"], "build": group["build"], "host": "wwise-console",
            "source_parent_key": group["source_parent_key"], "source_class": deepcopy(group["class"]),
            "source_receiver": deepcopy(group["receiver"]), "field": group["field"],
            "dependent_source_type": group["model"]["metadata"][group["field"]]["type"],
            "controller_types": {name: info["type"] for name, info in sorted(group["model"]["metadata"].items()) if name != group["field"]},
            "effective_instance_metadata": "unobserved", "matching_state": "unresolved",
            "required_facts": ["exact existing instance identity and actual plugin/class scope",
                "canonical scoped native field token (preserve absent native name separately)",
                "complete bounded effective field metadata and typed value kind",
                "all sibling and recursive dependencies, values, restrictions and optional presence",
                "exact scoped controller values and native enabled result"],
            "class_only_metadata_is_insufficient": True}
        for member in group["members"]:
            identity = member["id"]
            if identity in members:
                raise ValueError("duplicate exact scalar requirements member")
            mechanism["exact_member_ids"].append(identity)
            members[identity] = {"shape_sha256": member["shape_sha256"], "source_file_sha256": member["source_file_sha256"],
                "source_attributes": deepcopy(member["source_attributes"]), "source_predicate_type": member["source_predicate_type"],
                "source_value": deepcopy(member["source_value"]), "mechanism_key": key, "live_metadata_key": live_key,
                "required_categories": ["program", "live_metadata", "native"],
                "native_witness_ids": [mechanism["planned_native_witness_id"]],
                "disclosure_pointer": member["observation_pointer"],
                "behavioral_workflow_ids": deepcopy(member.get("behavioral_workflow_ids", [])),
                "program_behavior_state": "unobserved", "equivalence_review": "unreviewed_no_inheritance",
                "state": "unresolved"}
    for row in plan["unresolved"]:
        if row["id"] in members:
            raise ValueError("unresolved source member duplicated by a mechanism")
        members[row["id"]] = {"shape_sha256": row["shape_sha256"], "mechanism_key": None, "live_metadata_key": None,
            "native_witness_ids": [], "required_categories": None, "state": "unresolved", "reason": row["reason"],
            "equivalence_review": "unreviewed_no_inheritance"}
    return {"contract": "waapi-skill.condition-scalar-equivalence-proposal/v1", "review_status": "pending",
            "coverage_credit": "none", "scope": "exact_self_scalar_enable_source_members_only",
            "source_plan_sha256": digest(plan), "members": members, "mechanisms": mechanisms,
            "live_metadata_requirements": live_metadata}


PROGRAM_REVIEW_PATH = 'tests/fixtures/metadata-conditions/self-scalar-program-review.json.gz'
PROGRAM_REVIEW_SHA256 = 'c5635681ac5b911c20ee1f2f18c1d5d6667dc6e0661fa1ea37d7b003c1ab2ac5'


def program_review_document(plan):
    """Exact program collection policy; every native obligation stays required."""
    proposal = requirements_proposal(plan)
    return {'contract': 'waapi-skill.condition-scalar-program-review/v1',
        'program_collection_review': 'approved', 'native_equivalence_review': 'pending',
        'reviewed_reason': 'Maintainer approved exact original product program collection while effective live metadata and native mechanism/equivalence remain mandatory and unresolved; this grants no completion or native waiver.',
        'source_plan_sha256': digest(plan), 'proposal_sha256': digest(proposal),
        'requirements': {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {
            identity: {'native_shape_sha256': member['shape_sha256'], 'categories': ['program', 'live_metadata', 'native'],
                'reason': 'Exact Self scalar source member requires original public behavioral program evidence, matching effective live metadata and reviewed native mechanism effect linkage.',
                'mechanism_key': member['mechanism_key'], 'native_witness_ids': member['native_witness_ids'],
                'equivalence_review': 'pending', **({'unresolved_reason': member['reason']} if member.get('reason') else {})}
            for identity, member in proposal['members'].items()}}}


def load_program_review(root):
    import gzip
    import hashlib
    import json
    raw = (root / PROGRAM_REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROGRAM_REVIEW_SHA256:
        raise ValueError('reviewed program requirements source seal differs')
    return json.loads(gzip.decompress(raw))


def validate_program_review(root, plan, review):
    """Admission is exact program-only approval, never a caller category waiver."""
    if digest(review) != digest(load_program_review(root)) or digest(review) != digest(program_review_document(plan)):
        raise ValueError('reviewed requirements, full source plan or unresolved members differ')

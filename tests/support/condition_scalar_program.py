"""Original exact scalar program batches; requirements are reviewed separately."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from tests.maintenance.branch_audit_completion import pointer_value
from tests.support.condition_branch_evidence import prepare_condition_capture, validate_condition_frozen_source
from tests.maintenance import branch_coverage_audit as audit
from tests.support import condition_scalar_requirements as requirements


_SOURCES = ["tests/support/condition_scalar_requirements.py", requirements.PROGRAM_REVIEW_PATH, "tests/support/condition_scalar_program.py", "tests/support/condition_scalar_batch.py",
            "tests/maintenance/condition_parent_sources.py", "tests/unit/test_condition_scalar_program.py",
            "tests/unit/test_scalar_condition_product_gateway.py", "tests/unit/test_condition_scalar_batch_evidence.py",
            "tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz"]
_SOURCES += [f"tests/fixtures/gameparameter-metadata/{version}.json" for version in audit.VERSIONS]


def _encoded(document):
    return (json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _write(path, document):
    path.write_bytes(_encoded(document))
    return {"artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _exact(observed, expected):
    return type(observed) is type(expected) and audit.digest(observed) == audit.digest(expected)


def prepare_program_batch(root: Path, nodeids: list[str], plan: dict, inventory: dict, *, scope_kind="controlled",
                          reviewed_requirements=None, node_groups=None) -> dict:
    """Use the caller's one frozen inventory; never rebuild it per field."""
    if not nodeids or len(set(nodeids)) != len(nodeids) or scope_kind not in {"product", "controlled"}:
        raise ValueError("exact selected original nodes required")
    if scope_kind == "product":
        if reviewed_requirements is None:
            raise ValueError("product program requires reviewed requirements; native-effect linkage remains required")
        requirements.validate_program_review(audit.ROOT, plan, reviewed_requirements)
        if not isinstance(node_groups, dict) or set(node_groups) != set(nodeids):
            raise ValueError("exact predeclared original node roster required")
    all_groups = {group["id"]: group for group in plan["groups"]}
    if len(all_groups) != len(plan["groups"]):
        raise ValueError("duplicate original source group")
    if node_groups is not None:
        selected = [identity for node in nodeids for identity in node_groups.get(node, [])]
        if (set(node_groups) != set(nodeids) or not selected or any(not node_groups[node] for node in nodeids)
                or len(selected) != len(set(selected))
                or any(identity not in all_groups for identity in selected)):
            raise ValueError("exact node/group roster has missing, extra or duplicate source groups")
    else:
        selected = list(all_groups)
    capture = prepare_condition_capture(root, nodeids[0], create_output=False, inventory=inventory)
    branches = {b["id"]: b for b in inventory["native_coverage"]["obligations"]}
    if scope_kind == "product":
        for identity, policy in reviewed_requirements["requirements"]["branches"].items():
            if identity not in branches or branches[identity]["shape_sha256"] != policy["native_shape_sha256"]:
                raise ValueError("reviewed full source member missing from inventory")
    for group in plan["groups"]:
        for member in group["members"]:
            branch = branches[member["id"]]
            if (branch["owner_issue"] != 177 or branch["shape_sha256"] != member["shape_sha256"]
                    or branch["source_file_sha256"] != member["source_file_sha256"]):
                raise ValueError("exact scalar source member differs from frozen inventory")
    capture["relevant_sources"].update({name: hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() for name in _SOURCES})
    root.mkdir(parents=True, exist_ok=False)
    capture.update(scope_kind=scope_kind, nodeids=list(nodeids), plan=deepcopy(plan), reports={}, observations={},
                   branches=branches, routes={r["id"]: r for r in inventory["routes"]},
                   selected_group_ids=selected, node_groups=deepcopy(node_groups),
                   reviewed_requirements=deepcopy(reviewed_requirements))
    if reviewed_requirements is not None:
        capture["review_artifact"] = _write(root / "reviewed-requirements.json", reviewed_requirements)
        capture["requirements_artifact"] = _write(root / "requirements.json", reviewed_requirements["requirements"])
    capture["plan_artifact"] = _write(root / "plan.json", plan)
    capture["sources_artifact"] = _write(root / "sources.json", {
        "candidate_sha256": capture["candidate_sha256"], "git_candidate": capture["git_candidate"],
        "relevant_sources": capture["relevant_sources"]})
    capture["batch_plan_artifact"] = _write(root / "batch-plan.json", _batch_header(capture))
    return capture


def _batch_header(capture):
    return {"scope_kind": capture["scope_kind"], "nodeids": capture["nodeids"],
        "node_groups": capture["node_groups"], "selected_group_ids": capture["selected_group_ids"],
        "plan_sha256": audit.digest(capture["plan"]),
        "reviewed_requirements_sha256": audit.digest(capture["reviewed_requirements"])}


def _validate_observation(group, observed, before_values):
    model, field = group["model"], group["field"]
    if not _exact(observed["observations"]["metadata"], model["metadata"][field]):
        raise ValueError("original public metadata differs from predeclared source model")
    before, after = observed["observations"]["before"], observed["observations"]["after"]
    if 'source_receiver' in model and (
            before.get('type') != model['source_receiver']['native_type']
            or after.get('type') != model['source_receiver']['native_type']
            or not _exact(observed.get('input_fact_provenance'), model['provenance'])):
        raise ValueError('original exact source receiver or program-model provenance differs')
    if any(type(before.get(k)) is not type(v) or before.get(k) != v for k, v in before_values.items()):
        raise ValueError("original prerequisite values differ from predeclared source model")
    if not _exact(after, {**before, field: model["requested"]}):
        raise ValueError("original field change or prerequisite preservation differs")
    call = observed["native_call"]
    if (call["uri"] != "ak.wwise.core.object.setProperty" or not _exact(call["args"], {
            "object": before["id"], "property": field, "value": model["requested"]})):
        raise ValueError("exact selected field dispatch differs")
    gateway = observed["gateway"]
    if (gateway["exit_code"] != 0 or gateway["payload"].get("ok") is not True
            or gateway["payload"].get("verified") is not True or not gateway["argv"]):
        raise ValueError("original successful Gateway verification missing")
    for member in group["members"]:
        value = pointer_value(observed, member["observation_pointer"])
        if not _exact(value, member["expected"]):
            raise ValueError("exact source alternative observation differs")


def _validate_group(group, bundle):
    if 'failure' in bundle:
        raise ValueError('failed original group cannot publish behavioral evidence')
    flows = {flow["id"]: flow for flow in group["workflows"]}
    if set(bundle.get("workflows", {})) != set(flows):
        raise ValueError("missing or extra original behavioral workflows; metadata disclosure is insufficient")
    controls = {control["id"]: control for control in group["negative_controls"]}
    if set(bundle.get("negative_controls", {})) != set(controls):
        raise ValueError("missing or extra original outside-value controls")
    for identity, flow in flows.items():
        _validate_observation(group, bundle["workflows"][identity], flow["before"])
    for member in group["members"]:
        selected = member["behavioral_workflow_ids"]
        if not selected or any(identity not in flows for identity in selected):
            raise ValueError("exact member behavioral workflow linkage missing")
        controller = member["source_attributes"]["Name"]
        values = [flows[identity]["before"][controller] for identity in selected]
        alternative = member["alternative"]
        if "/value/" in alternative and (len(values) != 1 or not _exact(values[0], member["expected"])):
            raise ValueError("enum value behavior does not use that actual controller value")
        if alternative.startswith("Enumeration/") and "/value/" not in alternative:
            if {audit.digest(v) for v in values} != {audit.digest(v["value"]) for v in member["expected"]["values"]}:
                raise ValueError("enumeration behavior does not exercise every declared choice")
        if alternative.startswith("Range/"):
            low, high = member["expected"]["min"], member["expected"]["max"]
            middle = (low + high) // 2 if type(low) is int and type(high) is int else (low + high) / 2
            if {audit.digest(v) for v in values} != {audit.digest(v) for v in (low, middle, high)}:
                raise ValueError("range behavior lacks endpoints or representative interior")
            if not any(control["source_member"] == member["id"] for control in controls.values()):
                raise ValueError("range behavior lacks a source-bounded outside-value control")
    for identity, control in controls.items():
        observed = bundle["negative_controls"][identity]
        gateway = observed["gateway"]
        payload = gateway["payload"]
        codes = [payload.get("error_code"), *(issue.get("error_code") for issue in payload.get("details", {}).get("issues", []))]
        if (gateway["exit_code"] != 2 or control["expected_error_code"] not in codes
                or observed["mutation_calls"] != [] or not _exact(observed["before"], observed["after"])
                or any(not _exact(observed["before"].get(k), value) for k, value in control["before"].items())):
            raise ValueError("outside-value control lacks truthful public refusal and zero mutation")


def finish_program_node(capture: dict, nodeid: str, reports: dict, observations: dict) -> None:
    """Seal raw observations now; publish only after every actual teardown report."""
    root = capture["root"]
    if not _exact(json.loads((root / "batch-plan.json").read_text()), _batch_header(capture)):
        raise ValueError("original predeclared source/plan/node roster changed")
    if nodeid not in capture["nodeids"] or nodeid in capture["reports"]:
        raise ValueError("wrong or repeated original node")
    passed = all(reports.get(phase) == "passed" for phase in ("setup", "call", "teardown"))
    if capture["node_groups"] is not None:
        expected = set(capture["node_groups"][nodeid])
        if set(observations) - expected or (passed and set(observations) != expected):
            raise ValueError("original node observations differ from the exact predeclared group roster")
    if set(capture["observations"]) & set(observations):
        raise ValueError("another original node already owns this exact field observation")
    capture["reports"][nodeid] = deepcopy(reports)
    capture["observations"].update({key: {"nodeid": nodeid, "observed": deepcopy(value)} for key, value in observations.items()})
    _write(root / f"observations-{len(capture['reports'])}.json", {"nodeid": nodeid, "reports": reports, "observations": observations})
    if set(capture["reports"]) != set(capture["nodeids"]):
        return
    if not all(capture["reports"][node].get(phase) == "passed"
               for node in capture["nodeids"] for phase in ("setup", "call", "teardown")):
        _write(root / "outcome.json", {"outcome": "FAIL", "reports": capture["reports"], "acceptance": "withheld"})
        return
    groups = {g["id"]: g for g in capture["plan"]["groups"] if g["id"] in capture["selected_group_ids"]}
    if set(capture["observations"]) != set(groups):
        raise ValueError("missing or extra original field observations")
    validate_condition_frozen_source(capture)
    if audit.digest(json.loads((root / "plan.json").read_text())) != audit.digest(capture["plan"]):
        raise ValueError("predeclared original plan changed")
    if capture["scope_kind"] == "product":
        requirements.validate_program_review(audit.ROOT, capture["plan"], capture["reviewed_requirements"])
        if (not _exact(json.loads((root / "reviewed-requirements.json").read_text()), capture["reviewed_requirements"])
                or not _exact(json.loads((root / "requirements.json").read_text()), capture["reviewed_requirements"]["requirements"])):
            raise ValueError("original reviewed requirements artifact changed")
    for identity, group in groups.items():
        _validate_group(group, capture["observations"][identity]["observed"])
    destination = root / "published"
    if destination.exists():
        raise ValueError("original program publication is immutable")
    stage = Path(tempfile.mkdtemp(prefix=".program-pending-", dir=root))
    bindings = {}
    seal = {"contract": "waapi-skill.condition-scalar-program-batch/v1", "outcome": "PASS",
            "candidate_sha256": capture["candidate_sha256"], "scope_kind": capture["scope_kind"],
            "batch_plan_sha256": capture["batch_plan_artifact"]["sha256"],
            "plan_sha256": capture["plan_artifact"]["sha256"], "sources_sha256": capture["sources_artifact"]["sha256"],
            "reports": capture["reports"], "node_groups": capture["node_groups"], "groups": sorted(groups),
            "exact_members": sorted(m["id"] for g in groups.values() for m in g["members"])}
    if capture["reviewed_requirements"] is not None:
        seal["reviewed_requirements_sha256"] = capture["review_artifact"]["sha256"]
        seal["requirements_sha256"] = capture["requirements_artifact"]["sha256"]
    seal_path = root / "batch-final.json"
    seal_descriptor = {"artifact": str(seal_path), "sha256": hashlib.sha256(_encoded(seal)).hexdigest()}
    relevant = ["skills/waapi-skill/scripts/run.py", "skills/waapi-skill/scripts/gateway.py",
                "skills/waapi-skill/wwise_waapi/operation_registry.py",
                "skills/waapi-skill/wwise_waapi/metadata_restrictions.py", *_SOURCES]
    for identity, group in groups.items():
        entry = capture["observations"][identity]
        bundle = entry["observed"]
        raw = _write(root / ("observed-" + identity + ".json"), entry)
        for flow_id in sorted({member["behavioral_workflow_ids"][0] for member in group["members"]}):
            _publish_flow(stage, destination, capture, group, entry, bundle, flow_id, raw, seal_descriptor, relevant, bindings)
    if capture["reviewed_requirements"] is not None:
        _write(stage / "requirements.json", capture["reviewed_requirements"]["requirements"])
    _write(stage / "bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": bindings})
    _write(stage / "outcome.json", {"outcome": "PASS", "reports": capture["reports"],
        "functional_coverage": "program_only_effective_native_metadata_and_requirements_unverified",
        "requirements_state": "program_collection_approved_native_equivalence_pending" if capture["scope_kind"] == "product" else "pending_review", "exact_observed_members": len(bindings)})
    stage.rename(destination)
    validate_condition_frozen_source(capture)
    pending = root / ".batch-final.pending"
    pending.write_bytes(_encoded(seal))
    pending.rename(seal_path)


def _publish_flow(stage, destination, capture, group, entry, bundle, flow_id, raw, seal_descriptor, relevant, bindings):
    observed = bundle["workflows"][flow_id]
    members = [m for m in group["members"] if m["behavioral_workflow_ids"][0] == flow_id]
    summaries = {identity: {"before": value["observations"]["before"], "after": value["observations"]["after"],
        "gateway_argv": value["gateway"]["argv"], "verified": value["gateway"]["payload"]["verified"],
        "agent_result": value["gateway"]["payload"]["agent_result"], "native_call": value["native_call"]}
        for identity, value in bundle["workflows"].items()}
    record = {"candidate_sha256": capture["candidate_sha256"], "git_candidate": capture["git_candidate"],
              "scope_kind": capture["scope_kind"], "evidence_kind": "injected_client_program",
              "invocation": {"phase": "final", "outcome": "PASS", "node_outcomes": [
                  {"nodeid": node, "outcome": "PASS"} for node in capture["nodeids"]]},
              **deepcopy(observed), "branch_assertions": {},
              "behavioral_workflows": deepcopy(summaries), "negative_controls": deepcopy(bundle["negative_controls"]),
              "artifacts": [capture["plan_artifact"], capture["sources_artifact"], capture["batch_plan_artifact"], raw, seal_descriptor]}
    if capture["reviewed_requirements"] is not None:
        record["artifacts"].extend([capture["review_artifact"], capture["requirements_artifact"]])
    route = capture["routes"][group["version"] + "|function|ak.wwise.core.object.setProperty"]
    for member in members:
        branch = capture["branches"][member["id"]]
        checks = [{"pointer": member["observation_pointer"], "equals": deepcopy(member["expected"])},
                  {"pointer": "/gateway/payload/agent_result", "equals": deepcopy(observed["gateway"]["payload"]["agent_result"])},
                  {"pointer": "/observations/before", "equals": deepcopy(observed["observations"]["before"])},
                  {"pointer": "/observations/after", "equals": deepcopy(observed["observations"]["after"])}]
        controller = audit.escape(member["source_attributes"]["Name"])
        field = audit.escape(group["field"])
        for identity in member["behavioral_workflow_ids"]:
            summary = summaries[identity]
            checks.extend([
                {"pointer": f"/behavioral_workflows/{identity}/before/{controller}", "equals": summary["before"][member["source_attributes"]["Name"]]},
                {"pointer": f"/behavioral_workflows/{identity}/after/{field}", "equals": summary["after"][group["field"]]},
                {"pointer": f"/behavioral_workflows/{identity}/verified", "equals": True},
                {"pointer": f"/behavioral_workflows/{identity}/agent_result", "equals": deepcopy(summary["agent_result"])}])
        for identity, control in bundle["negative_controls"].items():
            checks.append({"pointer": f"/negative_controls/{identity}", "equals": deepcopy(control)})
        record["branch_assertions"][branch["id"]] = {"native_shape_sha256": branch["shape_sha256"], "native_route": None, "checks": checks}
        bindings[branch["id"]] = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
            "public_route": route["id"], "public_route_sha256": audit.digest(route),
            "input": {"gateway_argv": observed["gateway"]["argv"], "selector": group["source_parent_key"] + ":" + flow_id},
            **{key: {"source": source, "selector": branch["pointer"]} for key, source in {
                "construction": "skills/waapi-skill/wwise_waapi/operation_registry.py#_apply_reference_activation_dependencies",
                "validation": "skills/waapi-skill/wwise_waapi/metadata_restrictions.py#condition_restriction",
                "verifier": "skills/waapi-skill/wwise_waapi/operation_registry.py#verify_prepared_operation"}.items()},
            "observation_pointer": member["observation_pointer"], "gateway_observation_pointer": "/gateway/payload/agent_result",
            "native_hosts": ["wwise-console"], "relevant_sources": relevant, "evidence": {}}
    path = stage / (group["id"] + "-" + flow_id + ".json")
    descriptor = _write(path, record)
    descriptor["artifact"] = str(destination / path.name)
    for member in members:
        bindings[member["id"]]["evidence"]["program"] = {**descriptor, "nodeid": entry["nodeid"]}

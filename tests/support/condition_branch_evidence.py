"""Exact product-branch receipts for the existing condition Gateway test lane."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from tests.maintenance import branch_coverage_audit as audit


SHOW_BRANCH_ID = (
    "2025.1|installed|2025.1.7.9143|condition|existing-object|WObjects/WObjects.xml|"
    "PluginModule/WwiseObject[GameParameter]/Properties/Property[SlewRateUp]/Dependencies/142/condition"
)


def prepare_condition_capture(root: Path, nodeid: str) -> dict:
    """Freeze exact source and branch facts before the public workflow executes."""
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    branch = next(row for row in inventory["native_coverage"]["obligations"] if row["id"] == SHOW_BRANCH_ID)
    assert branch["owner_issue"] == 177 and branch["business_dimensions"]["operation_mode"] == "existing-object"
    relevant = [
        str(path.relative_to(audit.ROOT))
        for directory in ("scripts", "wwise_waapi", "resources", "references")
        for path in sorted((audit.ROOT / "skills/waapi-skill" / directory).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".json", ".md"}
    ]
    relevant.extend([
        "skills/waapi-skill/SKILL.md", "tests/support/condition_branch_evidence.py",
        "tests/unit/test_conditional_reference_gateway.py",
        "tests/destructive/test_condition_visibility_gateway.py",
        "tests/destructive/support/exact_real_evidence.py",
        "tests/destructive/support/category_evidence.py",
        "tests/conftest.py", "tests/support/exact_evidence_finalization.py",
        "tests/maintenance/branch_audit_completion.py", "tests/maintenance/branch_coverage_audit.py",
        "docs/branch-coverage-condition-sources.json",
    ])
    sources = {name: hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() for name in sorted(set(relevant))}
    return {"root": root, "nodeid": nodeid, "branch": branch,
            "public": next(row for row in inventory["routes"] if row["id"] == "2025.1|function|ak.wwise.core.object.setProperty"),
            "candidate_sha256": inventory["native_coverage"]["candidate_sha256"], "relevant_sources": sources,
            "git_candidate": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=audit.ROOT, text=True).strip()}


def finish_condition_capture(capture: dict, phase_reports: dict, observed: dict) -> None:
    """Write one original program result after pytest has reported its call."""
    root, branch = capture["root"], capture["branch"]
    unchanged = all(hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() == seal
                    for name, seal in capture["relevant_sources"].items())
    unchanged = unchanged and subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=audit.ROOT, text=True).strip() == capture["git_candidate"]
    passed = all(phase_reports.get(phase) == "passed" for phase in ("setup", "call", "teardown")) and unchanged
    outcome = "PASS" if passed else "FAIL"
    binding = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
        "public_route": capture["public"]["id"], "public_route_sha256": audit.digest(capture["public"]),
        "input": {"gateway_argv": observed.get("gateway", {}).get("argv", []),
                  "selector": "exact_bound_GameParameter_live_SlewRateUp_Field_Handle_value_37_with_RTPCRamping_0"},
        "construction": {"source": "skills/waapi-skill/wwise_waapi/operation_registry.py#_apply_reference_activation_dependencies", "selector": branch["pointer"]},
        "validation": {"source": "skills/waapi-skill/wwise_waapi/metadata_restrictions.py#condition_restriction", "selector": branch["pointer"]},
        "verifier": {"source": "skills/waapi-skill/wwise_waapi/operation_registry.py#verify_prepared_operation", "selector": branch["pointer"]},
        "native_hosts": ["wwise-console"],
        "observation_pointer": "/observations/wwise-console/metadata/dependencies/0",
        "gateway_observation_pointer": "/gateway/payload/agent_result",
        "relevant_sources": list(capture["relevant_sources"]), "evidence": {},
    }
    record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": "product",
        "evidence_kind": "injected_client_program", "git_candidate": capture["git_candidate"],
        "relevant_sources": capture["relevant_sources"],
        "invocation": {"phase": "final", "outcome": outcome,
                       "node_outcomes": [{"nodeid": capture["nodeid"], "outcome": outcome}]},
        **deepcopy(observed)}
    checks = [
        {"pointer": binding["observation_pointer"], "equals": observed.get("observations", {}).get("wwise-console", {}).get("metadata", {}).get("dependencies", [None])[0]},
        {"pointer": "/observations/wwise-console/observations/0/controller_before/RTPCRamping", "equals": 0},
        {"pointer": "/observations/wwise-console/observations/0/controller_after/RTPCRamping", "equals": 0},
        {"pointer": "/observations/wwise-console/observations/0/after/SlewRateUp", "equals": 37},
        {"pointer": binding["gateway_observation_pointer"], "equals": observed.get("gateway", {}).get("payload", {}).get("agent_result")},
    ]
    record["branch_assertions"] = {branch["id"]: {"native_shape_sha256": branch["shape_sha256"], "native_route": None, "checks": checks}}
    def write(name, value):
        path = root / name
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return {"artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    program_path = root / "program.json"
    program_bytes = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    descriptor = {"artifact": str(program_path), "sha256": hashlib.sha256(program_bytes).hexdigest()}
    binding["evidence"]["program"] = {**descriptor, "nodeid": capture["nodeid"]}
    write("bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": {branch["id"]: binding}})
    write("requirements.json", {"contract": "waapi-skill.branch-evidence-requirements/v1", "branches": {
        branch["id"]: {"native_shape_sha256": branch["shape_sha256"], "categories": ["program", "native"],
            "reason": "Exact installed existing-object Show condition: public mutation must preserve the controller and satisfy field readback. Console native effect requires a new finalized original node observation; injected program behavior grants no native or Authoring applicability credit."}}})
    write("capture.json", {"contract": "waapi-skill.condition-program-capture/v1", "branch_id": branch["id"],
                           "candidate_sha256": capture["candidate_sha256"], "git_candidate": capture["git_candidate"],
                           "source_unchanged": unchanged, "outcome": outcome, "nodeid": capture["nodeid"],
                           "functional_coverage": "program_only_native_missing", "obligations_in_scope": 1})
    pending = root / ".program.pending"
    pending.write_bytes(program_bytes)
    pending.replace(program_path)

"""Original public Short ID query receipts, using the shared phase finalizer."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.support.media_pool_branch_evidence import _git_candidate, _source_seals, _write
from tests.maintenance import branch_coverage_audit as audit


NODE = "tests/unit/test_typed_query_construction.py::test_short_id_source_resolves_native_candidates_then_applies_business_read_semantics"
POINTER = "/argsSchema/properties/from/oneOf/0/properties/id/items/oneOf/1"


def source_seals():
    seals = _source_seals()
    for name in ("tests/support/short_id_query_branch_evidence.py", "tests/unit/test_typed_query_construction.py"):
        seals[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return dict(sorted(seals.items()))


def prepare_short_id_capture(root: Path) -> Path:
    import subprocess
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=audit.ROOT, text=True).strip():
        raise ValueError("Short ID query capture requires a clean committed candidate")
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    witnesses = {}
    for branch in inventory["native_coverage"]["obligations"]:
        if branch["owner_issue"] == 181 and branch["pointer"] == POINTER and "|wwise-console|" in branch["id"] and "|ak.wwise.core.object.get|" in branch["id"]:
            version = branch["id"].split("|")[0]
            witnesses[version] = {"branch": branch, "public": next(row for row in inventory["routes"]
                if row["id"] == version + "|function|ak.wwise.core.object.get")}
    assert len(witnesses) == 5
    witnesses.pop("2021.1")
    context = {"contract": "waapi-skill.short-id-query-program-context/v1", "root": str(root.resolve()),
        "candidate_sha256": inventory["native_coverage"]["candidate_sha256"], "git_candidate": _git_candidate(),
        "relevant_sources": source_seals(), "witnesses": witnesses}
    path = root / "context.json"
    _write(path, context)
    return path


def load_short_id_capture(path: Path, nodeid: str, version: str) -> dict:
    context = json.loads(path.read_text(encoding="utf-8"))
    if (context.get("contract") != "waapi-skill.short-id-query-program-context/v1" or nodeid != NODE + "[" + version + "]"
            or context["git_candidate"] != _git_candidate() or context["relevant_sources"] != source_seals()):
        raise ValueError("Prepared Short ID query node or source changed")
    return {**context, "version": version, "nodeid": nodeid}


def finish_short_id_capture(capture: dict, reports: dict, observed: dict) -> None:
    unchanged = capture["git_candidate"] == _git_candidate() and capture["relevant_sources"] == source_seals()
    outcome = "PASS" if unchanged and all(reports.get(phase) == "passed" for phase in ("setup", "call", "teardown")) else "FAIL"
    witness = capture["witnesses"][capture["version"]]
    branch, public = witness["branch"], witness["public"]
    root = Path(capture["root"]) / capture["version"]
    root.mkdir(exist_ok=False)
    binding = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
        "public_route": public["id"], "public_route_sha256": audit.digest(public),
        "input": {"gateway_argv": observed.get("gateway", {}).get("argv", []),
                  "selector": "closed_uint32_short_id_resolves_guid_before_business_predicate_output_platform_language"},
        "construction": {"source": "skills/waapi-skill/scripts/gateway.py#dispatch_command", "selector": POINTER},
        "validation": {"source": "skills/waapi-skill/scripts/gateway.py#preflight_query_object_input", "selector": POINTER},
        "verifier": {"source": "skills/waapi-skill/scripts/gateway.py#strict_object_get_rows", "selector": POINTER},
        "dispatch_pointer": "/native_call", "observation_pointer": "/native_call/args/from/id/0",
        "gateway_observation_pointer": "/gateway/payload/agent_result", "native_hosts": ["wwise-console"],
        "relevant_sources": list(capture["relevant_sources"]), "evidence": {}}
    record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": "product", "evidence_kind": "injected_client_program",
        "git_candidate": capture["git_candidate"], "relevant_sources": capture["relevant_sources"],
        "invocation": {"phase": "final", "outcome": outcome, "node_outcomes": [{"nodeid": capture["nodeid"], "outcome": outcome}]},
        **deepcopy(observed), "branch_assertions": {branch["id"]: {"native_shape_sha256": branch["shape_sha256"],
        "native_route": branch["route"], "checks": [
            {"pointer": "/native_call/args/from/id/0", "equals": {"shortId": 123456, "type": 10}},
            {"pointer": "/gateway/payload/agent_result", "equals": observed.get("gateway", {}).get("payload", {}).get("agent_result")},
            {"pointer": "/gateway/payload/source_resolution/mutation_authority", "equals": False},
            {"pointer": "/final_call/options/platform", "equals": "Windows"},
            {"pointer": "/final_call/options/language", "equals": "English(US)"},
        ]}}}
    descriptor = _write(root / "program.json", record)
    binding["evidence"]["program"] = {**descriptor, "nodeid": capture["nodeid"]}
    _write(root / "bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": {branch["id"]: binding}})
    _write(root / "requirements.json", {"contract": "waapi-skill.branch-evidence-requirements/v1", "branches": {branch["id"]: {
        "native_shape_sha256": branch["shape_sha256"], "categories": ["program", "native"],
        "reason": "Exact native uint32 source alternative through a bounded public read. Injected program observation cannot establish real native host behavior or mutation identity."}}})
    _write(root / "capture.json", {"git_candidate": capture["git_candidate"], "source_unchanged": unchanged,
        "outcome": outcome, "phase_reports": reports, "functional_coverage": "program_only_native_missing", "obligations_in_scope": 1})

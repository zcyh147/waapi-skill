"""Exact public peak-read witnesses using the existing phase finalizer/reader."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from tests.maintenance import branch_coverage_audit as audit
from tests.support.media_pool_branch_evidence import _git_candidate, _source_seals, _write, _observation

NODE = "tests/unit/test_media_build_business_gateway.py::test_large_peak_read_follows_bounded_exact_result_pages_without_losing_channels"
OPERATIONS = ("ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion", "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion")


def source_seals():
    seals = _source_seals()
    name = "tests/support/peak_query_branch_evidence.py"
    seals[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return dict(sorted(seals.items()))


def prepare_peak_capture(root: Path) -> Path:
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=audit.ROOT, text=True).strip():
        raise ValueError("Peak product capture requires a clean committed candidate")
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    witnesses = {}
    for branch in inventory["native_coverage"]["obligations"]:
        version, host = branch["id"].split("|")[:2]
        if branch["owner_issue"] != 181 or host != "wwise-console":
            continue
        operation = branch["route"].split("|")[-1]
        if operation not in OPERATIONS:
            continue
        pointers = {f"/{phase}/properties/{field}/@presence/present": f"/native_call/{native}/{field}"
            for phase, native, fields in (
                ("argsSchema", "args", ["numPeaks", "getCrossChannelPeaks"] + (["timeFrom", "timeTo"] if operation == OPERATIONS[0] else [])),
                ("resultSchema", "result", ["numChannels", "peaksArrayLength", "peaksBinaryStrings", "peaksDataSize", "maxAbsValue", "channelConfig"]))
            for field in fields}
        pointers["/resultSchema/properties/peaksBinaryStrings/@cardinality/multiple"] = "/native_call/result/peaksBinaryStrings"
        if branch["pointer"] not in pointers:
            continue
        key = version + "|" + operation
        group = witnesses.setdefault(key, {"version": version, "operation": operation, "branches": [],
            "public": next(row for row in inventory["routes"] if row["id"] == version + "|function|" + operation)})
        group["branches"].append({"branch": branch, "observation_pointer": pointers[branch["pointer"]]})
    assert len(witnesses) == 10
    context = {"contract": "waapi-skill.peak-query-program-context/v1", "root": str(root.resolve()),
        "candidate_sha256": inventory["native_coverage"]["candidate_sha256"], "git_candidate": _git_candidate(),
        "relevant_sources": source_seals(), "witnesses": witnesses}
    path = root / "context.json"
    _write(path, context)
    return path


def load_peak_capture(path: Path, nodeid: str, version: str, operation: str) -> dict:
    context = json.loads(path.read_text(encoding="utf-8"))
    if (context.get("contract") != "waapi-skill.peak-query-program-context/v1"
            or nodeid != NODE + "[posix-" + operation + "-" + version + "]"
            or context["git_candidate"] != _git_candidate() or context["relevant_sources"] != source_seals()):
        raise ValueError("Prepared peak query source or exact node changed")
    return {**context, "version": version, "operation": operation, "nodeid": nodeid}


def finish_peak_capture(capture: dict, reports: dict, observed: dict) -> None:
    unchanged = capture["git_candidate"] == _git_candidate() and capture["relevant_sources"] == source_seals()
    outcome = "PASS" if unchanged and all(reports.get(phase) == "passed" for phase in ("setup", "call", "teardown")) else "FAIL"
    group = capture["witnesses"][capture["version"] + "|" + capture["operation"]]
    record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": "product", "evidence_kind": "injected_client_program",
        "git_candidate": capture["git_candidate"], "relevant_sources": capture["relevant_sources"],
        "invocation": {"phase": "final", "outcome": outcome, "node_outcomes": [{"nodeid": capture["nodeid"], "outcome": outcome}]},
        **deepcopy(observed), "branch_assertions": {}}
    bindings, requirements = {}, {}
    for witness in group["branches"]:
        branch, pointer, public = witness["branch"], witness["observation_pointer"], group["public"]
        checks = ([{"pointer": pointer, "cardinality": branch["value"]}] if branch["kind"] == "collection_cardinality"
            else [{"pointer": pointer, "equals": _observation(record, pointer)}])
        checks.extend({"pointer": path, "equals": _observation(record, path)} for path in
            ("/gateway/payload/agent_result", "/recovered_channels", "/peak_dispatch_count", "/all_pages_bounded", "/projection_complete"))
        record["branch_assertions"][branch["id"]] = {"native_shape_sha256": branch["shape_sha256"], "native_route": branch["route"], "checks": checks}
        bindings[branch["id"]] = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
            "public_route": public["id"], "public_route_sha256": audit.digest(public),
            "input": {"gateway_argv": observed.get("gateway", {}).get("argv", []), "selector": "closed_peak_read_to_exact_observation_projection_pages"},
            "construction": {"source": "skills/waapi-skill/wwise_waapi/media_build_business.py#_materialize_peaks", "selector": branch["pointer"]},
            "validation": {"source": "skills/waapi-skill/wwise_waapi/media_build_business.py#_normalize_peaks_result", "selector": branch["pointer"]},
            "verifier": {"source": "skills/waapi-skill/wwise_waapi/peak_read_continuation.py#finish_peak_page", "selector": branch["pointer"]},
            "dispatch_pointer": "/native_call", "observation_pointer": pointer,
            "gateway_observation_pointer": "/gateway/payload/agent_result", "native_hosts": ["wwise-console"],
            "relevant_sources": list(capture["relevant_sources"]), "evidence": {}}
        requirements[branch["id"]] = {"native_shape_sha256": branch["shape_sha256"], "categories": ["program", "native"],
            "reason": "Exact closed peak read and lossless bounded channel/pair continuations. Injected fake result and Windows envelope roundtrip grant no real native or Windows-host acceptance."}
    root = Path(capture["root"]) / capture["version"] / capture["operation"].split(".")[-1]
    root.mkdir(parents=True, exist_ok=False)
    descriptor = _write(root / "program.json", record)
    for binding in bindings.values():
        binding["evidence"]["program"] = {**descriptor, "nodeid": capture["nodeid"]}
    _write(root / "bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": bindings})
    _write(root / "requirements.json", {"contract": "waapi-skill.branch-evidence-requirements/v1", "branches": requirements})
    _write(root / "capture.json", {"git_candidate": capture["git_candidate"], "source_unchanged": unchanged,
        "outcome": outcome, "phase_reports": reports, "functional_coverage": "program_only_native_missing", "obligations_in_scope": len(bindings)})

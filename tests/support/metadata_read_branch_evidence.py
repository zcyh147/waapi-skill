"""Exact metadata result mappings; reuse the shared finalizer and strict reader.

Each source branch chooses one actual native field/array occurrence in one
literal result case. Unmatched branches remain in the frozen residual index.
No shape family, version, host, or condition effect inherits evidence.
"""
from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
from pathlib import Path
import subprocess

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support.metadata_result_case_bank import metadata_result_cases
from tests.support.media_pool_branch_evidence import _git_candidate, _source_seals, _write, _observation


URI = "ak.wwise.core.object.getPropertyInfo"
NODE = "tests/unit/test_metadata_discovery_gateway.py::test_public_metadata_result_bank_preserves_each_selected_native_fact"


# Root-reviewed R59 decoder scope. Exact host/build/shape identity is intentional:
# this is no exemption for metadata meanings, applicability or native effects.
ABSENT_DEFAULT_PROGRAM_BRANCHES = frozenset(
    version + "|wwise-console|" + build + "|function|" + URI
    + "|/resultSchema/properties/default/@presence/absent"
    for version, build in (
        ("2021.1", "2021.1.14.8108"), ("2022.1", "2022.1.19.8584"),
        ("2023.1", "2023.1.19.8928"), ("2024.1", "2024.1.13.9056"),
        ("2025.1", "2025.1.7.9143")))
ABSENT_DEFAULT_SHAPE = "15dbb2c4361b809a46b847b3b6c071f3c27c096057d31c45351902b79fe39efd"


def validate_selected_metadata_requirement(branch, policy):
    """Admit the exact reviewed decoder split; all other native reads stay required."""
    decoder = branch["id"] in ABSENT_DEFAULT_PROGRAM_BRANCHES
    categories = ["program"] if decoder else ["program", "live_metadata"]
    if (policy.get("native_shape_sha256") != branch["shape_sha256"]
            or (decoder and branch["shape_sha256"] != ABSENT_DEFAULT_SHAPE)
            or policy.get("categories") != categories or not policy.get("reason")):
        raise ValueError("Reviewed selected metadata shape or evidence policy changed")


def source_seals():
    seals = _source_seals()
    for name in ("tests/support/metadata_result_case_bank.py", "tests/support/metadata_read_branch_evidence.py",
                 "tests/unit/test_metadata_discovery_gateway.py", "tests/unit/test_branch_evidence_readers.py",
                 "tests/unit/test_metadata_default_branch_evidence.py",
                 "tests/unit/test_branch_coverage_completion_cli.py"):
        seals[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return dict(sorted(seals.items()))


def _context(branch, edges):
    """Only the four reviewed getPropertyInfo result reference occurrences."""
    pointer = branch["pointer"]
    if "/@definition/" not in pointer:
        return completion.native_observation_pattern(pointer), []
    # Follow each selected pinned edge, including the older waapi_definitions
    # propertyValue/uint32 homes. URI equality never substitutes for its target.
    sources = (
        "/resultSchema/properties/audioEngineId/$ref",
        "/resultSchema/properties/default/$ref",
        "/resultSchema/properties/dependencies/items/properties/property/$ref",
        "/resultSchema/properties/dependencies/items/properties/conditions/items/properties/restriction/$ref",
    )
    for source in sources:
        edge_id = branch["route"] + "|" + source
        edge = edges[edge_id]
        route, target = edge["reference"]["target"].rsplit("|", 1)
        if route != branch["route"]:
            raise ValueError("Reviewed native reference route changed")
        if pointer == target or pointer.startswith(target + "/"):
            return (completion.native_observation_pattern(source)
                    + completion.native_observation_pattern(pointer[len(target):])), [edge_id]
    raise ValueError("Unreviewed metadata reference occurrence")


def _locations(value, pattern, path="/native_call/result", *, absent=False):
    if not pattern:
        yield path, value, True
        return
    token, *rest = pattern
    if token == "*":
        if isinstance(value, list):
            for index, child in enumerate(value):
                yield from _locations(child, rest, path + "/" + str(index), absent=absent)
    elif isinstance(value, dict):
        if token in value:
            yield from _locations(value[token], rest, path + "/" + token, absent=absent)
        elif absent and not rest:
            # An absent child is observed only inside an actual parent object.
            yield path + "/" + token, None, False


def _witness(branch, native, edges):
    pattern, chain = _context(branch, edges)
    absent = branch["kind"] == "optional_presence" and branch.get("value") == "absent"
    for pointer, value, present in _locations(native, pattern, absent=absent):
        if absent != (not present):
            continue
        check = ({"pointer": pointer, "absent": True} if absent else
                 {"pointer": pointer, "cardinality": "empty" if not value else "single" if len(value) == 1 else "multiple"}
                 if branch["kind"] == "collection_cardinality" and isinstance(value, list) else
                 {"pointer": pointer, "equals": value})
        if not completion.proves_alternative(check, branch):
            continue
        if branch["kind"] == "constraint" and (type(value) is not type(branch.get("value")) or value != branch.get("value")):
            continue  # A generic successful scalar is no boundary control.
        if branch["kind"] == "schema":
            try:
                completion.validate_native_alternative(audit.ROOT, branch, value)
            except ValueError:
                continue
        binding = {"observation_pointer": pointer, **({"reference_chain": chain} if chain else {})}
        completion.exact_observation_pointer(branch, binding, "/native_call", "result", edges)
        return {"branch": branch, "observation_pointer": pointer, "reference_chain": chain, "check": check}
    return None


def prepare_metadata_capture(root: Path, *, selected_branch_ids=None, reviewed_requirements=None):
    """One frozen inventory before pytest; no committed inventory is written."""
    import json
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=audit.ROOT, text=True).strip():
        raise ValueError("Metadata product capture needs a clean committed candidate")
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    with gzip.open(root / "frozen-inventory.json.gz", "wt", encoding="utf-8") as stream:
        json.dump(inventory, stream, ensure_ascii=False, separators=(",", ":"))
    owned = [row for row in inventory["native_coverage"]["obligations"] if row["owner_issue"] == 181]
    selected = None
    if selected_branch_ids is not None:
        selected = set(selected_branch_ids)
        if (not selected or len(selected) != len(selected_branch_ids)
                or reviewed_requirements is None
                or reviewed_requirements.get("contract") != "waapi-skill.branch-evidence-requirements/v1"
                or set(reviewed_requirements.get("branches", {})) != selected):
            raise ValueError("Exact selected metadata branches need their reviewed requirements")
        available = {row["id"]: row for row in owned if "|wwise-console|" in row["route"]
                     and row["route"].endswith("|" + URI) and row["pointer"].startswith("/resultSchema")}
        for identity in selected:
            if identity not in available:
                raise ValueError("Reviewed selected metadata shape or evidence policy changed")
            validate_selected_metadata_requirement(available[identity], reviewed_requirements["branches"][identity])
    elif reviewed_requirements is not None:
        raise ValueError("Reviewed metadata requirements need an exact branch selection")
    edges = {row["id"]: row for row in owned if row["kind"] == "reference"}
    groups, mapped = {}, set()
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        branches = [row for row in owned if row["route"].startswith(version + "|wwise-console|")
                    and row["route"].endswith("|" + URI) and row["pointer"].startswith("/resultSchema")
                    and (selected is None or row["id"] in selected)]
        public = next(row for row in inventory["routes"] if row["id"] == version + "|function|" + URI)
        for name, native in metadata_result_cases(version).items():
            witnesses = []
            for branch in branches:
                if branch["id"] in mapped:
                    continue
                witness = _witness(branch, native, edges)
                if witness is not None:
                    witnesses.append(witness)
                    mapped.add(branch["id"])
            if witnesses or selected is None:
                groups[version + "|" + name] = {"version": version, "case_name": name, "branches": witnesses, "public": public}
    context = {"contract": "waapi-skill.metadata-result-program-context/v1", "root": str(root.resolve()),
        "candidate_sha256": inventory["native_coverage"]["candidate_sha256"], "git_candidate": _git_candidate(),
        "relevant_sources": source_seals(), "groups": groups,
        "reviewed_requirements": deepcopy(reviewed_requirements)}
    _write(root / "owned-planning-index.json", {"obligations": owned, "candidate_sha256": context["candidate_sha256"],
        "selected_branch_ids": sorted(mapped), "residual_branch_ids": sorted(row["id"] for row in owned if row["id"] not in mapped),
        "selected_unobserved_branch_ids": sorted((selected or set()) - mapped),
        "mapping_is_not_execution_credit": True})
    _write(root / "context.json", context)
    return root / "context.json"


def load_metadata_capture(path: Path, nodeid: str, version: str, case_name: str):
    import json
    context = json.loads(path.read_text(encoding="utf-8"))
    if (context.get("contract") != "waapi-skill.metadata-result-program-context/v1"
            or nodeid != NODE + "[" + version + "-" + case_name + "]"
            or context["git_candidate"] != _git_candidate() or context["relevant_sources"] != source_seals()):
        raise ValueError("Prepared metadata node or exact source changed")
    return {**context, "version": version, "case_name": case_name, "nodeid": nodeid}


def finish_metadata_capture(capture, reports, observed):
    unchanged = capture["git_candidate"] == _git_candidate() and capture["relevant_sources"] == source_seals()
    outcome = "PASS" if unchanged and all(reports.get(phase) == "passed" for phase in ("setup", "call", "teardown")) else "FAIL"
    group = capture["groups"][capture["version"] + "|" + capture["case_name"]]
    record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": capture.get("scope_kind", "product"),
        "evidence_kind": "injected_client_program", "git_candidate": capture["git_candidate"], "relevant_sources": capture["relevant_sources"],
        "invocation": {"phase": "final", "outcome": outcome, "node_outcomes": [{"nodeid": capture["nodeid"], "outcome": outcome}]},
        **deepcopy(observed), "branch_assertions": {}}
    bindings, requirements = {}, {}
    for witness in group["branches"]:
        branch, public = witness["branch"], group["public"]
        public_pointer = witness["observation_pointer"].replace("/native_call/result", "/gateway/payload/agent_result/metadata", 1)
        public_check = {**witness["check"], "pointer": public_pointer}
        checks = [witness["check"], public_check, *({"pointer": pointer, "equals": _observation(record, pointer)} for pointer in (
            "/gateway/payload/agent_result", "/native_metadata_dispatch_count", "/rejected_read/payload/error_code"))]
        record["branch_assertions"][branch["id"]] = {"native_shape_sha256": branch["shape_sha256"], "native_route": branch["route"], "checks": checks}
        bindings[branch["id"]] = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
            "public_route": public["id"], "public_route_sha256": audit.digest(public),
            "input": {"gateway_argv": observed.get("gateway", {}).get("argv", []), "selector": "exact_live_inventory_field_selection_to_native_metadata_result"},
            "construction": {"source": "skills/waapi-skill/wwise_waapi/metadata_discovery.py#browse_metadata", "selector": branch["pointer"]},
            "validation": {"source": "skills/waapi-skill/wwise_waapi/builders/metadata.py#parse_get_property_info_result", "selector": branch["pointer"]},
            "verifier": {"source": "skills/waapi-skill/wwise_waapi/metadata_discovery.py#browse_metadata", "selector": branch["pointer"]},
            "dispatch_pointer": "/native_call", "observation_pointer": witness["observation_pointer"],
            **({"reference_chain": witness["reference_chain"]} if witness["reference_chain"] else {}),
            "gateway_observation_pointer": public_pointer if capture.get("reviewed_requirements") else "/gateway/payload/agent_result",
            "native_hosts": ["wwise-console"],
            "relevant_sources": list(capture["relevant_sources"]), "evidence": {}}
        requirements[branch["id"]] = (deepcopy(capture["reviewed_requirements"]["branches"][branch["id"]])
            if capture.get("reviewed_requirements") else
            {"native_shape_sha256": branch["shape_sha256"], "categories": ["program", "native"],
             "reason": "Exact selected metadata result read. Raw disclosure proves no condition activation or write effect; matching native version/host/build read remains required."})
    root = Path(capture["root"]) / capture["version"] / capture["case_name"]
    root.mkdir(parents=True, exist_ok=False)
    descriptor = _write(root / "program.json", record)
    for binding in bindings.values():
        binding["evidence"]["program"] = {**descriptor, "nodeid": capture["nodeid"]}
    _write(root / "bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": bindings})
    _write(root / "requirements.json", {"contract": "waapi-skill.branch-evidence-requirements/v1", "branches": requirements})
    _write(root / "capture.json", {"outcome": outcome, "phase_reports": reports, "source_unchanged": unchanged,
        "git_candidate": capture["git_candidate"], "obligations_in_scope": len(bindings), "functional_coverage": "program_only_native_missing"})

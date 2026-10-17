"""Exact Media Pool product receipts using the shared pytest phase finalizer.

Prepare context before pytest; the test only loads it and records public reads.
This does not write committed inventories or grant native evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import pointer_value


NODEID = "tests/unit/test_media_build_business_gateway.py::test_product_media_pool_discovery_to_exact_filtered_projection_preserves_native_field_identity"
_BASE = "2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.mediaPool."
_FIELD = "/@definition/waapi_definitions.json/definitions/mediaPoolField/anyOf/11"
# Exact native occurrence, actual native observation, and reference path (if any).
WITNESSES = [
    ("getFields", "/resultSchema/properties/return/@presence/present", "/field_discovery_call/result/return", []),
    ("getFields", "/resultSchema/properties/return/@cardinality/multiple", "/field_discovery_call/result/return", []),
    ("getFields", "/resultSchema" + _FIELD, "/field_discovery_call/result/return/4",
     ["/resultSchema/properties/return/items/$ref"]),
    ("get", "/argsSchema/properties/filters/@presence/present", "/native_call/args/filters", []),
    ("get", "/argsSchema/properties/filters/@cardinality/single", "/native_call/args/filters", []),
    ("get", "/argsSchema/properties/filters/items/properties/field/@presence/present", "/native_call/args/filters/0/field", []),
    ("get", "/argsSchema" + _FIELD, "/native_call/args/filters/0/field",
     ["/argsSchema/properties/filters/items/properties/field/$ref"]),
    ("get", "/optionsSchema/properties/return/@presence/present", "/native_call/options/return", []),
    ("get", "/optionsSchema/properties/return/@cardinality/multiple", "/native_call/options/return", []),
    ("get", "/optionsSchema" + _FIELD, "/native_call/options/return/3",
     ["/optionsSchema/properties/return/items/$ref",
      "/optionsSchema/@definition/waapi_definitions.json/definitions/mediaPoolReturnOption/anyOf/7/$ref"]),
    ("get", "/resultSchema/properties/return/@presence/present", "/native_call/result/return", []),
    ("get", "/resultSchema/properties/return/@cardinality/single", "/native_call/result/return", []),
]


def public_read_observation(*, gateway_argv, exit_code, payload, uri, args, options, result):
    """One shared producer shape consumed by the existing strict program reader."""
    if type(exit_code) is not int or not isinstance(uri, str) or not uri or not gateway_argv:
        raise ValueError("A public read observation needs exact argv, exit status and native URI")
    return {"gateway": {"argv": list(gateway_argv), "exit_code": exit_code, "payload": deepcopy(payload)},
            "native_call": {"uri": uri, "args": deepcopy(args), "options": deepcopy(options), "result": deepcopy(result)}}


def _write(path: Path, value: dict) -> dict:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    path.write_bytes(data)
    return {"artifact": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _source_seals() -> dict[str, str]:
    selected = [path for path in (audit.ROOT / "skills/waapi-skill").rglob("*")
                if path.is_file() and path.suffix in {".py", ".json", ".md"}
                and not {".venv", "__pycache__", "data"}.intersection(path.relative_to(audit.ROOT / "skills/waapi-skill").parts)]
    selected += [audit.ROOT / name for name in (
        "tests/support/media_pool_branch_evidence.py", "tests/unit/test_media_build_business_gateway.py",
        "tests/conftest.py", "tests/support/exact_evidence_finalization.py",
        "tests/maintenance/branch_coverage_audit.py", "tests/maintenance/branch_audit_completion.py")]
    return {str(path.relative_to(audit.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(selected)}


def _git_candidate() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=audit.ROOT, text=True).strip()


RETURN_OPTION_NODEID = "tests/unit/test_media_build_business_gateway.py::test_media_pool_return_only_score_size_markers_and_regions_do_not_require_discovered_fields"
RETURN_OPTION_WITNESSES = [
    ("get", f"/optionsSchema/@definition/waapi_definitions.json/definitions/mediaPoolReturnOption/anyOf/{choice}/enum/0",
     f"/native_call/options/return/{index}", ["/optionsSchema/properties/return/items/$ref"])
    for choice, index in ((0, 3), (4, 4), (5, 5), (6, 6))
]


def prepare_media_pool_capture(root: Path, *, nodeid: str = NODEID, witnesses=WITNESSES,
                               extra_observation_pointers=None, reason=None, validation_symbol="_resolve_media_field") -> Path:
    """Run before pytest, from a clean candidate; retain each new capture root."""
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=audit.ROOT, text=True).strip():
        raise ValueError("Media Pool product capture requires a clean committed candidate")
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    branches = {row["id"]: row for row in inventory["native_coverage"]["obligations"]}
    chosen = []
    for suffix, pointer, observed, chain in witnesses:
        branch = branches[_BASE + suffix + "|" + pointer]
        assert branch["owner_issue"] == 181
        chosen.append({"branch": branch, "observation_pointer": observed,
                       "reference_chain": [_BASE + suffix + "|" + edge for edge in chain]})
    context = {"contract": "waapi-skill.media-pool-program-capture-context/v1", "nodeid": nodeid,
               "root": str(root.resolve()), "candidate_sha256": inventory["native_coverage"]["candidate_sha256"],
               "git_candidate": _git_candidate(), "relevant_sources": _source_seals(), "witnesses": chosen,
               "reason": reason or "Exact 2025.1 Console Media Pool field witness through public discovery/read, native payload and result assertions, plus unrelated/ambiguous field controls. Injected-client behavior grants no native host acceptance.",
               "validation_symbol": validation_symbol,
               "extra_observation_pointers": extra_observation_pointers or ["/gateway/payload/agent_result", "/media_pool_dispatch_count",
                   "/rejected_reads/0/payload/details/field_choices", "/rejected_reads/1/payload/details/field_choices",
                   "/no_match/payload/agent_result/fields"],
               "routes": {suffix: next(row for row in inventory["routes"]
                          if row["id"] == "2025.1|function|ak.wwise.core.mediaPool." + suffix)
                          for suffix in sorted({row[0] for row in witnesses})}}
    path = root / "context.json"
    _write(path, context)
    return path


def load_media_pool_capture(path: Path, nodeid: str) -> dict:
    context = json.loads(path.read_text(encoding="utf-8"))
    if (context.get("contract") != "waapi-skill.media-pool-program-capture-context/v1"
            or context["nodeid"] != nodeid or context["git_candidate"] != _git_candidate()
            or context["relevant_sources"] != _source_seals()):
        raise ValueError("Prepared Media Pool capture source or node changed")
    return context


def _observation(record: dict, pointer: str):
    try:
        return pointer_value(record, pointer)
    except (KeyError, IndexError, TypeError):
        # Failed tests still publish FAIL receipts without claiming missing facts.
        return None


def finish_media_pool_capture(capture: dict, phase_reports: dict, observed: dict) -> None:
    """Publish only after shared finalizer receives setup/call/teardown reports."""
    unchanged = capture["git_candidate"] == _git_candidate() and capture["relevant_sources"] == _source_seals()
    passed = unchanged and all(phase_reports.get(phase) == "passed" for phase in ("setup", "call", "teardown"))
    outcome = "PASS" if passed else "FAIL"
    root = Path(capture["root"])
    bindings, requirements = {}, {}
    for suffix in capture["routes"]:
        record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": "product",
                  "evidence_kind": "injected_client_program", "git_candidate": capture["git_candidate"],
                  "relevant_sources": capture["relevant_sources"],
                  "invocation": {"phase": "final", "outcome": outcome,
                                 "node_outcomes": [{"nodeid": capture["nodeid"], "outcome": outcome}]},
                  **deepcopy(observed), "branch_assertions": {}}
        if suffix == "getFields":
            record["gateway"] = deepcopy(observed.get("discovery", {}))
        for witness in capture["witnesses"]:
            branch = witness["branch"]
            if branch["route"] != _BASE + suffix:
                continue
            public = capture["routes"][suffix]
            pointer = witness["observation_pointer"]
            binding = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
                "public_route": public["id"], "public_route_sha256": audit.digest(public),
                "input": {"gateway_argv": record.get("gateway", {}).get("argv", []),
                          "selector": "live_exact_field_discovery_to_filter_and_lossless_unicode_collision_projection"},
                "construction": {"source": "skills/waapi-skill/wwise_waapi/media_pool_field_discovery.py#browse_media_pool_fields"
                    if suffix == "getFields" else "skills/waapi-skill/wwise_waapi/media_build_business.py#_materialize_media_pool", "selector": branch["pointer"]},
                "validation": {"source": "skills/waapi-skill/wwise_waapi/media_pool_field_discovery.py#browse_media_pool_fields"
                    if suffix == "getFields" else "skills/waapi-skill/wwise_waapi/media_build_business.py#" + capture["validation_symbol"], "selector": branch["pointer"]},
                "verifier": {"source": "skills/waapi-skill/wwise_waapi/media_pool_field_discovery.py#browse_media_pool_fields"
                    if suffix == "getFields" else "skills/waapi-skill/wwise_waapi/media_build_business.py#_normalize_media_pool_result", "selector": branch["pointer"]},
                "dispatch_pointer": "/field_discovery_call" if suffix == "getFields" else "/native_call",
                "observation_pointer": pointer, "gateway_observation_pointer": "/gateway/payload/agent_result",
                "native_hosts": ["wwise-console"], "relevant_sources": list(capture["relevant_sources"]), "evidence": {}}
            if witness["reference_chain"]:
                binding["reference_chain"] = witness["reference_chain"]
            checks = [{"pointer": pointer, "cardinality": branch["value"]} if branch["kind"] == "collection_cardinality"
                      else {"pointer": pointer, "equals": _observation(record, pointer)}]
            checks.extend({"pointer": check, "equals": _observation(record, check)}
                          for check in capture["extra_observation_pointers"])
            record["branch_assertions"][branch["id"]] = {"native_shape_sha256": branch["shape_sha256"],
                "native_route": branch["route"], "checks": checks}
            bindings[branch["id"]] = binding
            requirements[branch["id"]] = {"native_shape_sha256": branch["shape_sha256"], "categories": ["program", "native"],
                "reason": capture["reason"]}
        descriptor = _write(root / ("program-" + suffix + ".json"), record)
        for binding in bindings.values():
            if binding["branch_id"].startswith(_BASE + suffix + "|"):
                binding["evidence"]["program"] = {**descriptor, "nodeid": capture["nodeid"]}
    _write(root / "bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": bindings})
    _write(root / "requirements.json", {"contract": "waapi-skill.branch-evidence-requirements/v1", "branches": requirements})
    _write(root / "capture.json", {"contract": "waapi-skill.media-pool-program-capture/v1", "candidate_sha256": capture["candidate_sha256"],
        "git_candidate": capture["git_candidate"], "source_unchanged": unchanged, "outcome": outcome,
        "phase_reports": phase_reports, "obligations_in_scope": len(bindings), "functional_coverage": "program_only_native_missing"})

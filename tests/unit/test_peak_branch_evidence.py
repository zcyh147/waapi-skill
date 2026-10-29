"""Controlled receipt-format regressions, with no product/native coverage credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_audit_completion as completion
from tests.support.peak_query_branch_evidence import finish_peak_capture, source_seals, _git_candidate
from tests.support.media_pool_branch_evidence import public_read_observation


def _sealed(path: Path, nodeid: str):
    return {"artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "nodeid": nodeid}


@pytest.mark.parametrize("damage", ["api_instead_of_uri", "missing_exit_code"])
def test_peak_producer_receipt_is_accepted_only_with_exact_reader_dispatch_and_gateway_identity(tmp_path: Path, damage: str) -> None:
    uri = "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion"
    native_route = "2025.1|wwise-console|2025.1.7.9143|function|" + uri
    branch = {"id": "controlled-peak-channel-mode-presence", "route": native_route,
        "kind": "optional_presence", "value": "present", "shape_sha256": "b" * 64,
        "pointer": "/argsSchema/properties/getCrossChannelPeaks/@presence/present"}
    nodeid = "controlled-peak-producer-node"
    argv = ["core-call", uri, "--audio-source-id", "{11111111-1111-1111-1111-111111111111}",
        "--peak-pair-count", "1", "--start-seconds", "0", "--end-seconds", "1"]
    payload = {"ok": True, "agent_result": {"kind": "decoded_peaks", "channels": []}}
    observed = {**public_read_observation(gateway_argv=argv, exit_code=0, payload=payload,
        uri=uri, args={"getCrossChannelPeaks": False}, options={}, result={}),
        "recovered_channels": {}, "peak_dispatch_count": 1, "all_pages_bounded": True, "projection_complete": True}
    candidate = "c" * 64
    capture = {"root": str(tmp_path), "version": "2025.1", "operation": uri,
        "nodeid": nodeid, "candidate_sha256": candidate, "git_candidate": _git_candidate(),
        "scope_kind": "controlled", "relevant_sources": source_seals(),
        "witnesses": {"2025.1|" + uri: {"branches": [{"branch": branch,
            "observation_pointer": "/native_call/args/getCrossChannelPeaks"}],
            "public": {"id": "2025.1|function|" + uri}}}}
    finish_peak_capture(capture, {"setup": "passed", "call": "passed", "teardown": "passed"}, observed)
    root = tmp_path / "2025.1/getMinMaxPeaksInRegion"
    binding = json.loads((root / "bindings.json").read_text())["bindings"][branch["id"]]
    descriptor = binding["evidence"]["program"]
    assert completion.evidence_result(descriptor, branch, candidate, "program", "controlled", root, binding) == ("passed", None)
    record = json.loads((root / "program.json").read_text())
    assert record["scope_kind"] == "controlled"
    damaged = deepcopy(record)
    if damage == "api_instead_of_uri":
        damaged["native_call"]["api"] = damaged["native_call"].pop("uri")
    else:
        damaged["gateway"].pop("exit_code")
    path = root / "damaged.json"
    path.write_text(json.dumps(damaged))
    outcome, reason = completion.evidence_result(_sealed(path, nodeid), branch, candidate, "program", "controlled", root, binding)
    assert outcome == "missing" and ("uri" if damage == "api_instead_of_uri" else "exit_code") in reason
    assert completion.evidence_result(descriptor, branch, candidate, "program", "product", root, binding)[0] == "missing"

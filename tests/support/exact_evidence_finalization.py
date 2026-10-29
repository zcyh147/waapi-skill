"""Publish one node's exact evidence after pytest reports all teardown work."""
from __future__ import annotations

import traceback


def register_exact_evidence_finalizer(item, callback):
    if getattr(item, "_waapi_exact_evidence_finalizer", None) is not None:
        raise AssertionError("one exact evidence producer is permitted per pytest node")
    item._waapi_exact_evidence_finalizer = callback


def finalize_reported_node_evidence(item, report):
    if report.when != "teardown":
        return
    callback = getattr(item, "_waapi_exact_evidence_finalizer", None)
    if callback is None:
        return
    item._waapi_exact_evidence_finalizer = None
    try:
        callback(dict(item._waapi_phase_reports))
    except BaseException:
        # Final evidence publication is itself teardown work. A partial or
        # unsealed record cannot leave pytest reporting a successful node.
        item._waapi_phase_reports["teardown"] = "failed"
        report.outcome = "failed"
        report.longrepr = "Exact evidence finalization failed:\n" + traceback.format_exc()

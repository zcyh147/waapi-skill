"""Bounded per-file source-control status observations; no provider inference."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .canonical import canonical_json_bytes

MAX_STATUS_FILES = 32
MAX_STATUS_NATIVE_BYTES = 16 * 1024
MAX_STATUS_REPORT_BYTES = 768 * 1024
MAX_STATUS_PATH_BYTES = 64 * 1024
MAX_STATUS_ROWS = 4096


def status_file_plan(args: Any) -> dict[str, Any]:
    files = [{"scope": scope, "path": path} for attr, scope in
             (("project_file", "project"), ("originals_file", "originals"), ("exact_file", "exact"))
             for path in getattr(args, attr, [])]
    if not 1 <= len(files) <= MAX_STATUS_FILES:
        raise ValueError(f"Status read requires between 1 and {MAX_STATUS_FILES} exact file locators")
    if len(canonical_json_bytes(files)) > MAX_STATUS_PATH_BYTES:
        raise ValueError("Status file selection exceeds its fixed UTF-8 byte budget")
    return {"files": files, **({"io_root": args.io_root} if args.io_root is not None else {})}


def observe_status_files(files: list[str], *, version: str,
                         call: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    if not 1 <= len(files) <= MAX_STATUS_FILES or len(canonical_json_bytes(files)) > MAX_STATUS_PATH_BYTES:
        raise ValueError("Localized status file selection exceeds its fixed count or byte budget")
    observations = []
    complete = True
    reason = None
    rows_seen = 0
    for path in files:
        outcome = dict(call(path))
        record = {"file": path, "call": outcome["call"]}
        if outcome.get("ok") is not True:
            record["failure"] = outcome.get("failure")
            observations.append(record)
            complete, reason = False, "native_call_failed"
            break
        native = outcome["result"]
        record["result"] = native
        record["schema_validation"] = outcome["schema_validation"]
        observations.append(record)
        statuses = native.get("result") if isinstance(native, Mapping) else None
        log = native.get("log") if isinstance(native, Mapping) else None
        shape_ok = (isinstance(statuses, list) and isinstance(log, list)
                    and all(isinstance(row, Mapping) and all(key not in row or isinstance(row[key], str)
                        for key in ("owner", "status")) for row in statuses)
                    and all(isinstance(row, Mapping) for row in log))
        if not shape_ok:
            complete, reason = False, "status_result_shape_invalid"
            break
        rows_seen += len(statuses) + len(log)
        if rows_seen > MAX_STATUS_ROWS:
            complete, reason = False, "status_row_budget_exceeded"
            break
        if not statuses or any("status" not in row for row in statuses):
            complete, reason = False, "status_not_observed"
            break
    report = {"operation": "ak.wwise.core.sourceControl.getStatus", "version": version,
              "requested_file_count": len(files), "completed_file_count": sum("result" in row for row in observations),
              "complete": complete, "incomplete_reason": reason, "files": observations,
              "remaining_files": files[len(observations):], "observed_row_count": rows_seen,
              "provider_identity_verified": False, "provider_effects_verified": False,
              "limits": {"files": MAX_STATUS_FILES, "native_bytes_per_call": MAX_STATUS_NATIVE_BYTES,
                         "status_and_log_rows": MAX_STATUS_ROWS, "report_bytes": MAX_STATUS_REPORT_BYTES},
              "automatic_retry": False}
    if len(canonical_json_bytes(report)) > MAX_STATUS_REPORT_BYTES:
        raise ValueError("Status report exceeds its fixed byte ceiling; no complete observation can be claimed")
    return report

"""Profiler capability evidence schema for Phase 2.1 live probes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.support.runtime_evidence_paths import (
    RuntimeEvidencePathError,
    localize_runtime_evidence_path,
)


CAPABILITY_STATUS_VALUES = frozenset({"capability-observed", "capability-blocked", "prerequisite-blocked"})
PROMOTION_STATUS_VALUES = frozenset({"profiler-backed-tested", "soundengine-backed-tested"})
REQUIRED_EVIDENCE_ROW_FIELDS = frozenset(
    {
        "api_uri",
        "trigger_call",
        "observed_topic_or_log_uri",
        "observed_payload_fields",
        "missing_payload_blocker",
        "bounded_wait_seconds",
        "artifact_path",
        "cleanup_proof",
        "timestamp_window_mapping",
    }
)
INSUFFICIENT_PROOF_MARKERS = (
    "capture start/stop only",
    "no exception",
    "returned id only",
    "returned ids alone",
    "empty array",
    "empty arrays",
    "accepted call only",
)
PLACEHOLDER_BLOCKER_MARKERS = (
    "live probe replaces this",
    "replace this",
    "placeholder",
    "tbd",
)


class ProfilerCapabilitySchemaError(ValueError):
    """Raised when profiler capability evidence is too vague to audit."""


def validate_profiler_evidence_row(row: Mapping[str, Any]) -> None:
    """Validate one per-URI profiler evidence row.

    Profiler-backed promotion in later tasks needs an observed payload field for the
    target URI, or an exact blocker explaining why no payload was observable. Capture
    boundaries, accepted calls, returned identifiers, and empty arrays are recorded as
    context only; they are not accepted as behavioral proof on their own.
    """

    missing = sorted(field for field in REQUIRED_EVIDENCE_ROW_FIELDS if field not in row)
    if missing:
        raise ProfilerCapabilitySchemaError(
            f"profiler evidence row {row.get('api_uri', '<unknown>')} missing: {', '.join(missing)}"
        )

    api_uri = _require_non_empty_string(row, "api_uri")
    _require_non_empty_string(row, "trigger_call")
    _require_non_empty_string(row, "artifact_path")
    if float(row["bounded_wait_seconds"]) <= 0:
        raise ProfilerCapabilitySchemaError(f"profiler evidence row {api_uri} must use a positive bounded wait")
    cleanup = row["cleanup_proof"]
    if not isinstance(cleanup, Mapping) or not cleanup:
        raise ProfilerCapabilitySchemaError(f"profiler evidence row {api_uri} requires cleanup proof")
    if not bool(cleanup.get("capture_stopped")):
        raise ProfilerCapabilitySchemaError(f"profiler evidence row {api_uri} must prove capture cleanup")
    if "subscriptions_cleared" in cleanup and not bool(cleanup["subscriptions_cleared"]):
        raise ProfilerCapabilitySchemaError(f"profiler evidence row {api_uri} must prove subscription cleanup")

    observed_fields = row["observed_payload_fields"]
    blocker = row["missing_payload_blocker"]
    has_observed_fields = isinstance(observed_fields, Sequence) and not isinstance(observed_fields, (str, bytes)) and bool(observed_fields)
    has_blocker = isinstance(blocker, str) and bool(blocker.strip())
    if not has_observed_fields and not has_blocker:
        raise ProfilerCapabilitySchemaError(
            f"profiler evidence row {api_uri} requires observed payload fields or an exact missing-payload blocker"
        )
    if has_observed_fields:
        topic = _require_non_empty_string(row, "observed_topic_or_log_uri")
        if not topic.startswith("ak."):
            raise ProfilerCapabilitySchemaError(f"profiler evidence row {api_uri} has invalid observed topic {topic!r}")
    if has_blocker:
        lowered = blocker.lower()
        if any(marker in lowered for marker in PLACEHOLDER_BLOCKER_MARKERS):
            raise ProfilerCapabilitySchemaError(
                f"profiler evidence row {api_uri} blocker must be an exact observed blocker, not placeholder text"
            )
        if not any(term in lowered for term in ("payload", "topic", "prerequisite", "wwiseconsole", "headless")):
            raise ProfilerCapabilitySchemaError(
                f"profiler evidence row {api_uri} blocker must name the missing payload/topic prerequisite"
            )
    proof_text = " ".join(str(row.get(field, "")) for field in ("observed_topic_or_log_uri", "missing_payload_blocker"))
    if any(marker in proof_text.lower() for marker in INSUFFICIENT_PROOF_MARKERS) and not has_blocker:
        raise ProfilerCapabilitySchemaError(f"profiler evidence row {api_uri} uses insufficient proof: {proof_text}")


def validate_profiler_capability_resource(resource: Mapping[str, Any]) -> None:
    """Validate the Task 3 capability resource and ensure it does not promote APIs."""

    metadata = resource.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ProfilerCapabilitySchemaError("profiler capability resource missing metadata")
    if metadata.get("promotes_coverage") is not False:
        raise ProfilerCapabilitySchemaError("Task 3 capability resource must not promote coverage")
    evidence_root = metadata.get("evidence_root")
    if not isinstance(evidence_root, str) or not evidence_root.endswith("wwise-waapi-deferred-reevaluation/"):
        raise ProfilerCapabilitySchemaError("Task 3 evidence root must be deferred-reevaluation")

    case_count = 0
    for group_name in ("profiler_transport_cases", "soundengine_cases"):
        cases = resource.get(group_name)
        if not isinstance(cases, list) or not cases:
            raise ProfilerCapabilitySchemaError(f"profiler capability resource missing {group_name}")
        for case in cases:
            _validate_case(case)
            case_count += 1
    if case_count == 0:
        raise ProfilerCapabilitySchemaError("profiler capability resource contains no cases")


def safe_profiler_capability_evidence_path(repo_root: Path, evidence_root: Path, path: str) -> Path:
    """Localize resource provenance below the caller-owned Task 3 runtime root."""

    del repo_root  # Historical provenance is never resolved relative to the checkout.
    try:
        target = localize_runtime_evidence_path(evidence_root, path)
    except RuntimeEvidencePathError as exc:
        raise ProfilerCapabilitySchemaError(str(exc)) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _validate_case(case: Mapping[str, Any]) -> None:
    case_id = _require_non_empty_string(case, "id")
    status = _require_non_empty_string(case, "status")
    if status in PROMOTION_STATUS_VALUES:
        raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} must not promote status {status!r}")
    if status not in CAPABILITY_STATUS_VALUES:
        raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} has invalid capability status {status!r}")
    evidence_path = _require_non_empty_string(case, "evidence_path")
    accepted_evidence_roots = (
        ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/",  # historical committed provenance
        ".waapi-skill-state/evidence/wwise-waapi-deferred-reevaluation/",  # current writer
    )
    if not evidence_path.startswith(accepted_evidence_roots):
        raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} has wrong evidence path {evidence_path!r}")
    for field in ("capture_sequence", "cleanup", "assertions", "uris"):
        values = case.get(field)
        if not isinstance(values, list) or not values:
            raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} missing non-empty {field}")
    trigger = case.get("trigger")
    if not isinstance(trigger, Mapping) or float(trigger.get("bounded_wait_seconds", 0)) <= 0:
        raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} missing bounded trigger")
    rows = case.get("evidence_rows")
    if not isinstance(rows, list) or not rows:
        raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} missing evidence rows")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ProfilerCapabilitySchemaError(f"Task 3 case {case_id} has non-mapping evidence row")
        validate_profiler_evidence_row(row)
        _validate_case_row_status_consistency(case_id, status, row)


def _validate_case_row_status_consistency(case_id: str, status: str, row: Mapping[str, Any]) -> None:
    observed_fields = row["observed_payload_fields"]
    blocker = row["missing_payload_blocker"]
    has_observed_fields = isinstance(observed_fields, Sequence) and not isinstance(observed_fields, (str, bytes)) and bool(observed_fields)
    has_blocker = isinstance(blocker, str) and bool(blocker.strip())
    if status == "capability-observed":
        if not has_observed_fields:
            raise ProfilerCapabilitySchemaError(
                f"Task 3 case {case_id} status capability-observed requires observed payload fields"
            )
        if has_blocker:
            raise ProfilerCapabilitySchemaError(
                f"Task 3 case {case_id} status capability-observed cannot carry a missing-payload blocker"
            )
    if status == "capability-blocked":
        if has_observed_fields:
            raise ProfilerCapabilitySchemaError(
                f"Task 3 case {case_id} status capability-blocked cannot carry placeholder observed payload fields"
            )
        if not has_blocker:
            raise ProfilerCapabilitySchemaError(
                f"Task 3 case {case_id} status capability-blocked requires an exact missing-payload blocker"
            )


def _require_non_empty_string(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProfilerCapabilitySchemaError(f"profiler evidence row missing non-empty {field}")
    return value.strip()


__all__ = [
    "CAPABILITY_STATUS_VALUES",
    "PROMOTION_STATUS_VALUES",
    "ProfilerCapabilitySchemaError",
    "REQUIRED_EVIDENCE_ROW_FIELDS",
    "safe_profiler_capability_evidence_path",
    "validate_profiler_capability_resource",
    "validate_profiler_evidence_row",
]

"""Developer-owned real Gateway goal probes for selected expansion cases."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import (
    ExpansionCaseContext,
    PreparedExpansionCase,
)
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft,
    CaseBoundaryError,
    file_evidence,
)


_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaseBoundaryError(f"goal probe requires one exact {label}")
    return value


def _m01_goal_draft(ctx: ExpansionCaseContext,
                    prepared: PreparedExpansionCase) -> BusinessDraft:
    parameters = prepared.archive_preview_parameters
    before = prepared.before
    parent = before.get("parent")
    media_raw = parameters.get("media")
    expected_hashes = prepared.archive_oracle_parameters.get("expected_hashes")
    version = parameters.get("version")
    parent_path = parameters.get("parent_path")
    segment_name = parameters.get("segment_name")
    if (prepared.operation != "audio.import" or not isinstance(parent, Mapping)
            or not isinstance(media_raw, Mapping) or set(media_raw) != {"Quiet", "Full"}
            or not isinstance(expected_hashes, Mapping)
            or set(expected_hashes) != {"Quiet", "Full"}
            or version != ctx.version or not isinstance(parent_path, str)
            or parent.get("path") != parent_path or not isinstance(segment_name, str)
            or not segment_name):
        raise CaseBoundaryError("M01 prepared case does not seal the exact batch goal")
    parent_id = _required_string(parent.get("id"), "Music parent GUID")
    if not _GUID.fullmatch(parent_id):
        raise CaseBoundaryError("M01 parent identity is not a canonical GUID")
    media: dict[str, Path] = {}
    for name in ("Quiet", "Full"):
        raw_path = media_raw[name]
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise CaseBoundaryError("M01 media path is not an absolute fixture file")
        path = Path(raw_path)
        evidence = file_evidence(ctx, str(path))
        expected_hash = expected_hashes.get(name)
        if (not isinstance(expected_hash, str)
                or evidence.get("sha256") != expected_hash):
            raise CaseBoundaryError(f"M01 {name} media differs from its sealed fixture hash")
        media[name] = path
    if media["Quiet"].parent != media["Full"].parent:
        raise CaseBoundaryError("M01 one-batch media files must share the disclosed directory")

    draft = BusinessDraft(ctx, "audio.import")
    parent_handle = draft.bind(object_id=parent_id)
    draft.step(
        "draft-declare-import-batch",
        "--row-order", "segment", "quiet", "full",
        "--new-row", "segment", parent_handle, segment_name, "music-segment",
        "--new-row", "quiet", "segment", "Quiet", "music-track",
        "--new-row", "full", "segment", "Full", "music-track",
        "--media-directory", str(media["Quiet"].parent),
        "--media-file", "quiet", media["Quiet"].name,
        "--media-file", "full", media["Full"].name,
        "--field", "quiet", "volume_db", "-6",
    )
    return draft


def _c06_goal_draft(ctx: ExpansionCaseContext,
                    prepared: PreparedExpansionCase) -> BusinessDraft:
    parameters = prepared.archive_preview_parameters
    before = prepared.before
    rtpcs = before.get("rtpcs")
    owner_id = parameters.get("owner_id")
    control_id = parameters.get("control_id")
    target_id = parameters.get("target_id")
    expected_notes = parameters.get("expected_notes")
    if (prepared.operation != "object.setRTPC" or parameters.get("version") != ctx.version
            or not isinstance(rtpcs, Mapping) or not isinstance(owner_id, str)
            or not _GUID.fullmatch(owner_id) or not isinstance(control_id, str)
            or not _GUID.fullmatch(control_id) or not isinstance(target_id, str)
            or not _GUID.fullmatch(target_id) or not isinstance(expected_notes, str)):
        raise CaseBoundaryError("C06 prepared case does not seal the exact RTPC goal")
    target = rtpcs.get(target_id)
    control = target.get("@ControlInput") if isinstance(target, Mapping) else None
    target_control_id = control.get("id") if isinstance(control, Mapping) else control
    if (not isinstance(target, Mapping) or target.get("id") != target_id
            or target.get("@PropertyName") != "Volume" or target_control_id != control_id
            or target.get("notes") != expected_notes):
        raise CaseBoundaryError("C06 sealed target is not the existing Volume RTPC with preserved notes")

    draft = BusinessDraft(ctx, "object.setRTPC")
    owner_handle = draft.bind(object_id=owner_id)
    field_handle = draft.discover_field(owner_handle, "volume")
    control_handle = draft.bind(object_id=control_id)
    arguments = ["--object-handle", owner_handle, "--field-handle", field_handle,
                 "--control-input-handle", control_handle, "--mode", "add-or-update",
                 "--notes", expected_notes]
    for x, y, shape in ((0, -48, "Linear"), (50, -6, "Linear"), (100, 0, "Linear")):
        arguments.extend(("--point", str(x), str(y), shape))
    draft.step("draft-declare-rtpc", *arguments)
    return draft


def build_goal_draft(ctx: ExpansionCaseContext, case_id: str,
                     prepared: PreparedExpansionCase) -> BusinessDraft:
    if case_id == "M01":
        return _m01_goal_draft(ctx, prepared)
    if case_id == "C06":
        return _c06_goal_draft(ctx, prepared)
    raise CaseBoundaryError(f"no reviewed Gateway goal recipe for {case_id}")


def review_approve_execute_verify(
    draft: BusinessDraft,
    prepared: PreparedExpansionCase,
) -> Mapping[str, Any]:
    """Create one immutable Preview and require adapter approval before authorization."""
    draft.step("draft-check")
    preview = draft.step("preview-from-draft")
    transaction_id = preview.get("transaction_id")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise CaseBoundaryError("goal Preview did not return one transaction identity")
    shown = draft.ctx.gateway(["transaction-show", transaction_id])
    artifact = shown.get("artifact")
    artifact_hash = shown.get("artifact_hash")
    if (shown.get("transaction_id") != transaction_id
            or not isinstance(artifact_hash, str) or not artifact_hash
            or not isinstance(artifact, Mapping)):
        raise CaseBoundaryError("goal Preview did not expose its immutable artifact")
    if prepared.approve_preview(artifact) is not True:
        raise CaseBoundaryError("prepared case adapter did not approve the immutable goal Preview")
    confirmation = shown.get("confirmation")
    if (shown.get("state") != "awaiting_confirmation" or not isinstance(confirmation, Mapping)
            or not isinstance(confirmation.get("token"), str) or not confirmation["token"]):
        raise CaseBoundaryError("approved goal Preview has no explicit confirmation token")
    confirmed = draft.ctx.gateway([
        "confirm", transaction_id, "--confirmation-token", confirmation["token"],
    ])
    if confirmed.get("state") != "confirmed":
        raise CaseBoundaryError("approved goal Preview did not enter confirmed state")
    executed = draft.ctx.gateway(["execute", transaction_id])
    if executed.get("state") != "executed_unverified":
        raise CaseBoundaryError("goal mutation did not return its one unverified execution receipt")
    verified = draft.ctx.gateway(["verify", transaction_id])
    evidence = verified.get("verification")
    if (verified.get("state") != "verified" or not isinstance(evidence, Mapping)
            or evidence.get("business_state_verified") is not True):
        raise CaseBoundaryError("Gateway did not provide strong business verification for the goal")
    return {
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "gateway_verification_state": verified.get("state"),
        "business_state_verified": evidence["business_state_verified"],
    }


def _snapshot_digest(prepared: PreparedExpansionCase) -> str:
    try:
        encoded = json.dumps(prepared.before, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CaseBoundaryError("prepared goal baseline is not canonical finite JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def run_goal_probe(
    ctx: ExpansionCaseContext,
    case_id: str,
    prepared: PreparedExpansionCase,
    gateway_receipts: list[dict[str, Any]],
) -> Mapping[str, Any]:
    """Execute one adapter-approved goal and independently verify its full outcome."""
    if not prepared.required_assertions or not prepared.read_object_ids:
        raise CaseBoundaryError("goal probe needs the adapter's complete verifier and read scope")
    before_hash = _snapshot_digest(prepared)
    snapshot_start = len(gateway_receipts)
    baseline_one = prepared.snapshot()
    baseline_two = prepared.snapshot()
    if any(
        row.get("argv", [None])[0] not in {"query-object", "metadata", "status"}
        for row in gateway_receipts[snapshot_start:]
    ):
        raise CaseBoundaryError("independent pre-goal snapshot used a non-read Gateway command")
    try:
        digest_one = hashlib.sha256(json.dumps(
            baseline_one, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        digest_two = hashlib.sha256(json.dumps(
            baseline_two, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise CaseBoundaryError("independent pre-goal snapshot is not finite JSON") from exc
    if digest_one != before_hash or digest_two != before_hash:
        raise CaseBoundaryError("independent pre-goal reads differ from the sealed adapter baseline")

    goal_call_start = len(gateway_receipts)
    draft = build_goal_draft(ctx, case_id, prepared)
    transaction = review_approve_execute_verify(draft, prepared)
    goal_commands = [
        row.get("argv", [None])[0]
        for row in gateway_receipts[goal_call_start:]
        if isinstance(row.get("argv"), list) and row["argv"]
    ]
    if any(goal_commands.count(command) != 1 for command in (
        "draft-check", "preview-from-draft", "transaction-show", "confirm", "execute", "verify",
    )):
        raise CaseBoundaryError("goal transaction did not follow one checked, approved, single-execute lifecycle")

    after = prepared.snapshot()
    assertions = prepared.verify(prepared.before, after)
    if (set(assertions) != prepared.required_assertions
            or any(type(value) is not bool for value in assertions.values())
            or not all(assertions.values())):
        raise CaseBoundaryError(f"independent after-state did not prove every goal assertion: {assertions}")
    return {
        "case_id": case_id,
        "before_sha256": before_hash,
        "after_sha256": hashlib.sha256(json.dumps(
            after, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
        "transaction_id": transaction["transaction_id"],
        "artifact_hash": transaction["artifact_hash"],
        "gateway_verification_state": transaction["gateway_verification_state"],
        "business_state_verified": True,
        "business_effect_verified": True,
        "assertions": dict(assertions),
        "goal_gateway_commands": goal_commands,
        "agent_pass": False,
    }

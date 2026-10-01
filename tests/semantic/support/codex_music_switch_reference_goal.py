"""One developer-owned existing Music Switch reference-maintenance probe."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Mapping

from tests.semantic.support.codex_expansion_case_helpers import BusinessDraft, CaseBoundaryError, file_evidence
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_music_oracle_probes import SWITCH
from tests.semantic.support.codex_filesystem_security import (
    path_is_link_or_reparse, read_bounded_exclusive_regular_file,
)


ENTRY = "{903A30EC-F1F4-49FF-9CBC-99B89539598B}"
FIGHT = "{1D0ECA1F-2749-4DBB-B92C-0DBDFDA7A825}"
MAX_SNAPSHOT_CALLS = 64
MEDIA_PREPARATION_REPORT_BYTES = 128 * 1024


MEDIA_DONOR = Path("Originals/SFX/WAAPI Skill Integration V2/audit_clean.wav")
MEDIA_DONOR_SHA256 = "b1b29883097591b1de9a67ea780e0a2fef53784d2cd389c11d94bcaa0d695a97"


def _confined_media_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise CaseBoundaryError("media preparation path escapes its owned root")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            linked = path_is_link_or_reparse(cursor)
        except FileNotFoundError:
            linked = False
        if linked:
            raise CaseBoundaryError("media preparation cannot traverse links or reparse points")
        if cursor.exists() and cursor != root / relative and not cursor.is_dir():
            raise CaseBoundaryError("media preparation parent is not a directory")
    return cursor


def prepare_music_switch_reference_media(ctx, owned_wwu: Path, source_project: Path, *, evidence: dict[str, Any] | None = None) -> Mapping[str, Any]:
    """Fill missing legacy Originals in the private copy before any goal baseline."""
    owned = ctx.project_path.parent
    source = source_project.parent
    if (ctx.version != "2025.1" or owned == source or not owned.is_absolute() or not source.is_absolute()
            or source in owned.parents or owned in source.parents
            or owned.resolve(strict=True) != owned or source.resolve(strict=True) != source
            or ctx.project_path.name != "SampleProject.wproj" or source_project.name != "SampleProject.wproj"):
        raise CaseBoundaryError("media preparation requires a separate owned 2025.1 project")
    if path_is_link_or_reparse(owned) or path_is_link_or_reparse(source):
        raise CaseBoundaryError("media preparation roots cannot be linked")
    relative = Path("Containers/Music/Music.wwu")
    if owned_wwu != _confined_media_path(owned, relative):
        raise CaseBoundaryError("media preparation requires the exact owned Music WWU")
    def bounded(path, maximum):
        return read_bounded_exclusive_regular_file(path, max_bytes=maximum, require_private_posix_mode=False).raw
    raw = bounded(owned_wwu, 8 * 1_048_576)
    source_raw = bounded(_confined_media_path(source, relative), 8 * 1_048_576)
    if raw != source_raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise CaseBoundaryError("media preparation requires unchanged source-bound XML without entities")
    roots = [node for node in ET.fromstring(raw).iter("MusicSwitchContainer") if node.get("ID") == SWITCH]
    if len(roots) != 1:
        raise CaseBoundaryError("media preparation has no exact Music Switch owner")
    nodes = list(roots[0].iter("AudioFileSource"))
    if not 1 <= len(nodes) <= 128:
        raise CaseBoundaryError("music source set exceeds its fixture ceiling")
    paths, ids, destinations = {}, set(), {}
    for node in nodes:
        identifier, filename = node.get("ID"), node.findtext("AudioFile")
        if (not isinstance(identifier, str) or not re.fullmatch(r"\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", identifier)
                or identifier in ids or node.findtext("Language") != "SFX" or not isinstance(filename, str)):
            raise CaseBoundaryError("music media requires unique canonical source identities and SFX paths")
        parts = filename.split("\\")
        if (not 1 <= len(parts) <= 16 or any(not part or part in {".", ".."} or any(char in part for char in "/:\x00")
                                          or part.endswith((" ", ".")) for part in parts) or not parts[-1].lower().endswith(".wav")):
            raise CaseBoundaryError("music media path contains unsupported or escaping segments")
        target = _confined_media_path(owned, Path("Originals/SFX", *parts))
        folded = str(target).casefold()
        if folded in destinations and destinations[folded] != target:
            raise CaseBoundaryError("music media paths alias the same destination")
        destinations[folded] = target
        ids.add(identifier)
        paths.setdefault(target, []).append(identifier)  # Shared media references copy one file.
    source_donor = _confined_media_path(source, MEDIA_DONOR)
    donor = bounded(source_donor, 32 * 1_048_576)
    if hashlib.sha256(donor).hexdigest() != MEDIA_DONOR_SHA256:
        raise CaseBoundaryError("fixture donor differs from its pinned WAV hash")
    owned_donor = _confined_media_path(owned, MEDIA_DONOR)
    if bounded(owned_donor, 32 * 1_048_576) != donor:
        raise CaseBoundaryError("owned donor differs from the fixed source WAV")
    # Validate all existing inputs before writing; never replace their bytes.
    existing = {path: hashlib.sha256(bounded(path, 32 * 1_048_576)).hexdigest()
                for path in paths if path.exists()}
    project_raw = bounded(_confined_media_path(source, Path(source_project.name)), 1_048_576)
    report = evidence if evidence is not None else {}
    report.update({"source_project": str(source_project), "source_project_sha256": hashlib.sha256(project_raw).hexdigest(),
        "source_wwu_sha256": hashlib.sha256(source_raw).hexdigest(), "source_object_count": len(nodes),
        "donor": {"path": str(source_donor), "sha256": MEDIA_DONOR_SHA256, "bytes": len(donor)},
        "created_count": 0, "files": []})
    for path, source_ids in paths.items():
        created = path not in existing
        row = {"path": str(path), "source_ids": source_ids, "created": False,
               "creation_requested": created, "verified": False, "sha256": None, "bytes": None}
        prospective = {**report, "files": [*report["files"], {**row, "sha256": "f" * 64, "bytes": 32 * 1_048_576}]}
        if len(json.dumps(prospective, ensure_ascii=False).encode("utf-8")) > MEDIA_PREPARATION_REPORT_BYTES:
            raise CaseBoundaryError("media preparation evidence exceeds its byte ceiling")
        report["files"].append(row)
        if created:
            cursor = owned
            for part in path.parent.relative_to(owned).parts:
                cursor = cursor / part
                try:
                    cursor.mkdir()
                except FileExistsError:
                    pass
                _confined_media_path(owned, cursor.relative_to(owned))
                if not cursor.is_dir():
                    raise CaseBoundaryError("media preparation parent is not a directory")
            _confined_media_path(owned, path.relative_to(owned))
            # Exclusive creation cannot overwrite a file appearing after preflight.
            with path.open("xb") as output:
                output.write(donor)
            row["created"] = True
            report["created_count"] += 1
        observed = bounded(path, 32 * 1_048_576)
        if not observed:
            raise CaseBoundaryError("protected music media cannot be empty")
        digest = hashlib.sha256(observed).hexdigest()
        expected_digest = MEDIA_DONOR_SHA256 if created else existing[path]
        if digest != expected_digest:
            raise CaseBoundaryError("prepared media bytes drifted before the independent baseline")
        row.update({"bytes": len(observed), "sha256": digest, "verified": True})
    if bounded(owned_wwu, 8 * 1_048_576) != raw:
        raise CaseBoundaryError("media preparation changed its owned XML")
    return report


def append_bounded_goal_receipt(receipts, argv, code, payload, *, max_total_bytes=8 * 1_048_576):
    """Reserve failure-report space before retaining any full Gateway receipt."""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    receipt = {"argv": list(argv), "exit_code": code, "payload": payload}
    prospective_bytes = len(json.dumps([*receipts, receipt], ensure_ascii=False).encode("utf-8"))
    reserve = min(1024, max_total_bytes // 2)
    if len(encoded) > 1_048_576 or prospective_bytes > max_total_bytes - reserve:
        descriptor = {"error": "goal_receipt_overflow", "exit_code": code,
            "payload_bytes": len(encoded), "payload_sha256": hashlib.sha256(encoded).hexdigest()}
        if len(json.dumps([*receipts, descriptor], ensure_ascii=False).encode("utf-8")) <= max_total_bytes - reserve // 2:
            receipts.append(descriptor)
        raise CaseBoundaryError("goal evidence exceeds total byte ceiling")
    receipts.append(receipt)


def approve_music_switch_reference_preview(artifact: Mapping[str, Any]) -> bool:
    request = artifact.get("request")
    return isinstance(request, Mapping) and request.get("version") == "2025.1" and (
        request.get("operation") == "object.setReference" and request.get("arguments") == {
            "object": {"kind": "id", "value": ENTRY}, "reference": "AudioNode",
            "target": {"kind": "id", "value": FIGHT}})


def _without_audio_node(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return {**row, "references": {key: value for key, value in row.get("references", {}).items()
                                   if key != "AudioNode"}}


def verify_music_switch_reference_goal(before: Mapping[str, Any], after: Mapping[str, Any],
                                       witness: Mapping[str, Any]) -> Mapping[str, bool]:
    data = witness["music_switch"]
    expected_ids = [row["entry_id"] for row in data["mappings"]]
    expected_arguments = dict(zip(data["argument_slots"], data["groups"]))
    expected_paths = {row["entry_id"]: row["slots"] for row in data["mappings"]}
    expected_conditions = {slot: value for row in data["mappings"] for slot, value in zip(row["slots"], row["conditions"])}
    valid = bool(len(expected_ids) == len(set(expected_ids)) == 9 and len(expected_arguments) == 2 and len(expected_conditions) == 18
        and ENTRY in expected_ids and all(isinstance(value.get("entries"), Mapping)
            and set(value["entries"]) == set(expected_ids)
            and isinstance(value.get("entry_ids"), list) and len(value["entry_ids"]) == 9
            and set(value["entry_ids"]) == set(expected_ids) for value in (before, after)))
    old, new = before.get("entries", {}).get(ENTRY, {}), after.get("entries", {}).get(ENTRY, {})
    before_targets_match = valid and all(before["entries"][row["entry_id"]].get("references", {}).get("AudioNode", {}).get("id") == row["target"]
                                        for row in data["mappings"])
    return {
        "baseline_complete_and_bound": bool(before_targets_match),
        "selected_audio_node_matches": bool(valid and new.get("references", {}).get("AudioNode", {}).get("id") == FIGHT),
        "selected_entry_other_fields_preserved": bool(valid and _without_audio_node(old) == _without_audio_node(new)),
        "other_eight_entries_preserved": bool(valid and all(before["entries"][key] == after["entries"][key] for key in expected_ids if key != ENTRY)),
        "two_argument_references_preserved": bool(before.get("arguments") == after.get("arguments") == expected_arguments),
        "eighteen_condition_references_preserved": bool(before.get("conditions") == after.get("conditions") == expected_conditions),
        "entry_members_complete_and_unique": valid,
        "condition_dimension_positions_preserved": bool(before.get("argument_slots") == after.get("argument_slots") == data["argument_slots"]
            and before.get("paths") == after.get("paths") == expected_paths),
        "owner_preserved": bool(before.get("owner") and before.get("owner") == after.get("owner")),
        "protected_music_contents_preserved": bool(before.get("protected_contents") and before.get("protected_contents") == after.get("protected_contents")),
        "protected_media_preserved": bool(before.get("media") and before.get("media") == after.get("media")),
        "unsaved_owned_wwu_unchanged": before.get("wwu_sha256") == after.get("wwu_sha256") == witness["wwu_sha256"],
    }


def music_switch_reference_snapshot(ctx, witness: Mapping[str, Any], disk_witness: Callable) -> Mapping[str, Any]:
    """Closed public reads plus bounded owned-media hashes; never native calls."""
    if ctx.version != "2025.1":
        raise CaseBoundaryError("existing-entry reference goal is reviewed only for 2025.1")
    ctx.gateway(["query-schema", "--advanced"])
    calls = 0
    def read(argv):
        nonlocal calls
        calls += 1
        if calls > MAX_SNAPSHOT_CALLS:
            raise CaseBoundaryError("reference snapshot exceeds its fixed call ceiling")
        payload = ctx.gateway(argv)
        rows = payload.get("objects")
        if (payload.get("ok") is not True or payload.get("status") != "ok" or not isinstance(rows, list)
                or type(payload.get("count")) is not int or payload["count"] != len(rows)
                or len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 1_048_576
                or any(not isinstance(row, Mapping) or not isinstance(row.get("id"), str) for row in rows)
                or len({row["id"] for row in rows}) != len(rows)):
            raise CaseBoundaryError("reference snapshot has no complete bounded identity rows")
        cap = int(argv[argv.index("--max-results") + 1]) if "--max-results" in argv else 1
        expected_bound = ({"mode": "gateway-appended-take", "value": cap} if "--advanced-waql" in argv
                          else {"mode": "take", "value": cap} if "--max-results" in argv else {"mode": "exact-object"})
        if payload.get("query_bound") != expected_bound or payload.get("limit_reached") is True or (
                "--max-results" in argv and len(rows) >= cap):
            raise CaseBoundaryError("reference snapshot reached or changed its row ceiling")
        return rows
    def exact(identifier, fields=(), includes=()):
        rows = read(["query-object", "--exact-id", identifier,
            *(part for field in fields for part in ("--include-field", field)),
            *(part for value in includes for part in ("--include", value))])
        if len(rows) != 1 or rows[0]["id"] != identifier:
            raise CaseBoundaryError("reference snapshot exact identity changed")
        return rows[0]
    def collection(identifier, field, expected, cap):
        rows = read(["query-object", "--advanced-waql", f'from object "{identifier}" select @{field}', "--max-results", str(cap)])
        ids = [row["id"] for row in rows]
        if set(ids) != set(expected):
            raise CaseBoundaryError("reference snapshot collection differs from the complete fixture")
        return ids
    data = witness["music_switch"]
    arguments = {}
    argument_slots = collection(SWITCH, "Arguments", data["argument_slots"], 4)
    for slot in argument_slots:
        row = exact(slot, ("Argument",))
        arguments[slot] = row.get("references", {}).get("Argument", {}).get("id")
    entry_ids = collection(SWITCH, "Entries", [row["entry_id"] for row in data["mappings"]], 16)
    entries, paths, conditions = {}, {}, {}
    for baseline in data["mappings"]:
        identifier = baseline["entry_id"]
        row = exact(identifier, ("AudioNode", "Probability", "Weight"))
        if (set(row.get("properties", {})) != {"Probability", "Weight"}
                or any(type(value) is not int or not 0 <= value <= 100 for value in row["properties"].values())
                or set(row.get("references", {})) != {"AudioNode"}):
            raise CaseBoundaryError("reference snapshot omitted the exact entry configuration")
        entries[identifier] = row
        paths[identifier] = collection(identifier, "EntryPath", baseline["slots"], 4)
        for slot in paths[identifier]:
            conditions[slot] = exact(slot, ("EntryPathObject",)).get("references", {}).get("EntryPathObject", {}).get("id")
    owner = exact(SWITCH, ("ContinuePlay", "Mode"), ("notes", "volume-db", "output-bus", "work-unit"))
    exact(FIGHT)
    contents = read(["query-object", "--exact-id", SWITCH, "--relationship", "descendants", "--max-results", "1000",
        *(part for field in ("notes", "volume-db", "pitch-cents", "output-bus", "active-source", "original-file-path", "included", "child-count")
          for part in ("--include", field))])
    protected = sorted(({key: value for key, value in row.items() if row["id"] != ENTRY or key not in {"name", "path"}}
                        for row in contents), key=lambda row: row["id"])
    media = {}
    for row in contents:
        if row.get("type") != "AudioFileSource":
            continue
        path = row.get("original_file_path")
        if not isinstance(path, str) or not path:
            raise CaseBoundaryError("protected AudioFileSource has no original media path")
        if path not in media:
            if len(media) >= 128:
                raise CaseBoundaryError("protected music media exceeds its file ceiling")
            media[path] = file_evidence(ctx, path)
    if not media:
        raise CaseBoundaryError("reference goal requires protected source-media evidence")
    return {"owner": owner, "argument_slots": argument_slots, "arguments": arguments,
        "entry_ids": entry_ids, "entries": entries, "paths": paths, "conditions": conditions,
        "protected_contents": protected, "media": media, "wwu_sha256": disk_witness()["wwu_sha256"]}


def run_music_switch_reference_goal(ctx, witness: Mapping[str, Any], snapshot: Callable) -> Mapping[str, Any]:
    if ctx.version != "2025.1":
        raise CaseBoundaryError("reference maintenance goal has no reviewed earlier-version lane")
    ctx.gateway(["operation-schema", "object.setReference"])
    before = snapshot()
    baseline_checks = verify_music_switch_reference_goal(before, before, witness)
    if not all(value is True for key, value in baseline_checks.items() if key != "selected_audio_node_matches"):
        raise CaseBoundaryError("reference goal does not start from its complete sealed mapping/protection baseline")
    draft = BusinessDraft(ctx, "object.setReference")
    entry_handle = draft.bind(object_id=ENTRY)
    field_handle = draft.discover_field(entry_handle, "AudioNode")
    target_handle = draft.bind(object_id=FIGHT)
    draft.step("draft-declare-field-change", "--object-handle", entry_handle,
        "--field-handle", field_handle, "--target-handle", target_handle)
    draft.step("draft-check")
    preview = draft.step("preview-from-draft")
    transaction_id = preview["transaction_id"]
    shown = ctx.gateway(["transaction-show", transaction_id])
    artifact = shown.get("artifact")
    if (shown.get("transaction_id") != transaction_id or not isinstance(artifact, Mapping)
            or shown.get("artifact_hash") != canonical_digest(artifact)
            or not approve_music_switch_reference_preview(artifact)):
        raise CaseBoundaryError("reference Preview is not exactly the selected AudioNode change")
    preview_baseline = snapshot()
    # Entries is an unordered query result; keep its observed order in evidence.
    # Argument and EntryPath positions identify condition dimensions and stay exact.
    if ({**preview_baseline, "entry_ids": sorted(preview_baseline["entry_ids"])}
            != {**before, "entry_ids": sorted(before["entry_ids"])}):
        raise CaseBoundaryError("reference preparation or Preview changed its protected baseline")
    token = shown.get("confirmation", {}).get("token")
    if shown.get("state") != "awaiting_confirmation" or not isinstance(token, str) or not token:
        raise CaseBoundaryError("reference goal has no exact explicit-confirmation boundary")
    confirmed = ctx.gateway(["confirm", transaction_id, "--confirmation-token", token])
    if confirmed.get("state") != "confirmed":
        raise CaseBoundaryError("reference goal confirmation failed")
    executed = ctx.gateway(["execute", transaction_id])
    if (executed.get("state") != "executed_unverified" or executed.get("transaction_id") != transaction_id
            or executed.get("artifact_hash") != shown["artifact_hash"]):
        raise CaseBoundaryError("reference execution did not complete; never retry")
    verified = ctx.gateway(["verify", transaction_id])
    if (verified.get("state") != "verified" or verified.get("transaction_id") != transaction_id
            or verified.get("artifact_hash") != shown["artifact_hash"]
            or verified.get("verification", {}).get("business_state_verified") is not True):
        raise CaseBoundaryError("reference goal lacks strong Gateway verification")
    after = snapshot()
    checks = verify_music_switch_reference_goal(before, after, witness)
    if not all(value is True for value in checks.values()):
        raise CaseBoundaryError(f"reference goal failed independent preservation: {checks}")
    return {"transaction_id": transaction_id, "artifact_hash": shown["artifact_hash"],
        "gateway_verification_state": "verified", "gateway_business_state_verified": True,
        "selected_reference_effect_verified": True, "assertions": dict(checks), "before": before, "after": after,
        "agent_pass": False, "business_effect_verified": False, "complete_workflow_verified": False,
        "order_is_authoritative": False,
        "scope": "existing_selected_reference_and_preservation_only_order_authority_unproven"}

"""Closed read plans and XML witnesses for developer music investigations."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_filesystem_security import read_bounded_exclusive_regular_file


PLAYLIST = "{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}"
SWITCH = "{A9D070F3-3BD9-49EB-9D8B-5D3312173FB4}"
TRANSITION_ROOT = "{8A6F5BFD-8784-474D-8BDE-6460595AA1FC}"
TRANSITION = "{E49EF1AA-29FB-40F1-B343-523AF28244AE}"
FADE = "{0FC1E836-74BB-43AB-B417-6C9D16AE5636}"
MAX_CALLS = 96
MAX_RECEIPT_BYTES = 1_048_576
MAX_REPORT_BYTES = 8 * 1_048_576


class MusicOracleProbeError(ValueError):
    """An investigation cannot retain bounded, identity-bound evidence."""


def _one(root: ET.Element, tag: str, identifier: str) -> ET.Element:
    rows = [node for node in root.iter(tag) if node.get("ID") == identifier]
    if len(rows) != 1:
        raise MusicOracleProbeError(f"expected one {tag} identity {identifier}")
    return rows[0]


def _references(nodes: Sequence[ET.Element]) -> list[str]:
    values = [node.get("ID") for node in nodes]
    if any(not isinstance(value, str) or not value for value in values):
        raise MusicOracleProbeError("fixture reference has no identity")
    return values


def xml_music_witness(path: Path, version: str) -> Mapping[str, Any]:
    """Read one owned WWU; saved order is evidence, never a live-order claim."""
    if version not in {"2022.1", "2025.1"}:
        raise MusicOracleProbeError("unsupported music investigation version")
    raw = read_bounded_exclusive_regular_file(
        path, max_bytes=8 * 1_048_576, require_private_posix_mode=False,
    ).raw
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise MusicOracleProbeError("WWU must not contain external/entity declarations")
    root = ET.fromstring(raw)
    playlist = _one(root, "MusicPlaylistContainer", PLAYLIST)
    if version == "2022.1":
        playlist_root = playlist.find("./Playlist/MusicPlaylistItem")
    else:
        playlist_root = playlist.find("./ReferenceList/Reference[@Name='PlaylistRoot']/Custom/MusicPlaylistItem")
    if playlist_root is None:
        raise MusicOracleProbeError("fixture has no owned Playlist root")
    items = playlist_root.findall("./ChildrenList/MusicPlaylistItem")
    playlist_rows = []
    for item in items:
        refs = (item.findall("./SegmentRef") if version == "2022.1" else
                item.findall("./ReferenceList/Reference[@Name='Segment']/ObjectRef"))
        playlist_rows.append({"id": item.get("ID"), "segments": _references(refs)})
    owner = _one(root, "MusicSwitchContainer", SWITCH)
    if version == "2022.1":
        groups = _references(owner.findall("./ArgumentList/ArgumentRef"))
        entries = owner.findall("./EntryList/Entry")
    else:
        groups = _references(owner.findall("./ObjectLists/ObjectList[@Name='Arguments']/PluginInnerObject/ReferenceList/Reference[@Name='Argument']/ObjectRef"))
        entries = owner.findall("./ObjectLists/ObjectList[@Name='Entries']/MultiSwitchEntry")
    mappings = []
    for entry in entries:
        if version == "2022.1":
            conditions = _references(entry.findall("./Path/PathElementRef"))
            targets = _references(entry.findall("./AudioNodeInfo/AudioNodeRef"))
            slots = []
        else:
            conditions = _references(entry.findall("./ObjectLists/ObjectList[@Name='EntryPath']/PluginInnerObject/ReferenceList/Reference[@Name='EntryPathObject']/ObjectRef"))
            targets = _references(entry.findall("./ReferenceList/Reference[@Name='AudioNode']/ObjectRef"))
            slots = _references(entry.findall("./ObjectLists/ObjectList[@Name='EntryPath']/PluginInnerObject"))
        if len(conditions) != len(groups) or len(targets) != 1:
            raise MusicOracleProbeError("fixture tuple width/target cardinality is invalid")
        mappings.append({"entry_id": entry.get("ID"), "conditions": conditions,
                         "target": targets[0], "slots": slots})
    if len(groups) != 2 or len(mappings) != 9 or len({tuple(row["conditions"]) for row in mappings}) != 9:
        raise MusicOracleProbeError("fixture is not the complete nine-tuple baseline")
    rule_root = _one(root, "MusicTransition", TRANSITION_ROOT)
    rules = rule_root.findall("./ChildrenList/MusicTransition")
    target_rule = _one(rule_root, "MusicTransition", TRANSITION)
    fade = target_rule.find("./TransitionInfo/SourceFadeOut/MusicFade")
    if len(rules) != 15 or fade is None or fade.get("ID") != FADE:
        raise MusicOracleProbeError("fixture has no complete fifteen-rule existing-fade baseline")
    return {
        "wwu_sha256": hashlib.sha256(raw).hexdigest(),
        "playlist": {"owner": PLAYLIST, "root": playlist_root.get("ID"), "items": playlist_rows},
        "music_switch": {"owner": SWITCH, "groups": groups, "mappings": mappings,
            "argument_slots": _references(owner.findall("./ObjectLists/ObjectList[@Name='Arguments']/PluginInnerObject"))},
        "transition": {"owner": SWITCH, "root": TRANSITION_ROOT,
            "rules": [{"id": node.get("ID"), "subtree_sha256": hashlib.sha256(ET.tostring(node)).hexdigest()} for node in rules],
            "target": TRANSITION, "fade": FADE, "fade_role": "SourceFadeOut"},
        "saved_order_is_live_order_proof": False,
    }


def music_read_plan(family: str, witness: Mapping[str, Any], version: str) -> tuple[tuple[str, ...], ...]:
    """Only documented public reads; EntryPath selection is an explicit probe."""
    if version not in {"2022.1", "2025.1"} or family not in {"playlist", "transition", "music-switch"}:
        raise MusicOracleProbeError("unknown closed investigation family/version")
    commands: list[tuple[str, ...]] = [("query-schema",), ("describe", "ak.wwise.core.object.get", "--full-schema")]
    def exact(identifier, *fields):
        commands.append(("query-object", "--exact-id", identifier,
                         *(token for field in fields for token in ("--include-field", field))))
    def relation(identifier, kind, cap):
        commands.append(("query-object", "--exact-id", identifier, "--relationship", kind, "--max-results", str(cap)))
    if family == "playlist":
        data = witness["playlist"]
        exact(data["owner"], "Playlist Root")
        relation(data["root"], "children", 4)
        relation(data["root"], "parent", 2)
        for item in data["items"]:
            exact(item["id"], "Segment", "No. of Loops", "Playlist Item Type")
            commands.append(("metadata", "discover", "--exact-id", item["id"], "--meaning", "IsLoopingInfinite"))
    elif family == "transition":
        data = witness["transition"]
        relation(data["root"], "children", 16)
        relation(data["target"], "parent", 2)
        relation(data["fade"], "parent", 2)
        fields = ("Source Type", "Destination Type", "Source Object", "Destination Object",
                  "Exit Source At", "Destination Sync To", "Play Source Post-exit",
                  "Play Destination Pre-entry", "Enable Source Fade-out")
        for batch in (fields[:8], fields[8:]):
            commands.append(("metadata", "discover", "--exact-id", data["target"],
                             *(token for field in batch for token in ("--meaning", field))))
        for rule in data["rules"]:
            for batch in (fields[:8], fields[8:]):
                exact(rule["id"], *batch)
        exact(data["fade"], "Fade Time", "Fade Offset", "Fade Curve", "Fade Type")
        commands.append(("metadata", "discover", "--exact-id", data["fade"],
                         "--meaning", "Fade Time", "--meaning", "Fade Offset", "--meaning", "Fade Curve"))
        for field in ("Fade Time", "Fade Offset"):
            commands.append(("metadata", "property-state", "--exact-id", data["fade"], "--meaning", field))
    else:
        data = witness["music_switch"]
        commands.append(("query-schema", "--advanced"))
        for field in ("Arguments", "Entries"):
            commands.append(("query-object", "--advanced-waql",
                f'from object "{data["owner"]}" select @{field}', "--max-results", "16"))
        for group in data["groups"]:
            relation(group, "children", 8)
        if version == "2025.1":
            for slot in data["argument_slots"]:
                exact(slot, "Argument")
            for row in data["mappings"]:
                exact(row["entry_id"], "Audio Node", "Probability", "Weight")
                # This field is pinned in installed 2025 metadata, but its live
                # traversal is not granted PASS by constructing this argv.
                commands.append(("query-object", "--advanced-waql",
                    f'from object "{row["entry_id"]}" select @EntryPath', "--max-results", "4"))
                for slot in row["slots"]:
                    exact(slot, "EntryPath Object")
    if len(commands) > MAX_CALLS:
        raise MusicOracleProbeError("closed read plan exceeds its call ceiling")
    return tuple(commands)


def run_music_read_plan(plan: Sequence[Sequence[str]], gateway: Callable) -> Mapping[str, Any]:
    """Retain bounded rejection/clarification, without calling it capability PASS."""
    if not 1 <= len(plan) <= MAX_CALLS:
        raise MusicOracleProbeError("read plan has an invalid call count")
    if any(not argv or argv[0] not in {"describe", "query-schema", "query-object", "metadata"} for argv in plan):
        raise MusicOracleProbeError("investigation plan contains a non-read command")
    receipts = []
    for argv in plan:
        code, payload = gateway(list(argv))
        if code not in {0, 2} or not isinstance(payload, Mapping):
            raise MusicOracleProbeError("public Gateway returned no bounded read/error receipt")
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RECEIPT_BYTES:
            raise MusicOracleProbeError("Gateway receipt exceeds investigation byte ceiling")
        finding = "read_returned" if code == 0 and payload.get("ok") is True else "gateway_rejected"
        if payload.get("status") == "needs_clarification":
            finding = "needs_clarification"
        if argv[0] == "query-object" and finding == "read_returned":
            rows = payload.get("objects")
            if (payload.get("status") != "ok" or not isinstance(rows, list)
                    or type(payload.get("count")) is not int or payload["count"] != len(rows)
                    or any(not isinstance(row, Mapping) or not isinstance(row.get("id"), str) for row in rows)
                    or len({row["id"].casefold() for row in rows}) != len(rows)):
                raise MusicOracleProbeError("successful query lacks complete structured rows")
            exact_source = "--exact-id" in argv and "--relationship" not in argv and "--advanced-waql" not in argv
            if "--max-results" in argv:
                try:
                    limit = int(argv[argv.index("--max-results") + 1])
                except (IndexError, ValueError) as exc:
                    raise MusicOracleProbeError("read plan has no valid declared query bound") from exc
                if not 1 <= limit <= 16:
                    raise MusicOracleProbeError("read plan exceeds its declared query bound ceiling")
                expected_bound = {"mode": "gateway-appended-take" if "--advanced-waql" in argv else "take", "value": limit}
            elif exact_source:
                limit = 1
                expected_bound = {"mode": "exact-object"}
            else:
                raise MusicOracleProbeError("non-exact read plan has no declared query bound")
            observed_bound = payload.get("query_bound")
            if (observed_bound != expected_bound
                    or "value" in expected_bound and type(observed_bound.get("value")) is not int):
                raise MusicOracleProbeError("Gateway query bound differs from the declared read plan")
            if len(rows) > limit:
                raise MusicOracleProbeError("Gateway rows exceed the declared query bound")
            if exact_source:
                expected = argv[argv.index("--exact-id") + 1]
                if len(rows) != 1 or rows[0]["id"].casefold() != expected.casefold():
                    raise MusicOracleProbeError("exact query did not return its selected identity")
            if payload.get("limit_reached") is True or not exact_source and len(rows) >= limit:
                finding = "row_limit_reached"
        receipts.append({"argv": list(argv), "exit_code": code, "finding": finding, "payload": payload})
        if len(json.dumps(receipts, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_REPORT_BYTES:
            raise MusicOracleProbeError("investigation receipts exceed total byte ceiling")
    return {"contract": "waapi-skill.music-oracle-read-probe/v1", "receipts": receipts,
        "agent_pass": False, "business_effect_verified": False,
        "complete_order_or_unit_oracle_proven": False}


def compare_music_read_receipts(witness: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Compare known graph edges; observed ordering remains non-authoritative."""
    comparisons = []
    playlist, transition, switch = (witness[key] for key in ("playlist", "transition", "music_switch"))
    children = {playlist["root"]: [row["id"] for row in playlist["items"]],
                transition["root"]: [row["id"] for row in transition["rules"]]}
    owners = {playlist["root"]: playlist["owner"], transition["target"]: transition["root"],
              transition["fade"]: transition["target"]}
    argument_ids = switch["argument_slots"] if len(switch["argument_slots"]) == len(switch["groups"]) else None
    entry_ids = [row["entry_id"] for row in switch["mappings"]]
    if any(identifier is None for identifier in entry_ids):
        entry_ids = None
    collections = {f'from object "{switch["owner"]}" select @Arguments': argument_ids,
                   f'from object "{switch["owner"]}" select @Entries': entry_ids}
    collections.update({f'from object "{row["entry_id"]}" select @EntryPath': row["slots"]
                        for row in switch["mappings"] if row["entry_id"]})
    references = {playlist["owner"]: {"PlaylistRoot": playlist["root"]}}
    references.update({row["id"]: {"Segment": row["segments"][0]} for row in playlist["items"] if len(row["segments"]) == 1})
    references.update({slot: {"Argument": group} for slot, group in zip(switch["argument_slots"], switch["groups"])})
    for row in switch["mappings"]:
        if row["entry_id"]:
            references[row["entry_id"]] = {"AudioNode": row["target"]}
        references.update({slot: {"EntryPathObject": value} for slot, value in zip(row["slots"], row["conditions"])})
    for receipt in receipts:
        argv = receipt["argv"]
        if argv[0] != "query-object":
            continue
        if "--advanced-waql" in argv:
            expression = argv[argv.index("--advanced-waql") + 1]
            if expression not in collections:
                continue
            expected = collections[expression]
            if expected is None:
                comparisons.append({"expression": expression, "finding": "expected_representation_unavailable",
                    "gateway_finding": receipt["finding"], "checks": {}})
                continue
            checks = {}
            if receipt["finding"] == "read_returned":
                actual = [row["id"] for row in receipt["payload"]["objects"]]
                checks.update(member_set_matches=set(actual) == set(expected),
                    observed_order_matches_saved_xml=actual == expected, order_is_authoritative=False)
            comparisons.append({"expression": expression, "finding": receipt["finding"], "checks": checks})
            continue
        if "--exact-id" not in argv:
            continue
        identifier = argv[argv.index("--exact-id") + 1]
        comparison: dict[str, Any] = {"id": identifier, "finding": receipt["finding"], "checks": {}}
        if receipt["finding"] == "read_returned":
            rows = receipt["payload"]["objects"]
            if "--relationship" in argv:
                relationship = argv[argv.index("--relationship") + 1]
                if relationship == "children" and identifier in children:
                    actual, expected = [row["id"] for row in rows], children[identifier]
                    comparison["checks"].update(member_set_matches=set(actual) == set(expected),
                        observed_order_matches_saved_xml=actual == expected, order_is_authoritative=False)
                elif relationship == "parent" and identifier in owners:
                    comparison["checks"]["returned_parent_matches_saved_xml_owner"] = (
                        len(rows) == 1 and rows[0]["id"] == owners[identifier])
            elif identifier in references:
                actual = rows[0].get("references", {})
                for token, expected in references[identifier].items():
                    value = actual.get(token) if isinstance(actual, Mapping) else None
                    observed = value.get("id") if isinstance(value, Mapping) else None
                    comparison["checks"][token] = None if observed is None else observed == expected
        comparisons.append(comparison)
    return comparisons

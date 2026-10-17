"""Offline completion of externally sealed native reflection receipts.

This is part of the maintainer collector, not an execution route. It never calls
Wwise, edits a capture, or changes an original lifecycle verdict.
"""
from __future__ import annotations

import hashlib
import json
import plistlib
import re
from datetime import datetime, timezone
from pathlib import Path

from wwise_waapi.native_catalog import canonical_digest, validate_native_catalog


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(info, args):
    if not isinstance(info, dict) or info.get("isCommandLine") is not (args.host == "wwise-console"):
        raise ValueError("Native receipt host attestation mismatch")
    build = ".".join(str(info.get("version", {}).get(key)) for key in ("year", "major", "minor", "build"))
    if build != args.build or not build.startswith(args.version + "."):
        raise ValueError("Native receipt build/version attestation mismatch")
    if type(info.get("processId")) is not int or info["processId"] <= 0 or not isinstance(info.get("sessionId"), str) or not info["sessionId"].strip():
        raise ValueError("Native receipt session/process attestation missing")
    return {"host": args.host, "build": build, "session_id": info["sessionId"], "process_id": info["processId"]}


def _extend_definitions(definitions, args):
    if args.definition_attestation is None:
        return []
    raw_attestation = args.definition_attestation.read_bytes()
    attestation = json.loads(raw_attestation)
    if attestation.get("contract") != "waapi-skill.maintainer-installed-definition-attestation/v1":
        raise ValueError("Unsupported installed definition attestation")
    matching = [row for row in attestation["sources"] if row.get("version") == args.version and row.get("build") == args.build]
    if not matching:
        raise ValueError("No matching-build installed definition attestation")
    evidence = []
    for row in matching:
        if row.get("source_kind") != "installed_matching_build_definition" or row.get("bundle_version") != args.build:
            raise ValueError("Installed definition build evidence mismatch")
        install_root = Path(row["install_root"]).resolve(strict=True)
        source = Path(row["source_path"]).resolve(strict=True)
        executable = Path(row["authoring_executable"]).resolve(strict=True)
        source.relative_to(install_root)
        executable.relative_to(install_root)
        name = row["document_name"]
        if source.name != name or not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", name):
            raise ValueError("Installed definition document identity mismatch")
        source_raw = source.read_bytes()
        bundle_raw = Path(row["bundle_info_path"]).read_bytes()
        if (_sha(source_raw) != row["source_sha256"] or _sha(bundle_raw) != row["bundle_info_sha256"]
                or _sha(executable.read_bytes()) != row["authoring_executable_sha256"]):
            raise ValueError("Installed definition source digest mismatch")
        if plistlib.loads(bundle_raw).get("CFBundleVersion") != args.build:
            raise ValueError("Installed definition bundle build mismatch")
        document = json.loads(source_raw)
        if not isinstance(document.get("definitions"), dict) or len(document["definitions"]) != row["definition_count"]:
            raise ValueError("Installed definition count/structure mismatch")
        if name in definitions["documents"] and definitions["documents"][name] != document:
            raise ValueError("Installed definition conflicts with retained graph")
        definitions["documents"][name] = document
        definitions["source_file_names"] = sorted(set(definitions["source_file_names"] + [name]))
        evidence.append({"document_name": name, "source_sha256": row["source_sha256"],
                         "source_kind": row["source_kind"], "build": args.build,
                         "bundle_info_sha256": row["bundle_info_sha256"],
                         "authoring_executable_sha256": row["authoring_executable_sha256"],
                         "attestation_sha256": _sha(raw_attestation)})
    definitions["inventory_sha256"] = canonical_digest({k: v for k, v in definitions.items() if k != "inventory_sha256"})
    return evidence


def finalize_native_capture(args, *, skill_root: Path) -> int:
    if args.receipt_seal is None:
        raise ValueError("Offline finalization requires an independent receipt seal")
    seal_raw = args.receipt_seal.read_bytes()
    seal = json.loads(seal_raw)
    seal_root = Path(seal["root"]).resolve(strict=True)
    source = args.finalize_from.resolve(strict=True)
    source.relative_to(seal_root)
    output = args.output.resolve(strict=False)
    if output == seal_root or seal_root in output.parents or output in source.parents:
        raise ValueError("Derived output must be outside the immutable source capture")
    receipt_bytes = {}
    sources = {}
    endpoint = None
    initial = None

    def receipt(label, command, api=None):
        nonlocal endpoint, initial
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
            raise ValueError("Invalid native receipt name")
        path = source / f"{label}.json"
        relative = path.resolve(strict=True).relative_to(seal_root).as_posix()
        raw = path.read_bytes()
        if seal["files"].get(relative) != _sha(raw):
            raise ValueError(f"Native receipt seal mismatch: {relative}")
        payload = json.loads(raw)
        if payload.get("ok") is not True or payload.get("command") != command:
            raise ValueError(f"Native receipt failed or wrong command: {label}")
        if payload.get("detected_version") != args.version or payload.get("is_command_line") is not (args.host == "wwise-console"):
            raise ValueError(f"Native receipt host/version mismatch: {label}")
        if endpoint is None:
            endpoint = payload.get("endpoint")
            if not isinstance(endpoint, dict) or not endpoint.get("url"):
                raise ValueError("Native receipt endpoint missing")
        if payload.get("endpoint") != endpoint:
            raise ValueError("Native receipt endpoint drift")
        identity = _identity(payload.get("wwise") if command == "status" else payload.get("reflection_context"), args)
        if initial is None:
            initial = identity
        if initial != identity:
            raise ValueError("Native receipt session drift")
        if api is not None and payload.get("api_attempted") != api:
            raise ValueError("Native receipt API mismatch")
        receipt_bytes[path.name] = raw
        sources[path.name] = _sha(raw)
        return payload

    receipt("status-start", "status")
    inventories = {}
    for kind in ("functions", "topics"):
        uri = "ak.wwise.waapi.get" + kind.title()
        result = receipt(kind, "typed-zero-call", uri)["agent_result"]
        entries = result["uris"]
        if (result.get("kind") != kind[:-1] or result.get("count") != len(entries)
                or not isinstance(entries, list) or len(entries) > 4096
                or any(not isinstance(uri, str) or not re.fullmatch(r"ak\.[A-Za-z0-9_.]+", uri) for uri in entries)
                or len(set(entries)) != len(entries)):
            raise ValueError("Native receipt inventory malformed")
        inventories[kind] = entries
    schemas = {}
    for uri in sorted(set(inventories["functions"] + inventories["topics"])):
        payload = receipt(uri, "waapi-schema", "ak.wwise.waapi.getSchema")
        if payload.get("schema_target") != uri:
            raise ValueError("Native receipt schema target mismatch")
        schemas[uri] = payload["agent_result"]
    for kind in ("functions", "topics"):
        final = receipt(f"{kind}-end", "typed-zero-call", "ak.wwise.waapi.get" + kind.title())["agent_result"]
        if final["uris"] != inventories[kind] or final.get("count") != len(inventories[kind]):
            raise ValueError("Native receipt inventory drift")
    receipt("status-end", "status")
    definitions_path = skill_root / "resources/manifest" / args.version / "definitions.json"
    definitions_raw = definitions_path.read_bytes()
    definitions = json.loads(definitions_raw)
    if definitions["wwise_build"] != args.build:
        raise ValueError("Retained definition build mismatch")
    if definitions.get("inventory_sha256") != canonical_digest({k: v for k, v in definitions.items() if k != "inventory_sha256"}):
        raise ValueError("Retained definition inventory digest mismatch before extension")
    definition_evidence = _extend_definitions(definitions, args)
    catalog = {"contract": "waapi-skill.native-catalog/v1", "version": args.version,
               **inventories, "schemas": schemas, "definitions": definitions,
               "provenance": {**initial, "evidence_kind": "reflection_only", "sources": sources,
                              "definitions_source": {"path": f"resources/manifest/{args.version}/definitions.json", "sha256": _sha(definitions_raw)},
                              "additional_definition_sources": definition_evidence,
                              "derivation": {"mode": "offline_from_sealed_gateway_receipts", "derived_at": datetime.now(timezone.utc).isoformat(),
                                             "source_capture": seal_root.name, "source_seal_sha256": _sha(seal_raw),
                                             "candidate": seal.get("candidate"), "original_outcome": {key: value for key, value in (seal.get("original_outcome") or {}).items() if key != "root"}}}}
    validate_native_catalog(catalog)
    catalog["content_sha256"] = canonical_digest(catalog)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in receipt_bytes.items():
        (output / name).write_bytes(raw)
    (output / "native-catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0

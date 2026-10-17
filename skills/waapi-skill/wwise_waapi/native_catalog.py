"""Host-specific reflection truth, deliberately independent of executable routes.

Loading this store cannot extend ManifestStore or ExecutionContractRegistry.
The separate file seal protects inventory and schemas, including equal-count
URI substitutions. A missing capture is missing evidence, never native absence.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .capabilities import CapabilityCatalog, CapabilityCatalogError, CapabilityNotFoundError
from .execution_contracts import AUTHORING_UI_EXECUTION_PROFILE, CONSOLE_EXECUTION_PROFILE
from .versions import SUPPORTED_WWISE_VERSION_KEYS

NATIVE_CATALOG_ROOT = Path(__file__).resolve().parents[1] / "resources/native-catalog"
NATIVE_HOSTS = ("wwise-console", "wwise-authoring")
APPROVED_EXCLUSIONS = frozenset({"ak.wwise.ui.cli.executeLuaScript", "ak.wwise.ui.cli.launch"})


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_native_catalog(version: str, host: str, *, root: Path = NATIVE_CATALOG_ROOT) -> dict:
    if version not in SUPPORTED_WWISE_VERSION_KEYS or host not in NATIVE_HOSTS:
        raise CapabilityCatalogError("Unsupported native catalog version/host")
    name = f"{version}/{host}.json"
    try:
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != index.get(name):
            raise CapabilityCatalogError(f"Native catalog digest mismatch: {name}")
        catalog = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise CapabilityCatalogError(f"Native catalog evidence missing or invalid: {name}: {exc}") from exc
    if catalog.get("version") != version or catalog.get("provenance", {}).get("host") != host:
        raise CapabilityCatalogError(f"Native catalog host/version mismatch: {name}")
    if catalog.get("content_sha256") != canonical_digest({k: v for k, v in catalog.items() if k != "content_sha256"}):
        raise CapabilityCatalogError(f"Native catalog content digest mismatch: {name}")
    validate_native_catalog(catalog)
    return catalog


def native_capability(catalog: dict, uri: str, *, full_schema: bool = False) -> dict:
    kind = "function" if uri in catalog["functions"] else "topic"
    if uri not in catalog["schemas"]:
        raise CapabilityNotFoundError(f"{uri} absent from attested native inventory")
    host = catalog["provenance"]["host"]
    profile = AUTHORING_UI_EXECUTION_PROFILE if host == "wwise-authoring" else CONSOLE_EXECUTION_PROFILE
    try:
        implemented = CapabilityCatalog().describe_for_profile(catalog["version"], uri, profile=profile)
    except CapabilityNotFoundError:
        interface = {"status": "missing_implementation", "gateway_commands": [], "transaction_operations": []}
    else:
        interface = implemented.as_dict()["interface"]
    if uri in APPROVED_EXCLUSIONS:
        interface = {"status": "approved_exclusion", "reason": "Explicit Authoring Lua/launch exclusion", "gateway_commands": [], "transaction_operations": []}
    return {"version": catalog["version"], "uri": uri, "item_type": kind, "native_status": "present", "host_surface": host,
            "interface": {**interface, "execution_enabled_by_catalog": False},
            "schema": {"status": "ok", "sha256": canonical_digest(catalog["schemas"][uri]), **({"full": catalog["schemas"][uri], "definitions": catalog["definitions"]} if full_schema else {})},
            "provenance": {key: value for key, value in catalog["provenance"].items() if key != "sources"},
            "source_receipt_count": len(catalog["provenance"]["sources"]),
            "source_receipts_sha256": canonical_digest(catalog["provenance"]["sources"])}


def validate_native_catalog(catalog: dict) -> None:
    """Validate complete native membership and transitive same-build references."""
    from .schema_inventory import DefinitionGraph, resolve_schema_reference

    try:
        if catalog.get("contract") != "waapi-skill.native-catalog/v1":
            raise ValueError("unsupported native catalog contract")
        version = catalog["version"]
        provenance = catalog["provenance"]
        build = provenance["build"]
        if version not in SUPPORTED_WWISE_VERSION_KEYS or provenance["host"] not in NATIVE_HOSTS:
            raise ValueError("native catalog host/version mismatch")
        if not re.fullmatch(re.escape(version) + r"\.\d+\.\d+", build):
            raise ValueError("native catalog exact build missing")
        if not provenance.get("session_id") or not provenance.get("sources") or provenance.get("evidence_kind") != "reflection_only":
            raise ValueError("native catalog session/source provenance missing")
        functions, topics, schemas = catalog["functions"], catalog["topics"], catalog["schemas"]
        for entries in (functions, topics):
            if not isinstance(entries, list) or len(entries) > 4096 or any(not isinstance(uri, str) or not re.fullmatch(r"ak\.[A-Za-z0-9_.]+", uri) for uri in entries) or len(set(entries)) != len(entries):
                raise ValueError("native catalog inventory malformed or duplicated")
        if set(functions) & set(topics) or not isinstance(schemas, dict) or set(schemas) != set(functions + topics):
            raise ValueError("native catalog missing, extra, or ambiguous schema membership")
        definitions = catalog["definitions"]
        if definitions.get("version") != version or definitions.get("wwise_build") != build:
            raise ValueError("native definition build/version mismatch")
        unsigned_definitions = {k: v for k, v in definitions.items() if k != "inventory_sha256"}
        if definitions.get("inventory_sha256") != canonical_digest(unsigned_definitions):
            raise ValueError("native definition digest mismatch")
        graph = DefinitionGraph(contract=definitions["contract"], version=version, wwise_build=build, source_file_names=tuple(definitions["source_file_names"]), documents=definitions["documents"], inventory_sha256=definitions["inventory_sha256"])
        visited = set()

        def visit(node, root, context):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("$ref", "#ref"):
                        resolved = resolve_schema_reference(value, root_schema=root, graph=graph)
                        identity = (context if resolved.document_name == "<schema>" else resolved.document_name, resolved.pointer)
                        if identity not in visited:
                            visited.add(identity)
                            ref_root = root if resolved.document_name == "<schema>" else graph.documents[resolved.document_name]
                            visit(resolved.target, ref_root, identity[0])
                    elif key not in ("description", "examples"):
                        visit(value, root, context)
            elif isinstance(node, list):
                for value in node:
                    visit(value, root, context)

        for uri, schema in schemas.items():
            required = ("argsSchema", "optionsSchema", "resultSchema") if uri in functions else ("optionsSchema", "publishSchema")
            if not isinstance(schema, dict) or any(not isinstance(schema.get(section), dict) for section in required):
                raise ValueError(f"native schema sections missing for {uri}")
            for section in required:
                visit(schema[section], schema[section], (uri, section))
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise CapabilityCatalogError(f"Invalid native catalog evidence: {exc}") from exc

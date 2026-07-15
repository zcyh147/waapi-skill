"""Normalized, packaged capability catalog for every supported Wwise version.

This module intentionally separates three facts that older coverage resources
mixed together:

* reflection availability and schema shape;
* the Skill interface route that an agent can use without writing code;
* behavioral evidence or an explicit policy/safety boundary.

The catalog is computed only from resources shipped inside the Skill package,
so it remains available when the Skill is installed without this repository's
test tree and does not require a live Wwise connection.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .builders.source_notes import load_semantic_source_notes
from .category_policy import category_policy
from .deferred_registry import ApiClassifier
from .execution_contracts import (
    ExecutionContract,
    ExecutionContractError,
    ExecutionContractRegistry,
    FIXED_COMMANDS_BY_URI,
    UNDO_GROUP_MEMBER_URIS,
)
from .manifest import ManifestStore
from .operation_registry import OPERATION_SPECS
from .safety import ApiSafety, REVIEWED_FIXED_FUNCTION_URIS, classify_api_safety
from .versions import SUPPORTED_WWISE_VERSION_KEYS


SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
SEMANTIC_ROOT = SKILL_ROOT / "resources" / "semantic"
DEFERRED_ROOT = SKILL_ROOT / "resources" / "deferred"

if frozenset(FIXED_COMMANDS_BY_URI) != REVIEWED_FIXED_FUNCTION_URIS:
    raise RuntimeError(
        "The fixed gateway command map and immutable reviewed fixed-function allowlist must match exactly"
    )

class CapabilityCatalogError(ValueError):
    """Base error for invalid catalog requests or packaged resources."""


class CapabilityNotFoundError(CapabilityCatalogError):
    """Raised when a URI is not reflected by the requested version."""


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One normalized reflected function or topic."""

    version: str
    uri: str
    item_type: str
    category: str
    risk_level: str
    schema_status: str
    schema: Mapping[str, Any]
    safety: ApiSafety
    preferred_route: str
    execution_mode: str
    semantic_family: str | None = None
    fixed_commands: tuple[str, ...] = ()
    gateway_commands: tuple[str, ...] = ()
    transaction_operations: tuple[str, ...] = ()
    transaction_boundaries: tuple[Mapping[str, Any], ...] = ()
    policy: Mapping[str, Any] | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    execution_contract: Mapping[str, Any] = field(default_factory=dict)

    def as_compact_dict(self) -> dict[str, Any]:
        """Return the stable agent-facing inventory row.

        This representation keeps routing and safety boundaries visible while
        omitting reflected schema summaries, policy prose, and evidence detail.
        Use :meth:`as_dict` only for an explicitly requested detailed row.
        """

        return {
            "version": self.version,
            "uri": self.uri,
            "item_type": self.item_type,
            "category": self.category,
            "risk": self.risk_level,
            "schema_status": self.schema_status,
            "interface_status": self.safety.interface_status,
            "preferred_route": self.preferred_route,
            "gateway_commands": list(self.gateway_commands),
            "transaction_operations": list(self.transaction_operations),
            "transaction_boundaries": [_json_safe(item) for item in self.transaction_boundaries],
            "read_only": self.safety.read_only,
            "execution_contract": _compact_execution_contract(self.execution_contract),
        }

    def as_dict(self, *, detail: bool = False) -> dict[str, Any]:
        schema_summary = _schema_summary(self.schema_status, self.schema)
        if detail and self.schema_status == "ok":
            schema_summary["full"] = _json_safe(self.schema)
        return {
            "version": self.version,
            "uri": self.uri,
            "item_type": self.item_type,
            "category": self.category,
            "risk_level": self.risk_level,
            "interface": {
                "status": self.safety.interface_status,
                "preferred_route": self.preferred_route,
                "execution_mode": self.execution_mode,
                "fixed_commands": list(self.fixed_commands),
                "gateway_commands": list(self.gateway_commands),
                "transaction_operations": list(self.transaction_operations),
                "transaction_boundaries": [_json_safe(item) for item in self.transaction_boundaries],
                "semantic_family": self.semantic_family,
                "requires_live_wwise": True,
                "manifest_runtime_profile": "wwise-console",
                "authoring_ui_profile": "not_reflected_separately",
                "schema_validation_level": "bounded_recursive_reflection",
                **self.safety.as_dict(),
            },
            "execution_contract": _json_safe(self.execution_contract),
            "schema": schema_summary,
            "policy": _json_safe(self.policy) if self.policy is not None else None,
            "behavioral_evidence": _json_safe(self.evidence),
        }


@dataclass(slots=True)
class CapabilityCatalog:
    """Load and query normalized capabilities from packaged resources."""

    manifest_root: Path = MANIFEST_ROOT
    semantic_root: Path = SEMANTIC_ROOT
    deferred_root: Path = DEFERRED_ROOT
    classifier: ApiClassifier = field(default_factory=ApiClassifier)
    execution_registry: ExecutionContractRegistry = field(default_factory=ExecutionContractRegistry)

    def __post_init__(self) -> None:
        """Keep reflected schemas and executable contracts on one fail-closed root."""

        manifest_root = Path(self.manifest_root)
        registry_root = self.execution_registry.manifest_store.root
        if registry_root == MANIFEST_ROOT and manifest_root != MANIFEST_ROOT:
            self.execution_registry = ExecutionContractRegistry(
                manifest_store=ManifestStore(root=manifest_root)
            )
            return
        if registry_root is None or Path(registry_root) != manifest_root:
            raise CapabilityCatalogError(
                "Capability manifest_root and execution-contract manifest root must match"
            )

    def versions(self) -> tuple[str, ...]:
        return tuple(SUPPORTED_WWISE_VERSION_KEYS)

    def entries(self, version: str) -> tuple[CapabilityRecord, ...]:
        self._require_version(version)
        manifest = ManifestStore(root=self.manifest_root).load(version)
        schemas = {
            str(entry.get("uri")): entry
            for entry in manifest.get("schemas", [])
            if isinstance(entry, Mapping) and isinstance(entry.get("uri"), str)
        }
        semantic_families = self._semantic_families(version)
        deferred = self._deferred_entries(version)
        try:
            registry_entries = self.execution_registry.entries(version)
        except ExecutionContractError as exc:
            raise CapabilityCatalogError(str(exc)) from exc
        execution_contracts = {
            (entry.item_type, entry.uri): entry
            for entry in registry_entries
        }
        records: list[CapabilityRecord] = []
        seen: set[tuple[str, str]] = set()
        for item_type, section in (("function", "functions"), ("topic", "topics")):
            for entry in manifest.get(section, []):
                if not isinstance(entry, Mapping) or not isinstance(entry.get("uri"), str):
                    raise CapabilityCatalogError(f"Malformed {section} entry in packaged manifest {version}")
                uri = str(entry["uri"])
                key = (item_type, uri)
                if key in seen:
                    raise CapabilityCatalogError(f"Duplicate reflected {item_type} URI in {version}: {uri}")
                seen.add(key)
                classification = self.classifier.classify(uri, item_type)
                reflected_safety = classify_api_safety(uri, item_type, classification.category)
                try:
                    execution_contract = execution_contracts[(item_type, uri)]
                except KeyError as exc:
                    raise CapabilityCatalogError(
                        f"No public execution contract exists for reflected {item_type} {uri} in Wwise {version}"
                    ) from exc
                family = semantic_families.get(uri)
                fixed_commands = FIXED_COMMANDS_BY_URI.get(uri, ())
                transaction_operations, transaction_boundaries = _transaction_routes(version, uri)
                if uri in UNDO_GROUP_MEMBER_URIS:
                    transaction_operations = ("waapi.undoGroup",)
                    transaction_boundaries = ()
                safety = reflected_safety
                if execution_contract.route in {
                    "transaction",
                    "managed_transaction",
                    "isolated_transaction",
                }:
                    transaction_operations = tuple(sorted({*transaction_operations, "waapi.call"}))
                schema_entry = schemas.get(uri, {})
                schema_status = str(schema_entry.get("status") or "missing")
                raw_schema = schema_entry.get("schema")
                schema = raw_schema if isinstance(raw_schema, Mapping) else {}
                policy_record = _policy_record(classification.category)
                preferred_route = _preferred_route(execution_contract)
                gateway_commands = execution_contract.gateway_commands
                records.append(
                    CapabilityRecord(
                        version=version,
                        uri=uri,
                        item_type=item_type,
                        category=classification.category,
                        risk_level=classification.risk_level,
                        schema_status=schema_status,
                        schema=schema,
                        safety=safety,
                        preferred_route=preferred_route,
                        execution_mode=execution_contract.route,
                        semantic_family=family,
                        fixed_commands=tuple(fixed_commands),
                        gateway_commands=gateway_commands,
                        transaction_operations=transaction_operations,
                        transaction_boundaries=transaction_boundaries,
                        policy=policy_record,
                        evidence=_evidence_record(deferred.get(uri)),
                        execution_contract=execution_contract.as_dict(),
                    )
                )
        _validate_execution_contract_invariant(version, records)
        return tuple(sorted(records, key=lambda item: (item.uri, item.item_type)))

    def describe(self, version: str, uri: str) -> CapabilityRecord:
        for entry in self.entries(version):
            if entry.uri == uri:
                return entry
        raise CapabilityNotFoundError(f"WAAPI URI {uri!r} is not reflected by Wwise {version}")

    def select(
        self,
        version: str,
        *,
        category: str | None = None,
        item_type: str | None = None,
        semantic_family: str | None = None,
        preferred_route: str | None = None,
        query: str | None = None,
    ) -> tuple[CapabilityRecord, ...]:
        if item_type is not None and item_type not in {"function", "topic"}:
            raise CapabilityCatalogError("item_type must be 'function' or 'topic'")
        needle = query.lower() if query else None
        return tuple(
            entry
            for entry in self.entries(version)
            if (category is None or entry.category == category)
            and (item_type is None or entry.item_type == item_type)
            and (semantic_family is None or entry.semantic_family == semantic_family)
            and (preferred_route is None or entry.preferred_route == preferred_route)
            and (needle is None or needle in entry.uri.lower())
        )

    def summary(self, versions: Iterable[str]) -> dict[str, Any]:
        selected_versions = tuple(versions)
        if not selected_versions:
            raise CapabilityCatalogError("At least one Wwise version is required")
        version_summaries: dict[str, Any] = {}
        all_entries: list[CapabilityRecord] = []
        for version in selected_versions:
            entries = list(self.entries(version))
            all_entries.extend(entries)
            version_summaries[version] = _count_summary(entries)
        return {
            "versions": list(selected_versions),
            "totals": _count_summary(all_entries),
            "by_version": version_summaries,
        }

    def _semantic_families(self, version: str) -> dict[str, str]:
        resource = load_semantic_source_notes(
            self.semantic_root / version / "source_notes.json",
            expected_version=version,
        )
        result: dict[str, str] = {}
        for family, note in resource.notes.items():
            endpoints = note.get("endpoints")
            if not isinstance(endpoints, list):
                continue
            for uri in endpoints:
                if not isinstance(uri, str):
                    continue
                previous = result.get(uri)
                if previous is not None and previous != family:
                    raise CapabilityCatalogError(
                        f"Semantic endpoint {uri} is assigned to both {previous} and {family} in {version}"
                    )
                result[uri] = family
        return result

    def _deferred_entries(self, version: str) -> dict[str, Mapping[str, Any]]:
        path = self.deferred_root / f"{version}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CapabilityCatalogError(f"Could not read packaged deferred resource {path}: {exc}") from exc
        entries = payload.get("deferred")
        if not isinstance(entries, list):
            raise CapabilityCatalogError(f"Packaged deferred resource {path} lacks a deferred list")
        return {
            str(entry["uri"]): entry
            for entry in entries
            if isinstance(entry, Mapping) and isinstance(entry.get("uri"), str)
        }

    def _require_version(self, version: str) -> None:
        if version not in SUPPORTED_WWISE_VERSION_KEYS:
            raise CapabilityCatalogError(
                f"Unsupported Wwise version {version!r}; supported versions: {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
            )


def _preferred_route(contract: ExecutionContract) -> str:
    return {
        "excluded": "unsupported_boundary",
        "fixed_command": "fixed_command",
        "bounded_call": "manifest_dispatch",
        "bounded_topic_wait": "bounded_topic_wait",
        "transaction": "transaction_operation",
        "managed_transaction": "transaction_operation",
        "isolated_transaction": "transaction_operation",
        "compound_transaction_member": "transaction_operation",
    }[contract.route]


def _validate_execution_contract_invariant(
    version: str,
    records: Iterable[CapabilityRecord],
) -> None:
    """Prove every reflected row projects the registry's one public lane."""

    materialized = tuple(records)
    invalid = tuple(
        record.uri
        for record in materialized
        if not isinstance(record.execution_contract, Mapping)
        or record.execution_contract.get("version") != version
        or record.execution_contract.get("uri") != record.uri
        or tuple(record.execution_contract.get("gateway_commands", ())) != record.gateway_commands
        or bool(record.execution_contract.get("executable"))
        != (record.safety.interface_status != "unsupported_by_skill_interface")
    )
    if invalid:
        raise CapabilityCatalogError(
            f"Capability rows do not match the public execution contract in Wwise {version}: "
            f"{sorted(invalid)!r}"
        )


def _transaction_routes(
    version: str,
    uri: str,
) -> tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]:
    executable: list[str] = []
    boundaries: list[Mapping[str, Any]] = []
    for spec in OPERATION_SPECS.values():
        if spec.uri != uri or version not in spec.supported_versions:
            continue
        if spec.implemented:
            executable.append(spec.name)
        else:
            boundaries.append({"operation": spec.name, "boundary": spec.boundary})
    return tuple(sorted(executable)), tuple(sorted(boundaries, key=lambda item: str(item["operation"])))


def _policy_record(category: str) -> dict[str, str] | None:
    policy = category_policy(category)
    if policy is None:
        return None
    return {
        "target_status": policy.target_status,
        "rationale": policy.user_approved_rationale,
        "risk_explanation": policy.risk_explanation,
        "future_review_trigger": policy.future_review_trigger,
    }


def _evidence_record(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    if entry is None:
        return {
            "registry_status": "not_listed_in_packaged_deferred_registry",
            "behavioral_claim": "none",
            "note": "Absence from the deferred registry is not, by itself, proof of behavioral testing.",
        }
    return {
        "registry_status": str(entry.get("coverage_status") or entry.get("behavioral_coverage") or "deferred"),
        "behavioral_claim": str(entry.get("behavioral_coverage") or "deferred"),
        "inventory_coverage": entry.get("inventory_coverage"),
        "reason": entry.get("reason"),
        "blocking_condition": entry.get("blocking_condition"),
        "substitute_test": entry.get("substitute_test"),
        "review_trigger": entry.get("review_trigger"),
    }


def _schema_summary(status: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if status != "ok":
        return result
    result["description"] = schema.get("description")
    for source, target in (
        ("argsSchema", "args"),
        ("optionsSchema", "options"),
        ("resultSchema", "result"),
        ("publishSchema", "event"),
    ):
        section = schema.get(source)
        if not isinstance(section, Mapping):
            result[target] = {"type": "unknown", "required": [], "properties": []}
            continue
        properties = section.get("properties")
        result[target] = {
            "type": section.get("type") or ("schema-ref" if "$ref" in section else "unknown"),
            "required": sorted(str(item) for item in section.get("required", []) if isinstance(item, str)),
            "properties": sorted(str(item) for item in properties) if isinstance(properties, Mapping) else [],
            "ref": section.get("$ref"),
        }
    return result


def _count_summary(entries: Iterable[CapabilityRecord]) -> dict[str, Any]:
    rows = list(entries)
    return {
        "total": len(rows),
        "functions": sum(entry.item_type == "function" for entry in rows),
        "topics": sum(entry.item_type == "topic" for entry in rows),
        "schema_status": dict(sorted(Counter(entry.schema_status for entry in rows).items())),
        "interface_status": dict(sorted(Counter(entry.safety.interface_status for entry in rows).items())),
        "preferred_routes": dict(sorted(Counter(entry.preferred_route for entry in rows).items())),
        "semantic_families": dict(sorted(Counter(entry.semantic_family or "none" for entry in rows).items())),
        "behavioral_registry_status": dict(
            sorted(Counter(str(entry.evidence.get("registry_status")) for entry in rows).items())
        ),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _compact_execution_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Remove fields already present on the compact capability row."""

    fields = (
        "contract",
        "route",
        "effect",
        "timeout_seconds",
        "result_limit_bytes",
        "verification_strategy",
        "requires_confirmation",
        "lifecycle_strategy",
        "companion_uris",
        "executable",
    )
    return {
        field_name: _json_safe(contract[field_name])
        for field_name in fields
        if field_name in contract
    }

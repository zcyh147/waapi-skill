"""Generate the retired ``audio.import`` parity matrix from frozen evidence.

This module is maintenance-only.  The packaged Skill contains neither the
retired Composer projection nor its validator; the immutable pre-cutover
contract below is the sole source for offline parity review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from wwise_waapi.business_declarations import SUPPORTED_WWISE_VERSIONS
from wwise_waapi.canonical import canonical_sha256, strict_json_copy


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_AUDIO_IMPORT_CONTRACT_RESOURCE = (
    REPO_ROOT / "tests/fixtures/legacy/audio-import-composer-contract.json"
)
AUDIO_IMPORT_MIGRATION_RESOURCE = (
    REPO_ROOT
    / "tests/fixtures/legacy/audio-import-business-migration.json"
)
AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT = (
    "waapi-skill.audio-import-business-migration/v2"
)
LEGACY_AUDIO_IMPORT_CONTRACT = (
    "waapi-skill.retired-audio-import-composer-contract/v1"
)
LEGACY_AUDIO_IMPORT_SOURCE_COMMIT = (
    "d9dd0bf11fde89dccc3c4bd85fc01537a1d5d511"
)


def load_frozen_audio_import_contract() -> dict[str, Any]:
    """Load and validate the immutable pre-cutover contract snapshot."""

    payload = json.loads(
        LEGACY_AUDIO_IMPORT_CONTRACT_RESOURCE.read_text(encoding="utf-8")
    )
    if (
        not isinstance(payload, Mapping)
        or set(payload)
        != {
            "contract",
            "migration_classification",
            "source_commit",
            "versions",
        }
        or payload.get("contract") != LEGACY_AUDIO_IMPORT_CONTRACT
        or payload.get("source_commit") != LEGACY_AUDIO_IMPORT_SOURCE_COMMIT
    ):
        raise RuntimeError("frozen audio.import contract identity drifted")
    versions = payload.get("versions")
    if not isinstance(versions, Mapping) or tuple(versions) != tuple(
        SUPPORTED_WWISE_VERSIONS
    ):
        raise RuntimeError("frozen audio.import version lanes drifted")
    classification = payload.get("migration_classification")
    if not isinstance(classification, Mapping) or set(classification) != {
        "actions",
        "destination_kinds",
        "nested_fields",
        "request_options",
        "row_fields",
        "safety_rules",
    }:
        raise RuntimeError("frozen audio.import classification drifted")
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))


def build_audio_import_migration_inventory() -> dict[str, Any]:
    """Generate exhaustive old-to-deep rows from the frozen source contract."""

    frozen = load_frozen_audio_import_contract()
    classification = frozen["migration_classification"]
    destination_kinds = frozenset(classification["destination_kinds"])
    lanes = [
        _build_lane(
            version,
            frozen["versions"][version],
            classification,
            destination_kinds,
        )
        for version in SUPPORTED_WWISE_VERSIONS
    ]
    payload: dict[str, Any] = {
        "contract": AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT,
        "operation": "audio.import",
        "versions": list(SUPPORTED_WWISE_VERSIONS),
        "destination_kinds": sorted(destination_kinds),
        "source_contract": {
            "contract": frozen["contract"],
            "commit": frozen["source_commit"],
            "sha256": canonical_sha256(frozen),
        },
        "lanes": lanes,
        "cutover_policy": {
            "status": "deep_business_interface_public",
            "public_input_mode": "business_declaration",
            "old_interface": "deleted_from_packaged_runtime",
            "legacy_internal_role": "test_maintenance_frozen_contract_only",
            "fallback": False,
            "historical_evidence": "frozen_commits_only",
        },
    }
    payload["inventory_digest"] = canonical_sha256(payload)
    return strict_json_copy(payload)


def _build_lane(
    version: str,
    source: Mapping[str, Any],
    classification: Mapping[str, Any],
    destination_kinds: frozenset[str],
) -> dict[str, Any]:
    if set(source) != {
        "actions",
        "contract",
        "limits",
        "metadata_dependency_closure",
        "operation",
        "request_options",
        "row_fields",
        "source_schema_digest",
        "supported_row_fields",
        "version",
    }:
        raise RuntimeError(f"frozen audio.import {version} lane schema drifted")
    for family in ("request_options", "row_fields", "actions"):
        _require_exact_coverage(
            family,
            set(source[family]),
            set(classification[family]),
        )
    request_options = [
        _source_row(
            name,
            classification["request_options"][name],
            source_contract=source["request_options"][name],
            available=_available_in_version(
                source["request_options"][name], version
            ),
            destination_kinds=destination_kinds,
        )
        for name in sorted(source["request_options"])
    ]
    row_fields = [
        _source_row(
            name,
            classification["row_fields"][name],
            source_contract=source["row_fields"][name],
            available=True,
            destination_kinds=destination_kinds,
        )
        for name in sorted(source["row_fields"])
    ]
    actions = [
        _source_row(
            name,
            classification["actions"][name],
            source_contract=source["actions"][name],
            available=True,
            destination_kinds=destination_kinds,
        )
        for name in sorted(source["actions"])
    ]
    nested_fields = [
        _source_row(
            name,
            row,
            source_contract=None,
            available=True,
            destination_kinds=destination_kinds,
        )
        for name, row in sorted(classification["nested_fields"].items())
    ]
    contract_inventory = {
        f"{family}.{name}": _contract_leaf_inventory(
            source=name,
            contract=contract,
            migration=classification[family][name],
            destination_kinds=destination_kinds,
        )
        for family in ("request_options", "row_fields", "actions")
        for name, contract in sorted(source[family].items())
    }
    return {
        "version": version,
        "request_options": request_options,
        "row_fields": row_fields,
        "nested_fields": nested_fields,
        "actions": actions,
        "source_contract_inventory": contract_inventory,
        "safety_rules": list(classification["safety_rules"]),
        "limits": {"source": "frozen_pre_cutover_contract", **source["limits"]},
        "source_schema_digest": source["source_schema_digest"],
        "source_composer_digest": canonical_sha256(source),
    }


def _source_row(
    source: str,
    migration: Mapping[str, Any],
    *,
    source_contract: Mapping[str, Any] | None,
    available: bool,
    destination_kinds: frozenset[str],
) -> dict[str, Any]:
    _require_destination(source, migration, destination_kinds)
    return {
        "source": source,
        **strict_json_copy(dict(migration)),
        "available": available,
        "cutover": "remove_old_model_input",
        "source_contract_digest": (
            None
            if source_contract is None
            else canonical_sha256(source_contract)
        ),
    }


def _contract_leaf_inventory(
    *,
    source: str,
    contract: Any,
    migration: Mapping[str, Any],
    destination_kinds: frozenset[str],
) -> dict[str, Any]:
    _require_destination(source, migration, destination_kinds)
    leaves = {
        pointer: strict_json_copy(value)
        for pointer, value in _flatten_contract(contract)
    }
    return {
        "migration_source": source,
        "leaf_count": len(leaves),
        "contract_leaves": leaves,
    }


def _flatten_contract(value: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, Mapping):
        if not value:
            yield pointer, {}
            return
        for key in sorted(value):
            yield from _flatten_contract(
                value[key], f"{pointer}/{_escape_pointer(str(key))}"
            )
        return
    if isinstance(value, list):
        if not value:
            yield pointer, []
            return
        for index, item in enumerate(value):
            yield from _flatten_contract(item, f"{pointer}/{index}")
        return
    yield pointer, value


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _available_in_version(contract: Mapping[str, Any], version: str) -> bool:
    supported = contract.get("supported_versions")
    return not isinstance(supported, list) or version in supported


def _require_destination(
    source: str,
    migration: Mapping[str, Any],
    destination_kinds: frozenset[str],
) -> None:
    if (
        migration.get("destination_kind") not in destination_kinds
        or not isinstance(migration.get("destination"), str)
        or not migration["destination"]
    ):
        raise RuntimeError(f"{source} has an invalid migration destination")


def _require_exact_coverage(
    label: str,
    actual: set[str],
    classified: set[str],
) -> None:
    if actual != classified:
        raise RuntimeError(
            f"audio.import {label} migration coverage drifted: "
            f"missing={sorted(actual - classified)} "
            f"extra={sorted(classified - actual)}"
        )


__all__ = [
    "AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT",
    "AUDIO_IMPORT_MIGRATION_RESOURCE",
    "LEGACY_AUDIO_IMPORT_CONTRACT_RESOURCE",
    "build_audio_import_migration_inventory",
    "load_frozen_audio_import_contract",
]

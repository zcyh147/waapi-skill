"""Machine-readable native WAAPI request-surface audit policy.

Reflection proves what a Wwise version accepts.  A fixed command or dedicated
operation can intentionally expose a narrower, normalized request contract, but
that narrowing must remain explicit.  This module validates the reviewed policy
resource against the checked-in reflected schemas and the public route catalog.

The route audit partitions every public function into either the generic
reflected-schema path with no URI-specific restriction, or a reviewed special
path.  Common result/size/time ceilings still apply to the generic path.
Detailed selector classification is intentionally limited to the high-risk URI
subset that has a meaningfully different public request shape.  It is not an
execution allowlist, and a ``normalized_equivalent`` classification still
needs focused operation tests to prove its implementation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .capabilities import CapabilityCatalog
from .execution_contracts import (
    AUTHORING_UI_EXECUTION_PROFILE,
    CONSOLE_EXECUTION_PROFILE,
)
from .manifest import ManifestStore
from .versions import SUPPORTED_WWISE_VERSION_KEYS


SKILL_ROOT = Path(__file__).resolve().parents[1]
NATIVE_SURFACE_POLICY_PATH = (
    SKILL_ROOT / "resources" / "native_surface_policy.json"
)
NATIVE_SURFACE_POLICY_CONTRACT = "waapi-skill.native-surface-policy/v1"
NATIVE_SURFACE_POLICY_SCOPE = "high_risk_request_surface_differences"
PUBLIC_FUNCTION_ROUTE_AUDIT_CONTRACT = (
    "waapi-skill.public-function-route-audit/v1"
)
NATIVE_SURFACE_STATUSES = (
    "mapped",
    "normalized_equivalent",
    "intentionally_blocked",
    "missing",
)
NATIVE_SURFACE_PROFILES = (
    CONSOLE_EXECUTION_PROFILE,
    AUTHORING_UI_EXECUTION_PROFILE,
)
GENERIC_URI_RESTRICTION_URIS = frozenset(
    {
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.transport.destroy",
    }
)


class NativeSurfacePolicyError(ValueError):
    """The packaged native request-surface policy is malformed or stale."""


def load_native_surface_policy(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load the packaged policy without connecting to Wwise."""

    selected = path or NATIVE_SURFACE_POLICY_PATH
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeSurfacePolicyError(
            f"Unable to load native surface policy {selected}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise NativeSurfacePolicyError(
            "Native surface policy root must be a JSON object."
        )
    return payload


def validate_native_surface_policy(
    payload: Mapping[str, Any] | None = None,
    *,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    """Validate every reviewed selector against reflection and public routes."""

    selected = dict(payload) if payload is not None else load_native_surface_policy()
    if selected.get("contract") != NATIVE_SURFACE_POLICY_CONTRACT:
        raise NativeSurfacePolicyError(
            "Native surface policy contract is missing or unsupported."
        )
    if selected.get("scope") != NATIVE_SURFACE_POLICY_SCOPE:
        raise NativeSurfacePolicyError(
            "Native surface policy scope is missing or unsupported."
        )
    declared_statuses = selected.get("statuses")
    if declared_statuses != list(NATIVE_SURFACE_STATUSES):
        raise NativeSurfacePolicyError(
            "Native surface policy must declare the exact ordered status vocabulary."
        )
    coverage = _require_mapping(selected.get("coverage"), context="coverage")
    rules = selected.get("rules")
    if not isinstance(rules, list) or not rules:
        raise NativeSurfacePolicyError(
            "Native surface policy rules must be a non-empty array."
        )

    store = ManifestStore(
        root=manifest_root
        or (SKILL_ROOT / "resources" / "manifest")
    )
    catalog = CapabilityCatalog(
        manifest_root=store.root,
    )
    route_audit_summary, reviewed_special_uris = (
        _validate_public_function_route_audit(
            selected.get("route_audit"),
            catalog=catalog,
        )
    )
    seen_rows: set[tuple[str, str, str]] = set()
    selector_counts = {status: 0 for status in NATIVE_SURFACE_STATUSES}
    scope_count = 0
    semantic_boundary_count = 0
    high_risk_uris: set[str] = set()

    for index, raw_rule in enumerate(rules):
        rule = _require_mapping(raw_rule, context=f"rules[{index}]")
        uri = _require_text(rule.get("uri"), context=f"rules[{index}].uri")
        high_risk_uris.add(uri)
        profile = _require_text(
            rule.get("profile"),
            context=f"rules[{index}].profile",
        )
        if profile not in NATIVE_SURFACE_PROFILES:
            raise NativeSurfacePolicyError(
                f"rules[{index}].profile is unsupported: {profile!r}"
            )
        versions = _require_versions(
            rule.get("versions"),
            context=f"rules[{index}].versions",
        )
        expected_execution_mode = _require_text(
            rule.get("execution_mode"),
            context=f"rules[{index}].execution_mode",
        )
        expected_operations = _require_text_array(
            rule.get("operations"),
            context=f"rules[{index}].operations",
            allow_empty=True,
        )
        expected_fixed_commands = _require_text_array(
            rule.get("fixed_commands"),
            context=f"rules[{index}].fixed_commands",
            allow_empty=True,
        )
        scopes = rule.get("scopes")
        if not isinstance(scopes, list) or not scopes:
            raise NativeSurfacePolicyError(
                f"rules[{index}].scopes must be a non-empty array."
            )
        scope_pointers = [
            _require_text(
                _require_mapping(
                    scope,
                    context=f"rules[{index}].scopes[{scope_index}]",
                ).get("pointer"),
                context=f"rules[{index}].scopes[{scope_index}].pointer",
            )
            for scope_index, scope in enumerate(scopes)
        ]
        if len(scope_pointers) != len(set(scope_pointers)):
            raise NativeSurfacePolicyError(
                f"rules[{index}] contains duplicate schema pointers."
            )
        if "/argsSchema" not in scope_pointers or "/optionsSchema" not in scope_pointers:
            raise NativeSurfacePolicyError(
                f"rules[{index}] must classify both /argsSchema and /optionsSchema."
            )

        semantic_boundaries = rule.get("semantic_boundaries", [])
        semantic_boundary_count += _validate_semantic_boundaries(
            semantic_boundaries,
            context=f"rules[{index}].semantic_boundaries",
        )

        for version in versions:
            row_key = (version, profile, uri)
            if row_key in seen_rows:
                raise NativeSurfacePolicyError(
                    "Native surface policy contains duplicate version/profile/URI "
                    f"coverage: {row_key!r}"
                )
            seen_rows.add(row_key)
            schema = _schema_for(
                store,
                version=version,
                profile=profile,
                uri=uri,
            )
            capability = _capability_for(
                catalog,
                version=version,
                profile=profile,
                uri=uri,
            )
            if capability.execution_mode != expected_execution_mode:
                raise NativeSurfacePolicyError(
                    f"{row_key!r} execution mode changed: expected "
                    f"{expected_execution_mode!r}, got "
                    f"{capability.execution_mode!r}"
                )
            if list(capability.transaction_operations) != expected_operations:
                raise NativeSurfacePolicyError(
                    f"{row_key!r} transaction operations changed: expected "
                    f"{expected_operations!r}, got "
                    f"{list(capability.transaction_operations)!r}"
                )
            if list(capability.fixed_commands) != expected_fixed_commands:
                raise NativeSurfacePolicyError(
                    f"{row_key!r} fixed commands changed: expected "
                    f"{expected_fixed_commands!r}, got "
                    f"{list(capability.fixed_commands)!r}"
                )
            for scope_index, raw_scope in enumerate(scopes):
                scope = _require_mapping(
                    raw_scope,
                    context=f"rules[{index}].scopes[{scope_index}]",
                )
                pointer = scope_pointers[scope_index]
                counts = _validate_scope(
                    schema,
                    pointer=pointer,
                    classifications=scope.get("classifications"),
                    context=(
                        f"{version}/{profile}/{uri}"
                        f"/scopes[{scope_index}]"
                    ),
                )
                scope_count += 1
                for status, count in counts.items():
                    selector_counts[status] += count

    expected_rows = _expected_coverage_rows(
        coverage,
        store=store,
    )
    if seen_rows != expected_rows:
        missing = sorted(expected_rows - seen_rows)
        unexpected = sorted(seen_rows - expected_rows)
        raise NativeSurfacePolicyError(
            "Native surface policy coverage rows do not match the declared "
            f"audited URI set: missing={missing!r}, unexpected={unexpected!r}"
        )
    if not selector_counts["intentionally_blocked"]:
        raise NativeSurfacePolicyError(
            "The audited-difference policy must retain explicit blocked selectors."
        )
    if selector_counts["missing"]:
        raise NativeSurfacePolicyError(
            "The audited-difference policy must not retain missing selectors."
        )
    if not high_risk_uris.issubset(reviewed_special_uris):
        raise NativeSurfacePolicyError(
            "Every high-risk selector rule must belong to the reviewed special "
            "public-function route inventory."
        )

    return {
        "contract": NATIVE_SURFACE_POLICY_CONTRACT,
        "route_audit": route_audit_summary,
        "version_rows": len(seen_rows),
        "rules": len(rules),
        "scopes": scope_count,
        "schema_selectors": sum(selector_counts.values()),
        "selectors_by_status": selector_counts,
        "semantic_boundaries": semantic_boundary_count,
    }


def _validate_public_function_route_audit(
    value: Any,
    *,
    catalog: CapabilityCatalog,
) -> tuple[dict[str, Any], set[str]]:
    """Bind the complete public function inventory to one auditable partition."""

    audit = _require_mapping(value, context="route_audit")
    if audit.get("contract") != PUBLIC_FUNCTION_ROUTE_AUDIT_CONTRACT:
        raise NativeSurfacePolicyError(
            "route_audit contract is missing or unsupported."
        )
    declared_profiles = _require_mapping(
        audit.get("profiles"),
        context="route_audit.profiles",
    )
    if set(declared_profiles) != set(NATIVE_SURFACE_PROFILES):
        raise NativeSurfacePolicyError(
            "route_audit.profiles must declare both execution profiles."
        )

    actual_profiles: dict[str, dict[str, int]] = {}
    reviewed_special_uris: set[str] = set()
    for profile in NATIVE_SURFACE_PROFILES:
        entries = [
            entry
            for version in SUPPORTED_WWISE_VERSION_KEYS
            for entry in catalog.entries_for_profile(version, profile=profile)
            if entry.item_type == "function"
        ]
        generic_reflected = [
            entry
            for entry in entries
            if _uses_generic_reflected_route_without_uri_specific_restrictions(
                entry
            )
        ]
        special = [
            entry
            for entry in entries
            if not _uses_generic_reflected_route_without_uri_specific_restrictions(
                entry
            )
        ]
        reviewed_special_uris.update(entry.uri for entry in special)
        actual = {
            "function_rows": len(entries),
            "unique_function_uris": len({entry.uri for entry in entries}),
            "generic_reflected_rows": len(generic_reflected),
            "generic_reflected_unique_uris": len(
                {entry.uri for entry in generic_reflected}
            ),
            "special_rows": len(special),
            "special_unique_uris": len({entry.uri for entry in special}),
        }
        declared = _require_mapping(
            declared_profiles.get(profile),
            context=f"route_audit.profiles.{profile}",
        )
        if dict(declared) != actual:
            raise NativeSurfacePolicyError(
                f"route_audit profile counts changed for {profile}: "
                f"expected={dict(declared)!r}, actual={actual!r}"
            )
        actual_profiles[profile] = actual

    declared_special = _require_text_array(
        audit.get("reviewed_special_uris"),
        context="route_audit.reviewed_special_uris",
        allow_empty=False,
    )
    if declared_special != sorted(declared_special):
        raise NativeSurfacePolicyError(
            "route_audit.reviewed_special_uris must be sorted."
        )
    if set(declared_special) != reviewed_special_uris:
        missing = sorted(reviewed_special_uris - set(declared_special))
        stale = sorted(set(declared_special) - reviewed_special_uris)
        raise NativeSurfacePolicyError(
            "route_audit special URI inventory changed: "
            f"missing={missing!r}, stale={stale!r}"
        )

    declared_generic_restrictions = _require_mapping(
        audit.get("reviewed_generic_restrictions"),
        context="route_audit.reviewed_generic_restrictions",
    )
    if set(declared_generic_restrictions) != set(
        GENERIC_URI_RESTRICTION_URIS
    ):
        missing = sorted(
            set(GENERIC_URI_RESTRICTION_URIS)
            - set(declared_generic_restrictions)
        )
        stale = sorted(
            set(declared_generic_restrictions)
            - set(GENERIC_URI_RESTRICTION_URIS)
        )
        raise NativeSurfacePolicyError(
            "route_audit generic restriction inventory changed: "
            f"missing={missing!r}, stale={stale!r}"
        )
    for uri, reason in declared_generic_restrictions.items():
        _require_text(
            reason,
            context=f"route_audit.reviewed_generic_restrictions.{uri}",
        )

    return (
        {
            "contract": PUBLIC_FUNCTION_ROUTE_AUDIT_CONTRACT,
            "profiles": actual_profiles,
            "reviewed_special_uri_count": len(reviewed_special_uris),
            "reviewed_generic_restriction_count": len(
                declared_generic_restrictions
            ),
        },
        reviewed_special_uris,
    )


def _uses_generic_reflected_route_without_uri_specific_restrictions(
    entry: Any,
) -> bool:
    return entry.uri not in GENERIC_URI_RESTRICTION_URIS and (
        entry.preferred_route == "manifest_dispatch"
        or (
            entry.preferred_route == "transaction_operation"
            and tuple(entry.transaction_operations) == ("waapi.call",)
        )
    )


def _validate_scope(
    schema: Mapping[str, Any],
    *,
    pointer: str,
    classifications: Any,
    context: str,
) -> dict[str, int]:
    node = _json_pointer(schema, pointer, context=context)
    reflected = _surface_tokens(node, context=f"{context}:{pointer}")
    classified = _require_mapping(
        classifications,
        context=f"{context}.classifications",
    )
    if list(classified) != list(NATIVE_SURFACE_STATUSES):
        raise NativeSurfacePolicyError(
            f"{context}.classifications must use the exact ordered status keys."
        )
    owners: dict[str, str] = {}
    counts: dict[str, int] = {}
    for status in NATIVE_SURFACE_STATUSES:
        selectors = _require_text_array(
            classified.get(status),
            context=f"{context}.classifications.{status}",
            allow_empty=True,
        )
        counts[status] = len(selectors)
        for selector in selectors:
            previous = owners.setdefault(selector, status)
            if previous != status:
                raise NativeSurfacePolicyError(
                    f"{context} selector {selector!r} is classified as both "
                    f"{previous!r} and {status!r}."
                )
    classified_selectors = set(owners)
    if classified_selectors != reflected:
        missing = sorted(reflected - classified_selectors)
        stale = sorted(classified_selectors - reflected)
        raise NativeSurfacePolicyError(
            f"{context} does not exactly classify reflected surface {pointer}: "
            f"unclassified={missing!r}, stale={stale!r}"
        )
    return counts


def _surface_tokens(node: Any, *, context: str) -> set[str]:
    if not isinstance(node, Mapping):
        raise NativeSurfacePolicyError(
            f"{context} must resolve to a JSON Schema object."
        )
    tokens: set[str] = set()
    properties = node.get("properties", {})
    if not isinstance(properties, Mapping):
        raise NativeSurfacePolicyError(
            f"{context}.properties must be an object when present."
        )
    tokens.update(str(name) for name in properties)
    patterns = node.get("patternProperties", {})
    if not isinstance(patterns, Mapping):
        raise NativeSurfacePolicyError(
            f"{context}.patternProperties must be an object when present."
        )
    tokens.update(f"pattern:{pattern}" for pattern in patterns)
    ref = node.get("$ref")
    if ref is not None:
        if not isinstance(ref, str) or not ref:
            raise NativeSurfacePolicyError(
                f"{context} contains a malformed $ref."
            )
        if tokens:
            raise NativeSurfacePolicyError(
                f"{context} mixes a root $ref with inline surface fields."
            )
        tokens.add(f"$ref:{ref}")
    return tokens


def _json_pointer(
    root: Mapping[str, Any],
    pointer: str,
    *,
    context: str,
) -> Any:
    if pointer == "":
        return root
    if not pointer.startswith("/"):
        raise NativeSurfacePolicyError(
            f"{context} schema pointer must be an RFC 6901 absolute pointer."
        )
    current: Any = root
    for raw_segment in pointer[1:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or segment not in current:
            raise NativeSurfacePolicyError(
                f"{context} schema pointer does not resolve: {pointer!r}"
            )
        current = current[segment]
    return current


def _schema_for(
    store: ManifestStore,
    *,
    version: str,
    profile: str,
    uri: str,
) -> Mapping[str, Any]:
    manifest = (
        store.load(version)
        if profile == CONSOLE_EXECUTION_PROFILE
        else store.load_with_authoring_ui_commands(version)
    )
    rows = [
        row
        for row in manifest.get("schemas", [])
        if isinstance(row, Mapping) and row.get("uri") == uri
    ]
    if len(rows) != 1:
        raise NativeSurfacePolicyError(
            f"Expected one reflected schema for {(version, profile, uri)!r}, "
            f"got {len(rows)}."
        )
    row = rows[0]
    schema = row.get("schema")
    if row.get("status") != "ok" or not isinstance(schema, Mapping):
        raise NativeSurfacePolicyError(
            f"Reflected schema is unavailable for {(version, profile, uri)!r}."
        )
    return schema


def _capability_for(
    catalog: CapabilityCatalog,
    *,
    version: str,
    profile: str,
    uri: str,
) -> Any:
    rows = [
        row
        for row in catalog.entries_for_profile(version, profile=profile)
        if row.item_type == "function" and row.uri == uri
    ]
    if len(rows) != 1:
        raise NativeSurfacePolicyError(
            f"Expected one public function capability for "
            f"{(version, profile, uri)!r}, got {len(rows)}."
        )
    return rows[0]


def _expected_coverage_rows(
    coverage: Mapping[str, Any],
    *,
    store: ManifestStore,
) -> set[tuple[str, str, str]]:
    if set(coverage) != set(NATIVE_SURFACE_PROFILES):
        raise NativeSurfacePolicyError(
            "Native surface policy coverage must declare both execution profiles."
        )
    expected: set[tuple[str, str, str]] = set()
    for profile in NATIVE_SURFACE_PROFILES:
        uris = _require_text_array(
            coverage.get(profile),
            context=f"coverage.{profile}",
            allow_empty=True,
        )
        for version in SUPPORTED_WWISE_VERSION_KEYS:
            manifest = (
                store.load(version)
                if profile == CONSOLE_EXECUTION_PROFILE
                else store.load_with_authoring_ui_commands(version)
            )
            reflected_functions = {
                str(row.get("uri"))
                for row in manifest.get("functions", [])
                if isinstance(row, Mapping)
            }
            for uri in uris:
                if uri in reflected_functions:
                    expected.add((version, profile, uri))
    return expected


def _validate_semantic_boundaries(value: Any, *, context: str) -> int:
    if not isinstance(value, list):
        raise NativeSurfacePolicyError(f"{context} must be an array.")
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = _require_mapping(raw, context=f"{context}[{index}]")
        selector = _require_text(
            item.get("selector"),
            context=f"{context}[{index}].selector",
        )
        if selector in seen:
            raise NativeSurfacePolicyError(
                f"{context} contains duplicate selector {selector!r}."
            )
        seen.add(selector)
        status = item.get("status")
        if status not in NATIVE_SURFACE_STATUSES:
            raise NativeSurfacePolicyError(
                f"{context}[{index}].status is unsupported: {status!r}"
            )
        _require_text(
            item.get("reason"),
            context=f"{context}[{index}].reason",
        )
    return len(value)


def _require_mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeSurfacePolicyError(f"{context} must be a JSON object.")
    return value


def _require_text(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise NativeSurfacePolicyError(f"{context} must be a non-empty string.")
    return value


def _require_text_array(
    value: Any,
    *,
    context: str,
    allow_empty: bool,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        suffix = "" if allow_empty else " non-empty"
        raise NativeSurfacePolicyError(
            f"{context} must be a{suffix} string array."
        )
    if len(value) != len(set(value)):
        raise NativeSurfacePolicyError(
            f"{context} must not contain duplicates."
        )
    return list(value)


def _require_versions(value: Any, *, context: str) -> tuple[str, ...]:
    versions = _require_text_array(
        value,
        context=context,
        allow_empty=False,
    )
    unsupported = sorted(set(versions) - set(SUPPORTED_WWISE_VERSION_KEYS))
    if unsupported:
        raise NativeSurfacePolicyError(
            f"{context} contains unsupported versions: {unsupported!r}"
        )
    if versions != [
        version for version in SUPPORTED_WWISE_VERSION_KEYS if version in versions
    ]:
        raise NativeSurfacePolicyError(
            f"{context} must follow supported-version order."
        )
    return tuple(versions)


__all__ = [
    "NATIVE_SURFACE_POLICY_CONTRACT",
    "NATIVE_SURFACE_POLICY_PATH",
    "NATIVE_SURFACE_STATUSES",
    "NativeSurfacePolicyError",
    "load_native_surface_policy",
    "validate_native_surface_policy",
]

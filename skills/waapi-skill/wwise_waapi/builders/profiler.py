"""Bounded profiler/log semantic parameter guidance.

This module intentionally stays narrow: it returns compact parameter-shape
assistance for profiler/log-like URIs without building workflow trees or
loading broad schema/doc bundles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from wwise_waapi.deferred_registry import ApiClassifier, DeferredRegistry
from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION

from .common import ManifestSchemaLoader, SemanticErrorCode, SemanticValidationError


PROFILER_PARAMETER_GUIDANCE_SIZE_LIMIT = 2048
SUPPORTED_PROFILER_GUIDANCE_CATEGORIES = frozenset({"core.log", "core.profiler", "core.profiler.captureLog"})
PROFILER_GUIDANCE_SOURCE_PRIORITY = (
    "packaged-deferred-registry",
    "targeted-uri-schema",
    "official-docs-excluded-by-policy",
)


@dataclass(slots=True, frozen=True)
class ProfilerParameterGuidance:
    """Compact, source-backed guidance for a single profiler/log-like URI."""

    uri: str
    family: str
    version: str = DEFAULT_WWISE_VERSION
    parameter_shape: tuple[str, ...] = ()
    setup_hints: tuple[str, ...] = ()
    blocker_hints: tuple[str, ...] = ()
    source_priority: tuple[str, ...] = PROFILER_GUIDANCE_SOURCE_PRIORITY
    provenance: tuple[Mapping[str, Any], ...] = ()
    size_ceiling: int = PROFILER_PARAMETER_GUIDANCE_SIZE_LIMIT

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "uri": self.uri,
            "family": self.family,
            "version": self.version,
            "parameter_shape": list(self.parameter_shape),
            "setup_hints": list(self.setup_hints),
            "blocker_hints": list(self.blocker_hints),
            "source_priority": list(self.source_priority),
            "provenance": [dict(item) for item in self.provenance],
            "size_ceiling": self.size_ceiling,
        }
        _ensure_size_ceiling(payload, self.uri, self.version, self.size_ceiling)
        return payload


def extract_profiler_parameter_guidance(
    uri: str,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
    deferred_registry: DeferredRegistry | None = None,
) -> ProfilerParameterGuidance:
    """Return bounded parameter guidance for one profiler/log-like WAAPI URI."""

    classification = ApiClassifier().classify(uri)
    if classification.category not in SUPPORTED_PROFILER_GUIDANCE_CATEGORIES:
        raise SemanticValidationError(
            SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY,
            f"Unsupported profiler/log-like URI family: {classification.category}",
            details={"uri": uri, "family": classification.category, "version": version},
        )

    registry = deferred_registry or DeferredRegistry.load_default(version)
    try:
        deferred = registry.require(uri)
    except KeyError as exc:
        raise SemanticValidationError(
            SemanticErrorCode.MISSING_SOURCE_NOTE,
            f"Profiler/log-like URI is not recorded in the deferred registry: {uri}",
            details={"uri": uri, "family": classification.category, "version": version},
        ) from exc

    loader = manifest_loader or ManifestSchemaLoader()
    schema = loader.schema_for(uri, version)

    args_schema = _mapping_or_empty(schema.get("argsSchema"))
    options_schema = _mapping_or_empty(schema.get("optionsSchema"))
    result_schema = _mapping_or_empty(schema.get("resultSchema"))

    required_args = _string_tuple(args_schema.get("required"))
    args_fields = _property_names(args_schema)
    option_fields = _property_names(options_schema)
    result_fields = _property_names(result_schema)

    guidance = ProfilerParameterGuidance(
        uri=uri,
        family=classification.category,
        version=version,
        parameter_shape=_parameter_shape(required_args, args_fields, option_fields, result_fields),
        setup_hints=_setup_hints(deferred, classification.category),
        blocker_hints=_blocker_hints(deferred),
        provenance=_provenance(uri, classification.category, version, deferred),
    )
    guidance.as_dict()
    return guidance


def _parameter_shape(
    required_args: tuple[str, ...],
    args_fields: tuple[str, ...],
    option_fields: tuple[str, ...],
    result_fields: tuple[str, ...],
) -> tuple[str, ...]:
    session_fields = _bucket_fields(required_args, args_fields, tokens=("session", "captureSession", "profilerSession"))
    id_fields = _bucket_fields(
        required_args,
        args_fields,
        tokens=("id", "gameObject", "object", "meter", "switchGroup", "stateGroup"),
        exclude=session_fields,
    )
    range_fields = _bucket_fields(
        required_args,
        args_fields,
        tokens=("start", "end", "range", "cursor", "time", "position", "percent", "from", "to", "duration"),
        exclude=session_fields + id_fields,
    )
    output_fields = _bucket_fields(
        option_fields,
        result_fields,
        tokens=("return", "fields", "output"),
        exclude=session_fields + id_fields + range_fields,
    )

    return (
        _shape_line("session", session_fields),
        _shape_line("id", id_fields),
        _shape_line("range", range_fields),
        _shape_line("output", output_fields),
    )


def _setup_hints(deferred: Any, family: str) -> tuple[str, ...]:
    setup: list[str] = [_compact_text(str(deferred.reason))]
    if family == "core.profiler.captureLog":
        setup.append("setup: capture-log topic guidance stays inventory-only.")
    if family == "core.log":
        setup.append("setup: log guidance stays compact and read-only.")
    return tuple(item for item in setup if item)


def _blocker_hints(deferred: Any) -> tuple[str, ...]:
    hints = (
        _compact_text(str(deferred.blocking_condition)),
        _compact_text(str(deferred.substitute_test)),
    )
    return tuple(item for item in hints if item)


def _provenance(uri: str, family: str, version: str, deferred: Any) -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "source": "packaged-deferred-registry",
            "uri": uri,
            "family": family,
            "version": version,
            "path": f"resources/deferred/{version}.json#{uri}",
            "category": deferred.category,
        },
        {
            "source": "targeted-uri-schema",
            "uri": uri,
            "family": family,
            "version": version,
            "path": f"resources/manifest/{version}/schemas.json#{uri}",
        },
    )


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _property_names(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(str(name) for name in properties if isinstance(name, str))


def _bucket_fields(*groups: tuple[str, ...], tokens: tuple[str, ...], exclude: tuple[str, ...] = ()) -> tuple[str, ...]:
    seen: set[str] = set()
    bucket: list[str] = []
    excluded = set(exclude)
    lowered_tokens = tuple(token.lower() for token in tokens)
    for group in groups:
        for field_name in group:
            if field_name in excluded:
                continue
            lowered = field_name.lower()
            if not any(token in lowered for token in lowered_tokens):
                continue
            if field_name in seen:
                continue
            seen.add(field_name)
            bucket.append(field_name)
    return tuple(bucket)


def _shape_line(label: str, fields: tuple[str, ...]) -> str:
    return f"{label}: {', '.join(fields) if fields else 'none'}"


def _compact_text(text: str) -> str:
    return " ".join(text.split())


def _ensure_size_ceiling(payload: Mapping[str, Any], uri: str, version: str, ceiling: int) -> None:
    encoded = json.dumps(payload, sort_keys=True)
    if len(encoded) > ceiling:
        raise SemanticValidationError(
            SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            f"Profiler guidance payload exceeded compact size limit for {uri!r}.",
            details={"uri": uri, "version": version, "size": len(encoded), "limit": ceiling},
        )

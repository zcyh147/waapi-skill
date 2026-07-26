"""Narrow Authoring reflection supplement for ``ak.wwise.ui.commands``.

The packaged Console manifest remains canonical.  This module can add or
schema-override only the four UI-command functions and their one topic.  It is
deliberately not a general Console/Authoring inventory union.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256


CONSOLE_HOST_SURFACE = "wwise-console"
AUTHORING_HOST_SURFACE = "wwise-authoring"
AUTHORING_UI_COMMANDS_SUPPLEMENT_FORMAT = (
    "waapi-authoring-ui-commands-supplement-v1"
)
AUTHORING_UI_COMMANDS_SURFACE_FORMAT = (
    "waapi-console-with-authoring-ui-commands-v1"
)
AUTHORING_UI_COMMANDS_SUPPLEMENT_FILENAME = (
    "authoring-ui-commands-supplement.json"
)
AUTHORING_UI_COMMAND_FUNCTION_URIS = frozenset(
    {
        "ak.wwise.ui.commands.execute",
        "ak.wwise.ui.commands.getCommands",
        "ak.wwise.ui.commands.register",
        "ak.wwise.ui.commands.unregister",
    }
)
AUTHORING_UI_COMMAND_TOPIC_URIS = frozenset(
    {"ak.wwise.ui.commands.executed"}
)
AUTHORING_UI_COMMAND_URIS = (
    AUTHORING_UI_COMMAND_FUNCTION_URIS | AUTHORING_UI_COMMAND_TOPIC_URIS
)
_URI_RE = re.compile(r"^ak(?:\.[A-Za-z0-9_]+)+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AuthoringUiCommandsSupplementError(ValueError):
    """Raised when the fixed Authoring UI-command delta is malformed."""


class AuthoringUiCommandsSupplementMissingError(FileNotFoundError):
    """Raised when explicitly requested UI-command reflection is unavailable."""

    def __init__(self, version: str, path: Path | None = None) -> None:
        self.version = version
        self.path = path
        location = f": {path}" if path is not None else ""
        super().__init__(
            "Authoring UI-command manifest supplement is missing for "
            f"Wwise {version}{location}"
        )


@dataclass(frozen=True, slots=True)
class AuthoringUiCommandsSupplementAudit:
    """Count and digest summary for the fixed five-URI supplement."""

    added_function_count: int
    added_topic_count: int
    added_schema_count: int
    schema_override_count: int
    schema_failure_count: int
    inventory_sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "added_function_count": self.added_function_count,
            "added_schema_count": self.added_schema_count,
            "added_topic_count": self.added_topic_count,
            "inventory_sha256": self.inventory_sha256,
            "schema_failure_count": self.schema_failure_count,
            "schema_override_count": self.schema_override_count,
        }


@dataclass(slots=True)
class AuthoringUiCommandsSupplement:
    """Versioned Authoring evidence for only the ``ui.commands`` family."""

    version: str
    metadata: dict[str, Any]
    functions: list[dict[str, Any]] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    schemas: list[dict[str, Any]] = field(default_factory=list)
    schema_overrides: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.metadata = _normalize_metadata(self.version, self.metadata)
        self.functions = _normalize_entries(
            self.functions, kind="function", label="functions"
        )
        self.topics = _normalize_entries(
            self.topics, kind="topic", label="topics"
        )
        self.schemas = _normalize_schemas(self.schemas, label="schemas")
        self.schema_overrides = _normalize_schemas(
            self.schema_overrides, label="schema_overrides"
        )
        _validate_delta(self)

    @property
    def audit(self) -> AuthoringUiCommandsSupplementAudit:
        schema_rows = [*self.schemas, *self.schema_overrides]
        return AuthoringUiCommandsSupplementAudit(
            added_function_count=len(self.functions),
            added_topic_count=len(self.topics),
            added_schema_count=len(self.schemas),
            schema_override_count=len(self.schema_overrides),
            schema_failure_count=sum(
                row.get("status") != "ok" for row in schema_rows
            ),
            inventory_sha256=canonical_sha256(
                {
                    "authoring_ui_commands_reflection_sha256": self.metadata[
                        "authoring_ui_commands_reflection_sha256"
                    ],
                    "format": AUTHORING_UI_COMMANDS_SUPPLEMENT_FORMAT,
                    "functions": self.functions,
                    "schema_overrides": self.schema_overrides,
                    "schemas": self.schemas,
                    "topics": self.topics,
                    "version": self.version,
                }
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "audit": self.audit.as_dict(),
            "format": AUTHORING_UI_COMMANDS_SUPPLEMENT_FORMAT,
            "functions": self.functions,
            "metadata": self.metadata,
            "schema_overrides": self.schema_overrides,
            "schemas": self.schemas,
            "topics": self.topics,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_version: str | None = None,
    ) -> AuthoringUiCommandsSupplement:
        if payload.get("format") != AUTHORING_UI_COMMANDS_SUPPLEMENT_FORMAT:
            raise AuthoringUiCommandsSupplementError(
                "Invalid Authoring UI-command supplement format"
            )
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            raise AuthoringUiCommandsSupplementError(
                "Authoring UI-command supplement metadata must be an object"
            )
        version = metadata.get("wwise_version_target")
        if not isinstance(version, str):
            raise AuthoringUiCommandsSupplementError(
                "metadata.wwise_version_target must be a string"
            )
        if expected_version is not None and version != expected_version:
            raise AuthoringUiCommandsSupplementError(
                f"Supplement targets Wwise {version}, expected {expected_version}"
            )
        supplement = cls(
            version=version,
            metadata=dict(metadata),
            functions=_list_field(payload, "functions"),
            topics=_list_field(payload, "topics"),
            schemas=_list_field(payload, "schemas"),
            schema_overrides=_list_field(payload, "schema_overrides"),
        )
        if payload.get("audit") != supplement.audit.as_dict():
            raise AuthoringUiCommandsSupplementError(
                "Authoring UI-command supplement audit or inventory digest "
                "does not match its contents"
            )
        return supplement


def manifest_inventory_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash row identity and schemas, detecting same-count substitutions."""

    functions, topics, schemas = _normalize_manifest(manifest)
    return canonical_sha256(
        {"functions": functions, "schemas": schemas, "topics": topics}
    )


def build_authoring_ui_commands_supplement(
    console_manifest: Mapping[str, Any],
    authoring_manifest: Any,
    *,
    version: str,
    inventory_source: str = "live-reflection-authoring",
) -> AuthoringUiCommandsSupplement:
    """Select the five UI-command rows; ignore every other GUI-only API."""

    authoring_payload = (
        authoring_manifest.as_dict()
        if callable(getattr(authoring_manifest, "as_dict", None))
        else authoring_manifest
    )
    _require_version(console_manifest, version, "Console manifest")
    _require_version(authoring_payload, version, "Authoring manifest")
    declared_surface = _metadata(authoring_payload).get("host_surface")
    if declared_surface not in (None, AUTHORING_HOST_SURFACE):
        raise AuthoringUiCommandsSupplementError(
            f"Authoring reflection has host_surface={declared_surface!r}"
        )

    console_functions, console_topics, console_schemas = _normalize_manifest(
        console_manifest
    )
    authoring_functions, authoring_topics, authoring_schemas = (
        _normalize_manifest(authoring_payload)
    )
    cf, ct, cs = map(_by_uri, (console_functions, console_topics, console_schemas))
    af, at, ass = map(
        _by_uri, (authoring_functions, authoring_topics, authoring_schemas)
    )
    missing_functions = AUTHORING_UI_COMMAND_FUNCTION_URIS - set(af)
    missing_topics = AUTHORING_UI_COMMAND_TOPIC_URIS - set(at)
    if missing_functions or missing_topics:
        raise AuthoringUiCommandsSupplementError(
            "Authoring reflection is missing ui.commands rows: "
            f"functions={sorted(missing_functions)!r}, "
            f"topics={sorted(missing_topics)!r}"
        )
    wrong_console_kinds = (
        (AUTHORING_UI_COMMAND_FUNCTION_URIS & set(ct))
        | (AUTHORING_UI_COMMAND_TOPIC_URIS & set(cf))
    )
    if wrong_console_kinds:
        raise AuthoringUiCommandsSupplementError(
            "Console manifest classifies ui.commands rows with the wrong type: "
            f"{sorted(wrong_console_kinds)!r}"
        )

    added_functions = AUTHORING_UI_COMMAND_FUNCTION_URIS - set(cf)
    added_topics = AUTHORING_UI_COMMAND_TOPIC_URIS - set(ct)
    added_uris = added_functions | added_topics
    common_uris = AUTHORING_UI_COMMAND_URIS - added_uris
    selected = {
        "functions": [af[uri] for uri in sorted(AUTHORING_UI_COMMAND_FUNCTION_URIS)],
        "schemas": [ass[uri] for uri in sorted(AUTHORING_UI_COMMAND_URIS)],
        "topics": [at[uri] for uri in sorted(AUTHORING_UI_COMMAND_TOPIC_URIS)],
    }
    authoring_metadata = _metadata(authoring_payload)
    return AuthoringUiCommandsSupplement(
        version=version,
        metadata={
            "authoring_ui_commands_reflection_sha256": (
                manifest_inventory_sha256(selected)
            ),
            "base_host_surface": CONSOLE_HOST_SURFACE,
            "console_reflection_inventory_sha256": (
                manifest_inventory_sha256(console_manifest)
            ),
            "generator": (
                "wwise_waapi.authoring_ui_commands_manifest."
                "build_authoring_ui_commands_supplement"
            ),
            "host_surface": AUTHORING_HOST_SURFACE,
            "inventory_source": inventory_source,
            "manifest_origin": "authoring-ui-commands-reflection",
            "scope_uris": sorted(AUTHORING_UI_COMMAND_URIS),
            "surface_scope": "ak.wwise.ui.commands",
            "wwise_build": authoring_metadata.get("wwise_build", "unknown"),
            "wwise_version_target": version,
        },
        functions=[af[uri] for uri in sorted(added_functions)],
        topics=[at[uri] for uri in sorted(added_topics)],
        schemas=[ass[uri] for uri in sorted(added_uris)],
        schema_overrides=[
            ass[uri]
            for uri in sorted(common_uris)
            if ass[uri] != cs[uri]
        ],
    )


def merge_authoring_ui_commands_surface(
    console_manifest: Mapping[str, Any],
    supplement: AuthoringUiCommandsSupplement | Mapping[str, Any],
) -> dict[str, Any]:
    """Return an explicitly mixed Console + Authoring UI-command inventory."""

    if not isinstance(supplement, AuthoringUiCommandsSupplement):
        supplement = AuthoringUiCommandsSupplement.from_dict(supplement)
    _require_version(console_manifest, supplement.version, "Console manifest")
    functions, topics, schemas = _normalize_manifest(console_manifest)
    function_map, topic_map, schema_map = map(
        _by_uri, (functions, topics, schemas)
    )
    added_functions = _by_uri(supplement.functions)
    added_topics = _by_uri(supplement.topics)
    added_schemas = _by_uri(supplement.schemas)
    overrides = _by_uri(supplement.schema_overrides)
    console_uris = set(function_map) | set(topic_map)
    added_uris = set(added_functions) | set(added_topics)
    if added_uris & console_uris:
        raise AuthoringUiCommandsSupplementError(
            "UI-command additions duplicate Console rows: "
            f"{sorted(added_uris & console_uris)!r}"
        )
    common_ui_uris = console_uris & AUTHORING_UI_COMMAND_URIS
    if not set(overrides) <= common_ui_uris:
        raise AuthoringUiCommandsSupplementError(
            "UI-command schema overrides contain non-common URIs"
        )
    if any(overrides[uri] == schema_map[uri] for uri in overrides):
        raise AuthoringUiCommandsSupplementError(
            "UI-command schema override is identical to the Console schema"
        )
    if (
        supplement.metadata["console_reflection_inventory_sha256"]
        != manifest_inventory_sha256(console_manifest)
    ):
        raise AuthoringUiCommandsSupplementError(
            "Supplement was derived from a different Console inventory"
        )

    selected_functions = {
        uri: row
        for uri, row in function_map.items()
        if uri in AUTHORING_UI_COMMAND_FUNCTION_URIS
    }
    selected_functions.update(added_functions)
    selected_topics = {
        uri: row
        for uri, row in topic_map.items()
        if uri in AUTHORING_UI_COMMAND_TOPIC_URIS
    }
    selected_topics.update(added_topics)
    selected_schemas = {
        uri: schema_map[uri] for uri in common_ui_uris
    }
    selected_schemas.update(added_schemas)
    selected_schemas.update(overrides)
    if (
        set(selected_functions) != AUTHORING_UI_COMMAND_FUNCTION_URIS
        or set(selected_topics) != AUTHORING_UI_COMMAND_TOPIC_URIS
        or set(selected_schemas) != AUTHORING_UI_COMMAND_URIS
    ):
        raise AuthoringUiCommandsSupplementError(
            "Composed ui.commands inventory is incomplete"
        )
    selected = {
        "functions": list(selected_functions.values()),
        "schemas": list(selected_schemas.values()),
        "topics": list(selected_topics.values()),
    }
    if (
        manifest_inventory_sha256(selected)
        != supplement.metadata["authoring_ui_commands_reflection_sha256"]
    ):
        raise AuthoringUiCommandsSupplementError(
            "Supplement does not reconstruct its reflected five-URI inventory"
        )

    merged_functions = [
        _mark(
            row,
            AUTHORING_HOST_SURFACE
            if row["uri"] in AUTHORING_UI_COMMAND_URIS
            else CONSOLE_HOST_SURFACE,
            "console-manifest",
        )
        for row in functions
    ] + [
        _mark(row, AUTHORING_HOST_SURFACE, "authoring-ui-commands-supplement")
        for row in added_functions.values()
    ]
    merged_topics = [
        _mark(
            row,
            AUTHORING_HOST_SURFACE
            if row["uri"] in AUTHORING_UI_COMMAND_URIS
            else CONSOLE_HOST_SURFACE,
            "console-manifest",
        )
        for row in topics
    ] + [
        _mark(row, AUTHORING_HOST_SURFACE, "authoring-ui-commands-supplement")
        for row in added_topics.values()
    ]
    merged_schema_map = {
        row["uri"]: _mark(
            row,
            AUTHORING_HOST_SURFACE
            if row["uri"] in AUTHORING_UI_COMMAND_URIS
            else CONSOLE_HOST_SURFACE,
            "console-manifest",
        )
        for row in schemas
    }
    merged_schema_map.update(
        {
            uri: _mark(
                row,
                AUTHORING_HOST_SURFACE,
                "authoring-ui-commands-supplement",
            )
            for uri, row in added_schemas.items()
        }
    )
    merged_schema_map.update(
        {
            uri: _mark(
                row,
                AUTHORING_HOST_SURFACE,
                "authoring-ui-commands-schema-override",
            )
            for uri, row in overrides.items()
        }
    )
    merged_functions.sort(key=lambda row: row["uri"])
    merged_topics.sort(key=lambda row: row["uri"])
    merged_schemas = [
        merged_schema_map[uri] for uri in sorted(merged_schema_map)
    ]
    surface_digest = canonical_sha256(
        {
            "format": AUTHORING_UI_COMMANDS_SURFACE_FORMAT,
            "functions": merged_functions,
            "schemas": merged_schemas,
            "topics": merged_topics,
            "version": supplement.version,
        }
    )
    metadata = deepcopy(_metadata(console_manifest))
    metadata.update(
        {
            "authoring_ui_commands_supplement_sha256": (
                supplement.audit.inventory_sha256
            ),
            "base_host_surface": CONSOLE_HOST_SURFACE,
            "format": AUTHORING_UI_COMMANDS_SURFACE_FORMAT,
            "full_authoring_inventory_reflected": False,
            "manifest_origin": (
                "console-manifest+authoring-ui-commands-supplement"
            ),
            "surface_inventory_sha256": surface_digest,
            "surface_profile": "console-with-authoring-ui-commands",
            "wwise_version_target": supplement.version,
        }
    )
    base_audit = console_manifest.get("audit")
    return {
        "audit": {
            "authoring_ui_commands_supplement": supplement.audit.as_dict(),
            "base_console": (
                deepcopy(dict(base_audit))
                if isinstance(base_audit, Mapping)
                else {}
            ),
            "full_authoring_inventory_reflected": False,
            "surface_inventory_sha256": surface_digest,
            "surface_profile": "console-with-authoring-ui-commands",
        },
        "format": AUTHORING_UI_COMMANDS_SURFACE_FORMAT,
        "functions": merged_functions,
        "metadata": metadata,
        "schemas": merged_schemas,
        "topics": merged_topics,
    }


def _normalize_metadata(
    version: str, metadata: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(version, str) or not re.fullmatch(r"\d{4}\.\d+", version):
        raise AuthoringUiCommandsSupplementError(
            f"Invalid Wwise version key: {version!r}"
        )
    if not isinstance(metadata, Mapping):
        raise AuthoringUiCommandsSupplementError("metadata must be an object")
    value = deepcopy(dict(metadata))
    declared_version = value.get("wwise_version_target")
    if declared_version not in (None, version):
        raise AuthoringUiCommandsSupplementError(
            f"metadata targets Wwise {declared_version!r}, expected {version!r}"
        )
    value.setdefault("base_host_surface", CONSOLE_HOST_SURFACE)
    value.setdefault("host_surface", AUTHORING_HOST_SURFACE)
    value.setdefault("scope_uris", sorted(AUTHORING_UI_COMMAND_URIS))
    value.setdefault("surface_scope", "ak.wwise.ui.commands")
    value["wwise_version_target"] = version
    if value["base_host_surface"] != CONSOLE_HOST_SURFACE:
        raise AuthoringUiCommandsSupplementError(
            "base_host_surface must be 'wwise-console'"
        )
    if value["host_surface"] != AUTHORING_HOST_SURFACE:
        raise AuthoringUiCommandsSupplementError(
            "host_surface must be 'wwise-authoring'"
        )
    if value["scope_uris"] != sorted(AUTHORING_UI_COMMAND_URIS):
        raise AuthoringUiCommandsSupplementError(
            "scope_uris must be the fixed five-URI family"
        )
    if value["surface_scope"] != "ak.wwise.ui.commands":
        raise AuthoringUiCommandsSupplementError(
            "surface_scope must be 'ak.wwise.ui.commands'"
        )
    for field_name in (
        "authoring_ui_commands_reflection_sha256",
        "console_reflection_inventory_sha256",
    ):
        if not _SHA256_RE.fullmatch(str(value.get(field_name, ""))):
            raise AuthoringUiCommandsSupplementError(
                f"{field_name} must be a lowercase SHA-256 digest"
            )
    try:
        canonical_sha256(value)
    except (TypeError, ValueError) as exc:
        raise AuthoringUiCommandsSupplementError(
            "metadata must be finite JSON"
        ) from exc
    return value


def _normalize_manifest(
    manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(manifest, Mapping):
        raise AuthoringUiCommandsSupplementError("manifest must be an object")
    functions = _normalize_entries(
        _list_field(manifest, "functions"),
        kind="function",
        label="manifest.functions",
    )
    topics = _normalize_entries(
        _list_field(manifest, "topics"),
        kind="topic",
        label="manifest.topics",
    )
    schemas = _normalize_schemas(
        _list_field(manifest, "schemas"), label="manifest.schemas"
    )
    inventory_uris = {row["uri"] for row in [*functions, *topics]}
    if len(inventory_uris) != len(functions) + len(topics):
        raise AuthoringUiCommandsSupplementError(
            "manifest URI is both function and topic"
        )
    schema_uris = {row["uri"] for row in schemas}
    if schema_uris != inventory_uris:
        raise AuthoringUiCommandsSupplementError(
            "manifest schemas must match function/topic URIs exactly"
        )
    return functions, topics, schemas


def _normalize_entries(
    rows: Sequence[Any], *, kind: str, label: str
) -> list[dict[str, Any]]:
    if isinstance(rows, (str, bytes)):
        raise AuthoringUiCommandsSupplementError(f"{label} must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}] must be an object"
            )
        uri = _uri(raw.get("uri"), f"{label}[{index}].uri")
        if uri in seen:
            raise AuthoringUiCommandsSupplementError(
                f"{label} contains duplicate URI {uri!r}"
            )
        if raw.get("type") != kind:
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}].type must be {kind!r}"
            )
        reflection = raw.get("reflection")
        if not isinstance(reflection, Mapping) or reflection.get("uri") != uri:
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}].reflection.uri must match {uri!r}"
            )
        if "host_surface" in raw or "manifest_origin" in raw:
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}] contains reserved origin fields"
            )
        row = deepcopy(dict(raw))
        _finite_json(row, f"{label}[{index}]")
        result.append(row)
        seen.add(uri)
    return sorted(result, key=lambda row: row["uri"])


def _normalize_schemas(
    rows: Sequence[Any], *, label: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}] must be an object"
            )
        uri = _uri(raw.get("uri"), f"{label}[{index}].uri")
        if uri in seen:
            raise AuthoringUiCommandsSupplementError(
                f"{label} contains duplicate URI {uri!r}"
            )
        status = raw.get("status")
        if status == "ok" and "schema" not in raw:
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}] has status 'ok' without schema"
            )
        if status == "error" and (
            not isinstance(raw.get("error_type"), str)
            or not isinstance(raw.get("message"), str)
        ):
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}] error row is incomplete"
            )
        if status not in {"ok", "error"}:
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}].status must be 'ok' or 'error'"
            )
        if "host_surface" in raw or "manifest_origin" in raw:
            raise AuthoringUiCommandsSupplementError(
                f"{label}[{index}] contains reserved origin fields"
            )
        row = deepcopy(dict(raw))
        _finite_json(row, f"{label}[{index}]")
        result.append(row)
        seen.add(uri)
    return sorted(result, key=lambda row: row["uri"])


def _validate_delta(supplement: AuthoringUiCommandsSupplement) -> None:
    function_uris = {row["uri"] for row in supplement.functions}
    topic_uris = {row["uri"] for row in supplement.topics}
    invalid_functions = function_uris - AUTHORING_UI_COMMAND_FUNCTION_URIS
    invalid_topics = topic_uris - AUTHORING_UI_COMMAND_TOPIC_URIS
    if invalid_functions or invalid_topics:
        raise AuthoringUiCommandsSupplementError(
            "Supplement contains rows outside its fixed scope"
        )
    added_uris = function_uris | topic_uris
    schema_uris = {row["uri"] for row in supplement.schemas}
    if schema_uris != added_uris:
        raise AuthoringUiCommandsSupplementError(
            "Supplement schemas must match added rows exactly"
        )
    override_uris = {row["uri"] for row in supplement.schema_overrides}
    if not override_uris <= AUTHORING_UI_COMMAND_URIS:
        raise AuthoringUiCommandsSupplementError(
            "Schema override is outside the fixed ui.commands scope"
        )
    if override_uris & added_uris:
        raise AuthoringUiCommandsSupplementError(
            "Schema override must refer to a common row, not an addition"
        )


def _require_version(
    manifest: Mapping[str, Any], version: str, label: str
) -> None:
    target = _metadata(manifest).get("wwise_version_target")
    if target is not None and target != version:
        raise AuthoringUiCommandsSupplementError(
            f"{label} targets Wwise {target!r}, expected {version!r}"
        )


def _metadata(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = manifest.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _list_field(payload: Mapping[str, Any], name: str) -> list[Any]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise AuthoringUiCommandsSupplementError(f"{name} must be an array")
    return value


def _by_uri(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["uri"]: row for row in rows}


def _uri(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _URI_RE.fullmatch(value):
        raise AuthoringUiCommandsSupplementError(
            f"{label} must be a valid WAAPI URI"
        )
    return value


def _finite_json(value: Any, label: str) -> None:
    try:
        canonical_sha256(value)
    except (TypeError, ValueError) as exc:
        raise AuthoringUiCommandsSupplementError(
            f"{label} must be finite JSON"
        ) from exc


def _mark(
    row: Mapping[str, Any], host_surface: str, origin: str
) -> dict[str, Any]:
    marked = deepcopy(dict(row))
    marked["host_surface"] = host_surface
    marked["manifest_origin"] = origin
    return marked


__all__ = [
    "AUTHORING_HOST_SURFACE",
    "AUTHORING_UI_COMMAND_FUNCTION_URIS",
    "AUTHORING_UI_COMMAND_TOPIC_URIS",
    "AUTHORING_UI_COMMAND_URIS",
    "AUTHORING_UI_COMMANDS_SUPPLEMENT_FILENAME",
    "AUTHORING_UI_COMMANDS_SUPPLEMENT_FORMAT",
    "AUTHORING_UI_COMMANDS_SURFACE_FORMAT",
    "CONSOLE_HOST_SURFACE",
    "AuthoringUiCommandsSupplement",
    "AuthoringUiCommandsSupplementAudit",
    "AuthoringUiCommandsSupplementError",
    "AuthoringUiCommandsSupplementMissingError",
    "build_authoring_ui_commands_supplement",
    "manifest_inventory_sha256",
    "merge_authoring_ui_commands_surface",
]

"""Deterministic filesystem policy for isolated WAAPI transactions.

The public execution contract decides whether an API belongs to the isolated
transaction lane.  This module adds the missing path boundary for that lane:
it discovers filesystem-looking fields in the actual versioned request,
rejects ambiguous relative/NUL paths, confines every declared write target to
one explicit root, and records read-only inputs without forcing them under the
write root. Wwise-managed implicit writes are reported separately: declaring a
root acknowledges that side effect, but cannot prove where Wwise will write.

This is deliberately a request auditor, not a filesystem mutator.  It never
creates directories, opens files, or invents paths on behalf of an agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .execution_contracts import (
    MANIFEST_ROOT,
    ExecutionContractError,
    ExecutionContractRegistry,
)
from .manifest import ManifestStore


IO_POLICY_CONTRACT = "waapi-skill.isolated-io-audit/v1"
MAX_IO_SCAN_DEPTH = 32
MAX_IO_SCAN_NODES = 10_000
MAX_IO_PATHS = 1_024
MAX_IO_PATH_BYTES = 4_096


# These names describe operating-system paths in the reflected isolated APIs.
# Matching is case/separator insensitive.  Wwise object identities such as
# objectPath and importLocation are explicitly excluded below.
_EXACT_PATH_FIELDS = frozenset(
    {
        "audiofile",
        "cache",
        "directory",
        "file",
        "files",
        "folder",
        "headerfilepath",
        "importdefinitionfile",
        "importfile",
        "input",
        "licensefile",
        "newfiles",
        "output",
        "path",
        "project",
        "rootoutputpath",
        "soundbankpath",
        "sourcebyplatform",
        "sourcefile",
        "tabdelimitedimportfile",
    }
)
_NON_FILESYSTEM_FIELDS = frozenset(
    {
        "audiofilebase64",
        "dialogueevent",
        "event",
        # CLI switch asking Wwise to generate Wwise_IDs.h; the value itself is
        # a boolean, while explicit destinations use header-file-path.
        "headerfile",
        "importlocation",
        "objectpath",
        # A Wwise-managed relative segment below Originals, not an absolute
        # operating-system path supplied to WAAPI.
        "originalssubfolder",
    }
)
_PATH_SUFFIXES = ("directory", "file", "files", "folder", "path", "project")
_PLATFORM_MAPPING_FIELDS = frozenset(
    {"output", "soundbankpath", "sourcebyplatform"}
)
_PLATFORM_METADATA_FIELDS = frozenset(
    {"language", "name", "platform", "platformid"}
)

# A few reflected fields use filesystem vocabulary for values that are not
# operating-system paths, or accept a path only as one branch of a union. Keep
# those exceptions URI-scoped so a newly reflected field with the same name
# still fails conservatively into the normal path policy.
_URI_LOGICAL_PATH_FIELDS = frozenset(
    {
        (
            "ak.wwise.core.sourceControl.getSourceFiles",
            "folder",
        ),
    }
)
_URI_CONDITIONAL_READ_PATH_FIELDS = frozenset(
    {
        (
            "ak.wwise.cli.generateSoundbank",
            "bank",
        ),
    }
)
_URI_RELATIVE_WRITE_PATH_ROOTS: Mapping[str, frozenset[str]] = {
    "ak.wwise.cli.generateSoundbank": frozenset(
        {
            "$.args.cache",
            "$.args.header-file-path",
            "$.args.root-output-path",
            "$.args.soundbank-path",
        }
    ),
}


_READ_PATH_FIELDS = frozenset(
    {
        "audiofile",
        "folder",
        "importdefinitionfile",
        "importfile",
        "input",
        "licensefile",
        "sourcebyplatform",
        "sourcefile",
        "tabdelimitedimportfile",
    }
)
_WRITE_PATH_FIELDS = frozenset(
    {
        "cache",
        "headerfilepath",
        "newfiles",
        "output",
        "rootoutputpath",
        "soundbankpath",
    }
)


_PROJECT_WRITE_URIS = frozenset(
    {
        "ak.wwise.cli.addNewPlatform",
        "ak.wwise.cli.createNewProject",
        "ak.wwise.cli.migrate",
        "ak.wwise.cli.moveMediaIdsToSingleFile",
        "ak.wwise.cli.moveMediaIdsToWorkUnits",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.updateMediaIdsInSingleFile",
    }
)
_SOURCE_CONTROL_WRITE_URIS = frozenset(
    {
        "ak.wwise.core.sourceControl.add",
        "ak.wwise.core.sourceControl.checkOut",
        "ak.wwise.core.sourceControl.commit",
        "ak.wwise.core.sourceControl.delete",
        "ak.wwise.core.sourceControl.move",
        "ak.wwise.core.sourceControl.revert",
    }
)
_IMPLICIT_WRITE_REASONS: Mapping[str, str] = {
    "ak.wwise.cli.convertExternalSource": (
        "External-source conversion writes generated media even when Wwise selects the default output directory."
    ),
    "ak.wwise.cli.generateSoundbank": (
        "The CLI SoundBank generator writes banks, media, cache, or project-level output artifacts."
    ),
    "ak.wwise.core.audio.convert": (
        "Audio conversion writes converted media into Wwise-managed cache/output locations."
    ),
    "ak.wwise.core.audio.import": (
        "Audio import writes Originals media and project/work-unit content outside the source input path."
    ),
    "ak.wwise.core.audio.importTabDelimited": (
        "Tab-delimited import writes imported media and project/work-unit content."
    ),
    "ak.wwise.core.soundbank.convertExternalSources": (
        "External-source conversion writes platform media, including when the output field is omitted."
    ),
    "ak.wwise.core.soundbank.processDefinitionFiles": (
        "Processing SoundBank definition files can materialize generated SoundBank output."
    ),
}


class IOPolicyError(ValueError):
    """A deterministic isolated-I/O request boundary."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": IO_POLICY_CONTRACT,
            "ok": False,
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class IOPathAudit:
    """One validated filesystem path found in args or options."""

    section: str
    json_path: str
    field: str
    role: str
    raw_path: str
    resolved_path: str
    within_io_root: bool | None
    manifest_declared: bool
    schema_ref: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "json_path": self.json_path,
            "field": self.field,
            "role": self.role,
            "raw_path": self.raw_path,
            "resolved_path": self.resolved_path,
            "within_io_root": self.within_io_root,
            "manifest_declared": self.manifest_declared,
            "schema_ref": self.schema_ref,
        }


@dataclass(frozen=True, slots=True)
class IsolatedIOAudit:
    """Successful structured audit for one isolated transaction request."""

    version: str
    uri: str
    route: str
    manifest_schema: str
    requires_io_root: bool
    io_root: str | None
    paths: tuple[IOPathAudit, ...]
    implicit_writes: tuple[str, ...] = ()

    @property
    def read_paths(self) -> tuple[IOPathAudit, ...]:
        return tuple(path for path in self.paths if path.role == "read")

    @property
    def write_paths(self) -> tuple[IOPathAudit, ...]:
        return tuple(path for path in self.paths if path.role == "write")

    @property
    def explicit_write_confinement_proven(self) -> bool | None:
        """Whether explicit write targets resolved inside ``io_root``, if any."""

        write_paths = self.write_paths
        if not write_paths:
            return None
        return all(path.within_io_root is True for path in write_paths)

    @property
    def implicit_write_confinement_proven(self) -> bool | None:
        """Return ``False`` for implicit writes whose location is not request-bound."""

        return False if self.implicit_writes else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": IO_POLICY_CONTRACT,
            "ok": True,
            "version": self.version,
            "uri": self.uri,
            "route": self.route,
            "manifest_schema": self.manifest_schema,
            "requires_io_root": self.requires_io_root,
            "io_root": self.io_root,
            "path_count": len(self.paths),
            "read_path_count": len(self.read_paths),
            "write_path_count": len(self.write_paths),
            "confinement_scope": "explicit_write_paths_only",
            "explicit_write_confinement_proven": self.explicit_write_confinement_proven,
            "implicit_write_confinement_proven": self.implicit_write_confinement_proven,
            "implicit_writes": list(self.implicit_writes),
            "paths": [path.as_dict() for path in self.paths],
        }


@dataclass(frozen=True, slots=True)
class _PathCandidate:
    section: str
    json_path: str
    field: str
    role: str
    value: str
    manifest_declared: bool
    schema_ref: str | None


@dataclass(slots=True)
class _PathScanner:
    uri: str
    args: Mapping[str, Any]
    nodes_seen: int = 0
    candidates: list[_PathCandidate] = field(default_factory=list)

    def scan(
        self,
        section: str,
        payload: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> None:
        self._walk_mapping(section, payload, schema, (section,), depth=0)

    def _walk_mapping(
        self,
        section: str,
        payload: Mapping[str, Any],
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        *,
        depth: int,
    ) -> None:
        self._consume_node(depth, path)
        properties = schema.get("properties")
        schema_properties = properties if isinstance(properties, Mapping) else {}
        for raw_key, value in payload.items():
            key = str(raw_key)
            child_schema_value = schema_properties.get(key)
            child_schema = child_schema_value if isinstance(child_schema_value, Mapping) else {}
            child_path = (*path, key)
            normalized = _normalize_field(key)
            if (self.uri, normalized) in _URI_LOGICAL_PATH_FIELDS:
                # ``sourceControl.getSourceFiles.folder`` is relative to the
                # Wwise Originals hierarchy. It is not an absolute OS path.
                self._walk_nested(
                    section,
                    value,
                    child_schema,
                    child_path,
                    depth=depth + 1,
                )
                continue
            if (self.uri, normalized) in _URI_CONDITIONAL_READ_PATH_FIELDS:
                self._collect_conditional_read_path_value(
                    section,
                    key,
                    value,
                    child_schema,
                    child_path,
                    depth=depth + 1,
                )
                continue
            if _is_filesystem_field(normalized):
                role = _path_role(self.uri, normalized, self.args)
                self._collect_field_value(
                    section,
                    key,
                    normalized,
                    role,
                    value,
                    child_schema,
                    child_path,
                    depth=depth + 1,
                )
                continue
            self._walk_nested(section, value, child_schema, child_path, depth=depth + 1)

    def _walk_nested(
        self,
        section: str,
        value: Any,
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        *,
        depth: int,
    ) -> None:
        if isinstance(value, Mapping):
            self._walk_mapping(section, value, schema, path, depth=depth)
            return
        if isinstance(value, list):
            self._consume_node(depth, path)
            item_schema_value = schema.get("items")
            item_schema = item_schema_value if isinstance(item_schema_value, Mapping) else {}
            for index, item in enumerate(value):
                self._walk_nested(section, item, item_schema, (*path, index), depth=depth + 1)

    def _collect_field_value(
        self,
        section: str,
        field_name: str,
        normalized_field: str,
        role: str,
        value: Any,
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        *,
        depth: int,
    ) -> None:
        self._consume_node(depth, path)
        if isinstance(value, str):
            self._append_candidate(section, field_name, role, value, schema, path)
            return
        if normalized_field in _PLATFORM_MAPPING_FIELDS:
            self._collect_platform_mapping(
                section,
                field_name,
                role,
                value,
                schema,
                path,
                depth=depth,
            )
            return
        if isinstance(value, list):
            item_schema_value = schema.get("items")
            item_schema = item_schema_value if isinstance(item_schema_value, Mapping) else {}
            declared_item_schema = item_schema or schema
            for index, item in enumerate(value):
                self._collect_field_value(
                    section,
                    field_name,
                    normalized_field,
                    role,
                    item,
                    declared_item_schema,
                    (*path, index),
                    depth=depth + 1,
                )
            return
        if isinstance(value, Mapping):
            properties = schema.get("properties")
            schema_properties = properties if isinstance(properties, Mapping) else {}
            for raw_key, item in value.items():
                key = str(raw_key)
                child_schema_value = schema_properties.get(key)
                child_schema = child_schema_value if isinstance(child_schema_value, Mapping) else {}
                child_normalized = _normalize_field(key)
                if child_normalized in _PLATFORM_METADATA_FIELDS:
                    continue
                child_role = (
                    _path_role(self.uri, child_normalized, self.args)
                    if _is_filesystem_field(child_normalized)
                    else role
                )
                self._collect_field_value(
                    section,
                    key,
                    child_normalized,
                    child_role,
                    item,
                    child_schema,
                    (*path, key),
                    depth=depth + 1,
                )
            return
        raise IOPolicyError(
            "INVALID_IO_PATH_VALUE",
            f"Filesystem field {_json_path(path)} must contain a string or a bounded collection of strings.",
            details={"json_path": _json_path(path), "actual_type": type(value).__name__},
        )

    def _collect_conditional_read_path_value(
        self,
        section: str,
        field_name: str,
        value: Any,
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        *,
        depth: int,
    ) -> None:
        """Audit only the file-selector branch of a name-or-file field."""

        self._consume_node(depth, path)
        if isinstance(value, str):
            if _looks_like_file_selector(value):
                self._append_candidate(
                    section,
                    field_name,
                    "read",
                    value,
                    schema,
                    path,
                )
            return
        if isinstance(value, list):
            item_schema_value = schema.get("items")
            item_schema = item_schema_value if isinstance(item_schema_value, Mapping) else {}
            declared_item_schema = item_schema or schema
            for index, item in enumerate(value):
                self._collect_conditional_read_path_value(
                    section,
                    field_name,
                    item,
                    declared_item_schema,
                    (*path, index),
                    depth=depth + 1,
                )
            return
        raise IOPolicyError(
            "INVALID_IO_PATH_VALUE",
            f"Conditional filesystem field {_json_path(path)} must contain a string or an array of strings.",
            details={"json_path": _json_path(path), "actual_type": type(value).__name__},
        )

    def _collect_platform_mapping(
        self,
        section: str,
        field_name: str,
        role: str,
        value: Any,
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        *,
        depth: int,
    ) -> None:
        if isinstance(value, str):
            self._append_candidate(section, field_name, role, value, schema, path)
            return
        if isinstance(value, Mapping):
            for raw_key, item in value.items():
                key = str(raw_key)
                normalized = _normalize_field(key)
                if normalized in _PLATFORM_METADATA_FIELDS:
                    continue
                self._collect_field_value(
                    section,
                    key,
                    normalized,
                    role,
                    item,
                    schema,
                    (*path, key),
                    depth=depth + 1,
                )
            return
        if isinstance(value, list):
            if all(isinstance(item, Mapping) for item in value):
                for index, item in enumerate(value):
                    self._collect_platform_mapping(
                        section,
                        field_name,
                        role,
                        item,
                        schema,
                        (*path, index),
                        depth=depth + 1,
                    )
                return
            if all(isinstance(item, list) for item in value):
                if any(
                    len(item) != 2
                    or not isinstance(item[0], str)
                    or not isinstance(item[1], str)
                    for item in value
                ):
                    raise IOPolicyError(
                        "AMBIGUOUS_PLATFORM_PATH_MAPPING",
                        f"Filesystem field {_json_path(path)} must be a path string, a platform-to-path object, "
                        "an even PLATFORM/PATH string array, or an array of [PLATFORM, PATH] pairs.",
                        details={"json_path": _json_path(path)},
                    )
                for index, item in enumerate(value):
                    self._append_candidate(
                        section,
                        field_name,
                        role,
                        item[1],
                        schema,
                        (*path, index, 1),
                    )
                return
            if not all(isinstance(item, str) for item in value) or len(value) % 2:
                raise IOPolicyError(
                    "AMBIGUOUS_PLATFORM_PATH_MAPPING",
                    f"Filesystem field {_json_path(path)} must be a path string, a platform-to-path object, "
                    "an even PLATFORM/PATH string array, or an array of [PLATFORM, PATH] pairs.",
                    details={"json_path": _json_path(path)},
                )
            for index in range(1, len(value), 2):
                self._append_candidate(
                    section,
                    field_name,
                    role,
                    value[index],
                    schema,
                    (*path, index),
                )
            return
        raise IOPolicyError(
            "INVALID_IO_PATH_VALUE",
            f"Filesystem field {_json_path(path)} has an unsupported platform/path value.",
            details={"json_path": _json_path(path), "actual_type": type(value).__name__},
        )

    def _append_candidate(
        self,
        section: str,
        field_name: str,
        role: str,
        value: str,
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
    ) -> None:
        if len(self.candidates) >= MAX_IO_PATHS:
            raise IOPolicyError(
                "IO_PATH_LIMIT_EXCEEDED",
                f"Isolated request contains more than {MAX_IO_PATHS} filesystem paths.",
                details={"limit": MAX_IO_PATHS},
            )
        schema_ref = schema.get("$ref")
        self.candidates.append(
            _PathCandidate(
                section=section,
                json_path=_json_path(path),
                field=field_name,
                role=role,
                value=value,
                manifest_declared=bool(schema),
                schema_ref=schema_ref if isinstance(schema_ref, str) else None,
            )
        )

    def _consume_node(self, depth: int, path: tuple[str | int, ...]) -> None:
        if depth > MAX_IO_SCAN_DEPTH:
            raise IOPolicyError(
                "IO_SCAN_DEPTH_EXCEEDED",
                f"Isolated request exceeds the I/O scan depth at {_json_path(path)}.",
                details={"limit": MAX_IO_SCAN_DEPTH, "json_path": _json_path(path)},
            )
        self.nodes_seen += 1
        if self.nodes_seen > MAX_IO_SCAN_NODES:
            raise IOPolicyError(
                "IO_SCAN_NODE_LIMIT_EXCEEDED",
                "Isolated request exceeds the I/O scan node limit.",
                details={"limit": MAX_IO_SCAN_NODES},
            )


def validate_isolated_io(
    *,
    version: str,
    uri: str,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    io_root: str | Path | None = None,
    contract_registry: ExecutionContractRegistry | None = None,
    manifest_store: ManifestStore | None = None,
) -> IsolatedIOAudit:
    """Validate and audit filesystem paths for one isolated transaction.

    Read-only input files may live outside ``io_root`` but must be absolute and
    appear in the returned audit.  Every explicit write path must resolve under
    ``io_root``.  APIs with implicit filesystem writes also require an explicit
    root even when their WAAPI schema has no output-path argument. For those
    implicit writes, the root is an authorization/audit declaration only;
    physical confinement is proven only for explicit paths in ``write_paths``.
    """

    registry = contract_registry or ExecutionContractRegistry()
    try:
        execution_contract = registry.describe(version, uri)
    except ExecutionContractError as exc:
        raise IOPolicyError(
            "EXECUTION_CONTRACT_ERROR",
            f"Could not resolve the public execution contract for {uri!r} in Wwise {version}.",
            details={"version": version, "uri": uri, "reason": str(exc)},
        ) from exc
    if execution_contract.item_type != "function" or execution_contract.route != "isolated_transaction":
        raise IOPolicyError(
            "NOT_ISOLATED_TRANSACTION",
            f"WAAPI URI {uri!r} is routed as {execution_contract.route!r}, not isolated_transaction.",
            details={
                "version": version,
                "uri": uri,
                "item_type": execution_contract.item_type,
                "route": execution_contract.route,
            },
        )

    request_args = _require_mapping(args, "args")
    request_options = _require_mapping(options, "options")
    store = manifest_store or registry.manifest_store
    if store.root is None and not store.versions:
        store = ManifestStore(root=MANIFEST_ROOT)
    schema = _load_reflected_schema(store, version, uri)
    args_schema_value = schema.get("argsSchema")
    options_schema_value = schema.get("optionsSchema")
    args_schema = args_schema_value if isinstance(args_schema_value, Mapping) else {}
    options_schema = options_schema_value if isinstance(options_schema_value, Mapping) else {}

    scanner = _PathScanner(uri=uri, args=request_args)
    scanner.scan("args", request_args, args_schema)
    scanner.scan("options", request_options, options_schema)

    # Lexical validation is independent of root declaration and therefore
    # happens first. A missing root must not hide malformed path text. Relative
    # reads and non-allowlisted writes also fail before root resolution. The
    # four generateSoundbank fields documented as relative-capable are resolved
    # only after io_root itself has been validated and canonicalized.
    parsed_candidates = tuple(
        (candidate, _validated_path(candidate.value, json_path=candidate.json_path))
        for candidate in scanner.candidates
    )
    for candidate, path in parsed_candidates:
        if not path.is_absolute() and not _allows_relative_write(uri, candidate):
            raise IOPolicyError(
                "RELATIVE_IO_PATH",
                f"Filesystem path {candidate.json_path} must be absolute; relative paths are not accepted.",
                details={"json_path": candidate.json_path},
            )
    implicit_writes = _implicit_write_reasons(uri, request_args)
    requires_io_root = bool(implicit_writes) or any(
        candidate.role == "write" for candidate, _ in parsed_candidates
    )
    resolved_root = _resolve_io_root(io_root, required=requires_io_root)
    resolved_candidates = tuple(
        (
            candidate,
            _resolve_candidate_path(
                candidate,
                path,
                uri=uri,
                io_root=resolved_root,
            ),
        )
        for candidate, path in parsed_candidates
    )

    audits: list[IOPathAudit] = []
    for candidate, resolved in resolved_candidates:
        within_root = _is_within(resolved, resolved_root) if resolved_root is not None else None
        if candidate.role == "write" and within_root is not True:
            raise IOPolicyError(
                "IO_PATH_OUTSIDE_ROOT",
                f"Write path {candidate.json_path} resolves outside the declared I/O root.",
                details={
                    "json_path": candidate.json_path,
                    "resolved_path": str(resolved),
                    "io_root": str(resolved_root) if resolved_root is not None else None,
                },
            )
        audits.append(
            IOPathAudit(
                section=candidate.section,
                json_path=candidate.json_path,
                field=candidate.field,
                role=candidate.role,
                raw_path=candidate.value,
                resolved_path=str(resolved),
                within_io_root=within_root,
                manifest_declared=candidate.manifest_declared,
                schema_ref=candidate.schema_ref,
            )
        )

    return IsolatedIOAudit(
        version=version,
        uri=uri,
        route=execution_contract.route,
        manifest_schema=f"resources/manifest/{version}/schemas.json#{uri}",
        requires_io_root=requires_io_root,
        io_root=str(resolved_root) if resolved_root is not None else None,
        paths=tuple(audits),
        implicit_writes=implicit_writes,
    )


def _require_mapping(value: Mapping[str, Any] | None, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise IOPolicyError(
            "INVALID_IO_REQUEST",
            f"{label} must be a JSON object for isolated I/O validation.",
            details={"section": label, "actual_type": type(value).__name__},
        )
    return value


def _load_reflected_schema(
    manifest_store: ManifestStore,
    version: str,
    uri: str,
) -> Mapping[str, Any]:
    try:
        manifest = manifest_store.load(version)
    except Exception as exc:  # noqa: BLE001 - normalized to a stable policy boundary
        raise IOPolicyError(
            "MANIFEST_SCHEMA_UNAVAILABLE",
            f"Could not load the Wwise {version} manifest for isolated I/O validation.",
            details={"version": version, "uri": uri, "reason": str(exc)},
        ) from exc
    schemas = manifest.get("schemas")
    if not isinstance(schemas, list):
        raise IOPolicyError(
            "MANIFEST_SCHEMA_UNAVAILABLE",
            f"Wwise {version} has no packaged schema inventory.",
            details={"version": version, "uri": uri},
        )
    matches = [
        entry
        for entry in schemas
        if isinstance(entry, Mapping) and entry.get("uri") == uri
    ]
    if len(matches) != 1 or matches[0].get("status") != "ok":
        raise IOPolicyError(
            "MANIFEST_SCHEMA_UNAVAILABLE",
            f"WAAPI URI {uri!r} lacks one successful packaged schema in Wwise {version}.",
            details={"version": version, "uri": uri, "matches": len(matches)},
        )
    schema = matches[0].get("schema")
    if not isinstance(schema, Mapping):
        raise IOPolicyError(
            "MANIFEST_SCHEMA_UNAVAILABLE",
            f"WAAPI URI {uri!r} has a malformed packaged schema in Wwise {version}.",
            details={"version": version, "uri": uri},
        )
    return schema


def _resolve_io_root(value: str | Path | None, *, required: bool) -> Path | None:
    if value is None:
        if required:
            raise IOPolicyError(
                "IO_ROOT_REQUIRED",
                "This isolated transaction can write files and requires an explicit absolute io_root declaration.",
                details={
                    "required": True,
                    "confinement_scope": "explicit_write_paths_only",
                },
            )
        return None
    resolved = _resolve_absolute_path(str(value), json_path="io_root")
    anchor = Path(resolved.anchor)
    if resolved == anchor:
        raise IOPolicyError(
            "IO_ROOT_TOO_BROAD",
            "io_root cannot be the filesystem root because that would provide no write confinement.",
            details={"io_root": str(resolved)},
        )
    return resolved


def _resolve_absolute_path(value: str, *, json_path: str) -> Path:
    path = _validated_path(value, json_path=json_path)
    if not path.is_absolute():
        raise IOPolicyError(
            "RELATIVE_IO_PATH",
            f"Filesystem path {json_path} must be absolute; relative paths are not accepted.",
            details={"json_path": json_path},
        )
    return _resolve_path(path, json_path=json_path)


def _validated_path(value: str, *, json_path: str) -> Path:
    if "\x00" in value:
        raise IOPolicyError(
            "NUL_IN_IO_PATH",
            f"Filesystem path {json_path} contains a NUL byte.",
            details={"json_path": json_path},
        )
    try:
        byte_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise IOPolicyError(
            "INVALID_IO_PATH_ENCODING",
            f"Filesystem path {json_path} is not valid UTF-8 text.",
            details={"json_path": json_path},
        ) from exc
    if not value or byte_length > MAX_IO_PATH_BYTES:
        raise IOPolicyError(
            "INVALID_IO_PATH_LENGTH",
            f"Filesystem path {json_path} must contain 1..{MAX_IO_PATH_BYTES} UTF-8 bytes.",
            details={"json_path": json_path, "limit_bytes": MAX_IO_PATH_BYTES},
        )
    return Path(value)


def _resolve_path(path: Path, *, json_path: str) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise IOPolicyError(
            "IO_PATH_RESOLUTION_FAILED",
            f"Filesystem path {json_path} could not be resolved safely.",
            details={"json_path": json_path, "reason": str(exc)},
        ) from exc


def _resolve_candidate_path(
    candidate: _PathCandidate,
    path: Path,
    *,
    uri: str,
    io_root: Path | None,
) -> Path:
    if path.is_absolute():
        return _resolve_path(path, json_path=candidate.json_path)
    if not _allows_relative_write(uri, candidate):
        # The caller checks this before resolving io_root. Keep the boundary
        # fail-closed if this helper is reused independently later.
        raise IOPolicyError(
            "RELATIVE_IO_PATH",
            f"Filesystem path {candidate.json_path} must be absolute; relative paths are not accepted.",
            details={"json_path": candidate.json_path},
        )
    if io_root is None:
        raise IOPolicyError(
            "IO_ROOT_REQUIRED",
            "A relative write path requires an explicit absolute io_root declaration.",
            details={
                "required": True,
                "json_path": candidate.json_path,
                "confinement_scope": "explicit_write_paths_only",
            },
        )
    return _resolve_path(io_root / path, json_path=candidate.json_path)


def _allows_relative_write(uri: str, candidate: _PathCandidate) -> bool:
    if candidate.role != "write" or not candidate.manifest_declared:
        return False
    roots = _URI_RELATIVE_WRITE_PATH_ROOTS.get(uri, ())
    return any(
        candidate.json_path == root
        or candidate.json_path.startswith(f"{root}[")
        or candidate.json_path.startswith(f"{root}.")
        for root in roots
    )


def _implicit_write_reasons(uri: str, args: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    static = _IMPLICIT_WRITE_REASONS.get(uri)
    if static is not None:
        reasons.append(static)
    if uri == "ak.wwise.core.soundbank.generate" and (
        args.get("writeToDisk") is True or args.get("clearAudioFileCache") is True
    ):
        reasons.append(
            "SoundBank generation was asked to write to disk or clear the converted-media cache."
        )
    return tuple(reasons)


def _path_role(uri: str, normalized_field: str, args: Mapping[str, Any]) -> str:
    if normalized_field in _READ_PATH_FIELDS:
        return "read"
    if normalized_field in _WRITE_PATH_FIELDS:
        return "write"
    if normalized_field == "project":
        if uri in _PROJECT_WRITE_URIS:
            return "write"
        # The reflected CLI contract explicitly says imported definition/tab
        # content does not persist unless --save is present. The project is a
        # read input in that case; generated artifacts remain disclosed by the
        # API's separate implicit-write record.
        if uri == "ak.wwise.cli.generateSoundbank" and args.get("save") is True:
            return "write"
        if uri == "ak.wwise.cli.waapiServer" and args.get("allow-migration") is True:
            return "write"
        return "read"
    if normalized_field in {"files", "newfiles"}:
        return "write" if uri in _SOURCE_CONTROL_WRITE_URIS else "read"
    if normalized_field == "path":
        if uri in {
            "ak.wwise.console.project.create",
            "ak.wwise.console.project.open",
            "ak.wwise.debug.generateToneWAV",
            "ak.wwise.ui.project.create",
            "ak.wwise.ui.project.open",
        }:
            return "write"
        return "read"
    if normalized_field == "file":
        return "write" if uri == "ak.wwise.core.profiler.saveCapture" else "read"
    # A newly reflected path-like field fails conservatively into the write
    # class. This prevents an inventory update from silently gaining an
    # unconfined output while still preserving an audit row for review.
    return "write"


def _is_filesystem_field(normalized_field: str) -> bool:
    if normalized_field in _NON_FILESYSTEM_FIELDS:
        return False
    if normalized_field in _EXACT_PATH_FIELDS:
        return True
    return any(normalized_field.endswith(suffix) for suffix in _PATH_SUFFIXES)


def _normalize_field(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _looks_like_file_selector(value: str) -> bool:
    """Recognize the file branch of generateSoundbank's bank selector.

    The manifest permits either a SoundBank name or the full path to a ``.txt``
    file. Path separators are also treated as path intent so malformed or
    relative file selectors fail at the normal absolute-path boundary instead
    of silently becoming unaudited names.
    """

    return value.casefold().endswith(".txt") or "/" in value or "\\" in value


def _is_within(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _json_path(parts: tuple[str | int, ...]) -> str:
    result = "$"
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


__all__ = [
    "IO_POLICY_CONTRACT",
    "IOPathAudit",
    "IOPolicyError",
    "IsolatedIOAudit",
    "MAX_IO_PATH_BYTES",
    "MAX_IO_PATHS",
    "MAX_IO_SCAN_DEPTH",
    "MAX_IO_SCAN_NODES",
    "validate_isolated_io",
]

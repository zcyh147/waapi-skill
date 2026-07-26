"""Schema-aware semantic validation helpers for reflected WAAPI resources."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION

from .common import BuilderFamily, ManifestSchemaLoader, SemanticErrorCode, SemanticValidationError
from .source_notes import DEFAULT_SEMANTIC_SOURCE_NOTES, DEFAULT_SEMANTIC_SOURCE_ROOT, load_semantic_source_notes


SEMANTIC_CONSTRAINT_FACTS_SIZE_LIMIT = 4096
SCHEMA_VALIDATION_MAX_DEPTH = 32
SCHEMA_VALIDATION_MAX_NODES = 8192


@dataclass(slots=True, frozen=True)
class SchemaValidationResult:
    """Successful conservative validation evidence for one semantic payload."""

    uri: str
    version: str = DEFAULT_WWISE_VERSION
    required_fields: tuple[str, ...] = ()
    required_families: tuple[tuple[str, ...], ...] = ()
    section: str = "request"
    validated_nodes: int = 0
    unresolved_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "version": self.version,
            "required_fields": list(self.required_fields),
            "required_families": [list(family) for family in self.required_families],
            "section": self.section,
            "validated_nodes": self.validated_nodes,
            "unresolved_refs": list(self.unresolved_refs),
        }


@dataclass(slots=True, frozen=True)
class SemanticConstraintFacts:
    """Compact task-scoped WAAPI facts for one URI/family pair."""

    uri: str
    family: str
    version: str = DEFAULT_WWISE_VERSION
    required_args: tuple[str, ...] = ()
    required_arg_families: tuple[tuple[str, ...], ...] = ()
    supported_args: tuple[str, ...] = ()
    supported_options: tuple[str, ...] = ()
    identity_shape: tuple[str, ...] = ()
    property_hints: tuple[str, ...] = ()
    result_shape: str = ""
    result_fields: tuple[str, ...] = ()
    mutation_hints: tuple[str, ...] = ()
    source_priority: tuple[str, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    size_ceiling: int = SEMANTIC_CONSTRAINT_FACTS_SIZE_LIMIT

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uri": self.uri,
            "family": self.family,
            "version": self.version,
            "required_args": list(self.required_args),
            "required_arg_families": [list(family) for family in self.required_arg_families],
            "supported_args": list(self.supported_args),
            "supported_options": list(self.supported_options),
            "identity_shape": list(self.identity_shape),
            "property_hints": list(self.property_hints),
            "result_shape": self.result_shape,
            "result_fields": list(self.result_fields),
            "mutation_hints": list(self.mutation_hints),
            "source_priority": list(self.source_priority),
            "provenance": [dict(item) for item in self.provenance],
            "size_ceiling": self.size_ceiling,
        }
        _ensure_constraint_facts_size(payload, self.uri, self.version, self.size_ceiling)
        return payload


@dataclass(slots=True, frozen=True)
class SemanticSchemaValidator:
    """Validate builder payloads against manifest-backed schemas without dispatching."""

    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)
    version: str = DEFAULT_WWISE_VERSION
    authoring_ui_profile: bool = False

    def require_supported_version(self) -> None:
        if self.authoring_ui_profile:
            self.manifest_loader.load_authoring_ui_manifest(self.version)
        else:
            self.manifest_loader.load_manifest(self.version)

    def schema_for(self, uri: str) -> Mapping[str, Any]:
        self.require_supported_version()
        if self.authoring_ui_profile:
            return self.manifest_loader.authoring_ui_schema_for(
                uri,
                self.version,
            )
        return self.manifest_loader.schema_for(uri, self.version)

    def validate(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> SchemaValidationResult:
        schema = self.schema_for(uri)
        arg_payload = dict(args or {})
        option_payload = dict(options or {})
        args_schema = _mapping_or_empty(schema.get("argsSchema"))
        options_schema = _mapping_or_empty(schema.get("optionsSchema"))

        required_fields = _required_fields(args_schema)
        missing = tuple(field for field in required_fields if field not in arg_payload)
        if missing:
            raise _schema_error(uri, self.version, f"WAAPI URI {uri!r} is missing required args: {', '.join(missing)}", missing_args=missing)

        required_families = _required_families(args_schema)

        _reject_unknown_fields(uri, self.version, "args", args_schema, arg_payload)
        _reject_unknown_fields(uri, self.version, "options", options_schema, option_payload)
        _validate_known_types(uri, self.version, "args", args_schema, arg_payload)
        _validate_known_types(uri, self.version, "options", options_schema, option_payload)

        walker = _SchemaWalker(uri=uri, version=self.version)
        walker.validate(args_schema, arg_payload, path="args")
        walker.validate(options_schema, option_payload, path="options")

        return SchemaValidationResult(
            uri=uri,
            version=self.version,
            required_fields=required_fields,
            required_families=required_families,
            section="request",
            validated_nodes=walker.nodes,
            unresolved_refs=tuple(sorted(walker.unresolved_refs)),
        )

    def validate_result(self, uri: str, result: Any) -> SchemaValidationResult:
        """Validate one returned payload against the reflected result schema."""

        schema = self.schema_for(uri)
        result_schema = _mapping_or_empty(schema.get("resultSchema"))
        walker = _SchemaWalker(uri=uri, version=self.version)
        walker.validate(result_schema, result, path="result")
        return SchemaValidationResult(
            uri=uri,
            version=self.version,
            required_fields=_required_fields(result_schema),
            required_families=_required_families(result_schema),
            section="result",
            validated_nodes=walker.nodes,
            unresolved_refs=tuple(sorted(walker.unresolved_refs)),
        )

    def validate_event(self, uri: str, event: Any) -> SchemaValidationResult:
        """Validate one topic payload against the reflected publish schema."""

        schema = self.schema_for(uri)
        publish_schema = _mapping_or_empty(schema.get("publishSchema"))
        walker = _SchemaWalker(uri=uri, version=self.version)
        walker.validate(publish_schema, event, path="event")
        return SchemaValidationResult(
            uri=uri,
            version=self.version,
            required_fields=_required_fields(publish_schema),
            required_families=_required_families(publish_schema),
            section="event",
            validated_nodes=walker.nodes,
            unresolved_refs=tuple(sorted(walker.unresolved_refs)),
        )


def validate_semantic_payload(
    uri: str,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
    authoring_ui_profile: bool = False,
) -> SchemaValidationResult:
    """Validate one semantic payload using existing manifest/resource conventions."""

    validator = SemanticSchemaValidator(
        manifest_loader=manifest_loader or ManifestSchemaLoader(),
        version=version,
        authoring_ui_profile=authoring_ui_profile,
    )
    return validator.validate(uri, args=args, options=options)


def validate_semantic_result(
    uri: str,
    result: Any,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
    authoring_ui_profile: bool = False,
) -> SchemaValidationResult:
    """Validate one strict-JSON WAAPI result using the packaged manifest."""

    validator = SemanticSchemaValidator(
        manifest_loader=manifest_loader or ManifestSchemaLoader(),
        version=version,
        authoring_ui_profile=authoring_ui_profile,
    )
    return validator.validate_result(uri, result)


def validate_semantic_event(
    uri: str,
    event: Any,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
    authoring_ui_profile: bool = False,
) -> SchemaValidationResult:
    """Validate one topic event using the packaged reflected publish schema."""

    validator = SemanticSchemaValidator(
        manifest_loader=manifest_loader or ManifestSchemaLoader(),
        version=version,
        authoring_ui_profile=authoring_ui_profile,
    )
    return validator.validate_event(uri, event)


def extract_semantic_constraint_facts(
    uri: str,
    family: BuilderFamily | str,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
    source_note_path: Path | None = None,
    operator_allows_official_docs: bool = False,
) -> SemanticConstraintFacts:
    """Return bounded source-grounded facts for exactly one WAAPI URI."""

    family_value = _builder_family_value(family)
    note_path = source_note_path or _source_note_path_for_version(version)
    resource = load_semantic_source_notes(note_path, expected_version=version)
    if resource.version != version:
        raise SemanticValidationError(
            SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            f"Semantic source-note resource is for {resource.version}, expected {version}.",
            details={"version": version, "resource_version": resource.version},
        )
    note = resource.notes.get(family_value)
    if note is None:
        raise SemanticValidationError(
            SemanticErrorCode.MISSING_SOURCE_NOTE,
            f"Semantic source note is missing for builder family {family_value!r}.",
            details={"family": family_value, "version": version},
        )
    endpoints = _string_tuple(note.get("endpoints"))
    if uri not in endpoints:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"WAAPI URI {uri!r} is not in semantic source-note family {family_value!r}.",
            details={"uri": uri, "family": family_value, "version": version},
        )

    loader = manifest_loader or ManifestSchemaLoader()
    loader.load_manifest(version)
    schema = loader.schema_for(uri, version)
    args_schema = _mapping_or_empty(schema.get("argsSchema"))
    options_schema = _mapping_or_empty(schema.get("optionsSchema"))
    result_schema = _mapping_or_empty(schema.get("resultSchema"))

    supported_args = _property_names(args_schema)
    supported_options = _merge_unique(_note_options(note), _property_names(options_schema))
    required_args = _merge_unique(_required_fields(args_schema), _note_required_args_for_uri(note, uri))
    required_arg_families = _required_families(args_schema)
    identity_shape = _identity_shape(args_schema)
    property_hints = _property_hints(note, supported_options)
    result_fields = _property_names(result_schema)
    mutation_hints = _mutation_hints(note)
    provenance = _constraint_provenance(
        uri,
        family_value,
        version,
        note_path,
        note,
        operator_allows_official_docs=operator_allows_official_docs,
    )
    facts = SemanticConstraintFacts(
        uri=uri,
        family=family_value,
        version=version,
        required_args=required_args,
        required_arg_families=required_arg_families,
        supported_args=supported_args,
        supported_options=supported_options,
        identity_shape=identity_shape,
        property_hints=property_hints,
        result_shape=_compact_text(str(note.get("return_shape", ""))),
        result_fields=result_fields,
        mutation_hints=mutation_hints,
        source_priority=(
            "packaged-semantic-source-notes",
            "local-versioned-manifest",
            "targeted-uri-schema",
            "official-docs-explicit-only" if operator_allows_official_docs else "official-docs-excluded-by-policy",
        ),
        provenance=provenance,
    )
    facts.as_dict()
    return facts


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _builder_family_value(family: BuilderFamily | str) -> str:
    family_value = family.value if isinstance(family, BuilderFamily) else str(family)
    try:
        return BuilderFamily(family_value).value
    except ValueError as exc:
        raise SemanticValidationError(
            SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY,
            f"Unsupported semantic builder family: {family_value}",
            details={"family": family_value},
        ) from exc


def _source_note_path_for_version(version: str) -> Path:
    if version == DEFAULT_WWISE_VERSION:
        return DEFAULT_SEMANTIC_SOURCE_NOTES
    return DEFAULT_SEMANTIC_SOURCE_ROOT / version / "source_notes.json"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _merge_unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return tuple(merged)


def _property_names(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(str(name) for name in properties if isinstance(name, str))


def _note_required_args_for_uri(note: Mapping[str, Any], uri: str) -> tuple[str, ...]:
    prefix = f"{uri}:"
    required: list[str] = []
    for item in _string_tuple(note.get("required_fields")):
        if not item.startswith(prefix):
            continue
        value = item[len(prefix) :].strip()
        if value and value != "no required fields":
            required.append(value)
    return tuple(required)


def _note_options(note: Mapping[str, Any]) -> tuple[str, ...]:
    options: list[str] = []
    for item in _string_tuple(note.get("optional_fields")):
        if item.startswith("options."):
            options.append(item.removeprefix("options."))
        elif item in {"platform", "onNameConflict", "listMode", "autoAddToSourceControl", "importLocation"}:
            options.append(item)
    return tuple(options)


def _identity_shape(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    shapes: list[str] = []
    if "waql" in properties:
        shapes.append("waql")
    for key in ("object", "parent", "target", "source"):
        if key in properties:
            shapes.append(key)
    from_schema = properties.get("from")
    if isinstance(from_schema, Mapping):
        for branch in _schema_branches(from_schema):
            for required in _required_fields(branch):
                shapes.append(f"from.{required}")
    return _merge_unique(tuple(shapes))


def _schema_branches(schema: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    branches: list[Mapping[str, Any]] = []
    for key in ("oneOf", "anyOf"):
        entries = schema.get(key)
        if not isinstance(entries, list):
            continue
        branches.extend(_mapping_or_empty(entry) for entry in entries)
    return tuple(branches)


def _property_hints(note: Mapping[str, Any], supported_options: tuple[str, ...]) -> tuple[str, ...]:
    hints: list[str] = []
    if "return" in supported_options:
        hints.append("options.return selects returned object properties")
    for item in _string_tuple(note.get("optional_fields")):
        if "propert" in item.lower() or "reference" in item.lower():
            hints.append(_compact_text(item))
    return _merge_unique(tuple(hints))


def _mutation_hints(note: Mapping[str, Any]) -> tuple[str, ...]:
    destructive = _compact_text(str(note.get("destructive_behavior", "")))
    if not destructive:
        return ()
    lowered = destructive.lower()
    mode = "read-only" if "read-only" in lowered else "mutating" if "mutating" in lowered else "behavior"
    return (f"{mode}: {destructive}",)


def _constraint_provenance(
    uri: str,
    family: str,
    version: str,
    note_path: Path,
    note: Mapping[str, Any],
    *,
    operator_allows_official_docs: bool,
) -> tuple[Mapping[str, Any], ...]:
    provenance: list[Mapping[str, Any]] = [
        {
            "source": "packaged-semantic-source-notes",
            "family": family,
            "version": version,
            "path": _compact_resource_path(note_path),
            "fields": ["required_fields", "optional_fields", "return_shape", "destructive_behavior"],
        },
        {
            "source": "local-versioned-manifest",
            "version": version,
            "path": f"resources/manifest/{version}/manifest.json",
        },
        {
            "source": "targeted-uri-schema",
            "version": version,
            "uri": uri,
            "path": f"resources/manifest/{version}/schemas.json#{uri}",
            "facts": ["args", "options", "result"],
        },
    ]
    if operator_allows_official_docs:
        provenance.append(
            {
                "source": "official-docs",
                "status": "explicitly-allowed-by-operator-policy",
                "urls": list(_string_tuple(note.get("official_urls")))[:2],
            }
        )
    return tuple(provenance)


def _compact_resource_path(path: Path) -> str:
    parts = path.parts
    if "resources" in parts:
        index = parts.index("resources")
        return "/".join(parts[index:])
    return path.name


def _compact_text(value: str, limit: int = 320) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ensure_constraint_facts_size(payload: Mapping[str, Any], uri: str, version: str, size_ceiling: int) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > size_ceiling:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Semantic constraint facts for WAAPI URI {uri!r} exceeded the compact size ceiling.",
            details={"uri": uri, "version": version, "size": len(encoded), "size_ceiling": size_ceiling},
        )


def _required_fields(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = schema.get("required")
    if not isinstance(required, list):
        return ()
    return tuple(str(field) for field in required if isinstance(field, str))


def _required_families(schema: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    families: list[tuple[str, ...]] = []
    for key in ("oneOf", "anyOf"):
        entries = schema.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            family = _required_fields(_mapping_or_empty(entry))
            if family:
                families.append(family)
    return tuple(families)


def _reject_unknown_fields(uri: str, version: str, section: str, schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    if schema.get("additionalProperties") is not False:
        return
    properties = schema.get("properties")
    pattern_properties = schema.get("patternProperties")
    if not isinstance(properties, Mapping) and not isinstance(
        pattern_properties, Mapping
    ):
        # A top-level $ref is resolved by the schema walker below.  Preserve
        # that path instead of treating the unresolved wrapper as a closed,
        # empty object.
        return
    property_names = properties if isinstance(properties, Mapping) else {}
    raw_patterns = pattern_properties if isinstance(pattern_properties, Mapping) else {}
    compiled_patterns: list[re.Pattern[str]] = []
    for pattern in raw_patterns:
        if not isinstance(pattern, str):
            continue
        try:
            compiled_patterns.append(re.compile(pattern))
        except re.error as exc:
            raise _schema_error(
                uri,
                version,
                f"WAAPI URI {uri!r} contains an invalid packaged schema pattern.",
                section=section,
                pattern=pattern,
            ) from exc
    unknown = tuple(
        sorted(
            field
            for field in payload
            if field not in property_names
            and not any(pattern.search(field) is not None for pattern in compiled_patterns)
        )
    )
    if unknown:
        raise _schema_error(uri, version, f"WAAPI URI {uri!r} has unsupported {section} fields: {', '.join(unknown)}", unknown_fields=unknown, section=section)


def _validate_known_types(uri: str, version: str, section: str, schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    for field, value in payload.items():
        field_schema = properties.get(field)
        if not isinstance(field_schema, Mapping):
            continue
        expected = field_schema.get("type")
        if not isinstance(expected, str) or not _type_mismatch(expected, value):
            continue
        raise _schema_error(
            uri,
            version,
            f"WAAPI URI {uri!r} field {field!r} expected {expected}, got {type(value).__name__}.",
            section=section,
            field=field,
            expected_type=expected,
            actual_type=type(value).__name__,
        )


def _type_mismatch(expected: str, value: Any) -> bool:
    if expected == "object":
        return not isinstance(value, Mapping)
    if expected == "array":
        return not isinstance(value, list)
    if expected == "string":
        return not isinstance(value, str)
    if expected == "integer":
        return not isinstance(value, int) or isinstance(value, bool)
    if expected == "number":
        return not isinstance(value, (int, float)) or isinstance(value, bool)
    if expected == "boolean":
        return not isinstance(value, bool)
    return False


@dataclass(slots=True)
class _SchemaWalker:
    """Budgeted validator for the self-contained part of reflected schemas.

    Audiokinetic reflection commonly returns references to definition files
    that are not embedded in the URI response. Those references are reported as
    unresolved evidence instead of being invented. Every constraint present in
    the returned schema itself is still enforced recursively.
    """

    uri: str
    version: str
    nodes: int = 0
    unresolved_refs: set[str] = field(default_factory=set)

    def validate(self, schema: Mapping[str, Any], value: Any, *, path: str, depth: int = 0) -> None:
        self.nodes += 1
        if self.nodes > SCHEMA_VALIDATION_MAX_NODES:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} exceeded the schema-validation node budget.",
                section=path,
                maximum_nodes=SCHEMA_VALIDATION_MAX_NODES,
            )
        if depth > SCHEMA_VALIDATION_MAX_DEPTH:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} exceeded the schema-validation depth budget.",
                section=path,
                maximum_depth=SCHEMA_VALIDATION_MAX_DEPTH,
            )
        reference = schema.get("$ref")
        if isinstance(reference, str):
            self.unresolved_refs.add(reference)

        self._validate_type(schema, value, path)
        self._validate_const_enum(schema, value, path)
        if isinstance(value, Mapping):
            self._validate_object(schema, value, path, depth)
        elif isinstance(value, list):
            self._validate_array(schema, value, path, depth)
        elif isinstance(value, str):
            self._validate_string(schema, value, path)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self._validate_number(schema, value, path)

        all_of = schema.get("allOf")
        if isinstance(all_of, list):
            for index, branch in enumerate(all_of):
                if isinstance(branch, Mapping):
                    self.validate(branch, value, path=f"{path}.allOf[{index}]", depth=depth + 1)

        self._validate_alternatives(schema, value, path, depth)

    def _validate_alternatives(
        self,
        schema: Mapping[str, Any],
        value: Any,
        path: str,
        depth: int,
    ) -> None:
        """Evaluate reflected ``oneOf``/``anyOf`` branches conservatively.

        A successful branch containing an unresolved ``$ref`` is a possible
        match, not a proven match: the referenced definition could still reject
        the value.  Such branches keep the validation result partial without
        inventing constraints that are absent from the packaged reflection.  A
        branch with only locally available constraints is a definite match.

        Every attempted branch consumes the shared node/depth budget.  Failed
        speculative branches roll back only their unresolved-reference evidence;
        they never roll back budget consumption.
        """

        for keyword, required_policy in (("oneOf", "exactly one"), ("anyOf", "at least one")):
            raw_branches = schema.get(keyword)
            if not isinstance(raw_branches, list):
                continue

            required_alternatives = [
                list(_required_fields(branch))
                for branch in raw_branches
                if isinstance(branch, Mapping) and _required_fields(branch)
            ]
            definite_matches: list[int] = []
            possible_matches: list[int] = []
            failed_branches: list[dict[str, Any]] = []
            for index, branch in enumerate(raw_branches):
                if not isinstance(branch, Mapping):
                    failed_branches.append(
                        {
                            "index": index,
                            "error_code": "INVALID_PACKAGED_SCHEMA_BRANCH",
                        }
                    )
                    continue

                refs_before = set(self.unresolved_refs)
                # Validate each branch against branch-local reference evidence.
                # Otherwise two branches that mention the same unresolved ref
                # would incorrectly classify the later branch as a definite
                # match merely because the first branch already recorded it.
                self.unresolved_refs = set()
                try:
                    self.validate(
                        branch,
                        value,
                        path=f"{path}.{keyword}[{index}]",
                        depth=depth + 1,
                    )
                except SemanticValidationError as exc:
                    if _schema_budget_error(exc):
                        self.unresolved_refs |= refs_before
                        raise
                    self.unresolved_refs = refs_before
                    failed_branches.append(
                        {
                            "index": index,
                            "error_code": exc.error_code.value,
                            "message": _compact_text(exc.message),
                        }
                    )
                    continue

                branch_refs = set(self.unresolved_refs)
                self.unresolved_refs = refs_before | branch_refs
                if branch_refs:
                    possible_matches.append(index)
                else:
                    definite_matches.append(index)

            has_possible_match = bool(definite_matches or possible_matches)
            invalid = (
                not has_possible_match
                if keyword == "anyOf"
                else not has_possible_match or len(definite_matches) > 1
            )
            if not invalid:
                continue

            matched_indexes = definite_matches + possible_matches
            matched_alternatives = [
                list(_required_fields(raw_branches[index]))
                for index in matched_indexes
                if isinstance(raw_branches[index], Mapping) and _required_fields(raw_branches[index])
            ]

            raise _schema_error(
                self.uri,
                self.version,
                (
                    f"WAAPI URI {self.uri!r} field {path!r} must satisfy "
                    f"{required_policy} {keyword} branch."
                ),
                section=path,
                branch_keyword=keyword,
                required_policy=required_policy,
                required_alternatives=required_alternatives,
                matched_alternatives=matched_alternatives,
                branch_count=len(raw_branches),
                matched_branch_indexes=definite_matches,
                unresolved_branch_indexes=possible_matches,
                failed_branches=failed_branches,
            )

    def _validate_type(self, schema: Mapping[str, Any], value: Any, path: str) -> None:
        expected = schema.get("type")
        if isinstance(expected, str):
            allowed = (expected,)
        elif isinstance(expected, list) and all(isinstance(item, str) for item in expected):
            allowed = tuple(expected)
        else:
            return
        if not any(_matches_json_type(kind, value) for kind in allowed):
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} expected {', '.join(allowed)}, got {type(value).__name__}.",
                section=path,
                expected_types=allowed,
                actual_type=type(value).__name__,
            )

    def _validate_const_enum(self, schema: Mapping[str, Any], value: Any, path: str) -> None:
        if "const" in schema and value != schema["const"]:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} does not match its required constant.",
                section=path,
                expected=schema["const"],
            )
        allowed = schema.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} is not one of the reflected enum values.",
                section=path,
                allowed=allowed,
            )

    def _validate_object(
        self,
        schema: Mapping[str, Any],
        value: Mapping[str, Any],
        path: str,
        depth: int,
    ) -> None:
        required = schema.get("required")
        if isinstance(required, list):
            missing = tuple(item for item in required if isinstance(item, str) and item not in value)
            if missing:
                raise _schema_error(
                    self.uri,
                    self.version,
                    f"WAAPI URI {self.uri!r} field {path!r} is missing required members: {', '.join(missing)}.",
                    section=path,
                    missing_fields=missing,
                )
        properties = schema.get("properties")
        property_schemas = properties if isinstance(properties, Mapping) else {}
        pattern_properties = schema.get("patternProperties")
        patterns = pattern_properties if isinstance(pattern_properties, Mapping) else {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _schema_error(
                    self.uri,
                    self.version,
                    f"WAAPI URI {self.uri!r} field {path!r} must use string object keys.",
                    section=path,
                    actual_key_type=type(key).__name__,
                )
            child_schema = property_schemas.get(key)
            if isinstance(child_schema, Mapping):
                self.validate(child_schema, item, path=f"{path}.{key}", depth=depth + 1)
                continue
            matched = False
            for pattern, pattern_schema in patterns.items():
                if not isinstance(pattern, str) or not isinstance(pattern_schema, Mapping):
                    continue
                try:
                    matches = re.search(pattern, key) is not None
                except re.error as exc:
                    raise _schema_error(
                        self.uri,
                        self.version,
                        f"WAAPI URI {self.uri!r} contains an invalid packaged schema pattern.",
                        section=path,
                        pattern=pattern,
                    ) from exc
                if matches:
                    matched = True
                    self.validate(pattern_schema, item, path=f"{path}.{key}", depth=depth + 1)
            additional = schema.get("additionalProperties", True)
            if isinstance(schema.get("$ref"), str) and not property_schemas:
                # The reflected response omits the referenced definition file;
                # its properties cannot be reconstructed locally. Keep the ref
                # visible in validation evidence instead of treating every
                # referenced member as an unknown field.
                additional = True
            if not matched and additional is False:
                raise _schema_error(
                    self.uri,
                    self.version,
                    f"WAAPI URI {self.uri!r} has unsupported field {path}.{key}.",
                    section=path,
                    unknown_field=key,
                )
            if not matched and isinstance(additional, Mapping):
                self.validate(additional, item, path=f"{path}.{key}", depth=depth + 1)

    def _validate_array(self, schema: Mapping[str, Any], value: list[Any], path: str, depth: int) -> None:
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} requires at least {minimum} items.",
                section=path,
                minimum_items=minimum,
                actual_items=len(value),
            )
        if isinstance(maximum, int) and len(value) > maximum:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} allows at most {maximum} items.",
                section=path,
                maximum_items=maximum,
                actual_items=len(value),
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                self.validate(item_schema, item, path=f"{path}[{index}]", depth=depth + 1)

    def _validate_string(self, schema: Mapping[str, Any], value: str, path: str) -> None:
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} is shorter than {minimum} characters.",
                section=path,
                minimum_length=minimum,
                actual_length=len(value),
            )
        if isinstance(maximum, int) and len(value) > maximum:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} is longer than {maximum} characters.",
                section=path,
                maximum_length=maximum,
                actual_length=len(value),
            )
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matches = re.search(pattern, value) is not None
            except re.error as exc:
                raise _schema_error(
                    self.uri,
                    self.version,
                    f"WAAPI URI {self.uri!r} contains an invalid packaged schema pattern.",
                    section=path,
                    pattern=pattern,
                ) from exc
            if not matches:
                raise _schema_error(
                    self.uri,
                    self.version,
                    f"WAAPI URI {self.uri!r} field {path!r} does not match the reflected pattern.",
                    section=path,
                    pattern=pattern,
                )

    def _validate_number(self, schema: Mapping[str, Any], value: int | float, path: str) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} must be finite.",
                section=path,
            )
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} is below the reflected minimum.",
                section=path,
                minimum=minimum,
                actual=value,
            )
        if isinstance(maximum, (int, float)) and value > maximum:
            raise _schema_error(
                self.uri,
                self.version,
                f"WAAPI URI {self.uri!r} field {path!r} is above the reflected maximum.",
                section=path,
                maximum=maximum,
                actual=value,
            )


def _matches_json_type(expected: str, value: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _schema_budget_error(exc: SemanticValidationError) -> bool:
    """Return whether a speculative branch exhausted a global walker budget."""

    return "maximum_nodes" in exc.details or "maximum_depth" in exc.details


def _schema_error(uri: str, version: str, message: str, **details: Any) -> SemanticValidationError:
    return SemanticValidationError(
        SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
        message,
        details={"uri": uri, "version": version, **_json_safe_details(details)},
    )


def _json_safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, tuple):
            result[key] = [list(item) if isinstance(item, tuple) else item for item in value]
        else:
            result[key] = value
    return result

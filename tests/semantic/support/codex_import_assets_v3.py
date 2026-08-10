"""Deterministic file/request materializer for reviewed V3 import cases."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import re
import struct
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_import import (
    ImportContractError,
    normalize_originals_subfolder,
)

from .codex_eval_bundle_v3 import OnlineScenario
from .codex_version_layout_v3 import (
    CodexVersionLayoutError,
    get_codex_version_layout_v3,
)


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
IMPORT_ASSET_CONTRACT = "waapi-skill.import-eval-assets/v2"
COMPOUND_IMPORT_CONTRACT = "waapi-skill.compound-import-fields/v1"
METADATA_DISCOVERY_CONTRACT = "waapi-skill.metadata-discovery/v2"
IMPORT_APIS = frozenset(
    {"ak.wwise.core.audio.import", "ak.wwise.core.audio.importTabDelimited"}
)
CANONICAL_WWISE_LANGUAGE = {
    "Chinese": "Chinese(PRC)",
    "English": "English(US)",
    "Japanese": "Japanese",
    "SFX": "SFX",
}
_HEADER_TO_ROW_KEY = {
    "Object Path": "object_path",
    "Object Type": "object_type",
    "OriginalsSubFolder": "originals_subfolder",
    "Notes": "notes",
    "Audio Source Notes": "audio_source_notes",
}
_SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
_DIRECT_IMPORT_API = "ak.wwise.core.audio.import"
_TAB_IMPORT_API = "ak.wwise.core.audio.importTabDelimited"
_COMPOUND_FIELD_KINDS = frozenset({"property", "reference"})
_COMPOUND_DYNAMIC_MODES = frozenset({"mutate", "preserve"})
_TOKEN_WORD = re.compile(r"[A-Za-z0-9]+")


class ImportAssetMaterializationError(ValueError):
    """A reviewed import asset specification cannot be materialized safely."""


@dataclass(frozen=True, slots=True)
class MaterializedFile:
    key: str
    path: Path
    present: bool
    size: int | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class MaterializedImportCase:
    scenario_id: str
    visible_values: Mapping[str, str]
    operation_requests: tuple[Mapping[str, Any], ...]
    source_files: tuple[MaterializedFile, ...]
    pre_state_files: tuple[MaterializedFile, ...]
    tab_files: tuple[MaterializedFile, ...]
    expected_rows: tuple[Mapping[str, Any], ...]
    expected_primary_dispatch_count: int
    metadata_queries: tuple[str, ...] = ()
    compound_spec: Mapping[str, Any] | None = None
    metadata_binding: Mapping[str, Any] | None = None
    reference_fixture_paths: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @property
    def requires_metadata_binding(self) -> bool:
        return self.compound_spec is not None and self.metadata_binding is None


@dataclass(frozen=True, slots=True)
class BoundImportMetadata:
    """Closed live-metadata binding used to finalize one compound import case."""

    contract: str
    object_type: str
    discovery_sha256: str
    selected: Mapping[str, Mapping[str, Any]]
    reference_targets: Mapping[str, Mapping[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "object_type": self.object_type,
            "discovery_sha256": self.discovery_sha256,
            "selected": {
                key: dict(value)
                for key, value in self.selected.items()
            },
            "reference_targets": {
                key: dict(value)
                for key, value in self.reference_targets.items()
            },
        }


def materialize_import_case(
    scenario: OnlineScenario,
    *,
    version: str,
    asset_root: Path,
) -> MaterializedImportCase:
    """Create immutable WAV/TSV inputs and closed named-operation requests."""

    if scenario.api not in IMPORT_APIS:
        raise ImportAssetMaterializationError(
            f"unsupported import scenario API: {scenario.api}"
        )
    if version not in scenario.versions:
        raise ImportAssetMaterializationError(
            f"{scenario.id} does not support Wwise {version}"
        )
    spec = scenario.fixture.get("asset_spec")
    if not isinstance(spec, Mapping) or spec.get("contract") != IMPORT_ASSET_CONTRACT:
        raise ImportAssetMaterializationError(
            f"{scenario.id} lacks the reviewed import asset contract"
        )
    root = Path(asset_root).expanduser().resolve(strict=False)
    if root.exists():
        raise ImportAssetMaterializationError(
            f"import asset root already exists and cannot be reused: {root}"
        )
    source_root = root / "sources"
    pre_state_root = root / "pre-state"
    tab_root = root / "tables"
    for path in (source_root, pre_state_root, tab_root):
        path.mkdir(parents=True, exist_ok=False)

    sources = _materialize_sources(spec["sources"], source_root)
    pre_state = _materialize_pre_state(spec["pre_state_sources"], pre_state_root)
    source_by_key = {item.key: item for item in sources}
    rows = tuple(
        _versionize_import_row(dict(row), version=version)
        for row in _mapping_rows(spec["rows"], field="rows")
    )
    compound = _parse_compound_spec(spec.get("compound"))
    if compound is not None:
        dynamic_modes = compound_dynamic_modes_by_row(compound, rows)
        rows = tuple(
            {
                **row,
                "compound_dynamic_mode": dynamic_modes[
                    _required_string(row.get("row_key"), field="rows.row_key")
                ],
            }
            for row in rows
        )
    reference_fixture_paths = (
        _compound_reference_fixture_paths(
            compound,
            scenario_id=scenario.id,
            version=version,
        )
        if compound is not None
        else {}
    )

    if scenario.api == _DIRECT_IMPORT_API:
        if compound is None:
            requests = (
                _operation_request(
                    version,
                    "audio.import",
                    {
                        "imports": [
                            _audio_import_row(row, source_by_key=source_by_key)
                            for row in rows
                        ],
                        "import_operation": _required_string(
                            spec.get("audio_import_operation"),
                            field="audio_import_operation",
                        ),
                    },
                ),
            )
            visible_import_rows: Any = requests[0]["arguments"]["imports"]
        else:
            # A compound request is deliberately not executable until a
            # runner-owned live discovery payload closes every dynamic token.
            requests = ()
            visible_import_rows = _visible_compound_import_rows(
                rows,
                compound=compound,
                reference_fixture_paths=reference_fixture_paths,
                source_by_key=source_by_key,
            )
        visible_values = {
            "media_directory": str(source_root),
            "import_rows": _visible_json(visible_import_rows),
        }
        tab_files: tuple[MaterializedFile, ...] = ()
    else:
        location = _versionize_wwise_path(
            _required_string(spec.get("import_location"), field="import_location"),
            version=version,
        )
        table_specs = _mapping_rows(spec["tsv"], field="tsv")
        if compound is None:
            tab_files = _materialize_tables(
                table_specs,
                rows=rows,
                source_by_key=source_by_key,
                tab_root=tab_root,
            )
            requests = _tab_operation_requests(
                version=version,
                table_specs=table_specs,
                tab_files=tab_files,
                import_location=location,
            )
        else:
            # Dynamic header names are live metadata.  Leave the reviewed file
            # paths visible, but do not create a misleading placeholder TSV.
            tab_files = ()
            requests = ()
        if len(requests) == 1:
            visible_values = {
                "import_file": requests[0]["arguments"]["import_file"],
                "import_location": location,
            }
        elif compound is not None and len(table_specs) == 1:
            table_name = _required_string(
                table_specs[0].get("name"),
                field="tsv.name",
            )
            visible_values = {
                "import_file": str((tab_root / _safe_relative(table_name, field="tsv.name")).resolve(strict=False)),
                "import_location": location,
            }
        else:
            visible_values = {
                "language_import_files": _visible_json(
                    [
                        {
                            "file": request["arguments"]["import_file"],
                            "language": request["arguments"]["import_language"],
                            "import_operation": request["arguments"]["import_operation"],
                        }
                        for request in requests
                    ]
                ),
                "import_location": location,
            }

    expected_visible = {item.name for item in scenario.visible_inputs}
    if set(visible_values) != expected_visible:
        raise ImportAssetMaterializationError(
            f"{scenario.id} visible input mismatch; expected={sorted(expected_visible)} "
            f"actual={sorted(visible_values)}"
        )
    if (
        compound is None
        and len(requests) != scenario.primary_dispatch.count
        and scenario.primary_dispatch.count != 0
    ):
        raise ImportAssetMaterializationError(
            f"{scenario.id} request count does not match the reviewed primary dispatch count"
        )
    # The missing-file refusal still owns one preview request whose validation
    # must fail before any WAAPI business dispatch.
    if (
        compound is None
        and scenario.primary_dispatch.count == 0
        and len(requests) != 1
    ):
        raise ImportAssetMaterializationError(
            f"{scenario.id} zero-dispatch refusal must have one preflight request"
        )

    staged_compound: Mapping[str, Any] | None = None
    if compound is not None:
        staged = dict(compound)
        staged["_api"] = scenario.api
        staged["_audio_import_operation"] = spec.get("audio_import_operation")
        staged["_import_location"] = (
            _versionize_wwise_path(str(spec["import_location"]), version=version)
            if isinstance(spec.get("import_location"), str)
            else None
        )
        staged["_table_specs"] = [
            dict(row) for row in _mapping_rows(spec.get("tsv"), field="tsv")
        ]
        staged_compound = MappingProxyType(staged)

    return MaterializedImportCase(
        scenario_id=scenario.id,
        visible_values=visible_values,
        operation_requests=requests,
        source_files=sources,
        pre_state_files=pre_state,
        tab_files=tab_files,
        expected_rows=rows,
        expected_primary_dispatch_count=scenario.primary_dispatch.count,
        metadata_queries=(
            tuple(
                _required_string(row.get("query"), field="compound.metadata_queries.query")
                for row in _mapping_rows(
                    compound["metadata_queries"],
                    field="compound.metadata_queries",
                )
            )
            if compound is not None
            else ()
        ),
        compound_spec=staged_compound,
        reference_fixture_paths=MappingProxyType(dict(reference_fixture_paths)),
    )


def bind_import_live_metadata(
    materialized: MaterializedImportCase,
    *,
    version: str,
    discovery_payload: Mapping[str, Any],
    reference_targets: Mapping[str, Mapping[str, Any]] | None = None,
) -> MaterializedImportCase:
    """Finalize one staged compound import from one live discovery result.

    The reviewed JSON stores business intents, not Wwise property tokens.
    Exactly one bounded discovery result resolves those intents.  Ambiguous or
    incomplete candidate sets fail closed; the binder never chooses a top
    search hit merely because it ranked first.
    """

    if version not in _SUPPORTED_VERSIONS:
        raise ImportAssetMaterializationError(
            f"unsupported compound import version: {version}"
        )
    if materialized.compound_spec is None:
        raise ImportAssetMaterializationError(
            "ordinary import cases do not accept a metadata binding"
        )
    if materialized.metadata_binding is not None:
        raise ImportAssetMaterializationError(
            "compound import metadata is immutable once bound"
        )
    if materialized.operation_requests or materialized.tab_files:
        raise ImportAssetMaterializationError(
            "an unbound compound import must not expose executable requests or tables"
        )

    compound = dict(materialized.compound_spec)
    discovery = _metadata_agent_result(discovery_payload)
    selected = _select_compound_metadata(
        compound,
        discovery=discovery,
    )
    targets = _normalize_reference_targets(
        materialized,
        reference_targets=reference_targets,
    )
    binding = BoundImportMetadata(
        contract="waapi-skill.bound-import-metadata/v1",
        object_type=_required_string(
            compound.get("object_type"),
            field="compound.object_type",
        ),
        discovery_sha256=_json_sha256(discovery),
        selected=MappingProxyType(
            {
                key: MappingProxyType(dict(value))
                for key, value in selected.items()
            }
        ),
        reference_targets=MappingProxyType(
            {
                key: MappingProxyType(dict(value))
                for key, value in targets.items()
            }
        ),
    )

    source_by_key = {item.key: item for item in materialized.source_files}
    rows = [dict(row) for row in materialized.expected_rows]
    effective_by_row = _compound_effective_fields(
        rows,
        compound=compound,
        selected=selected,
        reference_targets=targets,
    )
    inline_by_row = _compound_inline_audio(
        rows,
        compound=compound,
        source_by_key=source_by_key,
    )

    if _materialized_api(materialized) == _DIRECT_IMPORT_API:
        imports: list[dict[str, Any]] = []
        expected_rows: list[dict[str, Any]] = []
        for row in rows:
            row_key = _required_string(row.get("row_key"), field="rows.row_key")
            request_row = _audio_import_row(row, source_by_key=source_by_key)
            inline = inline_by_row.get(row_key)
            if inline is not None:
                request_row.pop("audio_file", None)
                request_row["audio_file_base64"] = inline
            effective = effective_by_row[row_key]
            row_properties = effective["row_properties"]
            row_references = effective["row_references"]
            if row_properties:
                request_row["properties"] = [
                    {"name": item["name"], "value": item["value"]}
                    for item in row_properties
                ]
            if row_references:
                request_row["references"] = [
                    {"name": item["name"], "target": dict(item["target"])}
                    for item in row_references
                ]
            imports.append(request_row)
            expected = dict(row)
            expected["compound_effective_properties"] = list(
                effective["effective_properties"]
            )
            expected["compound_effective_references"] = list(
                effective["effective_references"]
            )
            expected["compound_media_kind"] = (
                "inline_base64" if inline is not None else "regular_file"
            )
            expected_rows.append(expected)

        defaults = _resolved_default_fields(
            compound,
            selected=selected,
            reference_targets=targets,
        )
        arguments: dict[str, Any] = {
            "imports": imports,
            "import_operation": _direct_import_operation(materialized),
        }
        if defaults["properties"] or defaults["references"]:
            arguments["defaults"] = {
                **(
                    {"properties": defaults["properties"]}
                    if defaults["properties"]
                    else {}
                ),
                **(
                    {"references": defaults["references"]}
                    if defaults["references"]
                    else {}
                ),
            }
        requests = (
            _operation_request(
                version,
                "audio.import",
                arguments,
            ),
        )
        tab_files: tuple[MaterializedFile, ...] = ()
    else:
        table_specs = _compound_table_specs(
            materialized,
            compound=compound,
            selected=selected,
            effective_by_row=effective_by_row,
            inline_by_row=inline_by_row,
        )
        tab_root = _materialized_asset_root(materialized) / "tables"
        tab_files = _materialize_tables(
            table_specs,
            rows=rows,
            source_by_key=source_by_key,
            tab_root=tab_root,
            inline_base64_by_row=inline_by_row,
            dynamic_cells_by_row={
                row_key: dict(value["tsv_cells"])
                for row_key, value in effective_by_row.items()
            },
        )
        requests = _tab_operation_requests(
            version=version,
            table_specs=table_specs,
            tab_files=tab_files,
            import_location=_materialized_import_location(materialized),
        )
        expected_rows = []
        for row in rows:
            row_key = _required_string(row.get("row_key"), field="rows.row_key")
            effective = effective_by_row[row_key]
            expected = dict(row)
            expected["compound_effective_properties"] = list(
                effective["effective_properties"]
            )
            expected["compound_effective_references"] = list(
                effective["effective_references"]
            )
            expected["compound_media_kind"] = (
                "inline_base64"
                if row_key in inline_by_row
                else "regular_file"
            )
            expected_rows.append(expected)

    if len(requests) != materialized.expected_primary_dispatch_count:
        raise ImportAssetMaterializationError(
            "bound compound request count differs from the reviewed primary dispatch"
        )
    return replace(
        materialized,
        operation_requests=tuple(requests),
        tab_files=tuple(tab_files),
        expected_rows=tuple(expected_rows),
        metadata_binding=MappingProxyType(binding.as_dict()),
    )


def bound_import_metadata_tokens(
    materialized: MaterializedImportCase,
) -> tuple[str, ...]:
    """Return the exact live names sealed into one bound compound import.

    The broker consumes this list when it proves that every trusted dynamic
    property, reference, and same-object dependency was present in the
    evaluated agent's own live metadata-discovery result.
    """

    binding = materialized.metadata_binding
    if (
        materialized.compound_spec is None
        or materialized.requires_metadata_binding
        or not isinstance(binding, Mapping)
        or binding.get("contract") != "waapi-skill.bound-import-metadata/v1"
    ):
        raise ImportAssetMaterializationError(
            "compound import metadata tokens require one completed live binding"
        )
    selected = binding.get("selected")
    if not isinstance(selected, Mapping) or not selected:
        raise ImportAssetMaterializationError(
            "bound compound import has no selected live metadata"
        )

    tokens: list[str] = []
    seen_tokens: dict[str, str] = {}

    def append_token(value: str) -> None:
        folded = value.casefold()
        previous = seen_tokens.get(folded)
        if previous is None:
            seen_tokens[folded] = value
            tokens.append(value)
        elif previous != value:
            raise ImportAssetMaterializationError(
                "bound compound metadata contains conflicting live-name casing"
            )

    for intent, raw in selected.items():
        if not isinstance(intent, str) or not isinstance(raw, Mapping):
            raise ImportAssetMaterializationError(
                "bound compound metadata selection is malformed"
            )
        name = raw.get("name")
        dependencies = raw.get("same_object_dependencies")
        if (
            not isinstance(name, str)
            or not name
            or name.startswith("@")
            or not isinstance(dependencies, list)
        ):
            raise ImportAssetMaterializationError(
                f"bound compound metadata intent {intent!r} is malformed"
            )
        append_token(name)
        for dependency in dependencies:
            dependency_name = (
                dependency.get("name")
                if isinstance(dependency, Mapping)
                else None
            )
            if (
                not isinstance(dependency_name, str)
                or not dependency_name
                or dependency_name.startswith("@")
            ):
                raise ImportAssetMaterializationError(
                    f"bound compound metadata intent {intent!r} has a malformed dependency"
                )
            append_token(dependency_name)
    return tuple(tokens)


def _parse_compound_spec(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ImportAssetMaterializationError("asset_spec.compound must be an object")
    required = {
        "contract",
        "object_type",
        "metadata_queries",
        "reference_fixtures",
        "defaults",
        "row_overrides",
        "inline_base64_rows",
        "tsv_dynamic_headers",
    }
    if set(value) != required or value.get("contract") != COMPOUND_IMPORT_CONTRACT:
        raise ImportAssetMaterializationError(
            "asset_spec.compound does not match the closed compound import contract"
        )
    object_type = _required_string(value.get("object_type"), field="compound.object_type")
    if object_type != "Sound":
        raise ImportAssetMaterializationError(
            "compound import metadata scope must be the exact live Sound type"
        )
    queries = _mapping_rows(value.get("metadata_queries"), field="compound.metadata_queries")
    if not 1 <= len(queries) <= 8:
        raise ImportAssetMaterializationError(
            "compound import requires 1..8 metadata queries"
        )
    ids: list[str] = []
    phrases: list[str] = []
    for index, row in enumerate(queries):
        if set(row) != {
            "id",
            "query",
            "kind",
            "metadata_types",
            "name_tokens",
        }:
            raise ImportAssetMaterializationError(
                f"compound.metadata_queries[{index}] schema is not closed"
            )
        ids.append(_required_string(row.get("id"), field="compound.metadata_queries.id"))
        phrases.append(
            _required_string(row.get("query"), field="compound.metadata_queries.query")
        )
        if row.get("kind") not in _COMPOUND_FIELD_KINDS:
            raise ImportAssetMaterializationError(
                "compound metadata query kind must be property or reference"
            )
        metadata_types = tuple(
            _required_string(item, field="compound.metadata_queries.metadata_types")
            for item in _sequence(
                row.get("metadata_types"),
                field="compound.metadata_queries.metadata_types",
            )
        )
        name_tokens = tuple(
            _required_string(item, field="compound.metadata_queries.name_tokens")
            for item in _sequence(
                row.get("name_tokens"),
                field="compound.metadata_queries.name_tokens",
            )
        )
        if not metadata_types or not name_tokens:
            raise ImportAssetMaterializationError(
                "compound metadata selectors must declare type and name-token evidence"
            )
    _require_unique(ids, field="compound metadata intent ids")
    _require_unique(
        [" ".join(value.split()).casefold() for value in phrases],
        field="compound metadata query phrases",
    )
    fixtures = _mapping_rows(
        value.get("reference_fixtures"),
        field="compound.reference_fixtures",
    )
    fixture_keys: list[str] = []
    fixture_names: list[str] = []
    for row in fixtures:
        if set(row) != {"key", "name"}:
            raise ImportAssetMaterializationError(
                "compound reference fixture schema is not closed"
            )
        fixture_keys.append(
            _required_string(row.get("key"), field="compound.reference_fixtures.key")
        )
        fixture_names.append(
            _required_string(row.get("name"), field="compound.reference_fixtures.name")
        )
    _require_unique(fixture_keys, field="compound reference fixture keys")
    _require_unique(
        [value.casefold() for value in fixture_names],
        field="compound reference fixture names",
    )
    if not isinstance(value.get("defaults"), Mapping):
        raise ImportAssetMaterializationError("compound.defaults must be an object")
    if set(value["defaults"]) != {"properties", "references"}:
        raise ImportAssetMaterializationError("compound.defaults schema is not closed")
    _validate_compound_assignments(
        value["defaults"],
        field="compound.defaults",
        known_intents=frozenset(ids),
        known_fixtures=frozenset(fixture_keys),
    )
    overrides = _mapping_rows(
        value.get("row_overrides"),
        field="compound.row_overrides",
    )
    override_keys: list[str] = []
    for row in overrides:
        if set(row) != {"row_key", "properties", "references"}:
            raise ImportAssetMaterializationError(
                "compound row override schema is not closed"
            )
        override_keys.append(
            _required_string(row.get("row_key"), field="compound.row_overrides.row_key")
        )
        _validate_compound_assignments(
            row,
            field="compound.row_overrides",
            known_intents=frozenset(ids),
            known_fixtures=frozenset(fixture_keys),
            include_row_key=True,
        )
    _require_unique(override_keys, field="compound row override keys")
    inline_rows = _mapping_rows(
        value.get("inline_base64_rows"),
        field="compound.inline_base64_rows",
    )
    inline_keys: list[str] = []
    for row in inline_rows:
        if set(row) != {"row_key", "relative_path"}:
            raise ImportAssetMaterializationError(
                "compound inline-base64 row schema is not closed"
            )
        inline_keys.append(
            _required_string(row.get("row_key"), field="compound.inline_base64_rows.row_key")
        )
        _safe_inline_relative_path(
            row.get("relative_path"),
            field="compound.inline_base64_rows.relative_path",
        )
    _require_unique(inline_keys, field="compound inline-base64 row keys")
    dynamic_headers = _mapping_rows(
        value.get("tsv_dynamic_headers"),
        field="compound.tsv_dynamic_headers",
    )
    dynamic_intents: list[str] = []
    for row in dynamic_headers:
        if set(row) != {"kind", "intent", "values"}:
            raise ImportAssetMaterializationError(
                "compound TSV dynamic-header schema is not closed"
            )
        kind = row.get("kind")
        intent = _required_string(
            row.get("intent"),
            field="compound.tsv_dynamic_headers.intent",
        )
        if kind not in _COMPOUND_FIELD_KINDS or intent not in ids:
            raise ImportAssetMaterializationError(
                "compound TSV dynamic header has an unknown kind or intent"
            )
        if not isinstance(row.get("values"), Mapping) or not row["values"]:
            raise ImportAssetMaterializationError(
                "compound TSV dynamic header values must be a non-empty object"
            )
        dynamic_intents.append(intent)
    _require_unique(dynamic_intents, field="compound TSV dynamic intents")
    return dict(value)


def compound_dynamic_modes_by_row(
    compound: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, str]:
    """Derive each row's exact dynamic-field intent from the reviewed spec.

    ``mutate`` means the row has at least one applicable property/reference
    assignment.  ``preserve`` means the table deliberately leaves every
    dynamic column blank for that row.  Callers must not infer this distinction
    from the generated expectation arrays because doing so would let an
    accidental simultaneous omission of both arrays pass as intentional.
    """

    defaults = compound.get("defaults")
    if not isinstance(defaults, Mapping):
        raise ImportAssetMaterializationError(
            "compound.defaults must be an object"
        )
    default_assignments = any(
        _mapping_rows(
            defaults.get(kind),
            field=f"compound.defaults.{kind}",
        )
        for kind in ("properties", "references")
    )
    row_keys = tuple(
        _required_string(row.get("row_key"), field="rows.row_key")
        for row in rows
    )
    _require_unique(row_keys, field="compound row keys")
    known_row_keys = frozenset(row_keys)

    overrides = {
        _required_string(
            row.get("row_key"),
            field="compound.row_overrides.row_key",
        ): row
        for row in _mapping_rows(
            compound.get("row_overrides"),
            field="compound.row_overrides",
        )
    }
    unknown_override_keys = sorted(set(overrides) - known_row_keys)
    if unknown_override_keys:
        raise ImportAssetMaterializationError(
            "compound row overrides reference unknown rows: "
            f"{unknown_override_keys}"
        )

    dynamic_headers = _mapping_rows(
        compound.get("tsv_dynamic_headers"),
        field="compound.tsv_dynamic_headers",
    )
    for header in dynamic_headers:
        values = header.get("values")
        if not isinstance(values, Mapping):
            raise ImportAssetMaterializationError(
                "compound TSV dynamic header values must be an object"
            )
        unknown_value_keys = sorted(
            str(key)
            for key in values
            if key != "*" and key not in known_row_keys
        )
        if unknown_value_keys:
            raise ImportAssetMaterializationError(
                "compound TSV dynamic header values reference unknown rows: "
                f"{unknown_value_keys}"
            )

    result: dict[str, str] = {}
    for row_key in row_keys:
        override = overrides.get(row_key)
        override_assignments = (
            False
            if override is None
            else any(
                _mapping_rows(
                    override.get(kind),
                    field=f"compound.row_overrides.{kind}",
                )
                for kind in ("properties", "references")
            )
        )
        table_assignments = any(
            row_key in header["values"] or "*" in header["values"]
            for header in dynamic_headers
        )
        result[row_key] = (
            "mutate"
            if default_assignments or override_assignments or table_assignments
            else "preserve"
        )
    if set(result.values()) - _COMPOUND_DYNAMIC_MODES:
        raise ImportAssetMaterializationError(
            "compound dynamic row mode is unsupported"
        )
    return MappingProxyType(result)


def _validate_compound_assignments(
    value: Mapping[str, Any],
    *,
    field: str,
    known_intents: frozenset[str],
    known_fixtures: frozenset[str],
    include_row_key: bool = False,
) -> None:
    for kind in ("properties", "references"):
        rows = _mapping_rows(value.get(kind), field=f"{field}.{kind}")
        intents: list[str] = []
        for row in rows:
            required = (
                {"intent", "value"}
                if kind == "properties"
                else {"intent", "target_fixture"}
            )
            if set(row) != required:
                raise ImportAssetMaterializationError(
                    f"{field}.{kind} assignment schema is not closed"
                )
            intent = _required_string(row.get("intent"), field=f"{field}.{kind}.intent")
            if intent not in known_intents:
                raise ImportAssetMaterializationError(
                    f"{field}.{kind} uses unknown metadata intent {intent!r}"
                )
            if kind == "properties":
                _require_scalar(row.get("value"), field=f"{field}.{kind}.value")
            else:
                fixture = _required_string(
                    row.get("target_fixture"),
                    field=f"{field}.{kind}.target_fixture",
                )
                if fixture not in known_fixtures:
                    raise ImportAssetMaterializationError(
                        f"{field}.{kind} uses unknown reference fixture {fixture!r}"
                    )
            intents.append(intent)
        _require_unique(intents, field=f"{field}.{kind} intents")
    if include_row_key:
        _required_string(value.get("row_key"), field=f"{field}.row_key")


def _metadata_agent_result(value: Mapping[str, Any]) -> dict[str, Any]:
    payload: Any = value.get("agent_result", value)
    if not isinstance(payload, Mapping):
        raise ImportAssetMaterializationError(
            "compound import live Sound metadata discovery payload is not an object"
        )
    scope = payload.get("scope")
    resolved = scope.get("resolved") if isinstance(scope, Mapping) else None
    failures: list[str] = []
    for field, expected in (
        ("contract", METADATA_DISCOVERY_CONTRACT),
        ("authority", "live-waapi"),
        ("result_detail", "compact"),
        ("selection_required", True),
        ("exact_live_name_required_for_mutation", True),
    ):
        if payload.get(field) != expected:
            failures.append(field)
    if (
        not isinstance(scope, Mapping)
        or scope.get("kind") != "object_type"
        or not isinstance(resolved, Mapping)
        or resolved.get("name") != "Sound"
    ):
        failures.append("scope")
    if not isinstance(payload.get("candidates"), list):
        failures.append("candidates")
    if not isinstance(payload.get("dependency_candidates"), list):
        failures.append("dependency_candidates")
    if payload.get("dependency_closure_complete") is not True:
        failures.append("dependency_closure_complete")
    unresolved = payload.get("unresolved_dependencies")
    if unresolved != []:
        failures.append("unresolved_dependencies")
    if failures:
        bounded_unresolved = (
            unresolved[:4]
            if isinstance(unresolved, list)
            else unresolved
        )
        raise ImportAssetMaterializationError(
            "compound import requires a complete live Sound metadata discovery "
            f"result; invalid fields={failures!r}; "
            f"unresolved_dependencies={bounded_unresolved!r}"
        )
    return json.loads(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _select_compound_metadata(
    compound: Mapping[str, Any],
    *,
    discovery: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    candidates = discovery.get("candidates")
    dependencies = discovery.get("dependency_candidates")
    assert isinstance(candidates, list)
    assert isinstance(dependencies, list)
    # A live dependency may also be one of the selected root candidates.  The
    # discovery contract deliberately omits such rows from
    # ``dependency_candidates`` because their full metadata already exists in
    # ``candidates``.  Resolve dependency detail from the union so a compound
    # request does not fail merely because, for example,
    # UseMaxSoundPerInstance is both requested directly and required by
    # MaxSoundPerInstance.
    dependency_by_name = {
        str(row.get("name")).casefold(): dict(row)
        for row in (*candidates, *dependencies)
        if isinstance(row, Mapping) and isinstance(row.get("name"), str)
    }
    selected: dict[str, dict[str, Any]] = {}
    used_names: set[str] = set()
    for query in _mapping_rows(
        compound.get("metadata_queries"),
        field="compound.metadata_queries",
    ):
        intent = _required_string(query.get("id"), field="metadata intent")
        kind = _required_string(query.get("kind"), field=f"{intent}.kind")
        accepted_types = {
            str(value).casefold()
            for value in _sequence(
                query.get("metadata_types"),
                field=f"{intent}.metadata_types",
            )
        }
        required_tokens = {
            str(value).casefold()
            for value in _sequence(
                query.get("name_tokens"),
                field=f"{intent}.name_tokens",
            )
        }
        matches: list[dict[str, Any]] = []
        for raw in candidates:
            if not isinstance(raw, Mapping):
                continue
            name = raw.get("name")
            metadata = raw.get("metadata")
            metadata_type = (
                str(metadata.get("type", "")).casefold()
                if isinstance(metadata, Mapping)
                else ""
            )
            if (
                not isinstance(name, str)
                or raw.get("kind") != kind
                or not isinstance(metadata, Mapping)
                or (
                    metadata_type not in accepted_types
                    and not (
                        kind == "reference"
                        and metadata_type == ""
                    )
                )
                or not required_tokens.issubset(_name_tokens(name))
            ):
                continue
            matches.append(dict(raw))
        if len(matches) != 1:
            nearby = [
                {
                    "name": raw.get("name"),
                    "kind": raw.get("kind"),
                    "metadata_type": (
                        raw.get("metadata", {}).get("type")
                        if isinstance(raw.get("metadata"), Mapping)
                        else None
                    ),
                }
                for raw in candidates
                if isinstance(raw, Mapping)
                and isinstance(raw.get("name"), str)
                and (
                    required_tokens.intersection(
                        _name_tokens(str(raw["name"]))
                    )
                    or intent == "output_bus"
                    and "bus" in _name_tokens(str(raw["name"]))
                )
            ][:12]
            raise ImportAssetMaterializationError(
                f"metadata intent {intent!r} resolved {len(matches)} candidates; "
                "a unique live candidate is required; nearby live candidates: "
                f"{nearby!r}"
            )
        candidate = matches[0]
        key = str(candidate["name"]).casefold()
        if key in used_names:
            raise ImportAssetMaterializationError(
                "two compound metadata intents resolved to the same live token"
            )
        used_names.add(key)
        same_object_dependencies = candidate.get("same_object_dependencies", [])
        if (
            not isinstance(same_object_dependencies, list)
            or not all(isinstance(item, str) and item for item in same_object_dependencies)
        ):
            raise ImportAssetMaterializationError(
                f"metadata intent {intent!r} has malformed dependency evidence"
            )
        dependency_rows: list[dict[str, Any]] = []
        for dependency_name in same_object_dependencies:
            dependency = dependency_by_name.get(dependency_name.casefold())
            if dependency is None:
                raise ImportAssetMaterializationError(
                    f"metadata intent {intent!r} lacks dependency detail for "
                    f"{dependency_name!r}"
                )
            dependency_rows.append(dependency)
        selected[intent] = {
            "name": candidate["name"],
            "kind": kind,
            "metadata": dict(candidate["metadata"]),
            "same_object_dependencies": dependency_rows,
        }
    return selected


def _name_tokens(value: str) -> frozenset[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return frozenset(token.casefold() for token in _TOKEN_WORD.findall(expanded))


def _normalize_reference_targets(
    materialized: MaterializedImportCase,
    *,
    reference_targets: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    supplied = (
        {
            key: {"kind": "path", "value": value}
            for key, value in materialized.reference_fixture_paths.items()
        }
        if reference_targets is None
        else {key: dict(value) for key, value in reference_targets.items()}
    )
    expected_keys = set(materialized.reference_fixture_paths)
    if set(supplied) != expected_keys:
        raise ImportAssetMaterializationError(
            "compound reference target keys differ from the reviewed fixtures"
        )
    for key, identity in supplied.items():
        if set(identity) != {"kind", "value"}:
            raise ImportAssetMaterializationError(
                f"compound reference target {key!r} identity is not closed"
            )
        kind = identity.get("kind")
        value = identity.get("value")
        if kind == "path":
            if (
                not isinstance(value, str)
                or not value.startswith("\\")
                or value != materialized.reference_fixture_paths[key]
            ):
                raise ImportAssetMaterializationError(
                    f"compound reference target {key!r} path drifted"
                )
        elif kind == "id":
            if (
                not isinstance(value, str)
                or re.fullmatch(
                    r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}",
                    value,
                )
                is None
            ):
                raise ImportAssetMaterializationError(
                    f"compound reference target {key!r} GUID is invalid"
                )
        else:
            raise ImportAssetMaterializationError(
                f"compound reference target {key!r} must use path or id"
            )
    return supplied


def _resolved_default_fields(
    compound: Mapping[str, Any],
    *,
    selected: Mapping[str, Mapping[str, Any]],
    reference_targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    defaults = compound.get("defaults")
    if not isinstance(defaults, Mapping):
        raise ImportAssetMaterializationError("compound defaults are unavailable")
    properties = [
        {
            "name": selected[str(item["intent"])]["name"],
            "value": item["value"],
        }
        for item in _mapping_rows(
            defaults.get("properties"),
            field="compound.defaults.properties",
        )
    ]
    references: list[dict[str, Any]] = []
    for item in _mapping_rows(
        defaults.get("references"),
        field="compound.defaults.references",
    ):
        intent = str(item["intent"])
        effective = _effective_reference(
            selected[intent],
            item,
            reference_targets=reference_targets,
        )
        references.append(
            {
                "name": effective["name"],
                "target": dict(effective["target"]),
            }
        )
        for dependency in effective["activation_properties"]:
            if all(
                str(value["name"]).casefold()
                != str(dependency["name"]).casefold()
                for value in properties
            ):
                properties.append(
                    {
                        "name": dependency["name"],
                        "value": dependency["value"],
                    }
                )
    return {"properties": properties, "references": references}


def _compound_effective_fields(
    rows: Sequence[Mapping[str, Any]],
    *,
    compound: Mapping[str, Any],
    selected: Mapping[str, Mapping[str, Any]],
    reference_targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    defaults = compound.get("defaults")
    assert isinstance(defaults, Mapping)
    overrides = {
        str(row["row_key"]): row
        for row in _mapping_rows(
            compound.get("row_overrides"),
            field="compound.row_overrides",
        )
    }
    dynamic_headers = _mapping_rows(
        compound.get("tsv_dynamic_headers"),
        field="compound.tsv_dynamic_headers",
    )
    result: dict[str, dict[str, Any]] = {}
    dynamic_modes = compound_dynamic_modes_by_row(compound, rows)

    for row in rows:
        row_key = _required_string(row.get("row_key"), field="rows.row_key")
        override = overrides.get(
            row_key,
            {"properties": [], "references": []},
        )
        override_property_intents = {
            str(item["intent"])
            for item in _mapping_rows(
                override.get("properties"),
                field="compound.row_overrides.properties",
            )
        }
        override_reference_intents = {
            str(item["intent"])
            for item in _mapping_rows(
                override.get("references"),
                field="compound.row_overrides.references",
            )
        }
        property_by_intent = {
            str(item["intent"]): dict(item)
            for item in _mapping_rows(
                defaults.get("properties"),
                field="compound.defaults.properties",
            )
        }
        reference_by_intent = {
            str(item["intent"]): dict(item)
            for item in _mapping_rows(
                defaults.get("references"),
                field="compound.defaults.references",
            )
        }
        for item in _mapping_rows(
            override.get("properties"),
            field="compound.row_overrides.properties",
        ):
            property_by_intent[str(item["intent"])] = dict(item)
        for item in _mapping_rows(
            override.get("references"),
            field="compound.row_overrides.references",
        ):
            reference_by_intent[str(item["intent"])] = dict(item)

        tsv_cells: dict[str, str] = {}
        for header in dynamic_headers:
            intent = str(header["intent"])
            raw_values = header.get("values")
            assert isinstance(raw_values, Mapping)
            value = raw_values.get(row_key, raw_values.get("*"))
            if value is None:
                continue
            resolved = selected[intent]
            column = (
                f"Property[{resolved['name']}]"
                if header["kind"] == "property"
                else f"Reference[{resolved['name']}]"
            )
            if header["kind"] == "property":
                _require_scalar(value, field=f"{row_key}.{intent}")
                property_by_intent[intent] = {"intent": intent, "value": value}
                tsv_cells[column] = _tab_scalar(value)
            else:
                if (
                    not isinstance(value, Mapping)
                    or set(value) != {"target_fixture"}
                ):
                    raise ImportAssetMaterializationError(
                        f"{row_key}.{intent} reference value is malformed"
                    )
                target_fixture = _required_string(
                    value.get("target_fixture"),
                    field=f"{row_key}.{intent}.target_fixture",
                )
                reference_by_intent[intent] = {
                    "intent": intent,
                    "target_fixture": target_fixture,
                }
                target = reference_targets[target_fixture]
                tsv_cells[column] = str(target["value"])

        effective_properties = [
            _effective_property(selected[intent], assignment)
            for intent, assignment in property_by_intent.items()
        ]
        effective_references = [
            _effective_reference(
                selected[intent],
                assignment,
                reference_targets=reference_targets,
            )
            for intent, assignment in reference_by_intent.items()
        ]
        # Direct import derives these activation properties inside the gateway.
        # Tab import requires explicit columns; add both to the independent
        # expected state and, where applicable, to the generated table.
        for reference in effective_references:
            for dependency in reference["activation_properties"]:
                dependency_name = str(dependency["name"])
                if all(
                    str(item["name"]).casefold() != dependency_name.casefold()
                    for item in effective_properties
                ):
                    effective_properties.append(dependency)
                if dynamic_headers:
                    tsv_cells.setdefault(
                        f"Property[{dependency_name}]",
                        "true",
                    )

        has_properties = bool(effective_properties)
        has_references = bool(effective_references)
        if has_properties != has_references:
            raise ImportAssetMaterializationError(
                f"compound row {row_key!r} must bind property and reference "
                "expectations together"
            )
        expected_mode = dynamic_modes[row_key]
        if row.get("compound_dynamic_mode") != expected_mode:
            raise ImportAssetMaterializationError(
                f"compound row {row_key!r} dynamic mode differs from its case spec"
            )
        if expected_mode == "mutate" and not has_properties:
            raise ImportAssetMaterializationError(
                f"compound row {row_key!r} requires dynamic expectations"
            )
        if expected_mode == "preserve" and has_properties:
            raise ImportAssetMaterializationError(
                f"compound row {row_key!r} unexpectedly has dynamic expectations"
            )

        result[row_key] = {
            "row_properties": [
                {
                    "name": item["name"],
                    "value": item["value"],
                }
                for intent, item in (
                    (
                        intent,
                        _effective_property(
                            selected[intent],
                            property_by_intent[intent],
                        ),
                    )
                    for intent in override_property_intents
                )
                if not dynamic_headers
            ],
            "row_references": [
                {
                    "name": item["name"],
                    "target": item["target"],
                }
                for intent, item in (
                    (
                        intent,
                        _effective_reference(
                            selected[intent],
                            reference_by_intent[intent],
                            reference_targets=reference_targets,
                        ),
                    )
                    for intent in override_reference_intents
                )
                if not dynamic_headers
            ],
            "effective_properties": effective_properties,
            "effective_references": effective_references,
            "tsv_cells": tsv_cells,
        }
    return result


def _effective_property(
    selected: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = selected.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ImportAssetMaterializationError("selected property metadata is malformed")
    return {
        "name": selected["name"],
        "value": assignment["value"],
        "metadata_type": metadata.get("type"),
        "source": "request",
    }


def _effective_reference(
    selected: Mapping[str, Any],
    assignment: Mapping[str, Any],
    *,
    reference_targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    fixture = str(assignment["target_fixture"])
    dependencies = selected.get("same_object_dependencies", [])
    activation: list[dict[str, Any]] = []
    if not isinstance(dependencies, list):
        raise ImportAssetMaterializationError("selected reference dependencies are malformed")
    for row in dependencies:
        metadata = row.get("metadata") if isinstance(row, Mapping) else None
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("name"), str)
            or not isinstance(metadata, Mapping)
            or str(metadata.get("type", "")).casefold() not in {"bool", "boolean"}
        ):
            raise ImportAssetMaterializationError(
                "reference activation dependency must be a live Boolean property"
            )
        activation.append(
            {
                "name": row["name"],
                "value": True,
                "metadata_type": metadata["type"],
                "source": "reference_dependency",
            }
        )
    return {
        "name": selected["name"],
        "target": dict(reference_targets[fixture]),
        "target_fixture": fixture,
        "activation_properties": activation,
    }


def _compound_inline_audio(
    rows: Sequence[Mapping[str, Any]],
    *,
    compound: Mapping[str, Any],
    source_by_key: Mapping[str, MaterializedFile],
) -> dict[str, str]:
    row_by_key = {
        _required_string(row.get("row_key"), field="rows.row_key"): row
        for row in rows
    }
    result: dict[str, str] = {}
    for item in _mapping_rows(
        compound.get("inline_base64_rows"),
        field="compound.inline_base64_rows",
    ):
        row_key = _required_string(
            item.get("row_key"),
            field="compound.inline_base64_rows.row_key",
        )
        row = row_by_key.get(row_key)
        if row is None:
            raise ImportAssetMaterializationError(
                f"inline-base64 fixture references unknown row {row_key!r}"
            )
        source_key = _required_string(row.get("source_key"), field=f"{row_key}.source_key")
        source = source_by_key.get(source_key)
        if source is None or not source.present:
            raise ImportAssetMaterializationError(
                f"inline-base64 row {row_key!r} lacks a present source WAV"
            )
        raw = source.path.read_bytes()
        relative = _safe_inline_relative_path(
            item.get("relative_path"),
            field=f"{row_key}.relative_path",
        )
        result[row_key] = f"{relative}|{base64.b64encode(raw).decode('ascii')}"
    return result


def _compound_table_specs(
    materialized: MaterializedImportCase,
    *,
    compound: Mapping[str, Any],
    selected: Mapping[str, Mapping[str, Any]],
    effective_by_row: Mapping[str, Mapping[str, Any]],
    inline_by_row: Mapping[str, str],
) -> tuple[Mapping[str, Any], ...]:
    del selected  # exact names are already present in the sealed cell mapping.
    asset_spec = _materialized_asset_spec(materialized)
    result: list[dict[str, Any]] = []
    dynamic_columns: list[str] = []
    for value in effective_by_row.values():
        cells = value.get("tsv_cells")
        if isinstance(cells, Mapping):
            for column in cells:
                if column not in dynamic_columns:
                    dynamic_columns.append(str(column))
    for raw in _mapping_rows(asset_spec.get("tsv"), field="tsv"):
        table = dict(raw)
        headers = [
            _required_string(value, field="tsv.headers")
            for value in _sequence(table.get("headers"), field="tsv.headers")
        ]
        if inline_by_row and "Audio File Base64" not in headers:
            audio_index = headers.index("Audio File") + 1
            headers.insert(audio_index, "Audio File Base64")
        if dynamic_columns and "Object Type" not in headers:
            # Keep the leaf type explicit for rows that create a new Sound
            # through a dynamic table.  Existing useExisting rows intentionally
            # leave these dynamic cells blank because Wwise can otherwise bind
            # them to the newly imported AudioFileSource instead of the Sound.
            object_path_index = headers.index("Object Path") + 1
            headers.insert(object_path_index, "Object Type")
        for column in dynamic_columns:
            if column not in headers:
                headers.append(column)
        table["headers"] = headers
        result.append(table)
    return tuple(result)


def _visible_compound_import_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    compound: Mapping[str, Any],
    reference_fixture_paths: Mapping[str, str],
    source_by_key: Mapping[str, MaterializedFile],
) -> list[dict[str, Any]]:
    defaults = compound.get("defaults")
    assert isinstance(defaults, Mapping)
    overrides = {
        str(row["row_key"]): row
        for row in _mapping_rows(
            compound.get("row_overrides"),
            field="compound.row_overrides",
        )
    }
    inline_by_row = _compound_inline_audio(
        rows,
        compound=compound,
        source_by_key=source_by_key,
    )
    visible: list[dict[str, Any]] = []
    for row in rows:
        row_key = str(row["row_key"])
        current = _audio_import_row(row, source_by_key=source_by_key)
        inline = inline_by_row.get(row_key)
        if inline is not None:
            current.pop("audio_file", None)
            current["audio_file_base64"] = inline
        property_values = {
            str(item["intent"]): item["value"]
            for item in _mapping_rows(
                defaults.get("properties"),
                field="compound.defaults.properties",
            )
        }
        reference_values = {
            str(item["intent"]): reference_fixture_paths[
                str(item["target_fixture"])
            ]
            for item in _mapping_rows(
                defaults.get("references"),
                field="compound.defaults.references",
            )
        }
        override = overrides.get(row_key)
        if override is not None:
            property_values.update(
                {
                    str(item["intent"]): item["value"]
                    for item in _mapping_rows(
                        override.get("properties"),
                        field="compound.row_overrides.properties",
                    )
                }
            )
            reference_values.update(
                {
                    str(item["intent"]): reference_fixture_paths[
                        str(item["target_fixture"])
                    ]
                    for item in _mapping_rows(
                        override.get("references"),
                        field="compound.row_overrides.references",
                    )
                }
            )
        current["sound_settings"] = property_values
        current["reference_targets"] = reference_values
        visible.append(current)
    return visible


def _compound_reference_fixture_paths(
    compound: Mapping[str, Any],
    *,
    scenario_id: str,
    version: str,
) -> dict[str, str]:
    del scenario_id  # fixture names are already globally explicit per case.
    try:
        root = get_codex_version_layout_v3(version).busses_dwu
    except CodexVersionLayoutError as exc:
        raise ImportAssetMaterializationError(str(exc)) from exc
    return {
        _required_string(row.get("key"), field="compound.reference_fixtures.key"):
        root
        + "\\"
        + _required_string(row.get("name"), field="compound.reference_fixtures.name")
        for row in _mapping_rows(
            compound.get("reference_fixtures"),
            field="compound.reference_fixtures",
        )
    }


def _versionize_import_row(
    row: dict[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    for key in ("object_path", "target_path"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith("\\"):
            row[key] = _versionize_wwise_path(value, version=version)
    event = row.get("event")
    if isinstance(event, Mapping):
        row["event"] = dict(event)
    return row


def _versionize_wwise_path(value: str, *, version: str) -> str:
    if version in {"2022.1", "2025.1"}:
        try:
            return get_codex_version_layout_v3(version).translate_2022_path(value)
        except CodexVersionLayoutError as exc:
            raise ImportAssetMaterializationError(str(exc)) from exc
    if version not in _SUPPORTED_VERSIONS:
        raise ImportAssetMaterializationError(
            f"unsupported Wwise version {version!r}"
        )
    return value


def _tab_operation_requests(
    *,
    version: str,
    table_specs: Sequence[Mapping[str, Any]],
    tab_files: Sequence[MaterializedFile],
    import_location: str,
) -> tuple[Mapping[str, Any], ...]:
    tab_by_name = {item.key: item for item in tab_files}
    return tuple(
        _operation_request(
            version,
            "audio.importTabDelimited",
            {
                "import_file": str(
                    tab_by_name[
                        _required_string(table["name"], field="tsv.name")
                    ].path
                ),
                "import_location": {"kind": "path", "value": import_location},
                "import_language": canonical_wwise_language(
                    _required_string(table["language"], field="tsv.language")
                ),
                "import_operation": _required_string(
                    table["import_operation"],
                    field="tsv.import_operation",
                ),
            },
        )
        for table in table_specs
    )


def _materialized_asset_root(materialized: MaterializedImportCase) -> Path:
    if not materialized.source_files:
        raise ImportAssetMaterializationError(
            "materialized compound import has no source files"
        )
    roots = {item.path.parent.parent for item in materialized.source_files}
    if len(roots) != 1:
        raise ImportAssetMaterializationError(
            "materialized compound source files do not share one asset root"
        )
    return next(iter(roots))


def _materialized_api(materialized: MaterializedImportCase) -> str:
    spec = materialized.compound_spec
    if not isinstance(spec, Mapping):
        raise ImportAssetMaterializationError("compound import spec is unavailable")
    api = spec.get("_api")
    if api not in IMPORT_APIS:
        raise ImportAssetMaterializationError(
            "compound import staging lacks an exact API identity"
        )
    return str(api)


def _materialized_asset_spec(
    materialized: MaterializedImportCase,
) -> Mapping[str, Any]:
    spec = materialized.compound_spec
    if not isinstance(spec, Mapping):
        raise ImportAssetMaterializationError("compound import spec is unavailable")
    # The original table definitions are retained next to the staged spec by
    # the materializer because they are needed only when exact live headers
    # become known.
    table_specs = spec.get("_table_specs")
    if not isinstance(table_specs, list):
        raise ImportAssetMaterializationError(
            "compound import staging lacks original table definitions"
        )
    return {"tsv": table_specs}


def _materialized_import_location(materialized: MaterializedImportCase) -> str:
    spec = materialized.compound_spec
    if not isinstance(spec, Mapping):
        raise ImportAssetMaterializationError("compound import spec is unavailable")
    return _required_string(
        spec.get("_import_location"),
        field="compound._import_location",
    )


def _direct_import_operation(materialized: MaterializedImportCase) -> str:
    spec = materialized.compound_spec
    if not isinstance(spec, Mapping):
        raise ImportAssetMaterializationError("compound import spec is unavailable")
    return _required_string(
        spec.get("_audio_import_operation"),
        field="compound._audio_import_operation",
    )


def _safe_inline_relative_path(value: Any, *, field: str) -> str:
    text = _required_string(value, field=field).replace("\\", "/")
    path = Path(text)
    if (
        path.is_absolute()
        or path.suffix.casefold() != ".wav"
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ImportAssetMaterializationError(
            f"{field} must be a contained relative WAV path"
        )
    return "/".join(path.parts)


def _require_scalar(value: Any, *, field: str) -> None:
    if value is None or isinstance(value, (list, Mapping)) or isinstance(value, float):
        raise ImportAssetMaterializationError(
            f"{field} must be a non-null string, integer, or Boolean"
        )


def _tab_scalar(value: Any) -> str:
    _require_scalar(value, field="TSV dynamic value")
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def canonical_wwise_language(value: str) -> str:
    try:
        return CANONICAL_WWISE_LANGUAGE[value]
    except KeyError as exc:
        raise ImportAssetMaterializationError(
            f"import fixture uses an unreviewed language alias: {value!r}"
        ) from exc


def _materialize_sources(
    rows: Any,
    root: Path,
) -> tuple[MaterializedFile, ...]:
    materialized: list[MaterializedFile] = []
    for row in _mapping_rows(rows, field="sources"):
        key = _required_string(row.get("source_key"), field="sources.source_key")
        relative = _safe_relative(row.get("relative_path"), field="sources.relative_path")
        path = root / relative
        presence = _required_string(row.get("presence"), field="sources.presence")
        if presence == "present":
            _write_pcm_wav(
                path,
                duration_ms=_positive_int(row.get("duration_ms"), field="sources.duration_ms"),
                frequency_hz=_positive_int(row.get("frequency_hz"), field="sources.frequency_hz"),
            )
            materialized.append(_file_row(key, path, present=True))
        elif presence == "absent":
            if row.get("duration_ms") is not None or row.get("frequency_hz") is not None:
                raise ImportAssetMaterializationError(
                    f"absent source {key} cannot declare signal fields"
                )
            materialized.append(_file_row(key, path, present=False))
        else:
            raise ImportAssetMaterializationError(
                f"source {key} has unsupported presence {presence!r}"
            )
    _require_unique([item.key for item in materialized], field="source keys")
    return tuple(materialized)


def _materialize_pre_state(
    rows: Any,
    root: Path,
) -> tuple[MaterializedFile, ...]:
    materialized: list[MaterializedFile] = []
    for index, row in enumerate(_mapping_rows(rows, field="pre_state_sources")):
        key = _required_string(
            row.get("media_sha256_key"), field="pre_state_sources.media_sha256_key"
        )
        relative = _safe_relative(
            row.get("relative_path"), field="pre_state_sources.relative_path"
        )
        path = root / relative
        _write_pcm_wav(
            path,
            duration_ms=_positive_int(
                row.get("duration_ms"), field=f"pre_state_sources[{index}].duration_ms"
            ),
            frequency_hz=_positive_int(
                row.get("frequency_hz"), field=f"pre_state_sources[{index}].frequency_hz"
            ),
        )
        materialized.append(_file_row(key, path, present=True))
    _require_unique([item.key for item in materialized], field="pre-state keys")
    return tuple(materialized)


def _materialize_tables(
    tables: Any,
    *,
    rows: Sequence[Mapping[str, Any]],
    source_by_key: Mapping[str, MaterializedFile],
    tab_root: Path,
    inline_base64_by_row: Mapping[str, str] | None = None,
    dynamic_cells_by_row: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[MaterializedFile, ...]:
    inline_base64_by_row = dict(inline_base64_by_row or {})
    dynamic_cells_by_row = {
        key: dict(value)
        for key, value in (dynamic_cells_by_row or {}).items()
    }
    result: list[MaterializedFile] = []
    for table in _mapping_rows(tables, field="tsv"):
        name = _required_string(table.get("name"), field="tsv.name")
        relative = _safe_relative(name, field="tsv.name")
        path = tab_root / relative
        headers = tuple(
            _required_string(value, field="tsv.headers")
            for value in _sequence(table.get("headers"), field="tsv.headers")
        )
        selected = sorted(
            (row for row in rows if row.get("tsv_name") == name),
            key=lambda row: _positive_int(row.get("tsv_row"), field="rows.tsv_row"),
        )
        if len(selected) != table.get("row_count"):
            raise ImportAssetMaterializationError(
                f"{name} row count does not match the reviewed table contract"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(
                handle,
                delimiter="\t",
                quoting=csv.QUOTE_MINIMAL,
                doublequote=True,
                lineterminator="\n",
            )
            writer.writerow(headers)
            for row in selected:
                writer.writerow(
                    [
                        _tab_cell(header, row=row, source_by_key=source_by_key)
                        if not inline_base64_by_row and not dynamic_cells_by_row
                        else _tab_cell(
                            header,
                            row=row,
                            source_by_key=source_by_key,
                            inline_base64=inline_base64_by_row.get(
                                _required_string(
                                    row.get("row_key"),
                                    field="rows.row_key",
                                )
                            ),
                            dynamic_cells=dynamic_cells_by_row.get(
                                _required_string(
                                    row.get("row_key"),
                                    field="rows.row_key",
                                ),
                                {},
                            ),
                        )
                        for header in headers
                    ]
                )
        result.append(_file_row(name, path, present=True))
    _require_unique([item.key for item in result], field="TSV names")
    return tuple(result)


def _tab_cell(
    header: str,
    *,
    row: Mapping[str, Any],
    source_by_key: Mapping[str, MaterializedFile],
    inline_base64: str | None = None,
    dynamic_cells: Mapping[str, str] | None = None,
) -> str:
    dynamic_cells = dynamic_cells or {}
    if header == "Audio File":
        if inline_base64 is not None:
            cell = ""
        else:
            source_key = _required_string(row.get("source_key"), field="rows.source_key")
            try:
                cell = str(source_by_key[source_key].path)
            except KeyError as exc:
                raise ImportAssetMaterializationError(
                    f"TSV row references unknown source {source_key!r}"
                ) from exc
    elif header == "Audio File Base64":
        cell = inline_base64 or ""
    elif header == "Event":
        event = row.get("event")
        cell = (
            ""
            if event is None
            else _required_string(event.get("path"), field="rows.event.path")
        )
    else:
        if header in dynamic_cells:
            cell = dynamic_cells[header]
        elif (
            header.startswith("Property[")
            or header.startswith("Reference[")
        ) and header.endswith("]"):
            # A dynamic column is table-wide, while an individual reviewed
            # row may intentionally leave that setting unset.
            cell = ""
        else:
            key = _HEADER_TO_ROW_KEY.get(header)
            if key is None:
                raise ImportAssetMaterializationError(
                    f"unsupported reviewed TSV header: {header!r}"
                )
            value = row.get(key)
            cell = "" if value is None else str(value)
        if not isinstance(cell, str):
            raise ImportAssetMaterializationError(
                f"TSV {header!r} cell must be a string"
            )
    if any(separator in cell for separator in ("\t", "\r", "\n")):
        raise ImportAssetMaterializationError(
            f"TSV {header!r} cells cannot contain physical row or column separators"
        )
    return cell


def _audio_import_row(
    row: Mapping[str, Any],
    *,
    source_by_key: Mapping[str, MaterializedFile],
) -> dict[str, Any]:
    source_key = _required_string(row.get("source_key"), field="rows.source_key")
    try:
        source = source_by_key[source_key]
    except KeyError as exc:
        raise ImportAssetMaterializationError(
            f"audio.import row references unknown source {source_key!r}"
        ) from exc
    if not source.present:
        raise ImportAssetMaterializationError(
            "audio.import dispatch rows cannot reference intentionally absent sources"
        )
    request: dict[str, Any] = {
        "object_path": _required_string(row.get("object_path"), field="rows.object_path"),
        "audio_file": str(source.path),
        "object_type": _required_string(row.get("object_type"), field="rows.object_type"),
        "import_language": canonical_wwise_language(
            _required_string(row.get("language"), field="rows.language")
        ),
    }
    for source_name, request_name in (
        ("originals_subfolder", "originals_subfolder"),
        ("notes", "notes"),
        ("audio_source_notes", "audio_source_notes"),
    ):
        value = row.get(source_name)
        if value is not None:
            if request_name == "originals_subfolder":
                try:
                    request[request_name] = normalize_originals_subfolder(
                        value,
                        field="rows.originals_subfolder",
                    )
                except ImportContractError as exc:
                    raise ImportAssetMaterializationError(str(exc)) from exc
            else:
                request[request_name] = str(value)
    event = row.get("event")
    if event is not None:
        request["event"] = {
            "path": _required_string(event.get("path"), field="rows.event.path"),
            "action": _required_string(event.get("action"), field="rows.event.action"),
        }
    return request


def _operation_request(
    version: str,
    operation: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def _write_pcm_wav(path: Path, *, duration_ms: int, frequency_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    frame_count = sample_rate * duration_ms // 1000
    if frame_count < 1:
        raise ImportAssetMaterializationError("deterministic WAV must contain at least one frame")
    with path.open("xb") as raw:
        with wave.open(raw, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            chunk = bytearray()
            for frame in range(frame_count):
                sample = int(
                    12_000
                    * math.sin(2.0 * math.pi * frequency_hz * frame / sample_rate)
                )
                chunk.extend(struct.pack("<h", sample))
            handle.writeframes(bytes(chunk))


def _file_row(key: str, path: Path, *, present: bool) -> MaterializedFile:
    if present:
        data = path.read_bytes()
        return MaterializedFile(
            key=key,
            path=path.resolve(strict=True),
            present=True,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
    if path.exists() or path.is_symlink():
        raise ImportAssetMaterializationError(
            f"intentionally absent input unexpectedly exists: {path}"
        )
    return MaterializedFile(
        key=key,
        path=path.resolve(strict=False),
        present=False,
        size=None,
        sha256=None,
    )


def _visible_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _mapping_rows(value: Any, *, field: str) -> tuple[Mapping[str, Any], ...]:
    rows = _sequence(value, field=field)
    if any(not isinstance(row, Mapping) for row in rows):
        raise ImportAssetMaterializationError(f"{field} must contain JSON objects")
    return tuple(rows)  # type: ignore[return-value]


def _sequence(value: Any, *, field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ImportAssetMaterializationError(f"{field} must be a JSON array")
    return tuple(value)


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ImportAssetMaterializationError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ImportAssetMaterializationError(f"{field} must be a positive integer")
    return value


def _safe_relative(value: Any, *, field: str) -> Path:
    text = _required_string(value, field=field)
    path = Path(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ImportAssetMaterializationError(f"{field} must be a contained relative path")
    return path


def _require_unique(values: Sequence[str], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise ImportAssetMaterializationError(f"{field} must be unique")


__all__ = [
    "BoundImportMetadata",
    "CANONICAL_WWISE_LANGUAGE",
    "COMPOUND_IMPORT_CONTRACT",
    "ImportAssetMaterializationError",
    "MaterializedFile",
    "MaterializedImportCase",
    "bind_import_live_metadata",
    "bound_import_metadata_tokens",
    "canonical_wwise_language",
    "materialize_import_case",
]

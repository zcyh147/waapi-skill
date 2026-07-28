"""Versioned, compact object-type metadata catalogs.

The packaged catalogs are discovery indexes, not live mutation authority.  They
let callers resolve common Wwise object type names without issuing one
``getTypes`` request per task.  A live mutation still has to validate the
selected type and any property metadata against the connected Wwise session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256
from .versions import SUPPORTED_WWISE_VERSION_KEYS, WWISE_VERSION_CONTRACTS


GET_TYPES_URI = "ak.wwise.core.object.getTypes"
OBJECT_TYPE_CATALOG_CONTRACT = "waapi-skill.object-type-catalog/v1"
OBJECT_TYPE_CATALOG_FILENAME = "object-types.json"
METADATA_CATALOG_ROOT = (
    Path(__file__).resolve().parents[1] / "resources" / "metadata"
)
MAX_OBJECT_TYPE_SEARCH_RESULTS = 100
MAX_OBJECT_TYPE_QUERY_CHARS = 256


class MetadataCatalogError(ValueError):
    """Raised when a packaged metadata catalog violates its contract."""


class MetadataCatalogMissingError(FileNotFoundError):
    """Raised when a supported Wwise version has no packaged catalog."""

    def __init__(self, version: str, path: Path) -> None:
        self.version = version
        self.path = path
        super().__init__(
            f"Object-type metadata catalog is missing for Wwise {version}: {path}"
        )


@dataclass(frozen=True, slots=True)
class ObjectTypeCatalogRecord:
    """One compact row from ``ak.wwise.core.object.getTypes``."""

    class_id: int
    name: str
    type: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "classId": self.class_id,
            "name": self.name,
            "type": self.type,
        }


@dataclass(frozen=True, slots=True)
class ObjectTypeCatalog:
    """Validated in-memory object-type index for one Wwise version."""

    version: str
    wwise_build: str
    source_result_sha256: str
    resource_sha256: str
    records: tuple[ObjectTypeCatalogRecord, ...]
    _by_class_id: Mapping[int, ObjectTypeCatalogRecord] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _by_folded_name: Mapping[str, ObjectTypeCatalogRecord] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_by_class_id",
            {record.class_id: record for record in self.records},
        )
        object.__setattr__(
            self,
            "_by_folded_name",
            {record.name.casefold(): record for record in self.records},
        )

    @property
    def row_count(self) -> int:
        return len(self.records)

    def by_class_id(self, class_id: int) -> ObjectTypeCatalogRecord | None:
        """Return one exact class-id match without scanning the catalog."""

        if not _is_uint32(class_id):
            raise MetadataCatalogError("class_id must be a uint32 integer")
        return self._by_class_id.get(class_id)

    def by_name(self, name: str) -> ObjectTypeCatalogRecord | None:
        """Return one case-insensitive exact type-name match."""

        normalized = _required_text(name, field_name="name")
        return self._by_folded_name.get(normalized.casefold())

    def search(
        self,
        query: str | None = None,
        *,
        object_type: str | None = None,
        limit: int = 20,
    ) -> tuple[ObjectTypeCatalogRecord, ...]:
        """Return a small, deterministic keyword-filtered result set.

        Query tokens must all occur in either the Wwise name or its broad
        ``type`` category.  Matching also uses an alphanumeric-folded form, so
        ``"audio source"`` can find a CamelCase name such as
        ``AudioFileSource`` without loading the full catalog into an LLM
        context.
        """

        _validate_search_limit(limit)
        normalized_query = ""
        if query is not None:
            normalized_query = _required_text(
                query,
                field_name="query",
                max_chars=MAX_OBJECT_TYPE_QUERY_CHARS,
            )
        normalized_type = (
            _required_text(object_type, field_name="object_type").casefold()
            if object_type is not None
            else None
        )
        tokens = tuple(
            token
            for token in (
                _alphanumeric_fold(part)
                for part in normalized_query.casefold().split()
            )
            if token
        )
        compact_query = _alphanumeric_fold(normalized_query)
        candidates: list[tuple[tuple[Any, ...], ObjectTypeCatalogRecord]] = []
        for record in self.records:
            if (
                normalized_type is not None
                and record.type.casefold() != normalized_type
            ):
                continue
            name_folded = record.name.casefold()
            type_folded = record.type.casefold()
            compact_name = _alphanumeric_fold(name_folded)
            compact_type = _alphanumeric_fold(type_folded)
            haystacks = (compact_name, compact_type)
            if tokens and not all(
                any(token in haystack for haystack in haystacks)
                for token in tokens
            ):
                continue
            rank = _search_rank(
                record,
                query_folded=normalized_query.casefold(),
                compact_query=compact_query,
                compact_name=compact_name,
                tokens=tokens,
            )
            candidates.append((rank, record))
        candidates.sort(key=lambda item: item[0])
        return tuple(record for _, record in candidates[:limit])

    def as_summary(self) -> dict[str, Any]:
        """Return bounded catalog facts suitable for diagnostics."""

        return {
            "contract": OBJECT_TYPE_CATALOG_CONTRACT,
            "resource_sha256": self.resource_sha256,
            "row_count": self.row_count,
            "wwise_build": self.wwise_build,
            "wwise_version_target": self.version,
        }


@dataclass(slots=True)
class ObjectTypeCatalogStore:
    """Load and memoize versioned object-type catalogs from packaged files."""

    root: Path = METADATA_CATALOG_ROOT
    _loaded: dict[str, ObjectTypeCatalog] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def load(self, version: str) -> ObjectTypeCatalog:
        _require_supported_version(version)
        cached = self._loaded.get(version)
        if cached is not None:
            return cached
        path = self.root / version / OBJECT_TYPE_CATALOG_FILENAME
        if not path.is_file():
            raise MetadataCatalogMissingError(version, path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MetadataCatalogError(
                f"Could not read object-type catalog for Wwise {version}: {exc}"
            ) from exc
        catalog = parse_object_type_catalog(payload, expected_version=version)
        self._loaded[version] = catalog
        return catalog

    def clear(self) -> None:
        self._loaded.clear()


def build_object_type_catalog_payload(
    source_payload: Mapping[str, Any],
    *,
    version: str,
    wwise_build: str | None = None,
) -> dict[str, Any]:
    """Build deterministic packaged content from one real ``getTypes`` result.

    ``source_payload`` may be either the direct WAAPI response or a dispatcher
    evidence envelope containing it under ``result``.  Local paths and other
    campaign-only fields are never copied into the resource.
    """

    _require_supported_version(version)
    build = wwise_build or WWISE_VERSION_CONTRACTS[version].build
    if build != WWISE_VERSION_CONTRACTS[version].build:
        raise MetadataCatalogError(
            f"Wwise build {build!r} does not match the pinned {version} build "
            f"{WWISE_VERSION_CONTRACTS[version].build!r}"
        )
    if not isinstance(source_payload, Mapping):
        raise MetadataCatalogError("getTypes source payload must be an object")
    source_api = source_payload.get("api")
    if source_api is not None and source_api != GET_TYPES_URI:
        raise MetadataCatalogError(
            f"Expected {GET_TYPES_URI!r} evidence, received {source_api!r}"
        )
    source_version = source_payload.get("version")
    if source_version is not None and source_version != version:
        raise MetadataCatalogError(
            f"Evidence version {source_version!r} does not match {version!r}"
        )
    if "ok" in source_payload and source_payload.get("ok") is not True:
        raise MetadataCatalogError("getTypes evidence must record ok=true")
    result = source_payload.get("result", source_payload)
    if not isinstance(result, Mapping):
        raise MetadataCatalogError("getTypes result must be an object")
    rows = result.get("return")
    if not isinstance(rows, list):
        raise MetadataCatalogError("getTypes result.return must be an array")
    records = tuple(
        _record_from_mapping(row, row_index=index, allow_extra=True)
        for index, row in enumerate(rows)
    )
    records = _validate_and_sort_records(records)
    compact_rows = [record.as_dict() for record in records]
    source_result_sha256 = canonical_sha256({"return": compact_rows})
    resource_body = {
        "contract": OBJECT_TYPE_CATALOG_CONTRACT,
        "types": compact_rows,
        "wwise_build": build,
        "wwise_version_target": version,
    }
    resource_sha256 = canonical_sha256(resource_body)
    return {
        "metadata": {
            "contract": OBJECT_TYPE_CATALOG_CONTRACT,
            "generator": (
                "tests.maintenance.build_object_type_catalogs"
            ),
            "inventory_source": "live-getTypes",
            "resource_sha256": resource_sha256,
            "row_count": len(compact_rows),
            "source_result_sha256": source_result_sha256,
            "source_uri": GET_TYPES_URI,
            "wwise_build": build,
            "wwise_version_target": version,
        },
        "types": compact_rows,
    }


def parse_object_type_catalog(
    payload: Mapping[str, Any],
    *,
    expected_version: str | None = None,
) -> ObjectTypeCatalog:
    """Validate one catalog payload and return its searchable representation."""

    if not isinstance(payload, Mapping):
        raise MetadataCatalogError("Object-type catalog must be a JSON object")
    metadata = payload.get("metadata")
    rows = payload.get("types")
    if not isinstance(metadata, Mapping):
        raise MetadataCatalogError(
            "Object-type catalog metadata must be an object"
        )
    if not isinstance(rows, list):
        raise MetadataCatalogError("Object-type catalog types must be an array")
    contract = metadata.get("contract")
    if contract != OBJECT_TYPE_CATALOG_CONTRACT:
        raise MetadataCatalogError(
            f"Unsupported object-type catalog contract: {contract!r}"
        )
    version = metadata.get("wwise_version_target")
    if not isinstance(version, str):
        raise MetadataCatalogError(
            "Object-type catalog version must be a string"
        )
    _require_supported_version(version)
    if expected_version is not None and version != expected_version:
        raise MetadataCatalogError(
            f"Object-type catalog version {version!r} does not match "
            f"{expected_version!r}"
        )
    build = metadata.get("wwise_build")
    if build != WWISE_VERSION_CONTRACTS[version].build:
        raise MetadataCatalogError(
            f"Object-type catalog build {build!r} does not match pinned "
            f"Wwise {version}"
        )
    records = tuple(
        _record_from_mapping(row, row_index=index, allow_extra=False)
        for index, row in enumerate(rows)
    )
    records = _validate_and_sort_records(records, require_sorted=True)
    row_count = metadata.get("row_count")
    if row_count != len(records):
        raise MetadataCatalogError(
            f"Object-type catalog row_count {row_count!r} does not match "
            f"{len(records)} rows"
        )
    source_result_sha256 = _require_sha256(
        metadata.get("source_result_sha256"),
        field_name="source_result_sha256",
    )
    resource_sha256 = _require_sha256(
        metadata.get("resource_sha256"),
        field_name="resource_sha256",
    )
    compact_rows = [record.as_dict() for record in records]
    expected_source_digest = canonical_sha256({"return": compact_rows})
    if source_result_sha256 != expected_source_digest:
        raise MetadataCatalogError(
            "Object-type catalog source_result_sha256 does not match its "
            "normalized getTypes rows"
        )
    expected_digest = canonical_sha256(
        {
            "contract": OBJECT_TYPE_CATALOG_CONTRACT,
            "types": compact_rows,
            "wwise_build": build,
            "wwise_version_target": version,
        }
    )
    if resource_sha256 != expected_digest:
        raise MetadataCatalogError(
            "Object-type catalog resource_sha256 does not match its content"
        )
    return ObjectTypeCatalog(
        version=version,
        wwise_build=build,
        source_result_sha256=source_result_sha256,
        resource_sha256=resource_sha256,
        records=records,
    )


def _record_from_mapping(
    row: Any,
    *,
    row_index: int,
    allow_extra: bool,
) -> ObjectTypeCatalogRecord:
    if not isinstance(row, Mapping):
        raise MetadataCatalogError(
            f"Object-type catalog row {row_index} must be an object"
        )
    required = {"classId", "name", "type"}
    missing = required.difference(row)
    if missing:
        raise MetadataCatalogError(
            f"Object-type catalog row {row_index} is missing "
            f"{', '.join(sorted(missing))}"
        )
    if not allow_extra and set(row) != required:
        raise MetadataCatalogError(
            f"Object-type catalog row {row_index} contains unsupported fields"
        )
    class_id = row.get("classId")
    if not _is_uint32(class_id):
        raise MetadataCatalogError(
            f"Object-type catalog row {row_index} classId must be uint32"
        )
    name = _required_text(row.get("name"), field_name=f"types[{row_index}].name")
    object_type = _required_text(
        row.get("type"),
        field_name=f"types[{row_index}].type",
    )
    return ObjectTypeCatalogRecord(
        class_id=class_id,
        name=name,
        type=object_type,
    )


def _validate_and_sort_records(
    records: Sequence[ObjectTypeCatalogRecord],
    *,
    require_sorted: bool = False,
) -> tuple[ObjectTypeCatalogRecord, ...]:
    class_ids: set[int] = set()
    folded_names: set[str] = set()
    for record in records:
        if record.class_id in class_ids:
            raise MetadataCatalogError(
                f"Duplicate object-type classId: {record.class_id}"
            )
        folded_name = record.name.casefold()
        if folded_name in folded_names:
            raise MetadataCatalogError(
                f"Duplicate object-type name: {record.name!r}"
            )
        class_ids.add(record.class_id)
        folded_names.add(folded_name)
    sorted_records = tuple(sorted(records, key=_record_sort_key))
    if require_sorted and tuple(records) != sorted_records:
        raise MetadataCatalogError(
            "Object-type catalog rows are not in deterministic order"
        )
    return sorted_records


def _record_sort_key(record: ObjectTypeCatalogRecord) -> tuple[Any, ...]:
    return (record.name.casefold(), record.name, record.type.casefold(), record.class_id)


def _search_rank(
    record: ObjectTypeCatalogRecord,
    *,
    query_folded: str,
    compact_query: str,
    compact_name: str,
    tokens: tuple[str, ...],
) -> tuple[Any, ...]:
    name_folded = record.name.casefold()
    if query_folded and name_folded == query_folded:
        match_class = 0
    elif compact_query and compact_name == compact_query:
        match_class = 1
    elif query_folded and name_folded.startswith(query_folded):
        match_class = 2
    elif compact_query and compact_name.startswith(compact_query):
        match_class = 3
    elif tokens and all(token in compact_name for token in tokens):
        match_class = 4
    elif tokens:
        match_class = 5
    else:
        match_class = 6
    positions = sum(
        min(
            (
                position
                for position in (
                    compact_name.find(token),
                    _alphanumeric_fold(record.type).find(token),
                )
                if position >= 0
            ),
            default=10_000,
        )
        for token in tokens
    )
    return (
        match_class,
        positions,
        len(record.name),
        record.name.casefold(),
        record.class_id,
    )


def _validate_search_limit(limit: int) -> None:
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_OBJECT_TYPE_SEARCH_RESULTS
    ):
        raise MetadataCatalogError(
            f"limit must be an integer from 1 to "
            f"{MAX_OBJECT_TYPE_SEARCH_RESULTS}"
        )


def _required_text(
    value: Any,
    *,
    field_name: str,
    max_chars: int = 512,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value) > max_chars
    ):
        raise MetadataCatalogError(
            f"{field_name} must be a non-empty string no longer than "
            f"{max_chars} characters"
        )
    return value.strip()


def _require_supported_version(version: str) -> None:
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise MetadataCatalogError(
            f"Unsupported Wwise version {version!r}; supported versions: "
            f"{', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )


def _is_uint32(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 0xFFFFFFFF
    )


def _require_sha256(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise MetadataCatalogError(
            f"Object-type catalog {field_name} must be a lowercase SHA-256"
        )
    return value


def _alphanumeric_fold(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


__all__ = [
    "GET_TYPES_URI",
    "MAX_OBJECT_TYPE_QUERY_CHARS",
    "MAX_OBJECT_TYPE_SEARCH_RESULTS",
    "METADATA_CATALOG_ROOT",
    "MetadataCatalogError",
    "MetadataCatalogMissingError",
    "OBJECT_TYPE_CATALOG_CONTRACT",
    "OBJECT_TYPE_CATALOG_FILENAME",
    "ObjectTypeCatalog",
    "ObjectTypeCatalogRecord",
    "ObjectTypeCatalogStore",
    "build_object_type_catalog_payload",
    "parse_object_type_catalog",
]

"""Deterministic reflection manifests for Wwise WAAPI resources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .versions import is_explicit_fail_closed_version  # pyright: ignore[reportMissingImports]


GET_FUNCTIONS_URI = "ak.wwise.waapi.getFunctions"
GET_TOPICS_URI = "ak.wwise.waapi.getTopics"
GET_SCHEMA_URI = "ak.wwise.waapi.getSchema"
DEFAULT_INVENTORY_SOURCE = "live-reflection"
LOCAL_PATH_PATTERN = re.compile(
    r"(?:/(?:Applications|Users|Volumes|private|tmp)/[^\n\r\t\"'<>]+)|(?:[A-Za-z]:\\[^\n\r\t\"'<>]+)"
)


class WaapiCaller(Protocol):
    """Minimal injectable WAAPI caller surface used by manifest generation."""

    def call(self, uri: str, *args: Any, **kwargs: Any) -> Any:
        """Call a WAAPI URI and return decoded JSON-like data."""


@dataclass(slots=True, frozen=True)
class ReflectionEntry:
    """Normalized function/topic inventory entry sorted by WAAPI URI."""

    uri: str
    reflection: dict[str, Any]


@dataclass(slots=True, frozen=True)
class SchemaFetchResult:
    """Schema fetch outcome for one reflected WAAPI URI."""

    uri: str
    status: str
    schema: Any | None = None
    error_type: str | None = None
    message: str | None = None

    def as_manifest_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"status": self.status, "uri": self.uri}
        if self.status == "ok":
            entry["schema"] = self.schema
        else:
            entry["error_type"] = self.error_type or "SchemaFetchError"
            entry["message"] = self.message or "schema fetch failed"
        return entry


@dataclass(slots=True)
class WaapiReflectionClient:
    """Collect functions, topics, and schemas from an injectable WAAPI caller."""

    caller: WaapiCaller

    def get_functions(self) -> list[ReflectionEntry]:
        result = self.caller.call(GET_FUNCTIONS_URI)
        return _extract_entries(result, ("functions", "return"))

    def get_topics(self) -> list[ReflectionEntry]:
        result = self.caller.call(GET_TOPICS_URI)
        return _extract_entries(result, ("topics", "return"))

    def get_schema(self, uri: str) -> SchemaFetchResult:
        try:
            schema = self.caller.call(GET_SCHEMA_URI, {"uri": uri})
        except Exception as exc:  # noqa: BLE001 - failures are evidence in manifests
            return SchemaFetchResult(
                uri=uri,
                status="error",
                error_type=type(exc).__name__,
                message=str(exc),
            )
        return SchemaFetchResult(uri=uri, status="ok", schema=_sanitize_for_manifest(schema))


@dataclass(slots=True, frozen=True)
class ManifestAudit:
    """Count summary proving reflected inventory matches generated manifests."""

    reflected_function_count: int
    manifest_function_count: int
    reflected_topic_count: int
    manifest_topic_count: int
    schema_count: int
    schema_failure_count: int

    @property
    def counts_match(self) -> bool:
        return (
            self.reflected_function_count == self.manifest_function_count
            and self.reflected_topic_count == self.manifest_topic_count
        )

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "counts_match": self.counts_match,
            "manifest_function_count": self.manifest_function_count,
            "manifest_topic_count": self.manifest_topic_count,
            "reflected_function_count": self.reflected_function_count,
            "reflected_topic_count": self.reflected_topic_count,
            "schema_count": self.schema_count,
            "schema_failure_count": self.schema_failure_count,
        }


@dataclass(slots=True)
class ReflectionManifest:
    """In-memory deterministic manifest bundle for a Wwise version."""

    version: str
    metadata: dict[str, Any]
    functions: list[dict[str, Any]]
    topics: list[dict[str, Any]]
    schemas: list[dict[str, Any]]
    audit: ManifestAudit

    def files(self) -> dict[str, dict[str, Any]]:
        return {
            "manifest.json": {
                "audit": self.audit.as_dict(),
                "metadata": self.metadata,
            },
            "functions.json": {
                "metadata": self.metadata,
                "functions": self.functions,
            },
            "topics.json": {
                "metadata": self.metadata,
                "topics": self.topics,
            },
            "schemas.json": {
                "metadata": self.metadata,
                "schemas": self.schemas,
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "audit": self.audit.as_dict(),
            "functions": self.functions,
            "metadata": self.metadata,
            "schemas": self.schemas,
            "topics": self.topics,
        }


@dataclass(slots=True)
class ReflectionManifestBuilder:
    """Build sorted, path-scrubbed manifests from WAAPI reflection."""

    reflection_client: WaapiReflectionClient
    version: str = "2022.1"
    inventory_source: str = DEFAULT_INVENTORY_SOURCE
    wwise_build: str | None = None

    def build(self) -> ReflectionManifest:
        functions = self.reflection_client.get_functions()
        topics = self.reflection_client.get_topics()
        all_uris = sorted({entry.uri for entry in functions + topics})
        schema_results = [self.reflection_client.get_schema(uri) for uri in all_uris]
        function_entries = [_entry_to_manifest(entry, "function") for entry in functions]
        topic_entries = [_entry_to_manifest(entry, "topic") for entry in topics]
        schema_entries = [result.as_manifest_entry() for result in schema_results]
        failure_count = sum(1 for result in schema_results if result.status != "ok")
        metadata = {
            "generator": "wwise_waapi.manifest.ReflectionManifestBuilder",
            "inventory_source": self.inventory_source,
            "schema_source_uri": GET_SCHEMA_URI,
            "schema_source_uris": [GET_SCHEMA_URI],
            "source_uris": [GET_FUNCTIONS_URI, GET_TOPICS_URI, GET_SCHEMA_URI],
            "wwise_build": self.wwise_build or "unknown",
            "wwise_version_target": self.version,
        }
        audit = ManifestAudit(
            reflected_function_count=len(functions),
            manifest_function_count=len(function_entries),
            reflected_topic_count=len(topics),
            manifest_topic_count=len(topic_entries),
            schema_count=len(schema_entries),
            schema_failure_count=failure_count,
        )
        return ReflectionManifest(
            version=self.version,
            metadata=metadata,
            functions=function_entries,
            topics=topic_entries,
            schemas=schema_entries,
            audit=audit,
        )


@dataclass(slots=True, frozen=True)
class DeterministicJsonWriter:
    """Serialize JSON resources with stable bytes across runs."""

    indent: int = 2

    def dumps(self, payload: Mapping[str, Any]) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=self.indent,
            sort_keys=True,
            separators=(",", ": "),
        ) + "\n"

    def write(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(payload), encoding="utf-8")


class ManifestResourceMissingError(FileNotFoundError):
    """Raised when an explicit version resource is missing and fallback is forbidden."""

    def __init__(self, version: str, path: Path) -> None:
        self.version = version
        self.path = path
        super().__init__(f"Manifest resource is missing for Wwise {version}: {path}")


@dataclass(slots=True)
class ManifestStore:
    """Filesystem-backed manifest store with legacy in-memory helpers."""

    root: Path | None = None
    writer: DeterministicJsonWriter = field(default_factory=DeterministicJsonWriter)
    versions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def load(self, version: str) -> dict[str, Any]:
        if self.root is None:
            return self.versions.get(version, {})
        version_dir = self.root / version
        manifest_path = version_dir / "manifest.json"
        if not manifest_path.exists():
            if is_explicit_fail_closed_version(version):
                raise ManifestResourceMissingError(version, manifest_path)
            return self.versions.get(version, {})
        manifest = _read_json(manifest_path)
        for name, key in (("functions.json", "functions"), ("topics.json", "topics"), ("schemas.json", "schemas")):
            path = version_dir / name
            if path.exists():
                manifest[key] = _read_json(path).get(key, [])
            elif is_explicit_fail_closed_version(version):
                raise ManifestResourceMissingError(version, path)
        return manifest

    def record(self, version: str, manifest: dict[str, Any]) -> None:
        self.versions[version] = manifest

    def write_manifest(self, manifest: ReflectionManifest) -> list[Path]:
        if self.root is None:
            self.versions[manifest.version] = manifest.as_dict()
            return []
        written: list[Path] = []
        for filename, payload in manifest.files().items():
            path = self.root / manifest.version / filename
            self.writer.write(path, payload)
            written.append(path)
        self.versions[manifest.version] = manifest.as_dict()
        return written

    def ensure_placeholder_versions(self, versions: list[str] | tuple[str, ...]) -> list[Path]:
        if self.root is None:
            return []
        written: list[Path] = []
        for version in versions:
            path = self.root / version / ".gitkeep"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("", encoding="utf-8")
            written.append(path)
        return written


def build_manifest_from_caller(
    caller: WaapiCaller,
    *,
    version: str = "2022.1",
    inventory_source: str = DEFAULT_INVENTORY_SOURCE,
    wwise_build: str | None = None,
) -> ReflectionManifest:
    """Convenience entry point for scripts/tests that already own a WAAPI caller."""

    client = WaapiReflectionClient(caller)
    return ReflectionManifestBuilder(
        client,
        version=version,
        inventory_source=inventory_source,
        wwise_build=wwise_build,
    ).build()


def audit_manifest(manifest: Mapping[str, Any]) -> ManifestAudit:
    """Recompute manifest counts from a loaded manifest dictionary."""

    functions = list(manifest.get("functions", []))
    topics = list(manifest.get("topics", []))
    schemas = list(manifest.get("schemas", []))
    audit = dict(manifest.get("audit", {}))
    return ManifestAudit(
        reflected_function_count=int(audit.get("reflected_function_count", len(functions))),
        manifest_function_count=len(functions),
        reflected_topic_count=int(audit.get("reflected_topic_count", len(topics))),
        manifest_topic_count=len(topics),
        schema_count=len(schemas),
        schema_failure_count=sum(1 for schema in schemas if schema.get("status") != "ok"),
    )


def _entry_to_manifest(entry: ReflectionEntry, entry_type: str) -> dict[str, Any]:
    return {
        "reflection": _sanitize_for_manifest(entry.reflection),
        "type": entry_type,
        "uri": entry.uri,
    }


def _extract_entries(result: Any, candidate_keys: tuple[str, ...]) -> list[ReflectionEntry]:
    raw_entries = _select_inventory_list(result, candidate_keys)
    entries = [_normalize_entry(item) for item in raw_entries]
    unique: dict[str, ReflectionEntry] = {entry.uri: entry for entry in entries}
    return [unique[uri] for uri in sorted(unique)]


def _select_inventory_list(result: Any, candidate_keys: tuple[str, ...]) -> list[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in candidate_keys:
            value = result.get(key)
            if isinstance(value, list):
                return value
        for value in result.values():
            if isinstance(value, list):
                return value
    raise ValueError(f"WAAPI reflection response did not include a list: {result!r}")


def _normalize_entry(item: Any) -> ReflectionEntry:
    if isinstance(item, str):
        uri = item
        reflection: dict[str, Any] = {"uri": item}
    elif isinstance(item, dict):
        uri_value = item.get("uri") or item.get("name")
        if not isinstance(uri_value, str) or not uri_value:
            raise ValueError(f"Reflection entry is missing a URI: {item!r}")
        uri = uri_value
        reflection = dict(item)
        reflection["uri"] = uri
    else:
        raise ValueError(f"Unsupported reflection entry: {item!r}")
    return ReflectionEntry(uri=uri, reflection=_sanitize_for_manifest(reflection))


def _sanitize_for_manifest(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_for_manifest(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sanitize_for_manifest(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_manifest(item) for item in value]
    if isinstance(value, str):
        if LOCAL_PATH_PATTERN.search(value):
            return LOCAL_PATH_PATTERN.sub("<local-path-redacted>", value)
        return value
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

"""Generate deterministic API coverage resources for reflected Wwise WAAPI inventory."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.deferred_registry import ApiClassifier, DeferredRegistry  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import DESTRUCTIVE_TOKENS  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import DeterministicJsonWriter, ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import DEFAULT_WAQL_REFERENCE, WAQL_API_URI, require_waql_helper_generation  # pyright: ignore[reportMissingImports]

DEFAULT_WWISE_VERSION = "2022.1"
SUPPORT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = Path(__file__).resolve().parents[3] / "skills" / "waapi-skill"
DEFAULT_MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
DEFAULT_COVERAGE_ROOT = SUPPORT_ROOT / "resources" / "capabilities"
DEFAULT_DEFERRED_ROOT = SKILL_ROOT / "resources" / "deferred"
DEFAULT_EVIDENCE_PATH = Path(".sisyphus/evidence/task-7-api-coverage-summary.json")

SAFE_FAKE_ROUTE_CATEGORIES = frozenset(
    {
        "core",
        "core.audioSourcePeaks",
        "core.log",
        "core.object",
        "core.profiler",
        "core.remote",
        "core.soundbank",
        "core.switchContainer",
        "core.transport",
        "waapi",
    }
)
UNSAFE_DEFERRED_CATEGORIES = frozenset({"soundengine", "ui", "ui.commands", "ui.project", "debug", "cli"})


@dataclass(slots=True, frozen=True)
class CoverageSummary:
    """Count summary written as Task 7 evidence."""

    version: str
    total_functions: int
    total_topics: int
    implemented: int
    safe_tested: int
    live_tested: int
    deferred: int
    destructive_opt_in: int
    inventory_covered_count: int
    behavioral_covered_count: int
    live_behavioral_covered_count: int
    substitute_covered_count: int
    deferred_count: int
    excluded_count: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "deferred": self.deferred,
            "destructive_opt_in": self.destructive_opt_in,
            "behavioral_covered_count": self.behavioral_covered_count,
            "deferred_count": self.deferred_count,
            "excluded_count": self.excluded_count,
            "implemented": self.implemented,
            "inventory_covered_count": self.inventory_covered_count,
            "live_behavioral_covered_count": self.live_behavioral_covered_count,
            "live_tested": self.live_tested,
            "safe_tested": self.safe_tested,
            "substitute_covered_count": self.substitute_covered_count,
            "total_functions": self.total_functions,
            "total_topics": self.total_topics,
            "version": self.version,
        }


@dataclass(slots=True)
class CoverageResource:
    """Generated coverage resource payload plus summary counts."""

    version: str
    metadata: dict[str, Any]
    entries: list[dict[str, Any]]
    summary: CoverageSummary

    def as_dict(self) -> dict[str, Any]:
        return {"coverage": self.entries, "metadata": self.metadata, "summary": self.summary.as_dict()}


@dataclass(slots=True)
class ApiCoverageBuilder:
    """Build one coverage entry for every reflected function/topic URI."""

    manifest_store: ManifestStore = field(default_factory=lambda: ManifestStore(root=DEFAULT_MANIFEST_ROOT))
    deferred_registry: DeferredRegistry | None = None
    classifier: ApiClassifier = field(default_factory=ApiClassifier)
    waql_reference_path: Path = DEFAULT_WAQL_REFERENCE

    def build(self, version: str = DEFAULT_WWISE_VERSION) -> CoverageResource:
        manifest = self._manifest(version)
        deferred_registry = self.deferred_registry or DeferredRegistry.load_default(version)
        schemas = self._schemas_by_uri(manifest)
        waql_reference_path = self._waql_reference_path(version)
        waql_uris = set(require_waql_helper_generation(manifest, waql_reference_path))
        entries = [
            self._entry(payload, "function", version, schemas, waql_uris, deferred_registry)
            for payload in self._section(manifest, "functions")
        ]
        entries.extend(
            self._entry(payload, "topic", version, schemas, waql_uris, deferred_registry)
            for payload in self._section(manifest, "topics")
        )
        entries = sorted(entries, key=lambda entry: entry["uri"])
        self._validate_exact_coverage(manifest, entries)
        summary = self._summary(version, entries, manifest)
        return CoverageResource(version=version, metadata=self._metadata(version), entries=entries, summary=summary)


    def _waql_reference_path(self, version: str) -> Path:
        if self.waql_reference_path != DEFAULT_WAQL_REFERENCE:
            return self.waql_reference_path
        return SKILL_ROOT / DEFAULT_WAQL_REFERENCE


    def _manifest(self, version: str) -> dict[str, Any]:
        manifest = self.manifest_store.load(version)
        if self.manifest_store.root is None and version not in self.manifest_store.versions:
            return ManifestStore(root=DEFAULT_MANIFEST_ROOT).load(version)
        return manifest

    def _entry(
        self,
        payload: Mapping[str, Any],
        item_type: str,
        version: str,
        schemas: Mapping[str, Mapping[str, Any]],
        waql_uris: set[str],
        deferred_registry: DeferredRegistry,
    ) -> dict[str, Any]:
        uri = self._uri(payload)
        classification = self.classifier.classify(uri, item_type)
        schema_entry = schemas.get(uri, {})
        schema = schema_entry.get("schema") if isinstance(schema_entry.get("schema"), Mapping) else {}
        deferred = self._is_deferred(uri, item_type, classification.category, classification.risk_level)
        route = self._route(uri, item_type, deferred)
        entry: dict[str, Any] = {
            "behavioral_evidence": self._behavioral_evidence(uri, item_type, deferred, version),
            "category": classification.category,
            "deferred": self._deferred_payload(
                uri,
                deferred,
                deferred_registry,
                version,
                item_type,
                classification.category,
                classification.risk_level,
            ),
            "destructive_opt_in": self._requires_destructive_opt_in(uri, item_type, classification.risk_level),
            "item_type": item_type,
            "risk_level": classification.risk_level,
            "route": route,
            "safety": self._safety(uri, item_type, classification.category, classification.risk_level, deferred),
            "schema_mapping": self._schema_mapping(uri, schema_entry, schema, version),
            "schema_status": str(schema_entry.get("status", "missing")),
            "test_status": "deferred-with-substitute-test" if deferred else "fake-route-tested",
            "uri": uri,
            "usage_guidance": self._usage_guidance(uri, item_type, classification.category, deferred, uri in waql_uris, version),
            "version": version,
        }
        return entry

    def _is_deferred(self, uri: str, item_type: str, category: str, risk_level: str) -> bool:
        if item_type == "topic":
            return True
        if self._requires_destructive_opt_in(uri, item_type, risk_level):
            return True
        if category in UNSAFE_DEFERRED_CATEGORIES or category.startswith("ui"):
            return True
        if category == "soundengine" or category.startswith("soundengine"):
            return True
        return not (risk_level == "low" and category in SAFE_FAKE_ROUTE_CATEGORIES)

    def _requires_destructive_opt_in(self, uri: str, item_type: str, risk_level: str) -> bool:
        if item_type != "function":
            return False
        operation = uri.rsplit(".", 1)[-1].lower()
        return risk_level == "high" or any(operation.startswith(token) for token in DESTRUCTIVE_TOKENS)

    def _route(self, uri: str, item_type: str, deferred: bool) -> dict[str, Any]:
        if item_type == "topic":
            target = "SubscriptionManager.wait_for_event"
        else:
            target = "WwiseDispatcher.dispatch"
        return {
            "deferred_registry_required": deferred,
            "dispatcher": "WwiseDispatcher.dispatch",
            "mode": "function-call" if item_type == "function" else "bounded-topic-wait",
            "route_test": "tests/unit/test_dispatch_routes_all_2022.py::test_every_non_deferred_api_routes_with_fake_runtime"
            if not deferred
            else "tests/unit/test_no_silent_skips.py::test_every_deferred_api_has_registry_evidence",
            "target": target,
        }

    def _safety(self, uri: str, item_type: str, category: str, risk_level: str, deferred: bool) -> dict[str, Any]:
        if deferred:
            reason = "Requires deferred registry evidence before behavioral execution."
            if item_type == "topic":
                reason = "Requires a live event publisher/subscription fixture; default tests use substitute evidence."
            elif category == "soundengine":
                reason = "Sound-engine state depends on a live initialized engine and fixture game objects."
            elif category.startswith("ui"):
                reason = "UI behavior depends on authoring foreground state and is not deterministic in default tests."
            elif self._requires_destructive_opt_in(uri, item_type, risk_level):
                reason = "Potentially destructive or mutating operation requires explicit opt-in."
            return {"classification": "deferred", "deterministic_default": False, "reason": reason}
        return {
            "classification": "live-safe-fake-route",
            "deterministic_default": True,
            "reason": "Low-risk reflected function can be resolved through the manifest-backed dispatcher with an injected fake WAAPI client.",
        }

    def _behavioral_evidence(self, uri: str, item_type: str, deferred: bool, version: str) -> dict[str, Any]:
        if deferred:
            return {
                "coverage": "substitute-test",
                "evidence": f"DeferredRegistry.load_default({version!r}) plus schema/route resource validation",
                "test": "tests/unit/test_no_silent_skips.py::test_every_deferred_api_has_registry_evidence",
            }
        if uri == WAQL_API_URI:
            return {
                "coverage": "fake-route-tested-and-waql-resource-gated",
                "evidence": f"resources/waql/{version}/object-get-examples.json",
                "test": "tests/unit/test_dispatch_routes_all_2022.py::test_every_non_deferred_api_routes_with_fake_runtime",
            }
        return {
            "coverage": "fake-route-tested",
            "evidence": "Injected fake WAAPI client validates WwiseDispatcher route resolution without live project mutation.",
            "test": "tests/unit/test_dispatch_routes_all_2022.py::test_every_non_deferred_api_routes_with_fake_runtime",
        }

    def _deferred_payload(
        self,
        uri: str,
        deferred: bool,
        deferred_registry: DeferredRegistry,
        version: str,
        item_type: str,
        category: str,
        risk_level: str,
    ) -> dict[str, Any]:
        if not deferred:
            return {"status": False}
        entry = deferred_registry.get(uri)
        if entry is None:
            if version == DEFAULT_WWISE_VERSION:
                deferred_registry.require(uri)
            return {
                "status": True,
                "behavioral_coverage": "deferred",
                "blocking_condition": (
                    f"No version-specific deferred registry entry exists for {uri}; "
                    "treat this reflected inventory row as substitute coverage only until live behavior evidence is added."
                ),
                "evidence_source": f"resources/manifest/{version} plus synthesized inventory-only deferral",
                "review_trigger": f"When {version} receives behavior-backed coverage or a complete deferred registry entry.",
                "risk_level": risk_level,
                "substitute_test": (
                    f"ApiCoverageBuilder inventory validation for {version}; not behavioral coverage."
                ),
                "synthesized": True,
                "item_type": item_type,
                "category": category,
            }
        return {
            "status": True,
            "behavioral_coverage": entry.behavioral_coverage,
            "blocking_condition": entry.blocking_condition,
            "evidence_source": entry.evidence_source,
            "review_trigger": entry.review_trigger,
            "substitute_test": entry.substitute_test,
        }

    def _schema_mapping(self, uri: str, schema_entry: Mapping[str, Any], schema: Any, version: str) -> dict[str, Any]:
        if not isinstance(schema, Mapping):
            return {"manifest_uri": f"resources/manifest/{version}/schemas.json#{uri}", "sections": {}}
        return {
            "manifest_uri": f"resources/manifest/{version}/schemas.json#{uri}",
            "sections": {
                "args": self._schema_section(schema.get("argsSchema")),
                "options": self._schema_section(schema.get("optionsSchema")),
                "result": self._schema_section(schema.get("resultSchema")),
            },
            "source_status": str(schema_entry.get("status", "missing")),
        }

    def _schema_section(self, section: Any) -> dict[str, Any]:
        if not isinstance(section, Mapping):
            return {"type": "missing", "required": [], "properties": []}
        properties = section.get("properties")
        required = section.get("required")
        return {
            "properties": sorted(properties) if isinstance(properties, Mapping) else [],
            "required": sorted(required) if isinstance(required, list) else [],
            "type": str(section.get("type", "schema-ref" if "$ref" in section else "unknown")),
        }

    def _usage_guidance(self, uri: str, item_type: str, category: str, deferred: bool, is_waql: bool, version: str) -> dict[str, Any]:
        guidance = {
            "default_path": "Use WwiseDispatcher with injected/fake clients in default tests; require live fixture for real WAAPI execution.",
            "notes": "Do not mutate broad user projects; use fixture projects and evidence paths for live tiers.",
        }
        if item_type == "topic":
            guidance["default_path"] = "Use SubscriptionManager.wait_for_event with bounded timeout; own long-running listeners explicitly."
        if deferred:
            guidance["notes"] = "Treat registry evidence as substitute coverage only; do not claim complete behavior until a live-safe behavioral test exists."
        if is_waql:
            guidance["waql_reference"] = f"resources/waql/{version}/object-get-examples.json"
            guidance["waql_gate"] = "wwise_waapi.waql.require_waql_helper_generation"
        if category == "soundengine":
            guidance["fixture_requirement"] = "Requires initialized sound engine/game-object state before live behavioral assertions."
        return guidance

    def _metadata(self, version: str) -> dict[str, Any]:
        return {
            "deferred_source": f"resources/deferred/{version}.json",
            "generator": "tests.destructive.support.api_coverage.ApiCoverageBuilder",
            "manifest_source": f"resources/manifest/{version}",
            "required_entry_fields": [
                "uri",
                "version",
                "item_type",
                "category",
                "risk_level",
                "schema_status",
                "schema_mapping",
                "route",
                "safety",
                "test_status",
                "deferred",
                "behavioral_evidence",
                "usage_guidance",
            ],
            "sort_key": "uri",
            "version": version,
            "waql_reference": f"resources/waql/{version}/object-get-examples.json",
        }

    def _summary(self, version: str, entries: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> CoverageSummary:
        fake_route_tested = sum(1 for entry in entries if entry["test_status"] == "fake-route-tested")
        deferred = sum(1 for entry in entries if entry["deferred"]["status"] is True)
        destructive = sum(1 for entry in entries if entry["destructive_opt_in"] is True)
        substitute = sum(
            1
            for entry in entries
            if entry["test_status"] in {"fake-route-tested", "deferred-with-substitute-test"}
        )
        return CoverageSummary(
            version=version,
            total_functions=len(self._section(manifest, "functions")),
            total_topics=len(self._section(manifest, "topics")),
            implemented=len(entries),
            safe_tested=fake_route_tested,
            live_tested=0,
            deferred=deferred,
            destructive_opt_in=destructive,
            inventory_covered_count=len(entries),
            behavioral_covered_count=0,
            live_behavioral_covered_count=0,
            substitute_covered_count=substitute,
            deferred_count=deferred,
            excluded_count=0,
        )

    def _validate_exact_coverage(self, manifest: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> None:
        reflected = [self._uri(item) for item in self._section(manifest, "functions") + self._section(manifest, "topics")]
        coverage = [str(entry.get("uri")) for entry in entries]
        if len(reflected) != len(set(reflected)):
            raise ValueError("Reflected manifest contains duplicate URIs")
        if len(coverage) != len(set(coverage)):
            raise ValueError("Coverage resource contains duplicate URIs")
        if sorted(reflected) != sorted(coverage):
            missing = sorted(set(reflected) - set(coverage))
            extra = sorted(set(coverage) - set(reflected))
            raise ValueError(f"Coverage resource mismatch; missing={missing}, extra={extra}")

    def _section(self, manifest: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
        section = manifest.get(name)
        if not isinstance(section, list):
            raise ValueError(f"Manifest section {name} must be a list")
        return [item for item in section if isinstance(item, Mapping)]

    def _schemas_by_uri(self, manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        schemas = manifest.get("schemas")
        if not isinstance(schemas, list):
            raise ValueError("Manifest schemas section must be a list")
        result: dict[str, Mapping[str, Any]] = {}
        for entry in schemas:
            if not isinstance(entry, Mapping):
                continue
            uri = entry.get("uri")
            if isinstance(uri, str):
                result[uri] = entry
        return result

    def _uri(self, payload: Mapping[str, Any]) -> str:
        uri = payload.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError(f"Manifest entry is missing uri: {payload!r}")
        return uri


@dataclass(slots=True, frozen=True)
class CoverageResourceWriter:
    """Write coverage resources and evidence summary with deterministic JSON bytes."""

    coverage_root: Path = DEFAULT_COVERAGE_ROOT
    evidence_path: Path = DEFAULT_EVIDENCE_PATH
    writer: DeterministicJsonWriter = field(default_factory=DeterministicJsonWriter)

    def write(self, resource: CoverageResource) -> list[Path]:
        coverage_path = self.coverage_root / resource.version / "api-coverage.json"
        self.writer.write(coverage_path, resource.as_dict())
        evidence_path = self.evidence_path
        if not evidence_path.is_absolute():
            evidence_path = Path.cwd() / evidence_path
        self.writer.write(evidence_path, resource.summary.as_dict())
        return [coverage_path, evidence_path]


def build_coverage_resource(version: str = DEFAULT_WWISE_VERSION) -> CoverageResource:
    """Build the default Task 7 coverage resource."""

    return ApiCoverageBuilder().build(version)


def write_default_coverage_resources(version: str = DEFAULT_WWISE_VERSION) -> list[Path]:
    """Generate and write coverage resources plus Task 7 evidence."""

    resource = build_coverage_resource(version)
    return CoverageResourceWriter().write(resource)


def load_coverage_resource(path: Path) -> dict[str, Any]:
    """Load a generated coverage resource JSON file."""

    return json.loads(path.read_text(encoding="utf-8"))

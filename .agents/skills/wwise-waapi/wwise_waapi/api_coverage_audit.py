"""Audit reflected WAAPI inventory against behavioral or deferred coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .deferred_registry import ApiClassifier, DeferredEntry, DeferredRegistry


@dataclass(slots=True, frozen=True)
class ReflectedApiItem:
    """One function or topic reflected from the manifest inventory."""

    uri: str
    item_type: str
    category: str


@dataclass(slots=True, frozen=True)
class BehavioralCoverageRecord:
    """Evidence that a WAAPI item has behavioral, not just inventory, coverage."""

    uri: str
    version: str
    category: str
    evidence_source: str
    test_name: str
    behavioral_coverage: str = "tested"

    def validate(self) -> None:
        missing = [
            name
            for name in ("uri", "version", "category", "evidence_source", "test_name", "behavioral_coverage")
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
        ]
        if missing:
            raise ValueError(f"Behavioral coverage record {self.uri or '<unknown>'} missing: {', '.join(missing)}")
        if self.behavioral_coverage == "deferred":
            raise ValueError(f"Behavioral coverage record {self.uri} cannot be marked deferred")


@dataclass(slots=True, frozen=True)
class ApiCoverageAuditResult:
    """Outcome of classifying all reflected WAAPI inventory."""

    version: str
    reflected_count: int
    inventory_covered_count: int
    behavioral_covered_count: int
    deferred_count: int
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    categories: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.invalid and (
            self.behavioral_covered_count + self.deferred_count == self.reflected_count
        )

    def raise_for_failures(self) -> None:
        if self.passed:
            return
        details = [*self.invalid, *[f"Missing coverage for {uri}" for uri in self.missing]]
        raise RuntimeError("WAAPI coverage audit failed: " + "; ".join(details))


class ApiCoverageAuditor:
    """Fail-closed audit for reflected function/topic coverage state."""

    def __init__(self, classifier: ApiClassifier | None = None) -> None:
        self.classifier = classifier or ApiClassifier()

    def audit(
        self,
        manifest: Mapping[str, Any],
        deferred_registry: DeferredRegistry,
        behavioral_records: Iterable[BehavioralCoverageRecord] = (),
        *,
        version: str = "2022.1",
    ) -> ApiCoverageAuditResult:
        items = self._manifest_items(manifest)
        deferred_registry.validate_all()
        behavior_by_uri = self._behavior_by_uri(behavioral_records, version)
        manifest_uris = {item.uri for item in items}
        invalid: list[str] = []
        missing: list[str] = []
        categories: dict[str, int] = {}
        deferred_count = 0
        behavioral_count = 0

        for uri in sorted(set(behavior_by_uri) & set(deferred_registry.entries)):
            invalid.append(f"URI {uri} has both behavioral coverage and a deferred entry")

        for item in items:
            categories[item.category] = categories.get(item.category, 0) + 1
            behavior = behavior_by_uri.get(item.uri)
            deferred = deferred_registry.get(item.uri)
            if behavior is not None:
                invalid.extend(self._validate_behavior_record(behavior, item, version))
                behavioral_count += 1
                continue
            if deferred is not None:
                invalid.extend(self._validate_deferred_entry(deferred, item, version))
                deferred_count += 1
                continue
            missing.append(item.uri)

        for uri in sorted(set(deferred_registry.entries) - manifest_uris):
            invalid.append(f"Deferred entry {uri} is not present in reflected manifest inventory")
        for uri in sorted(set(behavior_by_uri) - manifest_uris):
            invalid.append(f"Behavioral coverage record {uri} is not present in reflected manifest inventory")

        return ApiCoverageAuditResult(
            version=version,
            reflected_count=len(items),
            inventory_covered_count=len(items),
            behavioral_covered_count=behavioral_count,
            deferred_count=deferred_count,
            missing=tuple(sorted(missing)),
            invalid=tuple(invalid),
            categories=dict(sorted(categories.items())),
        )

    def _manifest_items(self, manifest: Mapping[str, Any]) -> list[ReflectedApiItem]:
        missing_sections = [section for section in ("functions", "topics") if section not in manifest]
        if missing_sections:
            raise ValueError(f"Manifest is missing required sections: {', '.join(missing_sections)}")
        items = [
            *self._items_from_section(manifest["functions"], "function"),
            *self._items_from_section(manifest["topics"], "topic"),
        ]
        if not items:
            raise ValueError("Manifest must include at least one reflected function or topic")
        seen: set[str] = set()
        duplicates: list[str] = []
        for item in items:
            if item.uri in seen:
                duplicates.append(item.uri)
            seen.add(item.uri)
        if duplicates:
            raise ValueError(f"Manifest contains duplicate reflected URIs: {', '.join(sorted(duplicates))}")
        return sorted(items, key=lambda item: item.uri)

    def _items_from_section(self, section: Any, item_type: str) -> list[ReflectedApiItem]:
        if not isinstance(section, list):
            raise ValueError(f"Manifest {item_type} section must be a list")
        items: list[ReflectedApiItem] = []
        for payload in section:
            if not isinstance(payload, Mapping):
                raise ValueError(f"Manifest {item_type} entry must be a mapping: {payload!r}")
            uri = payload.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                raise ValueError(f"Manifest {item_type} entry is missing uri: {payload!r}")
            classification = self.classifier.classify(uri, item_type)
            items.append(ReflectedApiItem(uri=uri, item_type=item_type, category=classification.category))
        return items

    def _behavior_by_uri(
        self, records: Iterable[BehavioralCoverageRecord], version: str
    ) -> dict[str, BehavioralCoverageRecord]:
        by_uri: dict[str, BehavioralCoverageRecord] = {}
        for record in records:
            record.validate()
            if record.version != version:
                raise ValueError(f"Behavioral coverage record {record.uri} targets {record.version}, expected {version}")
            if record.uri in by_uri:
                raise ValueError(f"Duplicate behavioral coverage record for {record.uri}")
            by_uri[record.uri] = record
        return by_uri

    def _validate_behavior_record(
        self, record: BehavioralCoverageRecord, item: ReflectedApiItem, version: str
    ) -> list[str]:
        invalid: list[str] = []
        if record.version != version:
            invalid.append(f"Behavioral coverage record {record.uri} version {record.version} != {version}")
        if record.category != item.category:
            invalid.append(
                f"Behavioral coverage record {record.uri} category {record.category!r} != deterministic {item.category!r}"
            )
        return invalid

    def _validate_deferred_entry(self, entry: DeferredEntry, item: ReflectedApiItem, version: str) -> list[str]:
        invalid: list[str] = []
        if entry.version != version:
            invalid.append(f"Deferred entry {entry.uri} version {entry.version} != {version}")
        if entry.item_type != item.item_type:
            invalid.append(f"Deferred entry {entry.uri} item_type {entry.item_type!r} != {item.item_type!r}")
        if entry.category != item.category:
            invalid.append(f"Deferred entry {entry.uri} category {entry.category!r} != deterministic {item.category!r}")
        expected_risk = self.classifier.risk_for(entry.uri, entry.item_type)
        if entry.risk_level != expected_risk:
            invalid.append(
                f"Deferred entry {entry.uri} risk_level {entry.risk_level!r} != deterministic {expected_risk!r}"
            )
        if entry.behavioral_coverage != "deferred":
            invalid.append(f"Deferred entry {entry.uri} must not claim behavioral coverage")
        return invalid

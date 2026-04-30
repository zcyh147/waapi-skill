"""Audit reflected WAAPI inventory against behavioral or deferred coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .deferred_registry import ApiClassifier, DeferredEntry, DeferredRegistry


PHASE2_ACHIEVED_STATUSES = frozenset(
    {
        "fake-route-tested",
        "live-smoke-tested",
        "live-sandbox-tested",
        "sandbox-mutating-tested",
        "profiler-backed-tested",
        "soundengine-backed-tested",
        "wrapper-only",
        "skipped-approved",
        "conformance-only-skip",
        "still-deferred-with-evidence",
    }
)
PHASE21_EVIDENCE_CLASSES = frozenset(
    {
        "live_behavioral_waapi",
        "live_behavioral_profiler",
        "conformance_only_skip",
        "still_deferred_with_evidence",
    }
)
STILL_DEFERRED_STATUS = "still-deferred-with-evidence"
CONFORMANCE_ONLY_STATUS = "conformance-only-skip"
LIVE_EVIDENCE_REQUIRED_STATUSES = frozenset(
    {
        "live-smoke-tested",
        "live-sandbox-tested",
        "sandbox-mutating-tested",
        "profiler-backed-tested",
        "soundengine-backed-tested",
    }
)
EVIDENCE_PATH_REQUIRED_STATUSES = LIVE_EVIDENCE_REQUIRED_STATUSES | {STILL_DEFERRED_STATUS}
LIVE_BEHAVIOR_STATUSES = frozenset(
    {
        "live-smoke-tested",
        "live-sandbox-tested",
        "sandbox-mutating-tested",
        "soundengine-backed-tested",
    }
)
POLICY_APPROVED_NON_BEHAVIOR_STATUSES = frozenset({"wrapper-only", "skipped-approved", "conformance-only-skip"})


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
class Phase2CoverageStatusRecord:
    """Phase 2 coverage status with evidence separate from reflected inventory."""

    uri: str
    version: str
    category: str
    inventory_coverage: str
    achieved_status: str = ""
    achieved_statuses: tuple[str, ...] = ()
    evidence_path: str = ""
    evidence_command: str = ""
    evidence_class: str = ""
    user_approved_rationale: str = ""
    future_review_trigger: str = ""
    behavioral_coverage: str = "not-behavioral"

    def validate(self) -> None:
        missing = [
            name
            for name in ("uri", "version", "category", "inventory_coverage")
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
        ]
        if missing:
            raise ValueError(f"Phase 2 coverage record {self.uri or '<unknown>'} missing: {', '.join(missing)}")

        statuses = self.statuses
        if LIVE_EVIDENCE_REQUIRED_STATUSES.intersection(statuses) and STILL_DEFERRED_STATUS in statuses:
            raise ValueError(f"Phase 2 coverage record {self.uri} live status cannot overlap with still-deferred")
        if len(statuses) != 1:
            raise ValueError(f"Phase 2 coverage record {self.uri} must declare exactly one achieved status")

        status = statuses[0]
        if status not in PHASE2_ACHIEVED_STATUSES:
            raise ValueError(f"Phase 2 coverage record {self.uri} has invalid achieved status {status!r}")
        if self.evidence_class.strip() and self.evidence_class.strip() not in PHASE21_EVIDENCE_CLASSES:
            raise ValueError(
                f"Phase 2 coverage record {self.uri} has invalid evidence class {self.evidence_class!r}"
            )
        if status in EVIDENCE_PATH_REQUIRED_STATUSES:
            missing_evidence = [
                name
                for name in ("evidence_path", "evidence_command", "evidence_class")
                if not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
            ]
            if missing_evidence:
                raise ValueError(
                    f"Phase 2 coverage record {self.uri} status {status!r} missing: "
                    + ", ".join(missing_evidence)
                )
        self._validate_evidence_class(status)
        if status in POLICY_APPROVED_NON_BEHAVIOR_STATUSES:
            missing_policy = [
                name
                for name in ("user_approved_rationale", "future_review_trigger")
                if not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
            ]
            if missing_policy:
                raise ValueError(
                    f"Phase 2 coverage record {self.uri} status {status!r} missing: " + ", ".join(missing_policy)
                )
        if status == STILL_DEFERRED_STATUS and not self.future_review_trigger.strip():
            raise ValueError(
                f"Phase 2 coverage record {self.uri} status {status!r} missing: future_review_trigger"
            )

    def _validate_evidence_class(self, status: str) -> None:
        evidence_class = self.evidence_class.strip()
        if not evidence_class:
            return
        if status == "profiler-backed-tested" and evidence_class != "live_behavioral_profiler":
            raise ValueError(
                f"Phase 2 coverage record {self.uri} status {status!r} requires evidence class 'live_behavioral_profiler'"
            )
        if status in {"live-smoke-tested", "live-sandbox-tested", "sandbox-mutating-tested", "soundengine-backed-tested"} and evidence_class != "live_behavioral_waapi":
            raise ValueError(
                f"Phase 2 coverage record {self.uri} status {status!r} requires evidence class 'live_behavioral_waapi'"
            )
        if status == CONFORMANCE_ONLY_STATUS and evidence_class != "conformance_only_skip":
            raise ValueError(
                f"Phase 2 coverage record {self.uri} status {status!r} requires evidence class 'conformance_only_skip'"
            )
        if status == STILL_DEFERRED_STATUS and evidence_class != "still_deferred_with_evidence":
            raise ValueError(
                f"Phase 2 coverage record {self.uri} status {status!r} requires evidence class 'still_deferred_with_evidence'"
            )

    @property
    def statuses(self) -> tuple[str, ...]:
        statuses: list[str] = []
        if isinstance(self.achieved_status, str) and self.achieved_status.strip():
            statuses.append(self.achieved_status.strip())
        statuses.extend(status.strip() for status in self.achieved_statuses if isinstance(status, str) and status.strip())
        return tuple(statuses)

    @property
    def status(self) -> str:
        statuses = self.statuses
        return statuses[0] if len(statuses) == 1 else ""

    @property
    def counts_as_behavioral(self) -> bool:
        if self.status == "profiler-backed-tested":
            return self.behavioral_coverage == "direct-behavior-with-profiler-evidence"
        return self.status in {"fake-route-tested", *LIVE_BEHAVIOR_STATUSES}

    @property
    def counts_as_live_behavioral(self) -> bool:
        if self.status == "profiler-backed-tested":
            return self.behavioral_coverage == "direct-behavior-with-profiler-evidence"
        return self.status in LIVE_BEHAVIOR_STATUSES


@dataclass(slots=True, frozen=True)
class ApiCoverageAuditResult:
    """Outcome of classifying all reflected WAAPI inventory."""

    version: str
    reflected_count: int
    inventory_covered_count: int
    behavioral_covered_count: int
    deferred_count: int
    covered_count: int = 0
    phase2_status_covered_count: int = 0
    live_behavioral_covered_count: int = 0
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    categories: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        covered_count = self.covered_count or self.behavioral_covered_count + self.deferred_count
        return not self.missing and not self.invalid and covered_count == self.reflected_count

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
        phase2_status_records: Iterable[Phase2CoverageStatusRecord] = (),
    ) -> ApiCoverageAuditResult:
        items = self._manifest_items(manifest)
        deferred_registry.validate_all()
        behavior_by_uri = self._behavior_by_uri(behavioral_records, version)
        phase2_by_uri, phase2_invalid, invalid_phase2_uris = self._phase2_by_uri(phase2_status_records, version)
        manifest_uris = {item.uri for item in items}
        invalid: list[str] = [*phase2_invalid]
        missing: list[str] = []
        categories: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        deferred_count = 0
        behavioral_count = 0
        covered_count = 0
        phase2_status_count = 0
        live_behavioral_count = 0

        for uri in sorted(set(behavior_by_uri) & set(deferred_registry.entries)):
            invalid.append(f"URI {uri} has both behavioral coverage and a deferred entry")

        for item in items:
            categories[item.category] = categories.get(item.category, 0) + 1
            phase2 = phase2_by_uri.get(item.uri)
            behavior = behavior_by_uri.get(item.uri)
            deferred = deferred_registry.get(item.uri)
            if phase2 is not None:
                invalid.extend(self._validate_phase2_status_record(phase2, item, version))
                status_counts[phase2.status] = status_counts.get(phase2.status, 0) + 1
                phase2_status_count += 1
                if phase2.counts_as_behavioral:
                    behavioral_count += 1
                if phase2.counts_as_live_behavioral:
                    live_behavioral_count += 1
                covered_count += 1
                continue
            if behavior is not None:
                invalid.extend(self._validate_behavior_record(behavior, item, version))
                behavioral_count += 1
                covered_count += 1
                continue
            if deferred is not None:
                invalid.extend(self._validate_deferred_entry(deferred, item, version))
                deferred_count += 1
                covered_count += 1
                continue
            if item.uri not in invalid_phase2_uris:
                missing.append(item.uri)

        for uri in sorted(set(deferred_registry.entries) - manifest_uris):
            invalid.append(f"Deferred entry {uri} is not present in reflected manifest inventory")
        for uri in sorted(set(behavior_by_uri) - manifest_uris):
            invalid.append(f"Behavioral coverage record {uri} is not present in reflected manifest inventory")
        for uri in sorted(set(phase2_by_uri) - manifest_uris):
            invalid.append(f"Phase 2 coverage record {uri} is not present in reflected manifest inventory")

        return ApiCoverageAuditResult(
            version=version,
            reflected_count=len(items),
            inventory_covered_count=len(items),
            behavioral_covered_count=behavioral_count,
            deferred_count=deferred_count,
            covered_count=covered_count,
            phase2_status_covered_count=phase2_status_count,
            live_behavioral_covered_count=live_behavioral_count,
            missing=tuple(sorted(missing)),
            invalid=tuple(invalid),
            categories=dict(sorted(categories.items())),
            status_counts=dict(sorted(status_counts.items())),
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

    def _phase2_by_uri(
        self, records: Iterable[Phase2CoverageStatusRecord], version: str
    ) -> tuple[dict[str, Phase2CoverageStatusRecord], list[str], set[str]]:
        by_uri: dict[str, Phase2CoverageStatusRecord] = {}
        invalid: list[str] = []
        invalid_uris: set[str] = set()
        for record in records:
            try:
                record.validate()
            except ValueError as exc:
                invalid.append(str(exc))
                if isinstance(record.uri, str) and record.uri.strip():
                    invalid_uris.add(record.uri)
                continue
            if record.version != version:
                invalid.append(f"Phase 2 coverage record {record.uri} targets {record.version}, expected {version}")
                invalid_uris.add(record.uri)
            if record.uri in by_uri:
                invalid.append(f"URI {record.uri} has multiple Phase 2 achieved statuses")
                invalid_uris.add(record.uri)
                continue
            by_uri[record.uri] = record
        return by_uri, invalid, invalid_uris

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

    def _validate_phase2_status_record(
        self, record: Phase2CoverageStatusRecord, item: ReflectedApiItem, version: str
    ) -> list[str]:
        invalid: list[str] = []
        if record.version != version:
            invalid.append(f"Phase 2 coverage record {record.uri} version {record.version} != {version}")
        if record.category != item.category:
            invalid.append(
                f"Phase 2 coverage record {record.uri} category {record.category!r} != deterministic {item.category!r}"
            )
        if record.inventory_coverage == record.behavioral_coverage:
            invalid.append(f"Phase 2 coverage record {record.uri} must keep inventory coverage separate from behavior")
        if record.status in POLICY_APPROVED_NON_BEHAVIOR_STATUSES and record.counts_as_live_behavioral:
            invalid.append(f"Phase 2 coverage record {record.uri} must not count {record.status!r} as live behavior")
        if record.status in POLICY_APPROVED_NON_BEHAVIOR_STATUSES and record.counts_as_behavioral:
            invalid.append(f"Phase 2 coverage record {record.uri} must not count {record.status!r} as behavior")
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

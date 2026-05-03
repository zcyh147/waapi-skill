"""Evidence-backed registry for deferred WAAPI behavioral coverage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_WWISE_VERSION = "2022.1"
REQUIRED_DEFERRED_FIELDS = (
    "uri",
    "version",
    "category",
    "reason",
    "evidence_source",
    "blocking_condition",
    "substitute_test",
    "owner_follow_up",
    "date",
    "review_trigger",
    "risk_level",
)
REQUIRED_COVERAGE_FIELDS = ("inventory_coverage", "behavioral_coverage")
ALLOWED_RISK_LEVELS = frozenset({"low", "medium", "high"})
DEFERRED_RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources" / "deferred"


@dataclass(slots=True, frozen=True)
class ApiClassification:
    """Deterministic URI-derived WAAPI classification."""

    uri: str
    item_type: str
    category: str
    risk_level: str


class ApiClassifier:
    """Classify WAAPI URIs from namespace and operation name only."""

    _READ_PREFIXES = ("get", "is", "verify", "dump")
    _HIGH_RISK_TOKENS = (
        "crash",
        "delete",
        "deleted",
        "migrate",
        "createnewproject",
        "project.close",
        "project.open",
    )

    def classify(self, uri: str, item_type: str = "function") -> ApiClassification:
        if item_type not in {"function", "topic"}:
            raise ValueError(f"Unsupported WAAPI item type {item_type!r} for {uri!r}")
        category = self.category_for(uri)
        return ApiClassification(
            uri=uri,
            item_type=item_type,
            category=category,
            risk_level=self.risk_for(uri, item_type),
        )

    def category_for(self, uri: str) -> str:
        parts = uri.split(".")
        if len(parts) < 3 or parts[0] != "ak":
            raise ValueError(f"WAAPI URI must start with an ak namespace: {uri!r}")
        if parts[1] == "soundengine":
            return "soundengine"
        if parts[1] == "wwise":
            category_parts = parts[2:-1]
            if not category_parts:
                return "wwise"
            return ".".join(category_parts)
        return ".".join(parts[1:-1]) or parts[1]

    def risk_for(self, uri: str, item_type: str = "function") -> str:
        lowered = uri.lower()
        if any(token in lowered for token in self._HIGH_RISK_TOKENS):
            return "high"
        operation = uri.rsplit(".", 1)[-1]
        if item_type == "function" and operation.startswith(self._READ_PREFIXES):
            return "low"
        return "medium"


@dataclass(slots=True, frozen=True)
class DeferredEntry:
    """One deferred WAAPI item with complete evidence for the deferral."""

    uri: str
    version: str
    category: str
    reason: str
    evidence_source: str
    blocking_condition: str
    substitute_test: str
    owner_follow_up: str
    date: str
    review_trigger: str
    risk_level: str
    inventory_coverage: str
    behavioral_coverage: str
    item_type: str = "function"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DeferredEntry:
        missing = _missing_required_fields(payload)
        if missing:
            uri = _uri_for_error(payload)
            raise ValueError(f"Deferred entry {uri} missing required fields: {', '.join(missing)}")

        entry = cls(
            uri=_string_field(payload, "uri"),
            version=_string_field(payload, "version"),
            category=_string_field(payload, "category"),
            reason=_string_field(payload, "reason"),
            evidence_source=_string_field(payload, "evidence_source"),
            blocking_condition=_string_field(payload, "blocking_condition"),
            substitute_test=_string_field(payload, "substitute_test"),
            owner_follow_up=_string_field(payload, "owner_follow_up"),
            date=_string_field(payload, "date"),
            review_trigger=_string_field(payload, "review_trigger"),
            risk_level=_string_field(payload, "risk_level"),
            inventory_coverage=_string_field(payload, "inventory_coverage"),
            behavioral_coverage=_string_field(payload, "behavioral_coverage"),
            item_type=str(payload.get("item_type", "function")),
        )
        entry.validate()
        return entry

    def validate(self) -> None:
        payload = self.as_dict()
        missing = _missing_required_fields(payload)
        if missing:
            raise ValueError(f"Deferred entry {self.uri} missing required fields: {', '.join(missing)}")
        if self.risk_level not in ALLOWED_RISK_LEVELS:
            raise ValueError(
                f"Deferred entry {self.uri} has invalid risk_level {self.risk_level!r}; "
                f"expected one of {sorted(ALLOWED_RISK_LEVELS)}"
            )
        if self.behavioral_coverage != "deferred":
            raise ValueError(f"Deferred entry {self.uri} must declare behavioral_coverage='deferred'")
        if not self.inventory_coverage.startswith("reflected"):
            raise ValueError(f"Deferred entry {self.uri} must declare reflected inventory_coverage")
        if self.item_type not in {"function", "topic"}:
            raise ValueError(f"Deferred entry {self.uri} has invalid item_type {self.item_type!r}")
        try:
            date.fromisoformat(self.date)
        except ValueError as exc:
            raise ValueError(f"Deferred entry {self.uri} has invalid ISO date {self.date!r}") from exc

    def as_dict(self) -> dict[str, str]:
        return {
            "behavioral_coverage": self.behavioral_coverage,
            "blocking_condition": self.blocking_condition,
            "category": self.category,
            "date": self.date,
            "evidence_source": self.evidence_source,
            "inventory_coverage": self.inventory_coverage,
            "item_type": self.item_type,
            "owner_follow_up": self.owner_follow_up,
            "reason": self.reason,
            "review_trigger": self.review_trigger,
            "risk_level": self.risk_level,
            "substitute_test": self.substitute_test,
            "uri": self.uri,
            "version": self.version,
        }


class DeferredRegistry:
    """Validated lookup of WAAPI items whose behavioral coverage is deferred."""

    def __init__(self, entries: Iterable[DeferredEntry] | None = None) -> None:
        self.entries: dict[str, DeferredEntry] = {}
        for entry in entries or ():
            self.add(entry)

    @classmethod
    def from_mappings(cls, payloads: Iterable[Mapping[str, Any]]) -> DeferredRegistry:
        return cls(DeferredEntry.from_mapping(payload) for payload in payloads)

    @classmethod
    def from_resource(cls, path: Path) -> DeferredRegistry:
        payload = json.loads(path.read_text(encoding="utf-8"))
        deferred = payload.get("deferred")
        if not isinstance(deferred, list):
            raise ValueError(f"Deferred resource {path} must contain a deferred list")
        return cls.from_mappings(deferred)

    @classmethod
    def load_default(cls, version: str = DEFAULT_WWISE_VERSION) -> DeferredRegistry:
        return cls.from_resource(DEFERRED_RESOURCE_DIR / f"{version}.json")

    def add(self, entry: DeferredEntry) -> None:
        entry.validate()
        if entry.uri in self.entries:
            raise ValueError(f"Duplicate deferred entry for {entry.uri}")
        self.entries[entry.uri] = entry

    def record(self, key: str, reason: str) -> None:
        classification = ApiClassifier().classify(key)
        self.add(
            DeferredEntry(
                uri=key,
                version=DEFAULT_WWISE_VERSION,
                category=classification.category,
                reason=reason,
                evidence_source="manual DeferredRegistry.record call",
                blocking_condition="Behavioral implementation and test evidence have not been supplied.",
                substitute_test="Registry lookup only; not behavioral coverage.",
                owner_follow_up="Add behavior-backed coverage before removing this deferral.",
                date=date.today().isoformat(),
                review_trigger="When behavioral implementation or reflected inventory changes.",
                risk_level=classification.risk_level,
                inventory_coverage="reflected-inventory-unverified",
                behavioral_coverage="deferred",
            )
        )

    def get(self, uri: str) -> DeferredEntry | None:
        return self.entries.get(uri)

    def require(self, uri: str) -> DeferredEntry:
        entry = self.get(uri)
        if entry is None:
            raise KeyError(f"No deferred entry exists for {uri}")
        return entry

    def missing(self) -> list[str]:
        return sorted(self.entries)

    def validate_all(self) -> None:
        for entry in self.entries.values():
            entry.validate()


def _missing_required_fields(payload: Mapping[str, Any]) -> list[str]:
    fields = REQUIRED_DEFERRED_FIELDS + REQUIRED_COVERAGE_FIELDS
    return [field for field in fields if not isinstance(payload.get(field), str) or not payload[field].strip()]


def _string_field(payload: Mapping[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        uri = _uri_for_error(payload)
        raise ValueError(f"Deferred entry {uri} has invalid {field}")
    return value.strip()


def _uri_for_error(payload: Mapping[str, Any]) -> str:
    value = payload.get("uri")
    return repr(value) if value else "<unknown>"

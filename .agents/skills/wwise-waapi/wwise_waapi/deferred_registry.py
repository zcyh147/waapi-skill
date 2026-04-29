"""Deferred registry placeholder for unsupported or untested WAAPI items."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeferredRegistry:
    """Track items that must be deferred until evidence exists."""

    entries: dict[str, str] = field(default_factory=dict)

    def record(self, key: str, reason: str) -> None:
        self.entries[key] = reason

    def missing(self) -> list[str]:
        return sorted(self.entries)

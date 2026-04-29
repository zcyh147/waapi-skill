"""Manifest placeholder for reflected Wwise WAAPI resources."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ManifestStore:
    """Placeholder store for generated function/topic/schema manifests."""

    versions: dict[str, dict[str, object]] = field(default_factory=dict)

    def load(self, version: str) -> dict[str, object]:
        return self.versions.get(version, {})

    def record(self, version: str, manifest: dict[str, object]) -> None:
        self.versions[version] = manifest

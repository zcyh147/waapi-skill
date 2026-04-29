"""Configuration and path helpers for the Wwise WAAPI skill."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class SkillPaths:
    """Resolved paths used by the Wwise WAAPI skill."""

    skill_root: Path
    data_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    fixtures_dir: Path = field(init=False)
    manifests_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", self.skill_root / "data")
        object.__setattr__(self, "logs_dir", self.skill_root / "logs")
        object.__setattr__(self, "fixtures_dir", self.skill_root / "fixtures")
        object.__setattr__(self, "manifests_dir", self.skill_root / "resources" / "manifest")


@dataclass(slots=True)
class SkillConfig:
    """Basic configuration for scaffolded Wwise WAAPI workflows."""

    skill_root: Path
    paths: SkillPaths = field(init=False)
    coverage_minimum: int = 85
    core_coverage_targets: dict[str, int] = field(
        default_factory=lambda: {
            "headless": 95,
            "manifest": 95,
            "dispatcher": 95,
            "subscriptions": 95,
            "deferred_registry": 95,
        }
    )
    wwise_live_env: str = "WWISE_LIVE"
    wwise_destructive_env: str = "WWISE_DESTRUCTIVE"

    def __post_init__(self) -> None:
        self.paths = SkillPaths(self.skill_root)

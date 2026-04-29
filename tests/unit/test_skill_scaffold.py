from __future__ import annotations

from pathlib import Path

from wwise_waapi import (  # pyright: ignore[reportMissingImports]
    DeferredRegistry,
    HeadlessLifecycle,
    ManifestStore,
    SkillConfig,
    SkillPaths,
    SubscriptionManager,
    WwiseDispatcher,
)


def test_package_imports_and_placeholders() -> None:
    assert SkillPaths(Path("/tmp/wwise-waapi")).skill_root.name == "wwise-waapi"
    assert SkillConfig(Path("/tmp/wwise-waapi")).coverage_minimum == 85
    assert isinstance(HeadlessLifecycle(), HeadlessLifecycle)
    assert isinstance(ManifestStore(), ManifestStore)
    assert isinstance(WwiseDispatcher(), WwiseDispatcher)
    assert isinstance(SubscriptionManager(), SubscriptionManager)
    assert isinstance(DeferredRegistry(), DeferredRegistry)


def test_config_targets_are_documented() -> None:
    config = SkillConfig(Path("/tmp/wwise-waapi"))
    assert config.paths.data_dir.name == "data"
    assert config.core_coverage_targets["headless"] == 95
    assert config.wwise_live_env == "WWISE_LIVE"

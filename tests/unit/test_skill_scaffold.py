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
    assert SkillPaths(Path("/tmp/waapi-skill")).skill_root.name == "waapi-skill"
    assert isinstance(HeadlessLifecycle(), HeadlessLifecycle)
    assert isinstance(ManifestStore(), ManifestStore)
    assert isinstance(WwiseDispatcher(), WwiseDispatcher)
    assert isinstance(SubscriptionManager(), SubscriptionManager)
    assert isinstance(DeferredRegistry(), DeferredRegistry)


def test_config_targets_are_documented() -> None:
    config = SkillConfig(Path("/tmp/waapi-skill"))
    assert config.paths.data_dir.name == "data"
    assert config.wwise_version is None
    assert config.waapi_host == "127.0.0.1"
    assert config.waapi_port is None
    assert config.project_modification_policy == "ask_before_changes"
    assert config.config_path.as_posix().endswith("data/config.json")

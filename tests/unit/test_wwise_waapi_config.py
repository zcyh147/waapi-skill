from __future__ import annotations

import json

from wwise_waapi import SkillConfig  # pyright: ignore[reportMissingImports]


def test_load_defaults_when_config_is_missing(tmp_path) -> None:
    config = SkillConfig.load(tmp_path)

    assert config.skill_root == tmp_path
    assert config.wwise_version is None
    assert config.waapi_host == "127.0.0.1"
    assert config.waapi_port is None
    assert config.project_modification_policy == "preview_then_confirm"
    assert config.use_current_selection_for_ambiguous_queries is True


def test_save_and_load_roundtrip(tmp_path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config = SkillConfig(tmp_path)
    config.wwise_version = "2024.1"
    config.waapi_host = "localhost"
    config.waapi_port = 8080
    config.project_modification_policy = "allow_with_notice"
    config.use_current_selection_for_ambiguous_queries = False

    config.save(config_path)

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload == {
        "waapi_host": "localhost",
        "waapi_port": 8080,
        "project_modification_policy": "allow_with_notice",
        "use_current_selection_for_ambiguous_queries": False,
        "wwise_version": "2024.1",
    }

    loaded = SkillConfig.load(tmp_path, config_path)
    assert loaded.wwise_version == "2024.1"
    assert loaded.waapi_host == "localhost"
    assert loaded.waapi_port == 8080
    assert loaded.project_modification_policy == "allow_with_notice"
    assert loaded.use_current_selection_for_ambiguous_queries is False


def test_update_persists_specific_fields(tmp_path) -> None:
    config_path = tmp_path / "data" / "config.json"

    SkillConfig(tmp_path).update(
        path=config_path,
        wwise_version="2025.1",
        waapi_port=1234,
        project_modification_policy="never",
    )

    loaded = SkillConfig.load(tmp_path, config_path)
    assert loaded.wwise_version == "2025.1"
    assert loaded.waapi_port == 1234
    assert loaded.project_modification_policy == "never"
    assert loaded.use_current_selection_for_ambiguous_queries is True


def test_invalid_project_modification_policy_fails_closed(tmp_path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '{"project_modification_policy": "mutating"}',
        encoding="utf-8",
    )

    try:
        SkillConfig.load(tmp_path, config_path)
    except ValueError as exc:
        assert "project_modification_policy must be one of" in str(exc)
    else:
        raise AssertionError("Expected invalid policy to raise ValueError")


def test_update_rejects_invalid_project_modification_policy(tmp_path) -> None:
    config = SkillConfig(tmp_path)

    try:
        config.update(project_modification_policy="mutating")
    except ValueError as exc:
        assert "project_modification_policy must be one of" in str(exc)
    else:
        raise AssertionError("Expected invalid policy to raise ValueError")


def test_update_rejects_unsupported_fields(tmp_path) -> None:
    config = SkillConfig(tmp_path)

    try:
        config.update(path=tmp_path / "data" / "config.json", unknown_field=True)
    except ValueError as exc:
        assert "Unsupported config field: unknown_field" in str(exc)
    else:
        raise AssertionError("Expected unsupported field to raise ValueError")


def test_invalid_json_fails_closed(tmp_path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("not-json", encoding="utf-8")

    try:
        SkillConfig.load(tmp_path, config_path)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("Expected invalid JSON to raise JSONDecodeError")

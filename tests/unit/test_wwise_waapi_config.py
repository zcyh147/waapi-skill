from __future__ import annotations

import json
from pathlib import Path

import pytest

from wwise_waapi import SkillConfig  # pyright: ignore[reportMissingImports]
from wwise_waapi.config import (  # pyright: ignore[reportMissingImports]
    DEFAULT_PROJECT_MODIFICATION_POLICY,
    LEGACY_PROJECT_MODIFICATION_POLICY_ALIASES,
    MAX_CONFIG_BYTES,
    PROJECT_MODIFICATION_POLICIES,
    resolve_external_config_path,
)


def test_external_config_path_precedence_and_default_location(tmp_path: Path) -> None:
    override = tmp_path / "override.json"
    xdg_home = tmp_path / "xdg"
    home = tmp_path / "home"

    assert resolve_external_config_path(
        {
            "WAAPI_SKILL_CONFIG_PATH": str(override),
            "XDG_CONFIG_HOME": str(xdg_home),
            "HOME": str(home),
        }
    ) == override
    assert resolve_external_config_path(
        {"XDG_CONFIG_HOME": str(xdg_home), "HOME": str(home)}
    ) == xdg_home / "waapi-skill" / "config.json"
    assert resolve_external_config_path({"HOME": str(home)}) == (
        home / ".config" / "waapi-skill" / "config.json"
    )


def test_external_config_paths_reject_relative_and_tilde_expansion() -> None:
    for environment in (
        {"WAAPI_SKILL_CONFIG_PATH": "relative/config.json"},
        {"WAAPI_SKILL_CONFIG_PATH": "~/.config/waapi-skill/config.json"},
        {"XDG_CONFIG_HOME": "~/.config"},
        {"HOME": "~"},
    ):
        try:
            resolve_external_config_path(environment)
        except ValueError as exc:
            assert "must be an absolute path" in str(exc)
        else:
            raise AssertionError(f"Expected non-absolute config environment to fail: {environment}")


def test_public_external_config_path_rejects_skill_checkout_containment(tmp_path: Path) -> None:
    skill_root = tmp_path / "skill"
    inside = skill_root / "data" / "config.json"

    try:
        resolve_external_config_path(
            {"WAAPI_SKILL_CONFIG_PATH": str(inside)},
            skill_root=skill_root,
        )
    except ValueError as exc:
        assert "outside the Skill checkout" in str(exc)
    else:
        raise AssertionError("Expected checkout-local external config override to fail")


def test_load_defaults_when_config_is_missing(tmp_path) -> None:
    config = SkillConfig.load(tmp_path)

    assert config.skill_root == tmp_path
    assert config.wwise_version is None
    assert config.waapi_host == "127.0.0.1"
    assert config.waapi_port is None
    assert config.project_modification_policy == "ask_before_changes"
    assert config.project_modification_policy == DEFAULT_PROJECT_MODIFICATION_POLICY


def test_save_and_load_roundtrip(tmp_path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config = SkillConfig(tmp_path)
    config.wwise_version = "2024.1"
    config.waapi_host = "localhost"
    config.waapi_port = 8080
    config.project_modification_policy = "allow_changes"

    config.save(config_path)

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload == {
        "waapi_host": "localhost",
        "waapi_port": 8080,
        "project_modification_policy": "allow_changes",
        "wwise_version": "2024.1",
    }

    loaded = SkillConfig.load(tmp_path, config_path)
    assert loaded.wwise_version == "2024.1"
    assert loaded.waapi_host == "localhost"
    assert loaded.waapi_port == 8080
    assert loaded.project_modification_policy == "allow_changes"


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
    assert loaded.project_modification_policy == "read_only"
    assert json.loads(config_path.read_text(encoding="utf-8"))[
        "project_modification_policy"
    ] == "read_only"


@pytest.mark.parametrize(
    ("value", "canonical"),
    (
        ("read_only", "read_only"),
        ("ask_before_changes", "ask_before_changes"),
        ("allow_changes", "allow_changes"),
        ("never", "read_only"),
        ("preview_then_confirm", "ask_before_changes"),
        ("allow_with_notice", "allow_changes"),
    ),
)
def test_update_accepts_canonical_and_legacy_policy_values_but_saves_canonical(
    tmp_path: Path,
    value: str,
    canonical: str,
) -> None:
    config_path = tmp_path / value / "config.json"

    config = SkillConfig(tmp_path).update(
        path=config_path,
        project_modification_policy=value,
    )

    assert config.project_modification_policy == canonical
    assert config.as_dict()["project_modification_policy"] == canonical
    assert json.loads(config_path.read_text(encoding="utf-8"))[
        "project_modification_policy"
    ] == canonical
    assert (
        SkillConfig.load(tmp_path, config_path).project_modification_policy
        == canonical
    )


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    tuple(LEGACY_PROJECT_MODIFICATION_POLICY_ALIASES.items()),
)
def test_save_canonicalizes_legacy_policy_assigned_by_config_set_style_caller(
    tmp_path: Path,
    legacy: str,
    canonical: str,
) -> None:
    config_path = tmp_path / legacy / "config.json"
    config = SkillConfig(tmp_path)
    config.project_modification_policy = legacy

    config.save(config_path)

    assert json.loads(config_path.read_text(encoding="utf-8"))[
        "project_modification_policy"
    ] == canonical


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    tuple(LEGACY_PROJECT_MODIFICATION_POLICY_ALIASES.items()),
)
def test_load_legacy_policy_normalizes_in_memory_without_rewriting_then_update_migrates(
    tmp_path: Path,
    legacy: str,
    canonical: str,
) -> None:
    config_path = tmp_path / legacy / "config.json"
    config_path.parent.mkdir(parents=True)
    original = (
        json.dumps(
            {
                "wwise_version": "2022.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 8080,
                "project_modification_policy": legacy,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    config_path.write_text(original, encoding="utf-8")

    loaded = SkillConfig.load(tmp_path, config_path, strict_fields=True)

    assert loaded.project_modification_policy == canonical
    assert loaded.as_dict()["project_modification_policy"] == canonical
    assert config_path.read_text(encoding="utf-8") == original

    loaded.update(path=config_path, waapi_host="localhost")

    migrated = json.loads(config_path.read_text(encoding="utf-8"))
    assert migrated["waapi_host"] == "localhost"
    assert migrated["project_modification_policy"] == canonical


def test_public_policy_inventory_contains_only_canonical_values() -> None:
    assert PROJECT_MODIFICATION_POLICIES == (
        "read_only",
        "ask_before_changes",
        "allow_changes",
    )
    assert set(PROJECT_MODIFICATION_POLICIES).isdisjoint(
        LEGACY_PROJECT_MODIFICATION_POLICY_ALIASES
    )


@pytest.mark.parametrize("invalid", ("mutating", "", " read_only", None, True))
def test_invalid_project_modification_policy_fails_closed(
    tmp_path: Path,
    invalid: object,
) -> None:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"project_modification_policy": invalid}),
        encoding="utf-8",
    )

    try:
        SkillConfig.load(tmp_path, config_path)
    except ValueError as exc:
        assert "project_modification_policy must be one of" in str(exc)
    else:
        raise AssertionError("Expected invalid policy to raise ValueError")


@pytest.mark.parametrize("invalid", ("mutating", "", "allow_changes ", None, False))
def test_update_rejects_invalid_project_modification_policy(
    tmp_path: Path,
    invalid: object,
) -> None:
    config = SkillConfig(tmp_path)

    try:
        config.update(project_modification_policy=invalid)
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


def test_legacy_internal_field_is_ignored_on_load_and_not_rewritten(tmp_path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": "2022.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 8080,
                "project_modification_policy": "preview_then_confirm",
                "use_current_selection_for_ambiguous_queries": False,
            }
        ),
        encoding="utf-8",
    )

    loaded = SkillConfig.load(tmp_path, config_path)
    assert loaded.wwise_version == "2022.1"
    assert loaded.waapi_port == 8080

    loaded.save(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert "use_current_selection_for_ambiguous_queries" not in payload


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


def test_config_rejects_duplicate_keys_and_non_finite_numbers(tmp_path: Path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True)

    for text, expected in (
        ('{"waapi_port":8080,"waapi_port":9000}', "duplicate key: waapi_port"),
        ('{"waapi_port":NaN}', "non-finite JSON constant: NaN"),
    ):
        config_path.write_text(text, encoding="utf-8")
        try:
            SkillConfig.load(tmp_path, config_path)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"Expected strict config JSON rejection: {text}")


def test_config_rejects_oversized_file_before_json_parse(tmp_path: Path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{" + ("x" * MAX_CONFIG_BYTES) + "}", encoding="utf-8")

    try:
        SkillConfig.load(tmp_path, config_path)
    except ValueError as exc:
        assert f"{MAX_CONFIG_BYTES}-byte" in str(exc)
    else:
        raise AssertionError("Expected oversized config to fail closed")

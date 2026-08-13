from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tests.semantic.support.codex_version_layout_v3 import (
    CodexVersionLayoutError,
    get_codex_version_layout_v3,
    get_version_layout,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
OBJECT_COMPOUND_DATA = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "compound-heavy-v1"
    / "object-create-set.json"
)


def test_reviewed_layouts_expose_exact_hierarchy_and_type_aliases() -> None:
    old = get_version_layout("2022.1")
    new = get_codex_version_layout_v3("2025.1")

    assert old.actor_hierarchy == r"\Actor-Mixer Hierarchy"
    assert old.actor_default_work_unit == (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
    )
    assert old.master_hierarchy == r"\Master-Mixer Hierarchy"
    assert old.master_default_work_unit == (
        r"\Master-Mixer Hierarchy\Default Work Unit"
    )
    assert old.master_audio_bus == (
        r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
    )
    assert old.requested_actor_mixer == old.reflected_actor_mixer == "ActorMixer"

    assert new.actor_hierarchy == r"\Containers"
    assert new.actor_default_work_unit == r"\Containers\Default Work Unit"
    assert new.master_hierarchy == r"\Busses"
    assert new.master_default_work_unit == r"\Busses\Default Work Unit"
    assert new.master_audio_bus == r"\Busses\Default Work Unit\Main Audio Bus"
    assert new.requested_actor_mixer == "ActorMixer"
    assert new.reflected_actor_mixer == "PropertyContainer"
    assert new.reflected_type("ActorMixer") == "PropertyContainer"
    assert new.requested_type("PropertyContainer") == "ActorMixer"
    assert new.reflected_type("Sound") == new.requested_type("Sound") == "Sound"


def test_2025_layout_translates_only_canonical_2022_path_prefixes() -> None:
    layout = get_version_layout("2025.1")

    assert layout.translate_2022_path(
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab"
    ) == r"\Containers\Default Work Unit\SemanticLab"
    assert layout.translate_2022_path(
        r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
    ) == r"\Busses\Default Work Unit\Main Audio Bus"
    assert layout.translate_2022_path(
        r"\Master-Mixer Hierarchy\Default Work Unit\Weapons"
    ) == r"\Busses\Default Work Unit\Weapons"
    assert layout.translate_2022_path(r"\Events\Default Work Unit") == (
        r"\Events\Default Work Unit"
    )
    assert layout.translate_2022_path("Actor-Mixer Hierarchy") == (
        "Actor-Mixer Hierarchy"
    )


def test_layouts_are_immutable_and_unknown_versions_fail_closed() -> None:
    layout = get_version_layout("2025.1")

    with pytest.raises(FrozenInstanceError):
        layout.containers_root = r"\Injected"  # type: ignore[misc]
    assert (
        get_version_layout("2021.1").containers_root
        == get_version_layout("2024.1").containers_root
        == r"\Actor-Mixer Hierarchy"
    )
    with pytest.raises(CodexVersionLayoutError, match="unsupported"):
        get_version_layout("2020.1")


def test_object_compound_data_is_closed_and_cross_version() -> None:
    payload = json.loads(OBJECT_COMPOUND_DATA.read_text(encoding="utf-8"))

    assert set(payload) == {"contract", "cases"}
    assert payload["contract"] == "waapi-skill.codex-compound-heavy-cases/v1"
    assert tuple(row["base_scenario_id"] for row in payload["cases"]) == (
        "OBJ22-F-CREATE-02",
        "OBJ22-F-CREATE-03",
        "OBJ22-F-SET-01",
        "OBJ22-F-SET-02",
    )
    for row in payload["cases"]:
        assert set(row) == {
            "base_scenario_id",
            "api",
            "versions",
            "prompt",
            "confirmation_prompt",
            "fixture_patch",
        }
        assert row["versions"] == ["2022.1", "2025.1"]
        assert len(row["prompt"]) >= 80
        assert "gateway" not in row["prompt"].casefold()
        expected_patch_keys = {"prerequisites", "asset_spec"}
        assert set(row["fixture_patch"]) == expected_patch_keys
        if row["base_scenario_id"] == "OBJ22-F-CREATE-02":
            assert row["fixture_patch"]["asset_spec"] == {
                "identity_binding": {
                    "contract": "waapi-skill.compound-object-identity/v1",
                    "fixture_key": "robot",
                }
            }
        else:
            assert row["fixture_patch"]["asset_spec"] == {
                "metadata_binding": {
                    "contract": "waapi-skill.compound-object-metadata/v1",
                    "queries": ["volume"],
                    "required_tokens": ["Volume"],
                }
            }
            assert "Actor Mixer" in row["prompt"]
        assert len(row["fixture_patch"]["prerequisites"]) == 2

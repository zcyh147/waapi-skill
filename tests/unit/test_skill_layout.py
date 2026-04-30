from __future__ import annotations

from pathlib import Path

import wwise_waapi  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "wwise-waapi"
ROOT_SKILL_ENTRIES = (
    "SKILL.md",
    "wwise_waapi",
    "resources",
    "references",
    "scripts",
    "evals",
    "requirements.txt",
)
LEGACY_SOURCE_DIRS = ("wwise_waapi", "resources", "references")


def test_root_level_skill_layout_is_canonical() -> None:
    for entry in ROOT_SKILL_ENTRIES:
        assert (REPO_ROOT / entry).exists(), entry
    assert (REPO_ROOT / "tests").is_dir()


def test_legacy_nested_source_directories_are_not_active() -> None:
    for entry in LEGACY_SOURCE_DIRS:
        assert not (LEGACY_SKILL_ROOT / entry).exists(), entry


def test_package_imports_from_root_skill_package() -> None:
    assert wwise_waapi.__file__ is not None
    package_path = Path(wwise_waapi.__file__).resolve()

    assert package_path.is_relative_to(REPO_ROOT / "wwise_waapi")
    assert not package_path.is_relative_to(LEGACY_SKILL_ROOT)


def test_project_metadata_does_not_point_at_nested_skill_root() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert ".agents/skills/wwise-waapi" not in pyproject
    assert 'source = ["wwise_waapi", "scripts"]' in pyproject

from __future__ import annotations

import json
from pathlib import Path

import wwise_waapi  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "wwise-waapi"
LEGACY_SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "wwise-waapi"
SKILL_ARTIFACT_ENTRIES = (
    "SKILL.md",
    "wwise_waapi",
    "resources",
    "references",
    "scripts",
    "requirements.txt",
)
ROOT_DEVELOPMENT_ENTRIES = ("tests", "ci", "evals", "references", "pyproject.toml")
ROOT_MOVED_ENTRIES = ("SKILL.md", "wwise_waapi", "resources", "scripts", "requirements.txt")
LEGACY_SOURCE_DIRS = ("wwise_waapi", "resources", "references")


def test_skill_artifact_layout_is_canonical() -> None:
    for entry in SKILL_ARTIFACT_ENTRIES:
        assert (SKILL_ROOT / entry).exists(), entry


def test_root_level_development_workspace_remains_canonical() -> None:
    for entry in ROOT_DEVELOPMENT_ENTRIES:
        assert (REPO_ROOT / entry).exists(), entry
    for entry in ROOT_MOVED_ENTRIES:
        assert not (REPO_ROOT / entry).exists(), entry


def test_legacy_nested_source_directories_are_not_active() -> None:
    for entry in LEGACY_SOURCE_DIRS:
        assert not (LEGACY_SKILL_ROOT / entry).exists(), entry


def test_package_imports_from_skill_artifact_package() -> None:
    assert wwise_waapi.__file__ is not None
    package_path = Path(wwise_waapi.__file__).resolve()

    assert package_path.is_relative_to(SKILL_ROOT / "wwise_waapi")
    assert not package_path.is_relative_to(LEGACY_SKILL_ROOT)


def test_semantic_source_note_references_are_packaged_with_skill() -> None:
    for source_notes_path in sorted((SKILL_ROOT / "resources" / "semantic").glob("*/source_notes.json")):
        payload = json.loads(source_notes_path.read_text(encoding="utf-8"))
        referenced_paths = [payload["protocol"]]
        for note in payload["notes"].values():
            referenced_paths.append(note["gate_evidence_path"])
            referenced_paths.extend(
                source_url for source_url in note["source_urls"] if source_url.startswith("references/")
            )

        for relative_path in set(referenced_paths):
            assert (SKILL_ROOT / relative_path).is_file() or (REPO_ROOT / relative_path).is_file(), (
                f"{source_notes_path}: {relative_path}"
            )


def test_project_metadata_does_not_point_at_nested_skill_root() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert ".agents/skills/wwise-waapi" not in pyproject
    assert "package-mode = false" in pyproject
    assert 'source = ["skills/wwise-waapi/wwise_waapi", "skills/wwise-waapi/scripts"]' in pyproject

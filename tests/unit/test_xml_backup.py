from __future__ import annotations

from pathlib import Path

from wwise_waapi.xml_backup import WAAPI_SKILL_BACKUP_DIR, create_xml_edit_backup, project_root_from_project_info  # pyright: ignore[reportMissingImports]


def test_project_root_from_get_project_info_prefers_directories_root(tmp_path: Path) -> None:
    root = tmp_path / "SampleProject"
    project_info = {
        "result": {
            "path": str(tmp_path / "Other" / "Other.wproj"),
            "directories": {"root": str(root)},
        }
    }

    assert project_root_from_project_info(project_info) == root.resolve()


def test_project_root_from_get_project_info_falls_back_to_wproj_parent(tmp_path: Path) -> None:
    project_path = tmp_path / "SampleProject" / "SampleProject.wproj"

    assert project_root_from_project_info({"path": str(project_path)}) == project_path.parent.resolve()


def test_create_xml_edit_backup_uses_project_root_dot_directory_and_preserves_relative_path(tmp_path: Path) -> None:
    project_root = tmp_path / "SampleProject"
    work_unit = project_root / "Actor-Mixer Hierarchy" / "NYC Ambience.wwu"
    work_unit.parent.mkdir(parents=True)
    work_unit.write_text("<WorkUnit />\n", encoding="utf-8")

    backup = create_xml_edit_backup(work_unit, project_root=project_root, timestamp="20260625-000952")

    assert backup == project_root / WAAPI_SKILL_BACKUP_DIR / "20260625-000952" / "Actor-Mixer Hierarchy" / "NYC Ambience.wwu.bak"
    assert backup.read_text(encoding="utf-8") == "<WorkUnit />\n"


def test_create_xml_edit_backup_uses_project_info_root(tmp_path: Path) -> None:
    project_root = tmp_path / "SampleProject"
    work_unit = project_root / "Containers" / "Default Work Unit.wwu"
    work_unit.parent.mkdir(parents=True)
    work_unit.write_text("<WorkUnit />\n", encoding="utf-8")

    backup = create_xml_edit_backup(
        work_unit,
        project_info={"directories": {"root": str(project_root)}, "path": str(project_root / "SampleProject.wproj")},
        timestamp="20260625-010203",
    )

    assert backup.is_file()
    assert backup.parent == project_root / WAAPI_SKILL_BACKUP_DIR / "20260625-010203" / "Containers"

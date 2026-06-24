from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


WAAPI_SKILL_BACKUP_DIR = ".waapi_skill_backups"


def project_root_from_project_info(project_info: Mapping[str, Any]) -> Path:
    payload = project_info.get("result", project_info)
    if not isinstance(payload, Mapping):
        raise ValueError("project_info must be a mapping or dispatcher result mapping")

    directories = payload.get("directories")
    if isinstance(directories, Mapping):
        root = directories.get("root")
        if isinstance(root, str) and root:
            return Path(root).expanduser().resolve()

    project_path = payload.get("path")
    if isinstance(project_path, str) and project_path:
        return Path(project_path).expanduser().resolve().parent

    raise ValueError("project_info must include directories.root or path")


def create_xml_edit_backup(
    source_path: str | Path,
    *,
    project_root: str | Path | None = None,
    project_info: Mapping[str, Any] | None = None,
    timestamp: str | None = None,
) -> Path:
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"XML source file does not exist: {source}")

    root = _resolve_project_root(project_root=project_root, project_info=project_info)
    relative_source = source.relative_to(root)
    backup_root = root / WAAPI_SKILL_BACKUP_DIR / (timestamp or _timestamp())
    destination = _available_backup_path(backup_root / relative_source.with_name(f"{relative_source.name}.bak"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _resolve_project_root(*, project_root: str | Path | None, project_info: Mapping[str, Any] | None) -> Path:
    if project_root is None:
        if project_info is None:
            raise ValueError("project_root or project_info is required")
        project_root = project_root_from_project_info(project_info)
    return Path(project_root).expanduser().resolve()


def _available_backup_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate unique backup path under {path.parent}")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")

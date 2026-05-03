"""Configuration and path helpers for the Wwise WAAPI skill."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_WWISE_CONSOLE_MACOS = Path(
    "/Applications/Audiokinetic/Wwise2022.1.19.8584/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
WINDOWS_WWISE_CONSOLE_RELATIVE = Path("Authoring") / "x64" / "Release" / "bin" / "WwiseConsole.exe"
PROJECT_MODIFICATION_POLICIES = ("never", "preview_then_confirm", "allow_with_notice")


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

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"


@dataclass(slots=True)
class SkillConfig:
    """Basic configuration for scaffolded Wwise WAAPI workflows."""

    skill_root: Path
    wwise_version: str | None = None
    waapi_host: str = "127.0.0.1"
    waapi_port: int | None = None
    project_modification_policy: str = "preview_then_confirm"
    use_current_selection_for_ambiguous_queries: bool = True
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
    wwise_version_env: str = "WWISE_VERSION"
    wwise_console_env: str = "WWISE_CONSOLE"
    wwise_fixture_project_env: str = "WWISE_FIXTURE_PROJECT"
    wwise_sample_project_path_env: str = "WWISE_SAMPLE_PROJECT_PATH"
    wwise_sandbox_root_env: str = "WWISE_SANDBOX_ROOT"
    wwise_root_env: str = "WWISEROOT"
    default_wwise_console_macos: Path = DEFAULT_WWISE_CONSOLE_MACOS
    windows_wwise_console_relative: Path = WINDOWS_WWISE_CONSOLE_RELATIVE

    def __post_init__(self) -> None:
        self.paths = SkillPaths(self.skill_root)

    @property
    def config_path(self) -> Path:
        return self.paths.config_path

    @classmethod
    def load(cls, skill_root: Path, path: Path | None = None) -> "SkillConfig":
        config = cls(skill_root)
        config_path = path or config.config_path
        if not config_path.exists():
            return config

        with config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, dict):
            raise ValueError("Skill config must be a JSON object")

        config.wwise_version = _load_optional_string(payload, "wwise_version")
        config.waapi_host = _load_string(payload, "waapi_host", default=config.waapi_host)
        config.waapi_port = _load_optional_int(payload, "waapi_port")
        config.project_modification_policy = _load_project_modification_policy(
            payload,
            "project_modification_policy",
            default=config.project_modification_policy,
        )
        config.use_current_selection_for_ambiguous_queries = _load_bool(
            payload,
            "use_current_selection_for_ambiguous_queries",
            default=config.use_current_selection_for_ambiguous_queries,
        )
        return config

    def save(self, path: Path | None = None) -> None:
        config_path = path or self.config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "wwise_version": self.wwise_version,
            "waapi_host": self.waapi_host,
            "waapi_port": self.waapi_port,
            "project_modification_policy": _validate_project_modification_policy(
                self.project_modification_policy
            ),
            "use_current_selection_for_ambiguous_queries": self.use_current_selection_for_ambiguous_queries,
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        os.replace(temp_path, config_path)

    def update(self, path: Path | None = None, **changes: Any) -> "SkillConfig":
        allowed_fields = {
            "wwise_version",
            "waapi_host",
            "waapi_port",
            "project_modification_policy",
            "use_current_selection_for_ambiguous_queries",
        }
        for key in changes:
            if key not in allowed_fields:
                raise ValueError(f"Unsupported config field: {key}")
        for key, value in changes.items():
            if key == "project_modification_policy":
                value = _validate_project_modification_policy(value)
            setattr(self, key, value)
        self.save(path=path)
        return self


def _load_optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _load_string(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _load_optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer or null")
    return value


def _load_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _load_project_modification_policy(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    return _validate_project_modification_policy(value, key=key)


def _validate_project_modification_policy(value: Any, key: str = "project_modification_policy") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be one of: {', '.join(PROJECT_MODIFICATION_POLICIES)}")
    if value not in PROJECT_MODIFICATION_POLICIES:
        raise ValueError(f"{key} must be one of: {', '.join(PROJECT_MODIFICATION_POLICIES)}")
    return value

"""Configuration and path helpers for the Wwise WAAPI skill."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .versions import SUPPORTED_WWISE_VERSION_KEYS


DEFAULT_WWISE_CONSOLE_MACOS = Path(
    "/Applications/Audiokinetic/Wwise2022.1.19.8584/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
WINDOWS_WWISE_CONSOLE_RELATIVE = Path("Authoring") / "x64" / "Release" / "bin" / "WwiseConsole.exe"
PROJECT_MODIFICATION_POLICIES = (
    "read_only",
    "ask_before_changes",
    "allow_changes",
)
LEGACY_PROJECT_MODIFICATION_POLICY_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "never": "read_only",
        "preview_then_confirm": "ask_before_changes",
        "allow_with_notice": "allow_changes",
    }
)
DEFAULT_PROJECT_MODIFICATION_POLICY = "ask_before_changes"
PUBLIC_CONFIG_FIELDS = frozenset(
    {"wwise_version", "waapi_host", "waapi_port", "project_modification_policy"}
)
CONFIG_PATH_ENV = "WAAPI_SKILL_CONFIG_PATH"
XDG_CONFIG_HOME_ENV = "XDG_CONFIG_HOME"
HOME_ENV = "HOME"
EXTERNAL_CONFIG_DIRECTORY = "waapi-skill"
EXTERNAL_CONFIG_FILENAME = "config.json"
MAX_CONFIG_BYTES = 64 * 1024


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
    """Persisted public user configuration for Wwise WAAPI workflows."""

    skill_root: Path
    wwise_version: str | None = None
    waapi_host: str = "127.0.0.1"
    waapi_port: int | None = None
    project_modification_policy: str = DEFAULT_PROJECT_MODIFICATION_POLICY
    paths: SkillPaths = field(init=False)

    def __post_init__(self) -> None:
        self.paths = SkillPaths(self.skill_root)

    @property
    def config_path(self) -> Path:
        return self.paths.config_path

    def as_dict(self) -> dict[str, Any]:
        """Return the validated public configuration surface."""

        return {
            "wwise_version": _validate_wwise_version(self.wwise_version),
            "waapi_host": _validate_waapi_host(self.waapi_host),
            "waapi_port": _validate_waapi_port(self.waapi_port),
            "project_modification_policy": _validate_project_modification_policy(
                self.project_modification_policy
            ),
        }

    @classmethod
    def load(
        cls,
        skill_root: Path,
        path: Path | None = None,
        *,
        strict_fields: bool = False,
    ) -> "SkillConfig":
        config = cls(skill_root)
        config_path = path or config.config_path
        if not config_path.exists():
            return config
        try:
            config_size = config_path.stat().st_size
        except OSError:
            raise
        if config_size > MAX_CONFIG_BYTES:
            raise ValueError(
                f"Skill config exceeds the {MAX_CONFIG_BYTES}-byte public config limit"
            )

        with config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(
                handle,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_json_keys,
            )

        if not isinstance(payload, dict):
            raise ValueError("Skill config must be a JSON object")
        if strict_fields:
            extra_fields = sorted(set(payload) - PUBLIC_CONFIG_FIELDS)
            if extra_fields:
                raise ValueError(
                    "External Skill config contains unsupported fields: "
                    + ", ".join(extra_fields)
                )

        config.wwise_version = _validate_wwise_version(
            _load_optional_string(payload, "wwise_version")
        )
        config.waapi_host = _validate_waapi_host(
            _load_string(payload, "waapi_host", default=config.waapi_host)
        )
        config.waapi_port = _validate_waapi_port(_load_optional_int(payload, "waapi_port"))
        config.project_modification_policy = _load_project_modification_policy(
            payload,
            "project_modification_policy",
            default=config.project_modification_policy,
        )
        return config

    def save(self, path: Path | None = None) -> None:
        config_path = path or self.config_path
        payload = self.as_dict()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
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
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def update(self, path: Path | None = None, **changes: Any) -> "SkillConfig":
        for key in changes:
            if key not in PUBLIC_CONFIG_FIELDS:
                raise ValueError(f"Unsupported config field: {key}")
        for key, value in changes.items():
            if key == "wwise_version":
                value = _validate_wwise_version(value)
            elif key == "waapi_host":
                value = _validate_waapi_host(value)
            elif key == "waapi_port":
                value = _validate_waapi_port(value)
            elif key == "project_modification_policy":
                value = _validate_project_modification_policy(value)
            setattr(self, key, value)
        self.save(path=path)
        return self


@dataclass(frozen=True, slots=True)
class ResolvedSkillConfig:
    """One effective gateway config plus its external/legacy provenance."""

    config: SkillConfig
    source: str
    external_path: Path
    legacy_path: Path
    legacy_fallback_used: bool


def resolve_external_config_path(
    env: Mapping[str, str] | None = None,
    *,
    skill_root: Path | None = None,
) -> Path:
    """Resolve the public config path outside the Skill checkout by default."""

    source_env = os.environ if env is None else env
    override = source_env.get(CONFIG_PATH_ENV)
    if override is not None:
        result = _require_absolute_config_path(override, label=f"${CONFIG_PATH_ENV}")
        return _require_outside_skill_checkout(result, skill_root=skill_root)

    xdg_home = source_env.get(XDG_CONFIG_HOME_ENV)
    if xdg_home:
        base = _require_absolute_config_path(xdg_home, label=f"${XDG_CONFIG_HOME_ENV}")
    else:
        home = source_env.get(HOME_ENV)
        base_home = _require_absolute_config_path(home, label=f"${HOME_ENV}") if home else Path.home()
        base = base_home / ".config"
    result = base / EXTERNAL_CONFIG_DIRECTORY / EXTERNAL_CONFIG_FILENAME
    return _require_outside_skill_checkout(result, skill_root=skill_root)


def load_effective_skill_config(
    skill_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> ResolvedSkillConfig:
    """Load external config first, with a read-only legacy checkout fallback."""

    root = Path(skill_root)
    external_path = resolve_external_config_path(env, skill_root=root)
    legacy_path = SkillPaths(root).config_path
    if external_path.exists():
        config = SkillConfig.load(root, external_path, strict_fields=True)
        source = "external"
        legacy_fallback_used = False
    elif legacy_path.exists():
        config = SkillConfig.load(root, legacy_path)
        source = "legacy"
        legacy_fallback_used = True
    else:
        config = SkillConfig(root)
        source = "defaults"
        legacy_fallback_used = False
    return ResolvedSkillConfig(
        config=config,
        source=source,
        external_path=external_path,
        legacy_path=legacy_path,
        legacy_fallback_used=legacy_fallback_used,
    )


def _load_optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"Skill config contains non-finite JSON constant: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"Skill config contains duplicate key: {key}")
        payload[key] = value
    return payload


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


def _require_absolute_config_path(value: str, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty absolute path")
    # Resolve only paths that are already absolute.  Expanding ``~`` here would
    # consult the Python process' ambient HOME rather than the explicit
    # environment mapping supplied by an isolated caller, which could escape a
    # test or broker-owned config root.
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return path.resolve(strict=False)


def _require_outside_skill_checkout(path: Path, *, skill_root: Path | None) -> Path:
    if skill_root is None:
        return path
    root = Path(skill_root).expanduser().resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return path
    raise ValueError(
        f"Public external config path must be outside the Skill checkout: {path}"
    )


def _validate_wwise_version(value: Any, key: str = "wwise_version") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in SUPPORTED_WWISE_VERSION_KEYS:
        raise ValueError(
            f"{key} must be null or one of: {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    return value


def _validate_waapi_host(value: Any, key: str = "waapi_host") -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{key} must be a non-empty host name or IP address")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError(f"{key} must not contain whitespace or control characters")
    if "://" in value or any(character in value for character in "/?#"):
        raise ValueError(f"{key} must be a host name or IP address, not a URL")
    if ":" in value and not (value.startswith("[") and value.endswith("]")):
        raise ValueError(f"{key} IPv6 addresses must use bracketed form, for example [::1]")
    return value


def _validate_waapi_port(value: Any, key: str = "waapi_port") -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer or null")
    if not 1 <= value <= 65535:
        raise ValueError(f"{key} must be between 1 and 65535")
    return value


def _load_project_modification_policy(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    return _validate_project_modification_policy(value, key=key)


def _validate_project_modification_policy(value: Any, key: str = "project_modification_policy") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be one of: {', '.join(PROJECT_MODIFICATION_POLICIES)}")
    canonical = LEGACY_PROJECT_MODIFICATION_POLICY_ALIASES.get(value, value)
    if canonical not in PROJECT_MODIFICATION_POLICIES:
        raise ValueError(f"{key} must be one of: {', '.join(PROJECT_MODIFICATION_POLICIES)}")
    return canonical

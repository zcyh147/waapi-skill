"""Stable user-facing APIs for the Wwise WAAPI skill runtime."""

from .config import SkillConfig, SkillPaths
from .deferred_registry import DeferredRegistry
from .dispatcher import DispatcherRequest, WwiseDispatcher
from .headless import HeadlessLifecycle
from .manifest import ManifestAudit, ManifestStore, ReflectionManifestBuilder, WaapiReflectionClient
from .platform_paths import (  # pyright: ignore[reportMissingImports]
    WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE,
    build_wwise_console_command,
    resolve_windows_wwise_console_from_env,
    windows_wwise_console_path,
)
from .subscriptions import SubscriptionManager
from .xml_backup import WAAPI_SKILL_BACKUP_DIR, create_xml_edit_backup, project_root_from_project_info
from .waql import (  # pyright: ignore[reportMissingImports]
    WAQL_EXAMPLES,
    WaqlReferenceGate,
    WaqlReferenceStatus,
    require_waql_helper_generation,
    validate_stored_waql_examples,
    validate_waql_example,
    waql_api_uris,
)

__all__ = [
    "DeferredRegistry",
    "DispatcherRequest",
    "HeadlessLifecycle",
    "ManifestAudit",
    "ManifestStore",
    "ReflectionManifestBuilder",
    "SkillConfig",
    "SkillPaths",
    "SubscriptionManager",
    "WAQL_EXAMPLES",
    "WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE",
    "WaapiReflectionClient",
    "WaqlReferenceGate",
    "WaqlReferenceStatus",
    "WwiseDispatcher",
    "WAAPI_SKILL_BACKUP_DIR",
    "build_wwise_console_command",
    "create_xml_edit_backup",
    "project_root_from_project_info",
    "require_waql_helper_generation",
    "resolve_windows_wwise_console_from_env",
    "validate_stored_waql_examples",
    "validate_waql_example",
    "waql_api_uris",
    "windows_wwise_console_path",
]

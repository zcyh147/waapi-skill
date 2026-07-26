"""Stable user-facing APIs for the Wwise WAAPI skill runtime."""

from .authoring_ui_commands_manifest import (
    AUTHORING_UI_COMMAND_URIS,
    AuthoringUiCommandsSupplement,
    AuthoringUiCommandsSupplementAudit,
    AuthoringUiCommandsSupplementError,
    AuthoringUiCommandsSupplementMissingError,
    build_authoring_ui_commands_supplement,
    manifest_inventory_sha256,
    merge_authoring_ui_commands_surface,
)
from .config import SkillConfig, SkillPaths
from .deferred_registry import DeferredRegistry
from .dispatcher import DispatcherRequest, WwiseDispatcher
from .headless import HeadlessLifecycle
from .manifest import (
    ManifestAudit,
    ManifestStore,
    ReflectionManifestBuilder,
    WaapiReflectionClient,
)
from .platform_paths import (  # pyright: ignore[reportMissingImports]
    WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE,
    build_wwise_console_command,
    resolve_windows_wwise_console_from_env,
    windows_wwise_console_path,
)
from .subscriptions import SubscriptionManager
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
    "AUTHORING_UI_COMMAND_URIS",
    "AuthoringUiCommandsSupplement",
    "AuthoringUiCommandsSupplementAudit",
    "AuthoringUiCommandsSupplementError",
    "AuthoringUiCommandsSupplementMissingError",
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
    "build_authoring_ui_commands_supplement",
    "build_wwise_console_command",
    "manifest_inventory_sha256",
    "merge_authoring_ui_commands_surface",
    "require_waql_helper_generation",
    "resolve_windows_wwise_console_from_env",
    "validate_stored_waql_examples",
    "validate_waql_example",
    "waql_api_uris",
    "windows_wwise_console_path",
]

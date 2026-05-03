"""Stable user-facing APIs for the Wwise WAAPI skill runtime."""

from .config import SkillConfig, SkillPaths
from .deferred_registry import DeferredRegistry
from .dispatcher import DispatcherRequest, WwiseDispatcher
from .headless import HeadlessLifecycle
from .live_environment import (  # pyright: ignore[reportMissingImports]
    DEFAULT_SAMPLE_PROJECT_ROOT,
    ENV_WWISE_SAMPLE_PROJECT_PATH,
    ENV_WWISE_SANDBOX_ROOT,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    parse_live_environment,
    require_destructive_environment,
    require_live_environment,
)
from .manifest import ManifestAudit, ManifestStore, ReflectionManifestBuilder, WaapiReflectionClient
from .notebooklm_gate import (  # pyright: ignore[reportMissingImports]
    NotebookLMGate,
    NotebookLMGateStatus,
    docs_generation_allowed,
    require_docs_generation,
)
from .platform_paths import (  # pyright: ignore[reportMissingImports]
    WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE,
    build_wwise_console_command,
    resolve_windows_wwise_console_from_env,
    windows_wwise_console_path,
)
from .sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxFixtureError,
    SandboxProject,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
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
    "DEFAULT_SAMPLE_PROJECT_ROOT",
    "DeferredRegistry",
    "DispatcherRequest",
    "ENV_WWISE_SAMPLE_PROJECT_PATH",
    "ENV_WWISE_SANDBOX_ROOT",
    "HeadlessLifecycle",
    "LiveEnvironmentContract",
    "LiveEnvironmentError",
    "LiveSandboxLock",
    "ManifestAudit",
    "ManifestStore",
    "NotebookLMGate",
    "NotebookLMGateStatus",
    "ReflectionManifestBuilder",
    "SandboxFixtureError",
    "SandboxProject",
    "SkillConfig",
    "SkillPaths",
    "SubscriptionManager",
    "WAQL_EXAMPLES",
    "WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE",
    "WaapiReflectionClient",
    "WaqlReferenceGate",
    "WaqlReferenceStatus",
    "WwiseDispatcher",
    "build_wwise_console_command",
    "cleanup_sandbox",
    "docs_generation_allowed",
    "launch_sandboxed_wwise",
    "parse_live_environment",
    "prepare_sample_project_sandbox",
    "require_destructive_environment",
    "require_docs_generation",
    "require_live_environment",
    "require_waql_helper_generation",
    "resolve_windows_wwise_console_from_env",
    "shutdown_sandboxed_wwise",
    "validate_stored_waql_examples",
    "validate_waql_example",
    "waql_api_uris",
    "windows_wwise_console_path",
]

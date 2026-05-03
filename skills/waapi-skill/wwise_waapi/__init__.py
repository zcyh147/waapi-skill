"""Wwise WAAPI package skeleton."""

from .config import SkillConfig, SkillPaths
from .api_coverage_audit import (  # pyright: ignore[reportMissingImports]
    ApiCoverageAuditor,
    ApiCoverageAuditResult,
    BehavioralCoverageRecord,
)
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
from .sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxFixtureError,
    SandboxProject,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
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
from .windows_gate import (  # pyright: ignore[reportMissingImports]
    WindowsValidationGate,
    WindowsValidationStatus,
    windows_validation_status,
)

__all__ = [
    "DeferredRegistry",
    "DispatcherRequest",
    "ApiCoverageAuditor",
    "ApiCoverageAuditResult",
    "BehavioralCoverageRecord",
    "HeadlessLifecycle",
    "DEFAULT_SAMPLE_PROJECT_ROOT",
    "ENV_WWISE_SAMPLE_PROJECT_PATH",
    "ENV_WWISE_SANDBOX_ROOT",
    "LiveEnvironmentContract",
    "LiveEnvironmentError",
    "ManifestAudit",
    "ManifestStore",
    "NotebookLMGate",
    "NotebookLMGateStatus",
    "WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE",
    "docs_generation_allowed",
    "require_docs_generation",
    "LiveSandboxLock",
    "SandboxFixtureError",
    "SandboxProject",
    "SkillConfig",
    "SkillPaths",
    "SubscriptionManager",
    "WindowsValidationGate",
    "WindowsValidationStatus",
    "ReflectionManifestBuilder",
    "WaapiReflectionClient",
    "WAQL_EXAMPLES",
    "WaqlReferenceGate",
    "WaqlReferenceStatus",
    "require_waql_helper_generation",
    "validate_stored_waql_examples",
    "validate_waql_example",
    "waql_api_uris",
    "build_wwise_console_command",
    "cleanup_sandbox",
    "launch_sandboxed_wwise",
    "parse_live_environment",
    "prepare_sample_project_sandbox",
    "shutdown_sandboxed_wwise",
    "require_destructive_environment",
    "require_live_environment",
    "resolve_windows_wwise_console_from_env",
    "windows_validation_status",
    "windows_wwise_console_path",
    "WwiseDispatcher",
]

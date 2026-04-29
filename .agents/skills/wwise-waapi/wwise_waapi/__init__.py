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
    "ManifestAudit",
    "ManifestStore",
    "NotebookLMGate",
    "NotebookLMGateStatus",
    "WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE",
    "docs_generation_allowed",
    "require_docs_generation",
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
    "resolve_windows_wwise_console_from_env",
    "windows_validation_status",
    "windows_wwise_console_path",
    "WwiseDispatcher",
]

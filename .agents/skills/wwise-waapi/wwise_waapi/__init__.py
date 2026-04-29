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
from .subscriptions import SubscriptionManager

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
    "docs_generation_allowed",
    "require_docs_generation",
    "SkillConfig",
    "SkillPaths",
    "SubscriptionManager",
    "ReflectionManifestBuilder",
    "WaapiReflectionClient",
    "WwiseDispatcher",
]

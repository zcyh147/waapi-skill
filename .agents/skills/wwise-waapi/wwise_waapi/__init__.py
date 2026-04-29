"""Wwise WAAPI package skeleton."""

from .config import SkillConfig, SkillPaths
from .deferred_registry import DeferredRegistry
from .dispatcher import WwiseDispatcher
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

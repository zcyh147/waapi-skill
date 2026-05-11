"""Scenario definitions for OpenCode-driven WAAPI semantic batches."""

from .phase3 import (
    PUBLIC_CONFIG_FIELDS,
    SUPPORTED_WWISE_VERSIONS,
    SemanticScenario,
    ScenarioVerdict,
    evaluate_scenario_output,
    phase3_scenarios,
    scenarios_for_set,
)

__all__ = [
    "PUBLIC_CONFIG_FIELDS",
    "SUPPORTED_WWISE_VERSIONS",
    "SemanticScenario",
    "ScenarioVerdict",
    "evaluate_scenario_output",
    "phase3_scenarios",
    "scenarios_for_set",
]

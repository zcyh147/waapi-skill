from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

EVIDENCE_PATH = Path(".waapi-skill-state/evidence/task-6-subscription-timeout.md")


@pytest.mark.live
def test_live_subscription_smoke_requires_deterministic_event_source() -> None:
    """Task 6 live subscription smoke is deferred unless a deterministic publisher is provided."""

    topic = os.getenv("WWISE_SUBSCRIPTION_SMOKE_TOPIC")
    if not topic:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(
            "# Task 6 subscription live smoke deferral\n\n"
            "Status: deferred\n\n"
            "Reason: no deterministic WAAPI topic event source was provided via "
            "WWISE_SUBSCRIPTION_SMOKE_TOPIC, so a bounded live wait would only test timing luck.\n",
            encoding="utf-8",
        )
        pytest.skip("WWISE_SUBSCRIPTION_SMOKE_TOPIC is required for deterministic live subscription smoke")

    pytest.skip(f"Deterministic publisher for {topic!r} is not yet defined by the live fixture")

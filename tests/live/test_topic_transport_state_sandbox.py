from __future__ import annotations

import os

import pytest  # pyright: ignore[reportMissingImports]


if os.getenv("WWISE_LIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 is required for transport Topic sandbox tests",
        allow_module_level=True,
    )

VERSION = os.getenv("WWISE_VERSION")
if VERSION not in {"2022.1", "2025.1"}:
    pytest.skip(
        "transport Topic proportional evidence is scoped to 2022.1 and 2025.1",
        allow_module_level=True,
    )

from tests.live.versioned_object_topics_sandbox import (  # pyright: ignore[reportMissingImports]
    run_versioned_transport_topic,
)


@pytest.mark.live
def test_transport_state_changed_emits_exact_matching_event() -> None:
    assert VERSION is not None
    run_versioned_transport_topic(VERSION, __file__)

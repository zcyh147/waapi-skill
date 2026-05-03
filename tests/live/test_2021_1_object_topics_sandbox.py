from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


VERSION = "2021.1"

if os.getenv("WWISE_LIVE") != "1":
    pytest.skip("WWISE_LIVE=1 is required for 2021.1 live object/topic sandbox tests", allow_module_level=True)
if os.getenv("WWISE_VERSION") != VERSION:
    pytest.skip("WWISE_VERSION=2021.1 is required for 2021.1 live object/topic sandbox tests", allow_module_level=True)

from tests.live.versioned_object_topics_sandbox import run_versioned_topic_plan  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / VERSION / "task-8-object-topic-live-plan.json"


@pytest.mark.live
def test_2021_1_live_safe_object_topics_against_sandbox() -> None:
    run_versioned_topic_plan(VERSION, PLAN_PATH, __file__)

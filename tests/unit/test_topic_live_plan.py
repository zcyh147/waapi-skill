"""Representative live-plan inputs compile through the existing topic boundary."""
from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ROOT = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities"
TASK_8_PLAN_PATHS = {"2021.1": CAPABILITY_ROOT / "2021.1" / "task-8-object-topic-live-plan.json"}
TASK_91_PLAN_PATH = CAPABILITY_ROOT / "2022.1" / "task-91-topic-business-live-plan.json"


def test_property_changed_subscription_options_render_disposable_object_id() -> None:
    case = _task8_topic_case(TASK_8_PLAN_PATHS["2021.1"], "ak.wwise.core.object.propertyChanged")
    subscription_options = getattr(import_module("tests.live.versioned_object_topics_sandbox"), "_subscription_options")

    rendered = subscription_options(case, {"object": "{12345678-1234-1234-1234-123456789abc}"})

    assert rendered == {
        "return": ["id", "name", "type", "path", "notes", "Volume"],
        "object": "{12345678-1234-1234-1234-123456789abc}",
        "property": "Volume",
    }
    assert "object" not in case["subscription_options"]


def test_task_91_plan_compiles_public_business_options_and_match() -> None:
    plan = _task8_plan(TASK_91_PLAN_PATH)
    case = next(
        item
        for item in plan["topic_cases"]
        if item["uri"] == "ak.wwise.core.object.propertyChanged"
    )
    module = import_module("tests.live.versioned_object_topics_sandbox")
    render_options = getattr(module, "_subscription_options")
    compile_business = getattr(module, "_business_subscription_inputs")
    object_id = "{12345678-1234-1234-1234-123456789abc}"

    business = compile_business(
        "2022.1",
        case,
        render_options(case, {"object": object_id}),
    )

    assert business.options == {
        "return": ["id", "name", "type", "path", "notes", "Volume"],
        "object": object_id,
        "property": "Volume",
    }
    assert business.match == {"new": -3.0}
    assert business.option_request.schema_digest
    assert business.match_request.schema_digest


def _task8_plan(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task8_topic_case(path: Path, uri: str) -> Mapping[str, Any]:
    for case in _task8_plan(path)["topic_cases"]:
        if case["uri"] == uri:
            return case
    raise AssertionError(f"missing Task 8 topic case {uri} in {path}")

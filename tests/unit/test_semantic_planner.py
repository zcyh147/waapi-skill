from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import SemanticErrorCode, SemanticValidationError  # pyright: ignore[reportMissingImports]
from wwise_waapi.semantic_planner import (  # pyright: ignore[reportMissingImports]
    SemanticIntent,
    SemanticIntentConstraint,
    SemanticIntentTarget,
    SemanticPlan,
    SemanticPlanner,
    SUPPORTED_SEMANTIC_FAMILIES,
)


def structured_query_intent() -> SemanticIntent:
    return SemanticIntent(
        family="intent_navigation",
        goal="List quiet sounds for review.",
        version="2022.1",
        targets=(SemanticIntentTarget("type", "Sound", metadata={"return": ("id", "name", "path")}),),
        constraints=(SemanticIntentConstraint("@Volume", "<", 0, reason="find quiet sounds"),),
        requested_operations=("object.get",),
        confirmation_state="preview",
        source_prompt_excerpt="list quiet Sound objects",
    )


def test_supported_semantic_families_match_plan_vocabulary() -> None:
    assert SUPPORTED_SEMANTIC_FAMILIES == (
        "intent_navigation",
        "crud_authoring",
        "system_design_preview",
        "asset_import_workflow",
        "soundbank_workflow",
        "switch_assignment_workflow",
        "bounded_profiler_guidance",
        "unsupported_runtime_boundary",
    )


def test_semantic_intent_requires_structured_family_and_goal() -> None:
    intent = structured_query_intent()

    assert intent.as_dict() == {
        "family": "intent_navigation",
        "goal": "List quiet sounds for review.",
        "version": "2022.1",
        "targets": [
            {
                "kind": "type",
                "identifier": "Sound",
                "display_name": "",
                "metadata": {"return": ["id", "name", "path"]},
            }
        ],
        "constraints": [{"field": "@Volume", "operator": "<", "value": 0, "reason": "find quiet sounds"}],
        "requested_operations": ["object.get"],
        "confirmation_state": "preview",
        "source_prompt_excerpt": "list quiet Sound objects",
    }

    with pytest.raises(SemanticValidationError) as missing_goal:
        SemanticIntent(
            family="intent_navigation",
            goal="",
            version="2022.1",
            targets=(),
            constraints=(),
            requested_operations=(),
            confirmation_state="preview",
            source_prompt_excerpt="",
        )
    assert missing_goal.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert missing_goal.value.details == {"field": "goal"}


def test_semantic_plan_serializes_preview_hash_and_verification_steps() -> None:
    plan = SemanticPlan(
        status="ready",
        family="intent_navigation",
        version="2022.1",
        steps=(
            {
                "step_id": "query-sounds",
                "operation": "object.get",
                "family": "intent_navigation",
                "preview": {
                    "preview_id": "preview-query-sounds",
                    "preview_hash": "sha256:abc123",
                    "summary": "Read-only Sound query preview.",
                    "payload": {"return": ("id", "name")},
                },
                "inputs": {"type": "Sound"},
                "source_builder_ref": "wwise_waapi.builders.query.build_object_get_query",
            },
        ),
        preview_id="preview-query-sounds",
        preview_hash="sha256:abc123",
        risk_flags=("read-only",),
        requires_confirmation=False,
        blocked_reason="",
        needs_clarification=False,
        unsupported_capability=False,
        verification_steps=(
            {
                "kind": "readback",
                "description": "Read back the generated object rows.",
                "preview_hash": "sha256:abc123",
                "readback_plan": {"uri": "ak.wwise.core.object.get", "options": {"return": ("id", "name")}},
            },
        ),
        source_builder_refs=("wwise_waapi.builders.query.build_object_get_query",),
    )

    assert plan.as_dict() == {
        "status": "ready",
        "family": "intent_navigation",
        "version": "2022.1",
        "steps": [
            {
                "step_id": "query-sounds",
                "operation": "object.get",
                "family": "intent_navigation",
                "preview": {
                    "preview_id": "preview-query-sounds",
                    "preview_hash": "sha256:abc123",
                    "summary": "Read-only Sound query preview.",
                    "payload": {"return": ["id", "name"]},
                },
                "inputs": {"type": "Sound"},
                "source_builder_ref": "wwise_waapi.builders.query.build_object_get_query",
            }
        ],
        "preview_id": "preview-query-sounds",
        "preview_hash": "sha256:abc123",
        "risk_flags": ["read-only"],
        "requires_confirmation": False,
        "blocked_reason": "",
        "needs_clarification": False,
        "unsupported_capability": False,
        "verification_steps": [
            {
                "kind": "readback",
                "description": "Read back the generated object rows.",
                "preview_hash": "sha256:abc123",
                "readback_plan": {"uri": "ak.wwise.core.object.get", "options": {"return": ["id", "name"]}},
            }
        ],
        "source_builder_refs": ["wwise_waapi.builders.query.build_object_get_query"],
    }
    assert json.loads(json.dumps(plan.as_dict(), sort_keys=True))["preview_hash"] == "sha256:abc123"


def test_planner_rejects_raw_natural_language_input() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        SemanticPlanner().plan("list all Sound objects")  # type: ignore[arg-type]

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details == {"expected": "SemanticIntent", "received": "str"}


def test_semantic_intent_rejects_unknown_family() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        SemanticIntent(
            family="raw-waapi",
            goal="List sounds.",
            version="2022.1",
            targets=(),
            constraints=(),
            requested_operations=(),
            confirmation_state="preview",
            source_prompt_excerpt="list sounds",
        )

    assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY
    assert exc.value.details["family"] == "raw-waapi"


def test_semantic_intent_rejects_unknown_confirmation_state() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        SemanticIntent(
            family="intent_navigation",
            goal="List sounds.",
            version="2022.1",
            targets=(),
            constraints=(),
            requested_operations=(),
            confirmation_state="approved",
            source_prompt_excerpt="list sounds",
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["confirmation_state"] == "approved"


def test_schema_only_planner_returns_blocked_structured_plan_for_valid_intent() -> None:
    plan = SemanticPlanner().plan(structured_query_intent())

    assert plan.as_dict() == {
        "status": "needs_clarification",
        "family": "intent_navigation",
        "version": "2022.1",
        "steps": [],
        "preview_id": "",
        "preview_hash": "",
        "risk_flags": [],
        "requires_confirmation": True,
        "blocked_reason": "schema-only planner has not routed intent to a builder",
        "needs_clarification": True,
        "unsupported_capability": False,
        "verification_steps": [],
        "source_builder_refs": [],
    }

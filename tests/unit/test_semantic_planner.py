from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import SemanticErrorCode, SemanticValidationError  # pyright: ignore[reportMissingImports]
from wwise_waapi.semantic_planner import (  # pyright: ignore[reportMissingImports]
    SEMANTIC_FAMILY_BUILDER_REFS,
    SemanticIntent,
    SemanticIntentConstraint,
    SemanticIntentTarget,
    SemanticPlan,
    SemanticPlanStatus,
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
                "builder_ref": "wwise_waapi.builders.query.build_object_get_query",
                "api": "ak.wwise.core.object.get",
                "args_preview": {"waql": "from type Sound"},
                "options_preview": {"return": ("id", "name")},
                "target_identity": {"kind": "type", "identifier": "Sound"},
                "read_only": True,
                "project_changing": False,
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
                "builder_ref": "wwise_waapi.builders.query.build_object_get_query",
                "api": "ak.wwise.core.object.get",
                "args_preview": {"waql": "from type Sound"},
                "options_preview": {"return": ["id", "name"]},
                "target_identity": {"kind": "type", "identifier": "Sound"},
                "read_only": True,
                "project_changing": False,
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


def test_navigation_intent_builds_object_get_step() -> None:
    plan = SemanticPlanner().plan(structured_query_intent())

    assert plan.status is SemanticPlanStatus.READY
    assert plan.requires_confirmation is False
    assert plan.needs_clarification is False
    assert plan.preview_hash.startswith("sha256:")
    assert tuple(plan.source_builder_refs) == ("wwise_waapi.builders.query",)

    step = plan.as_dict()["steps"][0]
    assert step["builder_ref"] == "wwise_waapi.builders.query.build_object_get_query"
    assert step["source_builder_ref"] == "wwise_waapi.builders.query.build_object_get_query"
    assert step["api"] == "ak.wwise.core.object.get"
    assert step["args_preview"] == {"waql": "from type Sound where @Volume < 0"}
    assert step["options_preview"] == {"return": ["id", "name", "path"]}
    assert step["target_identity"]["kind"] == "type"
    assert step["read_only"] is True
    assert step["project_changing"] is False


def semantic_intent_for_family(family: str, *, confirmation_state: str = "preview") -> SemanticIntent:
    return SemanticIntent(
        family=family,
        goal=f"Route {family} intent.",
        version="2022.1",
        targets=(),
        constraints=(),
        requested_operations=(),
        confirmation_state=confirmation_state,
        source_prompt_excerpt="structured semantic planner test",
    )


def unsafe_semantic_intent_with_family(family: str) -> SemanticIntent:
    intent = object.__new__(SemanticIntent)
    object.__setattr__(intent, "family", family)
    object.__setattr__(intent, "goal", "Bypass constructor to test planner fail-closed routing.")
    object.__setattr__(intent, "version", "2022.1")
    object.__setattr__(intent, "targets", ())
    object.__setattr__(intent, "constraints", ())
    object.__setattr__(intent, "requested_operations", ())
    object.__setattr__(intent, "confirmation_state", "preview")
    object.__setattr__(intent, "source_prompt_excerpt", "unknown family")
    return intent


def test_planner_routes_all_supported_families_to_builder_refs() -> None:
    planner = SemanticPlanner()

    assert tuple(SEMANTIC_FAMILY_BUILDER_REFS) == SUPPORTED_SEMANTIC_FAMILIES
    for family in SUPPORTED_SEMANTIC_FAMILIES:
        plan = planner.plan(semantic_intent_for_family(family))

        assert plan.family == family
        assert tuple(plan.source_builder_refs) == SEMANTIC_FAMILY_BUILDER_REFS[family]
        if family == "unsupported_runtime_boundary":
            assert plan.status is SemanticPlanStatus.UNSUPPORTED
            assert plan.unsupported_capability is True
            assert tuple(plan.steps) == ()
        else:
            assert plan.status in {SemanticPlanStatus.READY, SemanticPlanStatus.NEEDS_CLARIFICATION}
            assert plan.unsupported_capability is False
            assert plan.source_builder_refs


def test_planner_blocks_unknown_family_without_guessing() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        SemanticPlanner().plan(unsafe_semantic_intent_with_family("runtime_scheduler"))

    assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY
    assert exc.value.details["family"] == "runtime_scheduler"


def test_crud_authoring_routes_to_object_and_property_builders() -> None:
    plan = SemanticPlanner().plan(semantic_intent_for_family("crud_authoring", confirmation_state="confirmed"))

    assert plan.status is SemanticPlanStatus.NEEDS_CLARIFICATION
    assert plan.requires_confirmation is False
    assert {step.builder_ref for step in plan.steps} == {
        "wwise_waapi.builders.object_mutation.build_object_mutation_preview",
        "wwise_waapi.builders.properties.build_set_name_preview",
        "wwise_waapi.builders.properties.build_set_property_preview",
    }
    assert all(step.project_changing for step in plan.steps)
    assert tuple(plan.source_builder_refs) == (
        "wwise_waapi.builders.object_mutation",
        "wwise_waapi.builders.properties",
    )


def test_system_design_preview_decomposes_into_safe_candidate_steps() -> None:
    intent = SemanticIntent(
        family="system_design_preview",
        goal="Plan a foley ambience system preview.",
        version="2022.1",
        targets=(SemanticIntentTarget("path", "\\Actor-Mixer Hierarchy\\Default Work Unit", metadata={"design_type": "foley"}),),
        constraints=(),
        requested_operations=(),
        confirmation_state="preview",
        source_prompt_excerpt="plan foley ambience system",
    )

    plan = SemanticPlanner().plan(intent)
    steps = plan.as_dict()["steps"]

    assert plan.status is SemanticPlanStatus.NEEDS_CLARIFICATION
    assert plan.requires_confirmation is True
    assert [step["operation"] for step in steps] == ["object.get", "object.create", "setNotes", "audio.import"]
    assert steps[0]["read_only"] is True
    assert all(step["inputs"]["candidate_only"] is True for step in steps)
    assert all("missing_structured_input" in step["inputs"] for step in steps)
    assert not any(step["inputs"].get("live_dispatch") for step in steps)


def test_planner_steps_have_builder_provenance() -> None:
    planner = SemanticPlanner()
    families = (
        "intent_navigation",
        "crud_authoring",
        "asset_import_workflow",
        "soundbank_workflow",
        "switch_assignment_workflow",
        "bounded_profiler_guidance",
    )

    for family in families:
        intent = structured_query_intent() if family == "intent_navigation" else semantic_intent_for_family(family)
        plan = planner.plan(intent)

        assert plan.steps
        for step in plan.as_dict()["steps"]:
            assert step["builder_ref"]
            assert step["source_builder_ref"] == step["builder_ref"]
            assert "args_preview" in step
            assert "options_preview" in step
            assert "target_identity" in step
            assert isinstance(step["read_only"], bool)
            assert isinstance(step["project_changing"], bool)


def test_runtime_scheduler_family_returns_unsupported_plan() -> None:
    plan = SemanticPlanner().plan(semantic_intent_for_family("unsupported_runtime_boundary"))

    assert plan.status is SemanticPlanStatus.UNSUPPORTED
    assert plan.unsupported_capability is True
    assert tuple(plan.steps) == ()
    assert tuple(plan.source_builder_refs) == ()
    assert tuple(plan.risk_flags) == ()
    assert plan.requires_confirmation is False

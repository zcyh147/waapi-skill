from __future__ import annotations

import re
from pathlib import Path


SKILL_MD = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "SKILL.md"

SEMANTIC_FAMILIES = [
    "intent_navigation",
    "crud_authoring",
    "system_design_preview",
    "asset_import_workflow",
    "soundbank_workflow",
    "switch_assignment_workflow",
    "bounded_profiler_guidance",
    "unsupported_runtime_boundary",
]


def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def protocol_section() -> str:
    text = skill_text()
    start = text.index("## Operator protocol")
    end = text.index("## Setup and runner")
    return text[start:end]


def semantic_builders_section() -> str:
    text = skill_text()
    start = text.index("## Semantic builders")
    end = text.index("## Safety guardrails")
    return text[start:end]


def test_semantic_protocol_is_closed_and_before_implementation_details() -> None:
    text = skill_text()
    protocol = protocol_section()

    assert text.index("## Operator protocol") < text.index("## Setup and runner")
    assert "closed semantic-intent protocol" in protocol
    assert "Do not invent intent families" in protocol
    assert "Extract one structured `SemanticIntent`" in protocol
    assert "call `SemanticPlanner.plan()`" in protocol
    assert "present the resulting `SemanticPlan` preview" in protocol
    assert "Even read-only navigation and unsupported boundary requests still pass through `SemanticPlanner.plan()`" in protocol
    assert "SemanticPlanner().plan(intent)" in protocol
    assert "wwise_waapi.semantic_planner" in protocol
    assert "plan.verification_status" not in protocol

    for family in SEMANTIC_FAMILIES:
        assert f"`{family}`" in protocol


def test_protocol_documents_intent_to_planner_to_preview_to_confirm_to_verify() -> None:
    protocol = protocol_section()

    required_sequence = [
        "Extract `SemanticIntent`",
        "Route CRUD requests at the semantic family level",
        "Present the `SemanticPlan` preview",
        "Confirm with `confirm_semantic_plan(preview, confirmation_state, submitted_preview_hash)`",
        "Execute only the confirmed plan whose hash matched the preview shown to the user",
        "Verify after execution",
    ]

    positions = [protocol.index(item) for item in required_sequence]
    assert positions == sorted(positions)


def test_project_changing_steps_require_matching_preview_hash() -> None:
    protocol = protocol_section()

    assert "before project-changing work" in protocol
    assert "`preview_hash`" in protocol
    assert "submitted_preview_hash = confirmation_response.preview_hash" in protocol
    assert "submitted_preview_hash=plan.preview_hash" not in protocol
    assert "not copied from the preview object by construction" in protocol
    assert "`confirmation_state` is `confirmed`" in protocol
    assert "`submitted_preview_hash` exactly matches the current preview hash" in protocol
    assert "Missing or mismatched hashes require a fresh preview" in protocol
    assert "target identity" in protocol
    assert "planned API" in protocol
    assert "payload preview" in protocol
    assert "abort and re-preview" in protocol


def test_semantic_runs_must_emit_machine_readable_planner_facts() -> None:
    protocol = protocol_section()

    for field in [
        "structured_intent_extracted",
        "semantic_family",
        "semantic_planner_invoked",
        "semantic_plan_status",
        "preview_hash",
        "source_builder_refs",
        "unsupported_boundary_returned",
        "unsupported_boundary_reason",
        "mutation_executed",
        "mutation_executed_before_confirmation",
        "verification_status",
    ]:
        assert f"`{field}`" in protocol
    assert "SEMANTIC_RESULT_JSON" in protocol
    assert "live WAAPI may supplement or verify the plan" in protocol
    assert "verification_steps" in protocol


def test_crud_guidance_stays_at_semantic_family_level_without_raw_payload_sprawl() -> None:
    protocol = protocol_section()
    builders = semantic_builders_section()
    text = protocol + builders

    assert "Route CRUD requests at the semantic family level" in protocol
    assert "Do not paste raw WAAPI payload schemas into the prompt" in protocol
    assert "`crud_authoring`: create, set, delete, copy, move, property, reference" in builders

    low_level_family_lines = re.findall(
        r"^\d+\. `(?:query|object-mutation|property-reference|import|soundbank|switchcontainer)`:.*$",
        builders,
        re.MULTILINE,
    )
    assert low_level_family_lines == []
    assert "raw WAAPI payload schemas" in text
    assert "paste raw WAAPI payload schemas" in text
    assert '"objects"' not in protocol
    assert '"children"' not in protocol
    assert '"onNameConflict"' not in protocol


def test_unsupported_runtime_and_mcp_features_are_boundaries_not_execution_capabilities() -> None:
    protocol = protocol_section()
    builders = semantic_builders_section()

    unsupported = _unsupported_boundary_paragraph(protocol)
    for phrase in [
        "scheduler or delayed runtime posting",
        "Game Object View emitter control",
        "timed runtime or ambience playback",
        "audio narrative sequencing",
        "RTPC ramps over time",
        "cross-app MCP federation",
    ]:
        assert phrase in unsupported

    assert "are not supported execution capabilities" in unsupported
    assert "Route them as `unsupported_runtime_boundary`" in unsupported
    assert "no execution steps" in unsupported
    assert "no preview id or hash" in unsupported
    assert "no verification claims" in unsupported
    assert "supported alternatives only when appropriate" in unsupported
    assert "`unsupported_runtime_boundary`: unsupported runtime, scheduler, Game Object View, RTPC ramp, narrative sequencing, or cross-app MCP requests" in builders


def test_public_config_surface_excludes_internal_runtime_constants() -> None:
    text = skill_text()
    protocol = protocol_section()

    assert "`wwise_version`, `waapi_host`, `waapi_port`, and `project_modification_policy`" in text
    assert "saved public config fields are exactly `wwise_version`, `waapi_host`, `waapi_port`, and `project_modification_policy`" in protocol
    assert "startup" in text
    assert "readiness" in text
    assert "WwiseConsole" in text
    assert "not saved public config" in text
    assert "`use_current_selection_for_ambiguous_queries`" in text
    assert "saved public config fields include `startup" not in text
    assert "saved public config fields include `readiness" not in text
    assert "saved public config fields include `WwiseConsole" not in text


def _unsupported_boundary_paragraph(text: str) -> str:
    pattern = re.compile(r"^Unsupported boundary requests:.*?(?=^Named invariant:)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    assert match is not None
    return match.group(0)

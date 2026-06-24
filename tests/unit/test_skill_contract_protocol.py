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


def welcome_section() -> str:
    text = skill_text()
    start = text.index("## Welcome/status UX for Wwise version detection")
    end = text.index("Supported Wwise versions")
    return text[start:end]


def safety_section() -> str:
    text = skill_text()
    start = text.index("## Safety guardrails")
    end = text.index("## Resources and documentation")
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
        "Execute only the confirmed plan whose internally retained hash still matches the preview artifact shown to the user",
        "Verify after execution",
    ]

    positions = [protocol.index(item) for item in required_sequence]
    assert positions == sorted(positions)


def test_project_changing_steps_require_matching_preview_hash() -> None:
    protocol = protocol_section()

    assert "before project-changing work" in protocol
    assert "`preview_hash`" in protocol
    assert "submitted_preview_hash = confirmation_state.preview_hash_seen_by_agent" in protocol
    assert "submitted_preview_hash=plan.preview_hash" not in protocol
    assert "Do not display `preview_hash`" in protocol
    assert "the user gives clear affirmative confirmation" in protocol
    assert "retained `submitted_preview_hash` exactly matches the current preview hash" in protocol
    assert "the retained hash does not match, show a fresh preview" in protocol
    assert "target identity" in protocol
    assert "planned API" in protocol
    assert "payload preview" in protocol
    assert "abort and re-preview" in protocol


def test_preview_hash_is_internal_not_user_visible() -> None:
    protocol = protocol_section()

    assert "Do not display `preview_hash`, checksums, JSON, or magic phrases in user-facing text" in protocol
    assert "Do not ask the user to type the hash" not in protocol
    assert "short preview id or hash for traceability" not in protocol


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


def test_welcome_surface_mentions_project_modification_policy() -> None:
    welcome = welcome_section()

    assert "state the current `project_modification_policy`" in welcome
    assert "Current project modification policy: preview_then_confirm" in welcome
    assert "never, preview_then_confirm, or allow_with_notice" in welcome
    assert "one-time session onboarding" in welcome
    assert "first visible `waapi-skill` response after loading the skill" in welcome
    assert "after making the first WAAPI connection in the current conversation" in welcome
    assert "If you are not certain the current conversation already displayed the policy, display it" in welcome
    assert "even when the first task is read-only" in welcome
    assert "even when the user directly specified the query behavior" in welcome
    assert "当前工程修改模式：preview_then_confirm" in welcome
    assert "Never answer a first connection summary with only" in welcome
    assert "Wwise is v2022.1.19" in welcome
    assert "do not repeat it in every final connection/project summary" in welcome
    assert "Repeat it only when the user changes the policy" in welcome
    assert "asks about mutation safety/config" in welcome
    assert "preview or execute project-changing work" in welcome
    assert "current conversation already displayed the policy" in welcome
    assert "final summaries may simply say which project and Wwise version were used without repeating the policy" in welcome
    assert "repeat the active policy in that same summary" not in welcome


def test_xml_backup_guidance_uses_project_root_dot_directory() -> None:
    safety = safety_section()

    assert "ak.wwise.core.getProjectInfo" in safety
    assert "prefer `directories.root`" in safety
    assert ".waapi_skill_backups/<timestamp>/" in safety
    assert "create_xml_edit_backup()" in safety
    assert "instead of writing sibling `.bak` files" in safety


def _unsupported_boundary_paragraph(text: str) -> str:
    pattern = re.compile(r"^Unsupported boundary requests:.*?(?=^Named invariant:)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    assert match is not None
    return match.group(0)

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_object_graph_business_agent_runner import (
    build_preview_only_object_graph_steps,
    prepare_object_graph_business_runtime,
)
from tests.semantic.support.codex_object_graph_business_profile import (
    UNIT_IDS,
    load_object_graph_business_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "tests" / "semantic" / "data" / "object-graph-business" / "profile.json"


def test_profile_owns_one_current_weather_named_graph() -> None:
    profile = load_object_graph_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    unit = profile.units[0]
    assert unit.operation == "object.create"
    assert unit.root_name == "Weather"
    assert [(row["name"], row["volume_db"]) for row in unit.sounds] == [
        ("Rain", -4),
        ("Wind", -6),
    ]


def test_prompt_exposes_business_outcomes_not_gateway_or_native_mechanics() -> None:
    unit = load_object_graph_business_profile(PROFILE).units[0]
    prompt = unit.prompt_template.casefold()

    assert "{parent_path}" in prompt
    for forbidden in (
        "draft-start", "draft-bind", "draft-declare", "operation-request",
        "request-json", "ak.wwise.", "object_handle", "actormixer",
        "isloopingenabled",
    ):
        assert forbidden not in prompt


def test_unit_declares_named_business_graph_before_one_preview(tmp_path: Path) -> None:
    unit = load_object_graph_business_profile(PROFILE).units[0]
    runtime = prepare_object_graph_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_object_graph_steps(runtime)

    assert [step.subcommand for step in steps] == [
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-declare-new",
        "draft-declare-new",
        "draft-declare-new",
        "draft-check",
        "preview-from-draft",
    ]
    declarations = steps[3:6]
    encoded = repr([step.arguments for step in declarations])
    assert "actor-mixer" in encoded
    assert encoded.count("sound-sfx") == 2
    assert encoded.count("volume_db") == 2
    assert "ActorMixer" not in encoded
    assert "IsLoopingEnabled" not in encoded
    assert runtime.parent_path in runtime.prompt
    assert str(unit.parent["id"]) not in runtime.prompt
    assert steps[-1].expected_operation_request == runtime.request


def test_profile_filters_and_matrix_descriptor_are_exact() -> None:
    selected = load_object_graph_business_profile(
        PROFILE,
        unit_ids=UNIT_IDS,
        versions=("2022.1",),
    )
    assert tuple(unit.unit_id for unit in selected.units) == UNIT_IDS
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.OBJECT_GRAPH_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2022.1"}
    assert descriptor.run_name == "run_object_graph_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.OBJECT_GRAPH_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=UNIT_IDS,
            versions=("2022.1",),
        )
    )
    assert tuple(unit.unit_id for unit in units) == UNIT_IDS
    assert matrix.OBJECT_GRAPH_BUSINESS_PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.OBJECT_GRAPH_BUSINESS_PROFILE_ID
    ] == "waapi-skill.object-graph-business-agent-outcome/v1"

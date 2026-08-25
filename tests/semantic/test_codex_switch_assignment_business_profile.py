from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_switch_assignment_business_agent_runner import (
    build_preview_only_switch_assignment_steps,
    prepare_switch_assignment_business_runtime,
)
from tests.semantic.support.codex_switch_assignment_business_profile import (
    UNIT_IDS,
    load_switch_assignment_business_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "switch-assignment-business"
    / "profile.json"
)


def test_profile_owns_one_current_add_assignment_preview() -> None:
    profile = load_switch_assignment_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    unit = profile.units[0]
    assert unit.operation == "switchContainer.addAssignment"
    assert tuple(unit.objects) == (
        "switch_container",
        "child",
        "group",
        "state_or_switch",
    )
    assert unit.objects["child"]["parent"] == unit.objects["switch_container"]["id"]
    assert unit.objects["state_or_switch"]["parent"] == unit.objects["group"]["id"]


def test_prompt_exposes_three_business_paths_not_gateway_mechanics() -> None:
    unit = load_switch_assignment_business_profile(PROFILE).units[0]
    prompt = unit.prompt_template.casefold()

    for role in ("switch_container", "child", "state_or_switch"):
        assert f"{{{role}_path}}" in prompt
    for forbidden in (
        "draft-start",
        "draft-bind",
        "draft-declare",
        "operation-request",
        "request-json",
        "ak.wwise.",
        "object_handle",
    ):
        assert forbidden not in prompt


def test_unit_binds_three_paths_then_declares_one_preview(tmp_path: Path) -> None:
    unit = load_switch_assignment_business_profile(PROFILE).units[0]
    runtime = prepare_switch_assignment_business_runtime(
        unit,
        tmp_path / "runtime",
    )
    steps = build_preview_only_switch_assignment_steps(runtime.request)

    assert [step.subcommand for step in steps] == [
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-bind-object",
        "draft-bind-object",
        "draft-declare-switch-assignment",
        "draft-check",
        "preview-from-draft",
    ]
    assert all(
        unit.objects[role]["path"] in runtime.prompt
        for role in ("switch_container", "child", "state_or_switch")
    )
    assert all(row["id"] not in runtime.prompt for row in unit.objects.values())
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))
    assert fixture["assignments"] == []
    assert fixture["objects"][0]["SwitchGroupOrStateGroup"] == {
        "id": unit.objects["group"]["id"]
    }
    assert steps[-1].expected_operation_request == runtime.request


def test_profile_filters_and_formal_lane_registration_are_exact() -> None:
    selected = load_switch_assignment_business_profile(
        PROFILE,
        unit_ids=UNIT_IDS,
        versions=("2022.1",),
    )
    assert tuple(unit.unit_id for unit in selected.units) == UNIT_IDS
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.SWITCH_ASSIGNMENT_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2022.1"}
    assert descriptor.run_name == "run_switch_assignment_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.SWITCH_ASSIGNMENT_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=UNIT_IDS,
            versions=("2022.1",),
        )
    )
    assert tuple(unit.unit_id for unit in units) == UNIT_IDS
    assert (
        matrix.SWITCH_ASSIGNMENT_BUSINESS_PROFILE_ID
        in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    )
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.SWITCH_ASSIGNMENT_BUSINESS_PROFILE_ID
    ] == "waapi-skill.switch-assignment-business-agent-outcome/v1"

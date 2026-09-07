from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_business_agent_runner import (
    _expected_gateway_subcommands,
)
from tests.semantic.support.codex_compound_undo_business_agent_runner import (
    _compound_undo_business_run_spec,
    build_preview_only_compound_undo_steps,
    prepare_compound_undo_business_runtime,
)
from tests.semantic.support.codex_compound_undo_business_profile import (
    UNIT_IDS,
    load_compound_undo_business_profile,
)
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    _normalize_object_lifecycle_business_argument_order,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "compound-undo-business"
    / "profile.json"
)


def test_profile_owns_one_two_change_compound_preview() -> None:
    profile = load_compound_undo_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    unit = profile.units[0]
    assert unit.operation == "waapi.undoGroup"
    assert unit.transaction_count == 1
    assert unit.object["type"] == "Sound"


def test_prompt_exposes_business_outcome_not_gateway_mechanics() -> None:
    unit = load_compound_undo_business_profile(PROFILE).units[0]
    prompt = unit.prompt_template.casefold()

    for token in (
        "{object_path}",
        "{notes_value}",
        "{name_value}",
        "{display_name}",
    ):
        assert token in prompt
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


def test_unit_checks_children_then_emits_only_parent_preview(tmp_path: Path) -> None:
    unit = load_compound_undo_business_profile(PROFILE).units[0]
    runtime = prepare_compound_undo_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_compound_undo_steps(runtime)

    assert [step.name for step in steps] == [
        "tx03.operation-schema",
        "tx03.draft-start",
        "tx01.draft-start",
        "tx01.bind-object",
        "tx01.declare-object-change",
        "tx01.check",
        "tx02.draft-start",
        "tx02.bind-object",
        "tx02.declare-object-change",
        "tx02.check",
        "tx03.declare-undo-plan",
        "tx03.check",
        "tx03.preview",
    ]
    assert [
        step.name for step in steps if step.subcommand == "preview-from-draft"
    ] == ["tx03.preview"]
    assert [
        child["request"]["operation"]
        for child in steps[-1].expected_operation_request["arguments"]["calls"]
    ] == ["object.setNotes", "object.setName"]
    assert all(unit.object["id"] not in token for token in runtime.prompt.split())
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))
    assert fixture["objects"] == [dict(unit.object)]


def test_fresh_runner_allows_only_the_one_initial_operations_discovery(
    tmp_path: Path,
) -> None:
    unit = load_compound_undo_business_profile(PROFILE).units[0]
    runtime = prepare_compound_undo_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_compound_undo_steps(runtime)
    spec = _compound_undo_business_run_spec()

    assert spec.allow_compound_checked_child_handoff is False
    assert (
        spec.optional_initial_operations_discovery_operation
        == "waapi.undoGroup"
    )
    subcommands = _expected_gateway_subcommands(
        steps,
        optional_initial_operations_discovery_operation=(
            spec.optional_initial_operations_discovery_operation
        ),
    )
    assert subcommands[0] == "operations"
    assert subcommands.count("operations") == 1
    assert set(subcommands[1:]) == {step.subcommand for step in steps}


def test_object_lifecycle_declaration_named_options_are_transport_order_independent() -> None:
    step = ExpectedGatewayStep(
        name="tx01.declare-object-change",
        subcommand="draft-declare-object-change",
        arguments=(
            "draft-id",
            "--task-authority",
            "authority",
            "--expected-revision",
            "2",
            "--object-handle",
            "object-handle",
            "--notes",
            "Exterior rain loop",
        ),
    )

    assert _normalize_object_lifecycle_business_argument_order(
        step,
        (
            "draft-id",
            "--task-authority",
            "authority",
            "--expected-revision",
            "2",
            "--notes",
            "Exterior rain loop",
            "--object-handle",
            "object-handle",
        ),
    ) == step.arguments
    wrong = _normalize_object_lifecycle_business_argument_order(
        step,
        (
            "draft-id",
            "--task-authority",
            "authority",
            "--expected-revision",
            "2",
            "--notes",
            "Wrong",
            "--object-handle",
            "object-handle",
        ),
    )
    assert wrong != step.arguments
    assert "Wrong" in wrong


@pytest.mark.parametrize("with_discovery", (False, True))
def test_campaign_audit_accepts_only_the_optional_initial_operations_read(
    tmp_path: Path,
    with_discovery: bool,
) -> None:
    unit = load_compound_undo_business_profile(PROFILE).units[0]
    runtime = prepare_compound_undo_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_compound_undo_steps(runtime)
    audited_steps = (
        (("tx03.operations", "operations"),)
        if with_discovery
        else ()
    ) + tuple((step.name, step.subcommand) for step in steps)
    names = [name for name, _subcommand in audited_steps]
    records = [
        {
            "step_name": name,
            "gateway_arguments": [subcommand],
            "accepted": True,
            "authenticated": True,
            "succeeded": True,
            "exit_code": 0,
            "payload": (
                {"agent_result": {"request": steps[-1].expected_operation_request}}
                if name == "tx03.preview"
                else {}
            ),
        }
        for name, subcommand in audited_steps
    ]
    campaign._validate_bound_business_agent_protocol(  # noqa: SLF001
        {
            "expected_step_names": names,
            "consumed_step_names": names,
            "records": records,
        },
        expected_unit=unit,
        profile=matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID,
    )


def test_campaign_audit_rejects_repeated_operations_discovery(tmp_path: Path) -> None:
    unit = load_compound_undo_business_profile(PROFILE).units[0]
    runtime = prepare_compound_undo_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_compound_undo_steps(runtime)
    names = ["tx03.operations", "tx03.operations-again", *(step.name for step in steps)]
    with pytest.raises(campaign.CampaignEvidenceError, match="unreviewed discovery"):
        campaign._validate_bound_business_agent_protocol(  # noqa: SLF001
            {
                "expected_step_names": names,
                "consumed_step_names": names,
                "records": [],
            },
            expected_unit=unit,
            profile=matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID,
        )


def test_profile_filters_and_formal_lane_registration_are_exact() -> None:
    selected = load_compound_undo_business_profile(
        PROFILE,
        unit_ids=UNIT_IDS,
        versions=("2022.1",),
    )
    assert tuple(unit.unit_id for unit in selected.units) == UNIT_IDS
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2022.1"}
    assert descriptor.run_name == "run_compound_undo_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=UNIT_IDS,
            versions=("2022.1",),
        )
    )
    assert tuple(unit.unit_id for unit in units) == UNIT_IDS
    assert matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID
    ] == "waapi-skill.compound-undo-business-agent-outcome/v1"


def test_public_cli_defaults_to_the_frozen_terra_profile() -> None:
    options = matrix.parse_args(
        ["--profile", matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID]
    )

    assert options.suite_path == PROFILE
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"
    assert options.offline_only is False

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_object_metadata_business_agent_runner import (
    build_preview_only_metadata_steps,
    prepare_object_metadata_business_runtime,
)
from tests.semantic.support.codex_object_metadata_business_profile import (
    UNIT_IDS,
    load_object_metadata_business_profile,
)
from tests.semantic.support.codex_gateway_broker import MetadataQueryArgument


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "tests" / "semantic" / "data" / "object-metadata-business" / "profile.json"


def test_profile_owns_one_current_alarm_reference_repair() -> None:
    profile = load_object_metadata_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    assert profile.units[0].operation == "object.setReference"
    assert profile.units[0].field_meaning == "Output Bus"
    assert profile.units[0].native_reference == "OutputBus"


def test_prompt_exposes_ui_meaning_not_native_token_or_gateway_mechanics() -> None:
    unit = load_object_metadata_business_profile(PROFILE).units[0]
    prompt = unit.prompt_template.casefold()

    assert "{field_meaning}" in prompt
    assert unit.native_reference.casefold() not in prompt
    for forbidden in (
        "draft-start", "draft-bind", "draft-discover", "draft-declare",
        "operation-request", "request-json", "ak.wwise.", "field_handle",
    ):
        assert forbidden not in prompt


def test_unit_discovers_meaning_and_copies_opaque_handle_before_preview(tmp_path: Path) -> None:
    unit = load_object_metadata_business_profile(PROFILE).units[0]
    runtime = prepare_object_metadata_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_metadata_steps(runtime)
    subcommands = [step.subcommand for step in steps]

    assert subcommands == [
        "operation-schema", "draft-start", "draft-bind-object", "draft-discover-fields",
        "draft-bind-object", "draft-declare-field-change", "draft-check",
        "preview-from-draft",
    ]
    discover = steps[3]
    declare = steps[5]
    assert MetadataQueryArgument(unit.field_meaning) in discover.arguments
    assert unit.native_reference not in discover.arguments
    assert "--token" not in discover.arguments
    assert "--field-handle" in declare.arguments
    assert unit.native_reference not in declare.arguments
    assert runtime.source_id not in runtime.prompt
    assert runtime.target_id not in runtime.prompt
    assert steps[-1].expected_operation_request == runtime.request


def test_profile_filters_and_matrix_descriptor_are_exact() -> None:
    selected = load_object_metadata_business_profile(
        PROFILE,
        unit_ids=(UNIT_IDS[0],),
        versions=("2022.1",),
    )
    assert tuple(unit.unit_id for unit in selected.units) == UNIT_IDS
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.OBJECT_METADATA_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2022.1"}
    assert descriptor.run_name == "run_object_metadata_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.OBJECT_METADATA_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=UNIT_IDS,
            versions=("2022.1",),
        )
    )
    assert tuple(unit.unit_id for unit in units) == UNIT_IDS
    assert matrix.OBJECT_METADATA_BUSINESS_PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.OBJECT_METADATA_BUSINESS_PROFILE_ID
    ] == "waapi-skill.object-metadata-business-agent-outcome/v1"

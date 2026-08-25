from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_object_lifecycle_business_agent_runner import (
    build_preview_only_lifecycle_steps,
    prepare_object_lifecycle_business_runtime,
)
from tests.semantic.support.codex_object_lifecycle_business_profile import (
    UNIT_IDS,
    load_object_lifecycle_business_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "object-lifecycle-business"
    / "profile.json"
)


def test_profile_owns_three_current_business_routing_units() -> None:
    profile = load_object_lifecycle_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    assert [unit.operation for unit in profile.units] == [
        "object.setNotes",
        "object.delete",
        "object.setName",
    ]
    assert all(unit.version == "2022.1" for unit in profile.units)
    assert all(unit.scenario.api.startswith("ak.wwise.core.object.") for unit in profile.units)


def test_profile_prompts_expose_business_intent_not_gateway_mechanics() -> None:
    profile = load_object_lifecycle_business_profile(PROFILE)
    prompt = "\n".join(unit.prompt_template for unit in profile.units).casefold()

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


def test_every_unit_uses_business_declaration_and_stops_at_preview(tmp_path: Path) -> None:
    profile = load_object_lifecycle_business_profile(PROFILE)

    for index, unit in enumerate(profile.units, start=1):
        runtime = prepare_object_lifecycle_business_runtime(
            unit,
            tmp_path / f"runtime-{index}",
        )
        steps = build_preview_only_lifecycle_steps(runtime.request)
        subcommands = [step.subcommand for step in steps]

        assert "draft-declare-object-change" in subcommands
        assert "draft-apply" not in subcommands
        assert "execute" not in subcommands
        assert subcommands[-1] == "preview-from-draft"
        assert runtime.object_id not in runtime.prompt
        assert runtime.object_path in runtime.prompt
        assert steps[-1].expected_operation_request == runtime.request


def test_profile_filters_are_exact() -> None:
    selected = load_object_lifecycle_business_profile(
        PROFILE,
        unit_ids=("OLB22-NOTES",),
        versions=("2022.1",),
    )

    assert tuple(unit.unit_id for unit in selected.units) == ("OLB22-NOTES",)


def test_matrix_exposes_current_profile_through_the_existing_fresh_lane() -> None:
    assert (
        matrix.OBJECT_LIFECYCLE_BUSINESS_PROFILE_ID
        in matrix.EXECUTABLE_V3_PROFILE_IDS
    )
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.OBJECT_LIFECYCLE_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2022.1"}
    assert descriptor.run_name == "run_object_lifecycle_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.OBJECT_LIFECYCLE_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("OLB22-RENAME",),
            versions=("2022.1",),
        )
    )

    assert tuple(unit.unit_id for unit in units) == ("OLB22-RENAME",)

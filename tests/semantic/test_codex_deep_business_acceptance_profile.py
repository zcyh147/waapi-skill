from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support import codex_debug_control_business_agent_runner as debug_runner
from tests.semantic.support.codex_deep_business_acceptance_profile import (
    PROFILE_ID,
    PROFILE_TASK_COUNT,
    REQUIRED_FAMILIES,
    SUPPORTED_VERSIONS,
    DeepBusinessAcceptanceProfileError,
    load_deep_business_acceptance_profile,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_debug_control_business_transaction_steps,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "deep-business-acceptance"
    / "profile.json"
)


def test_deep_business_acceptance_profile_closes_every_migration_family() -> None:
    profile = load_deep_business_acceptance_profile(PROFILE)

    assert len(profile.units) == PROFILE_TASK_COUNT == 19
    assert {unit.version for unit in profile.units} == set(SUPPORTED_VERSIONS)
    assert {unit.family for unit in profile.units} == set(REQUIRED_FAMILIES)
    assert len({unit.unit_id for unit in profile.units}) == PROFILE_TASK_COUNT
    assert all(unit.component_profile_id for unit in profile.units)
    assert all(unit.component_suite_path.is_file() for unit in profile.units)
    assert all(unit.scenario.api for unit in profile.units)
    assert all(unit.user_turn_count in {1, 2} for unit in profile.units)
    assert all(unit.transaction_count in {0, 1} for unit in profile.units)


def test_deep_business_acceptance_profile_has_the_targeted_acceptance_behaviors() -> None:
    profile = load_deep_business_acceptance_profile(PROFILE)
    by_family = {unit.family: unit for unit in profile.units}

    assert by_family["audio-import-mvp"].unit_id == "AIB22-WEATHER-A"
    assert by_family["named-object-metadata-fields"].unit_id == (
        "OMB22-ALARM-OUTPUT-BUS"
    )
    assert by_family["fixed-query-metadata-selection-profiler-debug"].unit_id == (
        "TYP22-GENERIC-OBJECT-QUERY"
    )
    assert by_family["named-compound-undo"].unit_id == (
        "CUB22-WEATHER-TWO-CHANGES"
    )
    assert by_family["generic-topics"].unit_id == (
        "TYP24-TOPIC-SOUNDBANK-GENERATED"
    )
    assert by_family["named-dangerous-debug-controls"].unit_id == (
        "DBG21-AUTOMATION-PREVIEW"
    )


def test_deep_business_wrapper_preserves_component_turn_and_dispatch_contracts() -> None:
    profile = load_deep_business_acceptance_profile(PROFILE)
    query = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP22-GENERIC-OBJECT-QUERY"
    )

    assert query.turns == query.component_unit.turns
    assert query.expected_audited_dispatch_count == 2


def test_deep_business_campaign_seals_its_audio_import_protocol_revision() -> None:
    effective = {
        "selection": {"profile": PROFILE_ID},
        "harness": {
            "semantic_tree_sha256": "0" * 64,
            "protocol_manifest_revision": (
                campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
            ),
        },
    }

    assert campaign._sealed_protocol_manifest_revision(effective) == (
        campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
    )


def test_deep_business_archive_accepts_debug_component_with_one_discovery() -> None:
    wrapper = load_deep_business_acceptance_profile(
        PROFILE,
        unit_ids=("DBG21-AUTOMATION-PREVIEW",),
    ).units[0]
    component = wrapper.component_unit
    steps = build_debug_control_business_transaction_steps(
        version=component.version,
        label="tx01",
        enabled=True,
    )
    audited = (
        ("tx01.operations", "operations"),
        *((step.name, step.subcommand) for step in steps),
    )
    names = [name for name, _subcommand in audited]
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
                if name == "tx01.preview"
                else {}
            ),
        }
        for name, subcommand in audited
    ]

    campaign._validate_bound_business_agent_protocol(  # noqa: SLF001
        {
            "expected_step_names": names,
            "consumed_step_names": names,
            "records": records,
        },
        expected_unit=component,
        profile=wrapper.component_profile_id,
    )


def test_deep_business_acceptance_rejects_family_omission_before_filtering(
    tmp_path: Path,
) -> None:
    root = json.loads(PROFILE.read_text(encoding="utf-8"))
    root["tasks"].pop()
    drifted = tmp_path / "profile.json"
    drifted.write_text(json.dumps(root), encoding="utf-8")

    with pytest.raises(
        DeepBusinessAcceptanceProfileError,
        match="task count|family coverage",
    ):
        load_deep_business_acceptance_profile(
            drifted,
            unit_ids=("AIB22-WEATHER-A",),
        )


def test_deep_business_acceptance_profile_is_one_formal_terra_campaign() -> None:
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=PROFILE_ID,
            suite_path=PROFILE,
            case_ids=(),
            versions=(),
        )
    )

    assert len(units) == PROFILE_TASK_COUNT
    assert PROFILE_ID in matrix.EXECUTABLE_V3_PROFILE_IDS
    assert PROFILE_ID in matrix.SEMANTIC_BOOTSTRAP_PROFILE_IDS
    assert PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    options = matrix.parse_args(["--profile", PROFILE_ID])
    assert options.suite_path == PROFILE
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"


def test_deep_business_acceptance_filters_after_complete_validation() -> None:
    profile = load_deep_business_acceptance_profile(
        PROFILE,
        unit_ids=("DBG21-AUTOMATION-PREVIEW", "CLI25-SOUNDBANK-BUILD-PREVIEW"),
    )

    assert [unit.unit_id for unit in profile.units] == [
        "DBG21-AUTOMATION-PREVIEW",
        "CLI25-SOUNDBANK-BUILD-PREVIEW",
    ]
    with pytest.raises(
        DeepBusinessAcceptanceProfileError,
        match="unknown deep-business acceptance unit ids",
    ):
        load_deep_business_acceptance_profile(PROFILE, unit_ids=("missing",))


def test_deep_business_acceptance_delegates_to_the_sealed_component_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = load_deep_business_acceptance_profile(
        PROFILE,
        unit_ids=("DBG21-AUTOMATION-PREVIEW",),
    ).units[0]
    sentinel = object()
    observed: dict[str, object] = {}

    def fake_run(unit: object, *, scenario_root: Path, options: object) -> object:
        observed.update(
            unit=unit,
            scenario_root=scenario_root,
            profile=wrapper.component_profile_id,
            suite=wrapper.component_suite_path,
            options=options,
        )
        return sentinel

    monkeypatch.setattr(
        debug_runner,
        "run_debug_control_business_agent_unit",
        fake_run,
    )
    options = matrix.RunnerOptions(
        profile=PROFILE_ID,
        iteration_root=tmp_path / "iteration",
        suite_path=PROFILE,
        skill_source=REPO_ROOT / "skills" / "waapi-skill",
        codex_binary=tmp_path / "codex",
        auth_json=tmp_path / "auth.json",
        live_config=tmp_path / "live.json",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=360.0,
        case_ids=(),
        versions=(),
        pair_ids=(),
        offline_only=False,
        overwrite=False,
        wwise_readiness_timeout_seconds=600.0,
        windows_powershell_core_host=None,
    )

    result = matrix.run_heavy_v3_unit(
        wrapper,
        scenario_root=tmp_path / "scenario",
        options=options,
    )

    assert result is sentinel
    assert observed["unit"] is wrapper.component_unit
    assert observed["scenario_root"] == tmp_path / "scenario"
    delegated_options = observed["options"]
    assert delegated_options.model == "gpt-5.6-terra"
    assert options.require_first_use_intro is True

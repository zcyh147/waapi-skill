from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_project_setting_business_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import (
    validate_operation_draft_protocol_steps,
)
from tests.semantic.support.codex_project_setting_business_agent_runner import (
    prepare_project_setting_business_runtime,
)
from tests.semantic.support.codex_business_agent_runner import (
    _only_expected_business_commands,
)
from tests.semantic.support.codex_project_setting_business_profile import (
    OBJECT_ID,
    OBJECT_NAME,
    ProjectSettingBusinessProfileError,
    load_project_setting_business_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "project-setting-business"
    / "profile.json"
)


def test_project_setting_business_profile_is_one_closed_terra_preview() -> None:
    profile = load_project_setting_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "PSET25-GAME-PARAMETER-RANGE-PREVIEW"
    assert unit.operation == "ak.wwise.core.gameParameter.setRange"
    assert unit.version == "2025.1"
    assert unit.user_turn_count == unit.transaction_count == 1


def test_project_setting_business_profile_rejects_unknown_filters() -> None:
    with pytest.raises(
        ProjectSettingBusinessProfileError,
        match="unknown Project-setting business",
    ):
        load_project_setting_business_profile(PROFILE, unit_ids=("missing",))
    with pytest.raises(
        ProjectSettingBusinessProfileError,
        match="does not support versions",
    ):
        load_project_setting_business_profile(PROFILE, versions=("2022.1",))


def test_project_setting_runtime_contains_one_exact_game_parameter(
    tmp_path: Path,
) -> None:
    unit = load_project_setting_business_profile(PROFILE).units[0]
    runtime = prepare_project_setting_business_runtime(
        unit,
        tmp_path / "runtime",
    )
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))

    assert fixture["version"] == "2025.1"
    assert fixture["objects"] == [
        {
            "id": OBJECT_ID,
            "name": "WeatherIntensity",
            "type": "GameParameter",
            "path": r"\Game Parameters\Default Work Unit\WeatherIntensity",
        }
    ]
    assert "ak.wwise" not in runtime.prompt
    assert runtime.request["arguments"]["args"] == {
        "object": OBJECT_ID,
        "min": -10.0,
        "max": 100.0,
        "onCurveUpdate": "stretch",
    }


def test_business_fixture_shim_resolves_one_exact_typed_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = load_project_setting_business_profile(PROFILE).units[0]
    runtime = prepare_project_setting_business_runtime(unit, tmp_path / "runtime")
    shim_path = (
        REPO_ROOT
        / "tests"
        / "semantic"
        / "data"
        / "business-agent"
        / "waapi-shim"
        / "waapi.py"
    )
    spec = importlib.util.spec_from_file_location(
        "project_setting_business_waapi_shim",
        shim_path,
    )
    assert spec is not None and spec.loader is not None
    shim = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = shim
    spec.loader.exec_module(shim)
    monkeypatch.setenv("WAAPI_BUSINESS_AGENT_FIXTURE", str(runtime.fixture_path))

    result = shim.WaapiClient().call(
        "ak.wwise.core.object.get",
        {
            "waql": (
                'from type GameParameter where name = "WeatherIntensity" take 2'
            )
        },
        {"return": ["id", "name", "type", "path"]},
    )

    assert result["return"] == [
        {
            "id": OBJECT_ID,
            "name": OBJECT_NAME,
            "type": "GameParameter",
            "path": r"\Game Parameters\Default Work Unit\WeatherIntensity",
        }
    ]


def test_business_command_gate_folds_one_identical_windows_267_retry() -> None:
    command = "pwsh -Command request-schema"
    argv = ("python", "run.py", "gateway.py", "request-schema", "api")
    common = {
        "command": command,
        "argv": argv,
        "parse_error": "",
        "has_shell_operators": False,
        "parser_kind": "windows-pwsh-command",
    }
    failed = SimpleNamespace(
        **common,
        status="failed",
        exit_code=-1,
        aggregated_output=(
            "execution error: Io(windows sandbox: "
            "CreateProcessAsUserW failed: 267)"
        ),
    )
    successful = SimpleNamespace(
        **common,
        status="completed",
        exit_code=0,
        aggregated_output="{}",
    )
    facts = SimpleNamespace(
        command_records=(failed, successful),
        unexpected_commands=(),
        allowed_read_commands=(),
    )

    assert _only_expected_business_commands(facts, (argv,)) is True


def test_project_setting_protocol_is_singular_and_complete() -> None:
    steps = build_project_setting_business_transaction_steps(
        version="2025.1",
        label="tx01",
        object_id=OBJECT_ID,
        object_name=OBJECT_NAME,
    )
    validate_operation_draft_protocol_steps(steps)

    assert [step.subcommand for step in steps] == [
        "request-schema",
        "draft-start",
        "draft-bind-object",
        "draft-declare-project-setting-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[-1].expected_operation_request["arguments"] == {
        "api": "ak.wwise.core.gameParameter.setRange",
        "args": {
            "object": OBJECT_ID,
            "min": -10.0,
            "max": 100.0,
            "onCurveUpdate": "stretch",
        },
        "options": {},
    }
    assert steps[2].arguments[-3:] == (
        "--exact-type-name",
        "GameParameter",
        OBJECT_NAME,
    )
    assert all(
        step.subcommand not in {"typed-call", "draft-apply", "execute"}
        for step in steps
    )


def test_remaining_core_declarations_are_canonical_draft_commands() -> None:
    from tests.semantic.support.codex_draft_commands import (
        DRAFT_GATEWAY_SUBCOMMANDS,
    )

    assert {
        "draft-declare-project-setting-plan",
        "draft-declare-source-control-plan",
    } <= DRAFT_GATEWAY_SUBCOMMANDS


def test_project_setting_profile_is_registered_in_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2025.1"}
    assert descriptor.run_name == "run_project_setting_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("PSET25-GAME-PARAMETER-RANGE-PREVIEW",),
            versions=("2025.1",),
        )
    )
    assert len(units) == 1
    assert matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID in (
        campaign.TERRA_LOCKED_V3_PROFILE_IDS
    )
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID
    ] == "waapi-skill.project-setting-business-agent-outcome/v1"

    options = matrix.parse_args(
        ["--profile", matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID]
    )
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

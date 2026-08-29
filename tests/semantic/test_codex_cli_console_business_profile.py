from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_cli_console_business_agent_runner import (
    _cli_console_business_run_spec,
    prepare_cli_console_business_runtime,
)
from tests.semantic.support.codex_cli_console_business_profile import (
    OUTPUT_DIRECTORY,
    CliConsoleBusinessProfileError,
    load_cli_console_business_profile,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_cli_console_business_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import (
    validate_operation_draft_protocol_steps,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "cli-console-business"
    / "profile.json"
)


def test_cli_console_business_profile_is_one_closed_terra_preview() -> None:
    profile = load_cli_console_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "CLI25-SOUNDBANK-BUILD-PREVIEW"
    assert unit.operation == "ak.wwise.cli.generateSoundbank"
    assert unit.version == "2025.1"
    assert unit.user_turn_count == unit.transaction_count == 1


def test_cli_console_business_profile_rejects_unknown_filters() -> None:
    with pytest.raises(
        CliConsoleBusinessProfileError,
        match="unknown CLI/Console business",
    ):
        load_cli_console_business_profile(PROFILE, unit_ids=("missing",))
    with pytest.raises(
        CliConsoleBusinessProfileError,
        match="does not support versions",
    ):
        load_cli_console_business_profile(PROFILE, versions=("2022.1",))


def test_cli_console_business_runtime_closes_only_high_level_build_values(
    tmp_path: Path,
) -> None:
    unit = load_cli_console_business_profile(PROFILE).units[0]
    runtime = prepare_cli_console_business_runtime(unit, tmp_path / "runtime")
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))

    assert fixture["version"] == "2025.1"
    assert fixture["objects"] == fixture["fields"] == fixture["assignments"] == []
    assert "ak.wwise" not in runtime.prompt
    assert str(runtime.project_path) in runtime.prompt
    assert runtime.request["arguments"] == {
        "api": "ak.wwise.cli.generateSoundbank",
        "args": {
            "project": str(runtime.project_path),
            "platform": ["Windows"],
            "skip-languages": True,
            "no-source-control": True,
            "soundbank-path": ["Windows", OUTPUT_DIRECTORY],
            "quiet": True,
        },
        "options": {},
        "io_root": str(runtime.project_path.parent),
    }


def test_cli_console_business_protocol_is_one_complete_deep_draft(
    tmp_path: Path,
) -> None:
    project = (tmp_path / "SemanticProject.wproj").resolve()
    steps = build_cli_console_business_transaction_steps(
        api="ak.wwise.cli.generateSoundbank",
        version="2025.1",
        label="tx01",
        project_file=str(project),
        output_directory=OUTPUT_DIRECTORY,
    )
    validate_operation_draft_protocol_steps(steps)

    assert [step.subcommand for step in steps] == [
        "request-schema",
        "draft-start",
        "draft-declare-cli-console-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[-1].expected_operation_request["operation"] == "waapi.call"
    assert steps[-1].expected_operation_request["arguments"]["args"] == {
        "project": str(project),
        "platform": ["Windows"],
        "skip-languages": True,
        "no-source-control": True,
        "soundbank-path": ["Windows", OUTPUT_DIRECTORY],
        "quiet": True,
    }
    assert all(
        step.subcommand not in {"typed-call", "draft-apply", "execute"}
        for step in steps
    )


def test_cli_console_business_runner_allows_one_initial_operation_discovery() -> None:
    unit = load_cli_console_business_profile(PROFILE).units[0]
    spec = _cli_console_business_run_spec(unit)

    assert spec.optional_initial_operations_discovery_operation == unit.operation


def test_cli_console_business_profile_is_registered_in_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2025.1"}
    assert descriptor.run_name == "run_cli_console_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("CLI25-SOUNDBANK-BUILD-PREVIEW",),
            versions=("2025.1",),
        )
    )
    assert len(units) == 1
    assert matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID
    ] == "waapi-skill.cli-console-business-agent-outcome/v1"

    options = matrix.parse_args(
        ["--profile", matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID]
    )
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

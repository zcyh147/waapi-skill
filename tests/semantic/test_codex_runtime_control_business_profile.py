from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_runtime_control_business_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import (
    validate_operation_draft_protocol_steps,
)
from tests.semantic.support.codex_runtime_control_business_agent_runner import (
    prepare_runtime_control_business_runtime,
)
from tests.semantic.support.codex_runtime_control_business_profile import (
    RuntimeControlBusinessProfileError,
    load_runtime_control_business_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "runtime-control-business"
    / "profile.json"
)


def test_runtime_control_profile_is_one_closed_terra_preview() -> None:
    profile = load_runtime_control_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "RUNTIME25-PROFILER-VOICES-PREVIEW"
    assert unit.operation == "ak.wwise.core.profiler.enableProfilerData"
    assert unit.version == "2025.1"
    assert unit.user_turn_count == unit.transaction_count == 1


def test_runtime_control_profile_rejects_unknown_filters() -> None:
    with pytest.raises(
        RuntimeControlBusinessProfileError,
        match="unknown Runtime-control business",
    ):
        load_runtime_control_business_profile(PROFILE, unit_ids=("missing",))


def test_runtime_control_runtime_contains_no_authoring_objects(
    tmp_path: Path,
) -> None:
    unit = load_runtime_control_business_profile(PROFILE).units[0]
    runtime = prepare_runtime_control_business_runtime(unit, tmp_path / "runtime")
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))

    assert fixture["version"] == "2025.1"
    assert fixture["is_command_line"] is False
    assert fixture["objects"] == []
    assert "ak.wwise" not in runtime.prompt
    assert runtime.request["arguments"] == {
        "api": "ak.wwise.core.profiler.enableProfilerData",
        "args": {"dataTypes": [{"dataType": "voices", "enable": True}]},
        "options": {},
    }


def test_runtime_control_protocol_is_singular_and_complete() -> None:
    steps = build_runtime_control_business_transaction_steps(
        version="2025.1",
        label="tx01",
    )
    validate_operation_draft_protocol_steps(steps)

    assert [step.subcommand for step in steps] == [
        "request-schema",
        "draft-start",
        "draft-declare-runtime-control-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[-1].expected_operation_request["arguments"]["args"] == {
        "dataTypes": [{"dataType": "voices", "enable": True}]
    }
    assert all(
        step.subcommand not in {"typed-call", "draft-apply", "execute"}
        for step in steps
    )


def test_runtime_control_profile_is_registered_in_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2025.1"}
    assert descriptor.run_name == "run_runtime_control_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("RUNTIME25-PROFILER-VOICES-PREVIEW",),
            versions=("2025.1",),
        )
    )
    assert len(units) == 1
    assert matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID in (
        campaign.TERRA_LOCKED_V3_PROFILE_IDS
    )
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID
    ] == "waapi-skill.runtime-control-business-agent-outcome/v1"

    options = matrix.parse_args(
        ["--profile", matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID]
    )
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

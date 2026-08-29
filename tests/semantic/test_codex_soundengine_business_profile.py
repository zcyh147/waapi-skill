from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_soundengine_business_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import (
    validate_operation_draft_protocol_steps,
)
from tests.semantic.support.codex_soundengine_business_agent_runner import (
    prepare_soundengine_business_runtime,
)
from tests.semantic.support.codex_soundengine_business_profile import (
    SoundEngineBusinessProfileError,
    load_soundengine_business_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "soundengine-business"
    / "profile.json"
)


def test_soundengine_profile_is_one_closed_terra_preview() -> None:
    profile = load_soundengine_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "SOUND22-MONITOR-PREVIEW"
    assert unit.operation == "ak.soundengine.postMsgMonitor"
    assert unit.version == "2022.1"
    assert unit.user_turn_count == unit.transaction_count == 1


def test_soundengine_profile_rejects_unknown_filters() -> None:
    with pytest.raises(
        SoundEngineBusinessProfileError,
        match="unknown SoundEngine business",
    ):
        load_soundengine_business_profile(PROFILE, unit_ids=("missing",))


def test_soundengine_runtime_contains_exact_closed_monitor_request(
    tmp_path: Path,
) -> None:
    unit = load_soundengine_business_profile(PROFILE).units[0]
    runtime = prepare_soundengine_business_runtime(unit, tmp_path / "runtime")
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))

    assert fixture["version"] == "2022.1"
    assert fixture["is_command_line"] is False
    assert fixture["objects"] == []
    assert "ak.soundengine" not in runtime.prompt
    assert runtime.request["arguments"] == {
        "api": "ak.soundengine.postMsgMonitor",
        "args": {"message": "Fresh Agent SoundEngine business probe"},
        "options": {},
    }


def test_soundengine_protocol_is_singular_and_complete() -> None:
    steps = build_soundengine_business_transaction_steps(
        version="2022.1",
        label="tx01",
        monitor_message="Fresh Agent SoundEngine business probe",
    )
    validate_operation_draft_protocol_steps(steps)

    assert [step.subcommand for step in steps] == [
        "request-schema",
        "draft-start",
        "draft-declare-soundengine-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[-1].expected_operation_request["arguments"]["args"] == {
        "message": "Fresh Agent SoundEngine business probe"
    }
    assert all(
        step.subcommand not in {"typed-call", "draft-apply", "execute"}
        for step in steps
    )


def test_soundengine_profile_is_registered_in_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.SOUNDENGINE_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2022.1"}
    assert descriptor.run_name == "run_soundengine_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.SOUNDENGINE_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("SOUND22-MONITOR-PREVIEW",),
            versions=("2022.1",),
        )
    )
    assert len(units) == 1
    assert matrix.SOUNDENGINE_BUSINESS_PROFILE_ID in (
        campaign.TERRA_LOCKED_V3_PROFILE_IDS
    )
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.SOUNDENGINE_BUSINESS_PROFILE_ID
    ] == "waapi-skill.soundengine-business-agent-outcome/v1"

    options = matrix.parse_args(
        ["--profile", matrix.SOUNDENGINE_BUSINESS_PROFILE_ID]
    )
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

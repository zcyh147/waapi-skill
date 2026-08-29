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
    prepare_soundengine_business_broker_state,
    prepare_soundengine_business_runtime,
)
from tests.semantic.support.codex_soundengine_business_profile import (
    LISTENER_HANDLE,
    LISTENER_ID,
    SoundEngineBusinessProfileError,
    load_soundengine_business_profile,
)
from wwise_waapi.runtime_game_object_handles import (
    RuntimeGameObjectContext,
    RuntimeGameObjectHandleStore,
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


def test_soundengine_profile_is_four_closed_terra_previews() -> None:
    profile = load_soundengine_business_profile(PROFILE)

    assert len(profile.units) == 4
    assert [unit.unit_id for unit in profile.units] == [
        "SOUND22-MONITOR-PREVIEW",
        "SOUND22-GAME-OBJECT-PREVIEW",
        "SOUND22-EVENT-PREVIEW",
        "SOUND22-LISTENER-PREVIEW",
    ]
    assert [unit.operation for unit in profile.units] == [
        "ak.soundengine.postMsgMonitor",
        "ak.soundengine.registerGameObj",
        "ak.soundengine.executeActionOnEvent",
        "ak.soundengine.setListenerSpatialization",
    ]
    assert {unit.version for unit in profile.units} == {"2022.1"}
    assert all(
        unit.user_turn_count == unit.transaction_count == 1
        for unit in profile.units
    )
    assert "SoundEngine 运行时 Profiler Capture Log" in profile.units[0].prompt_template
    assert "Authoring Log" not in profile.units[0].prompt_template


def test_soundengine_profile_rejects_unknown_filters() -> None:
    with pytest.raises(
        SoundEngineBusinessProfileError,
        match="unknown SoundEngine business",
    ):
        load_soundengine_business_profile(PROFILE, unit_ids=("missing",))


def test_soundengine_runtimes_contain_exact_closed_parameter_closure_requests(
    tmp_path: Path,
) -> None:
    units = load_soundengine_business_profile(PROFILE).units
    runtimes = [
        prepare_soundengine_business_runtime(unit, tmp_path / f"runtime-{index}")
        for index, unit in enumerate(units)
    ]
    fixtures = [
        json.loads(runtime.fixture_path.read_text(encoding="utf-8"))
        for runtime in runtimes
    ]

    assert all(fixture["version"] == "2022.1" for fixture in fixtures)
    assert all(fixture["is_command_line"] is False for fixture in fixtures)
    assert all("ak.soundengine" not in runtime.prompt for runtime in runtimes)
    assert runtimes[0].request["arguments"] == {
        "api": "ak.soundengine.postMsgMonitor",
        "args": {"message": "Fresh Agent SoundEngine business probe"},
        "options": {},
    }
    assert runtimes[1].request["arguments"]["api"] == (
        "ak.soundengine.registerGameObj"
    )
    assert runtimes[1].request["arguments"]["args"]["name"] == (
        "Fresh Weather Listener"
    )
    assert fixtures[2]["objects"] == [
        {
            "id": "{11111111-2222-3333-4444-555555555555}",
            "name": "Fresh Alarm Event",
            "path": r"\Events\Default Work Unit\Fresh Alarm Event",
            "type": "Event",
        }
    ]
    assert runtimes[2].request["arguments"]["args"] == {
        "event": "{11111111-2222-3333-4444-555555555555}",
        "actionType": 0,
        "gameObject": 0xFFFFFFFFFFFFFFFF,
        "transitionDuration": 250,
        "fadeCurve": 4,
    }
    assert runtimes[3].request["arguments"]["args"] == {
        "listener": 424242,
        "spatialized": True,
        "channelConfig": 6 | (1 << 8) | (0x60F << 12),
        "volumeOffsets": [0.0] * 6,
    }


def test_soundengine_protocols_are_singular_and_complete(tmp_path: Path) -> None:
    profile = load_soundengine_business_profile(PROFILE)
    for index, unit in enumerate(profile.units):
        prepare_soundengine_business_runtime(
            unit,
            tmp_path / f"runtime-{index}",
        )
        steps = build_soundengine_business_transaction_steps(
            version=unit.version,
            label="tx01",
            operation=unit.operation,
            monitor_message="Fresh Agent SoundEngine business probe",
            game_object_name="Fresh Weather Listener",
            event_id="{11111111-2222-3333-4444-555555555555}",
            event_name="Fresh Alarm Event",
            listener_handle="goh1-11111111111111111111111111111111",
            listener_id=424242,
        )
        validate_operation_draft_protocol_steps(steps)
        assert steps[-1].subcommand == "preview-from-draft"
        assert all(
            step.subcommand not in {"typed-call", "draft-apply", "execute"}
            for step in steps
        )


def test_listener_runtime_seeds_one_context_bound_opaque_handle(
    tmp_path: Path,
) -> None:
    unit = load_soundengine_business_profile(PROFILE).units[3]
    runtime = prepare_soundengine_business_runtime(unit, tmp_path / "runtime")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    prepare_soundengine_business_broker_state(runtime, state_dir)

    record = RuntimeGameObjectHandleStore(state_dir).resolve(
        LISTENER_HANDLE,
        context=RuntimeGameObjectContext(
            endpoint_url="ws://127.0.0.1:31337/waapi",
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path=str(runtime.project_path),
            wwise_version="2022.1",
            wwise_build="v2022.1.0.1",
        ),
    )
    assert record.game_object_id == LISTENER_ID
    assert record.game_object_name == "Seeded Fresh Listener"


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

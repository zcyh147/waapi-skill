from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_host_ui_debug_business_transaction_steps,
)
from tests.semantic.support.codex_host_ui_debug_business_agent_runner import (
    _host_ui_debug_business_run_spec,
    prepare_host_ui_debug_business_runtime,
)
from tests.semantic.support.codex_host_ui_debug_business_profile import (
    HostUiDebugBusinessProfileError,
    load_host_ui_debug_business_profile,
)


PROFILE = matrix.DEFAULT_HOST_UI_DEBUG_BUSINESS_SUITE


def test_host_ui_debug_business_profile_is_one_closed_terra_preview() -> None:
    profile = load_host_ui_debug_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "HOST25-TONE-PREVIEW"
    assert unit.operation == "ak.wwise.debug.generateToneWAV"
    assert unit.version == "2025.1"
    assert unit.transaction_count == 1
    assert "draft-" not in unit.prompt_template.casefold()
    assert "ak.wwise." not in unit.prompt_template.casefold()


def test_host_ui_debug_business_profile_rejects_unknown_filters() -> None:
    with pytest.raises(HostUiDebugBusinessProfileError):
        load_host_ui_debug_business_profile(PROFILE, unit_ids=("missing",))
    with pytest.raises(HostUiDebugBusinessProfileError):
        load_host_ui_debug_business_profile(PROFILE, versions=("2022.1",))


def test_host_ui_debug_runtime_closes_only_business_tone_values(tmp_path) -> None:
    unit = load_host_ui_debug_business_profile(PROFILE).units[0]
    runtime = prepare_host_ui_debug_business_runtime(unit, tmp_path / "runtime")

    assert str(runtime.output_file) in runtime.prompt
    args = runtime.request["arguments"]["args"]
    assert args["frequency"] == 440
    assert args["channelConfig"] == "2.0"
    assert args["waveformChannelMask"] == 3
    assert runtime.request["arguments"]["io_root"] == str(runtime.output_file.parent)
    assert not runtime.output_file.exists()


def test_host_ui_debug_protocol_is_one_complete_deep_draft(tmp_path) -> None:
    output = str((tmp_path / "FreshAgentTone.wav").resolve())
    steps = build_host_ui_debug_business_transaction_steps(
        version="2025.1",
        label="tx01",
        output_file=output,
    )

    assert tuple(step.subcommand for step in steps) == (
        "request-schema",
        "draft-start",
        "draft-declare-host-plan",
        "draft-check",
        "preview-from-draft",
    )
    declaration = steps[2].arguments
    assert "frequency_hz" in declaration
    assert "channel_layout" in declaration
    assert "waveformChannelMask" not in declaration
    assert "channelConfig" not in declaration
    assert all(step.subcommand not in {"typed-call", "draft-apply", "execute"} for step in steps)


def test_host_ui_debug_runner_allows_one_initial_operation_discovery() -> None:
    unit = load_host_ui_debug_business_profile(PROFILE).units[0]
    spec = _host_ui_debug_business_run_spec(unit)

    assert spec.optional_initial_operations_discovery_operation == unit.operation


def test_host_ui_debug_profile_is_registered_in_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2025.1"}
    assert descriptor.run_name == "run_host_ui_debug_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("HOST25-TONE-PREVIEW",),
            versions=("2025.1",),
        )
    )
    assert len(units) == 1
    assert matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID
    ] == "waapi-skill.host-ui-debug-business-agent-outcome/v1"

    options = matrix.parse_args(
        ["--profile", matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID]
    )
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_core_business_agent_runner import (
    _core_business_run_spec,
    prepare_core_business_runtime,
)
from tests.semantic.support.codex_core_business_profile import (
    CoreBusinessProfileError,
    load_core_business_profile,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_core_business_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import (
    validate_operation_draft_protocol_steps,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "tests" / "semantic" / "data" / "core-business" / "profile.json"


def test_core_business_profile_is_one_closed_terra_preview() -> None:
    profile = load_core_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "CORE25-PROJECT-SAVE-PREVIEW"
    assert unit.operation == "ak.wwise.core.project.save"
    assert unit.version == "2025.1"
    assert unit.user_turn_count == unit.transaction_count == 1


def test_core_business_profile_rejects_unknown_filters() -> None:
    with pytest.raises(CoreBusinessProfileError, match="unknown Core business"):
        load_core_business_profile(PROFILE, unit_ids=("missing",))
    with pytest.raises(CoreBusinessProfileError, match="does not support versions"):
        load_core_business_profile(PROFILE, versions=("2022.1",))


def test_core_business_runtime_is_offline_and_contains_no_native_request(
    tmp_path: Path,
) -> None:
    unit = load_core_business_profile(PROFILE).units[0]
    runtime = prepare_core_business_runtime(unit, tmp_path / "runtime")
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))

    assert fixture["version"] == "2025.1"
    assert fixture["objects"] == fixture["fields"] == fixture["assignments"] == []
    assert "ak.wwise" not in runtime.prompt
    assert runtime.request["operation"] == "waapi.call"
    assert runtime.request["arguments"] == {
        "api": "ak.wwise.core.project.save",
        "args": {"autoCheckOutToSourceControl": False},
        "options": {},
    }


def test_core_business_protocol_uses_one_complete_gateway_continuation() -> None:
    steps = build_core_business_transaction_steps(
        api="ak.wwise.core.project.save",
        version="2025.1",
        label="tx01",
    )
    validate_operation_draft_protocol_steps(steps)

    assert [step.subcommand for step in steps] == [
        "request-schema",
        "draft-start",
        "draft-declare-core-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[-1].expected_operation_request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.project.save",
            "args": {"autoCheckOutToSourceControl": False},
            "options": {},
        },
    }
    assert steps[2].arguments[-3:] == (
        "--value",
        "auto_check_out",
        "false",
    )
    assert all(step.subcommand not in {"typed-call", "draft-apply", "execute"} for step in steps)


def test_core_business_fresh_runner_allows_one_initial_operation_discovery() -> None:
    unit = load_core_business_profile(PROFILE).units[0]
    spec = _core_business_run_spec(unit)

    assert spec.requires_initial_operations_discovery is False
    assert spec.optional_initial_operations_discovery_operation == unit.operation


def test_core_business_profile_is_registered_in_the_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.CORE_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2025.1"}
    assert descriptor.run_name == "run_core_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.CORE_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("CORE25-PROJECT-SAVE-PREVIEW",),
            versions=("2025.1",),
        )
    )
    assert len(units) == 1
    assert matrix.CORE_BUSINESS_PROFILE_ID in campaign.TERRA_LOCKED_V3_PROFILE_IDS
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.CORE_BUSINESS_PROFILE_ID
    ] == "waapi-skill.core-business-agent-outcome/v1"

    options = matrix.parse_args(["--profile", matrix.CORE_BUSINESS_PROFILE_ID])
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

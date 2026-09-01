from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_debug_control_business_agent_runner import (
    prepare_debug_control_business_runtime,
)
from tests.semantic.support.codex_debug_control_business_profile import (
    DebugControlBusinessProfileError,
    load_debug_control_business_profile,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_debug_control_business_transaction_steps,
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
    / "debug-control-business"
    / "profile.json"
)


def test_debug_control_profile_is_one_closed_safe_preview() -> None:
    profile = load_debug_control_business_profile(PROFILE)

    assert len(profile.units) == 1
    unit = profile.units[0]
    assert unit.unit_id == "DBG21-AUTOMATION-PREVIEW"
    assert unit.operation == "debug.setAutomationMode"
    assert unit.version == "2021.1"
    assert unit.user_turn_count == unit.transaction_count == 1


def test_debug_control_profile_rejects_unknown_filters() -> None:
    with pytest.raises(
        DebugControlBusinessProfileError,
        match="unknown Debug-control business",
    ):
        load_debug_control_business_profile(PROFILE, unit_ids=("missing",))


def test_debug_control_runtime_uses_production_gateway_without_wwise(
    tmp_path: Path,
) -> None:
    unit = load_debug_control_business_profile(PROFILE).units[0]
    runtime = prepare_debug_control_business_runtime(unit, tmp_path / "runtime")
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))

    assert fixture["version"] == "2021.1"
    assert fixture["objects"] == []
    assert "ak.wwise" not in runtime.prompt
    assert runtime.request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2021.1",
        "operation": "debug.setAutomationMode",
        "arguments": {"enabled": True},
    }


def test_debug_fixture_supplies_the_2021_project_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = load_debug_control_business_profile(PROFILE).units[0]
    runtime = prepare_debug_control_business_runtime(unit, tmp_path / "runtime")
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
        "debug_control_business_waapi_shim",
        shim_path,
    )
    assert spec is not None and spec.loader is not None
    shim = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = shim
    spec.loader.exec_module(shim)
    monkeypatch.setenv("WAAPI_BUSINESS_AGENT_FIXTURE", str(runtime.fixture_path))

    result = shim.WaapiClient().call(
        "ak.wwise.core.object.get",
        {"waql": "from type Project take 1"},
        {"return": ["id", "name", "type", "path", "filePath"]},
    )

    assert result == {
        "return": [
            {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "SemanticProject",
                "type": "Project",
                "path": str(runtime.fixture_path.parent / "project"),
                "filePath": str(
                    runtime.fixture_path.parent
                    / "project"
                    / "SemanticProject.wproj"
                ),
            }
        ]
    }


def test_debug_control_protocol_is_singular_and_complete() -> None:
    steps = build_debug_control_business_transaction_steps(
        version="2021.1",
        label="tx01",
        enabled=True,
    )
    validate_operation_draft_protocol_steps(steps)

    assert [step.subcommand for step in steps] == [
        "operation-schema",
        "draft-start",
        "draft-declare-debug-intent",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[-1].expected_operation_request["arguments"] == {"enabled": True}
    assert all(
        step.subcommand not in {"typed-call", "draft-apply", "execute"}
        for step in steps
    )


def test_debug_control_profile_is_registered_in_formal_terra_lane() -> None:
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.DEBUG_CONTROL_BUSINESS_PROFILE_ID
    ]
    assert descriptor.suite_path == PROFILE
    assert descriptor.supported_versions == {"2021.1"}
    assert descriptor.run_name == "run_debug_control_business_agent_unit"
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.DEBUG_CONTROL_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("DBG21-AUTOMATION-PREVIEW",),
            versions=("2021.1",),
        )
    )
    assert len(units) == 1
    assert matrix.DEBUG_CONTROL_BUSINESS_PROFILE_ID in (
        campaign.TERRA_LOCKED_V3_PROFILE_IDS
    )
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.DEBUG_CONTROL_BUSINESS_PROFILE_ID
    ] == "waapi-skill.debug-control-business-agent-outcome/v1"

    options = matrix.parse_args(
        ["--profile", matrix.DEBUG_CONTROL_BUSINESS_PROFILE_ID]
    )
    assert options.model == "gpt-5.6-terra"
    assert options.reasoning_effort == "medium"
    assert options.service_tier == "default"

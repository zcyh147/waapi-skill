from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support.codex_authoring_ui_business_agent_runner import (
    _final_response_reports_preview,
    prepare_authoring_ui_business_runtime,
)
from tests.semantic.support.codex_authoring_ui_business_profile import (
    AuthoringUiBusinessProfileError,
    load_authoring_ui_business_profile,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_authoring_ui_business_transaction_steps,
)


PROFILE = matrix.DEFAULT_AUTHORING_UI_BUSINESS_SUITE


def test_profile_owns_capture_and_command_units_with_terra_defaults() -> None:
    profile = load_authoring_ui_business_profile(PROFILE)

    assert [unit.unit_id for unit in profile.units] == [
        "AUI22-CAPTURE-PREVIEW",
        "AUI25-SAVE-PREVIEW",
    ]
    assert [unit.version for unit in profile.units] == ["2022.1", "2025.1"]
    assert matrix.AUTHORING_UI_BUSINESS_PROFILE_ID in (
        matrix.EXECUTABLE_V3_PROFILE_IDS
    )
    descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
        matrix.AUTHORING_UI_BUSINESS_PROFILE_ID
    ]
    assert descriptor.supported_versions == frozenset({"2022.1", "2025.1"})
    units = matrix.load_heavy_v3_units(
        SimpleNamespace(
            profile=matrix.AUTHORING_UI_BUSINESS_PROFILE_ID,
            suite_path=PROFILE,
            case_ids=("AUI22-CAPTURE-PREVIEW", "AUI25-SAVE-PREVIEW"),
            versions=("2022.1", "2025.1"),
        )
    )
    assert len(units) == 2
    assert matrix.AUTHORING_UI_BUSINESS_PROFILE_ID in (
        campaign.TERRA_LOCKED_V3_PROFILE_IDS
    )
    assert campaign.BUSINESS_AGENT_OUTCOME_CONTRACTS[
        matrix.AUTHORING_UI_BUSINESS_PROFILE_ID
    ] == "waapi-skill.authoring-ui-business-agent-outcome/v1"


@pytest.mark.parametrize("unit_id", ("AUI22-CAPTURE-PREVIEW", "AUI25-SAVE-PREVIEW"))
def test_each_unit_compiles_to_one_closed_public_business_preview(
    tmp_path: Path,
    unit_id: str,
) -> None:
    unit = load_authoring_ui_business_profile(
        PROFILE,
        unit_ids=(unit_id,),
    ).units[0]
    runtime = prepare_authoring_ui_business_runtime(unit, tmp_path / unit_id)
    steps = build_authoring_ui_business_transaction_steps(
        runtime.request,
        label="tx01",
    )

    expected = [
        "operations",
        "operation-schema",
        "draft-start",
        "draft-declare-ui-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert [step.subcommand for step in steps] == expected
    assert "ak.wwise.ui.commands.getCommands" not in [
        str(argument) for step in steps for argument in step.arguments
    ]
    assert steps[-1].expected_operation_request == runtime.request
    fixture = json.loads(runtime.fixture_path.read_text(encoding="utf-8"))
    assert fixture["is_command_line"] is False
    assert fixture["command_ids"] == ["SaveProject"]


def test_profile_rejects_prompt_level_gateway_mechanics(tmp_path: Path) -> None:
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    payload["units"][0]["prompt"] += " draft-start"
    path = tmp_path / "bad-profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AuthoringUiBusinessProfileError, match="prompt"):
        load_authoring_ui_business_profile(path)


def test_preview_report_accepts_natural_business_wording_without_command_id() -> None:
    assert _final_response_reports_preview(
        "已生成保存当前 Wwise 项目的执行预览，未执行，项目未发生任何更改。",
        operation="ui.commands.execute",
        markers=("SaveProject",),
    )


def test_authoring_fixture_shim_reports_host_and_bounded_command_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = load_authoring_ui_business_profile(
        PROFILE,
        unit_ids=("AUI25-SAVE-PREVIEW",),
    ).units[0]
    runtime = prepare_authoring_ui_business_runtime(unit, tmp_path / "runtime")
    shim_path = (
        Path(__file__).parent
        / "data"
        / "business-agent"
        / "waapi-shim"
        / "waapi.py"
    )
    spec = importlib.util.spec_from_file_location(
        "authoring_ui_business_waapi_shim",
        shim_path,
    )
    assert spec is not None and spec.loader is not None
    shim = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = shim
    spec.loader.exec_module(shim)
    monkeypatch.setenv("WAAPI_BUSINESS_AGENT_FIXTURE", str(runtime.fixture_path))

    client = shim.WaapiClient()

    assert client.call("ak.wwise.core.getInfo")["isCommandLine"] is False
    assert client.call("ak.wwise.ui.commands.getCommands") == {
        "commands": ["SaveProject"]
    }

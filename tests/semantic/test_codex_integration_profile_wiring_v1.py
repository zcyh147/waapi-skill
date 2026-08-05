from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner
from tests.semantic.support import codex_integration_alarm_runtime_v1 as alarm_runtime
from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep
from tests.semantic.support.codex_integration_workflows_v1 import (
    PROFILE_ID,
    VERSIONS,
    WORKFLOW_IDS,
    IntegrationWorkflowUnit,
    load_integration_workflows_profile,
)
from tests.semantic.support.codex_workflow_business_plan_v3 import (
    WorkflowBusinessPlanError,
    WorkflowBusinessPlanSections,
    compile_workflow_business_plan_sections,
)


PROFILE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "integration-workflows-v1"
    / "profile.json"
)


def _dependency_args(tmp_path: Path) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    codex = tmp_path / "codex.exe"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    codex.write_text("not invoked\n", encoding="utf-8")
    codex.chmod(0o755)
    auth.write_text("{}\n", encoding="utf-8")
    live.write_text("{}\n", encoding="utf-8")
    return [
        "--codex-binary",
        str(codex),
        "--auth-json",
        str(auth),
        "--live-config",
        str(live),
    ]


def _matrix_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--profile",
        PROFILE_ID,
        *_dependency_args(tmp_path),
        *extra,
    ]


def _campaign_args(
    tmp_path: Path,
    *extra: str,
) -> list[str]:
    return [
        "--campaign-root",
        str(tmp_path / "campaign"),
        "--profile",
        PROFILE_ID,
        *_dependency_args(tmp_path),
        *extra,
    ]


def _operation_request(
    operation: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": operation,
        "arguments": arguments,
    }


def _workflow_protocol(unit: IntegrationWorkflowUnit) -> V3GatewayProtocol:
    requests = []
    for transaction in unit.transactions:
        arguments = (
            {
                "soundbanks": [{"name": "Harbor_Release"}],
                "platforms": ["Windows", "Mac"],
                "languages": ["SFX"],
            }
            if transaction.operation == "soundbank.generate"
            else {"integration_transaction": transaction.index}
        )
        requests.append(
            _operation_request(transaction.operation, arguments)
        )
    transaction_protocol = build_transaction_protocol(tuple(requests))
    if unit.workflow_id != "alarm_diagnose_and_repair":
        return transaction_protocol
    diagnostic = ExpectedGatewayStep(
        name="alarm.diagnosis",
        subcommand="query-object",
        arguments=("--path", "\\Events\\Alarm\\Play_Alarm"),
    )
    return V3GatewayProtocol(
        steps=(diagnostic, *transaction_protocol.steps),
        turn_prefix_counts=(
            1,
            *(
                count + 1
                for count in transaction_protocol.turn_prefix_counts
            ),
        ),
    )


def _units() -> tuple[IntegrationWorkflowUnit, ...]:
    return load_integration_workflows_profile(PROFILE_PATH).units


def _unit(
    workflow_id: str,
    *,
    version: str = "2022.1",
) -> IntegrationWorkflowUnit:
    matches = [
        unit
        for unit in _units()
        if unit.workflow_id == workflow_id and unit.version == version
    ]
    assert len(matches) == 1
    return matches[0]


def test_campaign_maps_alarm_domain_turns_to_generic_receipt_kinds() -> None:
    unit = _unit("alarm_diagnose_and_repair")

    assert tuple(
        campaign._heavy_v3_receipt_kind_for_reviewed_turn(
            unit,
            turn,
            index=index,
        )
        for index, turn in enumerate(unit.turns, start=1)
    ) == ("request", "confirmation", "confirmation")


def test_alarm_uses_reviewed_cross_lane_reference_schedule() -> None:
    alarm = _unit("alarm_diagnose_and_repair")

    assert campaign._heavy_v3_required_reference(alarm) == (
        "references/waapi-query.md"
    )
    assert campaign._heavy_v3_expected_skill_reads(alarm) == (
        ("SKILL.md", "references/waapi-query.md"),
        ("references/waapi-operate.md",),
        (),
    )

    for workflow_id in (
        "interactive_weather_build",
        "harbor_soundbank_release",
    ):
        unit = _unit(workflow_id)
        assert campaign._heavy_v3_expected_skill_reads(unit) == (
            (("SKILL.md", "references/waapi-operate.md"),)
            + ((),) * (unit.user_turn_count - 1)
        )


def test_project_runner_wires_alarm_cross_lane_reference_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = _unit("alarm_diagnose_and_repair")
    protocol = _workflow_protocol(unit)
    visible_values = {
        "alarm_event_path": r"\Events\Default Work Unit\Alarm",
        "alarm_target_bus_path": r"\Master-Mixer Hierarchy\Default Work Unit\SFX",
    }
    prepared_runtime = SimpleNamespace(
        visible_values=visible_values,
        protocol=protocol,
        snapshot=lambda: ("before",),
        verify_turn=lambda _turn, _result: SimpleNamespace(passed=True),
        verify_final=lambda _payload, _result: SimpleNamespace(passed=True),
        cleanup=lambda: (),
        observe_payload=lambda _step, _payload: None,
        expected_dispatches=(
            ("ak.wwise.core.object.setReference", 1),
        ),
        oracle_requirements=(),
    )
    monkeypatch.setattr(
        alarm_runtime,
        "prepare_alarm_integration_runtime",
        lambda *_args, **_kwargs: prepared_runtime,
    )
    runtime = SimpleNamespace(
        version=unit.version,
        scenario_root=Path("/tmp/alarm-scenario"),
        owned_root=Path("/tmp/alarm-scenario/owned"),
        asset_root=Path("/tmp/alarm-scenario/owned/assets"),
        io_root=Path("/tmp/alarm-scenario/owned/io"),
    )

    prepared = project_runner._prepare_integration_workflow_case(
        unit.scenario,
        runtime=runtime,
        direct=object(),
        unit=unit,
    )

    assert prepared.required_reference == "references/waapi-query.md"
    assert prepared.turn_reference_schedule == (
        ("references/waapi-query.md",),
        ("references/waapi-operate.md",),
        (),
    )
    assert prepared.expected_dispatches == (
        ("ak.wwise.core.object.setReference", 1),
    )


def test_alarm_mutation_dispatch_audit_ignores_transaction_support_reads(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    apis = (
        *("ak.wwise.core.object.get" for _ in range(13)),
        "ak.wwise.core.object.setReference",
    )
    for index, api in enumerate(apis, start=1):
        path = evidence_root / f"{index:02d}.json"
        path.write_text(
            json.dumps({"api": api, "evidence_path": str(path)}),
            encoding="utf-8",
        )
    task = SimpleNamespace(
        broker_evidence=SimpleNamespace(
            evidence_directory=str(evidence_root),
        )
    )

    proof = project_runner._audit_workflow_dispatch(
        task=task,
        expected_dispatches=(
            ("ak.wwise.core.object.setReference", 1),
        ),
    )

    assert dict(proof["expected"]) == {
        "ak.wwise.core.object.setReference": 1,
    }
    assert dict(proof["observed"]) == {
        "ak.wwise.core.object.setReference": 1,
    }
    assert proof["total_expected_dispatches"] == 1


def test_campaign_alarm_dispatch_contract_counts_mutations_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = _unit("alarm_diagnose_and_repair")
    transaction_api = "ak.wwise.core.object.setReference"
    checks = {
        "task_passed": True,
        "direct_client_closed": True,
        "first_use_intro": True,
        "final_response_nonempty": True,
        "primary_dispatch": {
            "api": transaction_api,
            "dispatch_count": 1,
        },
        "workflow_dispatch": {
            "expected": {transaction_api: 1},
            "observed": {transaction_api: 1},
            "total_expected_dispatches": 1,
        },
        "runtime_cleanup": {},
    }
    monkeypatch.setattr(
        campaign,
        "_validate_heavy_v3_archived_verification",
        lambda *_args, **_kwargs: None,
    )

    campaign._validate_heavy_v3_pass_checks(
        checks,
        expected_unit=unit,
        expected_row={
            "api": transaction_api,
            "runner": "project",
            "version": unit.version,
        },
        expected_thread_id="unused-for-project-runner",
        primary_count=1,
        task_root=Path("/synthetic/task"),
        prompt_evidence=SimpleNamespace(
            typed_sections=_workflow_sections(
                unit,
                _workflow_protocol(unit),
            )
        ),
    )


@pytest.mark.parametrize(
    ("turn_index", "tampered_kind"),
    (
        (1, "request"),
        (2, "confirmation"),
        (3, "change_request"),
    ),
)
def test_campaign_rejects_tampered_alarm_domain_turn_kinds(
    turn_index: int,
    tampered_kind: str,
) -> None:
    unit = _unit("alarm_diagnose_and_repair")
    turn = replace(unit.turns[turn_index - 1], kind=tampered_kind)

    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="invalid request/confirmation order",
    ):
        campaign._heavy_v3_receipt_kind_for_reviewed_turn(
            unit,
            turn,
            index=turn_index,
        )


@pytest.mark.parametrize(
    "workflow_id",
    ("interactive_weather_build", "harbor_soundbank_release"),
)
def test_campaign_keeps_generic_turn_order_for_other_workflows(
    workflow_id: str,
) -> None:
    unit = _unit(workflow_id)

    assert tuple(
        campaign._heavy_v3_receipt_kind_for_reviewed_turn(
            unit,
            turn,
            index=index,
        )
        for index, turn in enumerate(unit.turns, start=1)
    ) == ("request", *(("confirmation",) * (unit.user_turn_count - 1)))

    tampered = replace(unit.turns[0], kind="diagnosis_request")
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="invalid request/confirmation order",
    ):
        campaign._heavy_v3_receipt_kind_for_reviewed_turn(
            unit,
            tampered,
            index=1,
        )


def _workflow_sections(
    unit: IntegrationWorkflowUnit,
    protocol: V3GatewayProtocol,
) -> WorkflowBusinessPlanSections:
    return project_runner._compile_integration_workflow_plan(
        unit=unit,
        protocol=protocol,
        visible_values={"profile_unit": unit.unit_id},
        oracle_requirements=(),
    )


def _provenance(
    unit: IntegrationWorkflowUnit,
    protocol: V3GatewayProtocol,
) -> Any:
    return SimpleNamespace(
        protocol=protocol,
        visible_values={"profile_unit": unit.unit_id},
    )


def _recompile_workflow_payload(
    payload: dict[str, Any],
) -> WorkflowBusinessPlanSections:
    static = payload["static_expectation"]
    return compile_workflow_business_plan_sections(
        workflow_id=static["workflow_id"],
        transactions=static["transactions"],
        workflow_steps=static["workflow_steps"],
        diagnostic_evidence=[
            {
                key: value
                for key, value in row.items()
                if key != "expectation_sha256"
            }
            for row in static["diagnostic_evidence"]
        ],
        live_bindings=payload["live_binding"]["bindings"],
        transaction_expectations=[
            {
                "transaction_id": row["transaction_id"],
                "expectation": row["expectation"],
            }
            for row in payload["delta_rules"]
        ],
    )


def test_matrix_integration_defaults_and_explicit_terra_lock(
    tmp_path: Path,
) -> None:
    defaults = matrix.parse_args(_matrix_args(tmp_path))
    explicit = matrix.parse_args(
        _matrix_args(
            tmp_path / "explicit",
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
            "--version",
            "2022.1",
            "--version",
            "2025.1",
        )
    )

    assert defaults.profile == PROFILE_ID
    assert defaults.model == explicit.model == "gpt-5.6-terra"
    assert defaults.reasoning_effort == explicit.reasoning_effort == "medium"
    assert defaults.service_tier == explicit.service_tier == "default"
    assert defaults.suite_path == (
        matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE.resolve()
    )
    assert defaults.iteration_root == (
        matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_ITERATION_ROOT.resolve()
    )
    assert defaults.versions == ()
    assert explicit.versions == VERSIONS


def test_campaign_integration_defaults_and_explicit_terra_lock(
    tmp_path: Path,
) -> None:
    defaults = campaign.parse_args(_campaign_args(tmp_path))
    explicit = campaign.parse_args(
        _campaign_args(
            tmp_path / "explicit",
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
            "--version",
            "2022.1",
            "--version",
            "2025.1",
        )
    )

    assert defaults.profile == PROFILE_ID
    assert defaults.model == explicit.model == "gpt-5.6-terra"
    assert defaults.reasoning_effort == explicit.reasoning_effort == "medium"
    assert defaults.service_tier == explicit.service_tier == "default"
    assert defaults.suite_path == (
        matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE.resolve()
    )
    assert defaults.campaign_root == (tmp_path / "campaign").resolve()
    assert defaults.versions == ()
    assert explicit.versions == VERSIONS


@pytest.mark.parametrize(
    "override",
    (
        ("--model", "gpt-5.6-sol"),
        ("--reasoning-effort", "high"),
        ("--service-tier", "priority"),
    ),
)
@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_integration_profile_rejects_terra_lock_overrides(
    tmp_path: Path,
    surface: str,
    override: tuple[str, str],
) -> None:
    argv = (
        _matrix_args(tmp_path, *override)
        if surface == "matrix"
        else _campaign_args(tmp_path, *override)
    )
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args

    with pytest.raises(SystemExit):
        parser(argv)


@pytest.mark.parametrize("version", ("2021.1", "2023.1", "2024.1"))
@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_integration_profile_rejects_versions_outside_2022_and_2025(
    tmp_path: Path,
    surface: str,
    version: str,
) -> None:
    argv = (
        _matrix_args(tmp_path, "--version", version)
        if surface == "matrix"
        else _campaign_args(tmp_path, "--version", version)
    )
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args

    with pytest.raises(SystemExit):
        parser(argv)


def test_matrix_loader_returns_six_units_and_honors_filters(
    tmp_path: Path,
) -> None:
    options = matrix.parse_args(_matrix_args(tmp_path))

    complete = matrix.load_heavy_v3_units(options)
    selected = matrix.load_heavy_v3_units(
        replace(
            options,
            case_ids=("INT25-ALARM-DIAGNOSE-AND-REPAIR",),
            versions=("2025.1",),
        )
    )

    assert len(complete) == 6
    assert [unit.workflow_id for unit in complete] == [
        *WORKFLOW_IDS,
        *WORKFLOW_IDS,
    ]
    assert [unit.version for unit in complete] == [
        "2022.1",
        "2022.1",
        "2022.1",
        "2025.1",
        "2025.1",
        "2025.1",
    ]
    assert [unit.unit_id for unit in selected] == [
        "INT25-ALARM-DIAGNOSE-AND-REPAIR"
    ]


@pytest.mark.parametrize("workflow_id", WORKFLOW_IDS)
def test_project_runner_compiles_complete_integration_plan_topology(
    workflow_id: str,
) -> None:
    unit = _unit(workflow_id)
    protocol = _workflow_protocol(unit)
    sections = _workflow_sections(unit, protocol)
    static = sections.static_expectation

    assert [
        (
            row["transaction_id"],
            row["api"],
            row["operation"],
            row["primary_step"],
        )
        for row in static["transactions"]
    ] == [
        (
            f"tx{index:02d}",
            transaction.api,
            transaction.operation,
            f"tx{index:02d}.execute",
        )
        for index, transaction in enumerate(unit.transactions, start=1)
    ]
    assert [row["name"] for row in static["workflow_steps"]] == [
        *(step.name for step in protocol.steps),
        "cleanup.success",
    ]
    assert list(sections.payload_bindings["primary_steps"]) == [
        f"tx{index:02d}.execute"
        for index in range(1, unit.transaction_count + 1)
    ]
    assert len(sections.delta_rules) == unit.transaction_count
    if workflow_id == "alarm_diagnose_and_repair":
        assert len(static["diagnostic_evidence"]) == 1
        assert static["diagnostic_evidence"][0]["step"] == "alarm.diagnosis"
    else:
        assert list(static["diagnostic_evidence"]) == []


def test_project_runner_normalizes_integration_dispatch_vector() -> None:
    first = "ak.wwise.core.audio.import"
    second = "ak.wwise.core.object.set"

    normalized = project_runner._integration_expected_dispatches(
        (
            (first, 1),
            SimpleNamespace(api=second, count=2),
            (first, 3),
        )
    )

    assert normalized == ((first, 4), (second, 2))
    with pytest.raises(
        project_runner.HeavyProjectRunnerError,
        match="invalid dispatch",
    ):
        project_runner._integration_expected_dispatches(
            (("not-an-api", 1),)
        )
    with pytest.raises(
        project_runner.HeavyProjectRunnerError,
        match="invalid dispatch",
    ):
        project_runner._integration_expected_dispatches(
            ((first, 0),)
        )


@pytest.mark.parametrize(
    ("workflow_id", "version", "platforms", "auro"),
    (
        (
            "interactive_weather_build",
            "2022.1",
            ("Windows",),
            None,
        ),
        (
            "harbor_soundbank_release",
            "2022.1",
            ("Windows", "Mac"),
            None,
        ),
        (
            "harbor_soundbank_release",
            "2025.1",
            ("Windows", "Mac"),
            project_runner.WWISE_2025_SOUNDBANK_AURO_PROFILE,
        ),
    ),
)
def test_project_runner_uses_integration_specific_prelaunch_request(
    monkeypatch: pytest.MonkeyPatch,
    workflow_id: str,
    version: str,
    platforms: tuple[str, ...],
    auro: str | None,
) -> None:
    captured: list[Any] = []

    def capture(request: Any) -> Any:
        captured.append(request)
        return request

    monkeypatch.setattr(
        project_runner,
        "make_project_prelaunch_hook",
        capture,
    )
    scenario = _unit(workflow_id, version=version).scenario

    result = project_runner._prelaunch_hook(
        scenario,
        media_holder={},
        version=version,
    )

    assert result is captured[0]
    assert captured[0].scenario_id == scenario.id
    assert captured[0].languages == ("SFX",)
    assert captured[0].platforms == platforms
    assert captured[0].auro_isolation_profile == auro


@pytest.mark.parametrize("workflow_id", WORKFLOW_IDS)
def test_campaign_parses_and_rebinds_integration_workflow_plan(
    workflow_id: str,
) -> None:
    unit = _unit(workflow_id)
    protocol = _workflow_protocol(unit)
    sections = _workflow_sections(unit, protocol)

    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=unit,
        provenance=_provenance(unit, protocol),
    )

    assert isinstance(parsed, WorkflowBusinessPlanSections)
    assert parsed.writer_kwargs() == sections.writer_kwargs()


def test_campaign_rejects_structurally_tampered_workflow_plan() -> None:
    unit = _unit("interactive_weather_build")
    protocol = _workflow_protocol(unit)
    payload = _workflow_sections(unit, protocol).writer_kwargs()
    payload["static_expectation"]["unexpected"] = True

    with pytest.raises(WorkflowBusinessPlanError, match="not closed"):
        campaign._validate_heavy_v3_typed_business_plan(
            payload,
            expected_unit=unit,
            provenance=_provenance(unit, protocol),
        )


def test_campaign_rejects_cross_bound_transaction_and_protocol_steps() -> None:
    unit = _unit("interactive_weather_build")
    protocol = _workflow_protocol(unit)
    first = unit.transactions[0]
    wrong_transaction = SimpleNamespace(
        index=first.index,
        operation="object.create",
        api="ak.wwise.core.object.create",
    )
    wrong_unit = SimpleNamespace(
        workflow_id=unit.workflow_id,
        version=unit.version,
        transactions=(wrong_transaction, *unit.transactions[1:]),
    )
    cross_bound = project_runner._compile_integration_workflow_plan(
        unit=wrong_unit,
        protocol=protocol,
        visible_values={"profile_unit": unit.unit_id},
        oracle_requirements=(),
    )
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="transaction topology drifted",
    ):
        campaign._validate_heavy_v3_typed_business_plan(
            cross_bound.writer_kwargs(),
            expected_unit=unit,
            provenance=_provenance(unit, protocol),
        )

    checkpoint = ExpectedGatewayStep(
        name="unexpected.checkpoint",
        subcommand="capabilities",
    )
    changed_protocol = V3GatewayProtocol(
        steps=(*protocol.steps, checkpoint),
        turn_prefix_counts=(
            *protocol.turn_prefix_counts[:-1],
            protocol.turn_prefix_counts[-1] + 1,
        ),
    )
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="steps differ",
    ):
        campaign._validate_heavy_v3_typed_business_plan(
            _workflow_sections(unit, protocol).writer_kwargs(),
            expected_unit=unit,
            provenance=_provenance(unit, changed_protocol),
        )


def test_campaign_rejects_workflow_live_values_not_bound_to_provenance() -> None:
    unit = _unit("interactive_weather_build")
    protocol = _workflow_protocol(unit)
    tampered = project_runner._compile_integration_workflow_plan(
        unit=unit,
        protocol=protocol,
        visible_values={"profile_unit": "INT22-TAMPERED"},
        oracle_requirements=(),
    )

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_heavy_v3_typed_business_plan(
            tampered.writer_kwargs(),
            expected_unit=unit,
            provenance=_provenance(unit, protocol),
        )


def test_campaign_rejects_rehashed_unreviewed_extra_live_binding() -> None:
    unit = _unit("interactive_weather_build")
    protocol = _workflow_protocol(unit)
    payload = copy.deepcopy(
        _workflow_sections(unit, protocol).writer_kwargs()
    )
    payload["live_binding"]["bindings"]["unreviewed_extra"] = {
        "switch": True,
    }
    tampered = _recompile_workflow_payload(payload)

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_heavy_v3_typed_business_plan(
            tampered.writer_kwargs(),
            expected_unit=unit,
            provenance=_provenance(unit, protocol),
        )


def test_campaign_rejects_rehashed_workflow_phase_tamper() -> None:
    unit = _unit("interactive_weather_build")
    protocol = _workflow_protocol(unit)
    payload = copy.deepcopy(
        _workflow_sections(unit, protocol).writer_kwargs()
    )
    payload["static_expectation"]["transactions"][0][
        "phase"
    ] = "tampered.phase"
    for row in payload["static_expectation"]["workflow_steps"]:
        if row["transaction_id"] == "tx01":
            row["phase"] = "tampered.phase"
    tampered = _recompile_workflow_payload(payload)

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_heavy_v3_typed_business_plan(
            tampered.writer_kwargs(),
            expected_unit=unit,
            provenance=_provenance(unit, protocol),
        )


def test_campaign_rejects_rehashed_diagnostic_step_reclassification() -> None:
    unit = _unit("alarm_diagnose_and_repair")
    protocol = _workflow_protocol(unit)
    payload = copy.deepcopy(
        _workflow_sections(unit, protocol).writer_kwargs()
    )
    diagnostic = payload["static_expectation"]["workflow_steps"][0]
    assert diagnostic["name"] == "alarm.diagnosis"
    diagnostic["kind"] = "checkpoint"
    payload["static_expectation"]["diagnostic_evidence"] = []
    tampered = _recompile_workflow_payload(payload)

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_heavy_v3_typed_business_plan(
            tampered.writer_kwargs(),
            expected_unit=unit,
            provenance=_provenance(unit, protocol),
        )


@pytest.mark.parametrize(
    ("workflow_id", "verification"),
    (
        (
            "interactive_weather_build",
            {
                "workflow_id": "interactive_weather_build",
                "phase": "workflow_complete",
                "passed": True,
                "failures": [],
                "evidence": {"five_sounds": True},
            },
        ),
        (
            "alarm_diagnose_and_repair",
            {
                "phase": "after_repair",
                "passed": True,
                "failures": [],
                "before": {"output_bus_id": "Ambient"},
                "after": {"output_bus_id": "Emergency"},
                "changed_fields": ["sound.details.output_bus_id"],
            },
        ),
        (
            "harbor_soundbank_release",
            {
                "phase": "final",
                "passed": True,
                "failures": [],
                "before": {"generated": False},
                "after": {"generated": True},
                "evidence": {"platforms": ["Windows", "Mac"]},
            },
        ),
    ),
)
def test_campaign_accepts_closed_integration_verification(
    workflow_id: str,
    verification: dict[str, Any],
) -> None:
    unit = _unit(workflow_id)
    sections = _workflow_sections(unit, _workflow_protocol(unit))

    campaign._validate_integration_workflow_verification(
        sections,
        verification,
        label=workflow_id,
    )


@pytest.mark.parametrize(
    ("workflow_id", "verification", "message"),
    (
        (
            "interactive_weather_build",
            {
                "workflow_id": "harbor_soundbank_release",
                "phase": "final",
                "passed": True,
                "failures": [],
                "evidence": {},
            },
            "identity",
        ),
        (
            "alarm_diagnose_and_repair",
            {
                "phase": "after_repair",
                "passed": True,
                "failures": [],
                "before": {},
                "after": {},
                "changed_fields": ["sound.details.volume"],
            },
            "OutputBus-only",
        ),
        (
            "harbor_soundbank_release",
            {
                "phase": "unreviewed",
                "passed": True,
                "failures": [],
                "before": {},
                "after": {},
                "evidence": {},
            },
            "phase",
        ),
    ),
)
def test_campaign_rejects_tampered_integration_verification(
    workflow_id: str,
    verification: dict[str, Any],
    message: str,
) -> None:
    unit = _unit(workflow_id)
    sections = _workflow_sections(unit, _workflow_protocol(unit))

    with pytest.raises(campaign.CampaignEvidenceError, match=message):
        campaign._validate_integration_workflow_verification(
            sections,
            verification,
            label=workflow_id,
        )


def test_campaign_rejects_empty_weather_verification_with_arbitrary_phase() -> None:
    unit = _unit("interactive_weather_build")
    sections = _workflow_sections(unit, _workflow_protocol(unit))

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_integration_workflow_verification(
            sections,
            {
                "workflow_id": "interactive_weather_build",
                "phase": "arbitrary",
                "passed": True,
                "failures": [],
                "evidence": {},
            },
            label=unit.workflow_id,
        )


def test_campaign_rejects_alarm_repair_claim_without_a_real_delta() -> None:
    unit = _unit("alarm_diagnose_and_repair")
    sections = _workflow_sections(unit, _workflow_protocol(unit))

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_integration_workflow_verification(
            sections,
            {
                "phase": "after_repair",
                "passed": True,
                "failures": [],
                "before": {},
                "after": {},
                "changed_fields": ["sound.details.output_bus_id"],
            },
            label=unit.workflow_id,
        )


def test_campaign_rejects_harbor_verification_without_evidence_or_delta() -> None:
    unit = _unit("harbor_soundbank_release")
    sections = _workflow_sections(unit, _workflow_protocol(unit))

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_integration_workflow_verification(
            sections,
            {
                "phase": "final",
                "passed": True,
                "failures": [],
                "before": {},
                "after": {},
                "evidence": {},
            },
            label=unit.workflow_id,
        )


@pytest.mark.parametrize(
    ("workflow_id", "foreign_shape"),
    (
        (
            "harbor_soundbank_release",
            {
                "workflow_id": "harbor_soundbank_release",
                "phase": "final",
                "passed": True,
                "failures": [],
                "evidence": {},
            },
        ),
        (
            "interactive_weather_build",
            {
                "phase": "final",
                "passed": True,
                "failures": [],
                "before": {},
                "after": {},
                "evidence": {},
            },
        ),
        (
            "alarm_diagnose_and_repair",
            {
                "workflow_id": "alarm_diagnose_and_repair",
                "phase": "final",
                "passed": True,
                "failures": [],
                "evidence": {},
            },
        ),
    ),
)
def test_campaign_rejects_cross_workflow_verification_schema(
    workflow_id: str,
    foreign_shape: dict[str, Any],
) -> None:
    unit = _unit(workflow_id)
    sections = _workflow_sections(unit, _workflow_protocol(unit))

    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_integration_workflow_verification(
            sections,
            foreign_shape,
            label=workflow_id,
        )

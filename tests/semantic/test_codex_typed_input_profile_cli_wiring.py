from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_typed_input_profile import PROFILE_ID
from tests.semantic.support.codex_direct_business_plan_v3 import (
    compile_direct_business_plan,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    ExpectedGatewayStep,
    build_direct_protocol,
)


def _dependencies(tmp_path: Path) -> list[str]:
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    codex = tmp_path / "codex"
    codex.write_text("synthetic", encoding="utf-8")
    return [
        "--codex-binary",
        str(codex),
        "--auth-json",
        str(auth),
    ]


def test_matrix_selects_the_public_typed_input_profile_and_exact_units(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda value: Path(value))
    options = matrix.parse_args(
        [
            "--profile",
            PROFILE_ID,
            "--case-id",
            "TYP21-ZERO-GET-INFO",
            "--version",
            "2021.1",
            *_dependencies(tmp_path),
        ]
    )

    assert options.profile == PROFILE_ID
    assert options.suite_path == matrix.DEFAULT_TYPED_INPUT_SUITE.resolve()
    assert options.iteration_root == matrix.DEFAULT_TYPED_INPUT_ITERATION_ROOT.resolve()
    assert (options.model, options.reasoning_effort, options.service_tier) == (
        "gpt-5.6-terra",
        "medium",
        "default",
    )
    units = matrix.load_heavy_v3_units(options)
    assert [(unit.unit_id, unit.version) for unit in units] == [
        ("TYP21-ZERO-GET-INFO", "2021.1")
    ]


def test_typed_input_profile_rejects_offline_pair_and_model_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda value: Path(value))
    dependencies = _dependencies(tmp_path)
    for forbidden in (
        ["--offline-only"],
        ["--pair-id", "pair-1"],
        ["--model", "gpt-5.6-sol"],
        ["--reasoning-effort", "high"],
        ["--service-tier", "priority"],
    ):
        with pytest.raises(SystemExit):
            matrix.parse_args(
                ["--profile", PROFILE_ID, *forbidden, *dependencies]
            )


def test_campaign_uses_same_profile_and_disables_same_root_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda value: Path(value))
    options = campaign.parse_args(
        [
            "--profile",
            PROFILE_ID,
            "--campaign-root",
            str(tmp_path / "campaign"),
            *_dependencies(tmp_path),
        ]
    )

    assert options.profile == PROFILE_ID
    assert options.suite_path == matrix.DEFAULT_TYPED_INPUT_SUITE.resolve()
    assert options.max_pre_action_retries == 0
    assert (options.model, options.reasoning_effort, options.service_tier) == (
        "gpt-5.6-terra",
        "medium",
        "default",
    )

    selected = campaign.parse_args(
        [
            "--profile",
            PROFILE_ID,
            "--campaign-root",
            str(tmp_path / "selected-campaign"),
            "--case-id",
            "TYP22-GENERIC-OBJECT-QUERY",
            *_dependencies(tmp_path),
        ]
    )
    assert selected.case_ids == ("TYP22-GENERIC-OBJECT-QUERY",)

    with pytest.raises(SystemExit):
        campaign.parse_args(
            [
                "--profile",
                PROFILE_ID,
                "--campaign-root",
                str(tmp_path / "bad-campaign"),
                "--max-pre-action-retries",
                "1",
                *_dependencies(tmp_path),
            ]
        )
    with pytest.raises(SystemExit):
        campaign.parse_args(
            [
                "--profile",
                PROFILE_ID,
                "--campaign-root",
                str(tmp_path / "bad-pair-campaign"),
                "--pair-id",
                "TYP22-GENERIC-OBJECT-QUERY",
                *_dependencies(tmp_path),
            ]
        )


def test_typed_input_matrix_rejects_reused_agent_thread_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda value: Path(value))
    monkeypatch.setattr(
        matrix,
        "prepare_iteration_root",
        lambda path, *, overwrite: path.mkdir(parents=True, exist_ok=False),
    )
    options = matrix.parse_args(
        [
            "--profile",
            PROFILE_ID,
            "--iteration-root",
            str(tmp_path / "matrix"),
            *_dependencies(tmp_path),
        ]
    )
    units = matrix.load_heavy_v3_units(options)[:2]

    def run(unit, **_kwargs):
        payload = {
            "contract": "synthetic-typed-input-outcome/v1",
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "status": "PASS",
            "reason": "",
            "scenario_root": "synthetic",
            "task_root": "synthetic",
            "thread_id": "reused-thread",
            "checks": {},
            "lifecycle": {},
        }
        return SimpleNamespace(
            scenario_id=unit.unit_id,
            version=unit.version,
            status="PASS",
            reason="",
            passed=True,
            thread_id="reused-thread",
            as_dict=lambda: payload,
        )

    result = matrix.run_heavy_v3_matrix(
        options,
        unit_loader=lambda _options: units,
        unit_runner=run,
        dependency_preflight=lambda: {"ok": True},
    )

    assert result == 1
    summary = json.loads(
        (options.iteration_root / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["passed_unit_ids"] == [units[0].unit_id]
    assert summary["blocked_unit_ids"] == [units[1].unit_id]
    assert "reused a prior task thread identity" in "\n".join(
        summary["run_errors"]
    )


def test_typed_input_campaign_freezes_retryable_units_in_the_same_root() -> None:
    consolidated = {
        "blocked_unit_ids": [],
        "pending_unit_ids": [],
        "retryable_unit_ids": ["TYP21-ZERO-GET-INFO"],
        "failed_unit_ids": [],
        "all_selected_passed": False,
    }

    assert campaign.heavy_v3_consolidated_exit(consolidated) is None
    assert campaign.heavy_v3_consolidated_exit(
        consolidated,
        freeze_retryable=True,
    ) == campaign.EXIT_PENDING


def test_campaign_reader_independently_accepts_exact_direct_plan() -> None:
    protocol = build_direct_protocol(
        (
            ExpectedGatewayStep(
                "host.status",
                "status",
            ),
            ExpectedGatewayStep(
                "host.get-info.schema",
                "request-schema",
                ("ak.wwise.core.getInfo",),
            ),
            ExpectedGatewayStep(
                "host.get-info",
                "typed-zero-call",
                ("ak.wwise.core.getInfo",),
            ),
        )
    )
    bindings = {
        "version": "2021.1",
        "build": "2021.1.8100.0",
        "process_id": 42,
        "launch_process_id": 41,
        "session_id": "session",
        "result_sha256": "a" * 64,
        "project_digest": "b" * 64,
        "status": {
            "wwise_build": "2021.1.8100.0",
            "process_id": 42,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "type": "Project",
                "path": "\\",
            },
        },
    }
    sections = compile_direct_business_plan(
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        protocol_steps=tuple(
            {"name": step.name, "subcommand": step.subcommand}
            for step in protocol.steps
        ),
        live_bindings=bindings,
        verification_boundary="exact_host_identity",
    )
    plan = sections.writer_kwargs()
    unit = SimpleNamespace(
        base_scenario_id="O22-GET-INFO-01",
        version="2021.1",
        scenario=SimpleNamespace(api="ak.wwise.core.getInfo"),
    )

    assert campaign._heavy_v3_business_plan_fixture_spec(
        plan,
        expected_unit=unit,
    ) == dict(sections.fixture_spec)
    assert campaign._validate_heavy_v3_typed_business_plan(
        plan,
        expected_unit=unit,
        provenance=SimpleNamespace(protocol=protocol),
    ).writer_kwargs() == sections.writer_kwargs()


@pytest.mark.parametrize(
    ("api", "verification_boundary", "verification", "label"),
    (
        (
            "ak.wwise.core.getInfo",
            "exact_host_identity",
            {
                "passed": True,
                "failures": [],
                "evidence": {
                    "expected_build": "2021.1.8100.0",
                    "expected_process_id": 42,
                    "expected_result_sha256": "a" * 64,
                    "actual_result_sha256": "a" * 64,
                },
            },
            "direct business oracle",
        ),
        (
            "ak.wwise.core.executeLuaScript",
            "result_schema_only",
            {
                "passed": True,
                "failures": [],
                "evidence": {
                    "expected_return": {"profile": "typed_input", "count": 3},
                    "actual_return": {"profile": "typed_input", "count": 3},
                    "business_state_verified": False,
                    "script_sha256": "c" * 64,
                },
            },
            "direct business oracle",
        ),
        (
            "ak.wwise.core.executeLuaScript",
            "result_schema_only",
            {
                "passed": True,
                "failures": [],
                "evidence": {"turn_index": 2, "weak_boundary_reported": True},
            },
            "direct weak-verifier UX oracle",
        ),
    ),
)
def test_full_archive_dispatcher_terminates_after_direct_typed_validation(
    api: str,
    verification_boundary: str,
    verification: dict,
    label: str,
    tmp_path: Path,
) -> None:
    scenario_id = "O22-GET-INFO-01" if api.endswith("getInfo") else "LUA23-CORE-FILE-02"
    version = "2021.1" if api.endswith("getInfo") else "2025.1"
    steps = (
        (
            {"name": "host.status", "subcommand": "status"},
            {"name": "host.get-info.schema", "subcommand": "request-schema"},
            {"name": "host.get-info", "subcommand": "typed-zero-call"},
        )
        if api.endswith("getInfo")
        else ({"name": "direct.execute", "subcommand": "typed-zero-call"},)
    )
    bindings = (
        {
            "version": version,
            "build": "2021.1.8100.0",
            "process_id": 42,
            "launch_process_id": 41,
            "session_id": "session",
            "result_sha256": "a" * 64,
            "project_digest": "b" * 64,
            "status": {
                "wwise_build": "2021.1.8100.0",
                "process_id": 42,
                "project": {
                    "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                    "name": "SampleProject",
                    "type": "Project",
                    "path": "\\",
                },
            },
        }
        if api.endswith("getInfo")
        else {
            "version": version,
            "script_file": "/owned/user.lua",
            "script_sha256": "c" * 64,
            "dispatch": {"uri": api, "args": {}, "options": {}},
            "project_digest": "d" * 64,
            "expected_return": {"profile": "typed_input", "count": 3},
        }
    )
    sections = compile_direct_business_plan(
        scenario_id=scenario_id,
        api=api,
        protocol_steps=steps,
        live_bindings=bindings,
        verification_boundary=verification_boundary,
    )
    plan_sha = "e" * 64
    prompt_evidence = SimpleNamespace(
        typed_sections=sections,
        business_oracle_plan=SimpleNamespace(sha256=plan_sha),
    )
    envelope = {
        "contract": campaign.HEAVY_V3_ORACLE_CONTRACT,
        "scenario_id": scenario_id,
        "version": version,
        "api": api,
        "runner": "project",
        "business_oracle_plan_sha256": plan_sha,
        "verification": verification,
    }
    task_root = tmp_path / "codex-task"
    task_root.mkdir()
    if api.endswith("getInfo"):
        sandbox_project = tmp_path / "SampleProject.wproj"
        sandbox_project.write_text("<Project/>\n", encoding="utf-8")
        (tmp_path / "start.json").write_text(
            json.dumps({"sandbox_project": str(sandbox_project)}),
            encoding="utf-8",
        )
        (task_root / "task-result.json").write_text(
            json.dumps(
                {
                    "broker": {
                        "records": [
                            {
                                "step_name": "host.status",
                                "payload": {
                                    "wwise": {
                                        "processId": 42,
                                        "version": {
                                            "year": 2021,
                                            "major": 1,
                                            "minor": 8100,
                                            "build": 0,
                                        },
                                    },
                                    "project": {
                                        "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                                        "name": "SampleProject",
                                        "type": "Project",
                                        "path": "\\",
                                    },
                                },
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    campaign._validate_heavy_v3_archived_verification(
        envelope,
        api=api,
        scenario_id=scenario_id,
        version=version,
        runner="project",
        primary_count=1,
        task_root=task_root,
        prompt_evidence=prompt_evidence,
        scenario_fixture={},
        label=label,
    )

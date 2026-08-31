from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_audio_import_composer_transaction_steps,
)
from tests.semantic.support.codex_import_business_profile import (
    ImportBusinessUnit,
    UNIT_IDS,
    load_import_business_profile,
)
from tests.semantic.support.codex_import_business_agent_runner import (
    _business_protocol_is_exact,
    _final_response_reports_preview,
    build_preview_only_business_steps,
    prepare_import_business_runtime,
)
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol
from tests.semantic.support.codex_gateway_broker import (
    DraftTypedActionArgument,
    DraftTypedActionBatchArgument,
    ExpectedGatewayStep,
)
from tests.semantic.support.typed_gateway_input import (
    _container_action,
    _require_disclosed_continuation,
    _require_nested_container_disclosure,
    _render_step_arguments,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "tests/semantic/data/audio-import-business/profile.json"


def test_real_gateway_adapter_follows_business_schema_start() -> None:
    _require_disclosed_continuation(
        ExpectedGatewayStep(
            name="tx01.operation-schema",
            subcommand="operation-schema",
            arguments=("audio.import",),
        ),
        {
            "business_adapter": {
                "start": {
                    "next_command": {
                        "gateway_argv": ["draft-start", "audio.import"]
                    }
                }
            }
        },
        ["draft-start", "audio.import"],
        pending_container_actions=[],
    )


def test_real_gateway_adapter_follows_business_copy_bindings() -> None:
    draft_id = "od1-" + "1" * 32
    authority = "da1-" + "2" * 40

    def binding(subcommand: str, revision: int) -> list[str]:
        return [
            "python",
            "/task/skill/scripts/run.py",
            "gateway.py",
            subcommand,
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
        ]

    bind_prefix = binding("draft-bind-object", 1)
    _require_disclosed_continuation(
        ExpectedGatewayStep(
            name="tx01.draft-start",
            subcommand="draft-start",
            arguments=("audio.import",),
        ),
        {
            "draft": {
                "next_action_binding": {
                    "contract": "waapi-skill.business-draft-next-action/v1",
                    "object_binding": {
                        "by_path_segments": {
                            "fixed_argv_prefix": bind_prefix,
                            "append_repeated": [
                                "--object-path-segment",
                                "<one-segment>",
                            ],
                        }
                    }
                }
            }
        },
        [
            *bind_prefix[3:],
            "--object-path-segment",
            "Actor-Mixer Hierarchy",
            "--object-path-segment",
            "Default Work Unit",
        ],
        pending_container_actions=[],
    )
    declare_prefix = binding("draft-declare-new", 2)
    _require_disclosed_continuation(
        ExpectedGatewayStep(
            name="tx01.bind-object.001",
            subcommand="draft-bind-object",
            arguments=(),
        ),
        {
            "draft": {
                "next_action_binding": {
                    "contract": "waapi-skill.business-draft-next-action/v1",
                    "declare_new": {
                        "fixed_argv_prefix": declare_prefix,
                        "append": [
                            "--declaration-id",
                            "<task-local-id>",
                            "--parent-handle",
                            "<bound-handle>",
                            "--name",
                            "<name>",
                            "--kind",
                            "<kind>",
                            "[--field <name> <value>]...",
                        ],
                    }
                }
            }
        },
        [
            *declare_prefix[3:],
            "--declaration-id",
            "rain",
            "--parent-handle",
            "boh1-" + "3" * 32,
            "--name",
            "Rain",
            "--kind",
            "sound-sfx",
            "--field",
            "volume_db",
            "-4",
        ],
        pending_container_actions=[],
    )


def test_real_gateway_adapter_renders_atomic_draft_action_batches() -> None:
    actions = tuple(
        DraftTypedActionArgument(
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                "action": "set_import_option",
                "name": "import_operation",
                "value": value,
            },
            operation="audio.import",
        )
        for value in ("createNew", "useExisting")
    )
    step = ExpectedGatewayStep(
        name="tx01.action.001",
        subcommand="draft-apply",
        arguments=(DraftTypedActionBatchArgument(actions),),
    )

    rendered = _render_step_arguments(step, {})

    assert rendered == [
        "--action",
        "set_import_option",
        "--option",
        "import_operation",
        "string",
        "createNew",
        "--action",
        "set_import_option",
        "--option",
        "import_operation",
        "string",
        "useExisting",
    ]


def test_real_gateway_adapter_allows_branch_first_container_disclosure() -> None:
    assert _container_action(
        {
            "continuation": {
                "next_command_decision": {
                    "evaluate_in_order": [
                        "branch_disclosure",
                        "deferred_fact_queue",
                    ]
                }
            }
        }
    ) is None


def test_real_gateway_adapter_follows_exact_nested_container_disclosure() -> None:
    command = [
        "request-map-container",
        "soundbank.setInclusions",
        "--map-handle",
        "trm1-child",
        "--key",
        "object",
        "--shape",
        "object",
        "--parent-schema-token",
        "lineage-token",
    ]

    template = list(command)
    template[template.index("object")] = "<exact-key>"
    template[-1] = "<selected-choice-handle-from-child_contract>"
    payload = {
        "child_contract": {
            "branch_choices": [{"choices": [{"handle": "lineage-token"}]}]
        },
        "draft": {
            "next_action_binding": {
                "resume_previous_container_response": {
                    "next_command_decision": {
                        "branch_disclosure": {"argv_by_shape": {"object": template}}
                    }
                }
            }
        },
    }

    _require_nested_container_disclosure(payload, command)


def test_production_audio_import_profile_has_four_independent_business_pairs() -> None:
    profile = load_import_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    assert len({unit.scenario.id for unit in profile.units}) == 8
    assert [unit.family for unit in profile.units] == [
        "weather", "weather", "rifle", "rifle",
        "footsteps", "footsteps", "weapons", "weapons",
    ]
    assert all(unit.scenario.api == "ak.wwise.core.audio.import" for unit in profile.units)


def test_every_profile_transaction_compiles_to_the_production_business_draft() -> None:
    profile = load_import_business_profile(PROFILE)

    for unit in profile.units[::2]:
        for index, transaction in enumerate(unit.transactions, start=1):
            request = {
                "contract": "waapi-skill.operation-request/v1",
                "version": unit.version,
                "operation": "audio.import",
                "arguments": transaction["arguments"],
            }
            steps = build_audio_import_composer_transaction_steps(
                request,
                label=f"tx{index:02d}",
            )
            subcommands = tuple(step.subcommand for step in steps)
            assert "draft-start" in subcommands
            assert "draft-declare-import-batch" in subcommands
            assert "draft-check" in subcommands
            assert "preview-from-draft" in subcommands
            assert "draft-apply" not in subcommands
            preview = next(
                step
                for step in steps
                if step.subcommand == "preview-from-draft"
            )
            assert "--apply" not in preview.arguments


def test_protocol_accepts_the_normal_wwise_actor_mixer_path_token() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit"
                        r"\<Actor-Mixer>Weather"
                    ),
                    "object_type": "ActorMixer",
                }
            ]
        },
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")

    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )
    assert "actor-mixer" in declaration.arguments


def test_implicit_create_uses_the_planned_parent_instead_of_live_binding_it() -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-WEATHER-A",),
    ).units[0]
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": "audio.import",
        "arguments": unit.transactions[0]["arguments"],
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")

    bound_paths = {
        step.arguments[-1]
        for step in steps
        if step.subcommand == "draft-bind-object"
        and step.arguments[-2] == "--object-path"
    }
    assert (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
        r"\BusinessImportRoot\<Actor-Mixer>Weather"
    ) not in bound_paths
    assert all(
        step.subcommand != "draft-business-configure" for step in steps
    )
    batch = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )
    assert "sound-sfx" in batch.arguments
    assert "--new-row" in batch.arguments
    assert "--new-root-row" not in batch.arguments
    assert "--new-child-row" not in batch.arguments
    assert "language" not in batch.arguments


def test_existing_target_derives_reimport_while_replace_remains_explicit() -> None:
    profile = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-RIFLE-A", "AIB22-RIFLE-B"),
    )

    steps_by_unit = {}
    for unit in profile.units:
        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": unit.version,
            "operation": "audio.import",
            "arguments": unit.transactions[0]["arguments"],
        }
        steps_by_unit[unit.unit_id] = build_audio_import_composer_transaction_steps(
            request,
            label="tx01",
        )

    assert all(
        step.subcommand != "draft-business-configure"
        for step in steps_by_unit["AIB22-RIFLE-A"]
    )
    replace = next(
        step
        for step in steps_by_unit["AIB22-RIFLE-B"]
        if step.subcommand == "draft-business-configure"
    )
    assert replace.arguments[-2:] == ("--mode", "replace")


def test_use_existing_protocol_binds_live_rows_and_declares_missing_rows() -> None:
    parent = (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
        r"\<Virtual Folder>Weapons\<Random Container>Rifle"
    )
    existing = parent + r"\<Sound SFX>Rifle_Close"
    missing = parent + r"\<Sound SFX>Rifle_Tail"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2021.1",
        "operation": "audio.import",
        "arguments": {
            "import_operation": "useExisting",
            "imports": [
                {
                    "audio_file": "/tmp/rifle-close.wav",
                    "object_path": existing,
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                },
                {
                    "audio_file": "/tmp/rifle-tail.wav",
                    "object_path": missing,
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                },
            ],
        },
    }

    steps = build_audio_import_composer_transaction_steps(
        request,
        label="tx01",
        existing_target_paths=frozenset(
            {
                re.sub(r"(?<=\\)<[^<>\\]+>", "", existing),
            }
        ),
    )
    bindings = [
        step for step in steps if step.subcommand == "draft-bind-object"
    ]
    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )

    assert len(bindings) == 2
    assert bindings[0].arguments[-2:] == (
        "--object-path-segment",
        "<Sound SFX>Rifle_Close",
    )
    assert bindings[1].arguments[-2:] == (
        "--object-path-segment",
        "<Random Container>Rifle",
    )
    assert "--existing-row" in declaration.arguments
    assert "--new-row" in declaration.arguments


def test_profile_filters_preserve_independent_unit_identity() -> None:
    selected = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-WEATHER-B", "AIB25-WEAPONS-A"),
    )

    assert tuple(unit.unit_id for unit in selected.units) == (
        "AIB22-WEATHER-B",
        "AIB25-WEAPONS-A",
    )


def test_final_preview_report_accepts_typographic_minus_without_fixed_wording() -> None:
    assert _final_response_reports_preview(
        "预览已生成：Rain_Bed −4 dB；Wind_Bed −6 dB。",
        markers=("Rain_Bed", "Wind_Bed", "-4", "-6"),
    )


def test_final_preview_report_does_not_require_fixed_synonym_markers() -> None:
    assert _final_response_reports_preview(
        "已完成安全重导入预览：Rifle 保持对象身份；未执行项目修改。",
        markers=("Rifle", "保留"),
    )


def test_final_preview_report_accepts_exact_machine_result() -> None:
    payload = {
        "operation": "audio.import",
        "state": "awaiting_confirmation",
        "executed": False,
        "request": {
            "contract": "waapi-skill.operation-request/v1",
            "operation": "audio.import",
            "arguments": {"import_operation": "replaceExisting"},
        },
    }
    assert _final_response_reports_preview(
        json.dumps(payload),
        markers=("Rifle", "替换"),
    )
    payload["executed"] = True
    assert not _final_response_reports_preview(
        json.dumps(payload),
        markers=("Rifle", "替换"),
    )


def test_runtime_resolves_media_and_stops_every_transaction_at_preview(tmp_path: Path) -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-RIFLE-A",),
    ).units[0]

    runtime = prepare_import_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_business_steps(runtime.requests)

    assert len(runtime.requests) == 1
    assert all(path.is_file() for path in runtime.media_paths)
    assert "media://" not in runtime.prompt
    assert sum(step.subcommand == "preview-from-draft" for step in steps) == 1
    object_bindings = [
        step for step in steps if step.subcommand == "draft-bind-object"
    ]
    assert object_bindings
    assert all("--object-path-segment" in step.arguments for step in object_bindings)
    assert all("--object-path" not in step.arguments for step in object_bindings)
    assert all("--object-name" not in step.arguments for step in object_bindings)
    assert all(step.subcommand not in {"confirm", "execute", "verify"} for step in steps)


def test_rifle_modes_are_isolated_into_one_preview_per_fresh_unit() -> None:
    units = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-RIFLE-A", "AIB22-RIFLE-B"),
    ).units

    assert [unit.transaction_count for unit in units] == [1, 1]
    assert [
        unit.transactions[0]["arguments"]["import_operation"]
        for unit in units
    ] == ["useExisting", "replaceExisting"]
    assert [unit.final_markers for unit in units] == [
        ("Rifle", "保留"),
        ("Rifle", "替换"),
    ]


def test_agent_outcome_accepts_broker_proven_commutative_binding_order() -> None:
    evidence = SimpleNamespace(
        passed=True,
        expected_step_names=("bind-field.001", "bind-object.002"),
        consumed_step_names=("bind-object.002", "bind-field.001"),
    )

    assert _business_protocol_is_exact(
        evidence,
        SimpleNamespace(passed=True),
    )


def test_matrix_wires_the_profile_to_the_packaged_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    codex.write_text("fixture", encoding="utf-8")
    auth.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda _value: codex)

    options = matrix.parse_args(
        [
            "--profile",
            "audio_import_business_8",
            "--case-id",
            "AIB25-WEAPONS-B",
            "--auth-json",
            str(auth),
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
        ]
    )

    assert options.suite_path == PROFILE
    assert options.skill_source == matrix.SKILL_ROOT
    assert options.iteration_root.name == "audio-import-business-8"
    assert [unit.unit_id for unit in matrix.load_heavy_v3_units(options)] == [
        "AIB25-WEAPONS-B"
    ]


def test_campaign_wires_the_same_suite_and_forbids_same_root_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    for path, content in ((codex, "fixture"), (auth, "{}"), (live, "{}")):
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda _value: codex)

    options = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--profile",
            "audio_import_business_8",
            "--auth-json",
            str(auth),
            "--live-config",
            str(live),
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
        ]
    )

    assert options.suite_path == PROFILE
    assert options.max_pre_action_retries == 0


def test_campaign_uses_the_agent_lane_and_closed_offline_preflight(tmp_path: Path) -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-WEATHER-A",),
    ).units[0]
    matrix_row = matrix._heavy_v3_unit_row(unit, sequence=1)
    campaign_row = campaign.heavy_v3_unit_row(unit, sequence=1)
    assert matrix_row == campaign_row
    assert matrix_row["runner"] == "agent"
    assert unit.user_turn_count == 1
    assert unit.transaction_count == 1
    assert len(unit.scenario.prompt_sha256) == 64

    (tmp_path / "live-preflight.json").write_text(
        json.dumps(
            {
                "contract": "waapi-skill.audio-import-business-preflight/v1",
                "ok": True,
                "mode": "offline-production-gateway",
                "wwise_started": False,
                "production_gateway": True,
            }
        ),
        encoding="utf-8",
    )
    campaign._validate_heavy_v3_live_preflight(
        tmp_path,
        summary={"preflight": "passed"},
        expected_profile="audio_import_business_8",
    )


def _write_synthetic_agent_evidence(
    scenario_root: Path,
    unit: ImportBusinessUnit,
    *,
    thread_id: str,
) -> tuple[dict[str, object], tuple[object, ...]]:
    evidence = scenario_root / "evidence"
    evidence.mkdir(parents=True)
    runtime = prepare_import_business_runtime(
        unit,
        evidence / "codex-task" / "runtime",
    )
    steps = build_preview_only_business_steps(runtime.requests)
    serialized_steps = {
        step["name"]: step
        for step in serialize_protocol(
            V3GatewayProtocol(steps=steps, turn_prefix_counts=(len(steps),))
        )["steps"]
    }
    records = []
    explicit_sfx_added = False
    for step in steps:
        gateway_arguments = [step.subcommand]
        if step.allow_explicit_derived_sfx_language and not explicit_sfx_added:
            gateway_arguments.extend(("--field", "language", "SFX"))
            explicit_sfx_added = True
        payload = (
            {
                "agent_result": {
                    "request": campaign._bind_audio_import_request_paths(
                        serialized_steps[step.name][
                            "expected_operation_request"
                        ]["value"],
                        objects=unit.objects,
                    )
                }
            }
            if step.subcommand == "preview-from-draft"
            else {}
        )
        records.append(
            {
                "step_name": step.name,
                "gateway_arguments": gateway_arguments,
                "accepted": True,
                "authenticated": True,
                "succeeded": True,
                "exit_code": 0,
                "payload": payload,
            }
        )
    expected_names = [step.name for step in steps]
    outcome = {
        "contract": "waapi-skill.audio-import-business-agent-outcome/v1",
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "status": "PASS",
        "reason": "",
        "thread_id": thread_id,
        "gates": {"broker_passed": True, "exact_protocol": True},
        "command_count": len(steps),
        "transaction_count": unit.transaction_count,
        "production_gateway": True,
        "wwise_started": False,
        "final_response": "预览完成",
    }
    for path, payload in (
        (evidence / "outcome.json", outcome),
        (scenario_root / "outcome.json", outcome),
        (evidence / "broker-reconciliation.json", {"passed": True}),
        (
            evidence / "broker-evidence.json",
            {
                "passed": True,
                "complete": True,
                "expected_step_names": expected_names,
                "consumed_step_names": expected_names,
                "records": records,
            },
        ),
        (evidence / "codex-result-facts.json", {}),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")
    return outcome, steps


def test_campaign_validates_the_profile_specific_agent_outcome(tmp_path: Path) -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB25-WEAPONS-A",),
    ).units[0]
    outcome, _steps = _write_synthetic_agent_evidence(
        tmp_path,
        unit,
        thread_id="thread-fixture",
    )

    campaign._validate_audio_import_business_agent_outcome(
        outcome,
        matrix_case={
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "status": "PASS",
            "reason": "",
        },
        expected_unit=unit,
        scenario_root=tmp_path,
            options=SimpleNamespace(
                profile=campaign.AUDIO_IMPORT_BUSINESS_PROFILE_ID,
                protocol_manifest_revision=(
                    campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
                )
            ),
    )


def test_campaign_child_validator_consumes_reviewed_agent_protocol_revision(
    tmp_path: Path,
) -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB25-WEAPONS-A",),
    ).units[0]
    matrix_root = tmp_path / "matrix"
    scenario_root = matrix_root / "scenarios" / f"001-{unit.unit_id}"
    outcome, steps = _write_synthetic_agent_evidence(
        scenario_root,
        unit,
        thread_id="thread-agent-child",
    )

    row = campaign.heavy_v3_unit_row(unit, sequence=1)
    matrix_case = {
        "contract": matrix.HEAVY_V3_CASE_RECORD_CONTRACT,
        **row,
        "status": "PASS",
        "reason": "",
        "scenario_root": str(scenario_root.resolve()),
        "runner_outcome": outcome,
    }
    matrix.write_json(scenario_root / "matrix-case.json", matrix_case)
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live.json"
    for path, content in ((codex, "codex"), (auth, "{}"), (live, "{}")):
        path.write_text(content, encoding="utf-8")
    options = campaign.CampaignOptions(
        campaign_root=tmp_path / "campaign",
        resume=True,
        verify_only=True,
        profile=matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID,
        suite_path=PROFILE,
        skill_source=REPO_ROOT / "skills/waapi-skill",
        codex_binary=codex,
        auth_json=auth,
        live_config=live,
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=240.0,
        case_ids=(unit.unit_id,),
        versions=(),
        pair_ids=(),
        offline_only=False,
        lock_timeout_seconds=1.0,
        max_pre_action_retries=0,
        protocol_manifest_revision=(
            campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
        ),
    )
    runner_options = matrix.RunnerOptions(
        profile=options.profile,
        iteration_root=matrix_root,
        suite_path=options.suite_path,
        skill_source=options.skill_source,
        codex_binary=options.codex_binary,
        auth_json=options.auth_json,
        live_config=options.live_config,
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier,
        timeout_seconds=options.timeout_seconds,
        case_ids=options.case_ids,
        versions=(),
        pair_ids=(),
        offline_only=False,
        overwrite=False,
    )
    started = "2026-08-25T00:00:00Z"
    completed = "2026-08-25T00:01:00Z"
    run_config = matrix._heavy_v3_run_config(
        runner_options,
        unit_rows=(row,),
        records=(matrix_case,),
        run_errors=(),
        stop_reason="",
        preflight_state="passed",
        started_at=started,
        completed_at=completed,
    )
    summary = matrix._heavy_v3_summary(
        unit_rows=(row,),
        records=(matrix_case,),
        run_errors=(),
        stop_reason="",
        preflight_state="passed",
        started_at=started,
        completed_at=completed,
        profile=options.profile,
    )
    matrix.write_json(matrix_root / "run-config.json", run_config)
    matrix.write_json(matrix_root / "summary.json", summary)
    matrix.write_json(
        matrix_root / "live-preflight.json",
        {
            "contract": "waapi-skill.audio-import-business-preflight/v1",
            "ok": True,
            "mode": "offline-production-gateway",
            "wwise_started": False,
            "production_gateway": True,
        },
    )

    result = campaign.validate_heavy_v3_child_run(
        matrix_root,
        expected_units=(unit,),
        options=options,
        returncode=0,
    )

    assert result.observations[0]["status"] == "PASS"
    rejected = campaign.validate_heavy_v3_child_run(
        matrix_root,
        expected_units=(unit,),
        options=replace(
            options,
            protocol_manifest_revision="unreviewed-revision",
        ),
        returncode=0,
    )
    assert rejected.observations[0]["status"] == "BLOCKED"
    assert "audio import business protocol revision is unreviewed" in (
        rejected.phase_verdicts[0].reason
    )
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="historical harness hash is unreviewed",
    ):
        campaign._sealed_protocol_manifest_revision(
            {
                "selection": {
                    "profile": matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID
                },
                "harness": {"semantic_tree_sha256": "0" * 64},
            }
        )

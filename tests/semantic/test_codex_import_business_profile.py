from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_audio_import_composer_transaction_steps,
)
from tests.semantic.support.codex_import_business_profile import (
    UNIT_IDS,
    load_import_business_profile,
)
from tests.semantic.support.codex_import_business_agent_runner import (
    _business_protocol_is_exact,
    _final_response_reports_preview,
    build_preview_only_business_steps,
    prepare_import_business_runtime,
)
from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep
from tests.destructive.support.typed_gateway_input import (
    _require_disclosed_continuation,
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
                "start": {"gateway_argv": ["draft-start", "audio.import"]}
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
            assert "draft-declare-new" in subcommands or "draft-declare-existing" in subcommands
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
        step for step in steps if step.subcommand == "draft-declare-new"
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
    sound_declarations = [
        step
        for step in steps
        if step.subcommand == "draft-declare-new"
        and "sound-sfx" in step.arguments
    ]
    assert sound_declarations
    assert all("language" not in step.arguments for step in sound_declarations)


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


def test_campaign_validates_the_profile_specific_agent_outcome(tmp_path: Path) -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB25-WEAPONS-A",),
    ).units[0]
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outcome = {
        "contract": "waapi-skill.audio-import-business-agent-outcome/v1",
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "status": "PASS",
        "reason": "",
        "thread_id": "thread-fixture",
        "gates": {"broker_passed": True, "exact_protocol": True},
        "command_count": 11,
        "transaction_count": unit.transaction_count,
        "production_gateway": True,
        "wwise_started": False,
        "final_response": "预览完成",
    }
    for name, payload in (
        ("outcome.json", outcome),
        ("broker-reconciliation.json", {"passed": True}),
        ("broker-evidence.json", {"complete": True}),
        ("codex-result-facts.json", {}),
    ):
        (evidence / name).write_text(json.dumps(payload), encoding="utf-8")

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
    )

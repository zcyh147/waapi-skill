from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3ProtocolError,
    build_modification_policy_protocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    ResponseBinding,
    SemanticJsonArgument,
)
from tests.semantic.support.codex_modification_policy_v3 import (
    APPROVAL_POLICY,
    CODEX_CLI_INVOCATION_COUNT,
    MODEL,
    POLICY_MODES,
    PROFILE_ID,
    READ_ONLY_FOLLOW_UP_PROMPT,
    REASONING_EFFORT,
    SERVICE_TIER,
    TASK_COUNT,
    ModificationPolicyProfileError,
    load_modification_policy_profile,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    build_object_heavy_v3_recipe,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    deserialize_protocol,
    serialize_protocol,
    write_prompt_provenance,
)


PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "evals"
    / "modification-policy-9.json"
)


def _profile():
    return load_modification_policy_profile(PROFILE_PATH)


def _base_protocol():
    recipe = build_object_heavy_v3_recipe("OBJ22-F-CREATE-01")
    return build_transaction_protocol([recipe.request.as_dict()])


def _path_args(tmp_path: Path) -> list[str]:
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live.json"
    for path in (codex, auth, live):
        path.write_text("{}\n", encoding="utf-8")
    codex.chmod(0o755)
    return [
        "--codex-binary",
        str(codex),
        "--auth-json",
        str(auth),
        "--live-config",
        str(live),
    ]


def _policy_result(events: list[dict[str, object]]) -> SimpleNamespace:
    preview = "gateway preview --apply --request-json request"
    execute = "gateway execute tx"
    return SimpleNamespace(
        stdout="\n".join(
            json.dumps(event, ensure_ascii=False) for event in events
        )
        + "\n",
        command_facts=SimpleNamespace(
            gateway_attempt_commands=(preview, execute),
            gateway_subcommands=("preview", "execute"),
        ),
    )


def _agent(text: str) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": text},
    }


def _command(command: str, *, completed: bool = True) -> dict[str, object]:
    return {
        "type": "item.completed" if completed else "item.started",
        "item": {"type": "command_execution", "command": command},
    }


def test_profile_is_exactly_three_modes_by_three_repetitions_and_fifteen_turns() -> None:
    profile = _profile()

    assert PROFILE_ID == "modification_policy_9"
    assert len(profile.units) == TASK_COUNT == 9
    assert sum(unit.user_turn_count for unit in profile.units) == (
        CODEX_CLI_INVOCATION_COUNT
    ) == 15
    assert tuple(mode.id for mode in profile.modes) == POLICY_MODES
    assert [unit.unit_id for unit in profile.units] == [
        f"POL22-CREATE-{label}-R{repetition}"
        for label in ("READ-ONLY", "ASK-BEFORE", "ALLOW-CHANGES")
        for repetition in (1, 2, 3)
    ]
    assert {
        (unit.policy_mode, unit.repetition)
        for unit in profile.units
    } == {
        (mode, repetition)
        for mode in POLICY_MODES
        for repetition in (1, 2, 3)
    }


def test_profile_turns_are_natural_and_reuse_the_reviewed_business_request() -> None:
    profile = _profile()

    assert all(unit.turns[0].prompt == profile.scenario.prompt for unit in profile.units)
    for unit in profile.units:
        assert all(turn.kind in {"request", "confirmation"} for turn in unit.turns)
        for turn in unit.turns:
            folded = turn.prompt.casefold()
            assert "必须遵守" not in turn.prompt
            assert "skill 的边界" not in folded
            assert "harness" not in folded
            assert "测试用例" not in turn.prompt
    read_units = [unit for unit in profile.units if unit.policy_mode == "read_only"]
    assert all(unit.turns[1].prompt == READ_ONLY_FOLLOW_UP_PROMPT for unit in read_units)


def test_profile_filters_preserve_unique_unit_identity_and_fail_closed() -> None:
    selected = load_modification_policy_profile(
        PROFILE_PATH,
        unit_ids=("POL22-CREATE-ALLOW-CHANGES-R2",),
        versions=("2022.1",),
    )
    assert [unit.unit_id for unit in selected.units] == [
        "POL22-CREATE-ALLOW-CHANGES-R2"
    ]

    with pytest.raises(ModificationPolicyProfileError, match="unknown"):
        load_modification_policy_profile(PROFILE_PATH, unit_ids=("UNKNOWN",))
    with pytest.raises(ModificationPolicyProfileError, match="only Wwise 2022.1"):
        load_modification_policy_profile(PROFILE_PATH, versions=("2023.1",))


def test_policy_protocols_have_exact_apply_and_turn_topologies() -> None:
    base = _base_protocol()
    read_only = build_modification_policy_protocol(base, policy="read_only")
    ask = build_modification_policy_protocol(base, policy="ask_before_changes")
    allow = build_modification_policy_protocol(base, policy="allow_changes")

    assert tuple(step.subcommand for step in read_only.steps) == (
        "operation-schema",
    )
    assert read_only.turn_prefix_counts == (1, 1)
    assert read_only.allowed_turn_prefix_counts == ((1,), (1,))
    assert read_only.accepted_terminal_prefixes == (1,)

    assert tuple(step.subcommand for step in ask.steps) == (
        "operation-schema",
        "preview",
        "transaction-show",
        "confirm",
        "execute",
        "verify",
    )
    assert ask.turn_prefix_counts == (2, 6)
    assert ask.steps[1].arguments[:2] == ("--apply", "--request-json")
    assert isinstance(ask.steps[1].arguments[2], SemanticJsonArgument)

    assert tuple(step.subcommand for step in allow.steps) == (
        "operation-schema",
        "preview",
        "execute",
        "verify",
    )
    assert allow.turn_prefix_counts == (4,)
    assert allow.steps[1].arguments[:2] == ("--apply", "--request-json")
    assert allow.steps[2].arguments == (
        ResponseBinding("tx01.preview", "/transaction_id"),
    )
    assert allow.steps[3].arguments == (
        ResponseBinding("tx01.execute", "/transaction_id"),
    )


def test_policy_protocol_rejects_unknown_mode_or_nontransaction_base() -> None:
    with pytest.raises(V3ProtocolError, match="must be"):
        build_modification_policy_protocol(_base_protocol(), policy="unsafe")
    with pytest.raises(V3ProtocolError, match="ordinary transaction"):
        build_modification_policy_protocol(
            build_transaction_protocol(
                [
                    build_object_heavy_v3_recipe(
                        "OBJ22-F-CREATE-01"
                    ).request.as_dict()
                ],
                terminal_execute=True,
            ),
            policy="allow_changes",
        )


@pytest.mark.parametrize("policy", POLICY_MODES)
def test_policy_prompt_provenance_round_trips_without_a_second_harness(
    tmp_path: Path,
    policy: str,
) -> None:
    profile = _profile()
    unit = next(item for item in profile.units if item.policy_mode == policy)
    protocol = build_modification_policy_protocol(_base_protocol(), policy=policy)
    scenario_root = tmp_path / policy
    (scenario_root / "evidence").mkdir(parents=True)

    evidence = write_prompt_provenance(
        scenario=profile.scenario,
        version="2022.1",
        scenario_root=scenario_root,
        prompts=tuple(turn.prompt for turn in unit.turns),
        visible_values={},
        protocol=protocol,
    )

    assert evidence.prompts == tuple(turn.prompt for turn in unit.turns)
    assert deserialize_protocol(serialize_protocol(protocol)) == protocol


def test_matrix_and_campaign_select_fixed_low_cost_policy_settings(
    tmp_path: Path,
) -> None:
    common = _path_args(tmp_path)
    matrix_options = matrix.parse_args(
        ["--profile", PROFILE_ID, *common]
    )
    campaign_options = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--profile",
            PROFILE_ID,
            *common,
        ]
    )

    for options in (matrix_options, campaign_options):
        assert options.profile == PROFILE_ID
        assert options.suite_path == PROFILE_PATH.resolve()
        assert options.model == MODEL
        assert options.reasoning_effort == REASONING_EFFORT
        assert options.service_tier == SERVICE_TIER
    assert len(matrix.load_heavy_v3_units(matrix_options)) == 9

    with pytest.raises(SystemExit):
        matrix.parse_args(
            [
                "--profile",
                PROFILE_ID,
                "--model",
                "gpt-5.6-sol",
                *common,
            ]
        )


def test_campaign_child_request_seals_policy_repetition_turns_and_no_approval(
    tmp_path: Path,
) -> None:
    common = _path_args(tmp_path)
    options = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--profile",
            PROFILE_ID,
            *common,
        ]
    )
    unit = _profile().units[0]
    argv = campaign.build_heavy_v3_child_argv(
        options,
        units=(unit,),
        matrix_root=tmp_path / "matrix",
    )
    request = campaign.heavy_v3_child_request(
        options,
        units=(unit,),
        argv=argv,
    )

    assert request["request"]["memory"] == "disabled"
    assert request["request"]["approval_policy"] == APPROVAL_POLICY
    assert request["units"][0]["project_modification_policy"] == "read_only"
    assert request["units"][0]["repetition"] == 1
    assert len(request["units"][0]["turns"]) == 2
    assert argv.count("--case-id") == 1
    assert unit.unit_id in argv

    filtered = replace(options, case_ids=(unit.unit_id,))
    with pytest.raises(campaign.CampaignConfigError, match="fixed nine-task"):
        campaign.run_heavy_v3_campaign(filtered)


def test_policy_matrix_rejects_reused_thread_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "prepare_iteration_root",
        lambda path, *, overwrite: path.mkdir(parents=True, exist_ok=False),
    )
    common = _path_args(tmp_path)
    options = matrix.parse_args(
        [
            "--profile",
            PROFILE_ID,
            "--iteration-root",
            str(tmp_path / "matrix-run"),
            *common,
        ]
    )
    units = _profile().units[:2]

    def run(unit, **_kwargs):
        payload = {
            "contract": "synthetic-policy-outcome/v1",
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
    assert "reused a prior policy task thread identity" in "\n".join(
        summary["run_errors"]
    )


def test_policy_matrix_preserves_blocked_outcome_without_thread_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "prepare_iteration_root",
        lambda path, *, overwrite: path.mkdir(parents=True, exist_ok=False),
    )
    common = _path_args(tmp_path)
    options = matrix.parse_args(
        [
            "--profile",
            PROFILE_ID,
            "--iteration-root",
            str(tmp_path / "matrix-run"),
            *common,
        ]
    )
    unit = _profile().units[0]
    reason = "Codex failed before returning a thread identity"

    def run(_unit, **_kwargs):
        payload = {
            "contract": "synthetic-policy-outcome/v1",
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "status": "BLOCKED",
            "reason": reason,
            "scenario_root": "synthetic",
            "task_root": None,
            "thread_id": None,
            "checks": {},
            "lifecycle": {},
        }
        return SimpleNamespace(
            scenario_id=unit.unit_id,
            version=unit.version,
            status="BLOCKED",
            reason=reason,
            passed=False,
            thread_id=None,
            as_dict=lambda: payload,
        )

    result = matrix.run_heavy_v3_matrix(
        options,
        unit_loader=lambda _options: (unit,),
        unit_runner=run,
        dependency_preflight=lambda: {"ok": True},
    )

    assert result == 1
    case = json.loads(
        next((options.iteration_root / "scenarios").glob("*/matrix-case.json"))
        .read_text(encoding="utf-8")
    )
    assert case["status"] == "BLOCKED"
    assert case["reason"] == reason
    assert case["runner_outcome"]["thread_id"] is None


def test_policy_campaign_rejects_thread_reuse_across_retry_attempts(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    attempts_root = campaign_root / "attempts"

    def write_outcome(
        attempt_id: str,
        *,
        outcome_thread_id: str,
        event_thread_id: str,
    ) -> Path:
        scenario_root = (
            attempts_root
            / attempt_id
            / "runs"
            / campaign.HEAVY_V3_GROUP_ID
            / "matrix"
            / "scenarios"
            / "001-policy"
        )
        task_root = scenario_root / "evidence" / "codex-task"
        turn_root = task_root / "turns" / "turn-01"
        turn_root.mkdir(parents=True)
        (turn_root / "events.jsonl").write_text(
            json.dumps(
                {"type": "thread.started", "thread_id": event_thread_id}
            )
            + "\n",
            encoding="utf-8",
        )
        (scenario_root / "outcome.json").write_text(
            json.dumps(
                {
                    "thread_id": outcome_thread_id,
                    "task_root": str(task_root),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return attempts_root / attempt_id

    prior_root = write_outcome(
        "attempt-000001",
        outcome_thread_id="reused-thread",
        event_thread_id="reused-thread",
    )
    current_root = write_outcome(
        "attempt-000002",
        outcome_thread_id="reused-thread",
        event_thread_id="reused-thread",
    )
    assert prior_root.is_dir()

    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="reused policy thread identity",
    ):
        campaign._validate_modification_policy_identity_history(
            campaign_root,
            manifests=({"attempt_id": "attempt-000001"},),
            current_attempt_root=current_root,
        )


def test_policy_campaign_allows_attempt_without_returned_thread_identity(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    scenario_root = (
        campaign_root
        / "attempts"
        / "attempt-000001"
        / "runs"
        / campaign.HEAVY_V3_GROUP_ID
        / "matrix"
        / "scenarios"
        / "001-policy"
    )
    scenario_root.mkdir(parents=True)
    (scenario_root / "outcome.json").write_text(
        json.dumps({"thread_id": None, "task_root": None}) + "\n",
        encoding="utf-8",
    )

    campaign._validate_modification_policy_identity_history(
        campaign_root,
        manifests=({"attempt_id": "attempt-000001"},),
    )


def test_policy_campaign_preserves_raw_thread_for_retryable_second_turn_failure(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    scenario_root = (
        campaign_root
        / "attempts"
        / "attempt-000001"
        / "runs"
        / campaign.HEAVY_V3_GROUP_ID
        / "matrix"
        / "scenarios"
        / "001-policy"
    )
    task_root = scenario_root / "evidence" / "codex-task"
    turns_root = task_root / "turns"
    for turn_index in (1, 2):
        turn_root = turns_root / f"turn-{turn_index:02d}"
        turn_root.mkdir(parents=True)
        (turn_root / "events.jsonl").write_text(
            json.dumps(
                {"type": "thread.started", "thread_id": "fresh-policy-thread"}
            )
            + "\n",
            encoding="utf-8",
        )
    failure = {
        "category": "timeout_before_agent_action",
        "turn_failed": False,
        "timed_out": True,
        "agent_item_event_count": 0,
    }
    checks = {
        "failure_classification": "BLOCKED",
        "codex_infrastructure_failure": failure,
    }
    (task_root / "infrastructure-failure.json").write_text(
        json.dumps(
            {
                "contract": (
                    campaign.HEAVY_V3_TASK_INFRASTRUCTURE_FAILURE_CONTRACT
                ),
                "scenario_id": "OBJ22-F-CREATE-01",
                "version": "2022.1",
                "failed_turn_index": 2,
                "expected_turn_count": 2,
                "prior_completed_turn_count": 1,
                "previous_broker_prefix": 2,
                "expected_failed_turn_prefix": 6,
                "prior_thread_id": "fresh-policy-thread",
                "prompt_sha256": "a" * 64,
                "failure": failure,
                "artifact_sha256": {"turns/turn-01/events.jsonl": "b" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (scenario_root / "outcome.json").write_text(
        json.dumps(
            {
                "scenario_id": "POL22-CREATE-ASK-BEFORE-R1",
                "version": "2022.1",
                "status": "BLOCKED",
                "task_root": str(task_root),
                "thread_id": None,
                "checks": checks,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    campaign._validate_modification_policy_identity_history(
        campaign_root,
        manifests=({"attempt_id": "attempt-000001"},),
    )


def test_broker_accepts_only_canonical_project_policy_names(tmp_path: Path) -> None:
    step = _base_protocol().steps[0]
    broker = CodexGatewayBroker(
        skill_source=tmp_path / "skill",
        expected_steps=(step,),
        project_modification_policy="allow_changes",
    )
    assert broker.project_modification_policy == "allow_changes"

    with pytest.raises(ValueError, match="must be read_only"):
        CodexGatewayBroker(
            skill_source=tmp_path / "skill",
            expected_steps=(step,),
            project_modification_policy="preview_then_confirm",
        )


def test_allow_changes_notice_terms_come_from_the_sealed_object_recipe() -> None:
    assert project_runner._policy_notice_change_terms(_profile().scenario) == (
        "Player_Foley",
        "Footsteps",
        "Cloth",
    )


def test_allow_changes_intro_or_generic_mode_text_cannot_masquerade_as_notice() -> None:
    preview = "gateway preview --apply --request-json request"
    execute = "gateway execute tx"
    terms = ("Player_Foley", "Footsteps", "Cloth")
    intro_before_preview = _policy_result(
        [
            _agent(
                "已加载 waapi-skill，修改策略 allow_changes，将创建 "
                "Player_Foley、Footsteps 和 Cloth。"
            ),
            _command(preview),
            _command(execute, completed=False),
        ]
    )
    generic_after_preview = _policy_result(
        [
            _command(preview),
            _agent("当前修改策略是 allow_changes，可以直接继续。"),
            _command(execute, completed=False),
        ]
    )
    concrete_after_preview = _policy_result(
        [
            _command(preview),
            _agent(
                "预览已生成；当前 allow_changes 模式允许直接执行。"
                "接下来会创建 Player_Foley，并建出 Footsteps 和 Cloth。"
            ),
            _command(execute, completed=False),
        ]
    )

    assert not project_runner._policy_notice_precedes_execute(
        intro_before_preview,
        expected_change_terms=terms,
    )
    assert not project_runner._policy_notice_precedes_execute(
        generic_after_preview,
        expected_change_terms=terms,
    )
    assert project_runner._policy_notice_precedes_execute(
        concrete_after_preview,
        expected_change_terms=terms,
    )
    for natural_notice in (
        "预览已生成，当前 allow_changes；接下来我会按预览直接执行，"
        "创建 Player_Foley，并建出 Footsteps 和 Cloth。",
        "当前修改策略 allow_changes，我现在直接按预览执行："
        "创建 Player_Foley，下设 Footsteps 和 Cloth。",
        "allow_changes 已授权；随后按预览执行，"
        "创建 Player_Foley、Footsteps 和 Cloth。",
        "预览已锁定，当前模式已授权执行；现在会创建 "
        "Player_Foley、Footsteps 和 Cloth。",
        "即将创建 Player_Foley、Footsteps 和 Cloth；"
        "现在按当前策略执行并验证。",
    ):
        assert project_runner._policy_notice_precedes_execute(
            _policy_result(
                [
                    _command(preview),
                    _agent(natural_notice),
                    _command(execute, completed=False),
                ]
            ),
            expected_change_terms=terms,
        )
    for negated in (
        "我不会创建",
        "我不能创建",
        "先不去创建",
        "暂不新建",
    ):
        negated_after_preview = _policy_result(
            [
                _command(preview),
                _agent(
                    f"当前是 allow_changes，但{negated} "
                    "Player_Foley、Footsteps 或 Cloth。"
                ),
                _command(execute, completed=False),
            ]
        )
        assert not project_runner._policy_notice_precedes_execute(
            negated_after_preview,
            expected_change_terms=terms,
        )


def test_read_only_and_ask_before_changes_require_truthful_natural_responses() -> None:
    terms = ("Player_Foley", "Footsteps", "Cloth")
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "当前是 read_only 只读模式，所以不会创建 Player_Foley，"
                "项目保持原样，没有改动。"
            )
        ),
        policy="read_only",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(final_response="项目保持原样，没有任何改动。"),
        policy="read_only",
        turn_index=2,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "当前策略为 read_only，已确认可用的创建方案会包含 "
                "Player_Foley；本次未执行创建。"
            )
        ),
        policy="read_only",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "当前为 read_only，因此无法创建对象；工程未发生任何修改。"
            )
        ),
        policy="read_only",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "当前策略为 read_only，因此不能创建 Wwise 对象；"
                "工程未发生任何更改。"
            )
        ),
        policy="read_only",
        turn_index=1,
        expected_change_terms=terms,
    )
    for unchanged_wording in (
        "当前策略为 read_only，无法创建对象；工程未发生任何变更。",
        "当前策略为 read_only，无法创建对象；工程未发生变化。",
        "当前策略为 read_only，无法创建对象；本次没有更改项目。",
        "当前策略为 read_only，无法创建对象；本次未对工程做任何更改。",
        "当前为 read_only，已阻止此次创建请求，工程未发生任何更改。",
    ):
        project_runner._require_policy_turn_response(
            SimpleNamespace(final_response=unchanged_wording),
            policy="read_only",
            turn_index=1,
            expected_change_terms=terms,
        )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "我已生成预览：会创建 Player_Foley，并在其中建立 Footsteps "
                "和 Cloth；目前尚未执行，项目没有改动。请确认后我再继续。"
            )
        ),
        policy="ask_before_changes",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "Player_Foley 的预览已经创建完成，预期其中包含 Footsteps "
                "与 Cloth；项目尚未执行、没有改动，请确认后我再继续。"
            )
        ),
        policy="ask_before_changes",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "已生成创建预览：将创建 Player_Foley、Footsteps 和 Cloth，"
                "尚未写入工程。请明确回复“确认创建”以执行。"
            )
        ),
        policy="ask_before_changes",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "预览已生成，尚未写入工程。将创建 Player_Foley、Footsteps "
                "和 Cloth。请回复“确认创建”以执行；完成后我会列出结果。"
            )
        ),
        policy="ask_before_changes",
        turn_index=1,
        expected_change_terms=terms,
    )
    project_runner._require_policy_turn_response(
        SimpleNamespace(
            final_response=(
                "已生成创建预览，尚未改动工程。将创建 Player_Foley、"
                "Footsteps 和 Cloth。确认要执行创建吗？"
            )
        ),
        policy="ask_before_changes",
        turn_index=1,
        expected_change_terms=terms,
    )
    for direct_question in (
        "可以继续执行吗？",
        "要继续吗？",
        "需要我现在执行吗？",
    ):
        project_runner._require_policy_turn_response(
            SimpleNamespace(
                final_response=(
                    "预览已生成，工程尚未修改。将创建 Player_Foley、"
                    f"Footsteps 和 Cloth。{direct_question}"
                )
            ),
            policy="ask_before_changes",
            turn_index=1,
            expected_change_terms=terms,
        )

    with pytest.raises(project_runner.HeavyProjectRunnerError, match="read_only"):
        project_runner._require_policy_turn_response(
            SimpleNamespace(final_response="操作已完成。"),
            policy="read_only",
            turn_index=1,
            expected_change_terms=terms,
        )
    with pytest.raises(
        project_runner.HeavyProjectRunnerError,
        match="ask_before_changes",
    ):
        project_runner._require_policy_turn_response(
            SimpleNamespace(final_response="已经创建完成。"),
            policy="ask_before_changes",
            turn_index=1,
            expected_change_terms=terms,
        )
    for ambiguous in ("尚未完成。", "项目尚未达到最终状态。"):
        with pytest.raises(
            project_runner.HeavyProjectRunnerError,
            match="read_only",
        ):
            project_runner._require_policy_turn_response(
                SimpleNamespace(final_response=ambiguous),
                policy="read_only",
                turn_index=2,
                expected_change_terms=terms,
            )
    for ambiguous in (
        "Player_Foley 的预览尚未完成，请确认后继续。",
        "Player_Foley 的预览已生成，项目尚未全部完成，请确认后继续。",
        "预览已生成，尚未修改工程。将创建 Player_Foley、Footsteps 和 Cloth。"
        "确认后我会执行。",
    ):
        with pytest.raises(
            project_runner.HeavyProjectRunnerError,
            match="ask_before_changes",
        ):
            project_runner._require_policy_turn_response(
                SimpleNamespace(final_response=ambiguous),
                policy="ask_before_changes",
                turn_index=1,
                expected_change_terms=terms,
            )
    with pytest.raises(project_runner.HeavyProjectRunnerError, match="read_only"):
        project_runner._require_policy_turn_response(
            SimpleNamespace(
                final_response=(
                    "当前是 read_only，Player_Foley 层级已经建好了，"
                    "但项目没有改动。"
                )
            ),
            policy="read_only",
            turn_index=1,
            expected_change_terms=terms,
        )
    with pytest.raises(
        project_runner.HeavyProjectRunnerError,
        match="ask_before_changes",
    ):
        project_runner._require_policy_turn_response(
            SimpleNamespace(
                final_response=(
                    "Player_Foley 的操作已经完成，项目尚未执行；请确认。"
                )
            ),
            policy="ask_before_changes",
            turn_index=1,
            expected_change_terms=terms,
        )

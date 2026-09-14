from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support import codex_first_use as welcome
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ExpectedGatewayStep
from tests.semantic.test_codex_gateway_broker import run_model_command


FACTS = {
    "endpoint_url": "ws://127.0.0.1:18765/waapi",
    "adapter_version": "2024.1",
    "project_modification_policy": "allow_changes",
}
INTRO = (
    "WAAPI Skill 已加载。当前配置的地址为 ws://127.0.0.1:18765/waapi，"
    "适配版本 2024.1，当前模式 allow_changes。"
    "read_only 只读；ask_before_changes 修改前确认；allow_changes 允许修改。"
)


def test_both_initial_prompts_are_bare_invocations() -> None:
    skill = Path("/demo/.agents/skills/waapi-skill")
    assert welcome.initial_prompt("bare-slash", skill) == "/waapi-skill"
    assert welcome.initial_prompt("bare-link", skill) == (
        "[$waapi-skill](/demo/.agents/skills/waapi-skill/SKILL.md)"
    )
    assert welcome.FOLLOWUP == "先不操作，等我下一条消息。"
    with pytest.raises(ValueError):
        welcome.initial_prompt("unknown", skill)


@pytest.mark.parametrize("folder", ["Skill root 声音", "Skill(root)"])
def test_bare_link_keeps_a_special_install_path_in_one_markdown_destination(folder) -> None:
    skill = Path("/demo") / folder / "waapi-skill"

    assert welcome.initial_prompt("bare-link", skill) == (
        f"[$waapi-skill](<{skill / 'SKILL.md'}>)"
    )


def test_intro_uses_gateway_facts_without_exact_sentence_matching() -> None:
    assert all(welcome.introduction_checks(INTRO, FACTS).values())
    assert all(welcome.introduction_checks(INTRO.replace("WAAPI Skill", "waapi-skill"), FACTS).values())
    assert not all(welcome.introduction_checks("请告诉我你想做什么。", FACTS).values())
    assert not all(welcome.introduction_checks(INTRO.replace("2024.1", "2025.1"), FACTS).values())
    assert not welcome.introduction_checks(INTRO.replace("当前配置的", "当前连接的"), FACTS)["offline_wording"]
    assert not all(welcome.introduction_checks(INTRO, {}).values())


@pytest.mark.parametrize("phrase", (
    "尚未确认已连接", "还未验证是否已成功连接", "未确认已连接",
))
def test_offline_intro_accepts_unconfirmed_connection_but_rejects_a_separate_claim(phrase) -> None:
    unconfirmed = INTRO + phrase + "。"

    assert welcome.introduction_checks(unconfirmed, FACTS)["offline_wording"]
    for affirmative in ("已连接 Wwise。", "已成功连接 Wwise。", "当前连接的 Wwise 已就绪。"):
        assert not welcome.introduction_checks(
            unconfirmed + affirmative, FACTS
        )["offline_wording"]


@pytest.mark.parametrize("display", ["WAAPI 端口为 18765", "WAAPI port: 18765"])
def test_intro_accepts_localized_port_without_requiring_the_full_url(display) -> None:
    text = INTRO.replace("ws://127.0.0.1:18765/waapi", display)
    assert all(welcome.introduction_checks(text, FACTS).values())
    for wrong in ("8080", "118765", "187650"):
        assert not welcome.introduction_checks(text.replace("18765", wrong), FACTS)["endpoint"]


def test_first_use_matrix_routes_without_loading_a_legacy_suite(monkeypatch) -> None:
    options = SimpleNamespace(profile="first_use_2")
    monkeypatch.setattr(matrix, "parse_args", lambda argv: options)
    monkeypatch.setattr(welcome, "run_first_use_matrix", lambda value: 0 if value is options else 1)
    monkeypatch.setattr(matrix, "load_eval_suite", lambda *_: pytest.fail("legacy suite is out of scope"))
    assert matrix.main([]) == 0


def test_turn_archive_retains_raw_events_and_independent_audits(tmp_path) -> None:
    result = SimpleNamespace(
        stdout='{"type":"turn.completed"}\n', stderr="", final_response=INTRO,
        facts_dict=lambda: {"thread_id": "fresh-thread", "prompt_audit": {"passed": True}},
    )
    welcome.save_turn(tmp_path, result)
    assert (tmp_path / "events.jsonl").read_text() == result.stdout
    assert (tmp_path / "final-response.txt").read_text() == INTRO
    assert json.loads((tmp_path / "codex-result.json").read_text())["thread_id"] == "fresh-thread"


def test_followup_rejects_repeated_welcome_or_a_new_thread(monkeypatch) -> None:
    monkeypatch.setattr(welcome, "common_checks", lambda result: {"completed": True})
    def result(text, thread_id="same", commands=()):
        return SimpleNamespace(
            thread_id=thread_id, command_facts=SimpleNamespace(commands=commands),
            stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}}),
        )
    assert all(welcome.followup_checks(result("好的，等你下一条消息。"), "same", FACTS).values())
    assert not welcome.followup_checks(result(INTRO), "same", FACTS)["no_repeated_welcome"]
    assert not welcome.followup_checks(result("好的", thread_id="new"), "same", FACTS)["same_thread"]
    assert not welcome.followup_checks(result("好的", commands=("config-show",)), "same", FACTS)["no_commands"]


@pytest.mark.parametrize("extra", [[], ["--offline-only"], ["--offline-only", "--iteration-root", "unused", "--overwrite"]])
def test_first_use_cli_requires_a_new_explicit_offline_root(extra) -> None:
    with pytest.raises(SystemExit) as error:
        matrix.parse_args(["--profile", "first_use_2", *extra])
    assert error.value.code == 2


def test_offline_broker_executes_production_config_show_and_rejects_a_second_call(tmp_path) -> None:
    with CodexGatewayBroker(
        skill_source=matrix.SKILL_ROOT,
        expected_steps=(ExpectedGatewayStep("config-show", "config-show"),),
        expected_wwise_version="2024.1",
        project_modification_policy="allow_changes",
        runner_environment=matrix.trusted_gateway_environment({"WWISE_WAAPI_PORT": "18765"}),
        working_root=tmp_path / "broker", transport="tcp",
    ) as broker:
        completed = run_model_command(broker, ["config-show"])
        assert completed.returncode == 0, completed.stderr + completed.stdout
        evidence = broker.evidence()
        assert evidence.passed
        context = evidence.records[0].payload["session_context"]
        assert all(context["one_time_introduction"]["facts"][key] == value for key, value in FACTS.items())
        assert not tuple(broker.evidence_directory.glob("dispatch-*.json"))
        assert run_model_command(broker, ["config-show"]).returncode != 0
        assert not broker.evidence().passed

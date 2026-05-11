from __future__ import annotations

from pathlib import Path

from wwise_waapi.config import SkillConfig  # pyright: ignore[reportMissingImports]
from wwise_waapi.operator import (  # pyright: ignore[reportMissingImports]
    OPERATOR_INTENT_FAMILIES,
    OperatorInputs,
    decide_operator_policy,
    decide_operator_policy_for_inputs,
)


def ready_config(tmp_path: Path, *, project_modification_policy: str = "preview_then_confirm") -> SkillConfig:
    return SkillConfig(
        tmp_path,
        wwise_version="2022.1",
        waapi_host="127.0.0.1",
        waapi_port=8080,
        project_modification_policy=project_modification_policy,
    )


def test_all_seven_operator_intent_families_are_exposed() -> None:
    assert OPERATOR_INTENT_FAMILIES == (
        "operator_read",
        "operator_waql",
        "operator_mutation_preview",
        "operator_mutation_confirmed",
        "compound_read_then_confirm",
        "research_explicit",
        "blocked_setup",
    )


def test_ready_read_only_prompt_routes_to_operator_read_before_research(tmp_path: Path) -> None:
    decision = decide_operator_policy("show selected objects", config=ready_config(tmp_path))

    assert decision.intent_family == "operator_read"
    assert decision.setup_ready is True
    assert decision.live_waapi_attempt is True
    assert decision.live_waapi_required is True
    assert decision.research_allowed is False
    assert decision.mutation_allowed is False
    assert decision.blockers == ()


def test_read_prompt_with_audio_source_domain_word_is_not_research(tmp_path: Path) -> None:
    decision = decide_operator_policy("show audio source objects", config=ready_config(tmp_path))

    assert decision.intent_family == "operator_read"
    assert decision.live_waapi_attempt is True
    assert decision.research_allowed is False


def test_waql_shape_routes_to_operator_waql(tmp_path: Path) -> None:
    decision = decide_operator_policy(
        "run this WAQL query",
        config=ready_config(tmp_path),
        waql="from type Sound",
        api="ak.wwise.core.object.get",
    )

    assert decision.intent_family == "operator_waql"
    assert decision.live_waapi_attempt is True
    assert decision.inputs["waql_supplied"] is True


def test_explicit_research_prompt_routes_to_research_explicit(tmp_path: Path) -> None:
    decision = decide_operator_policy("research the Wwise docs for object.get return fields", config=ready_config(tmp_path))

    assert decision.intent_family == "research_explicit"
    assert decision.research_allowed is True
    assert decision.live_waapi_attempt is False
    assert decision.blockers == ()


def test_setup_blocked_read_reports_public_config_and_connection_blockers(tmp_path: Path) -> None:
    config = SkillConfig(tmp_path)
    decision = decide_operator_policy("list objects", config=config, connection_available=False)

    assert decision.intent_family == "blocked_setup"
    assert decision.setup_ready is False
    assert decision.live_waapi_required is True
    assert decision.live_waapi_attempt is False
    assert decision.research_allowed is True
    assert decision.blockers == (
        "wwise_version is not configured",
        "waapi_port is not configured",
        "live WAAPI connection is unavailable",
    )


def test_connection_inputs_can_complete_setup_without_persisting_new_fields(tmp_path: Path) -> None:
    config = SkillConfig(tmp_path, wwise_version="2022.1", waapi_port=None)
    decision = decide_operator_policy(
        "get Wwise info",
        config=config,
        connection_host="127.0.0.1",
        connection_port=31337,
        connection_available=True,
    )

    assert decision.intent_family == "operator_read"
    assert decision.setup_ready is True
    assert decision.config.waapi_port is None
    assert decision.inputs["connection_port"] == 31337


def test_project_modification_policy_never_blocks_live_mutation_but_allows_preview(tmp_path: Path) -> None:
    decision = decide_operator_policy(
        "delete this sound",
        config=ready_config(tmp_path, project_modification_policy="never"),
        mutation_requested=True,
        confirmation_state="confirmed",
    )

    assert decision.intent_family == "operator_mutation_preview"
    assert decision.mutation_preview is True
    assert decision.mutation_allowed is False
    assert decision.dispatcher_dry_run is True
    assert decision.dispatcher_allow_destructive is False
    assert decision.blockers == ("project_modification_policy=never blocks live mutation",)


def test_preview_then_confirm_is_preview_first(tmp_path: Path) -> None:
    decision = decide_operator_policy(
        "rename the object",
        config=ready_config(tmp_path, project_modification_policy="preview_then_confirm"),
        mutation_requested=True,
        confirmation_state="preview",
    )

    assert decision.intent_family == "operator_mutation_preview"
    assert decision.mutation_preview is True
    assert decision.mutation_confirmation_required is True
    assert decision.dispatcher_dry_run is True
    assert decision.mutation_allowed is False


def test_allow_with_notice_allows_explicit_wrapper_mutation_without_separate_confirmation(tmp_path: Path) -> None:
    decision = decide_operator_policy(
        "rename the object",
        config=ready_config(tmp_path, project_modification_policy="allow_with_notice"),
        mutation_requested=True,
    )

    assert decision.intent_family == "operator_mutation_confirmed"
    assert decision.mutation_allowed is True
    assert decision.mutation_confirmed is True
    assert decision.dispatcher_allow_destructive is True
    assert decision.dispatcher_dry_run is False
    assert decision.blockers == ()


def test_allow_with_notice_does_not_infer_destructive_permission_from_prompt_tone(tmp_path: Path) -> None:
    decision = decide_operator_policy(
        "please rename the object now",
        config=ready_config(tmp_path, project_modification_policy="allow_with_notice"),
    )

    assert decision.intent_family == "operator_mutation_preview"
    assert decision.mutation_allowed is False
    assert decision.dispatcher_allow_destructive is False
    assert decision.blockers == ("unknown mutation confirmation state is blocked",)


def test_confirmed_mutation_requires_explicit_confirmation_state(tmp_path: Path) -> None:
    confirmed = decide_operator_policy(
        "delete the object now",
        config=ready_config(tmp_path),
        mutation_requested=True,
        confirmation_state="confirmed",
    )
    ambiguous = decide_operator_policy(
        "please delete the object; this sounds urgent",
        config=ready_config(tmp_path),
        mutation_requested=True,
    )

    assert confirmed.intent_family == "operator_mutation_confirmed"
    assert confirmed.mutation_allowed is True
    assert confirmed.mutation_confirmed is True
    assert confirmed.dispatcher_allow_destructive is True
    assert ambiguous.intent_family == "operator_mutation_preview"
    assert ambiguous.mutation_allowed is False
    assert ambiguous.mutation_confirmation_required is True
    assert ambiguous.blockers == ("unknown mutation confirmation state is blocked",)


def test_compound_read_then_confirm_stages_preview_without_implementing_execution(tmp_path: Path) -> None:
    decision = decide_operator_policy(
        "read the target first then rename it",
        config=ready_config(tmp_path),
        mutation_requested=True,
        read_before_mutation=True,
    )

    assert decision.intent_family == "compound_read_then_confirm"
    assert decision.live_waapi_attempt is True
    assert decision.mutation_preview is True
    assert decision.mutation_confirmation_required is True
    assert decision.dispatcher_dry_run is True
    assert decision.mutation_allowed is False


def test_policy_can_load_skill_config_from_path(tmp_path: Path) -> None:
    config_path = tmp_path / "data" / "config.json"
    config = ready_config(tmp_path, project_modification_policy="allow_with_notice")
    config.save(config_path)

    decision = decide_operator_policy("show project info", skill_root=tmp_path, config_path=config_path)

    assert decision.intent_family == "operator_read"
    assert decision.config.as_dict() == {
        "wwise_version": "2022.1",
        "waapi_host": "127.0.0.1",
        "waapi_port": 8080,
        "project_modification_policy": "allow_with_notice",
    }


def test_operator_inputs_reject_unknown_confirmation_state(tmp_path: Path) -> None:
    try:
        decide_operator_policy_for_inputs(
            OperatorInputs(prompt="delete", mutation_requested=True, confirmation_state="sure"),
            ready_config(tmp_path),
        )
    except ValueError as exc:
        assert "confirmation_state must be one of" in str(exc)
    else:
        raise AssertionError("Expected invalid confirmation state to fail closed")

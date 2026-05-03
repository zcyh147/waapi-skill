from __future__ import annotations

from pathlib import Path


SKILL_MD = Path(__file__).resolve().parents[2] / "skills" / "wwise-waapi" / "SKILL.md"


def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_contract_documents_generic_dispatcher_not_per_api_wrappers() -> None:
    text = skill_text()

    assert "one generic" in text.lower()
    assert "Do not create one skill or wrapper per API" in text
    assert "WwiseDispatcher" in text
    assert "resources/manifest/<version>/" in text


def test_skill_contract_documents_input_output_and_error_fields() -> None:
    text = skill_text()

    for required in ("api", "version", "args", "options", "timeout", "dry_run", "allow_destructive", "evidence_dir"):
        assert required in text
    for required in ("ok", "api", "version", "error_code", "message", "evidence_path"):
        assert f'"{required}"' in text or f"`{required}`" in text


def test_skill_contract_documents_safety_timeout_notebooklm_and_evidence_guidance() -> None:
    text = skill_text()

    assert "prefer 5-10 seconds" in text
    assert "WWISE_DESTRUCTIVE=1" in text
    assert "Destructive or mutating functions are blocked by default" in text
    assert "NotebookLM documentation gate" in text
    assert "wwise-2022.1-docs" in text
    assert "evidence_path" in text


def test_skill_contract_documents_topic_subscription_runtime() -> None:
    text = skill_text()

    assert "topic_mode" in text
    assert "SubscriptionManager" in text
    assert "Long-running listeners" in text


def test_skill_contract_prefers_semantic_builders_for_complex_api_families() -> None:
    text = skill_text()

    assert "For P0/P1/P2 complex WAAPI work" in text
    assert "prefer `wwise_waapi.builders` semantic builders" in text
    assert "they do not open Wwise, subscribe to topics, or dispatch live calls by default" in text
    assert "raw `WwiseDispatcher` contract remains the explicit escape hatch" in text
    for family in (
        "`query`",
        "`object-mutation`",
        "`property-reference`",
        "`import`",
        "`soundbank`",
        "`switchcontainer`",
    ):
        assert family in text

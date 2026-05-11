from __future__ import annotations

import re
from pathlib import Path


SKILL_MD = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "SKILL.md"


def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def protocol_section() -> str:
    text = skill_text()
    start = text.index("## Operator protocol")
    end = text.index("## Setup and runner")
    return text[start:end]


def test_operator_protocol_is_closed_and_before_implementation_details() -> None:
    text = skill_text()
    protocol = protocol_section()

    assert text.index("## Operator protocol") < text.index("## Setup and runner")
    assert "closed decision tree" in protocol
    assert "Choose exactly one intent family" in protocol
    assert "Do not invent additional intent families" in protocol

    intent_names = re.findall(r"^\d+\. `(operator_[^`]+|compound_read_then_confirm|research_explicit|blocked_setup)`", protocol, re.MULTILINE)
    assert intent_names == [
        "operator_read",
        "operator_waql",
        "operator_mutation_preview",
        "operator_mutation_confirmed",
        "compound_read_then_confirm",
        "research_explicit",
        "blocked_setup",
    ]


def test_read_only_and_waql_ready_prompts_must_execute_live_before_research() -> None:
    protocol = protocol_section()

    read_branch = _numbered_branch(protocol, "operator_read")
    waql_branch = _numbered_branch(protocol, "operator_waql")

    for branch in (read_branch, waql_branch):
        assert "persisted config" in branch
        assert "live WAAPI" in branch
        assert "execute live WAAPI first" in branch
        assert "before repository, source, or documentation research" in branch
        assert "only after live execution is blocked" in branch
        assert "report the blocker" in branch


def test_research_is_limited_to_explicit_requests_or_blocked_live_execution() -> None:
    protocol = protocol_section()
    research_branch = _numbered_branch(protocol, "research_explicit")
    blocked_branch = _numbered_branch(protocol, "blocked_setup")

    assert "Use only when the user explicitly asks for research" in research_branch
    assert "not as a substitute for a ready live read or WAQL request" in research_branch
    assert "report the blocker" in blocked_branch
    assert "then use local packaged resources or repository docs only to unblock setup" in blocked_branch


def test_compound_contract_and_preview_identity_invariant_are_documented() -> None:
    protocol = protocol_section()
    compound_branch = _numbered_branch(protocol, "compound_read_then_confirm")

    assert "resolve/probe -> read -> summarize -> preview -> confirm -> execute -> verify" in compound_branch
    assert "Preview identity invariant" in protocol
    assert "preview-resolved target identity" in protocol
    assert "must be reused during confirmed execution" in protocol
    assert "abort and re-preview" in protocol


def test_public_config_surface_excludes_internal_runtime_constants() -> None:
    text = skill_text()
    protocol = protocol_section()

    assert "`wwise_version`, `waapi_host`, `waapi_port`, and `project_modification_policy`" in text
    assert "saved public config fields are exactly `wwise_version`, `waapi_host`, `waapi_port`, and `project_modification_policy`" in protocol
    assert "startup" in text
    assert "readiness" in text
    assert "WwiseConsole" in text
    assert "not saved public config" in text
    assert "`use_current_selection_for_ambiguous_queries`" in text
    assert "not saved public config" in text
    assert "saved public config fields include `startup" not in text
    assert "saved public config fields include `readiness" not in text
    assert "saved public config fields include `WwiseConsole" not in text


def _numbered_branch(text: str, name: str) -> str:
    pattern = re.compile(rf"^\d+\. `{re.escape(name)}`(?P<body>.*?)(?=^\d+\. `|^Named invariant:|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    assert match is not None, name
    return match.group(0)

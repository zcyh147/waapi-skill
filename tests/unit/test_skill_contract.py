from __future__ import annotations

from pathlib import Path


SKILL_MD = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "SKILL.md"


def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_contract_documents_runner_and_dispatcher() -> None:
    text = skill_text()

    assert "scripts/run.py" in text
    assert "WwiseDispatcher" in text
    assert "SubscriptionManager" in text
    assert "resources/manifest/<version>/" in text
    assert "resources/semantic/<version>/" in text
    assert "resources/waql/<version>/" in text
    assert "resources/deferred/<version>.json" in text
    assert "references/semantic/<version>/" in text


def test_skill_contract_documents_inputs_outputs_and_safety() -> None:
    text = skill_text()

    for required in ("api", "version", "args", "options", "timeout", "dry_run", "allow_destructive", "evidence_dir"):
        assert required in text
    for required in ("project modification policy", "never", "preview_then_confirm", "allow_with_notice"):
        assert required in text
    for required in ("ok", "api", "version", "error_code", "message", "evidence_path"):
        assert f'"{required}"' in text or f"`{required}`" in text
    assert "blocked by default" in text
    assert "Do not claim Windows validation has passed" in text
    assert "Treat operations such as object deletion, object creation" in text


def test_skill_contract_stays_user_facing_and_local_resource_oriented() -> None:
    text = skill_text()

    assert "local packaged resources" in text
    assert "large prompt-loaded 2025 reference files" in text
    legacy_path = "resources/" + "coverage/<version>/"
    assert legacy_path not in text


def test_skill_contract_prefers_live_read_only_execution_before_research() -> None:
    text = skill_text()

    assert "When config and live WAAPI connection details are already known" in text
    assert "execute the live read-only query first" in text
    assert "Do not start by inspecting repository files or launching documentation research" in text


def test_skill_contract_requires_confirmation_before_retargeting_invalid_parent() -> None:
    text = skill_text()

    assert "If a requested mutation target path is not a valid direct writable parent" in text
    assert "do not silently retarget the mutation" in text
    assert "ask the user to confirm the intended writable child container" in text

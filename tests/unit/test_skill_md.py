from __future__ import annotations

from pathlib import Path


def test_skill_contract_mentions_scaffold_elements() -> None:
    skill_md = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "wwise-waapi" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "wwise-waapi" in text
    assert "scripts/run.py" in text
    assert "pytest" in text
    assert "headless lifecycle" in text.lower()

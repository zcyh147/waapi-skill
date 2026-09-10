from __future__ import annotations

from pathlib import Path


def test_skill_contract_mentions_scaffold_elements() -> None:
    skill_md = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "name: waapi-skill" in text
    assert "scripts/run.py" in text
    assert "versioned manifest, semantic, WAQL, and deferred resources" in text
    assert "references/waapi-setup.md" in text
    assert "references/waapi-query.md" in text
    assert "references/waapi-operate.md" in text
    assert "gateway.py status" in text

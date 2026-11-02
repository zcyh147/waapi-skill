from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
REFERENCE_ROOT = SKILL_ROOT / "references" / "semantic" / "2023.1"
GATE_PATH = REFERENCE_ROOT / "semantic-builder-notebooklm-gate.md"
PACKAGED_2022_REFERENCE_ROOT = SKILL_ROOT / "references" / "semantic" / "2022.1"

FAMILIES = (
    "query",
    "object-mutation",
    "property-reference",
    "import",
    "soundbank",
    "switchcontainer",
)

PACKAGED_2022_FILES = (
    "semantic-builder-protocol.md",
    "semantic-builder-notebooklm-gate.md",
    *(f"semantic-builder-{family}.md" for family in FAMILIES),
)

REQUIRED_SECTIONS = (
    "## Official/source URLs",
    "## Endpoint inventory",
    "## Required fields",
    "## Optional fields",
    "## Return shape",
    "## Destructive behavior",
    "## Ambiguity constraints",
    "## Unsupported cases",
    "## Cited required fields",
)


def read_reference(name: str) -> str:
    return (REFERENCE_ROOT / f"semantic-builder-{name}.md").read_text(encoding="utf-8")


def test_2023_semantic_references_do_not_use_packaged_2022_files() -> None:
    for filename in PACKAGED_2022_FILES:
        assert (PACKAGED_2022_REFERENCE_ROOT / filename).exists(), f"missing fixture for isolation check: {filename}"

    expected_files = {
        "semantic-builder-protocol.md",
        "semantic-builder-notebooklm-gate.md",
        *(f"semantic-builder-{family}.md" for family in FAMILIES),
    }
    assert {path.name for path in REFERENCE_ROOT.glob("semantic-builder-*.md")} == expected_files

    for name in ("protocol", *FAMILIES):
        text = read_reference(name)
        assert "wwise-2023.1-docs" in text
        assert "2023.1" in text
        assert "references/semantic/2023.1/semantic-builder-notebooklm-gate.md" in text or name == "protocol"
        assert "references/semantic-builder-" not in text
        assert "wwise-2022.1-docs" not in text

    gate_text = GATE_PATH.read_text(encoding="utf-8")
    assert "references/semantic-builder-" not in gate_text
    assert "wwise-2022.1-docs" not in gate_text


def test_2023_local_references_keep_version_matched_source_sections() -> None:
    for family in FAMILIES:
        text = read_reference(family)
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{family} missing {section}"
        assert "wwise-2023.1-docs" in text
        assert "references/semantic/2023.1/semantic-builder-notebooklm-gate.md" in text
        assert "2023.1.19_8928" in text
        assert "## Evidence caveat" in text

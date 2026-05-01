from __future__ import annotations

from pathlib import Path


REFERENCE_ROOT = Path("references") / "semantic" / "2023.1"
GATE_PATH = REFERENCE_ROOT / "semantic-builder-notebooklm-gate.md"
GLOBAL_REFERENCE_ROOT = Path("references")

FAMILIES = (
    "query",
    "object-mutation",
    "property-reference",
    "import",
    "soundbank",
    "switchcontainer",
)

GLOBAL_2022_FILES = (
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


def test_2023_semantic_references_do_not_use_global_2022_files() -> None:
    for filename in GLOBAL_2022_FILES:
        assert (GLOBAL_REFERENCE_ROOT / filename).exists(), f"missing fixture for isolation check: {filename}"

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


def test_2023_notebooklm_gate_evidence_is_persisted_locally() -> None:
    gate_text = GATE_PATH.read_text(encoding="utf-8")

    assert "- Gate status: open" in gate_text
    assert "- Notebook id: wwise-2023.1-docs" in gate_text
    assert "- Auth result: success" in gate_text
    assert "- List result: success" in gate_text
    assert "- Query result: success" in gate_text
    assert "Evidence path: references/semantic/2023.1/semantic-builder-notebooklm-gate.md" in gate_text
    assert "official URL status: `evidence-candidate`" in "\n".join(read_reference(family) for family in FAMILIES)
    assert "https://blog.audiokinetic.com/waapi-for-wwise-2023.1/" in gate_text
    assert "https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html" in gate_text
    assert "waapi_functions_index.html" in gate_text
    assert "waapi_topics_index.html" in gate_text
    assert "waql_reference.html" in gate_text

    for family in FAMILIES:
        text = read_reference(family)
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{family} missing {section}"
        assert "wwise-2023.1-docs" in text
        assert "references/semantic/2023.1/semantic-builder-notebooklm-gate.md" in text
        assert "2023.1.19_8928" in text
        assert "## Evidence caveat" in text

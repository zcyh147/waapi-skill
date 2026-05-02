from __future__ import annotations

import json
from pathlib import Path

from wwise_waapi.builders.common import BuilderFamily  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import (  # pyright: ignore[reportMissingImports]
    EXPECTED_SOURCE_NOTE_URI_INVENTORY,
    SemanticSourceNoteChecker,
    source_note_uri_inventory,
)


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = ROOT / 'references' / 'semantic' / '2021.1'
SOURCE_NOTES = ROOT / 'resources' / 'semantic' / '2021.1' / 'source_notes.json'
NOTEBOOK = 'wwise-2021.1.14-docs'
VERSION = '2021.1'
GENERATED_AT = '2026-05-02T00:00:00Z'
GATE_METADATA = {
    'status': 'open',
    'notebook_id': NOTEBOOK,
    'gate_evidence_path': 'references/semantic/2021.1/semantic-builder-notebooklm-gate.md',
    'source_only_caveat': 'source notes are not behavioral proof',
    'citation_caveat': 'NotebookLM returned numbered citation labels rather than stable source URLs',
}
FORBIDDEN_NOTEBOOK_IDS = ('wwise-2022.1-docs', 'wwise-2023.1-docs', 'wwise-2024.1-docs', 'wwise-2025.1-docs')
FORBIDDEN_PATHS = ('references/semantic/2022.1', 'references/semantic/2023.1', 'references/semantic/2024.1', 'references/semantic/2025.1', 'resources/semantic/2022.1', 'resources/semantic/2023.1', 'resources/semantic/2024.1', 'resources/semantic/2025.1')
FORBIDDEN_CLAIMS = ('NotebookLM-only text proves 2021.1 behavior', '2021.1 source notes prove behavioral support', 'manifest reflection proves 2021.1 behavior', 'full support for 2021.1', 'complete 2021.1 support')


def test_2021_docs_reject_newer_version_evidence_as_2021_behavior() -> None:
    combined = '\n'.join(path.read_text(encoding='utf-8') for path in sorted(REFERENCE_ROOT.glob('*.md'))) + '\n' + SOURCE_NOTES.read_text(encoding='utf-8')

    assert NOTEBOOK in combined
    assert VERSION in combined
    assert GENERATED_AT in combined
    assert 'source_pending' not in combined
    assert 'reflection_pending' not in combined

    for forbidden in FORBIDDEN_NOTEBOOK_IDS:
        assert forbidden not in combined
    for forbidden in FORBIDDEN_PATHS:
        assert forbidden not in combined
    for claim in FORBIDDEN_CLAIMS:
        assert claim.lower() not in combined.lower()

    assert 'source notes are not behavioral proof' in combined.lower()
    assert 'runtime builders must read local json and markdown resources' in combined.lower()


def test_2021_source_notes_match_runtime_inventory_and_allow_local_checker() -> None:
    inventory = source_note_uri_inventory(SOURCE_NOTES)

    assert inventory == EXPECTED_SOURCE_NOTE_URI_INVENTORY
    assert set(inventory) == {family.value for family in BuilderFamily}

    payload = json.loads(SOURCE_NOTES.read_text(encoding='utf-8'))
    assert payload['generated_at'] == GENERATED_AT
    assert payload['gate'] == GATE_METADATA

    checker = SemanticSourceNoteChecker(resource_path=SOURCE_NOTES, notebook_id=NOTEBOOK)
    for family in BuilderFamily:
        status = checker.check(family.value, version=VERSION)
        assert status.allowed is True
        assert status.version == VERSION
        assert status.notebook_id == NOTEBOOK
        assert status.reason == 'Semantic source note is grounded.'


def test_2021_docs_keep_source_only_caveats_and_do_not_claim_behavioral_proof() -> None:
    text = (REFERENCE_ROOT / 'semantic-builder-protocol.md').read_text(encoding='utf-8')
    text += '\n' + (REFERENCE_ROOT / 'semantic-builder-notebooklm-gate.md').read_text(encoding='utf-8')
    text += '\n' + SOURCE_NOTES.read_text(encoding='utf-8')

    assert 'behavioral proof' in text.lower() or 'not behavioral proof' in text.lower()
    assert 'copyable full urls were not directly surfaced' in text.lower()
    assert 'source_pending' not in text
    assert 'reflection_pending' not in text
    assert _runtime_package_has_no_notebooklm_calls()


def _runtime_package_has_no_notebooklm_calls() -> bool:
    forbidden_patterns = (
        'import notebooklm',
        'from notebooklm',
        'scripts/run.py',
        'ask_question.py',
        'notebooklm.google.com/notebook/',
    )
    for path in Path('wwise_waapi').glob('**/*.py'):
        text = path.read_text(encoding='utf-8')
        lowered = text.lower()
        for pattern in forbidden_patterns:
            if pattern in lowered:
                return False
    return True

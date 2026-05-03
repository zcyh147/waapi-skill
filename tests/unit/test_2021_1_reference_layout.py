from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


REFERENCE_ROOT = Path('references') / 'semantic' / '2021.1'
SOURCE_NOTES = Path('skills') / 'wwise-waapi' / 'resources' / 'semantic' / '2021.1' / 'source_notes.json'
RUNTIME_PACKAGE_ROOT = Path('skills') / 'wwise-waapi' / 'wwise_waapi'
GATE_PATH = REFERENCE_ROOT / 'semantic-builder-notebooklm-gate.md'
VERSION = '2021.1'
NOTEBOOK = 'wwise-2021.1.14-docs'
GENERATED_AT = '2026-05-02T00:00:00Z'
GATE_METADATA = {
    'status': 'open',
    'notebook_id': NOTEBOOK,
    'gate_evidence_path': 'references/semantic/2021.1/semantic-builder-notebooklm-gate.md',
    'source_only_caveat': 'source notes are not behavioral proof',
    'citation_caveat': 'NotebookLM returned numbered citation labels rather than stable source URLs',
}
FAMILIES = (
    'query',
    'object-mutation',
    'property-reference',
    'import',
    'soundbank',
    'switchcontainer',
)
EXPECTED_FILES = {
    'semantic-builder-protocol.md',
    'semantic-builder-notebooklm-gate.md',
    *(f'semantic-builder-{family}.md' for family in FAMILIES),
}
REQUIRED_SECTIONS = (
    '## Official/source URLs',
    '## Endpoint inventory',
    '## Required fields',
    '## Optional fields',
    '## Return shape',
    '## Destructive behavior',
    '## Ambiguity constraints',
    '## Unsupported cases',
    '## Cited required fields',
)
FORBIDDEN_TEXT = (
    'wwise-2022.1-docs',
    'wwise-2023.1-docs',
    'wwise-2024.1-docs',
    'wwise-2025.1-docs',
    'references/semantic-builder-',
    'references/semantic/2022.1',
    'references/semantic/2023.1',
    'references/semantic/2024.1',
    'references/semantic/2025.1',
    'resources/semantic/2022.1',
    'resources/semantic/2023.1',
    'resources/semantic/2024.1',
    'resources/semantic/2025.1',
    'source_pending',
    'reflection_pending',
)
REQUIRED_NOTE_KEYS = {
    'family',
    'status',
    'notebook_id',
    'version_target',
    'gate_evidence_path',
    'official_urls',
    'source_urls',
    'endpoints',
    'required_fields',
    'optional_fields',
    'return_shape',
    'destructive_behavior',
    'ambiguity_constraints',
    'unsupported_cases',
    'cited_required_fields',
}
EXPECTED_INVENTORY = {
    'query': ('ak.wwise.core.object.get',),
    'object-mutation': (
        'ak.wwise.core.object.create',
        'ak.wwise.core.object.set',
        'ak.wwise.core.object.delete',
        'ak.wwise.core.object.copy',
        'ak.wwise.core.object.move',
        'ak.wwise.core.object.diff',
        'ak.wwise.core.object.pasteProperties',
        'ak.wwise.core.undo.beginGroup',
        'ak.wwise.core.undo.endGroup',
        'ak.wwise.core.undo.undo',
    ),
    'property-reference': (
        'ak.wwise.core.object.getTypes',
        'ak.wwise.core.object.getPropertyAndReferenceNames',
        'ak.wwise.core.object.getPropertyInfo',
        'ak.wwise.core.object.isPropertyEnabled',
        'ak.wwise.core.object.getAttenuationCurve',
        'ak.wwise.core.object.setName',
        'ak.wwise.core.object.setNotes',
        'ak.wwise.core.object.setProperty',
        'ak.wwise.core.object.setReference',
        'ak.wwise.core.object.setRandomizer',
        'ak.wwise.core.object.setAttenuationCurve',
    ),
    'import': (
        'ak.wwise.core.audio.import',
        'ak.wwise.core.audio.importTabDelimited',
        'ak.wwise.core.audio.imported',
    ),
    'soundbank': (
        'ak.wwise.core.soundbank.getInclusions',
        'ak.wwise.core.soundbank.setInclusions',
        'ak.wwise.core.soundbank.generate',
        'ak.wwise.core.soundbank.convertExternalSources',
        'ak.wwise.core.soundbank.processDefinitionFiles',
        'ak.wwise.core.soundbank.generated',
        'ak.wwise.core.soundbank.generationDone',
    ),
    'switchcontainer': (
        'ak.wwise.core.switchContainer.getAssignments',
        'ak.wwise.core.switchContainer.addAssignment',
        'ak.wwise.core.switchContainer.removeAssignment',
        'ak.wwise.core.switchContainer.assignmentAdded',
        'ak.wwise.core.switchContainer.assignmentRemoved',
    ),
}


def read_reference(name: str) -> str:
    return (REFERENCE_ROOT / f'semantic-builder-{name}.md').read_text(encoding='utf-8')


def read_source_notes() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(SOURCE_NOTES.read_text(encoding='utf-8')))


def test_2021_1_semantic_reference_files_are_versioned_and_grounded() -> None:
    assert {path.name for path in REFERENCE_ROOT.glob('semantic-builder-*.md')} == EXPECTED_FILES

    for name in ('protocol', 'notebooklm-gate', *FAMILIES):
        text = read_reference(name)
        assert VERSION in text
        assert NOTEBOOK in text
        assert 'source_pending' not in text
        assert 'reflection_pending' not in text
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in text, f"{name} contains forbidden proof fragment: {forbidden}"

    for family in FAMILIES:
        text = read_reference(family)
        assert f"- family: `{family}`" in text
        assert '- status: `grounded`' in text
        assert '- official URL status: `evidence-candidate`' in text
        assert '## Evidence caveat' in text
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{family} missing {section}"


def test_2021_1_notebooklm_gate_is_open_and_local() -> None:
    gate_text = GATE_PATH.read_text(encoding='utf-8')

    assert '- Gate status: open' in gate_text
    assert f'- Notebook id: {NOTEBOOK}' in gate_text
    assert '- Auth result: success' in gate_text
    assert '- List result: success' in gate_text
    assert '- Query result: success' in gate_text
    assert 'source-grounded answers returned' in gate_text
    assert 'source evidence' in gate_text.lower()
    assert 'NotebookLM returned numbered citation labels' in gate_text


def test_2021_1_source_notes_are_grounded_and_local_only() -> None:
    payload = read_source_notes()

    assert payload['version'] == VERSION
    assert payload['notebook_id'] == NOTEBOOK
    assert payload['protocol'] == 'references/semantic/2021.1/semantic-builder-protocol.md'
    assert payload['generated_at'] == GENERATED_AT
    assert payload['gate'] == GATE_METADATA
    assert set(payload['notes']) == set(FAMILIES)

    for family, note in payload['notes'].items():
        assert set(note) == REQUIRED_NOTE_KEYS
        assert note['family'] == family
        assert note['status'] == 'grounded'
        assert note['notebook_id'] == NOTEBOOK
        assert note['version_target'] == VERSION
        assert note['gate_evidence_path'] == 'references/semantic/2021.1/semantic-builder-notebooklm-gate.md'
        assert note['source_urls'] == [
            'references/semantic/2021.1/semantic-builder-notebooklm-gate.md',
            f'references/semantic/2021.1/semantic-builder-{family}.md',
        ]
        assert note['endpoints'] == list(EXPECTED_INVENTORY[family])
        assert note['required_fields']
        assert note['optional_fields']
        assert note['return_shape']
        assert note['destructive_behavior']
        assert note['ambiguity_constraints']
        assert note['unsupported_cases']
        assert note['cited_required_fields']
        assert set(note['required_fields']) <= set(note['cited_required_fields'])
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in json.dumps(note, sort_keys=True)


def test_2021_1_runtime_layout_checks_have_no_notebooklm_dependency() -> None:
    from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]

    assert SOURCE_NOTES.is_file()
    assert GATE_PATH.is_file()
    assert _runtime_package_has_no_notebooklm_calls()

    checker = SemanticSourceNoteChecker(resource_path=SOURCE_NOTES, notebook_id=NOTEBOOK)
    status = checker.check('query', version=VERSION)

    assert status.allowed is True
    assert status.version == VERSION
    assert status.notebook_id == NOTEBOOK
    assert status.reason == 'Semantic source note is grounded.'


def _runtime_package_has_no_notebooklm_calls() -> bool:
    forbidden_patterns = (
        'import notebooklm',
        'from notebooklm',
        'scripts/run.py',
        'ask_question.py',
        'notebooklm.google.com/notebook/',
    )
    for path in RUNTIME_PACKAGE_ROOT.glob('**/*.py'):
        text = path.read_text(encoding='utf-8')
        lowered = text.lower()
        for pattern in forbidden_patterns:
            if pattern in lowered:
                return False
    return True

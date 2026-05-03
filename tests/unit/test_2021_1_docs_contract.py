from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from wwise_waapi.builders.common import BuilderFamily  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import (  # pyright: ignore[reportMissingImports]
    EXPECTED_SOURCE_NOTE_URI_INVENTORY,
    SemanticSourceNoteChecker,
    source_note_uri_inventory,
)


ROOT = Path(__file__).resolve().parents[2]
EVALS_JSON = ROOT / 'evals' / 'evals.json'
DOC_CONTRACT_PATHS = (
    ROOT / 'skills' / 'waapi-skill' / 'SKILL.md',
    ROOT / 'references' / 'long-run-runbook.md',
    ROOT / 'references' / 'eval-review-workflow.md',
    ROOT / 'references' / 'phase2-user-review-packet.md',
)
REFERENCE_ROOT = ROOT / 'references' / 'semantic' / '2021.1'
SOURCE_NOTES = ROOT / 'skills' / 'waapi-skill' / 'resources' / 'semantic' / '2021.1' / 'source_notes.json'
RUNTIME_PACKAGE_ROOT = ROOT / 'skills' / 'waapi-skill' / 'wwise_waapi'
COVERAGE_2021 = ROOT / 'skills' / 'waapi-skill' / 'resources' / 'capabilities' / '2021.1' / 'api-coverage.json'
SUMMARY_2021 = ROOT / 'skills' / 'waapi-skill' / 'resources' / 'capabilities' / '2021.1' / 'phase2-coverage-summary.json'
DEFERRED_2021 = ROOT / 'skills' / 'waapi-skill' / 'resources' / 'deferred' / '2021.1.json'
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
WWISE_2021_CONSOLE = '/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh'
WWISE_2021_SAMPLE_PROJECT = '/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj'
LIVE_2021_READ_ONLY_COMMAND = (
    'WWISE_VERSION=2021.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" '
    'WWISE_LIVE=1 python -m pytest tests/live/test_2021_1_live_prerequisites.py '
    'tests/live/test_2021_1_reflection_prerequisites.py tests/live/test_2021_1_object_get_matrix.py -q'
)
DESTRUCTIVE_2021_COMMAND = (
    'WWISE_VERSION=2021.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" '
    'WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2021.1 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 '
    'python -m pytest tests/destructive/test_2021_1_project_mutation_sandbox.py '
    'tests/destructive/test_2021_1_soundbank_audio_sandbox.py '
    'tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py -q'
)
PROMOTED_2021_MUTATING_APIS = {
    'ak.wwise.core.audio.import',
    'ak.wwise.core.object.create',
    'ak.wwise.core.object.delete',
    'ak.wwise.core.object.setNotes',
    'ak.wwise.core.soundbank.setInclusions',
    'ak.wwise.core.switchContainer.addAssignment',
    'ak.wwise.core.switchContainer.removeAssignment',
    'ak.wwise.core.undo.beginGroup',
    'ak.wwise.core.undo.endGroup',
}
FORBIDDEN_2021_POSITIVE_CLAIMS = (
    'all 2021.1 APIs are live-tested',
    'all 2021 APIs are live-tested',
    'all 2021.1 APIs are behavior-tested',
    'all 2021 APIs are behavior-tested',
    'all 2021.1 APIs are fully behavior-tested',
    'full 2021.1 WAAPI behavioral coverage',
    '2021.1 full WAAPI coverage',
    '2021.1 full WAAPI behavioral coverage',
    'manifest reflection proves 2021.1 behavior',
    'manifest reflection is 2021.1 live evidence',
    'NotebookLM-only text proves 2021.1 behavior',
    '2021.1 source notes prove runtime behavior',
    '2021.1 source notes prove behavioral support',
)


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


def test_2021_docs_and_evals_reject_no_overclaim_phrases() -> None:
    combined = _combined_docs_and_evals_text().lower()

    for claim in FORBIDDEN_2021_POSITIVE_CLAIMS:
        assert claim.lower() not in combined

    for phrase in (
        'fully behavior-tested 2021.1',
        '2021.1 APIs are fully behavior-tested',
        '2021.1 support is complete',
        '2021.1 manifest reflection proves live behavior',
        'all APIs live-tested for 2021.1',
    ):
        assert phrase.lower() not in combined


def test_2021_docs_include_exact_counts_paths_commands_and_limited_claims() -> None:
    combined = '\n'.join(path.read_text(encoding='utf-8') for path in DOC_CONTRACT_PATHS)
    counts = _resource_counts()

    assert counts == {
        'coverage_total': 126,
        'summary_total': 99,
        'deferred_registry_total': 89,
        'coverage_status': {'excluded': 46, 'deferred': 70, 'sandbox-mutating-tested': 9, 'live-tested': 1},
        'coverage_item_type': {'function': 99, 'topic': 27},
        'summary_status': {'excluded': 46, 'deferred': 43, 'sandbox-mutating-tested': 9, 'live-tested': 1},
        'summary_item_type': {'function': 99},
        'deferred_registry_status': {'excluded': 46, 'deferred': 43},
        'deferred_registry_item_type': {'function': 89},
    }

    assert WWISE_2021_CONSOLE in combined
    assert WWISE_2021_SAMPLE_PROJECT in combined
    assert 'python -m pytest -q' in combined
    assert _squash_command(LIVE_2021_READ_ONLY_COMMAND) in _squash_command(combined)
    assert _squash_command(DESTRUCTIVE_2021_COMMAND) in _squash_command(combined)

    for phrase in (
        '99 functions',
        'topic inventory is now present',
        'topic inventory rows are inventory/substitute accounting only until fresh active live topic evidence exists',
        'supported 0',
        'behavioral 0',
        'deferred 43',
        'excluded 46',
        'live-tested 1',
        'sandbox-mutating-tested 9',
        'unknown 0',
        'one live read-only URI',
        'nine copied-sandbox mutating URIs',
        'installed SampleProject is immutable source only',
        'destructive tests must only mutate copied sandboxes',
        'NotebookLM and source notes are source-only',
        'not runtime proof',
        'resources/manifest/2021.1/',
        'resources/semantic/2021.1/source_notes.json',
        'resources/capabilities/2021.1/',
        'resources/deferred/2021.1.json',
        'resources/waql/2021.1/',
        'references/semantic/2021.1/',
        'ak.wwise.core.object.get',
        'ak.wwise.core.soundbank.getInclusions',
        'ak.wwise.core.switchContainer.getAssignments',
        'remain unpromoted',
    ):
        assert phrase in combined

    for api in PROMOTED_2021_MUTATING_APIS:
        assert api in combined


def test_2021_eval_examples_are_version_scoped_when_added() -> None:
    payload = json.loads(EVALS_JSON.read_text(encoding='utf-8'))
    entries = [entry for entry in payload['evals'] if entry['id'].startswith('2021-')]

    assert {entry['id'] for entry in entries} == {
        '2021-parity-review-version-scoped-summary',
        '2021-live-and-destructive-command-review',
    }

    for entry in entries:
        serialized = json.dumps(entry, sort_keys=True)
        lowered = serialized.lower()
        assert '2021.1' in serialized, entry['id']
        assert any('2021.1' in file_path for file_path in entry['files']), entry['id']
        assert 'resources/manifest/2022.1' not in serialized, entry['id']
        assert 'resources/manifest/2023.1' not in serialized, entry['id']
        assert 'resources/manifest/2024.1' not in serialized, entry['id']
        assert 'resources/manifest/2025.1' not in serialized, entry['id']
        assert 'wwise-2022.1-docs proves 2021.1' not in serialized, entry['id']
        for claim in FORBIDDEN_2021_POSITIVE_CLAIMS:
            assert claim.lower() not in lowered, entry['id']


def _combined_docs_and_evals_text() -> str:
    parts = [path.read_text(encoding='utf-8') for path in DOC_CONTRACT_PATHS]
    parts.extend(path.read_text(encoding='utf-8') for path in sorted(REFERENCE_ROOT.glob('*.md')))
    parts.append(SOURCE_NOTES.read_text(encoding='utf-8'))
    parts.append(EVALS_JSON.read_text(encoding='utf-8'))
    return '\n'.join(parts)


def _resource_counts() -> dict[str, Any]:
    coverage = json.loads(COVERAGE_2021.read_text(encoding='utf-8'))['coverage']
    summary = json.loads(SUMMARY_2021.read_text(encoding='utf-8'))['entries']
    deferred = json.loads(DEFERRED_2021.read_text(encoding='utf-8'))['deferred']
    return {
        'coverage_total': len(coverage),
        'summary_total': len(summary),
        'deferred_registry_total': len(deferred),
        'coverage_status': dict(Counter(entry['coverage_status'] for entry in coverage)),
        'coverage_item_type': dict(Counter(entry['item_type'] for entry in coverage)),
        'summary_status': dict(Counter(entry['coverage_status'] for entry in summary)),
        'summary_item_type': dict(Counter(entry['item_type'] for entry in summary)),
        'deferred_registry_status': dict(Counter(entry['coverage_status'] for entry in deferred)),
        'deferred_registry_item_type': dict(Counter(entry['item_type'] for entry in deferred)),
    }


def _squash_command(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\\\n', ' ')).strip()


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

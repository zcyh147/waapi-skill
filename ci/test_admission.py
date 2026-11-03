"""Require an explicit Program or Non-live disposition for new unit test files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

if __package__:
    from .run_program_tests import load_program_nodes
else:
    from run_program_tests import load_program_nodes


_BASELINE_COMMIT = '1f2b19385bd955117d7e2851bb1e76159dc0aa61'
_BASELINE_DIGEST = '8ef491ebfe2d125b23bfae44f206821c7d99a1ca3bcd10bbe077594412c9c297'


def check_test_admission(root: Path) -> None:
    """Validate classifications without changing the fixed Program selection."""
    nodes = load_program_nodes(root / 'ci/program-test-nodes.txt', repo_root=root)
    program = {node.split('::', 1)[0] for node in nodes}
    document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text(encoding='utf-8'))
    if not isinstance(document, dict) or set(document) != {
        'schema', 'baseline_commit', 'baseline_nonlive_reason',
        'baseline_nonlive_files', 'nonlive',
    } or document['schema'] != 'waapi.test-admission/v1':
        raise ValueError('invalid unit test admission document')
    baseline = document['baseline_nonlive_files']
    if (document['baseline_commit'] != _BASELINE_COMMIT
            or not isinstance(baseline, list)
            or not all(isinstance(path, str) for path in baseline)
            or hashlib.sha256(json.dumps(baseline, separators=(',', ':')).encode()).hexdigest()
            != _BASELINE_DIGEST):
        raise ValueError('grandfathered Non-live baseline changed; new files require an explicit disposition')
    if not isinstance(document['baseline_nonlive_reason'], str) or not document['baseline_nonlive_reason'].strip():
        raise ValueError('grandfathered Non-live baseline requires its scope reason')
    nonlive = document['nonlive']
    if not isinstance(nonlive, dict) or any(
        not isinstance(reason, str) or not reason.strip() for reason in nonlive.values()
    ):
        raise ValueError('each explicit Non-live disposition requires a nonempty reason')
    if any(reason.strip() == document['baseline_nonlive_reason'].strip()
           for reason in nonlive.values()):
        raise ValueError('new Non-live files cannot borrow the grandfathered reason')
    if set(baseline) & set(nonlive):
        raise ValueError('explicit Non-live disposition duplicates a grandfathered file')
    # A grandfathered file may be promoted by the canonical roster. Its immutable
    # baseline membership remains history, not a second current disposition.
    declared = set(baseline) | set(nonlive)
    actual = {path.relative_to(root).as_posix()
              for path in (root / 'tests/unit').glob('test_*.py') if path.is_file()}
    stale = set(nonlive) - actual
    if stale:
        raise ValueError('stale Non-live disposition: ' + ', '.join(sorted(stale)))
    overlap = program & set(nonlive)
    if overlap:
        raise ValueError('both Program and explicit Non-live disposition: ' + ', '.join(sorted(overlap)))
    unclassified = actual - program - declared
    if unclassified:
        raise ValueError('unclassified unit test files; add Program selectors or Non-live reasons: '
                         + ', '.join(sorted(unclassified)))

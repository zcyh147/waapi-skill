"""Fixed developer pytest selection; no campaign or semantic execution harness."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

if __package__:
    from .run_program_tests import validate_program_pytest_args
else:
    from run_program_tests import validate_program_pytest_args

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / 'ci/notice-fast-test-nodes.txt'


def load_notice_fast_nodes(manifest: Path, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Accept only existing, unique fake semantic regression files in manifest order."""
    root = (repo_root / 'tests/semantic').resolve(strict=True)
    nodes = []
    for line in manifest.read_text(encoding='utf-8-sig').splitlines():
        if not line or line.startswith('#'):
            continue
        test_path = line.split('::', 1)[0]
        if (not test_path.startswith('tests/semantic/test_')
                or not test_path.endswith('.py') or '\\' in line
                or any(character.isspace() for character in line)
                or any(part in {'', '.', '..'} for part in test_path.split('/'))):
            raise ValueError(f'notice-fast manifest requires a semantic regression file: {line}')
        try:
            path = (repo_root / test_path).resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError(f'notice-fast manifest names missing or escaping file: {line}') from exc
        if not path.is_file() or line in nodes:
            raise ValueError(f'notice-fast manifest has duplicate or non-file entry: {line}')
        nodes.append(line)
    if not nodes:
        raise ValueError('notice-fast manifest contains no pytest nodes')
    return nodes


def main(argv: Sequence[str] | None = None) -> int:
    try:
        nodes = load_notice_fast_nodes(MANIFEST)
        # Reuse the existing closed pytest-flag contract; paths, marker/plugin
        # overrides and options capable of widening collection stay prohibited.
        arguments = validate_program_pytest_args(sys.argv[1:] if argv is None else argv)
    except (OSError, ValueError) as exc:
        print(f'notice-fast selection error: {exc}', file=sys.stderr)
        return 2
    print(f'notice-fast manifest: {MANIFEST} ({len(nodes)} manifest entries)', flush=True)
    import pytest
    return int(pytest.main([
        *nodes, '-m', 'not live and not destructive',
        '--ignore=tests/live', '--ignore=tests/destructive', *arguments,
    ]))


if __name__ == '__main__':
    raise SystemExit(main())

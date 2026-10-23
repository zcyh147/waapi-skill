"""Write the finite source-only #177 assessment without touching the inventory."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from tests.support.condition_source_resolution import reconcile_sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    report = reconcile_sources(root)
    frozen = json.loads(gzip.decompress((root / 'tests/fixtures/metadata-conditions/self-scalar-program-review.json.gz').read_bytes()))
    expected = {identity: policy['native_shape_sha256'] for identity, policy in frozen['requirements']['branches'].items()}
    members = [(m['id'], m['shape_sha256']) for row in report['occurrences'] for m in row['members']]
    if len(members) != len(dict(members)) or dict(members) != expected:
        raise ValueError('Original exact condition member/shape roster changed')
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress(raw, mtime=0) if args.output.suffix == '.gz' else raw)
    print(json.dumps({'assessment': 'source_only_no_coverage_credit', 'members': len(members),
                      'occurrences': len(report['occurrences']), 'output': str(args.output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

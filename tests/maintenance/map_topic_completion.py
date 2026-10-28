"""Export finite Topic mappings into the existing attachment/completion path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage
from tests.support.topic_completion_mapping import topic_component, export_mapping, program_anchors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--program-review', type=Path)
    args = parser.parse_args(argv)
    inventory = topic_component(audit.ROOT)
    anchors = (program_anchors(audit.ROOT, inventory, args.output_directory, args.program_review)
               if args.program_review else None)
    exported = export_mapping(audit.ROOT, args.output_directory, inventory=inventory, anchors=anchors)
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], exported['requirements'])
    result = evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=exported['requirements'])
    report = {'assessment_scope': 'all pinned Topic closed wrappers only; no native delivery or global completion credit',
        'summary': exported['summary'], 'completion': result['completion'],
        'evidence_outcomes': {category: sorted({row['evidence_results'][category]['outcome']
            for row in result['obligations'] if category in row['evidence_results']}) for category in ('program', 'native')}}
    (args.output_directory / 'assessment.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))
    return 0 if result['completion']['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

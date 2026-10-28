"""Export the finite #192 cohort through existing completion readers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage
from tests.support.history_completion_mapping import history_component, history_program_anchors, export_history_mapping


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--ordinary-run', type=Path)
    args = parser.parse_args(argv)
    inventory = history_component(audit.ROOT)
    anchors = history_program_anchors(audit.ROOT, inventory, args.output_directory, args.ordinary_run) if args.ordinary_run else None
    exported = export_history_mapping(audit.ROOT, args.output_directory, inventory=inventory, anchors=anchors)
    # Consume the actual persisted parts, not the exporter's in-memory document.
    requirements = audit.load(args.output_directory / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], requirements)
    result = evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    report = {'assessment_scope': 'exact #192 correspondence and representative CODE only; accepted provider/compound/history limits and historical native facts separately attributed; no global completion',
        'summary': exported['summary'], 'completion': result['completion'],
        'evidence_outcomes': sorted({row['evidence_results']['program']['outcome'] for row in result['obligations']})}
    (args.output_directory / 'assessment.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))
    return 0 if result['completion']['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

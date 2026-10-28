"""Export exact #190/#193 lightweight host mappings through ordinary readers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage
from tests.support.host_completion_mapping import host_component, program_anchors, export_mapping


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--ordinary-run', type=Path)
    args = parser.parse_args(argv)
    inventory = host_component(audit.ROOT)
    anchors = program_anchors(audit.ROOT, inventory, args.output_directory, args.ordinary_run) if args.ordinary_run else None
    exported = export_mapping(audit.ROOT, args.output_directory, inventory=inventory, anchors=anchors)
    requirements = audit.load(exported['requirements_path'])
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], requirements)
    result = evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    report = {'assessment_scope': 'exact #190/#193 lightweight correspondence and aggregate CODE only; no host/native effect or global completion',
        'summary': exported['summary'], 'completion': result['completion'],
        'evidence_outcomes': sorted({row['evidence_results']['program']['outcome'] for row in result['obligations'] if 'program' in row['evidence_results']})}
    (args.output_directory / 'assessment.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))
    return 0 if result['completion']['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

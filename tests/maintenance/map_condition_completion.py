"""Export exact #177 source-definition assignments through the existing reader."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from tests.maintenance.branch_coverage_audit import digest
from tests.maintenance.branch_audit_completion import evaluate_coverage
from tests.support.condition_completion_mapping import export_mapping, validate_mapping_attachment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--operation-mode', choices=('existing-object', 'new-object'), default='existing-object')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    exported = export_mapping(root, args.output_directory, operation_mode=args.operation_mode)
    context = validate_mapping_attachment(exported['attachment'], args.output_directory, root)
    identities = set(context['branches'])
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1',
        'branches': {i: exported['requirements']['branches'][i] for i in identities}}
    # This is the existing reader over its exact installed-definition subset.
    # Parent/non-installed obligations are preserved, never inferred complete.
    inventory = {'routes': [], 'native_coverage': {'candidate_sha256': digest(context['review']['current_sources']),
        'catalogs': {}, 'routes': [], 'obligations': list(context['branches'].values())}}
    result = evaluate_coverage(root, inventory, exported['bindings'], digest=digest,
        evidence_base=args.output_directory, requirements_document=requirements)
    result['assessment_scope'] = 'exact ' + args.operation_mode + ' installed source definitions only; constructor dependencies and non-installed facts are not inferred complete'
    (args.output_directory / 'assessment.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    (args.output_directory / 'mapping.json.gz').write_bytes(gzip.compress(
        (args.output_directory / 'mapping.json').read_bytes(), mtime=0))
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': [],
        'condition_definition_attachments': [exported['attachment']]}
    (args.output_directory / 'evidence-index.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'assessment_scope': result['assessment_scope'], 'completion': result['completion'],
        'output': str(args.output_directory)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

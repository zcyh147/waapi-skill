"""Export installed class/mode correspondence through the ordinary reader."""
import argparse
import json
from pathlib import Path

from tests.maintenance.branch_coverage_audit import digest
from tests.maintenance.branch_audit_completion import evaluate_coverage
from tests.support.applicability_completion_mapping import export_mapping


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    exported = export_mapping(root, args.output_directory)
    inventory = {'routes': [], 'native_coverage': {'candidate_sha256': digest(exported['mapping']),
        'catalogs': {}, 'routes': [], 'obligations': exported['branches']}}
    requirements = {'contract': exported['requirements']['contract'],
        'branches': {r['id']: exported['requirements']['branches'][r['id']] for r in exported['branches']}}
    assessment = evaluate_coverage(root, inventory, exported['bindings'], digest=digest,
        evidence_base=args.output_directory, requirements_document=requirements)
    assessment['assessment_scope'] = 'installed source class/mode applicability only; no per-class execution claim'
    path = args.output_directory / 'assessment.json'
    if path.exists():
        raise ValueError('Installed applicability publication is immutable')
    path.write_text(json.dumps(assessment, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'assessment_scope': assessment['assessment_scope'], 'completion': assessment['completion']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

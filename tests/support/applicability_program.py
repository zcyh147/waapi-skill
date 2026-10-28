"""Sealed selected public code mechanisms; no native recipient credit."""
import ast
import hashlib
from pathlib import Path
import re


def program_sources(root):
    selected = {p.relative_to(root).as_posix() for directory in ('scripts', 'wwise_waapi', 'resources')
        for p in (root / 'skills/waapi-skill' / directory).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py', '.json'}}
    selected.update({'tests/support/applicability_program.py', 'tests/support/applicability_completion_mapping.py',
        'tests/support/exact_evidence_finalization.py', 'docs/branch-coverage-condition-sources.json',
        'docs/plans/full-waapi-coverage/SPEC.md',
        'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz',
        'tests/fixtures/metadata-conditions/applicability-sdk-sources.json.gz',
        'tests/fixtures/metadata-conditions/applicability-current-program.json.gz',
        'tests/fixtures/metadata-conditions/applicability-current-program-r2.json.gz',
        *['tests/_org/' + v + '/SampleProject.wproj' for v in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')]})
    pending = ['tests/unit/test_applicability_public_program.py']
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        for node in ast.walk(ast.parse((root / name).read_bytes())):
            if isinstance(node, ast.ImportFrom) and node.module:
                dependency = (node.module.replace('.', '/') + '.py' if node.module.startswith('tests.')
                    else 'tests/unit/' + node.module + '.py' if node.module.startswith('test_') else None)
                if dependency and (root / dependency).is_file():
                    pending.append(dependency)
    result = {}
    for name in sorted(selected):
        raw = (root / name).read_bytes()
        if name == 'tests/support/applicability_completion_mapping.py':
            # Only the digest of this very record is normalized; all executable
            # reader/classification logic and every other source pin stay sealed.
            raw, count = re.subn(rb"(?m)^PROOF_SHA256 = '[^']*'$", b"PROOF_SHA256 = '<self-record-digest>'", raw)
            if count != 1:
                raise ValueError('One exact applicability proof digest declaration required')
        result[name] = hashlib.sha256(raw).hexdigest()
    return result

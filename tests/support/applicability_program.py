"""Sealed selected public runtime mechanisms; no native recipient credit.

The producer imports only PREVIOUS_PROOF data from the mapper. It does not call
installed_obligations, the accounting digest or portable _read to select inputs.
That classifier/consumer runs separately against current sources in the ordinary
portable-join tests; this historical capture does not certify its execution.
The mapper file is retained as an extra sealed source, not an executed reader.
"""
import ast
import hashlib
from pathlib import Path
import re


def program_sources(root):
    selected = {p.relative_to(root).as_posix() for directory in ('scripts', 'wwise_waapi', 'resources')
        for p in (root / 'skills/waapi-skill' / directory).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py', '.json'}}
    # Playlist applicability also depends on exact retained SDK/native bytes,
    # not merely the JSON descriptors or imported compiler implementation.
    selected.update(p.relative_to(root).as_posix() for version in ('2023.1', '2024.1', '2025.1')
        for p in (root / 'skills/waapi-skill/references/semantic' / version / 'music-playlist-sources').rglob('*')
        if p.is_file() and p.suffix in {'.html', '.json'})
    selected.update({'tests/support/applicability_program.py', 'tests/support/applicability_completion_mapping.py',
        'tests/support/exact_evidence_finalization.py', 'docs/branch-coverage-condition-sources.json',
        'docs/plans/full-waapi-coverage/SPEC.md',
        'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz',
        'tests/fixtures/metadata-conditions/applicability-sdk-sources.json.gz',
        'tests/fixtures/metadata-conditions/applicability-current-program.json.gz',
        'tests/fixtures/metadata-conditions/applicability-current-program-r2.json.gz',
        'tests/fixtures/metadata-conditions/applicability-current-program-r3.json.gz',
        *['tests/_org/' + v + '/SampleProject.wproj' for v in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')]})
    pending = ['tests/unit/test_applicability_public_program.py', 'tests/unit/test_music_playlist_gateway.py',
        'tests/conftest.py']
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        for node in ast.walk(ast.parse((root / name).read_bytes())):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                # Both `from tests.unit import helper` and imports of one
                # concrete module execute helper code in the selected flows.
                modules = [node.module, *[node.module + '.' + alias.name for alias in node.names]]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                dependency = (module.replace('.', '/') + '.py' if module.startswith('tests.')
                    else 'tests/unit/' + module + '.py' if module.startswith('test_') else None)
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

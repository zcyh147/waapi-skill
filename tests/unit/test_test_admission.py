from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / 'repository'
    (root / 'ci').mkdir(parents=True)
    (root / 'tests/unit').mkdir(parents=True)
    for name in ('preflight.py', 'run_program_tests.py', 'test_admission.py'):
        source = ROOT / 'ci' / name
        if source.exists():
            shutil.copyfile(source, root / 'ci' / name)
    (root / 'tests/unit/test_selected.py').write_text('def test_selected(): pass\n')
    (root / 'ci/program-test-nodes.txt').write_text('tests/unit/test_selected.py\n')
    # The existing preflight's child dispatch is the external boundary here.
    # Admission, manifest parsing and filesystem inputs remain real.
    (root / 'ci/test_driver.py').write_text(
        'import json,sys\nfrom pathlib import Path\n'
        'Path("dispatch.json").write_text(json.dumps(sys.argv[1:]))\n'
        'raise SystemExit(7)\n'
    )
    dispositions = json.loads((ROOT / 'ci/nonlive-test-dispositions.json').read_text())
    for path in [*dispositions['baseline_nonlive_files'], *dispositions['nonlive']]:
        (root / path).write_text('')
    (root / 'ci/nonlive-test-dispositions.json').write_text(json.dumps(dispositions))
    return root


def _preflight(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(root / 'ci/preflight.py')],
                          cwd=root, text=True, capture_output=True, check=False)


def test_preflight_rejects_a_new_unclassified_unit_file_before_dispatch(tmp_path):
    root = _repository(tmp_path)
    (root / 'tests/unit/test_new_unclassified.py').write_text('def test_new(): pass\n')
    result = _preflight(root)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'unclassified' in result.stderr
    assert 'tests/unit/test_new_unclassified.py' in result.stderr
    assert not (root / 'dispatch.json').exists()


def test_grandfathered_baseline_is_history_not_a_requirement_to_keep_deleted_files(tmp_path):
    root = _repository(tmp_path)
    document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text())
    (root / document['baseline_nonlive_files'][0]).unlink()
    result = _preflight(root)
    assert result.returncode == 7, result.stdout + result.stderr
    assert (root / 'dispatch.json').is_file()


def _write_dispositions(root: Path, document: dict) -> None:
    (root / 'ci/nonlive-test-dispositions.json').write_text(json.dumps(document))


@pytest.mark.parametrize('choice', ['program', 'nonlive'])
def test_new_file_with_an_explicit_choice_preserves_child_selection_and_exit(tmp_path, choice):
    root = _repository(tmp_path)
    added = 'tests/unit/test_added.py'
    (root / added).write_text('def test_added(): pass\n')
    if choice == 'program':
        with (root / 'ci/program-test-nodes.txt').open('a') as stream:
            stream.write(added + '::test_added\n')
    else:
        document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text())
        document['nonlive'][added] = 'Exercises developer tooling outside the fixed Program selection.'
        _write_dispositions(root, document)
    result = _preflight(root)
    assert result.returncode == 7, result.stdout + result.stderr
    arguments = json.loads((root / 'dispatch.json').read_text())
    assert arguments[:3] == ['--mode', 'nonlive', '--']
    assert 'tests/unit/test_public_route_program_matrix.py' in arguments
    assert arguments[-2:] == ['-q', '-ra']


def test_count_preserving_program_substitution_cannot_hide_an_unclassified_file(tmp_path):
    root = _repository(tmp_path)
    (root / 'tests/unit/test_replacement.py').write_text('def test_replacement(): pass\n')
    # One selector before and after: a count-only check cannot detect this omission.
    (root / 'ci/program-test-nodes.txt').write_text('tests/unit/test_replacement.py\n')
    result = _preflight(root)
    assert result.returncode == 2
    assert 'unclassified' in result.stderr and 'tests/unit/test_selected.py' in result.stderr
    assert not (root / 'dispatch.json').exists()


@pytest.mark.parametrize('damage', ['missing-file', 'empty-reason', 'also-program', 'borrowed-baseline-reason'])
def test_explicit_nonlive_disposition_must_be_current_and_unambiguous(tmp_path, damage):
    root = _repository(tmp_path)
    added = 'tests/unit/test_nonlive_choice.py'
    (root / added).write_text('')
    document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text())
    document['nonlive'][added] = 'Kept in Non-live for this explicit developer-tooling scope.'
    if damage == 'missing-file':
        (root / added).unlink()
    elif damage == 'empty-reason':
        document['nonlive'][added] = '   '
    elif damage == 'borrowed-baseline-reason':
        document['nonlive'][added] = document['baseline_nonlive_reason']
    else:
        with (root / 'ci/program-test-nodes.txt').open('a') as stream:
            stream.write(added + '\n')
    _write_dispositions(root, document)
    result = _preflight(root)
    assert result.returncode == 2, result.stdout + result.stderr
    assert {'missing-file': 'stale', 'empty-reason': 'reason',
            'also-program': 'both Program', 'borrowed-baseline-reason': 'grandfathered reason'}[damage] in result.stderr
    assert not (root / 'dispatch.json').exists()


def test_new_file_cannot_borrow_the_grandfathered_baseline(tmp_path):
    root = _repository(tmp_path)
    added = 'tests/unit/test_future.py'
    (root / added).write_text('')
    document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text())
    document['baseline_nonlive_files'].append(added)
    _write_dispositions(root, document)
    result = _preflight(root)
    assert result.returncode == 2 and 'baseline changed' in result.stderr
    assert not (root / 'dispatch.json').exists()


def test_grandfathered_file_can_be_explicitly_promoted_into_program(tmp_path):
    root = _repository(tmp_path)
    document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text())
    promoted = document['baseline_nonlive_files'][0]
    with (root / 'ci/program-test-nodes.txt').open('a') as stream:
        stream.write(promoted + '\n')
    result = _preflight(root)
    assert result.returncode == 7, result.stdout + result.stderr
    assert (root / 'dispatch.json').is_file()


def test_same_count_renamed_baseline_file_requires_a_new_disposition(tmp_path):
    root = _repository(tmp_path)
    document = json.loads((root / 'ci/nonlive-test-dispositions.json').read_text())
    original = document['baseline_nonlive_files'][0]
    renamed = 'tests/unit/test_replacement_nonlive.py'
    (root / original).rename(root / renamed)
    result = _preflight(root)
    assert result.returncode == 2 and 'unclassified' in result.stderr
    assert renamed in result.stderr
    assert not (root / 'dispatch.json').exists()

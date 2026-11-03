"""One closed project-local custom-property fixture, before native startup only."""
import json
import os
from pathlib import Path

from tests.destructive.support.source_copy_fixture import read_file, sha, xml
from tests.semantic.support.codex_project_prelaunch_v3 import _require_owned_path, _reject_symlink_chain

PROFILE = '2025-project-local-status-query/v1'
TOKEN = 'MyCompany:Status'
SOUND = '{0030BF58-90C3-428B-B940-44CC1C5A51B5}'
WWU = Path('Containers/Footsteps.wwu')
WWU_SHA = '0b5c0a9c8b195d4c2c95d5ace81836711b3978533f7c2ec17cb17a7782700270'
TARGET = Path('Add-ons/Properties/waapi-skill-query-status.wcustomproperties')
DEFINITION_SHA = 'ddff67f083dbaa7c3efab9339c98e325c8a69d41926e58df7a872a55464fab8c'
SOURCE_SHA = '44fcb58e3488a9fcdd63e2b491cfd943ed17b268504956bfb4c17ce16a1f82b9'
FIXTURES = Path(__file__).parents[2] / 'fixtures/query-custom-property'


def official_sources():
    raw = read_file(FIXTURES / 'source.json', 16384)
    assert sha(raw) == SOURCE_SHA, 'Custom-property source evidence drift'
    source = json.loads(raw)
    assert source['build'] == '2025.1.7.9143' and source['native_acceptance'] is False
    for page in source['pages'].values():
        for section in page['sections']:
            assert sha(section['html'].encode()) == section['sha256']
    definition = read_file(FIXTURES / 'status.wcustomproperties', 2048)
    assert sha(definition) == source['definition_sha256'] == DEFINITION_SHA, 'Definition drift'
    return source, definition


def source_sound_frame(sandbox):
    """Complete original WWU proof; no assignment or value RETURN is invented."""
    raw = read_file(Path(sandbox.sandbox_path) / WWU)
    assert sha(raw) == WWU_SHA, 'Custom-property fixture WWU preimage drift'
    tree = xml(raw)
    matches = [node for node in tree.iter('Sound') if node.get('ID') == SOUND]
    assert len(matches) == 1, 'Missing or duplicate fixture Sound'
    assert not any(node.get('Name') == TOKEN for node in tree.iter()), 'Custom property already assigned in WWU'
    node, = matches
    assert node.get('Name') == 'Footstep_Crouching_Concrete_01'
    return {'relative_path': WWU.as_posix(), 'sha256': sha(raw), 'bytes': len(raw),
        'sound_id': SOUND, 'sound_name': node.get('Name'), 'complete_wwu_nonassignment': True}


def prepare_namespaced_query_fixture(sandbox, *, owned_root, io_root):
    owned, root, io = Path(owned_root), Path(sandbox.sandbox_path), Path(io_root)
    source = Path(sandbox.source_root).resolve(strict=True)
    for path in (owned, root, io, Path(sandbox.sandbox_project)):
        assert path.is_absolute() and path.resolve(strict=True) == path, 'Fixture path is not canonical'
        _reject_symlink_chain(path, owned_input=owned, label='Custom-property fixture')
        if path != owned: _require_owned_path(path, owned_root=owned, label='Custom-property fixture')
    assert not root.is_relative_to(source) and not source.is_relative_to(root), 'Cannot modify immutable source'
    assert not io.is_relative_to(root) and not root.is_relative_to(io), 'Report must be outside project tree'
    assert Path(sandbox.sandbox_project).parent == root, 'Unexpected project location'
    report_path = io / 'namespaced-query-prelaunch.json'
    assert not os.path.lexists(report_path), 'Never replace earlier fixture evidence'
    sources, definition = official_sources()
    before = source_sound_frame(sandbox)
    original_wwu = read_file(source / WWU)
    assert sha(original_wwu) == WWU_SHA, 'Immutable source differs'
    project_before = read_file(sandbox.sandbox_project)
    target = root / TARGET
    assert not os.path.lexists(target), 'Never replace an existing custom-property definition'
    for relative in ('Add-ons', 'Add-ons/Properties'):
        directory = root / relative
        if not os.path.lexists(directory): directory.mkdir()
        _reject_symlink_chain(directory, owned_input=owned, label='Custom-property definition')
        assert directory.is_dir()
    with os.scandir(target.parent) as entries:
        assert next(entries, None) is None, 'Existing project-local property definitions require separate review'
    # Exclusive, no-follow creation; never truncate a preexisting file/inode.
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'wb') as stream:
        stream.write(definition)
    _reject_symlink_chain(target, owned_input=owned, label='Custom-property definition')
    assert read_file(target, 2048) == definition
    assert source_sound_frame(sandbox) == before
    assert read_file(source / WWU) == original_wwu and read_file(sandbox.sandbox_project) == project_before
    report = {'profile': PROFILE, 'native_acceptance': False, 'coverage_credit': 'none',
        'relative_path': TARGET.as_posix(), 'definition_sha256': DEFINITION_SHA,
        'definition_bytes': len(definition), 'source': sources, 'source_wwu': before,
        'loading': 'project-local Add-ons/Properties at project-open; no global installation',
        'expected_value_authority': 'official declared default0 plus fresh live metadata and complete WWU nonassignment; not custom RETURN'}
    with report_path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2); stream.write('\n')
    return report

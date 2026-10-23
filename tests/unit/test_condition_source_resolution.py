"""Finite installed-source accounting retains scope without inventing live facts."""
from pathlib import Path

import pytest

from tests.support.condition_source_resolution import reconcile_sources

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def report():
    return reconcile_sources(ROOT)


def test_inherited_diffraction_controller_resolves_in_the_actual_sound_consumer(report):
    rows = [r for r in report['occurrences'] if r['version'] == '2025.1'
            and r['source_pointer'] == 'PluginModule/ObjectBase[EnableDiffraction]/Properties/Property[EnableDiffraction]/Dependencies']
    assert len(rows) == 1
    sound = next(c for c in rows[0]['consumers'] if c['catalog']['name'] == 'Sound')
    assert sound['catalog'] == {'classId': 65552, 'name': 'Sound', 'type': 'WObject'}
    assert sound['controller']['name'] == '3DPosition'
    assert sound['controller']['type'] == 'int16'
    assert sound['controller']['source_pointer'] == 'PluginModule/ObjectBase[ListenerRelativePositioning]/Properties/Property[3DPosition]'
    assert sound['controller']['source_only'] is True
    assert rows[0]['native_instance_effect'] == 'unobserved'
    assert rows[0]['coverage_credit'] == 'none'


def test_inner_batch_settings_keep_a_control_owner_without_claiming_object_mutability(report):
    row = next(r for r in report['occurrences'] if r['version'] == '2025.1'
               and '/InnerType[BatchRenameSettings]/Properties/Property[ReplaceFindWhat]/' in r['source_pointer'])
    assert row['scope'] == 'inner-tool-record'
    assert row['consumers'][0]['catalog'] == {'classId': 65011712, 'name': 'BatchRenameSettings', 'type': 'Inner'}
    assert row['control_dependencies'] == [{'owner_issue': 190, 'parent_issue': 174,
        'route': 'function|ak.wwise.ui.commands.execute',
        'missing_fact': 'Addressable Batch Rename settings and the supported control/verification path; ShowBatchRename is only a retained command snapshot, not a setter or runtime allowlist.'}]
    assert row['condition_owner_issue'] == 177
    assert row['native_instance_effect'] == 'unobserved'
    assert row['coverage_credit'] == 'none'


def test_fieldless_group_conditions_retain_consumers_without_inventing_fields(report):
    rows = [r for r in report['occurrences'] if r['version'] == '2025.1'
            and r['source_pointer'] == 'PluginModule/ObjectBase[PositioningType_AudioNode]/Dependencies']
    assert len(rows) == 1
    row = rows[0]
    assert row['scope'] == 'inherited-group'
    assert row['source_fields'] == []
    assert row['resolution'] == 'declared_group_without_selected_field'
    assert row['field'] is None
    assert any(c['catalog']['name'] == 'Sound' for c in row['consumers'])
    assert row['coverage_credit'] == 'none'


def test_music_loop_missing_controller_is_not_borrowed_from_an_unrelated_loop_base(report):
    rows = [r for r in report['occurrences'] if '/WwiseObject[MusicPlaylistItem]/Properties/Property[LoopCount]/' in r['source_pointer']]
    assert len(rows) == 5
    for row in rows:
        assert len(row['consumers']) == 1
        assert row['consumers'][0]['controller']['state'] == 'missing_source_declaration'
        assert row['consumers'][0]['controller']['name'] == 'IsLoopingInfinite'
        assert row['resolution'] == 'controller_source_unresolved'
        assert {d['owner_issue'] for d in row['control_dependencies']} == {180, 181}
        assert row['native_instance_effect'] == 'unobserved'


def test_source_reconciliation_command_preserves_every_frozen_id_and_shape(tmp_path):
    import gzip
    import json
    from tests.maintenance.reconcile_condition_sources import main
    destination = tmp_path / 'source-reconciliation.json.gz'
    assert main(['--output', str(destination)]) == 0
    result = json.loads(gzip.decompress(destination.read_bytes()))
    frozen = json.loads(gzip.decompress((ROOT / 'tests/fixtures/metadata-conditions/self-scalar-program-review.json.gz').read_bytes()))
    actual = {m['id']: m['shape_sha256'] for r in result['occurrences'] for m in r['members']}
    expected = {identity: value['native_shape_sha256'] for identity, value in frozen['requirements']['branches'].items()}
    assert len(actual) == 5669
    assert actual == expected
    assert result['coverage_credit'] == 'none'
    assert all(r['native_instance_effect'] == 'unobserved' for r in result['occurrences'])

"""Accepted hidden-controller limitation keeps source, reads and writes distinct."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tests.support.condition_completion_mapping import definition_mapping
from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, condition
from tests.unit.test_field_interface_closure_gateway import VERSIONS
from tests.unit.test_time_modulator_range_gateway import declare, finish


ROOT = Path(__file__).parents[2]
AUTHORITY = ('docs/plans/full-waapi-coverage/SPEC.md#'
             'user-approved-music-playlist-hidden-dependency-boundary--2026-10-28')


@pytest.fixture(scope='module')
def mapping():
    return definition_mapping(ROOT)


def test_only_exact_music_loop_members_receive_the_conditional_limitation(mapping):
    original = json.loads((ROOT / 'tests/fixtures/branch-evidence/product/'
                           'condition-definitions-195-r1/mapping.json').read_bytes())
    expected = {m['id']: m['shape_sha256'] for row in original['occurrences']
                if row['dependency_kind'] == 'music' for m in row['members']}
    limited = [row for row in mapping['occurrences'] if row.get('approved_exclusion', {}).get('authority') == AUTHORITY]
    assert {m['id']: m['shape_sha256'] for row in limited for m in row['members']} == expected
    assert len(expected) == 15
    for row in limited:
        limit = row['approved_exclusion']
        assert limit['authority'] == AUTHORITY
        assert limit['when'] == 'required_controller_not_exposed_by_applicable_metadata'
        assert limit['reads_retained'] is True
        assert limit['exposed_controller_path_retained'] is True
        assert limit['execution_credit'] is False
        assert limit['native_absence_claim'] is False
        assert limit['writable_field_proof'] is False
        source = next(r for r in original['occurrences'] if r['occurrence_id'] == row['occurrence_id'])
        assert {k: v for k, v in row.items() if k != 'approved_exclusion'} == {
            **source, 'dependencies': []}


class MusicTask(ScalarPropertyTask):
    """Only Wwise transport is substituted; no native acceptance is claimed."""
    def __init__(self, path, version, *, exposed=False):
        super().__init__(path, version)
        self.set_object_type(FIRST, 'MusicPlaylistItem', 2359312)
        self.objects[FIRST].update(LoopCount=1, Weight=50.0)
        self.metadata = {
            'LoopCount': {'name': 'LoopCount', 'type': 'int16',
                'restriction': {'type': 'range', 'min': 0, 'max': 32767},
                'dependencies': [condition('IsLoopingInfinite', False)]},
            'Weight': {'name': 'Weight', 'type': 'Real64'},
        }
        self.enabled = exposed
        if exposed:
            self.metadata['IsLoopingInfinite'] = {'name': 'IsLoopingInfinite', 'type': 'bool'}
            self.objects[FIRST]['IsLoopingInfinite'] = False

    def call(self, uri, args=None, options=None):
        if uri.endswith('getPropertyInfo') and args['property'] not in self.metadata:
            self.calls.append((uri, deepcopy(args), options))
            return {}
        if uri.endswith('object.get') and args.get('waql') == f'from object "{FIRST}"':
            self.calls.append((uri, deepcopy(args), options))
            row = deepcopy(self.objects[FIRST])
            row['@LoopCount'] = row['LoopCount']
            return {'return': self.project_rows([row], options)}
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', VERSIONS)
def test_missing_controller_preserves_public_read_and_refuses_loop_change(tmp_path, version):
    task = MusicTask(tmp_path, version)
    before = deepcopy(task.objects)
    code, read = task.run('query-object', '--exact-id', FIRST, '--include-field', 'LoopCount')
    assert code == 0, read
    assert read['agent_result'][0]['properties'] == {'LoopCount': 1}
    code, discovered = task.run('metadata', 'discover', '--exact-id', FIRST, '--meaning', 'LoopCount')
    assert code == 0, discovered
    assert discovered['agent_result']['dependency_closure_complete'] is False
    missing = discovered['agent_result']['unresolved_dependencies'][0]
    assert missing['reason'] == 'dependency-name-not-in-live-inventory'
    assert missing['dependency']['property'] == 'IsLoopingInfinite'
    declare(task, 'LoopCount', 3)
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert checked['error_code'] == 'INVALID_METADATA'
    assert checked['details']['field'] == 'LoopCount'
    assert checked['details']['controller'] == 'IsLoopingInfinite'
    assert checked['details']['reason'] == 'required_controller_metadata_unavailable'
    assert checked['details']['cause']['message'] == 'Field binding needs an exact live-discovered token.'
    assert checked['recovery']['project_write_outcome'] == 'no_project_write_in_this_invocation'
    assert task.objects == before
    assert not any(uri.endswith(('setProperty', 'setReference', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_exposed_supported_controller_keeps_the_normal_loop_change_path(tmp_path, version):
    task = MusicTask(tmp_path, version, exposed=True)
    before = deepcopy(task.objects[FIRST])
    declare(task, 'LoopCount', 3)
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST] == {**before, 'LoopCount': 3}


def test_other_music_fields_remain_writable_without_the_hidden_loop_controller(tmp_path):
    task = MusicTask(tmp_path, '2025.1')
    task.enabled = True  # The unrelated Weight field is independently applicable.
    before = deepcopy(task.objects[FIRST])
    declare(task, 'Weight', 75)
    finish(task)
    assert task.objects[FIRST] == {**before, 'Weight': 75}


@pytest.fixture(scope='module')
def packet(mapping, tmp_path_factory):
    """Use the real attachment reader without regenerating global requirements."""
    from tests.support.condition_completion_mapping import REVIEW_PATH, validate_mapping_attachment
    from tests.maintenance.branch_coverage_audit import portable_binding_inputs
    base = tmp_path_factory.mktemp('music-selected-reader')
    def write(name, value):
        raw = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True) + '\n').encode()
        (base / name).write_bytes(raw)
        return {'artifact': name, 'sha256': hashlib.sha256(raw).hexdigest()}
    descriptor = write('attachment.json', {
        'contract': 'waapi-skill.condition-definition-attachment/v1',
        'review': write('review.json', (ROOT / REVIEW_PATH).read_bytes()),
        'mapping': write('mapping.json', mapping)})
    context = validate_mapping_attachment(descriptor, base, ROOT)
    policies = {}
    for identity, row in context['members'].items():
        if row['dependency_kind'] != 'music':
            continue
        policies[identity] = {
            'native_shape_sha256': context['branches'][identity]['shape_sha256'],
            'categories': [], 'reason': 'Recorded conditional hidden-controller limitation.',
            'definition_scope': 'source_definition',
            'approved_exclusion': deepcopy(row['approved_exclusion'])}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': policies}
    write('index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [], 'condition_definition_attachments': [descriptor]})
    bindings, actual_base, _ = portable_binding_inputs(base / 'index.json', requirements)
    assert actual_base == base
    return base, descriptor, context, requirements, bindings


def assess(packet, requirements=None, bindings=None, identities=None):
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    from tests.maintenance.branch_coverage_audit import digest
    base, _, context, original_requirements, original_bindings = packet
    requirements = deepcopy(original_requirements if requirements is None else requirements)
    identities = list(requirements['branches']) if identities is None else identities
    requirements['branches'] = {identity: requirements['branches'][identity] for identity in identities}
    selected_bindings = deepcopy(original_bindings if bindings is None else bindings)
    selected_bindings['bindings'] = {identity: selected_bindings['bindings'][identity] for identity in identities}
    return evaluate_coverage(ROOT, {'routes': [], 'native_coverage': {
        'candidate_sha256': 'c' * 64, 'catalogs': {}, 'routes': [],
        'obligations': [deepcopy(context['branches'][identity]) for identity in identities]}},
        selected_bindings, digest=digest,
        evidence_base=base, requirements_document=requirements)


def test_ordinary_reader_finalizes_only_conditional_limitation_without_execution_credit(packet, tmp_path):
    result = assess(packet)
    # Persist/reload the final report through the same JSON contract as the CLI.
    report = tmp_path / 'assessment.json'
    report.write_text(json.dumps(result))
    final = json.loads(report.read_text())
    assert final['completion']['states'] == {'approved_exclusion': 15}
    assert final['completion']['complete'] is True
    for row in final['obligations']:
        assert row['exclusion']['authority'] == AUTHORITY
        assert row['exclusion']['when'] == 'required_controller_not_exposed_by_applicable_metadata'
        assert row['exclusion']['native_absence_claim'] is False
        assert row['direct_recipient_native_effect'] == 'not_observed'
        assert row['direct_recipient_instance_metadata'] == 'not_observed'
        assert row['requirements'] == [] and row['evidence_results'] == {}
        binding = packet[4]['bindings'][row['id']]
        assert binding['evidence'] == {} and 'public_mechanism' not in binding


@pytest.mark.parametrize('category', ['program', 'native', 'live_metadata'])
def test_conditional_limitation_supplies_no_execution_or_metadata_evidence(packet, category):
    from tests.support.condition_completion_mapping import mapping_evidence_result
    base, descriptor, context, requirements, bindings = packet
    identity = next(iter(requirements['branches']))
    outcome, _ = mapping_evidence_result(descriptor, context['branches'][identity], category,
        'product', base, bindings['bindings'][identity], ROOT, context=context)
    assert outcome == 'missing'


@pytest.mark.parametrize('damage', ['missing-policy', 'missing-binding', 'broadened-condition', 'native-credit', 'writable-proof'])
def test_conditional_limitation_fails_closed_without_its_exact_policy_and_binding(packet, damage):
    requirements, bindings = deepcopy(packet[3]), deepcopy(packet[4])
    identity = next(iter(requirements['branches']))
    policy = requirements['branches'][identity]
    if damage == 'missing-policy': policy.pop('approved_exclusion')
    elif damage == 'missing-binding': bindings['bindings'][identity].pop('approved_exclusion')
    elif damage == 'broadened-condition': policy['approved_exclusion']['when'] = 'always'
    elif damage == 'native-credit': policy['approved_exclusion']['execution_credit'] = True
    else: policy['approved_exclusion']['writable_field_proof'] = True
    result = assess(packet, requirements, bindings, [identity])
    assert result['obligations'][0]['state'] == 'unresolved'


@pytest.mark.parametrize('damage', ['member', 'controller', 'version', 'when', 'native-absence'])
def test_limitation_attachment_cannot_change_its_exact_source_or_conditional_scope(packet, damage):
    from tests.support.condition_completion_mapping import validate_mapping_attachment
    base, descriptor, context, _, _ = packet
    mapping = deepcopy(context['mapping'])
    row = next(r for r in mapping['occurrences'] if r['dependency_kind'] == 'music')
    if damage == 'member': row['members'].pop()
    elif damage == 'controller': row['source_attributes']['Name'] = 'OtherController'
    elif damage == 'version': row['version'] = '2025.1'
    elif damage == 'when': row['approved_exclusion']['when'] = 'always'
    else: row['approved_exclusion']['native_absence_claim'] = True
    with pytest.raises(ValueError, match='exact source definition'):
        validate_mapping_attachment(descriptor, base, ROOT, selected_mapping=mapping)


@pytest.mark.parametrize('damage', ['missing', 'changed', 'review'])
def test_limitation_requires_the_exact_recorded_user_decision(tmp_path, damage):
    from tests.support.condition_completion_mapping import (
        FIELDLESS_REVIEW_PATH, BATCH_EXCLUSION_REVIEW_PATH, MUSIC_LIMIT_REVIEW_PATH)
    structural = json.loads((ROOT / FIELDLESS_REVIEW_PATH).read_bytes())
    for name in (FIELDLESS_REVIEW_PATH, BATCH_EXCLUSION_REVIEW_PATH, MUSIC_LIMIT_REVIEW_PATH,
                 structural['original_mapping']['path'], structural['source_snapshot']['path'],
                 'docs/plans/full-waapi-coverage/SPEC.md'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = tmp_path / 'docs/plans/full-waapi-coverage/SPEC.md'
    if damage == 'review':
        path = tmp_path / MUSIC_LIMIT_REVIEW_PATH
        path.write_text(path.read_text().replace('conditional mutation only', 'all writes'))
    else:
        text = path.read_text()
        text = (text.split('## User-approved Music Playlist hidden-dependency boundary', 1)[0]
                if damage == 'missing' else text.replace('retain reads but clearly refuse', 'remove reads and refuse'))
        path.write_text(text)
    with pytest.raises(ValueError, match='Music Playlist hidden-dependency'):
        definition_mapping(tmp_path)


def test_unrelated_condition_cannot_borrow_the_music_limitation(packet):
    requirements, bindings = deepcopy(packet[3]), deepcopy(packet[4])
    context = packet[2]
    ordinary = next(row for row in context['mapping']['occurrences']
        if row['dependency_kind'] is None and row['version'] == '2025.1'
        and row['source_pointer'].endswith('Property[BaseFrequency]/Dependencies'))
    identity = ordinary['members'][0]['id']
    policy = deepcopy(next(iter(requirements['branches'].values())))
    policy['native_shape_sha256'] = context['branches'][identity]['shape_sha256']
    requirements['branches'] = {identity: policy}
    bindings['bindings'][identity].update(evidence={}, approved_exclusion=deepcopy(policy['approved_exclusion']))
    result = assess(packet, requirements, bindings)
    assert result['obligations'][0]['state'] == 'unresolved'

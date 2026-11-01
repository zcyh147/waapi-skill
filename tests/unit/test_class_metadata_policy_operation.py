"""Private policy reuse keeps public metadata schedules exact and bounded."""
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import collect_class_metadata as collector


@pytest.fixture
def policy_root(tmp_path, monkeypatch):
    prefix = '2021.1|wwise-console|2021.1.14.8108|function|ak.wwise.core.object.getPropertyInfo|'
    definition = '/resultSchema/@definition/waapi_definitions.json/definitions/propertyValue'
    ids = [prefix + definition + suffix for suffix in ('/anyOf/3/@boolean/true', '/anyOf/1', '/anyOf/1/@empty/string')]
    policy = {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {
        identity: {'categories': ['program', 'live_metadata']} for identity in ids}}
    docs = tmp_path / 'docs'; docs.mkdir()
    path = docs / 'branch-coverage-requirements.json'
    audit.write_requirements(path, policy)
    (docs / 'branch-coverage-evidence-index.json').write_text('{}')
    types = tmp_path / 'skills/waapi-skill/resources/metadata/2021.1/object-types.json'
    types.parent.mkdir(parents=True)
    types.write_text(json.dumps({'types': [{'name': scope, 'classId': collector.CLASS_IDS[scope]}
        for scope in ('ModulatorTime', 'MusicStinger')]}))
    monkeypatch.setattr(collector, 'REPO', tmp_path)
    reads = []
    original_open = Path.open
    def counted_open(target, *args, **kwargs):
        # The normal bounded loader opens positionally; raw envelope snapshots
        # use Path.read_bytes. Count complete policy loads, not byte snapshots.
        if target == path and args and args[0] == 'rb': reads.append(target)
        return original_open(target, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', counted_open)
    return tmp_path, path, policy, reads


def operation(root):
    return collector._collection_policy_operation(root)


def test_repeated_collection_plans_load_validated_policy_only_at_operation_boundaries(policy_root):
    root, _, _, reads = policy_root
    with operation(root):
        first = collector.collection_plan('2021.1')
        for _ in range(3):
            with operation(root):
                assert collector.collection_plan('2021.1') == first
                assert collector.collection_plan('2021.1', cohort='r55')['targets'] == {'MusicStinger': ['CustomCueMatchName']}
    assert len(reads) == 2


def test_consecutive_operations_and_standalone_plans_remain_fresh(policy_root):
    root, path, policy, reads = policy_root
    for _ in range(2):
        reads.clear()
        with operation(root): collector.collection_plan('2021.1')
        assert len(reads) == 2
    reads.clear()
    collector.collection_plan('2021.1'); collector.collection_plan('2021.1')
    assert len(reads) == 2
    identity = next(iter(policy['branches']))
    policy['branches'][identity]['categories'] = ['program']
    audit.write_requirements(path, policy)
    with pytest.raises(ValueError, match='requirement assignment'):
        collector.collection_plan('2021.1')


def test_reuse_keeps_each_call_version_cohort_class_and_category_validation(policy_root):
    root, path, policy, _ = policy_root
    identity = next(key for key in policy['branches'] if '/anyOf/1' in key)
    policy['branches'][identity]['categories'] = ['program']
    audit.write_requirements(path, policy)
    with operation(root):
        collector.collection_plan('2021.1')
        with pytest.raises(ValueError, match='requirement assignment'):
            collector.collection_plan('2021.1', cohort='r55')
        for version, cohort in [('2099.1', 'r54'), ('2025.1', 'r55'), ('2021.1', 'foreign')]:
            with pytest.raises(ValueError, match='Unreviewed class metadata version'):
                collector.collection_plan(version, cohort=cohort)
        types = root / 'skills/waapi-skill/resources/metadata/2021.1/object-types.json'
        types.write_text(json.dumps({'types': [{'name': 'ModulatorTime', 'classId': 0}]}))
        with pytest.raises(ValueError, match='Pinned class identity'):
            collector.collection_plan('2021.1')


@pytest.mark.parametrize('drift', ['envelope', 'part', 'policy', 'index'])
def test_policy_drift_prevents_operation_result_and_resets_scope(policy_root, drift):
    root, path, policy, reads = policy_root
    part = path.parent / json.loads(path.read_bytes())['parts'][0]['path']
    originals = {target: target.read_bytes() for target in (path, part, path.parent / 'branch-coverage-evidence-index.json')}
    result = None
    with pytest.raises(ValueError, match='changed during operation|digest mismatch'):
        with operation(root):
            plan = collector.collection_plan('2021.1')
            if drift == 'policy':
                policy['branches'][plan['eligible_branch_ids'][0]]['categories'] = ['program']
                audit.write_requirements(path, policy)
            else:
                target = {'envelope': path, 'part': part, 'index': path.parent / 'branch-coverage-evidence-index.json'}[drift]
                target.write_bytes(target.read_bytes() + b'\n')
        result = plan
    assert result is None
    for target, raw in originals.items(): target.write_bytes(raw)
    reads.clear()
    with operation(root): collector.collection_plan('2021.1')
    assert len(reads) == 2


def test_unrelated_operation_needs_no_metadata_or_source_policy(tmp_path):
    from tests.maintenance import branch_audit_completion as completion
    with collector._collection_policy_operation(tmp_path):
        pass
    assert completion.evidence_result(None, {'id': 'unrelated', 'route': 'unrelated'},
        'a' * 64, 'program', 'product', tmp_path, source_root=tmp_path)[0] == 'missing'


# Reuse the genuine immutable Source publisher fixture to prove that an importer
# scope's metadata guard failure prevents the existing final index rename.
from tests.unit.test_source_accounting_operation import accounting_packet


@pytest.mark.parametrize('accounting_packet', [True], indirect=True)
def test_metadata_policy_drift_cannot_publish_a_final_index(accounting_packet, monkeypatch):
    from tests.support import source_copy_native_evidence as source
    case = accounting_packet
    original_open = Path.open
    triggered = []
    def drifted_open(path, *args, **kwargs):
        mode = kwargs.get('mode', args[0] if args else None)
        if path.name == 'index.json.pending' and mode == 'rb' and not triggered:
            triggered.append(path)
            collector.collection_plan('2021.1')
            collector.collection_plan('2021.1')
            case['policy'].write_bytes(case['policy'].read_bytes() + b'\n')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', drifted_open)
    with pytest.raises(ValueError, match='policy changed during operation'):
        source.publish_source_native_successor(case['original'], predecessor=case['native']['predecessor'],
            inventory=case['inventory'], product_base=case['product'], destination=case['output'] / 'publication', accounting=True)
    assert triggered
    portable = case['output'] / 'publication/portable'
    assert not (portable / 'index.json').exists()
    assert (portable / 'index.json.pending').is_file()


@pytest.mark.parametrize('damage', ['wrong-class', 'true-vs-one', 'native-bytes'])
def test_existing_class_packet_shape_checks_remain_active_with_policy_reuse(tmp_path, monkeypatch, damage):
    import hashlib
    from tests.maintenance import branch_audit_completion as reader
    from tests.unit.test_class_metadata_collection import controlled_capture
    prefix = '2022.1|wwise-console|2022.1.19.8584|function|ak.wwise.core.object.getPropertyInfo|'
    definition = '/resultSchema/@definition/waapi_definitions.json/definitions/propertyValue'
    pointers = ['/resultSchema/properties/default/@presence/present', '/resultSchema/properties/default',
        '/resultSchema/properties/default/$ref', definition, definition + '/anyOf/0',
        definition + '/anyOf/0/@nullable', definition + '/anyOf/2', definition + '/anyOf/3',
        definition + '/anyOf/3/@boolean/false', definition + '/anyOf/3/@boolean/true']
    policy = {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {
        prefix + pointer: {'categories': ['program', 'live_metadata']} for pointer in pointers}}
    policy_path = tmp_path / 'policy/branch-coverage-requirements.json'
    policy_path.parent.mkdir()
    audit.write_requirements(policy_path, policy)
    canonical = collector.REPO / 'docs/branch-coverage-requirements.json'
    view = {canonical: policy_path}
    for part in json.loads(policy_path.read_bytes())['parts']:
        view[canonical.parent / part['path']] = policy_path.parent / part['path']
    original_open = Path.open
    def selected_open(path, *args, **kwargs):
        return original_open(view.get(path, path), *args, **kwargs)
    monkeypatch.setattr(Path, 'open', selected_open)
    capture = tmp_path / 'capture'
    with operation(collector.REPO):
        descriptor = controlled_capture(capture)['2022.1|Wwise Delay|FeedbackEnabled']
        assert reader.read_metadata_run(descriptor, capture)['native_result']['default'] is True
        targets = json.loads((capture / 'targets.json').read_bytes())
        target = targets[descriptor['target_index']]
        native_path = capture / target['native_receipt']
        if damage == 'native-bytes':
            native_path.write_text('{}')
            reason = 'metadata external seal mismatch'
        else:
            payload_path = capture / (descriptor['receipt'] + '.stdout')
            payload = json.loads(payload_path.read_bytes())
            native = json.loads(native_path.read_bytes())
            if damage == 'wrong-class':
                payload['agent_result']['scope']['resolved']['classId'] = 65552
                reason = 'Exact public class identity changed'
            else:
                payload['agent_result']['metadata']['default'] = native['result']['default'] = 1
                reason = 'Original typed class default witness changed'
            payload_path.write_text(json.dumps(payload))
            (capture / (descriptor['receipt'] + '.agent-result.json')).write_text(json.dumps(payload['agent_result']))
            native_path.write_text(json.dumps(native))
            target.update(native_sha256=hashlib.sha256(native_path.read_bytes()).hexdigest(), native_bytes=native_path.stat().st_size)
            (capture / 'targets.json').write_text(json.dumps(targets))
            seal_path = capture / 'evidence-seal.json'
            seal = json.loads(seal_path.read_bytes())
            for entry in seal['files']:
                path = capture / entry['path']
                entry.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
            seal_path.write_text(json.dumps(seal))
            descriptor['seal']['sha256'] = hashlib.sha256(seal_path.read_bytes()).hexdigest()
        with pytest.raises(ValueError, match=reason):
            reader.read_metadata_run(descriptor, capture)

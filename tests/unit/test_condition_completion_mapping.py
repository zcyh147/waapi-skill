"""Exact installed definitions share reviewed proof, never invented observations."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os

import pytest

from tests.support.condition_completion_mapping import definition_mapping

ROOT = Path(__file__).parents[2]


def test_current_public_source_and_device_condition_routes(tmp_path, request):
    """Two different live-class shapes; source metadata stays explicitly modeled."""
    from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan
    from tests.support.condition_mechanism_reuse import _require_object_scope_mechanism
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST
    from tests.unit.test_time_modulator_range_gateway import finish
    plan = scalar_plan(scalar_manifest(ROOT))
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('scripts', 'wwise_waapi') for p in (ROOT / 'skills/waapi-skill' / folder).rglob('*.py')
        if '__pycache__' not in p.parts}
    sources[str(Path(__file__).relative_to(ROOT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    observed = {}
    for field, native_type, class_id in (('BaseFrequency', 'SourcePlugin', 9699330),
                                        ('MainMixHeadphoneConfiguration', 'AudioDevice', 11403271)):
        group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == field)
        model = group['model']
        path = tmp_path / field; path.mkdir()
        task = ScalarPropertyTask(path, '2025.1')
        task.set_object_type(FIRST, native_type, class_id)
        catalog = json.loads((ROOT / 'skills/waapi-skill/resources/metadata/2025.1/object-types.json').read_bytes())
        actual_class, = [r for r in catalog['types'] if r['classId'] == class_id]
        task.types = [r for r in task.types if r['classId'] != class_id] + [actual_class]
        task.metadata = deepcopy(model['metadata'])
        task.objects[FIRST].update(model['before'])
        before = deepcopy(task.objects[FIRST])
        handle = task.bind(FIRST); selected = task.discover(handle, field)
        code, declared = task.step('draft-declare-field-change', '--object-handle', handle,
            '--field-handle', selected, '--business-value', json.dumps(model['requested']))
        assert code == 0, declared
        preview, code, verified, transaction = finish(task)
        assert code == 0 and verified['verified'] is True
        after = deepcopy(task.objects[FIRST])
        assert after == {**before, field: model['requested']}
        calls = [{'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options)} for uri, args, options in task.calls]
        writes = [c for c in calls if c['uri'].endswith('setProperty')]
        assert len(writes) == 1
        flow = {'native_call': writes[0], 'object_scope_call_trace': calls,
            'before': before, 'after': after, 'metadata': deepcopy(task.metadata), 'class_catalog': actual_class,
            'gateway': {'argv': ['verify', transaction], 'exit_code': code, 'payload': verified}}
        _require_object_scope_mechanism(flow, {'selected_field': field, 'controller': model['controller']})
        observed[native_type] = flow
    def finalized(reports):
        assert reports == {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
        assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in sources.items())
        destination = Path(os.environ.get('WAAPI_CONDITION_MECHANISM_CAPTURE_ROOT', str(tmp_path / 'published')))
        destination.mkdir(parents=True, exist_ok=False)
        record = {'contract': 'waapi-skill.condition-current-public-mechanism/v1', 'scope_kind': 'product',
            'evidence_kind': 'injected_client_program', 'nodeid': request.node.nodeid, 'reports': reports,
            'sources': sources, 'observations': observed, 'metadata_scope': 'source_definition',
            'direct_recipient_class_metadata': 'not_observed', 'direct_recipient_instance_metadata': 'not_observed',
            'direct_recipient_native_effect': 'not_observed'}
        (destination / 'current-program.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    register_exact_evidence_finalizer(request.node, finalized)


@pytest.fixture(scope='module')
def mapping():
    return definition_mapping(ROOT)


def test_full_source_roster_and_explicit_dependencies_are_conserved(mapping):
    from tests.maintenance.branch_audit_completion import installed_obligations
    from tests.maintenance.branch_coverage_audit import digest, load
    expected = {r['id']: r['shape_sha256'] for r in installed_obligations(ROOT, digest=digest, load=load)
                if r['owner_issue'] == 177 and r['kind'] == 'metadata_condition'}
    actual = {m['id']: m['shape_sha256'] for r in mapping['occurrences'] for m in r['members']}
    assert actual == expected and len(actual) == 7297
    assert len(mapping['recipes']) == 11
    assert sum(len(r['members']) for r in mapping['occurrences'] if r['dependency_kind'] == 'music') == 15
    assert sum(len(r['members']) for r in mapping['occurrences'] if r['dependency_kind'] == 'batch') == 240
    assert sum(len(r['members']) for r in mapping['occurrences'] if r['dependency_kind'] == 'fieldless') == 30
    assert all(r['metadata_scope'] == 'source_definition' for r in mapping['occurrences'])
    assert all(r['direct_recipient_class_metadata'] == 'not_observed' and
               r['direct_recipient_instance_metadata'] == 'not_observed' for r in mapping['occurrences'])

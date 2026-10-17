"""Existing producer compatibility, independent of new branch coverage claims."""
import hashlib
import json
import gzip
from pathlib import Path
from copy import deepcopy

import pytest

from tests.maintenance import branch_audit_completion as completion

FIXTURES = Path(__file__).parents[1] / 'fixtures/branch-evidence'


def sealed(path, **extra):
    return {'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), **extra}


def test_existing_category_v3_positive_and_forged_host_negative(tmp_path):
    path = FIXTURES / 'category-v3.json'
    original = json.loads(path.read_text())
    descriptor = sealed(path, nodeid=original['invocation']['node_outcomes'][0]['nodeid'])
    context = completion.read_category_run(descriptor, tmp_path)
    assert context['candidate'] == original['candidate']
    assert context['host'] == 'wwise-console' and context['version'] == '2024.1'
    assert context['build'] == '.'.join(str(original['host']['version'][k]) for k in ('year', 'major', 'minor', 'build'))
    forged = deepcopy(original)
    forged['host'] = {'wwise_build': context['build'], 'native_host': 'wwise-console', 'candidate_source_sha256': 'a' * 64}
    target = tmp_path / 'forged.json';target.write_text(json.dumps(forged))
    with pytest.raises((ValueError, KeyError)):
        completion.read_category_run(sealed(target, nodeid=descriptor['nodeid']), tmp_path)


def metadata_descriptor():
    root = FIXTURES / 'metadata'
    return {'seal': sealed(root / 'seal.json'), 'root': str(root), 'receipt': '006', 'status_receipt': '003'}


def isolated_original_sources(target, context, names):
    fixture = json.loads(gzip.decompress((FIXTURES / 'original-sources.json.gz').read_bytes()))
    assert fixture['candidate'] == context['candidate']
    for name in names:
        original = fixture['files'][name]
        raw = original['text'].encode('utf-8')
        assert hashlib.sha256(raw).hexdigest() == original['sha256'] == context['relevant_sources'][name]
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return target


def test_existing_scenario_metadata_positive_and_exact_receipt_corruption(tmp_path):
    descriptor = metadata_descriptor()
    result = completion.read_metadata_run(descriptor, tmp_path)
    assert result['version'] == '2021.1' and result['host'] == 'wwise-console'
    assert result['build'] == '2021.1.14.8108'
    assert result['gateway']['payload']['agent_result']['metadata']['name'] == 'ContinuePlay'
    assert result['candidate'] == 'e0f2d2952488223865a1c52cd485a7ed897184a4'
    import shutil
    copied = tmp_path / 'metadata';shutil.copytree(FIXTURES / 'metadata', copied)
    damaged = deepcopy(descriptor);damaged['root'] = str(copied)
    (copied / '006.stdout').write_text('{}')
    with pytest.raises(ValueError, match='seal'):
        completion.read_metadata_run(damaged, tmp_path)


@pytest.mark.parametrize('per_record', [False, True])
def test_metadata_branch_uses_original_receipt_and_reviewed_source_equivalence(tmp_path, per_record):
    from tests.maintenance import branch_coverage_audit as audit
    context = completion.read_metadata_run(metadata_descriptor(), tmp_path)
    branch = {'id': 'controlled-original-metadata', 'route': None, 'version': '2021.1', 'build': '2021.1.14.8108',
              'pointer': '/installed/condition', 'kind': 'metadata_condition', 'shape_sha256': 'b' * 64}
    candidate = 'c' * 64
    sources = ['skills/waapi-skill/scripts/run.py', 'skills/waapi-skill/scripts/gateway.py']
    original_root = isolated_original_sources(tmp_path / 'original-source-context', context, sources)
    binding = {'input': {'gateway_argv': context['gateway']['argv']}, 'native_hosts': ['wwise-console'],
        'observation_pointer': '/gateway/payload/agent_result/metadata/dependencies/0/context', 'relevant_sources': sources,
        **{key: {'source': 'skills/waapi-skill/scripts/gateway.py#execute_gateway', 'selector': branch['pointer']}
           for key in ('construction', 'validation', 'verifier')}}
    record = {'candidate_sha256': candidate, 'scope_kind': 'controlled', 'metadata_run': metadata_descriptor(),
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': 'preserved-metadata', 'outcome': 'PASS'}]},
        'branch_assertions': {branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': None,
          'checks': [{'pointer': binding['observation_pointer'], 'equals': 'AssocParent'}]}}}
    path = tmp_path / 'mapped.json';path.write_text(json.dumps(record))
    descriptor = sealed(path, nodeid='preserved-metadata')
    proof = {'contract': 'waapi-skill.branch-evidence-equivalence/v1', 'reviewed_reason': 'Controlled reader compatibility: original metadata source files unchanged.',
        'from_candidate': context['candidate'], 'to_candidate': candidate, 'branch_id': branch['id'],
        'native_shape_sha256': branch['shape_sha256'], 'native_route': None,
        'evidence_sha256': context['receipt_sha256'], 'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
        'sources': {name: context['relevant_sources'][name] for name in sources}}
    proof_path = tmp_path / 'reuse.json';proof_path.write_text(json.dumps(proof))
    binding['native_equivalence'] = ({context['receipt_sha256']: sealed(proof_path)} if per_record else sealed(proof_path))
    assert completion.evidence_result(descriptor, branch, candidate, 'live_metadata', 'controlled', tmp_path, binding, source_root=original_root) == ('passed', None)
    # The same historical proof must not silently certify a changed Gateway.
    assert completion.evidence_result(descriptor, branch, candidate, 'live_metadata', 'controlled', tmp_path, binding, source_root=audit.ROOT) == ('missing', 'equivalence relevant source changed')
    assert completion.evidence_result(descriptor, branch, candidate, 'native', 'controlled', tmp_path, binding)[0] == 'missing'
    assert completion.evidence_result(descriptor, branch, candidate, 'fresh', 'controlled', tmp_path, binding)[0] == 'missing'
    record['branch_assertions'][branch['id']]['checks'][0]['equals'] = 'Parent'
    path.write_text(json.dumps(record));descriptor = sealed(path, nodeid='preserved-metadata')
    assert completion.evidence_result(descriptor, branch, candidate, 'live_metadata', 'controlled', tmp_path, binding, source_root=original_root)[0] == 'missing'


def test_native_absence_requires_omission_in_each_exact_host_observation():
    hosts = {'wwise-console', 'wwise-authoring'}
    binding = {'absence_observation_pointers': {host: f'/observations/{host}/capabilities/field' for host in hosts}}
    record = {'observations': {host: {'capabilities': {}} for host in hosts}}
    checks = [{'pointer': pointer, 'absent': True} for pointer in binding['absence_observation_pointers'].values()]
    completion.validate_native_absence_observations(record, binding, checks, hosts)
    record['observations']['wwise-console']['capabilities']['field'] = True
    with pytest.raises(ValueError, match='present'):
        completion.validate_native_absence_observations(record, binding, checks, hosts)
    record['observations']['wwise-console']['capabilities'].clear()
    binding['absence_observation_pointers']['wwise-authoring'] = binding['absence_observation_pointers']['wwise-console']
    with pytest.raises(ValueError, match='host'):
        completion.validate_native_absence_observations(record, binding, checks, hosts)


@pytest.mark.parametrize("damage", ["api_instead_of_uri", "missing_exit_code"])
def test_metadata_result_producer_uses_existing_strict_reader_without_product_credit(tmp_path, damage):
    from tests.support.metadata_read_branch_evidence import finish_metadata_capture, source_seals, _git_candidate, URI
    from tests.support.media_pool_branch_evidence import public_read_observation
    route = "2025.1|wwise-console|2025.1.7.9143|function|" + URI
    branch = {"id": "controlled-metadata-default-presence", "route": route, "kind": "optional_presence",
        "value": "present", "shape_sha256": "b" * 64, "pointer": "/resultSchema/properties/default/@presence/present"}
    nodeid, candidate = "controlled-metadata-result-node", "c" * 64
    observed = {**public_read_observation(gateway_argv=["metadata", "detail", "--selection", "controlled"], exit_code=0,
        payload={"ok": True, "agent_result": {"metadata": {"default": None}}}, uri=URI,
        args={"property": "Volume"}, options={}, result={"default": None}),
        "native_metadata_dispatch_count": 1, "rejected_read": {"payload": {"error_code": "METADATA_SELECTION_SCOPE_CHANGED"}}}
    capture = {"root": str(tmp_path), "version": "2025.1", "case_name": "controlled", "nodeid": nodeid,
        "candidate_sha256": candidate, "git_candidate": _git_candidate(), "scope_kind": "controlled",
        "relevant_sources": source_seals(), "groups": {"2025.1|controlled": {
            "public": {"id": "2025.1|function|" + URI}, "branches": [{"branch": branch,
                "observation_pointer": "/native_call/result/default", "reference_chain": [],
                "check": {"pointer": "/native_call/result/default", "equals": None}}]}}}
    finish_metadata_capture(capture, {"setup": "passed", "call": "passed", "teardown": "passed"}, observed)
    root = tmp_path / "2025.1/controlled"
    binding = json.loads((root / "bindings.json").read_text())["bindings"][branch["id"]]
    descriptor = binding["evidence"]["program"]
    assert completion.evidence_result(descriptor, branch, candidate, "program", "controlled", root, binding) == ("passed", None)
    damaged = json.loads((root / "program.json").read_text())
    if damage == "api_instead_of_uri":
        damaged["native_call"]["api"] = damaged["native_call"].pop("uri")
    else:
        damaged["gateway"].pop("exit_code")
    path = root / "damaged.json"
    path.write_text(json.dumps(damaged))
    outcome, reason = completion.evidence_result(sealed(path, nodeid=nodeid), branch, candidate, "program", "controlled", root, binding)
    assert outcome == "missing" and ("uri" if damage == "api_instead_of_uri" else "exit_code") in reason
    assert completion.evidence_result(descriptor, branch, candidate, "program", "product", root, binding)[0] == "missing"

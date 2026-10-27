"""Versioned RTPC fields share one public-read evidence publisher."""
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway

URI = 'ak.wwise.core.profiler.getRTPCs'
RPM = '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}'
BUILDS = {'2021.1': (14, 8108), '2022.1': (19, 8584), '2023.1': (19, 8928),
          '2024.1': (13, 9056), '2025.1': (7, 9143)}
FIXTURES = audit.ROOT / 'tests/fixtures/branch-evidence/product'


def public_rtpc_read(root, version='2022.1', host='wwise-authoring', position='23637', rows=None, native_reads=None):
    from tests.support.runtime_observation_evidence import program_source_context
    source_context = program_source_context()
    root.mkdir(parents=True, exist_ok=True)
    native_rows = deepcopy(rows if rows is not None else [
        {'id': RPM, 'name': 'RPM', 'gameObjectId': 18446744073709551615, 'value': 1000.0},
        {'id': RPM, 'name': 'RPM', 'gameObjectId': 18446744073709551614, 'value': 1000.0}])
    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(root, version=version)
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri == URI:
                result = {'return': deepcopy(native_rows)}
            elif uri == 'ak.wwise.core.profiler.getCursorTime':
                result = {'return': 12345 if args['cursor'] == 'capture' else 23456}
            else:
                result = super().call(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                minor, build = BUILDS[version]
                result['isCommandLine'] = host == 'wwise-console'
                result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
            if native_reads is not None:
                native_reads.append({'ordinal': len(self.calls) - 1, 'uri': uri,
                    'args': deepcopy(args), 'options': deepcopy(options), 'result': deepcopy(result)})
            return result
    client = Client()
    argv = ['core-call', URI, '--profiler-position', position, '--max-results', '64']
    code, payload = gateway.execute_gateway(['--state-dir', str(root / 'state'), *argv],
        env=_env(root, version=version), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    assert payload['agent_result']['return'] == native_rows
    assert payload['agent_result']['complete'] is True
    expected_time = int(position) if position.isdecimal() else 12345 if position == 'capture-latest' else 23456
    assert client.calls[-1] == (URI, {'time': expected_time}, {})
    return {'argv': argv, 'exit_code': code, 'payload': payload}, {
        'uri': URI, 'args': {'time': expected_time}, 'options': {}, 'result': {'return': native_rows}}, source_context


def original_array_program(root, version):
    from tests.support.runtime_observation_evidence import write_program_receipt
    originals = (FIXTURES / 'runtime-rtpc-fields-r109/originals/2022.1' if version == '2022.1'
        else FIXTURES / 'runtime-read-r108')
    capture = json.loads((originals / 'original-capture.json').read_bytes())
    evidence = capture['outcomes']['profiler-rtpcs-observation']['evidence']
    receipt, dispatch, context = public_rtpc_read(root, version,
        position=str(evidence['position_ms']), rows=evidence['agent_result']['return'])
    path = root / 'original-array-program.json'
    write_program_receipt(path, receipt, dispatch, nodeid=f'original-array-{version}',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    return path


@pytest.fixture(scope='module')
def inventory():
    started = perf_counter()
    result = audit.build_inventory()
    print(json.dumps({'rtpc_phase': 'build_inventory', 'seconds': perf_counter() - started}))
    return result


def test_one_rtpc_flow_publishes_independent_fields_and_references(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle
    receipt, dispatch, context = public_rtpc_read(tmp_path)
    program = tmp_path / 'capture.json'
    write_program_receipt(program, receipt, dispatch, nodeid='rtpc-fields-2022',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', program,
        FIXTURES / 'runtime-rtpc-fields-r109/originals/2022.1', inventory=inventory,
        version='2022.1', host='wwise-authoring', mode='data',
        guard_replay=original_array_program(tmp_path / 'replay', '2022.1'))
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    bindings, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, bindings,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in bindings['bindings']]
    assert len(selected) == 15
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    assert all(row['requirements'] == ['native', 'program'] for row in selected)


@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('host', ('wwise-console', 'wwise-authoring'))
def test_public_rtpc_contract_and_exact_mapping_across_versions(tmp_path, inventory, version, host):
    from tests.support.runtime_observation_evidence import rtpc_field_mappings
    # Both zero and positive time cross the actual public construction boundary.
    for position in ('0', '23637'):
        receipt, dispatch, _ = public_rtpc_read(tmp_path / position, version, host, position)
        assert dispatch['args'] == {'time': int(position)}
        assert receipt['payload']['agent_result']['profiler_position'] == position
    _, data = rtpc_field_mappings(inventory, version=version, host=host, mode='data')
    assert len(data) == {'2021.1': 15, '2022.1': 15, '2023.1': 11, '2024.1': 11, '2025.1': 9}[version]
    _, construction = rtpc_field_mappings(inventory, version=version, host=host, mode='construction')
    assert len(construction) == 6
    assert all('profilerCursor' not in item['branch']['pointer'] for item in construction)


@pytest.mark.parametrize('version,count', [('2022.1', 17), ('2025.1', 5)])
def test_original_complete_native_arrays_preserved_through_public_gateway(tmp_path, request, version, count):
    originals = (FIXTURES / 'runtime-rtpc-fields-r109/originals/2022.1' if version == '2022.1'
        else FIXTURES / 'runtime-read-r108')
    capture = json.loads((originals / 'original-capture.json').read_bytes())
    evidence = capture['outcomes']['profiler-rtpcs-observation']['evidence']
    rows = evidence['agent_result']['return']
    receipt, dispatch, context = public_rtpc_read(tmp_path, version, position=str(evidence['position_ms']), rows=rows)
    assert len(receipt['payload']['agent_result']['return']) == count
    if version == '2022.1':
        # Reflection's uniqueName pattern does not describe these original strings.
        # Preserve actual native names; this makes no whole-array schema claim.
        assert rows[12]['name'] == 'CC #1: Modulation'
        assert rows[14]['name'] == 'MIDI note velocity'
    import os
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.runtime_observation_evidence import write_program_receipt
    destination = Path(os.environ.get('WAAPI_RTPC_FIELD_CAPTURE_DIR', tmp_path)) / f'{version}-original-array.json'
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, dispatch, nodeid=request.node.nodeid, phase_reports=phases, source_context=context))


def test_construction_only_policy_and_unobserved_native_remain_distinct(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle
    receipt, dispatch, context = public_rtpc_read(tmp_path, '2021.1', 'wwise-console', '0')
    program = tmp_path / 'capture.json'
    write_program_receipt(program, receipt, dispatch, nodeid='rtpc-zero',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    for mode, state, count in [('construction', 'verified', 6), ('data', 'implemented_unverified', 15)]:
        index = write_field_bundle(tmp_path / mode, program, None, inventory=inventory,
            version='2021.1', host='wwise-console', mode=mode)
        policy = json.loads((index.parent / 'requirements.json').read_bytes())
        bindings, base, _ = audit.portable_binding_inputs(index, policy)
        result = completion.evaluate_coverage(audit.ROOT, inventory, bindings,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        selected = [row for row in result['obligations'] if row['id'] in bindings['bindings']]
        assert len(selected) == count
        assert {row['state'] for row in selected} == {state}, json.dumps(selected)
        assert all(row['evidence_results']['program']['outcome'] == 'passed' for row in selected)
        if mode == 'data':
            assert all(row['evidence_results']['native']['outcome'] == 'missing' for row in selected)


@pytest.mark.parametrize('arguments', [
    ['--profiler-position', '-1'], ['--profiler-position', '1.5'],
    ['--profiler-position', 'NaN'], ['--profiler-position', '0', '--args', '{}'],
    ['--profiler-position', '0', '--options', '{}'],
])
def test_rtpc_construction_rejects_negative_nondecimal_and_native_inputs(tmp_path, arguments):
    client = _RuntimeControlDraftClient(tmp_path, version='2022.1')
    calls = []
    original = client.call
    def call(uri, args=None, options=None):
        calls.append(uri)
        return original(uri, args, options)
    client.call = call
    if '--args' in arguments or '--options' in arguments:
        with pytest.raises(SystemExit) as rejected:
            gateway.execute_gateway(['core-call', URI, *arguments],
                env=_env(tmp_path, version='2022.1'), client_factory=lambda _: client)
        assert rejected.value.code == 2
    else:
        code, payload = gateway.execute_gateway(['core-call', URI, *arguments],
            env=_env(tmp_path, version='2022.1'), client_factory=lambda _: client)
        assert code != 0, payload
    assert URI not in calls


@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('position', ('capture-latest', 'user-cursor'))
def test_cursor_choices_stay_owned_two_step_reads_without_enum_credit(tmp_path, version, position):
    receipt, dispatch, _ = public_rtpc_read(tmp_path, version, position=position)
    assert dispatch['args'] == {'time': 12345 if position == 'capture-latest' else 23456}
    assert receipt['payload']['agent_result']['profiler_position'] == position


@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('host', ('wwise-console', 'wwise-authoring'))
@pytest.mark.parametrize('position', ('0', 'positive'))
def test_rtpc_field_program_emits_after_actual_teardown(tmp_path, request, version, host, position):
    import os
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.runtime_observation_evidence import write_program_receipt
    position = ('30837' if version == '2025.1' else '23637') if position == 'positive' else position
    receipt, dispatch, context = public_rtpc_read(tmp_path, version, host, position)
    directory = Path(os.environ.get('WAAPI_RTPC_FIELD_CAPTURE_DIR', tmp_path))
    destination = directory / f'{version}-{host}-{position}.json'
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, dispatch, nodeid=request.node.nodeid, phase_reports=phases, source_context=context))


def test_2025_field_flow_reaches_final_consumer_with_phase_timing(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle
    started = perf_counter()
    receipt, dispatch, context = public_rtpc_read(tmp_path, '2025.1', position='30837')
    program = tmp_path / 'capture.json'
    write_program_receipt(program, receipt, dispatch, nodeid='rtpc-fields-2025',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    print(json.dumps({'rtpc_phase': 'public_capture', 'seconds': perf_counter() - started}))
    started = perf_counter()
    index = write_field_bundle(tmp_path / 'bundle', program, FIXTURES / 'runtime-read-r108',
        inventory=inventory, version='2025.1', host='wwise-authoring', mode='data',
        guard_replay=original_array_program(tmp_path / 'replay', '2025.1'))
    print(json.dumps({'rtpc_phase': 'publication', 'seconds': perf_counter() - started}))
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    started = perf_counter()
    bindings, base, _ = audit.portable_binding_inputs(index, policy)
    print(json.dumps({'rtpc_phase': 'portable_import', 'seconds': perf_counter() - started}))
    started = perf_counter()
    result = completion.evaluate_coverage(audit.ROOT, inventory, bindings,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    print(json.dumps({'rtpc_phase': 'evaluate', 'seconds': perf_counter() - started}))
    selected = [row for row in result['obligations'] if row['id'] in bindings['bindings']]
    assert len(selected) == 9
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)


def test_five_version_stage_uses_one_portable_consumer_without_native_inference(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_stage
    captures = {}
    for version in BUILDS:
        for host in ('wwise-console', 'wwise-authoring'):
            for mode, position in [('construction', '0'), ('data', '30837' if version == '2025.1' else '23637')]:
                root = tmp_path / f'{version}-{host}-{mode}'
                receipt, dispatch, context = public_rtpc_read(root, version, host, position)
                path = root / 'capture.json'
                write_program_receipt(path, receipt, dispatch, nodeid=f'rtpc-{version}-{host}-{mode}',
                    phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
                captures[version, host, mode] = path
    index = write_field_stage(tmp_path / 'stage', captures, {}, inventory=inventory)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    bindings, base, _ = audit.portable_binding_inputs(index, policy)
    assert len(bindings['bindings']) == 182
    assert not list(index.parent.glob('*closure*'))
    result = completion.evaluate_coverage(audit.ROOT, inventory, bindings,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in bindings['bindings']]
    assert sum(row['state'] == 'verified' for row in selected) == 60
    assert sum(row['state'] == 'implemented_unverified' for row in selected) == 122


@pytest.fixture(scope='module')
def native_field_bundle(tmp_path_factory, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle
    root = tmp_path_factory.mktemp('rtpc-native-fields')
    receipt, dispatch, context = public_rtpc_read(root)
    program = root / 'capture.json'
    write_program_receipt(program, receipt, dispatch, nodeid='rtpc-native-fields',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    return write_field_bundle(root / 'bundle', program,
        FIXTURES / 'runtime-rtpc-fields-r109/originals/2022.1', inventory=inventory,
        version='2022.1', host='wwise-authoring', mode='data',
        guard_replay=original_array_program(root / 'replay', '2022.1'))


def test_historical_git_map_reuse_keeps_exact_immutable_source_identity(native_field_bundle, inventory, monkeypatch):
    import subprocess
    policy = json.loads((native_field_bundle.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(native_field_bundle, policy)
    selected = {key: value for key, value in document['bindings'].items()
        if key.endswith('/items/properties/id') or key.endswith('/items/properties/name')}
    assert len(selected) == 2
    document['bindings'] = selected
    completion._historical_git_source_seal.cache_clear()
    actual = subprocess.run
    git_calls = []
    def observed(command, *args, **kwargs):
        if command[:3] == ['git', '--no-replace-objects', 'show']:
            git_calls.append(command)
        return actual(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', observed)
    for evaluation in (1, 2):
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        assert all(row['state'] == 'verified' for row in result['obligations'] if row['id'] in selected)
        assert len(git_calls) == 413


def test_historical_git_map_key_keeps_exact_source_selection(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    from tests.support.runtime_observation_evidence import write_json
    candidate = 'current-focused-consumer'
    branch = {'id': 'exact-branch', 'shape_sha256': 'exact-shape', 'route': 'exact-route'}
    descriptor = {'sha256': 'original-run'}
    files = ['skills/waapi-skill/scripts/run.py', 'skills/waapi-skill/scripts/gateway.py',
        'skills/waapi-skill/wwise_waapi/dispatcher.py']
    root = tmp_path / 'fixture-repo'
    root.mkdir()
    hooks = tmp_path / 'empty-hooks'
    hooks.mkdir()
    def fixture_git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Fixture',
            '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
            '-c', 'core.hooksPath=' + str(hooks), *args], cwd=root, text=True).strip()
    fixture_git('init', '--quiet')
    original_gateway = b"def execute_gateway():\n    return 'original'\n"
    for name, raw in zip(files, (b'# fixture launcher\n', original_gateway, b'# fixture dispatcher\n')):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    fixture_git('add', '--', *files)
    fixture_git('commit', '--quiet', '-m', 'Original fixture sources')
    original_candidate = fixture_git('rev-parse', 'HEAD')
    (root / files[1]).write_bytes(b"def execute_gateway():\n    return 'current'\n")
    fixture_git('add', '--', files[1])
    fixture_git('commit', '--quiet', '-m', 'Different fixture Gateway')
    context = {'candidate': fixture_git('rev-parse', 'HEAD')}
    actual = subprocess.run
    calls = []
    def observed(command, *args, **kwargs):
        if command[:3] == ['git', '--no-replace-objects', 'show']:
            calls.append(command)
        return actual(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', observed)
    cache = {}
    for selected, expected in [(files[:2], 2), (files[:2], 2), (files, 3)]:
        sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in selected}
        binding = {'relevant_sources': selected, **{key: {'source': files[1] + '#execute_gateway'}
            for key in ('construction', 'validation', 'verifier')}}
        proof = {'contract': 'waapi-skill.branch-evidence-equivalence/v1',
            'from_candidate': context['candidate'], 'to_candidate': candidate,
            'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
            'native_route': branch['route'], 'evidence_sha256': descriptor['sha256'],
            'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
            'reviewed_reason': 'Focused unchanged historical source selection', 'sources': sources}
        binding['native_equivalence'] = write_json(tmp_path / f'proof-{len(selected)}.json', proof)
        completion.validate_native_source(context, descriptor, branch, candidate, binding,
            tmp_path, root, historical_sources=cache)
        assert len(calls) == expected

    original = completion.historical_source_seals(root, original_candidate, files[:2], cache)
    assert len(calls) == 5
    assert original[files[1]] == hashlib.sha256(original_gateway).hexdigest()
    assert original[files[1]] != sources[files[1]]
    assert completion.historical_source_seals(root, original_candidate, files[:2], cache) == original
    assert len(calls) == 5
    other_root = tmp_path / 'not-the-fixture-repo'
    other_root.mkdir()
    with pytest.raises(ValueError, match='original native source candidate unavailable'):
        completion.historical_source_seals(other_root, context['candidate'], files[:2], cache)
    assert len(calls) == 6


@pytest.mark.parametrize('damage,reason', [
    ('reference-chain', 'reference-chain mapping differs'),
    ('guard-delta', 'reviewed guard source/branch closure differs'),
    ('guard-host', 'reviewed guard source/branch closure differs'),
    ('guard-replay-value', 'complete original-array public replay'),
    ('guard-replay-missing', 'No such file'),
])
def test_final_reader_rejects_resealed_rtpc_mapping_and_guard_corruption(
        native_field_bundle, inventory, tmp_path, damage, reason):
    import shutil
    from tests.support.runtime_observation_evidence import write_json
    base = tmp_path / 'bundle'
    shutil.copytree(native_field_bundle.parent, base)
    policy = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(base / 'index.json', policy)
    identity = next(key for key in document['bindings'] if key.endswith(
        '/@definition/waapi_definitions.json/definitions/uniqueName' if damage == 'reference-chain'
        else '/items/properties/value'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    if damage == 'reference-chain':
        binding['reference_chain'] = []
    else:
        proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
        review = completion.read_sealed_artifact(proof['source_review'], base)
        if damage == 'guard-delta':
            review['changed_files']['skills/waapi-skill/wwise_waapi/runtime_inspection_business.py']['after'] = '0' * 64
        elif damage == 'guard-host':
            review['scope']['host'] = 'wwise-console'
        elif damage == 'guard-replay-missing':
            (base / review['program_replay']['artifact']).unlink()
        else:
            replay = completion.read_sealed_artifact(review['program_replay'], base)
            replay['gateway']['payload']['agent_result']['return'][7]['value'] = 2000.0
            replay['native_call']['result']['return'][7]['value'] = 2000.0
            review['program_replay'] = write_json(base / 'forged-replay.json', replay)
        # Refresh immediate descriptor seals: rejection must reach the semantic
        # source/host/original-array check, rather than stopping at a checksum.
        proof['source_review'] = write_json(base / 'forged-source-review.json', review)
        binding['runtime_observation_attachment'] = write_json(base / 'forged-proof.json', proof)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = next(row for row in result['obligations'] if row['id'] == identity)
    assert selected['state'] == 'implemented_unverified', json.dumps(selected)
    assert selected['evidence_results']['native']['outcome'] == 'missing'
    assert reason in selected['evidence_results']['native']['reason']


@pytest.mark.parametrize('version,host', [('2021.1', 'wwise-authoring'), ('2022.1', 'wwise-console')])
def test_program_field_publisher_requires_exact_public_host_version(tmp_path, inventory, version, host):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle
    receipt, dispatch, context = public_rtpc_read(tmp_path)
    program = tmp_path / 'capture.json'
    write_program_receipt(program, receipt, dispatch, nodeid='exact-host-version',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    with pytest.raises(ValueError, match='exact public host/version'):
        write_field_bundle(tmp_path / 'bundle', program, None, inventory=inventory,
            version=version, host=host, mode='construction')


@pytest.mark.parametrize('damage', ['phase', 'host', 'version', 'source'])
def test_program_only_final_consumer_checks_exact_capture(tmp_path, inventory, damage):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle, write_json
    receipt, dispatch, context = public_rtpc_read(tmp_path)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='exact-program-only',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2022.1', host='wwise-authoring', mode='construction')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    identity = next(key for key in document['bindings'] if key.endswith('/argsSchema/properties/time'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    program['runtime_read_program'] = json.loads(capture.read_bytes())
    if damage == 'phase':
        program['runtime_read_program']['phase_reports']['teardown'] = 'failed'
    elif damage == 'source':
        program['runtime_read_program']['source_context']['packaged'][
            'skills/waapi-skill/scripts/run.py'] = '0' * 64
    else:
        gateway = program['runtime_read_program']['gateway']
        if damage == 'host':
            gateway['payload']['is_command_line'] = True
        else:
            gateway['payload']['schema_validation']['result']['version'] = '2021.1'
        program['gateway'] = deepcopy(gateway)
    rewritten = write_json(base / 'program.json', program)
    binding['evidence']['program'].update(rewritten)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = next(row for row in result['obligations'] if row['id'] == identity)
    assert selected['state'] == 'implemented_unverified', json.dumps(selected)
    assert selected['evidence_results']['program']['outcome'] == 'missing'
    assert 'exact current public read capture' in selected['evidence_results']['program']['reason']


def test_final_rtpc_consumer_rejects_resealed_public_native_field_mismatch(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle, write_json
    receipt, dispatch, context = public_rtpc_read(tmp_path, '2021.1')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='same-public-native-field',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2021.1', host='wwise-authoring', mode='data')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    identity = next(key for key in document['bindings'] if key.endswith('/items/properties/id'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def evaluate():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row for row in result['obligations'] if row['id'] == identity)
    assert evaluate()['evidence_results']['program'] == {'outcome': 'passed', 'reason': None}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    replacement = '{11111111-1111-1111-1111-111111111111}'
    program['gateway']['payload']['agent_result']['return'][1]['id'] = replacement
    program['runtime_read_program']['gateway'] = deepcopy(program['gateway'])
    public_pointer = binding['gateway_observation_pointer']
    for check in program['branch_assertions'][identity]['checks']:
        if check['pointer'] == public_pointer:
            check['equals'] = replacement
    assert program['native_call']['result']['return'][1]['id'] == RPM
    binding['evidence']['program'].update(write_json(base / 'program.json', program))
    changed = evaluate()
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert 'complete native/public RTPC return' in changed['evidence_results']['program']['reason']


def test_rtpc_capture_contract_cannot_be_bypassed_by_removing_markers(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle, write_json
    receipt, dispatch, context = public_rtpc_read(tmp_path, '2021.1')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='mandatory-rtpc-capture',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2021.1', host='wwise-authoring', mode='construction')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    identity = next(key for key in document['bindings'] if key.endswith('/argsSchema/properties/time'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def evaluate():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row for row in result['obligations'] if row['id'] == identity)
    assert evaluate()['state'] == 'verified'
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    del binding['runtime_read_program']
    del program['runtime_read_program']
    program['gateway']['payload']['is_command_line'] = True
    for section in ('request', 'result'):
        program['gateway']['payload']['schema_validation'][section]['version'] = '2022.1'
    binding['evidence']['program'].update(write_json(base / 'program.json', program))
    changed = evaluate()
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert 'exact current public read capture' in changed['evidence_results']['program']['reason']


def test_rtpc_numeric_position_cannot_be_resealed_as_another_native_time(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle, write_json
    receipt, dispatch, context = public_rtpc_read(tmp_path, '2021.1')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='same-numeric-time',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2021.1', host='wwise-authoring', mode='construction')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    identity = next(key for key in document['bindings'] if key.endswith('/argsSchema/properties/time'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def evaluate():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row for row in result['obligations'] if row['id'] == identity)
    assert evaluate()['state'] == 'verified'
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    program['native_call']['args']['time'] = 23638
    program['runtime_read_program']['native_call'] = deepcopy(program['native_call'])
    for check in program['branch_assertions'][identity]['checks']:
        if check['pointer'] == '/native_call/args/time':
            check['equals'] = 23638
    binding['evidence']['program'].update(write_json(base / 'program.json', program))
    changed = evaluate()
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert 'numeric profiler position' in changed['evidence_results']['program']['reason']


def test_one_optional_rtpc_shape_flow_proves_only_six_exact_branches(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle
    receipt, dispatch, context = public_rtpc_read(tmp_path, '2021.1', rows=[{}])
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='optional-empty-single',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2021.1', host='wwise-authoring', mode='single')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 6
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    assert all(row['requirements'] == ['program'] for row in selected)
    assert sum(row['kind'] == 'optional_presence' for row in selected) == 4


def rtpc_shape_rows(version, mode):
    if mode == 'structure':
        return None  # The existing legal two-row program fixture.
    if mode == 'empty':
        return []
    if version in ('2021.1', '2022.1'):
        return [{}]
    return [{'id': RPM, 'name': '' if version == '2025.1' else 'RPM',
        'gameObjectId': 18446744073709551615, 'value': 1000.0}]


@pytest.fixture(scope='module')
def shape_bundle(tmp_path_factory, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_stage
    root = tmp_path_factory.mktemp('rtpc-shapes')
    captures = {}
    for version in BUILDS:
        for host in ('wwise-console', 'wwise-authoring'):
            for mode in ('structure', 'empty', 'single'):
                path = root / f'{version}-{host}-{mode}'
                receipt, dispatch, context = public_rtpc_read(path, version, host,
                    rows=rtpc_shape_rows(version, mode))
                capture = path / 'capture.json'
                write_program_receipt(capture, receipt, dispatch, nodeid=f'{version}-{host}-{mode}',
                    phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
                captures[version, host, mode] = capture
    return write_field_stage(root / 'bundle', captures, {}, inventory=inventory)


def test_five_version_rtpc_shapes_prove_exact_132_program_only_branches(shape_bundle, inventory):
    policy = json.loads((shape_bundle.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(shape_bundle, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 132
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    assert all(row['requirements'] == ['program'] for row in selected)
    assert sum(row['pointer'].startswith('/argsSchema') or row['pointer'].startswith('/optionsSchema')
        for row in selected) == 40
    assert sum(row['kind'] == 'schema' and row['pointer'].startswith('/resultSchema') for row in selected) == 50


@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('host', ('wwise-console', 'wwise-authoring'))
@pytest.mark.parametrize('mode', ('empty', 'single'))
def test_rtpc_shape_program_emits_after_actual_teardown(tmp_path, request, version, host, mode):
    import os
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.runtime_observation_evidence import write_program_receipt
    receipt, dispatch, context = public_rtpc_read(tmp_path, version, host, rows=rtpc_shape_rows(version, mode))
    destination = Path(os.environ.get('WAAPI_RTPC_FIELD_CAPTURE_DIR', tmp_path)) / f'{version}-{host}-{mode}.json'
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, dispatch, nodeid=request.node.nodeid, phase_reports=phases, source_context=context))


@pytest.mark.parametrize('damage', ('native-extra-key', 'absent-row', 'null-row'))
def test_rtpc_structural_credit_rejects_resealed_wrong_container(shape_bundle, inventory, tmp_path, damage):
    import shutil
    from tests.support.runtime_observation_evidence import write_json
    base = tmp_path / 'bundle'
    shutil.copytree(shape_bundle.parent, base)
    policy = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(base / 'index.json', policy)
    suffix = '/resultSchema/additionalProperties' if damage == 'native-extra-key' else '/items/properties/id/@presence/absent'
    identity = next(key for key in document['bindings'] if key.startswith('2021.1|wwise-authoring|') and key.endswith(suffix))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def evaluate():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row for row in result['obligations'] if row['id'] == identity)
    assert evaluate()['state'] == 'verified'
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    if damage == 'native-extra-key':
        assert 'complete' in program['gateway']['payload']['agent_result']  # Intentional public metadata.
        program['native_call']['result']['invented'] = True
        for check in program['branch_assertions'][identity]['checks']:
            if check['pointer'] == '/native_call/result':
                check['equals'] = deepcopy(program['native_call']['result'])
    else:
        rows = [] if damage == 'absent-row' else [None]
        program['native_call']['result']['return'] = deepcopy(rows)
        result = program['gateway']['payload']['agent_result']
        result.update({'return': deepcopy(rows), 'returned_count': len(rows), 'total_count': len(rows)})
        checks = program['branch_assertions'][identity]['checks']
        parent = binding['gateway_observation_pointer'].rsplit('/', 1)[0]
        program['branch_assertions'][identity]['checks'] = [check for check in checks if check['pointer'] != parent]
        if damage == 'null-row':
            program['branch_assertions'][identity]['checks'].append({'pointer': parent, 'equals': None})
    program['runtime_read_program']['native_call'] = deepcopy(program['native_call'])
    program['runtime_read_program']['gateway'] = deepcopy(program['gateway'])
    binding['evidence']['program'].update(write_json(base / 'forged-program.json', program))
    changed = evaluate()
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    reason = changed['evidence_results']['program']['reason']
    assert ('native object structure predicate' in reason if damage == 'native-extra-key' else
        'existing native/public row' in reason or 'index out of range' in reason)


@pytest.mark.parametrize('damage,reason', [
    ('request-position', 'public profiler-position contract'),
    ('proxy-pointer', 'native object structure predicate'),
])
def test_rtpc_capture_rejects_resealed_request_or_structure_proxy(shape_bundle, inventory, tmp_path, damage, reason):
    import shutil
    from tests.support.runtime_observation_evidence import write_json
    base = tmp_path / 'bundle'
    shutil.copytree(shape_bundle.parent, base)
    policy = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(base / 'index.json', policy)
    identity = next(key for key in document['bindings'] if key.startswith('2021.1|wwise-authoring|')
        and key.endswith('/argsSchema/additionalProperties'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def evaluate():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row for row in result['obligations'] if row['id'] == identity)
    assert evaluate()['state'] == 'verified'
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    if damage == 'request-position':
        argv = program['gateway']['argv']
        argv[argv.index('--profiler-position') + 1] = 'not-a-position'
        binding['input']['gateway_argv'] = deepcopy(argv)
    else:
        program['native_call']['args']['invented'] = True
        program['valid_proxy'] = {'time': 23637}
        binding['program_observation_pointer'] = '/valid_proxy'
        for check in program['branch_assertions'][identity]['checks']:
            if check['pointer'] == '/native_call/args':
                check['equals'] = deepcopy(program['native_call']['args'])
    program['runtime_read_program']['gateway'] = deepcopy(program['gateway'])
    program['runtime_read_program']['native_call'] = deepcopy(program['native_call'])
    binding['evidence']['program'].update(write_json(base / 'forged-program.json', program))
    changed = evaluate()
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert reason in changed['evidence_results']['program']['reason']


def rtpc_scalar_rows():
    return [
        {'id': '{aBcD1234-16e7-4B8A-b9ca-7BF10ad315B4}', 'name': 'Engine_Load', 'gameObjectId': 0, 'value': 0.0},
        {'id': RPM, 'name': 'RPM', 'gameObjectId': 18446744073709551615, 'value': 1000.0},
        {'id': RPM, 'name': 'CC #1: Modulation', 'gameObjectId': 1, 'value': 1.0},
    ]


def test_one_rtpc_scalar_flow_checks_exact_pinned_predicates(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle, write_json
    receipt, dispatch, context = public_rtpc_read(tmp_path, rows=rtpc_scalar_rows())
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='rtpc-scalars',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2022.1', host='wwise-authoring', mode='scalar')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 4
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    identity = next(key for key in document['bindings'] if key.endswith('/definitions/guid/pattern'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    # Update every immediate seal/assertion: the selected reflected predicate,
    # rather than JSON equality or a stale checksum, must reject this string.
    for target in (program, program['runtime_read_program']):
        target['native_call']['result']['return'][0]['id'] = 'malformed-guid'
        target['gateway']['payload']['agent_result']['return'][0]['id'] = 'malformed-guid'
    for check in program['branch_assertions'][identity]['checks']:
        if check['pointer'].endswith('/return/0/id'):
            check['equals'] = 'malformed-guid'
    binding['evidence']['program'].update(write_json(base / 'program.json', program))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    changed = next(row for row in result['obligations'] if row['id'] == identity)
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert 'pinned scalar predicate' in changed['evidence_results']['program']['reason']


@pytest.mark.parametrize('version', BUILDS)
def test_public_rtpc_discloses_legacy_label_compatibility_after_row_validation(tmp_path, version):
    from wwise_waapi.builders.schema import validate_semantic_result
    receipt, dispatch, _ = public_rtpc_read(tmp_path, version, rows=rtpc_scalar_rows())
    metadata = receipt['payload']['schema_validation']['result']
    rules = metadata.get('compatibility_rules', [])
    assert receipt['payload']['agent_result']['return'][2]['name'] == 'CC #1: Modulation'
    assert metadata['unresolved_refs']  # Conservative traversal remains accurately disclosed.
    assert not validate_semantic_result(URI, dispatch['result'], version=version).compatibility_rules
    if version == '2025.1':
        assert not rules
    else:
        assert len(rules) == 1
        assert rules[0] == {
            'rule': 'rtpc-legacy-name-label-preservation',
            'section': '$.return[*].name', 'definition': 'waapi_definitions.json#/definitions/uniqueName',
            'reflected_pattern': '^[a-zA-Z_]+[a-zA-Z_0-9()]*$',
            'enforced_type': 'string', 'pattern_enforced': False,
            'behavior': 'Preserve native labels unchanged, including labels outside the reflected pattern',
        }


def test_one_rtpc_cursor_flow_proves_normalized_construction_and_rejects_resealed_trace(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_bundle, write_json
    trace = []
    receipt, dispatch, context = public_rtpc_read(tmp_path, position='capture-latest', native_reads=trace)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, dispatch, nodeid='rtpc-cursor', native_reads=trace,
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    index = write_field_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2022.1', host='wwise-authoring', mode='cursor-capture')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 4
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    identity = next(key for key in document['bindings'] if key.endswith('/profilerCursor/enum/1'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    relevant = program['runtime_read_program']['native_reads']
    cursor = next(row for row in relevant if row['uri'].endswith('getCursorTime'))
    cursor['result']['return'] += 1
    binding['evidence']['program'].update(write_json(base / 'program.json', program))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    changed = next(row for row in result['obligations'] if row['id'] == identity)
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert 'ordered cursor normalization trace' in changed['evidence_results']['program']['reason']


@pytest.fixture(scope='module')
def frontier_bundle(tmp_path_factory, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_field_stage
    root = tmp_path_factory.mktemp('rtpc-frontier')
    captures = {}
    for version in BUILDS:
        for host in ('wwise-console', 'wwise-authoring'):
            for mode in ('scalar', 'cursor-capture', 'cursor-user'):
                path = root / f'{version}-{host}-{mode}'
                trace = []
                position = {'cursor-capture': 'capture-latest', 'cursor-user': 'user-cursor'}.get(mode, '23637')
                receipt, dispatch, context = public_rtpc_read(path, version, host, position,
                    rows=rtpc_scalar_rows() if mode == 'scalar' else None, native_reads=trace)
                capture = path / 'capture.json'
                write_program_receipt(capture, receipt, dispatch, nodeid=f'{version}-{host}-{mode}',
                    native_reads=trace if mode.startswith('cursor-') else None,
                    phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
                captures[version, host, mode] = capture
    return write_field_stage(root / 'bundle', captures, {}, inventory=inventory)


def test_five_version_rtpc_frontier_proves_exact_88_program_branches(frontier_bundle, inventory):
    policy = json.loads((frontier_bundle.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(frontier_bundle, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 88
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    assert sum(row['kind'] == 'constraint' for row in selected) == 38
    assert sum(row['pointer'].startswith('/argsSchema') for row in selected) == 50
    assert all(row['requirements'] == ['program'] for row in selected)


@pytest.mark.parametrize('damage', ('minimum-bool', 'maximum-overflow', 'name-domain',
    'trace-missing', 'trace-enum', 'trace-order', 'trace-extra'))
def test_rtpc_frontier_consumer_rejects_resealed_scalar_and_trace_damage(frontier_bundle, inventory, tmp_path, damage):
    import shutil
    from tests.support.runtime_observation_evidence import write_json
    base = tmp_path / 'bundle'
    shutil.copytree(frontier_bundle.parent, base)
    policy = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(base / 'index.json', policy)
    suffix = {'minimum-bool': '/gameObject/minimum', 'maximum-overflow': '/gameObject/maximum',
        'name-domain': '/uniqueName/pattern'}.get(damage, '/profilerCursor/enum/1')
    identity = next(key for key in document['bindings'] if key.startswith('2022.1|wwise-authoring|') and key.endswith(suffix))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    if damage.startswith('trace-'):
        trace = program['runtime_read_program']['native_reads']
        cursor = next(row for row in trace if row['uri'].endswith('getCursorTime'))
        final = next(row for row in trace if row['uri'] == URI)
        if damage == 'trace-missing':
            del program['runtime_read_program']['native_reads']
        elif damage == 'trace-enum':
            cursor['args']['cursor'] = 'user'
        elif damage == 'trace-order':
            a, b = cursor['ordinal'], final['ordinal']
            trace[a], trace[b] = final, cursor
            for index, row in enumerate(trace):
                row['ordinal'] = index
        else:
            trace.append({**deepcopy(cursor), 'ordinal': len(trace)})
        expected = 'cursor normalization'
    else:
        pointer = binding['observation_pointer']
        index = int(pointer.split('/')[-2])
        field = pointer.rsplit('/', 1)[1]
        value = {'minimum-bool': False, 'maximum-overflow': 18446744073709551616,
            'name-domain': 'CC #1: Modulation'}[damage]
        for target in (program, program['runtime_read_program']):
            target['native_call']['result']['return'][index][field] = value
            target['gateway']['payload']['agent_result']['return'][index][field] = value
        for check in program['branch_assertions'][identity]['checks']:
            if check['pointer'] in (pointer, binding['gateway_observation_pointer']):
                check['equals'] = value
        expected = 'pinned scalar predicate'
    binding['evidence']['program'].update(write_json(base / 'program.json', program))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = next(row for row in result['obligations'] if row['id'] == identity)
    assert selected['evidence_results']['program']['outcome'] == 'missing', json.dumps(selected)
    assert expected in selected['evidence_results']['program']['reason']


@pytest.mark.parametrize('returned', (-1, True, 1.5))
def test_rtpc_invalid_cursor_response_stops_before_rtpc_dispatch(tmp_path, returned):
    calls = []
    class Client(_RuntimeControlDraftClient):
        def call(self, uri, args=None, options=None):
            calls.append(uri)
            if uri == 'ak.wwise.core.profiler.getCursorTime':
                return {'return': returned}
            return super().call(uri, args, options)
    client = Client(tmp_path, version='2022.1')
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'core-call', URI, '--profiler-position', 'capture-latest'],
        env=_env(tmp_path, version='2022.1'), client_factory=lambda _: client)
    assert code != 0, payload
    assert calls.count('ak.wwise.core.profiler.getCursorTime') == 1, payload
    assert URI not in calls


@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('host', ('wwise-console', 'wwise-authoring'))
@pytest.mark.parametrize('mode', ('scalar', 'cursor-capture', 'cursor-user'))
def test_rtpc_frontier_program_emits_after_actual_teardown(tmp_path, request, version, host, mode):
    import os
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.runtime_observation_evidence import write_program_receipt
    trace = []
    position = {'cursor-capture': 'capture-latest', 'cursor-user': 'user-cursor'}.get(mode, '23637')
    receipt, dispatch, context = public_rtpc_read(tmp_path, version, host, position,
        rows=rtpc_scalar_rows() if mode == 'scalar' else None, native_reads=trace)
    destination = Path(os.environ.get('WAAPI_RTPC_FIELD_CAPTURE_DIR', tmp_path)) / f'{version}-{host}-{mode}.json'
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, dispatch, nodeid=request.node.nodeid, phase_reports=phases, source_context=context,
        native_reads=trace if mode.startswith('cursor-') else None))

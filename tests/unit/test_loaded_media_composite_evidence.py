"""Older API availability and9262 semantic support retain separate attribution."""
from copy import deepcopy
import gzip
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
from tests.unit.test_loaded_media_runtime_evidence import ROW, URI

BUILDS = {'2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056'}


def public_read(path, version, rows, position):
    path.mkdir(parents=True)
    context = runtime.program_source_context(flow=URI)
    client = _RuntimeControlDraftClient(path, version=version)
    fallback, trace = client.call, []
    def call(uri, args=None, options=None):
        result = ({'return': deepcopy(rows)} if uri == URI else
                  {'return': 99328} if uri.endswith('.getCursorTime') else fallback(uri, args, options))
        if uri == 'ak.wwise.core.getInfo':
            year, major, minor, build = map(int, BUILDS[version].split('.'))
            result['version'].update(year=year, major=major, minor=minor, build=build,
                                     displayName='v' + BUILDS[version])
        trace.append({'ordinal': len(trace), 'uri': uri, 'args': deepcopy(args),
                      'options': deepcopy(options), 'result': deepcopy(result)})
        return result
    client.call = call
    argv = ['core-call', URI, '--profiler-position', position, '--max-results', '64']
    code, payload = gateway.execute_gateway(['--state-dir', str(path / 'state'), *argv],
        env=_env(path, version=version), client_factory=lambda _: client)
    assert code == 0, payload
    assert payload['agent_result']['return'] == rows
    return {'argv': argv, 'exit_code': code, 'payload': payload}, {
        key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}, context, trace


@pytest.fixture(scope='module')
def inventory():
    stored = json.loads((audit.ROOT / 'docs/branch-coverage-inventory.json').read_bytes())
    packed = json.loads(gzip.decompress((audit.ROOT / 'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    routes = [r for r in stored['native_coverage']['routes'] if r['version'] in BUILDS
              and r['host'] == 'wwise-authoring' and r['uri'] == URI]
    ids = {r['id'] for r in routes}
    rows = []
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']] not in ids:
            continue
        row = dict(encoded)
        row.update(packed['contexts'][row.pop('context')])
        route = packed['routes'][row['route']]
        row.update(route=route, id=route + '|' + row['pointer'],
                   shape_sha256=packed['shapes'][row.pop('shape')])
        rows.append(row)
    return {'routes': [r for r in stored['routes'] if r['id'] in {route['public_route'] for route in routes}],
            'native_coverage': {'candidate_sha256': 'f' * 64, 'catalogs': stored['native_coverage']['catalogs'],
                                'routes': routes, 'obligations': rows}}


@pytest.mark.parametrize('version', ('2023.1', '2024.1'))
def test_older_loaded_media_composite_public_teardown_consumer(request, tmp_path, inventory, version):
    families = [([ROW], '99328'), ([], '0'),
                ([{**ROW, 'fileName': '', 'format': '', 'soundBank': ''}] * 2, '0'),
                ([ROW], 'capture-latest'), ([ROW], 'user-cursor')]
    captures = [public_read(tmp_path / str(i), version, rows, position)
                for i, (rows, position) in enumerate(families)]
    def finalize(phases):
        from tests.support.loaded_media_runtime_evidence import write_composite_bundle
        paths = []
        for i, (receipt, native, context, trace) in enumerate(captures):
            path = tmp_path / ('capture-' + str(i) + '.json')
            runtime.write_program_receipt(path, receipt, native, nodeid=request.node.nodeid,
                phase_reports=phases, source_context=context, native_reads=trace,
                public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
            paths.append(path)
        index = write_composite_bundle(tmp_path / 'bundle', paths, inventory=inventory, version=version)
        policies = json.loads((index.parent / 'requirements.json').read_bytes())
        document, base, _ = audit.portable_binding_inputs(index, policies)
        result = completion.evaluate_coverage(audit.ROOT, inventory, document, digest=audit.digest,
            evidence_base=base, requirements_document=policies)
        rows = [r for r in result['obligations'] if r['route'].startswith(version + '|')]
        assert len(rows) == 31
        assert {r['state'] for r in rows} == {'verified'}, json.dumps(rows)
        anchor = next(r for r in rows if r['id'].endswith('/@cardinality/single'))
        assert anchor['representative_native_support'] == {
            'catalog_build': BUILDS[version], 'availability_build': BUILDS[version],
            'observed_build': '2025.1.11.9262', 'basis': 'exact_reviewed_cross_version_composite_support',
            'older_nonempty_native_execution': False, 'older_parent_outcome': 'BLOCKED'}
    register_exact_evidence_finalizer(request.node, finalize)

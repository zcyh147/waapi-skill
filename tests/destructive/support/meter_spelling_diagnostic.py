"""Four fixed developer observations; never a public native-input interface."""
from copy import deepcopy
import hashlib
import json
import time

from wwise_waapi.builders.schema import validate_resolved_semantic_payload, validate_resolved_semantic_result
from wwise_waapi.headless import _run_with_timeout

URI = 'ak.wwise.core.profiler.getMeters'
SELECTORS = (None, 'states', 'suppportsRandomizer', 'supportsRandomizer')
OUTCOMES = ('profiler-meter-default-diagnostic', 'profiler-meter-states-diagnostic',
    'profiler-meter-randomizer-typo-diagnostic', 'profiler-meter-randomizer-comparator-diagnostic')
MAX_PACKET_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 10


def collect_meter_spellings(batch, report, destination, persist, *, time_ms, owned_bus):
    """Read only the two pinned anomalies and comparator on the exact owned host."""
    from waapi import WaapiClient
    from waapi.wamp.interface import WaapiRequestFailed

    nodeid, = batch.selected_nodeids
    runtime = batch.node_runtimes[nodeid]
    assert runtime.version == '2025.1' and batch.info['isCommandLine'] is False
    assert type(time_ms) is int and time_ms >= 0
    diagnostic = report['meter_spelling_diagnostic'] = {
        'contract': 'waapi-skill.owned-meter-spelling-diagnostic/v1',
        'business_effect_verified': False, 'alias_equivalence_verified': False,
        'coverage_credit': 'none_pending_semantics', 'observations': [],
        'limits': {'getMeters_reads': 4, 'packet_bytes': MAX_PACKET_BYTES, 'total_packet_bytes': 4 * MAX_PACKET_BYTES, 'call_seconds': TIMEOUT_SECONDS},
        'scope': 'Exact issued requests/returned keys on this owned Bus/frame only; omission and equality establish no alias'}
    context = {'candidate': batch.candidate, 'info': deepcopy(batch.info),
        'endpoint': {'host': runtime.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url},
        'sandbox_project': str(runtime.sandbox.sandbox_project), 'nodeid': nodeid,
        'owned_bus': {key: owned_bus[key] for key in ('id', 'name')}, 'time_ms': time_ms}
    client = None

    def bounded(operation):
        return _run_with_timeout(operation, TIMEOUT_SECONDS, TimeoutError, 'Meter diagnostic call timed out')

    def session():
        info = bounded(lambda: client.call('ak.wwise.core.getInfo'))
        assert isinstance(info, dict) and all(info.get(key) == batch.info.get(key)
            for key in ('isCommandLine', 'processId', 'sessionId', 'version')), 'Meter diagnostic owned session changed'
        assert all(info.get(key) is not None for key in ('processId', 'sessionId'))
        return info

    try:
        client = _run_with_timeout(lambda: WaapiClient(url=runtime.lifecycle.waapi_url, allow_exception=True),
            TIMEOUT_SECONDS, TimeoutError, 'Meter diagnostic connection timed out',
            late_result_cleanup=lambda late: late.disconnect())
        initial_info = session()
        for index, (selector, outcome) in enumerate(zip(SELECTORS, OUTCOMES, strict=True)):
            request = {'uri': URI, 'args': {'time': time_ms}}
            if selector is not None:
                request['options'] = {'return': ['id', 'name', selector]}
            packet = {'contract': 'waapi-skill.owned-meter-spelling-call/v1', 'context': deepcopy(context),
                'request': request, 'info_before': initial_info, 'started_at_unix_ns': time.time_ns()}
            observation = {'selector': selector, 'native_status': 'not_dispatched', 'observation_status': 'BLOCKED',
                'request_schema': {'status': 'BLOCKED'}, 'result_schema': {'status': 'not_returned'}}
            diagnostic['observations'].append(observation)
            continue_session = True
            try:
                try:
                    proof = validate_resolved_semantic_payload(URI, request['args'], request.get('options', {}),
                        version='2025.1', authoring_ui_profile=True)
                    observation['request_schema'] = {'status': 'PASS', 'proof': proof.as_dict()}
                except Exception as exc:
                    observation['request_schema'] = {'status': 'FAIL', 'error': str(exc)[:4096]}
                    raise
                try:
                    observation['native_status'] = 'dispatch_attempted'
                    packet['result'] = bounded(lambda: client.call(URI, request['args'], **(
                        {'options': request['options']} if 'options' in request else {})))
                    observation['native_status'] = 'returned' if packet['result'] is not None else 'missing_response'
                except WaapiRequestFailed as exc:
                    packet['native_error'] = {'type': type(exc).__name__, 'message': str(exc),
                        'uri': exc.uri, 'kwargs': deepcopy(exc.kwargs), 'args': deepcopy(exc._error.args)}
                    observation['native_status'] = 'native_rejected' if (str(exc.uri).startswith('ak.')
                        or exc.uri in ('wamp.error.invalid_argument', 'wamp.error.invalid_uri',
                            'wamp.error.no_such_procedure')) else 'unattributed_error'
                packet['info_after'] = initial_info = session()
                if observation['native_status'] == 'native_rejected':
                    observation['observation_status'] = 'PASS'
                elif observation['native_status'] == 'returned':
                    try:
                        proof = validate_resolved_semantic_result(URI, packet['result'], version='2025.1')
                        observation['result_schema'] = {'status': 'PASS', 'proof': proof.as_dict()}
                    except Exception as exc:
                        observation['result_schema'] = {'status': 'FAIL', 'error': str(exc)[:4096]}
                        raise
                    rows = packet['result']['meters']
                    matches = [i for i, row in enumerate(rows) if row['object'].get('id') == owned_bus['id']]
                    observation['owned_bus_rows'] = matches
                    assert matches and all(rows[i]['object'].get('name') == owned_bus['name'] for i in matches), 'Owned Bus absent from diagnostic frame'
                    observation['owned_bus_selected_key_present'] = (
                        [selector in rows[i]['object'] for i in matches] if selector else None)
                    observation['owned_bus_returned_keys'] = [list(rows[i]['object']) for i in matches]
                    observation['observation_status'] = 'PASS'
                else:
                    raise ValueError('Meter diagnostic native outcome is not attributable')
            except Exception as exc:
                packet['diagnostic_error'] = {'type': type(exc).__name__, 'message': str(exc)}
                # A schema/attribution failure with a proven live session can
                # retain the other selectors. A transport/context failure cannot.
                continue_session = 'info_after' in packet
            finally:
                packet['finished_at_unix_ns'] = time.time_ns()
                raw = (json.dumps(packet, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()
                if len(raw) > MAX_PACKET_BYTES:
                    observation['observation_status'] = 'BLOCKED'
                    observation['packet_error'] = {'reason': 'complete diagnostic packet exceeds bound', 'bytes': len(raw)}
                    continue_session = False
                else:
                    name = f'meter-spelling-{index}.json'
                    with (destination / name).open('xb') as stream:
                        stream.write(raw)
                    observation['artifact'] = {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
                report['outcomes'][outcome] = {'outcome': observation['observation_status'], 'evidence': deepcopy(observation)}
                persist()
            if not continue_session:
                break
    finally:
        if client is not None:
            try:
                disconnected = bounded(client.disconnect)
                diagnostic['client_disconnect'] = {'call_completed': True, 'result': disconnected}
            except Exception as exc:
                report['cleanup']['errors'].append({'action': 'meter-diagnostic-disconnect',
                    'type': type(exc).__name__, 'message': str(exc)[:4096]})
        persist()


def meter_packet_present(root, outcome, observation):
    """The final writer requires the exact bounded original call packet."""
    if root is None or outcome not in OUTCOMES:
        return False
    descriptor = observation.get('evidence', {}).get('artifact', {})
    name = f'meter-spelling-{OUTCOMES.index(outcome)}.json'
    if descriptor.get('path') != name:
        return False
    try:
        with (root / name).open('rb') as stream:
            raw = stream.read(MAX_PACKET_BYTES + 1)
    except OSError:
        return False
    return (len(raw) <= MAX_PACKET_BYTES and len(raw) == descriptor.get('bytes')
        and hashlib.sha256(raw).hexdigest() == descriptor.get('sha256'))

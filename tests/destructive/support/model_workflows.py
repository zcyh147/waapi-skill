"""Owned model witnesses; closed Gateway plans and acknowledged Topic delivery."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from wwise_waapi.canonical import canonical_sha256

URI = 'ak.wwise.ui.'
COMMON_NODE = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_model_2024_state_click'
FILE_NODE = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_model_2025_file_state_toggle'
NODES = {COMMON_NODE: '2024.1', FILE_NODE: '2025.1'}
CONTRACT = 'waapi-skill.owned-model-cohort/v1'
FILENAME = 'model-workflow-observations.json'
OBSERVER_SECONDS = 10.0
WEAK_STRENGTH = 'native_result_only_observable_effect_unfinished'
STATE_STRENGTH = 'independent_widget_state_observation'
CREATIONS = {'model.registerWafm': 'template', 'window.create': 'window', 'model.createHandle': 'model'}


def template_plan(version):
    def assignment(name, kind, value):
        return {'attribute': name, 'value': {'kind': kind, kind: value}}
    unit = {'template_key': 'Owned', 'root_widget': 'Root',
        'widgets': [{'key': 'State', 'kind': 'Checkbox', 'attributes': [
            assignment('Checked', 'boolean', False), assignment('Text', 'text', 'Owned state')]}],
        'layouts': [{'key': 'Root', 'kind': 'BinLayout' if version == '2025.1' else 'AnchorLayout',
            'attributes': [assignment('Width', 'integer', 400), assignment('Height', 'integer', 160)],
            'children': [{'widget': 'State'}]}]}
    if version == '2024.1':
        unit['widgets'].append({'key': 'Trigger', 'kind': 'PushButton',
            'attributes': [assignment('Text', 'text', 'Owned signal')]})
        unit['layouts'][0]['children'] = [
            {'widget': key, 'positions': [0, index * 40, 160, 30], 'anchors': ['side-left', 'side-top']}
            for index, key in enumerate(('State', 'Trigger'))]
        return {**unit, 'registration_medium': 'inline', 'registration_form': 'template_attribute'}
    assert version == '2025.1'
    return {'templates': [unit], 'registration_medium': 'file'}


def expected_operations(version):
    return ['model.registerWafm', 'window.create', 'model.createHandle', 'window.present',
        *(['model.getState'] if version == '2024.1' else []), 'model.setState', 'signal.emit',
        'model.destroyHandle', 'window.close']


def _prepare(call, suffix, plan, report):
    schema = call(['request-schema', URI + suffix])
    started = call(schema['continuation']['gateway_argv'])
    draft, authority = started['draft'], started['task_authority']
    declared = call(['draft-declare-model-plan', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(draft['revision']), '--plan', json.dumps(plan)])
    checked = call(['draft-check', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision'])])
    preview = call(['preview-from-draft', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])])
    tx = preview['transaction_id']
    entry = {'operation': URI + suffix, 'transaction_id': tx, 'plan': deepcopy(plan),
        'execute_attempted': False, 'executed': False, 'verification': None}
    report['effects'].append(entry)
    shown = call(['transaction-show', tx])
    call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
    return entry


def _execute(call, entry):
    assert not entry['execute_attempted'], 'Never repeat an owned model mutation'
    entry['execute_attempted'] = True
    payload = call(['execute', entry['transaction_id']])
    assert payload['state'] == 'executed_unverified', payload
    entry['executed'] = True
    return payload


def _verify(call, entry):
    payload = call(['verify', entry['transaction_id']])
    strong = entry['operation'] in {URI + 'model.getState', URI + 'model.setState'}
    verification = payload['verification']
    assert payload['verified'] is strong and verification['business_state_verified'] is strong, payload
    assert verification['verification_strength'] == (STATE_STRENGTH if strong else WEAK_STRENGTH), payload
    entry['verification'] = {'business_state_verified': strong,
        'verification_strength': verification['verification_strength']}
    return payload


def _resource(payload):
    result = payload['agent_result']
    if 'business_result' in result:
        result = result['business_result']
    assert result['observable_effect_verified'] is False and result['resource_handle'].startswith('ar1-'), result
    return result['resource_handle']


def _retirement(state_root, handle, transaction_id):
    path = state_root / 'authoring-resources-v1' / (handle + '.consumed.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    digest = record.pop('sha256', None)
    assert (digest == canonical_sha256(record) and record['handle'] == handle
        and record['consumed_by'] == transaction_id and record['outcome'] == 'dispatch_reserved_once'), record
    return {'handle': handle, 'transaction_id': transaction_id, 'gateway_retired': True,
        'native_disappearance_independently_verified': False}


def _observe_emit(batch, call, entry, report, *, nodeid, model, widget, signal):
    topic = URI + 'signal.' + signal
    schema = call(['topic-schema', topic])
    digest = schema['continuation']['contract_binding']['value']
    observation = report['signal'] = {'topic': topic, 'model': model, 'widget': widget,
        'transaction_id': entry['transaction_id'], 'contract_digest': digest,
        'ack_before_execute': False, 'event': None, 'target_completed': False, 'cleanup': 'unknown'}
    endpoint = {'host': batch.runtime.host, 'port': batch.runtime.port,
        'url': f'ws://{batch.runtime.host}:{batch.runtime.port}/waapi'}
    expected = None

    def observe(record):
        nonlocal expected
        if record.get('record_type') == 'started':
            assert not observation['ack_before_execute'], 'Duplicate ACK cannot repeat an emission'
            assert (record.get('contract') == 'waapi-skill.topic-stream/v1' and record.get('ok') is True
                and record.get('status') == 'streaming' and record.get('topic') == topic
                and record.get('topic_contract_digest') == digest and record.get('endpoint') == endpoint
                and record.get('detected_version') == batch.runtime.version
                and record.get('is_command_line') is False and record.get('event_count_limit') == 1), record
            expected = record.get('match')
            assert isinstance(expected, dict) and set(expected) == {'handleID', 'widgetID'} and expected['widgetID'] == widget
            observation['ack_before_execute'] = True
            _execute(call, entry)
        elif record.get('record_type') == 'event':
            assert observation['ack_before_execute'] and entry['executed']
            assert observation['event'] is None and record['event'] == expected, record
            observation['event'] = deepcopy(record['event'])

    code, terminal = batch.node_signal_stream(nodeid, topic=topic, digest=digest,
        model=model, widget=widget, stream_sink=observe)
    observation.update(cleanup=terminal.get('cleanup', 'unknown'), terminal_exit_code=code,
        target_completed=terminal.get('monitoring_outcome', {}).get('target_completed') is True)
    assert (code == 0 and observation['ack_before_execute'] and observation['event'] is not None
        and observation['target_completed'] and observation['cleanup'] == 'unsubscribed'), terminal
    _verify(call, entry)


def collect_model_workflow(batch, call, *, nodeid):
    assert NODES.get(nodeid) == batch.runtime.version
    version = batch.runtime.version
    runtime = batch.node_runtimes[nodeid]
    destination = Path(runtime.runner_environment['WWISE_EVIDENCE_DIR']) / FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {'contract': CONTRACT, 'nodeid': nodeid, 'candidate': batch.candidate, 'version': version,
        'complete': False, 'effects': [], 'signal': None, 'state_observed': False,
        'resources': {}, 'recoveries': [], 'retirements': [], 'errors': [],
        'cleanup': {'local_resources_retired': False, 'session_cleanup': 'pending_batch_teardown',
            'template_cleanup': 'owning_Authoring_session_end_no_unregister'},
        'boundaries': {'visible_window_effect_verified': False, 'native_destroy_close_effect_verified': False,
            'emit_result_is_delivery_proof': False, 'verification_strength': WEAK_STRENGTH}}
    primary = None
    cleanup_errors = []

    def effect(suffix, plan):
        entry = _prepare(call, suffix, plan, report)
        _execute(call, entry)
        verified = _verify(call, entry)
        if suffix in CREATIONS:
            report['resources'][CREATIONS[suffix]] = _resource(verified)
        return entry, verified

    try:
        effect('model.registerWafm', template_plan(version))
        effect('window.create', {'title': 'WAAPI Skill owned model', 'width': 400, 'height': 160})
        effect('model.createHandle', {'window': report['resources']['window'],
            'template': report['resources']['template'], **({'template_key': 'Owned'} if version == '2025.1' else {})})
        model = report['resources']['model']
        effect('window.present', {'window': report['resources']['window']})
        if version == '2024.1':
            _, observed = effect('model.getState', {'model': model,
                'widgets': [{'widget': 'State', 'attributes': ['Checked']}]})
            assert observed['agent_result']['business_result']['widgets'] == [
                {'widget': 'State', 'attributes': {'Checked': False}}], observed
        effect('model.setState', {'model': model, 'widgets': [{'widget': 'State', 'attributes': [
            {'attribute': 'Checked', 'value': {'kind': 'boolean', 'boolean': True}}]}]})
        report['state_observed'] = True
        signal, widget = ('click', 'Trigger') if version == '2024.1' else ('toggle', 'State')
        entry = _prepare(call, 'signal.emit', {'model': model, 'widget': widget, 'signal': signal}, report)
        _observe_emit(batch, call, entry, report, nodeid=nodeid, model=model, widget=widget, signal=signal)
    except BaseException as exc:
        primary = exc
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:2048]})
    finally:
        # Only known successful creations can recover cleanup authority. An
        # unknown creation or failed unsubscribe belongs to the owning teardown.
        cleanup_safe = (primary is None or isinstance(primary, Exception)) and (
            report['signal'] is None or report['signal']['cleanup'] == 'unsubscribed')
        try:
            for entry in report['effects']:
                suffix = entry['operation'].removeprefix(URI)
                if suffix not in CREATIONS:
                    continue
                if entry['execute_attempted'] and not entry['executed']:
                    cleanup_safe = False
                kind = CREATIONS[suffix]
                if entry['executed'] and kind not in report['resources']:
                    recovered = call(['authoring-resource', entry['transaction_id']])
                    report['resources'][kind] = _resource(recovered)
                    report['recoveries'].append({'kind': kind, 'transaction_id': entry['transaction_id']})
            if cleanup_safe:
                for kind, suffix in [('model', 'model.destroyHandle'), ('window', 'window.close')]:
                    if kind not in report['resources']:
                        continue
                    entry, _ = effect(suffix, {kind: report['resources'][kind]})
                    report['retirements'].append(_retirement(runtime.owned_root / 'setup-state',
                        report['resources'][kind], entry['transaction_id']))
                report['cleanup']['local_resources_retired'] = bool(report['resources'].get('window'))
        except BaseException as exc:
            cleanup_errors.append(exc)
            report['errors'].append({'phase': 'cleanup', 'type': type(exc).__name__, 'message': str(exc)[:2048]})
        report['complete'] = primary is None and not cleanup_errors and report['cleanup']['local_resources_retired']
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        assert len(raw) <= 65536, 'Owned model report exceeds its fixed byte bound'
        destination.write_bytes(raw)
    if primary is not None and cleanup_errors:
        raise BaseExceptionGroup('Model witness and owned cleanup failed', [primary, *cleanup_errors])
    if primary is not None:
        raise primary
    if cleanup_errors:
        raise BaseExceptionGroup('Owned model cleanup failed', cleanup_errors)
    return report


def validate_model_report(report, *, nodeid, candidate, version, receipts, state_root):
    """The final category writer joins independent outcomes to public receipts."""
    if (report.get('contract') != CONTRACT or report.get('nodeid') != nodeid
            or report.get('candidate') != candidate or report.get('version') != version or NODES.get(nodeid) != version
            or report.get('complete') is not True or report.get('errors') or report.get('state_observed') is not True
            or report.get('cleanup') != {'local_resources_retired': True,
                'session_cleanup': 'pending_batch_teardown', 'template_cleanup': 'owning_Authoring_session_end_no_unregister'}
            or report.get('boundaries') != {'visible_window_effect_verified': False,
                'native_destroy_close_effect_verified': False, 'emit_result_is_delivery_proof': False,
                'verification_strength': WEAK_STRENGTH}):
        raise ValueError('Owned model cohort lacks its completed context and truthful effect boundaries')
    effects = report.get('effects', [])
    if ([row.get('operation') for row in effects] != [URI + suffix for suffix in expected_operations(version)]
            or len({row.get('transaction_id') for row in effects}) != len(effects)):
        raise ValueError('Owned model effects differ from the approved exact transaction sequence')
    for effect in effects:
        tx = effect['transaction_id']
        executed = [r for r in receipts if r.get('argv') == ['execute', tx]]
        verified = [r for r in receipts if r.get('argv') == ['verify', tx]]
        strong = effect['operation'] in {URI + 'model.getState', URI + 'model.setState'}
        expected = {'business_state_verified': strong,
            'verification_strength': STATE_STRENGTH if strong else WEAK_STRENGTH}
        if (effect.get('executed') is not True or effect.get('execute_attempted') is not True
                or len(executed) != 1 or executed[0].get('exit_code') != 0
                or executed[0].get('payload', {}).get('state') != 'executed_unverified'
                or len(verified) != 1 or verified[0].get('exit_code') != 0
                or effect.get('verification') != expected
                or any(verified[0].get('payload', {}).get('verification', {}).get(k) != v for k, v in expected.items())):
            raise ValueError('Owned model outcome lacks its exact execute-once and verifier receipts')
    signal = report.get('signal') or {}
    emitter = effects[-3]
    plan = emitter['plan']
    streams = [r for r in receipts if r.get('argv', [None])[0] == 'stream-topic']
    if (len(streams) != 1 or streams[0].get('exit_code') != 0 or signal.get('ack_before_execute') is not True
            or signal.get('target_completed') is not True or signal.get('cleanup') != 'unsubscribed'):
        raise ValueError('Signal emission result cannot replace acknowledged delivery and unsubscribe')
    stream = streams[0]
    records = stream.get('stream_records', [])
    starts = [r for r in records if r.get('record_type') == 'started']
    events = [r for r in records if r.get('record_type') == 'event']
    terminal = stream.get('payload', {})
    topic = URI + 'signal.' + ('click' if version == '2024.1' else 'toggle')
    expected_argv = ['stream-topic', topic, '--topic-contract-digest', signal.get('contract_digest'),
        '--signal-model', plan['model'], '--signal-widget', plan['widget'], '--event-count', '1']
    executed_index = next(i for i, row in enumerate(receipts) if row.get('argv') == ['execute', emitter['transaction_id']])
    if (stream.get('argv') != expected_argv or signal.get('model') != plan['model']
            or signal.get('widget') != plan['widget'] or signal.get('topic') != topic
            or receipts.index(stream) >= executed_index
            or len(starts) != 1 or len(events) != 1 or not records or records[0] != starts[0]
            or starts[0].get('topic') != topic
            or starts[0].get('topic_contract_digest') != signal.get('contract_digest')
            or starts[0].get('is_command_line') is not False or starts[0].get('detected_version') != version
            or events[0].get('event') != starts[0].get('match') or signal.get('event') != events[0].get('event')
            or signal.get('transaction_id') != effects[-3]['transaction_id']
            or terminal.get('cleanup') != 'unsubscribed'
            or terminal.get('monitoring_outcome', {}).get('target_completed') is not True):
        raise ValueError('Signal outcome differs from its matching public stream observations')
    retirements = report.get('retirements', [])
    expected_retirements = [_retirement(state_root, report['resources'][kind], effect['transaction_id'])
        for kind, effect in zip(('model', 'window'), effects[-2:])]
    if retirements != expected_retirements:
        raise ValueError('Owned model cleanup lacks its exact local handle retirement proofs')
    return report

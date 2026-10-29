"""Developer-only independent session witness for one owned Console log add."""
from copy import deepcopy
import json

TOPIC = 'ak.wwise.core.log.itemAdded'


def observe_peer_execution(runtime, transaction_id, receipt, output):
    """Use the existing public stream/packaged peer; never replay an execution."""
    assert runtime.version == '2023.1'
    diagnostic = {'contract': 'waapi-skill.console-log-peer-diagnostic/v1',
        'topic': TOPIC, 'records': [], 'events': [], 'ack_before_execute': False,
        'execute_attempted': False, 'cleanup': 'unknown', 'complete': False,
        'classification': 'unresolved', 'silence_meaning': 'inconclusive; no native absence inferred',
        'limits': {'events': 8, 'records': 10, 'record_bytes': 1024 * 1024,
            'receipt_bytes': 3 * 1024 * 1024, 'stream_total_seconds': 10,
            'producer_gateway_seconds': 10, 'producer_process_seconds': 30}}
    receipt['peer_diagnostic'] = diagnostic
    transaction = receipt['transaction']
    executed = verified = None

    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        assert len(raw) <= diagnostic['limits']['receipt_bytes'], 'Console peer receipt byte bound exceeded'
        output.write_bytes(raw)

    code, schema = runtime.raw_gateway(['topic-schema', TOPIC])
    assert code == 0 and schema.get('ok') is True, schema
    digest = schema['continuation']['contract_binding']['value']
    diagnostic['topic_contract_digest'] = digest
    endpoint = {'host': runtime.lifecycle.host, 'port': runtime.lifecycle.port, 'url': runtime.lifecycle.waapi_url}

    def peer(phase):
        transaction['phase'] = phase
        code, payload = runtime.packaged_topic_producer([phase, transaction_id])
        transaction[phase], transaction[phase + '_exit_code'] = payload, code
        if phase == 'execute':
            diagnostic['same_session'] = deepcopy(payload.get('dispatch_result', {}).get('log_item_observation'))
        persist()
        assert code == 0 and payload.get('ok') is True, payload
        return payload

    def observe(record):
        nonlocal executed, verified
        assert len(diagnostic['records']) < 10, 'Console peer record count exceeded'
        assert len(json.dumps(record).encode('utf-8')) <= 1024 * 1024, 'Console peer record byte bound exceeded'
        diagnostic['records'].append(deepcopy(record))
        persist()
        if record.get('record_type') == 'started':
            assert not diagnostic['execute_attempted'], 'Duplicate ACK; never repeat execute'
            assert (record.get('contract') == 'waapi-skill.topic-stream/v1'
                and record.get('topic') == TOPIC and record.get('topic_contract_digest') == digest
                and record.get('status') == 'streaming' and record.get('ok') is True
                and record.get('endpoint') == endpoint and record.get('detected_version') == runtime.version
                and record.get('is_command_line') is True and record.get('event_count_limit') == 8), record
            diagnostic['ack_before_execute'] = True
            diagnostic['execute_attempted'] = True
            persist()
            executed = peer('execute')
            diagnostic['same_session'] = deepcopy(executed['dispatch_result'].get('log_item_observation'))
            verified = peer('verify')
        elif record.get('record_type') == 'event':
            event = record['event']
            expected = receipt['expected']
            matches = (event.get('channel') == expected['channel']
                and event.get('item', {}).get('message') == expected['message']
                and event.get('item', {}).get('severity') == expected['severity'])
            diagnostic['events'].append({'event': deepcopy(event), 'matches_expected': matches,
                'schema_validation': 'accepted_by_gateway', 'exclusive_causation_proven': False})
        persist()

    try:
        code, terminal = runtime.raw_gateway(['--timeout', '10', 'stream-topic', TOPIC,
            '--topic-contract-digest', digest, '--event-count', '8', '--no-idle-timeout'], stream_sink=observe)
        diagnostic.update(terminal=terminal, terminal_exit_code=code, cleanup=terminal.get('cleanup', 'unknown'))
        independent = any(row['matches_expected'] for row in diagnostic['events'])
        same = diagnostic.get('same_session', {}).get('outcome') == 'matched'
        diagnostic['classification'] = ('both_sessions_matched' if independent and same else
            'independent_session_only' if independent else 'same_session_only' if same else 'neither_session_matched')
        assert diagnostic['ack_before_execute'] and executed is not None and verified is not None, 'No acknowledged peer execution'
        assert diagnostic['cleanup'] == 'unsubscribed', 'Independent observer unsubscribe unproven'
        assert terminal.get('error_code') in (None, 'TIMEOUT'), terminal
        diagnostic['complete'] = True
        return executed, verified
    finally:
        persist()

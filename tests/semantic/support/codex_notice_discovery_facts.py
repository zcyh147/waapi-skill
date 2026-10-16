"""The two public Draft discovery commands, bound to one immutable Preview."""
from dataclasses import asdict, is_dataclass
from typing import Mapping
import re
import json
from pathlib import Path

from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_harness import normalized_gateway_command_argv

DISCOVERY_COMMANDS = {'draft-discover-types', 'draft-discover-fields'}


def _option(argv, name, *, repeated=False):
    values = [argv[index + 1] for index, value in enumerate(argv) if value == name]
    if not repeated and len(values) != 1:
        raise ValueError('discovery requires one exact option')
    return values if repeated else values[0]


def _meanings(argv):
    from wwise_waapi.metadata_discovery import (MAX_METADATA_DISCOVERY_QUERIES,
        MAX_METADATA_DISCOVERY_QUERY_CHARS, MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS)
    values = _option(argv, '--meaning', repeated=True)
    if (not 1 <= len(values) <= MAX_METADATA_DISCOVERY_QUERIES or any(not isinstance(value, str) or not value.strip()
            or len(value) > MAX_METADATA_DISCOVERY_QUERY_CHARS for value in values)
            or sum(map(len, values)) > MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS
            or len(set(values)) != len(values)):
        raise ValueError('invalid bounded discovery meanings')
    return values


def _type_candidates(payload, meanings, role):
    from wwise_waapi.metadata_discovery import MAX_METADATA_DISCOVERY_LIMIT
    rows = payload['type_candidates']
    if role not in {'object', 'source', 'effect'} or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_METADATA_DISCOVERY_LIMIT:
        raise ValueError('invalid discovery role or rows')
    projected, identities = [], set()
    for row in rows:
        if (not isinstance(row, Mapping) or set(row) != {'handle', 'label', 'role', 'matched_meanings'}
                or row['role'] != role or not isinstance(row['label'], str) or not row['label']
                or not isinstance(row['handle'], str) or not re.fullmatch(r'bth1-[0-9a-f]{32}', row['handle'])
                or row['handle'] in identities or not isinstance(row['matched_meanings'], list)
                or not row['matched_meanings'] or len(set(row['matched_meanings'])) != len(row['matched_meanings'])
                or not set(row['matched_meanings']) <= set(meanings)):
            raise ValueError('invalid type candidate')
        identities.add(row['handle'])
        projected.append({'candidate_sha256': canonical_digest(row['handle']), 'label': row['label'],
            'role': role, 'matched_meanings': list(row['matched_meanings'])})
    if type(payload['candidate_count']) is not int or payload['candidate_count'] != len(rows):
        raise ValueError('invalid candidate count')
    if payload['selection_required'] is not True or payload['selection_rule'] != 'copy_one_returned_type_candidate.handle':
        raise ValueError('invalid type selection rule')
    return projected


def _validate_field_metadata_extension(row):
    present = set(row) & {'metadata', 'unit'}
    if not present:
        return  # Historical receipts predate the metadata detail projection.
    if present != {'metadata', 'unit'}:
        raise ValueError('field metadata and unit must be paired')
    from wwise_waapi.builders.metadata import parse_get_property_info_result
    from wwise_waapi.canonical import canonical_json_bytes
    from wwise_waapi.metadata_discovery import MAX_METADATA_DISCOVERY_INFO_BYTES
    metadata, unit = row['metadata'], row['unit']
    keys = {'name', 'type', 'default', 'supports', 'display', 'restriction', 'dependencies', 'ui', 'audioEngineId'}
    if (not isinstance(metadata, Mapping) or set(metadata) != keys
            or len(canonical_json_bytes(metadata)) > MAX_METADATA_DISCOVERY_INFO_BYTES):
        raise ValueError('invalid bounded field metadata')
    parsed = parse_get_property_info_result(metadata).as_dict()
    if canonical_digest(parsed) != canonical_digest(metadata):
        raise ValueError('metadata differs from public normalized shape')
    meaning = metadata['ui'].get('dataMeaning')
    if meaning is not None and not isinstance(meaning, str):
        raise ValueError('invalid metadata unit category')
    expected = {'status': 'unknown', 'value': None} if meaning in {None, 'None'} else {'status': 'known', 'value': meaning}
    if not isinstance(unit, Mapping) or dict(unit) != expected:
        raise ValueError('field unit differs from metadata')


def _field_candidates(payload, meanings, platform):
    from wwise_waapi.business_declarations import _normalize_restrictions
    from wwise_waapi.metadata_discovery import MAX_METADATA_DISCOVERY_LIMIT, _validate_queries
    normalized_meanings = {value.casefold() for value in _validate_queries(meanings)}
    groups = payload['meaning_results']
    if (not isinstance(groups, list) or [row['meaning'] for row in groups] != meanings
            or type(payload['meaning_count']) is not int or payload['meaning_count'] != len(meanings)
            or type(payload['rejected_candidate_count']) is not int or payload['rejected_candidate_count'] < 0
            or type(payload['selection_required']) is not bool
            or payload['selection_rule'] != 'copy_exactly_one_candidate.handle_per_requested_meaning'):
        raise ValueError('invalid field discovery meaning summary')
    indexed, meaning_results = {}, []
    for group in groups:
        rows = group['candidates']
        if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_METADATA_DISCOVERY_LIMIT
                or type(group['candidate_count']) is not int or group['candidate_count'] != len(rows)
                or len({row['handle'] for row in rows}) != len(rows)):
            raise ValueError('invalid field discovery candidate count')
        ids = []
        for row in rows:
            required = {'handle', 'label', 'field_kind', 'value_type', 'platform', 'restrictions', 'value_input'}
            if (not isinstance(row, Mapping) or not required <= set(row) or set(row) - required - {'matched_meanings', 'metadata', 'unit'}
                    or not isinstance(row['handle'], str) or not re.fullmatch(r'bfh1-[0-9a-f]{32}', row['handle'])
                    or not isinstance(row['label'], str) or not row['label']
                    or row['field_kind'] not in {'property', 'reference'}
                    or row['value_type'] not in {'number', 'integer', 'boolean', 'string', 'reference'}
                    or (row['field_kind'] == 'reference') != (row['value_type'] == 'reference')
                    or row['platform'] != platform or not isinstance(row['value_input'], Mapping)
                    or row['value_input'].get('type') != row['value_type']):
                raise ValueError('invalid typed field candidate')
            _validate_field_metadata_extension(row)
            restrictions = _normalize_restrictions(row['restrictions'], field_kind=row['field_kind'], value_type=row['value_type'])
            if canonical_digest(restrictions) != canonical_digest(row['restrictions']):
                raise ValueError('field restrictions differ from normalized public contract')
            matched = row.get('matched_meanings')
            if matched is not None:
                normalized_matches = {value.casefold() for value in _validate_queries(matched)}
                if (' '.join(group['meaning'].split()).casefold() not in normalized_matches
                        or not normalized_matches <= normalized_meanings):
                    raise ValueError('field candidate meaning differs')
            if row['handle'] in indexed and canonical_digest(indexed[row['handle']]) != canonical_digest(row):
                raise ValueError('field candidate identity differs between meanings')
            indexed[row['handle']] = row
            ids.append(canonical_digest(row['handle']))
        meaning_results.append({'meaning': group['meaning'], 'candidate_count': len(rows), 'candidate_sha256s': ids})
    rows = list(indexed.values())
    if (type(payload['candidate_count']) is not int or payload['candidate_count'] != len(rows)
            or len(rows) > MAX_METADATA_DISCOVERY_LIMIT
            or payload['selection_required'] != any(row['candidate_count'] != 1 for row in groups)):
        raise ValueError('field discovery counts or selection differ')
    if 'field_candidates' in payload and canonical_digest(payload['field_candidates']) != canonical_digest(rows):
        raise ValueError('field discovery projections differ')
    return [{**{key: row[key] for key in ('label', 'field_kind', 'value_type', 'platform', 'restrictions')},
        'candidate_sha256': canonical_digest(row['handle']),
        'matched_meanings': list(row['matched_meanings']) if 'matched_meanings' in row else [
            group['meaning'] for group in groups if any(candidate['handle'] == row['handle']
            for candidate in group['candidates'])]} for row in rows], meaning_results


def draft_discovery_evidence(events, command_records, *, version, broker_records,
        preview_position, transaction_id, preview_artifact, public_parser=None):
    from tests.semantic.support.codex_expansion_notice_adjudication import _authenticated_event_receipt
    records = [{**asdict(row), 'succeeded': row.succeeded} if is_dataclass(row) else row for row in broker_records]
    commands = {row.command: normalized_gateway_command_argv(row.argv, expected_wwise_version=version)
        for row in command_records}
    completed = [(position, event, commands[event['item']['command']]) for position, event in enumerate(events)
        if event.get('type') == 'item.completed' and event.get('item', {}).get('type') == 'command_execution'
        and event['item'].get('command') in commands and len(commands[event['item']['command']]) >= 4]
    result = {'transaction_id': transaction_id, 'preview_sha256': canonical_digest(preview_artifact),
        'pre_execution_timeline_sha256': canonical_digest(events), 'preview_event_position': preview_position,
        'discoveries': []}
    if not any(argv[3] in DISCOVERY_COMMANDS for _, _, argv in completed):
        return result
    if public_parser is None:
        from tests.semantic.support.codex_expansion_archive import _public_gateway
        parser = _public_gateway({'skill_source': Path(__file__).parents[3] / 'skills/waapi-skill'}).build_parser()
        def public_parser(argv):
            try:
                return parser.parse_args(['--version', version, *argv])
            except SystemExit as exc:
                raise ValueError('Draft command violates the packaged parser') from exc
    preview_argv = commands[events[preview_position]['item']['command']][3:]
    draft_id, authority = preview_argv[1], _option(preview_argv, '--task-authority')
    revision, last_sequence, used = None, 0, set()
    bound_objects, bound_types = {}, {}
    capabilities = {authority}
    result['draft_sha256'] = canonical_digest(draft_id)
    result['revision_lineage'] = []
    operation = preview_artifact['request']['operation']
    binding = None
    for position, event, normalized in completed:
        argv = normalized[3:]
        if argv[0] not in DISCOVERY_COMMANDS and argv[0] != 'draft-start' and (len(argv) < 2 or argv[1] != draft_id):
            continue
        if position > preview_position:
            raise ValueError('discovery is not before Preview')
        matches = [(index, row) for index, row in enumerate(records)
            if tuple(normalized_gateway_command_argv(row['model_argv'], expected_wwise_version=version))[1:] == normalized[1:]
            and normalized[0] in {row['model_argv'][0], row['normalized_model_argv'][0]}]
        if len(matches) != 1 or matches[0][0] in used:
            raise ValueError('Draft event lacks one distinct Broker receipt')
        index, record = matches[0]
        used.add(index)
        if (type(record['sequence']) is not int or record['sequence'] <= last_sequence
                or any(row['sequence'] <= record['sequence'] for row in records if tuple(row.get('gateway_arguments', ()))[:1] == ('execute',))):
            raise ValueError('Draft receipt is not ordered pre-Execute')
        last_sequence = record['sequence']
        payload = _authenticated_event_receipt(event, record, normalized, exact=True)
        public_parser(argv)
        if argv[0] in DISCOVERY_COMMANDS and (payload.get('ok') is False or payload.get('status') == 'needs_clarification'):
            failed_draft = payload.get('draft')
            if (type(record['exit_code']) is not int or record['exit_code'] != 2
                    or tuple(record.get('allowed_exit_codes', ())) != (0, 2)
                    or argv[1] != draft_id or _option(argv, '--task-authority') != authority
                    or int(_option(argv, '--expected-revision')) != revision
                    or not (isinstance(payload.get('error_code'), str) and payload['error_code']
                        or payload.get('status') == 'needs_clarification')
                    or payload.get('executed') is True
                    or payload.get('detected_version', version) != version
                    or any(key in payload for key in ('type_candidates', 'field_candidates', 'meaning_results'))
                    or failed_draft is not None and (not isinstance(failed_draft, Mapping)
                        or failed_draft.get('draft_id') != draft_id or type(failed_draft.get('revision')) is not int
                        or failed_draft['revision'] != revision
                        or canonical_digest(failed_draft.get('binding')) != canonical_digest(binding))):
                raise ValueError('failed discovery differs from the admitted unchanged Draft')
            # Broker acceptance/success attests its existing durable unchanged-
            # revision check; the following authenticated lineage must still
            # consume this exact revision. The failed output grants no candidates.
            result['revision_lineage'].append({'command': argv[0], 'event_position': position,
                'broker_sequence': record['sequence'], 'payload_sha256': record['payload_sha256'],
                'broker_record_sha256': canonical_digest(record), 'expected_revision': revision,
                'result_revision': revision, 'status': 'failed-no-acquisition'})
            continue
        if payload.get('ok') is not True or type(record['exit_code']) is not int or record['exit_code'] != 0:
            raise ValueError('Draft receipt is unsuccessful')
        if argv[0] == 'preview-from-draft':
            if (argv[1] != draft_id or _option(argv, '--task-authority') != authority
                    or int(_option(argv, '--expected-revision')) != revision
                    or payload.get('transaction_id') != transaction_id
                    or payload.get('artifact_hash') != result['preview_sha256']):
                raise ValueError('discovery lineage does not bind Preview')
            result['preview_broker_sequence'] = record['sequence']
            result['preview_expected_revision'] = revision
            result['preview_payload_sha256'] = record['payload_sha256']
            result['preview_broker_record_sha256'] = canonical_digest(record)
            continue
        draft = payload['draft']
        if (draft['draft_id'] != draft_id or draft['binding']['operation'] != operation
                or draft['binding']['version'] != version or type(draft['revision']) is not int):
            raise ValueError('Draft identity or version differs')
        if argv[0] == 'draft-start':
            if revision is not None or draft['revision'] != 1 or (payload.get('task_authority') is not None
                    and payload['task_authority'] != authority):
                raise ValueError('Draft lineage has another start')
            binding = draft['binding']
        else:
            if (argv[1] != draft_id or _option(argv, '--task-authority') != authority
                    or (argv[0] != 'draft-inspect' and int(_option(argv, '--expected-revision')) != revision)
                    or draft['revision'] != revision + (argv[0] != 'draft-inspect')
                    or canonical_digest(draft['binding']) != canonical_digest(binding)):
                raise ValueError('Draft revision lineage differs')
        previous_revision, revision = revision, draft['revision']
        result['revision_lineage'].append({'command': argv[0], 'event_position': position,
            'broker_sequence': record['sequence'], 'payload_sha256': record['payload_sha256'],
            'broker_record_sha256': canonical_digest(record), 'expected_revision': previous_revision,
            'result_revision': revision})
        if argv[0] == 'draft-bind-object':
            from wwise_waapi.object_capabilities import object_identity_semantics
            bound = payload['bound_object']
            if (not isinstance(bound, Mapping) or not isinstance(bound.get('handle'), str)
                    or not re.fullmatch(r'boh1-[0-9a-f]{32}', bound['handle'])
                    or not isinstance(bound.get('type'), str) or not bound['type']
                    or not isinstance(bound.get('name'), str)
                    or not bound['name'] and not object_identity_semantics(bound['type']).empty_name_allowed):
                raise ValueError('invalid exposed bound object')
            bound_objects[bound['handle']] = {'kind': 'bound-object', 'object_sha256': canonical_digest(bound['handle']),
                **{key: bound[key] for key in ('name', 'type', 'id', 'path') if key in bound}}
        if argv[0] not in DISCOVERY_COMMANDS:
            continue
        if payload.get('offline') is not False or payload.get('detected_version') != version:
            raise ValueError('discovery is not matching live session metadata')
        meanings = _meanings(argv)
        meaning_results = None
        if argv[0] == 'draft-discover-types':
            role = _option(argv, '--role')
            candidates = _type_candidates(payload, meanings, role)
            scope = {'role': role}
            for row, projected in zip(payload['type_candidates'], candidates):
                bound_types[row['handle']] = {'kind': 'class-candidate',
                    **{key: projected[key] for key in ('candidate_sha256', 'label', 'role')}}
        else:
            from wwise_waapi.business_declarations import resolve_semantic_kind, _normalize_field_platform
            scopes = [name for name in ('--object-handle', '--type-handle', '--semantic-kind') if name in argv]
            if len(scopes) != 1:
                raise ValueError('field discovery lacks exact bound scope')
            name, value = scopes[0], _option(argv, scopes[0])
            if name == '--semantic-kind':
                resolve_semantic_kind(value, version=version)  # Validate; do not invent an acquired native class id.
            scope = (dict(bound_objects[value]) if name == '--object-handle' else dict(bound_types[value])
                if name == '--type-handle' else {'kind': 'semantic-class', 'semantic_kind': value})
            scope['platform'] = _normalize_field_platform(_option(argv, '--platform') if '--platform' in argv else None)
            candidates, meaning_results = _field_candidates(payload, meanings, scope['platform'])
            capabilities.update(row['handle'] for group in payload['meaning_results'] for row in group['candidates'])
        integrity = draft.get('response_integrity')
        if integrity is not None and (not isinstance(integrity, Mapping)
                or type(integrity.get('complete')) is not bool or type(integrity.get('truncated')) is not bool):
            raise ValueError('invalid discovery response integrity')
        result['discoveries'].append({'command': argv[0], 'event_position': position,
            'broker_sequence': record['sequence'], 'payload_sha256': record['payload_sha256'],
            'broker_record_sha256': canonical_digest(record), 'draft_sha256': canonical_digest(draft_id),
            'expected_revision': previous_revision, 'result_revision': revision,
            'meanings': meanings, 'scope': scope, 'candidates': candidates,
            'candidate_count': payload['candidate_count'], 'selection_required': payload['selection_required'],
            'selection': 'not-established-by-discovery', 'acquisition': 'session-bound-live-metadata',
            'fresh_network_fetch': 'unattested', 'entire_catalog_complete': 'unattested',
            'current_property_values': 'not-discovered',
            'response_integrity': ({key: integrity[key] for key in ('complete', 'truncated')} if integrity else None)})
        if meaning_results is not None:
            result['discoveries'][-1].update(meaning_results=meaning_results,
                rejected_candidate_count=payload['rejected_candidate_count'])
    if 'preview_broker_sequence' not in result:
        raise ValueError('discovery has no matching Preview')
    projected = json.dumps(result, ensure_ascii=False)
    capabilities.update(set(bound_objects) | set(bound_types))
    if any(value in projected for value in capabilities):
        raise ValueError('discovery projection contains a capability')
    return result

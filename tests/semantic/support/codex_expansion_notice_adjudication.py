"""Closed workflow adapters for prospective expansion notice review.

Only attested case facts cross the existing isolated reviewer boundary. This
module owns no business oracle, authorization, execution or language grammar.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_harness import normalized_gateway_command_argv, parse_jsonl_events

LEGACY_CONTRACT = 'waapi-skill.expansion-notice-adjudication/v1'
BUSINESS_CONTRACT = 'waapi-skill.expansion-notice-adjudication/v2'
CONTRACT = 'waapi-skill.expansion-notice-adjudication/v3'
CONTRACTS = frozenset({LEGACY_CONTRACT, BUSINESS_CONTRACT, CONTRACT})
CASES = frozenset({'C01', 'C03', 'C06', 'C08', 'C09', 'M01', 'M05'})


def _identity(row, kind):
    return (isinstance(row, Mapping) and row.get('type') == kind
        and isinstance(row.get('id'), str)
        and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', row['id'])
        and all(isinstance(row.get(key), str) for key in ('name', 'path')))


def _same_identity(row, observed):
    return isinstance(row, Mapping) and all(row.get(key) == observed.get(key) for key in ('id', 'name', 'type', 'path'))


def _sources_match(snapshot, owner, observed_sources):
    if not isinstance(snapshot, Mapping) or snapshot.get('owner_id') != owner:
        return False
    rows = snapshot.get('rows')
    if not isinstance(rows, list) or len(rows) != len(observed_sources):
        return False
    indexed = {row.get('id'): row for row in rows if isinstance(row, Mapping)}
    if len(indexed) != len(rows) or set(indexed) != {row['id'] for row in observed_sources}:
        return False
    return all(_same_identity(indexed[row['id']], row)
        and indexed[row['id']].get('parent', {}).get('id') == owner
        and indexed[row['id']].get('audioSource:language') == row.get('source_language')
        for row in observed_sources)


def _import_roles(case_id, artifact, before, parameters):
    from tests.semantic.support.codex_expansion_voice_case import approve_c01_preview
    from tests.semantic.support.codex_expansion_media_case import approve_c03_preview
    from tests.semantic.support.codex_expansion_music_case import approve_m01_preview
    parameters = dict(parameters)
    if case_id == 'C01':
        parameters['replacement'] = Path(parameters['replacement'])
        approved = approve_c01_preview(artifact, **parameters)
    elif case_id == 'C03':
        parameters['mappings'] = {key: Path(value) for key, value in parameters['mappings'].items()}
        approved = approve_c03_preview(artifact, **parameters)
    else:
        parameters['media'] = {key: Path(value) for key, value in parameters['media'].items()}
        approved = approve_m01_preview(artifact, **parameters)
    request, prepared = artifact['request'], artifact['prepared_operation']
    plan = prepared['verification_plan']
    if (not approved or prepared.get('request') != request
            or prepared.get('operation') != 'audio.import' or prepared.get('version') != request['version']
            or plan.get('version') != request['version'] or plan.get('kind') != 'closed-audio-import'):
        return None
    args = request['arguments']
    rows = [{**args.get('defaults', {}), **row} for row in args['imports']]
    targets = plan.get('targets')
    if not isinstance(targets, list) or len(targets) != len(rows):
        return None
    by_path = {row.get('canonical_target_path'): row for row in targets}
    if len(by_path) != len(targets):
        return None
    mappings = []
    for row in rows:
        path = re.sub(r'<[^>]+>', '', row['object_path'])
        target = by_path.get(path)
        kind = row.get('object_type', 'Sound Voice' if case_id == 'C01' else 'Sound SFX')
        language = row.get('import_language', 'SFX')
        file = row.get('audio_file')
        if (not isinstance(target, Mapping) or target.get('requested_object_type') != kind
                or target.get('requested_language', 'SFX') != language
                or target.get('media_expected') is not (file is not None)
                or (file is not None and (not isinstance(target.get('source_file'), Mapping)
                    or target['source_file'].get('kind') != 'regular_file'
                    or target['source_file'].get('path') != file))):
            return None
        destination = {'path': path, 'type': kind}
        if case_id == 'C01':
            sound = before['sound']
            if (not _identity(sound, 'Sound') or sound['id'] != parameters['sound_id']
                    or sound['path'] != parameters['sound_path'] or set(before['sources']) != {'Japanese', 'English(US)'}):
                return None
            for expected_language, entry in before['sources'].items():
                source = entry['object']
                if (not _identity(source, 'AudioFileSource') or source.get('parent', {}).get('id') != sound['id']
                        or source.get('source_language', {}).get('name') != expected_language):
                    return None
            destination = sound
            if (not _sources_match(target.get('localized_source_snapshot'), sound['id'],
                    [entry['object'] for entry in before['sources'].values()])
                    or target.get('localized_audio_file_source_id') != before['sources']['Japanese']['object']['id']):
                return None
        elif case_id == 'C03':
            entries = [entry for entry in before['sounds'].values() if entry['object'].get('path') == path]
            if len(entries) != 1:
                return None
            destination = entries[0]['object']
            if (not _identity(destination, 'Sound') or destination['id'] != parameters['target_ids'][path]
                    or not _identity(entries[0]['source'], 'AudioFileSource')
                    or entries[0]['source'].get('parent', {}).get('id') != destination['id']):
                return None
            if not _sources_match(target.get('existing_sfx_source_snapshot'), destination['id'], [entries[0]['source']]):
                return None
        else:
            parent = before['parent']
            if (not _identity(parent, 'MusicPlaylistContainer') or parent['path'] != parameters['parent_path']
                    or before.get('segment') is not None or before.get('tracks') != {}
                    or target.get('preexisting_id') is not None):
                return None
            anchor = prepared.get('resolved_roles', {}).get(f'targets[{targets.index(target)}].anchor', {})
            if anchor.get('object') != parent['id'] or not _same_identity(anchor.get('row'), parent):
                return None
        if case_id != 'M01' and target.get('preexisting_id') != destination['id']:
            return None
        if case_id != 'M01':
            rows_before = target.get('pre_state_rows')
            if (not isinstance(rows_before, list) or len(rows_before) != 1
                    or not _same_identity(rows_before[0], destination)):
                return None
        mappings.append({'source_file': file, 'destination': destination, 'language': language,
            'field_owner': kind, 'properties': row.get('properties', []),
            'before_source': (before['sources']['Japanese'] if case_id == 'C01'
                else entries[0] if case_id == 'C03' else None)})
    if case_id == 'M01':
        # The independent case fixes one Segment, two Tracks, one source per
        # Track and Quiet-only Track gain. The raw request cannot stand in for
        # those typed future roles.
        mappings.sort(key=lambda row: (row['source_file'] is not None,
            0 if row['destination']['path'].endswith('Quiet') else 1))
    return {'quantity': len(mappings), 'mappings': mappings,
        'target': before['sound'] if case_id == 'C01' else before.get('parent'),
        'topology': 'one MusicSegment with Quiet/Full MusicTrack; one AudioFileSource, sequence and clip per Track' if case_id == 'M01' else 'existing Sound and AudioFileSource identities',
        'units': {'Volume': 'decibels'}, 'preserve': {
            'C01': ['English(US) media and association', 'Sound volume and routing', 'Event and Action', 'distractor'],
            'C03': ['source identities and Originals locations', 'Sound volume and routing', 'distractor'],
            'M01': ['parent and Keep', 'Full default Volume', 'Clip and Source zero gain', 'no playlist/Transition/Stinger'],
        }[case_id]}


def _roles(case_id, artifact, before, version, parameters):
    if case_id in {'C01', 'C03', 'M01'}:
        return _import_roles(case_id, artifact, before, parameters)
    if case_id == 'C06':
        from tests.semantic.support.codex_task_runner_v3 import _rtpc_notice_context
        from tests.semantic.support.codex_expansion_rtpc_case import approve_c06_preview
        if not approve_c06_preview(artifact, **parameters):
            return None
        association = _rtpc_notice_context(artifact, before)
        if association is None or before['owner'].get('type') != 'Sound':
            return None
        control = next(row for row in before['controls'] if row['id'] == parameters['control_id'])
        if control.get('type') != 'GameParameter':
            return None
        return {'target': before['owner'], 'control_input': control, 'association': association,
            'units': {'x': 'GameParameter value', 'y': 'decibels'},
            'preserve': ['RTPC identity', 'other RTPC curves', 'notes', 'Sound state and media', 'control identity, notes and parent']}
    if case_id in {'C09', 'M05'}:
        from tests.semantic.support.codex_task_runner_v3 import _bound_context_notice
        from tests.semantic.support.codex_expansion_effects_case import approve_c09_preview
        from tests.semantic.support.codex_expansion_stinger_case import approve_m05_preview
        approve = approve_c09_preview if case_id == 'C09' else approve_m05_preview
        if not approve(artifact, **parameters):
            return None
        context = _bound_context_notice(artifact, before)
        if context is None:
            return None
        if case_id == 'C09':
            return {'target': before['owner'], 'append': context,
                'preserve': ['existing effects and order', 'Sound volume and routing']}
        if context['kind'] != 'reference' or context['old_reference'] is None or context['segment'] is None:
            return None
        return {'source': before['stinger'], 'destination': before['target'], 'field': 'Trigger',
            'before_reference': context['old_reference'], 'owner': before['owner'],
            'preserved_segment': before['segment'], 'siblings': before['siblings'],
            'preserve': ['same MusicStinger identity/type/notes', 'Segment reference', 'owner and siblings', 'other music settings'],
            'display_boundary': 'MusicStinger name/path may derive from its new associations; these are not fixed preservation fields'}
    if case_id == 'C08':
        from tests.semantic.support.codex_attenuation_notice import attenuation_notice_context
        from tests.semantic.support.codex_expansion_attenuation_case import approve_c08_preview
        if not approve_c08_preview(artifact, **parameters):
            return None
        curve = attenuation_notice_context(artifact, before, version)
        source_state = before.get('source')
        source = source_state.get('object') if isinstance(source_state, Mapping) else None
        if (curve is None or not _identity(source, 'Attenuation')
                or any(not source[key] for key in ('name', 'path'))
                or source['id'].casefold() == before['attenuation']['id'].casefold()):
            return None
        return {
            'target': before['attenuation'], 'curve': curve,
            'preserved_source': source,
            'units': {'x': 'distance in the sealed project domain', 'y': 'decibels'},
            'preserve': ['other curves', 'source Attenuation', 'users and references'],
            'gateway_verification': 'result_schema',
        }
    return None


def _notice_identity(row):
    return {key: row[key] for key in ('id', 'name', 'type', 'path') if key in row}


def _notice_obligations(case_id, roles):
    """Required business meaning, derived only after full operation attestation.

    Facts omitted here remain in attested_roles to check affirmative claims.
    This projection supplies expected meaning, never evidence that it was said.
    """
    obligations = {'preserve': roles['preserve']}
    if case_id in {'C01', 'C03'}:
        obligations.update(action='reimport-existing-media', media_count=len(roles['mappings']),
            mappings=[{'source_file': row['source_file'], 'destination': _notice_identity(row['destination'])}
                for row in roles['mappings']], preserve_existing_sound_and_source_identity=True)
        if case_id == 'C01':
            obligations['selected_language'] = roles['mappings'][0]['language']
            obligations['import_kind'] = roles['mappings'][0]['field_owner']
    elif case_id == 'M01':
        segment, *tracks = roles['mappings']
        obligations.update(action='import-new-music-media', parent=_notice_identity(roles['target']),
            segment=_notice_identity(segment['destination']), segment_count=1, track_count=len(tracks),
            media_count=len(tracks), volume_owner='MusicTrack', volume_unit=roles['units']['Volume'],
            mappings=[{'source_file': row['source_file'], 'destination': _notice_identity(row['destination']),
                'properties': row['properties']} for row in tracks])
    elif case_id == 'C06':
        association = roles['association']
        obligations.update(action='update-existing-RTPC', target=_notice_identity(roles['target']),
            control_input=_notice_identity(roles['control_input']), association_id=association['ids'][2],
            property='Volume', points=[{'x': x, 'y': y, 'shape': 'Linear'} for x, y in association['new']],
            axis_meaning=roles['units'])
    elif case_id == 'C08':
        curve = roles['curve']
        obligations.update(action='update-selected-attenuation-curve', target=_notice_identity(roles['target']),
            curve_kind=curve['kind'], curve_source=curve['source'], points=curve['points'],
            axis_meaning=roles['units'], gateway_verification=roles['gateway_verification'])
    elif case_id == 'C09':
        obligations.update(action='append-effect', target=_notice_identity(roles['target']),
            effect=roles['append']['descriptor'], effect_count=1)
    elif case_id == 'M05':
        obligations.update(action='update-existing-reference', source=_notice_identity(roles['source']),
            destination=_notice_identity(roles['destination']), field=roles['field'],
            preserved_segment=_notice_identity(roles['preserved_segment']))
    return obligations


def _verification_context(artifact):
    """Packaged interface evidence, never live availability or completed proof.

    This operation-to-reader relation is established by the fixed Gateway
    metadata disclosure, not inferred from native URI spelling or case IDs.
    Terminal disclosure timing comes from waapi-operate.md's Terminal states.
    """
    from wwise_waapi.execution_contracts import FIXED_COMMANDS_BY_URI
    public_readers = {
        'ak.wwise.core.object.setAttenuationCurve': 'ak.wwise.core.object.getAttenuationCurve',
    }
    request = artifact['request']
    operation = request['operation']
    if operation == 'waapi.call':
        operation = request['arguments']['api']
    reader = public_readers.get(operation)
    return {
        'public_readback_routes': ([{'uri': reader, 'fixed_commands': list(FIXED_COMMANDS_BY_URI[reader])}]
            if reader is not None else []),
        'support_evidence': 'packaged-public-interface-only',
        'route_inventory_scope': 'positive-support-evidence-only-not-exhaustive',
        'live_availability_or_completed_read': 'not_attested',
        'disclosure_timing': {
            'authority': 'operation-contract-Skill-guidance-and-explicit-user-request',
            'pre_execution': 'only-at-required-source-timing',
            'terminal': 'report-actual-verification-strength-and-boundaries',
        },
        'sources': ['skills/waapi-skill/references/waapi-operate.md#terminal-states',
            'skills/waapi-skill/wwise_waapi/execution_contracts.py#FIXED_COMMANDS_BY_URI',
            'skills/waapi-skill/scripts/gateway.py#fixed-command-disclosure'],
    }


def decide_expansion_notice(result: Any, command_records: Sequence[Any], *, case_id: str,
        version: str, execute_expected: bool, preview_artifact: Mapping[str, Any],
        before_snapshot: Mapping[str, Any], preview_parameters: Mapping[str, Any],
        user_prompt: str = '', transaction_id: str = '',
        adjudication_contract: str = CONTRACT) -> dict[str, Any]:
    from tests.semantic.support.codex_c09_notice_adjudication import INPUT_MAX_BYTES
    if (adjudication_contract not in CONTRACTS or case_id not in CASES or version not in {'2022.1', '2025.1'}
            or (case_id, version) == ('M05', '2022.1')
            or execute_expected != (case_id not in {'C01', 'C03'})
            or preview_parameters.get('version') != version):
        return {'outcome': 'material_reject', 'reason': 'workflow-version-policy-boundary'}
    try:
        roles = _roles(case_id, preview_artifact, before_snapshot, version, preview_parameters)
    except (KeyError, TypeError, ValueError):
        roles = None
    if roles is None:
        return {'outcome': 'material_reject', 'reason': 'unattested-workflow-operation-or-roles'}
    if case_id == 'C09':
        from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice
        legacy = decide_c09_notice(result, command_records, version=version, execute_expected=execute_expected,
            preview_artifact=preview_artifact, before_snapshot=before_snapshot, complete_meaning_required=True)
        if legacy['outcome'] == 'material_reject':
            return legacy
    routes = {}
    for record in command_records:
        argv = normalized_gateway_command_argv(record.argv, expected_wwise_version=version)
        if len(argv) >= 4:
            routes[record.command] = argv[3]
    preview = execute = None
    visible, events_before_execute = [], []
    for position, event in enumerate(parse_jsonl_events(result.stdout)):
        item = event.get('item', {})
        if not isinstance(item, Mapping):
            continue
        route = routes.get(item.get('command'))
        if item.get('type') == 'command_execution' and route == 'execute':
            execute = position
            break
        events_before_execute.append(event)
        if event.get('type') == 'item.completed':
            if route == 'preview-from-draft' and item.get('type') == 'command_execution':
                if preview is not None:
                    return {'outcome': 'material_reject', 'reason': 'multiple-Previews'}
                preview = position
            elif item.get('type') == 'agent_message':
                visible.append({'event_position': position, 'text': str(item.get('text', ''))})
    if (preview is None or execute_expected != (execute is not None)
            or not any(row['event_position'] > preview and row['text'].strip() for row in visible)):
        return {'outcome': 'material_reject', 'reason': 'missing-ordered-visible-notice'}
    # Historical parsers establish only selected edit frames. Even a positive
    # cannot prove the meaning of every supplied baseline/verifier/scope claim
    # in the complete visible notice. The prospective contract therefore needs
    # one complete independent judgment after its deterministic hard checks.
    review_input = {
        'contract': adjudication_contract, 'case_id': case_id, 'version': version,
        'transaction_id': transaction_id or preview_artifact.get('transaction_id'),
        'preview_sha256': canonical_digest(preview_artifact),
        'pre_execution_timeline_sha256': canonical_digest(events_before_execute),
        'preview_event_position': preview, 'execute_event_position': execute,
        'user_prompt': user_prompt, 'visible_messages': visible,
        'before_snapshot': before_snapshot, 'immutable_request': preview_artifact['request'],
        'prepared_operation': preview_artifact['prepared_operation'], 'attested_roles': roles,
    }
    if adjudication_contract != LEGACY_CONTRACT:
        obligations = _notice_obligations(case_id, roles)
        if adjudication_contract == CONTRACT:
            # Protected invariants and transaction strength remain attested
            # facts, not an exhaustive inventory of required spoken promises.
            obligations.pop('preserve')
            obligations.pop('gateway_verification', None)
            obligations['preservation_intent'] = {
                'only_declared_changes': True, 'adopt_user_preservation_scope': True}
            review_input['verification_context'] = _verification_context(preview_artifact)
        review_input['notice_obligations'] = obligations
    if len(json.dumps(review_input, ensure_ascii=False).encode('utf-8')) > INPUT_MAX_BYTES:
        return {'outcome': 'material_reject', 'reason': 'complete-review-input-exceeds-bound'}
    return {'outcome': 'review_required', 'reason': (
        'legacy-lexical-match-insufficient-for-complete-import-mappings-and-scope'
        if case_id in {'C01', 'C03', 'M01'} else 'legacy-partial-parser-insufficient-for-complete-notice-meaning'), 'input': review_input}


def grade_expansion_notice(result, command_records, *, other_gates, root, options, **kwargs):
    from pathlib import Path
    from wwise_waapi.transactions import validate_transaction_id
    from tests.semantic.support.codex_c09_notice_adjudication import review_c09_notice, verify_c09_review_receipt, _decode
    decision = decide_expansion_notice(result, command_records, **kwargs)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'notice-decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding='utf-8')
    hard_passed = bool(other_gates) and all(value is True for value in other_gates.values())
    passed, receipt = decision['outcome'] == 'accepted', None
    if decision['outcome'] == 'review_required' and hard_passed:
        validate_transaction_id(decision['input']['transaction_id'])
        receipt = review_c09_notice(decision, root=root / 'notice-review', options=options)
        binding = _decode((root / 'notice-review/invocation-binding.json').read_text(encoding='utf-8'))
        passed = verify_c09_review_receipt(receipt, decision=decision, expected_binding=binding)
    return {'passed': hard_passed and passed, 'decision': decision, 'receipt': receipt,
        'invocation_binding_sha256': receipt.get('invocation_binding_sha256') if receipt else None}

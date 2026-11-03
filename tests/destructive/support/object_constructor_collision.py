"""Fixed maintainer-only constructor diagnostic; no public raw execution route.

One existing ScenarioLifecycle and one OwnedDirectWaapiCall own the complete
attempt. A collection PASS means the requested fixed observations were retained
(nine by default), never that a native policy was equivalent or a public
operation passed.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from wwise_waapi.builders.schema import SemanticSchemaValidator
from wwise_waapi.operation_plugin import _closed_object_reference_id

VERSION = '2025.1'
PROFILES = ('action', 'effect_slot', 'source')
BOUNDS = {'discriminators': 9, 'native_calls': 100, 'members_per_owner': 16,
          'result_bytes_per_call': 262144, 'evidence_bytes': 4194304}
BASE = ['id', 'name', 'type', 'classId', 'path', 'parent', 'owner', 'notes']
FIELDS = {'action': ['@ActionType', '@Target'],
          'effect_slot': ['@Effect', '@Bypass', '@Render'],
          'source': ['audioSource:language', '@StartFreq', '@WaveType']}
REPO = Path(__file__).resolve().parents[3]
RESOURCE = REPO / 'skills/waapi-skill/resources/metadata'


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def selected_profiles(text=None):
    """Closed maintainer selection; omitted selects the original nine cases."""
    return _validate_profiles(PROFILES if text is None else tuple(text.split(',')))


def _validate_profiles(profiles):
    if (not isinstance(profiles, tuple) or not profiles or len(profiles) > len(PROFILES)
            or any(profile not in PROFILES for profile in profiles) or len(set(profiles)) != len(profiles)):
        raise ValueError('select each of action,effect_slot,source at most once; at least one is required')
    return tuple(profile for profile in PROFILES if profile in profiles)


def source_pins():
    """Reuse the five installed SDK extractions, without new source collection."""
    action_path = RESOURCE / 'action-constructor-sources.json'
    actions = json.loads(action_path.read_text(encoding='utf-8'))
    pins = {}
    for version, action in actions['versions'].items():
        path = RESOURCE / version / 'documented-list-fields.json'
        lists = json.loads(path.read_text(encoding='utf-8'))
        classes = [row for row in lists['classes'] if row['name'] in
                   {'Action', 'Event', 'Sound', 'EffectSlot', 'Wwise Tone Generator'}]
        assert {'Action', 'Event', 'Sound'} <= {row['name'] for row in classes}
        validator = SemanticSchemaValidator(version=version)
        available = {row['uri'] for row in validator.manifest_loader.load_manifest(version)['schemas']}
        pins[version] = {
            'build': action['build'], 'action_constructor': action,
            'action_resource_sha256': hashlib.sha256(action_path.read_bytes()).hexdigest(),
            'documented_lists_resource_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'sdk_archive': lists['source'], 'classes': classes,
            'unindexed_classes_not_native_absence': sorted(
                {'Action', 'Event', 'Sound', 'EffectSlot', 'Wwise Tone Generator'} - {row['name'] for row in classes}),
            'reflected_schema_sha256': {uri: hashlib.sha256(_encoded(validator.schema_for(uri))).hexdigest()
                for uri in ('ak.wwise.core.object.create', 'ak.wwise.core.object.set',
                            'ak.wwise.core.object.get', 'ak.wwise.core.object.getPropertyInfo',
                            'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.getTypes',
                            'ak.wwise.core.getInfo') if uri in available},
        }
    assert set(pins) == {'2021.1', '2022.1', '2023.1', '2024.1', VERSION}
    return pins


class _Calls:
    def __init__(self, actor, evidence):
        self.actor, self.evidence = actor, evidence
        self.validator = SemanticSchemaValidator(version=VERSION)

    def __call__(self, uri, args, options=None):
        options = options or {}
        assert len(self.evidence['native_calls']) < BOUNDS['native_calls'], 'native call ceiling'
        validation = self.validator.validate(uri, args, options).as_dict()
        record = {'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options),
                  'schema_validation': validation}
        self.evidence['native_calls'].append(record)
        try:
            result = self.actor(uri, args, options)
            assert len(_encoded(result)) <= BOUNDS['result_bytes_per_call'], 'native result byte ceiling'
            record['result'] = result
            assert len(_encoded(self.evidence)) <= BOUNDS['evidence_bytes'], 'evidence byte ceiling'
            return result
        except BaseException as exc:
            record['error'] = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
            raise


def _one(rows):
    assert len(rows) == 1, rows
    return rows[0]


def _lookup(call, source, fields):
    rows = call('ak.wwise.core.object.get', {'from': source}, {'return': fields})['return']
    assert len(rows) <= BOUNDS['members_per_owner'], 'object row ceiling'
    assert len({row['id'] for row in rows}) == len(rows), 'duplicate object GUID'
    return rows


def _snapshot(call, identity, profile):
    owner_fields = BASE + (['@Effects'] if profile == 'effect_slot' else ['@IsVoice'] if profile == 'source' else [])
    owner = _one(_lookup(call, {'id': [identity]}, owner_fields))
    if profile == 'effect_slot':
        ids = [row['id'] for row in owner.get('@Effects', [])]
        assert len(ids) <= BOUNDS['members_per_owner'] and len(set(ids)) == len(ids)
        members = _lookup(call, {'id': ids}, BASE + FIELDS[profile]) if ids else []
        assert {row['id'] for row in members} == set(ids)
    else:
        members = call('ak.wwise.core.object.get', {'from': {'id': [identity]},
            'transform': [{'select': ['children']}, {'range': [0, BOUNDS['members_per_owner'] + 1]}]},
            {'return': BASE + FIELDS[profile]})['return']
        assert len(members) <= BOUNDS['members_per_owner'], 'child row ceiling'
    assert len({row['id'] for row in members}) == len(members), 'duplicate member GUID'
    for member in members:
        assert {'id', 'name', 'type', 'classId', 'path'} <= set(member), member
        relation = member.get('owner' if profile == 'effect_slot' else 'parent')
        assert isinstance(relation, dict) and relation['id'] == identity, member
        assert all(field in member for field in FIELDS[profile]), member
    return {'owner': owner, 'members': members}


def collect_observations(actor, evidence):
    """Observe selected fixed profiles; never derive conflict equivalence."""
    call = _Calls(actor, evidence)
    profiles = evidence['selected_profiles']
    info = call('ak.wwise.core.getInfo', {})
    evidence['get_info'] = info
    version = info['version']
    actual_build = '.'.join(str(version[key]) for key in ('year', 'major', 'minor', 'build'))
    assert info['isCommandLine'] is True and actual_build == evidence['source_pins'][VERSION]['build']
    project = call('ak.wwise.core.getProjectInfo', {})
    languages = [row for row in project['languages'] if row['name'] in {'English(US)', 'Japanese'}]
    assert len(languages) == 2 and {row['name'] for row in languages} == {'English(US)', 'Japanese'}
    assert len({row['id'] for row in languages}) == 2
    evidence['project_info'], evidence['selected_languages'] = project, languages
    catalog = call('ak.wwise.core.object.getTypes', {})['return']
    selected = {name: _one([row for row in catalog if row['name'] == name]) for name in
                ('Action', 'Event', 'Sound', 'EffectSlot', 'Wwise Tone Generator')}
    for source in evidence['source_pins'][VERSION]['classes']:
        assert selected[source['name']]['classId'] == source['class_id']
    evidence['selected_live_types'] = selected
    evidence['selected_live_fields'] = {}
    if 'action' in profiles:
        action_metadata = call('ak.wwise.core.object.getPropertyInfo',
            {'classId': selected['Action']['classId'], 'property': 'ActionType'})
        play = _one([row for row in action_metadata['restriction']['values'] if row['displayName'] == '/Play'])
        evidence['selected_live_fields']['ActionType'] = action_metadata
    if 'source' in profiles:
        frequency_metadata = call('ak.wwise.core.object.getPropertyInfo',
            {'classId': selected['Wwise Tone Generator']['classId'], 'property': 'StartFreq'})
        restriction = frequency_metadata['restriction']
        assert restriction['type'] == 'range' and restriction['min'] <= 440 < 660 <= restriction['max']
        evidence['selected_live_fields']['StartFreq'] = frequency_metadata
    units = {key: _one(_lookup(call, {'path': [path]}, BASE)) for key, path in
             [('event', r'\Events\Default Work Unit'), ('sound', r'\Containers\Default Work Unit')]
             if key == 'sound' or 'action' in profiles}
    assert all(row['type'] == 'WorkUnit' for row in units.values())
    targets = []
    for name in (('CollisionTargetA', 'CollisionTargetB') if 'action' in profiles else ()):
        created = call('ak.wwise.core.object.create', {'parent': units['sound']['id'], 'type': 'Sound',
            'name': name, 'onNameConflict': 'fail'})
        target = _one(_lookup(call, {'id': [created['id']]}, BASE))
        assert target['type'] == 'Sound' and target['classId'] == selected['Sound']['classId']
        targets.append(target)
    evidence['targets_before'] = targets
    for profile in profiles:
        for mode in ('rename', 'merge', 'replace'):
            name = f'ConstructorCollision_{profile}_{mode}'
            owner_type = 'Event' if profile == 'action' else 'Sound'
            unit = units['event' if profile == 'action' else 'sound']
            owner_node = {'type': owner_type, 'name': name, 'notes': 'retain owner'}
            if profile == 'action':
                seed = {'type': 'Action', 'name': '', '@ActionType': play['value'], '@Target': targets[0]['id'], 'notes': 'original'}
                member = {**seed, '@Target': targets[1]['id'], 'notes': 'requested'}
                owner_node['children'] = [seed]
            elif profile == 'effect_slot':
                seed = {'type': 'EffectSlot', 'name': '', '@Effect': None, '@Bypass': True, '@Render': False}
                member = {**seed, '@Bypass': False, '@Render': True}
                owner_node['@Effects'] = [seed]
            else:
                seed = {'type': 'Source', 'name': 'SameName', 'classId': selected['Wwise Tone Generator']['classId'],
                        'language': 'English(US)', '@StartFreq': 660, 'notes': 'original'}
                member = {**seed, 'language': 'Japanese', '@StartFreq': 440, 'notes': 'requested'}
                owner_node['@IsVoice'] = True
                source_seed_nodes = [seed,
                    {**seed, 'name': 'UnrelatedJapanese', 'language': 'Japanese', 'notes': 'retain unrelated'}]
            # Setup is separate from the discriminator, always fail-on-name.
            call('ak.wwise.core.object.set', {'objects': [{'object': unit['id'], 'children': [owner_node]}],
                'onNameConflict': 'fail', 'listMode': 'append'})
            owner = _one(_lookup(call, {'path': [unit['path'] + '\\' + name]}, BASE))
            assert owner['type'] == owner_type and owner['classId'] == selected[owner_type]['classId']
            if profile == 'source':
                # Reuse the retained R44/voice_source_staging sequence: Source
                # language needs an independently verified existing Voice.
                empty_voice = _snapshot(call, owner['id'], profile)
                assert empty_voice['owner']['@IsVoice'] is True and empty_voice['members'] == []
                assert empty_voice['owner']['notes'] == 'retain owner'
                source_seed_args = {'objects': [{'object': owner['id'], 'children': source_seed_nodes}],
                                    'onNameConflict': 'fail', 'listMode': 'append'}
                source_stage = {'mode': mode, 'empty_voice': empty_voice, 'request': source_seed_args}
                evidence['source_owner_stages'].append(source_stage)
                source_stage['native_result'] = call('ak.wwise.core.object.set', source_seed_args)
            before = _snapshot(call, owner['id'], profile)
            assert len(before['members']) == (2 if profile == 'source' else 1)
            assert all(row['classId'] == selected['Wwise Tone Generator' if profile == 'source' else
                       'EffectSlot' if profile == 'effect_slot' else 'Action']['classId'] for row in before['members'])
            if profile == 'action':
                old = _one(before['members'])
                target = old['@Target']
                assert old['name'] == '' and old['@ActionType'] == play['value'] and old['notes'] == 'original'
                assert (target['id'] if isinstance(target, dict) else target) == targets[0]['id']
            elif profile == 'effect_slot':
                old = _one(before['members'])
                assert old['name'] == '' and _closed_object_reference_id(
                    old['@Effect'], field='EffectSlot.@Effect', allow_none=True) is None
                assert old['@Bypass'] is True and old['@Render'] is False
            else:
                assert before['owner'] == empty_voice['owner'], 'Source setup changed independently verified Voice'
                assert before['owner']['@IsVoice'] is True
                assert {(row['name'], row['audioSource:language']['name'], row['@StartFreq'], row['notes'])
                        for row in before['members']} == {
                            ('SameName', 'English(US)', 660, 'original'),
                            ('UnrelatedJapanese', 'Japanese', 660, 'retain unrelated')}
            if profile == 'action':
                uri = 'ak.wwise.core.object.create'
                args = {'parent': owner['id'], **member, 'onNameConflict': mode}
            else:
                uri = 'ak.wwise.core.object.set'
                args = {'objects': [{'object': owner['id'], '@Effects' if profile == 'effect_slot' else 'children': [member]}],
                        'onNameConflict': mode, 'listMode': 'append'}
            case = {'profile': profile, 'mode': mode, 'uri': uri, 'request': args, 'before': before,
                    'schema_validation': call.validator.validate(uri, args, {}).as_dict()}
            evidence['cases'].append(case)
            try:
                case['native_result'] = call(uri, args)
                case['outcome'] = 'returned'
            except Exception as exc:
                from waapi import WaapiRequestFailed
                if not isinstance(exc, WaapiRequestFailed):
                    raise
                case['outcome'] = 'native_rejection'
                case['native_error'] = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
            case['after'] = _snapshot(call, owner['id'], profile)
            old_ids = {row['id'] for row in before['members']}
            new_ids = {row['id'] for row in case['after']['members']}
            case['removed_exact_id_readbacks'] = {identity: _lookup(call, {'id': [identity]}, BASE + FIELDS[profile])
                                                  for identity in sorted(old_ids - new_ids)}
            case['membership_delta'] = {'retained': sorted(old_ids & new_ids), 'removed': sorted(old_ids - new_ids),
                                        'added': sorted(new_ids - old_ids)}
    evidence['targets_after'] = [_one(_lookup(call, {'id': [target['id']]}, BASE)) for target in targets]
    assert evidence['targets_before'] == evidence['targets_after'], 'unrelated Action targets changed'
    assert len(evidence['cases']) == evidence['requested_discriminators']


def run_diagnostic(lifecycle, *, actor_factory=None, profiles=PROFILES):
    """Seal collection evidence before finish; lifecycle.json owns the final outcome."""
    profiles = _validate_profiles(profiles)
    if actor_factory is None:
        from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
        actor_factory = OwnedDirectWaapiCall
    evidence = {'kind': 'native-constructor-collision-diagnostic', 'version': VERSION,
                'public_gateway_pass': False, 'agent_semantic_pass': False,
                'bounds': BOUNDS, 'source_pins': source_pins(), 'cases': [], 'native_calls': [],
                'selected_profiles': list(profiles), 'requested_discriminators': len(profiles) * 3,
                'native_writes_max': len(profiles) * 6 + (2 if 'action' in profiles else 0) + (3 if 'source' in profiles else 0),
                'source_owner_stages': []}
    runtime = actor = None
    status, reason = 'FAIL', 'diagnostic did not complete'
    try:
        runtime = lifecycle.start()
        actor = actor_factory(host=runtime.host, port=runtime.port)
        collect_observations(actor, evidence)
        status, reason = 'PASS', ''
        return evidence
    except BaseException as exc:
        reason = f'{type(exc).__name__}: {exc}'[:4096]
        evidence['error'] = reason
        raise
    finally:
        evidence['collection_status'] = status
        closed = True
        if actor is not None:
            try:
                closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                closed = False
                evidence['actor_close_error'] = str(exc)[:4096]
        if not closed:
            status, reason = 'BLOCKED', 'owned direct actor did not close'
        evidence['status'], evidence['reason'] = 'PENDING', reason
        evidence['final_outcome'] = {'path': 'lifecycle.json', 'field': 'final_status'}
        if runtime is not None:
            try:
                payload = _encoded(evidence)
                assert len(payload) <= BOUNDS['evidence_bytes'], 'evidence byte ceiling'
                (runtime.evidence_root / 'object-constructor-collisions.json').write_bytes(payload)
            except BaseException:
                status, reason = 'BLOCKED', 'diagnostic evidence could not be sealed'
                raise
            finally:
                # No required evidence writes may follow the authoritative final receipt.
                finished = lifecycle.finish(status, reason=reason)
                assert finished.final_status == status, finished
        if 'error' not in evidence:
            assert closed, reason

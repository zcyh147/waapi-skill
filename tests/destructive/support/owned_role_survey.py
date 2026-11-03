"""Fixed, read-only 2025 instance/owner source collection; parent owns launch.

No constructor, automatic-birth, public-Gateway or per-class functional credit.
The existing ScenarioLifecycle remains the source/cleanup receipt authority.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re

from wwise_waapi.builders.schema import SemanticSchemaValidator
from wwise_waapi.operation_plugin import _closed_object_reference_id

VERSION = '2025.1'
CLASSES = (
    'ActionException', 'ControlSurfaceBinding', 'ControlSurfaceBindingGroup',
    'CustomState', 'ExternalSource', 'ExternalSourceFile', 'Language',
    'MediaPoolQuery', 'MidiParameter', 'MusicFade', 'MusicTransition', 'Panner',
    'Path2D', 'PluginDataSource', 'Position', 'StateGroupInfo', 'UserProjectSettings',
)
INFO = 'ak.wwise.core.getInfo'
TYPES = 'ak.wwise.core.object.getTypes'
GET = 'ak.wwise.core.object.get'
READ_ONLY_URIS = frozenset({INFO, TYPES, GET})
FIELDS = ['id', 'name', 'type', 'classId', 'path', 'parent', 'owner']
BOUNDS = {'native_calls': 48, 'instances_per_class': 2, 'related_ids': 64,
    'bytes_per_result': 256 * 1024, 'evidence_bytes': 4 * 1024 * 1024}
EVIDENCE_FILE = 'owned-role-survey.json'
_GUID = re.compile(r'^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$')


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def source_roster():
    root = Path(__file__).resolve().parents[3]
    path = root / 'skills/waapi-skill/resources/metadata/2025.1/object-types.json'
    raw = path.read_bytes()
    catalog = json.loads(raw)
    assert catalog['metadata']['wwise_version_target'] == VERSION
    rows = []
    for name in CLASSES:
        matches = [row for row in catalog['types'] if row['name'] == name]
        assert len(matches) == 1 and matches[0]['type'] == 'WObject', name
        rows.append(deepcopy(matches[0]))
    return {'path': str(path.relative_to(root)), 'sha256': sha256(raw).hexdigest(),
        'build': catalog['metadata']['wwise_build'], 'classes': rows,
        'retained_getTypes_result_sha256': catalog['metadata']['source_result_sha256']}


def _guid(value):
    assert isinstance(value, str) and _GUID.fullmatch(value), 'Malformed returned GUID'
    return value.upper()


def _rows(result, *, maximum):
    assert isinstance(result, dict) and isinstance(result.get('return'), list), 'Missing return rows'
    rows = result['return']
    assert len(rows) <= maximum, 'Returned row bound exceeded'
    seen = set()
    for row in rows:
        assert isinstance(row, dict)
        identity = _guid(row.get('id'))
        assert identity not in seen, 'Duplicate returned GUID'
        seen.add(identity)
        assert isinstance(row.get('name'), str)
        assert row.get('path') is None or isinstance(row['path'], str)
        assert isinstance(row.get('type'), str) and row['type']
        assert type(row.get('classId')) is int
    return rows


def collect(actor, evidence):
    """One bounded source schedule; query rejection is a retained finding."""
    from waapi import WaapiRequestFailed
    validator = SemanticSchemaValidator(version=VERSION)

    def call(uri, args, options=None):
        assert uri in READ_ONLY_URIS, 'Survey URI is outside the fixed read-only allowlist'
        assert len(evidence['native_calls']) < BOUNDS['native_calls']
        options = options or {}
        record = {'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options),
            'schema_validation': validator.validate(uri, args, options).as_dict()}
        evidence['native_calls'].append(record)
        try:
            result = actor(uri, args, options)
            raw = _encoded(result)
            record['result_bytes'] = len(raw)
            record['result_sha256'] = sha256(raw).hexdigest()
            assert len(raw) <= BOUNDS['bytes_per_result'], 'Native result byte bound exceeded'
            record['result'] = result
            # Leave room for bounded error/finalization facts; never retain an oversized document.
            if len(_encoded(evidence)) > BOUNDS['evidence_bytes'] - 65536:
                del record['result']
                raise ValueError('Survey evidence byte bound exceeded')
            record['result_schema_validation'] = validator.validate_result(uri, result).as_dict()
            return result
        except BaseException as exc:
            record['error'] = {'type': type(exc).__name__, 'message': str(exc)[:4096],
                **({'uri': exc.uri} if isinstance(exc, WaapiRequestFailed) else {})}
            raise

    info = call(INFO, {})
    evidence['live_identity'] = {'isCommandLine': info['isCommandLine'], 'version': info['version']}
    build = '.'.join(str(info['version'][key]) for key in ('year', 'major', 'minor', 'build'))
    assert info['isCommandLine'] is True and build == evidence['source']['build'], 'Wrong host/build'
    registrations = call(TYPES, {})['return']
    assert isinstance(registrations, list)
    related, sampled = set(), set()
    for source in evidence['source']['classes']:
        registered = [row for row in registrations if row.get('name') == source['name']]
        finding = {'class_name': source['name'], 'source_class_id': source['classId']}
        evidence['classes'].append(finding)
        if not registered:
            finding['finding'] = 'absent_class_in_live_getTypes'
            continue
        assert len(registered) == 1 and all(registered[0].get(key) == source[key]
            for key in ('name', 'type', 'classId')), 'Source/live class registration drift'
        finding['registration'] = deepcopy(registered[0])
        finding['call_index'] = len(evidence['native_calls'])
        try:
            result = call(GET, {'from': {'ofType': [source['name']]},
                'transform': [{'range': [0, 2]}]}, {'return': FIELDS})
        except WaapiRequestFailed as exc:
            finding.update(finding='registered_type_query_rejected', native_error_uri=exc.uri,
                queryability='this_exact_ofType_request_rejected; not_native_absence')
            continue
        rows = _rows(result, maximum=BOUNDS['instances_per_class'])
        finding.update(finding='sampled_instances' if rows else 'registered_no_instance_in_sample',
            instance_ids=[row['id'] for row in rows], sample_is_complete=False)
        for row in rows:
            finding.setdefault('identity_observations', []).append({
                'id': row['id'], 'type': row['type'], 'classId': row['classId'],
                'type_matches_registration': row['type'] == source['name'],
                'class_id_matches_registration': row['classId'] == source['classId'],
                'registration_matches': row['type'] == source['name'] and row['classId'] == source['classId'],
                'certifies_constructibility': False})
            sampled.add(_guid(row['id']))
            for field in ('parent', 'owner'):
                reference = row.get(field)
                if reference is None:
                    continue
                if isinstance(reference, dict) and 'id' not in reference:
                    finding.setdefault('unresolved_related_references', []).append({'id': row['id'], 'field': field})
                    continue
                identity = _closed_object_reference_id(reference, field='role-survey.' + field, allow_none=True)
                if identity is not None:
                    related.add(_guid(identity))
    lookup_ids = sorted(related - sampled)
    assert len(lookup_ids) <= BOUNDS['related_ids'], 'Related identity batch bound exceeded'
    evidence['related_lookup'] = {'ids': lookup_ids, 'sampled_identities_reused': sorted(related & sampled)}
    if lookup_ids:
        evidence['related_lookup']['call_index'] = len(evidence['native_calls'])
        result = call(GET, {'from': {'id': lookup_ids}}, {'return': FIELDS})
        rows = _rows(result, maximum=BOUNDS['related_ids'])
        assert {_guid(row['id']) for row in rows} == set(lookup_ids), 'Related identity lookup is incomplete or extra'
    evidence['survey_completed'] = True
    return evidence


def run_survey(lifecycle, *, actor_factory=None):
    """Persist raw collection before the existing authoritative lifecycle receipt."""
    if actor_factory is None:
        from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
        actor_factory = OwnedDirectWaapiCall
    evidence = {'contract': 'waapi-skill.owned-role-source-survey/v1', 'version': VERSION,
        'source': source_roster(), 'bounds': BOUNDS, 'read_only_uris': sorted(READ_ONLY_URIS),
        'native_calls': [], 'classes': [], 'public_gateway_pass': False, 'agent_semantic_pass': False,
        'constructor_proven': False, 'automatic_birth_proven': False, 'per_class_execution_credit': False}
    runtime, actor = None, None
    status, reason, closed = 'FAIL', '', True
    try:
        runtime = lifecycle.start()
        evidence['owned_scope'] = {'host': runtime.host, 'port': runtime.port,
            'sandbox_project': str(runtime.sandbox.sandbox_project),
            'source_project': str(runtime.sandbox.source_project),
            'launch_command': list(runtime.lifecycle.command),
            'source_hash_before': asdict(runtime.source_hash_before),
            'source_mtime_before_ns': runtime.source_mtime_before_ns}
        actor = actor_factory(host=runtime.host, port=runtime.port)
        collect(actor, evidence)
        status = 'PASS'
    except BaseException as exc:
        reason = str(exc)[:4096]
        evidence['error'] = {'type': type(exc).__name__, 'message': reason}
        raise
    finally:
        if actor is not None:
            try:
                closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                closed = False
                evidence['actor_close_error'] = str(exc)[:4096]
            if not closed:
                status, reason = 'BLOCKED', 'Owned read-only actor could not close'
        evidence['collection_status'] = status
        evidence['status'] = 'PENDING'
        evidence['final_outcome'] = {'path': 'lifecycle.json', 'field': 'final_status'}
        if runtime is not None:
            try:
                encoded = _encoded(evidence)
                assert len(encoded) <= BOUNDS['evidence_bytes']
                (runtime.evidence_root / EVIDENCE_FILE).write_bytes(encoded)
            except BaseException:
                status, reason = 'BLOCKED', 'Owned role survey evidence could not be sealed'
                raise
            finally:
                finished = lifecycle.finish(status, reason=reason)
                assert finished.final_status == status, finished
        if 'error' not in evidence:
            assert closed, reason
    return evidence

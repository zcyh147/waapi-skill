"""One unproved Project-parent Language constructor candidate in an owned copy.

This developer diagnostic is not a public gateway route. It must stop after any
rejection or ambiguous effect: no retry, alternative parent, List name or type.
ScenarioLifecycle remains the sole source-integrity and final cleanup authority.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import uuid4
import xml.etree.ElementTree as ET

from wwise_waapi.builders.schema import SemanticSchemaValidator
from wwise_waapi.host_paths import localize_waapi_host_path

VERSION = '2025.1'
INFO, PROJECT_INFO, TYPES, GET, CREATE, SAVE = (
    'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.getTypes',
    'ak.wwise.core.object.get', 'ak.wwise.core.object.create', 'ak.wwise.core.project.save')
ALLOWED_URIS = frozenset({INFO, PROJECT_INFO, TYPES, GET, CREATE, SAVE})
FIELDS = ['id', 'name', 'type', 'classId', 'path', 'parent', 'owner']
PROJECT_FIELDS = FIELDS + ['filePath', 'DefaultLanguage', 'UseDefaultLanguage']
BOUNDS = {'native_calls': 16, 'create_attempts': 1, 'save_attempts': 1,
    'language_rows': 256, 'bytes_per_result': 262144, 'evidence_bytes': 2097152,
    'project_file_bytes': 16777216, 'project_xml_nodes': 65536}
EVIDENCE_FILE = 'language-registration-candidate.json'
_GUID = re.compile(r'^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$')


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def _guid(value):
    assert isinstance(value, str) and _GUID.fullmatch(value), 'Malformed native GUID'
    assert value != '{00000000-0000-0000-0000-000000000000}', 'Zero native GUID'
    return value.upper()


def source_pins():
    root = Path(__file__).resolve().parents[3]
    paths = ['skills/waapi-skill/resources/metadata/2025.1/object-types.json',
        'skills/waapi-skill/resources/manifest/2025.1/schemas.json']
    raw = {path: (root / path).read_bytes() for path in paths}
    catalog = json.loads(raw[paths[0]])
    classes = {name: [row for row in catalog['types'] if row['name'] == name]
        for name in ('Project', 'Language')}
    assert all(len(rows) == 1 and rows[0]['type'] == 'WObject' for rows in classes.values())
    return {'build': catalog['metadata']['wwise_build'],
        'files': {path: sha256(value).hexdigest() for path, value in raw.items()},
        'classes': {name: rows[0] for name, rows in classes.items()},
        'candidate_basis': 'generic create schema plus saved Project registration ownership; placement unproved'}


def _one(rows):
    assert isinstance(rows, list) and len(rows) == 1, 'Expected one exact native row'
    return rows[0]


def _languages(rows, *, typed=False):
    assert isinstance(rows, list) and len(rows) <= BOUNDS['language_rows'], 'Incomplete/oversized language inventory'
    result, names = {}, set()
    for row in rows:
        assert isinstance(row, dict)
        identity, name = _guid(row.get('id')), row.get('name')
        assert isinstance(name, str) and name and len(name.encode('utf-8')) <= 256
        assert identity not in result and name.casefold() not in names, 'Duplicate language identity/name'
        if typed:
            assert row.get('type') == 'Language' and row.get('classId') == 4915216, 'Wrong Language class'
        result[identity] = deepcopy(row)
        names.add(name.casefold())
    assert result, 'Empty language baseline'
    return result


def _value(row, name):
    keys = [key for key in (name, '@' + name) if key in row]
    assert keys and all(row[key] == row[keys[0]] for key in keys), 'Missing/contradictory default-language setting'
    return row[keys[0]]


def _saved_project(path):
    with path.open('rb') as stream:
        raw = stream.read(BOUNDS['project_file_bytes'] + 1)
    assert len(raw) <= BOUNDS['project_file_bytes'], 'Project XML exceeds byte bound'
    assert b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'Unsafe Project XML'
    tree = ET.fromstring(raw)
    assert sum(1 for _ in tree.iter()) <= BOUNDS['project_xml_nodes'], 'Project XML exceeds node bound'
    project = _one(tree.findall('./ProjectInfo/Project'))
    language_list = _one(project.findall('LanguageList'))
    assert all(child.tag == 'Language' for child in language_list), 'Unexpected LanguageList entry'
    rows = [{'id': child.attrib['ID'], 'name': child.attrib['Name'], 'attributes': dict(child.attrib)}
        for child in language_list]
    return {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'project_id': _guid(project.attrib['ID']),
        'languages': _languages(rows), 'explicit_default_settings': {
            node.attrib['Name']: dict(node.attrib) for node in project.findall('./PropertyList/Property')
            if node.get('Name') in {'DefaultLanguage', 'UseDefaultLanguage'}}}


def _addition(before, after, identity, name):
    assert set(after) == set(before) | {identity} and identity not in before, 'Language population changed unexpectedly'
    assert all(after[key] == row for key, row in before.items()), 'Existing language changed'
    assert after[identity]['name'] == name, 'New registered language has wrong name'


def collect(actor, evidence, runtime):
    validator = SemanticSchemaValidator(version=VERSION)

    def call(uri, args, options=None):
        assert uri in ALLOWED_URIS and len(evidence['native_calls']) < BOUNDS['native_calls']
        if uri in {CREATE, SAVE}:
            limit = BOUNDS['create_attempts' if uri == CREATE else 'save_attempts']
            assert sum(row['uri'] == uri for row in evidence['native_calls']) < limit, 'No native mutation retry'
        options = options or {}
        record = {'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options),
            'schema_validation': validator.validate(uri, args, options).as_dict()}
        if uri in {CREATE, SAVE}:
            record['mutation'] = {'attempted': True, 'acknowledged': False, 'result_validated': False}
        record['response_kind'] = 'none'
        evidence['native_calls'].append(record)  # Count even rejected/ambiguous dispatches.
        try:
            result = actor(uri, args, options)
            record['response_kind'] = 'result'
            if 'mutation' in record:
                record['mutation']['acknowledged'] = True
            raw = _encoded(result)
            record.update(result_bytes=len(raw), result_sha256=sha256(raw).hexdigest())
            assert len(raw) <= BOUNDS['bytes_per_result'], 'Native result exceeds byte bound'
            record['result'] = deepcopy(result)
            if len(_encoded(evidence)) > BOUNDS['evidence_bytes'] - 65536:
                del record['result']
                raise ValueError('Diagnostic evidence exceeds byte bound')
            record['result_schema_validation'] = validator.validate_result(uri, result).as_dict()
            if 'mutation' in record:
                record['mutation']['result_validated'] = True
            return result
        except BaseException as exc:
            from waapi import WaapiRequestFailed
            if isinstance(exc, WaapiRequestFailed):
                record['response_kind'] = 'native_error'
                # An explicit server error is not a documented atomic no-effect
                # guarantee for these two mutation APIs. Preserve it separately
                # from transport loss without inventing rollback certainty.
                record['native_error_no_effect_certified'] = False
            record['error'] = {'type': type(exc).__name__, 'message': str(exc)[:4096],
                **({'uri': str(exc.uri)[:512]} if hasattr(exc, 'uri') else {})}
            mutations = [index for index, row in enumerate(evidence['native_calls']) if 'mutation' in row]
            if mutations:
                evidence['mutation_uncertainty'] = {'failed_call_index': len(evidence['native_calls']) - 1,
                    'mutation_call_indices': mutations,
                    'reason': 'mutation_response_missing_or_unvalidated' if 'mutation' in record
                        else 'postwrite_observation_unavailable'}
            raise

    def project_info():
        info = call(PROJECT_INFO, {})
        owned = runtime.sandbox.sandbox_project.resolve(strict=True)
        assert Path(localize_waapi_host_path(info['path'])).resolve(strict=True) == owned, 'Live project is not the owned copy'
        assert not owned.samefile(runtime.sandbox.source_project), 'Never inspect/mutate source project'
        _languages(info['languages'])
        return info

    def project_row(args):
        row = _one(call(GET, args, {'return': PROJECT_FIELDS})['return'])
        assert row['type'] == 'Project' and row['classId'] == 196624 and row['path'] == '\\'
        assert Path(localize_waapi_host_path(row['filePath'])).resolve(strict=True) == runtime.sandbox.sandbox_project.resolve(strict=True)
        assert isinstance(_value(row, 'DefaultLanguage'), str) and type(_value(row, 'UseDefaultLanguage')) is bool
        return row

    def inventory():
        return _languages(call(GET, {'from': {'ofType': ['Language']},
            'transform': [{'range': [0, BOUNDS['language_rows'] + 1]}]}, {'return': FIELDS})['return'], typed=True)

    def preserve_settings(before_info, after_info, before_root, after_root):
        for key in ('id', 'name', 'path', 'referenceLanguageId', 'currentLanguageId', 'currentPlatformId',
                'platforms', 'defaultConversion', 'directories'):
            assert after_info[key] == before_info[key], 'Project context/default-language setting changed: ' + key
        assert after_root == before_root, 'Project identity/default-language settings changed'

    info = call(INFO, {})
    evidence['get_info'] = info
    build = '.'.join(str(info['version'][key]) for key in ('year', 'major', 'minor', 'build'))
    assert info['isCommandLine'] is True and build == evidence['source']['build'], 'Wrong native host/build'
    types = call(TYPES, {})['return']
    for name, source in evidence['source']['classes'].items():
        found = _one([row for row in types if row.get('name') == name])
        assert all(found.get(key) == source[key] for key in ('name', 'type', 'classId')), 'Live type registration drift'
    before_info = project_info()
    before_root = project_row({'from': {'ofType': ['Project']}, 'transform': [{'range': [0, 2]}]})
    parent = _guid(before_root['id'])
    assert parent == _guid(before_info['id'])
    before_languages = inventory()
    saved_before = _saved_project(runtime.sandbox.sandbox_project)
    assert saved_before['project_id'] == parent
    evidence['before'] = {'project_info': before_info, 'project': before_root,
        'languages': before_languages, 'saved_project': saved_before}
    name = evidence['test_name']
    assert all(row['name'].casefold() != name.casefold() for rows in
        (before_languages, _languages(before_info['languages']), saved_before['languages']) for row in rows.values())
    request = {'parent': before_root['id'], 'type': 'Language', 'name': name,
        'onNameConflict': 'fail', 'autoAddToSourceControl': False}
    evidence['candidate_request'] = deepcopy(request)
    result = call(CREATE, request)
    evidence['create_result'] = result
    identity = _guid(result['id'])
    assert result['name'] == name and identity not in before_languages
    returned = _one(call(GET, {'from': {'id': [result['id']]}}, {'return': FIELDS})['return'])
    assert _guid(returned['id']) == identity and returned['name'] == name
    assert returned['type'] == 'Language' and returned['classId'] == 4915216, 'Returned object is not the requested Language'
    after_languages = inventory()
    after_root = project_row({'from': {'id': [before_root['id']]}})
    after_info = project_info()
    evidence['after'] = {'exact_created_row': returned, 'languages': after_languages,
        'project': after_root, 'project_info': after_info}
    _addition(before_languages, after_languages, identity, name)
    _addition(_languages(before_info['languages']), _languages(after_info['languages']), identity, name)
    preserve_settings(before_info, after_info, before_root, after_root)
    saved_after = _saved_project(runtime.sandbox.sandbox_project)
    evidence['save_needed'] = identity not in saved_after['languages']
    if evidence['save_needed']:
        call(SAVE, {'autoCheckOutToSourceControl': False})
        saved_after = _saved_project(runtime.sandbox.sandbox_project)
        saved_info = project_info()
        saved_root = project_row({'from': {'id': [before_root['id']]}})
        evidence['after_save'] = {'project_info': saved_info, 'project': saved_root}
        _addition(_languages(before_info['languages']), _languages(saved_info['languages']), identity, name)
        preserve_settings(before_info, saved_info, before_root, saved_root)
        assert saved_info['isDirty'] is False, 'Saved registration remains dirty'
    evidence['saved_project_after'] = saved_after
    assert saved_after['project_id'] == parent
    _addition(saved_before['languages'], saved_after['languages'], identity, name)
    assert saved_after['explicit_default_settings'] == saved_before['explicit_default_settings'], 'Saved default-language settings changed'
    evidence['candidate_registration_observed'] = True
    evidence['observation_scope'] = 'one_2025.1.7.9143_Console_Project_parent_create; live_and_saved_registration; no_public_route_or_other_version_credit'


def run_diagnostic(lifecycle, *, actor_factory=None):
    if actor_factory is None:
        from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
        actor_factory = OwnedDirectWaapiCall
    evidence = {'contract': 'waapi-skill.language-registration-candidate/v1', 'version': VERSION,
        'source': source_pins(), 'bounds': dict(BOUNDS), 'native_calls': [],
        'test_name': 'GatewayLanguage195_' + uuid4().hex[:12], 'candidate_registration_observed': False,
        'native_absence_claim': False, 'public_gateway_pass': False, 'agent_semantic_pass': False,
        'five_version_support_proven': False}
    runtime = actor = None
    status, reason, closed = 'FAIL', 'Candidate not proven', True
    try:
        runtime = lifecycle.start()
        evidence['owned_scope'] = {'host': runtime.host, 'port': runtime.port,
            'sandbox_project': str(runtime.sandbox.sandbox_project),
            'source_project': str(runtime.sandbox.source_project),
            'launch_command': list(runtime.lifecycle.command),
            'source_hash_before': asdict(runtime.source_hash_before),
            'source_mtime_before_ns': runtime.source_mtime_before_ns}
        actor = actor_factory(host=runtime.host, port=runtime.port)
        collect(actor, evidence, runtime)
        status, reason = 'PASS', ''
    except BaseException as exc:
        if evidence.get('mutation_uncertainty'):
            status = 'INDETERMINATE'
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
                status, reason = 'BLOCKED', 'Owned language actor could not close'
        evidence.update(collection_status=status, status='PENDING', reason=reason,
            final_outcome={'path': 'lifecycle.json', 'field': 'final_status'})
        if runtime is not None:
            try:
                raw = _encoded(evidence)
                assert len(raw) <= BOUNDS['evidence_bytes']
                (runtime.evidence_root / EVIDENCE_FILE).write_bytes(raw)
            except BaseException:
                status, reason = 'BLOCKED', 'Language diagnostic evidence could not be sealed'
                raise
            finally:
                finished = lifecycle.finish(status, reason=reason)
                assert finished.final_status == status, finished
        if 'error' not in evidence:
            assert closed, reason
    return evidence

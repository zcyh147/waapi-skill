from __future__ import annotations

import importlib.util
import base64
import json
import os
import hashlib
import math
import re
from pathlib import Path
import sys
from time import monotonic as _operator_monotonic, sleep as _operator_sleep
from typing import Mapping
import uuid
import xml.etree.ElementTree as ET

import pytest  # pyright: ignore[reportMissingImports]


if (
    os.getenv("WWISE_LIVE") != "1"
    or os.getenv("WWISE_DESTRUCTIVE") != "1"
    or os.getenv("WWISE_AUTHORING_LIVE") != "1"
):
    pytest.skip(
        "WWISE_LIVE=1, WWISE_DESTRUCTIVE=1, and WWISE_AUTHORING_LIVE=1 "
        "are required for externally launched Authoring business tests",
        allow_module_level=True,
    )


from wwise_waapi.transactions import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    TransactionState,
    TransactionStore,
)
from wwise_waapi.host_paths import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    localize_waapi_host_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
GATEWAY_SPEC = importlib.util.spec_from_file_location(
    "waapi_authoring_ui_business_live_gateway",
    GATEWAY_PATH,
)
assert GATEWAY_SPEC is not None and GATEWAY_SPEC.loader is not None
gateway = importlib.util.module_from_spec(GATEWAY_SPEC)
sys.modules[GATEWAY_SPEC.name] = gateway
GATEWAY_SPEC.loader.exec_module(gateway)


@pytest.fixture(scope='module')
def owned_authoring_layout_batch(request):
    from tests.destructive.support.authoring_batch import AuthoringBatchAdapter
    batch = getattr(request.config, '_waapi_authoring_batch', None)
    if not isinstance(batch, AuthoringBatchAdapter):
        pytest.fail('Layout effects require an actual owner-supplied ScenarioLifecycle batch; environment labels are insufficient')
    yield batch
    batch.prepare_stop(request.session.items)


@pytest.fixture
def owned_authoring_layout_node(owned_authoring_layout_batch, request):
    batch = owned_authoring_layout_batch
    return batch, batch.node_gateway(request.node.nodeid)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_2025_meter_cursor_capture(owned_authoring_layout_node):
    from tests.destructive.support.profiler_capture import collect_owned_capture
    collect_owned_capture(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_2025_loaded_media_event_probe(owned_authoring_layout_node):
    from tests.destructive.support.loaded_media_probe import collect_loaded_event_probe
    collect_loaded_event_probe(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_2025_profiler_readers(owned_authoring_layout_node):
    from tests.destructive.support.profiler_capture import collect_owned_capture
    collect_owned_capture(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_profiler_capture_reads(owned_authoring_layout_node):
    from tests.destructive.support.profiler_capture import collect_owned_capture
    collect_owned_capture(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_2024_meter_projection(owned_authoring_layout_node):
    from tests.destructive.support.profiler_capture import collect_owned_capture
    collect_owned_capture(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_2025_selected_transport_semantics(owned_authoring_layout_node):
    from tests.destructive.support.transport_semantics import collect_selected_transport_semantics
    collect_selected_transport_semantics(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_2025_mixed_transport_semantics(owned_authoring_layout_node):
    from tests.destructive.support.transport_semantics import collect_mixed_transport_semantics
    collect_mixed_transport_semantics(*owned_authoring_layout_node)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_owned_older_transport_semantics(owned_authoring_layout_node):
    from tests.destructive.support.transport_semantics import collect_older_transport_semantics
    collect_older_transport_semantics(*owned_authoring_layout_node)


def _layout_effect(call, suffix, *, layout_handle, fields=()):
    schema = call(['request-schema', 'ak.wwise.ui.layout.' + suffix])
    started = call(schema['continuation']['gateway_argv'])
    draft, authority = started['draft'], started['task_authority']
    declared = call(['draft-declare-layout-plan', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(draft['revision']), '--layout-handle', layout_handle, *fields])
    checked = call(['draft-check', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision'])])
    preview = call(['preview-from-draft', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])])
    tx = preview['transaction_id']
    shown = call(['transaction-show', tx])
    call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
    call(['execute', tx])
    verified = call(['verify', tx])
    assert verified['verification']['business_state_verified'] is True, verified
    return verified


def _owned_layout_start(call):
    original = call(['layout-read', 'current'])['result']['name']
    assert original, 'Owned layout fixture needs a named current layout for restoration'
    anchor = call(['layout-inspect', '--layout-name', original])
    name = 'WAAPI_Skill_Owned_' + uuid.uuid4().hex
    _layout_effect(call, 'setLayout', layout_handle=anchor['layout_handle'], fields=['--new-layout-name', name])
    observed = call(['layout-read', 'contents', '--layout-name', name])['result']
    assert observed['Layout']['Name'] == name
    owned = call(['layout-inspect', '--layout-name', name])
    _layout_effect(call, 'switchLayout', layout_handle=owned['layout_handle'])
    assert call(['layout-read', 'current'])['result']['name'] == name
    return original, name


def _owned_layout_remove(call, original, name):
    restore = call(['layout-inspect', '--layout-name', original])
    _layout_effect(call, 'switchLayout', layout_handle=restore['layout_handle'])
    assert call(['layout-read', 'current'])['result']['name'] == original
    owned = call(['layout-inspect', '--layout-name', name])
    _layout_effect(call, 'removeLayout', layout_handle=owned['layout_handle'])


def test_authoring_layout_owned_registration_and_switch(owned_authoring_layout_node):
    _, call = owned_authoring_layout_node
    original, name = _owned_layout_start(call)
    assert call(['layout-read', 'instances', '--layout-name', name])['result']['viewInstances'] == []
    _owned_layout_remove(call, original, name)


@pytest.mark.parametrize('initial_position', [(), ('--initial-x', '17'), ('--initial-y', '29'),
    ('--initial-x', '17', '--initial-y', '29')], ids=['omitted', 'x-only', 'y-only', 'both'])
def test_authoring_layout_owned_view_lifecycle(owned_authoring_layout_node, initial_position):
    batch, call = owned_authoring_layout_node
    original, name = _owned_layout_start(call)
    assert call(['layout-read', 'instances', '--layout-name', name])['result']['viewInstances'] == []
    types = call(['layout-read', 'types'])['result']['viewTypes']
    assert any(row.get('viewName') == 'ProjectExplorer' for row in types), 'Owned fixture requires the live ProjectExplorer type'
    owned = call(['layout-inspect', '--layout-name', name])
    _layout_effect(call, 'getOrCreateView', layout_handle=owned['layout_handle'],
        fields=['--view-type', 'ProjectExplorer', *initial_position])
    created = call(['layout-read', 'instances', '--layout-name', name])['result']['viewInstances']
    identities = {row['viewID'] for row in created if row.get('viewName') == 'ProjectExplorer'}
    assert len(identities) == 1
    owned = call(['layout-inspect', '--layout-name', name])
    _layout_effect(call, 'getOrCreateView', layout_handle=owned['layout_handle'], fields=['--view-type', 'ProjectExplorer'])
    reused = call(['layout-read', 'instances', '--layout-name', name])['result']['viewInstances']
    assert {row['viewID'] for row in reused if row.get('viewName') == 'ProjectExplorer'} == identities
    if batch.runtime.version == '2025.1':
        owned = call(['layout-inspect', '--layout-name', name])
        views = [row for row in owned['views'] if row['kind'] == 'ProjectExplorer']
        assert len(views) == 1
        _layout_effect(call, 'closeView', layout_handle=owned['layout_handle'], fields=['--view-handle', views[0]['handle']])
        closed = call(['layout-read', 'instances', '--layout-name', name])['result']['viewInstances']
        assert not identities.intersection(row.get('viewID') for row in closed)
    _owned_layout_remove(call, original, name)


MEDIA_DIAGNOSTIC_NODE = (__name__.replace('.', '/') +
    '.py::test_authoring_2024_media_preservation_metadata_diagnostic')
MEDIA_DIAGNOSTIC_SESSIONS = (
    ('{9C02096E-8E29-4029-9D49-778F85015C87}', 'MIDI'),
    ('{1C5BA931-9550-4DC8-B1C7-13689B8AE813}', 'Minigun'),
    ('{F4B8069C-3C15-4157-B570-8A41AB2463C2}', 'Music'),
)


def _media_diagnostic_settings(project, *, owned_root):
    """Hash project-local settings, retaining only the observed RTPC whitelist."""
    from wwise_waapi.operation_soundbank import capture_file_proof, open_regular_artifact_file
    assert project.resolve(strict=True).is_relative_to(owned_root.resolve(strict=True))
    files, entries = [], 0
    for path in project.parent.iterdir():
        entries += 1
        assert entries <= 512, 'Owned settings directory exceeds diagnostic entry bound'
        if not (path.name.casefold().startswith(project.stem.casefold() + '.')
                and path.suffix.casefold() == '.wsettings'):
            continue
        assert len(files) < 4, 'Owned settings file count exceeds diagnostic bound'
        limit = 1024 * 1024
        proof = capture_file_proof(path, field='owned diagnostic settings', max_bytes=limit, io_root=owned_root)
        _, descriptor, before = open_regular_artifact_file(path, field='owned diagnostic settings', io_root=owned_root)
        with os.fdopen(descriptor, 'rb') as stream:
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        assert (len(raw) == proof['size'] and hashlib.sha256(raw).hexdigest() == proof['sha256']
            and all(getattr(before, key) == getattr(after, key)
                    for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
            and capture_file_proof(path, field='owned diagnostic settings', max_bytes=limit, io_root=owned_root) == proof), 'Owned settings changed while observed'
        assert b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'Settings XML declarations are outside this diagnostic'
        root = ET.fromstring(raw)
        assert root.tag == 'WwiseDocument' and root.get('Type') == 'UserProjectSettings'
        nodes, fields, seen = list(root.iter()), [], set()
        assert len(nodes) <= 4096, 'Settings XML exceeds diagnostic node bound'
        for item in nodes:
            name = item.get('Name', '')
            if item.tag != 'Property' or not re.fullmatch(
                    r'RTPC\\GameParameterSimValue\\\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', name):
                continue
            assert name.upper() not in seen and len(fields) < 256, 'Duplicate or oversized settings whitelist'
            seen.add(name.upper())
            value = item.get('Value')
            assert item.get('Type') == 'Real64' and value is not None and len(value) <= 128 and math.isfinite(float(value)) and not list(item), 'Unknown RTPC settings shape'
            fields.append({'name': name, 'type': item.get('Type'), 'value': value})
        files.append({'relative_path': path.name, 'file_proof': proof, 'fields': fields,
            'whitelist': 'RTPC\\GameParameterSimValue\\<canonical GUID> only',
            'unlisted_fields_retained': False})
    return {'complete': True, 'files': sorted(files, key=lambda row: row['relative_path']),
        'scope': 'owned project directory only; no global user settings',
        'state_switch_value_observer': 'not established'}


def test_authoring_2024_media_preservation_metadata_diagnostic(owned_authoring_layout_node):
    """Diagnostic reads only; a successful collection grants no media credit."""
    batch, call = owned_authoring_layout_node
    assert batch.runtime.version == '2024.1' and batch.info['version']['build'] == 9056
    runtime = batch.node_runtimes[MEDIA_DIAGNOSTIC_NODE]
    destination = Path(runtime.runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'media-preservation-diagnostic.json'
    report = {'contract': 'waapi-skill.media-preservation-diagnostic/v1',
        'complete': False, 'business_preservation_verified': False,
        'completeness_scope': 'permitted bounded diagnostic reads; not complete Soundcaster runtime state',
        'runtime_session_values_observed': False, 'media_operation_executed': False,
        'opaque_plugin_payload': 'not interpreted or modified',
        'coverage_credit': 'none; diagnostic observation only', 'host': batch.info,
        'sessions': [], 'field_details': [], 'plugin': {}, 'logs': {}, 'settings': {},
        'requests': [], 'errors': [], 'detail_limit_reached': False,
        'limits': {'public_calls': 32, 'reply_bytes': 256 * 1024, 'total_reply_bytes': 2 * 1024 * 1024,
            'name_pages_per_session': 4, 'names_per_page': 64, 'field_details': 6,
            'plugin_type_pages': 2, 'log_rows_per_channel': 40,
            'settings_files': 4, 'settings_file_bytes': 1024 * 1024,
            'settings_whitelist_rows_per_file': 256}}
    assert not path.exists() and not path.is_symlink(), 'Diagnostic cannot overwrite an earlier observation'
    path.write_text(json.dumps(report, ensure_ascii=False) + '\n', encoding='utf-8')
    total = 0
    def read(argv):
        nonlocal total
        assert len(report['requests']) < 32, 'Public diagnostic call bound exceeded'
        entry = {'argv': argv}
        report['requests'].append(entry)
        payload = call(argv)  # Original replies/errors remain in owner receipts.
        size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        total += size
        assert size <= 256 * 1024 and total <= 2 * 1024 * 1024, 'Public diagnostic byte bound exceeded'
        entry.update(reply_bytes=size, complete_reply_retained_by_owner=True)
        return payload
    project = batch.runtime.sandbox.sandbox_project
    try:
        report['settings']['before'] = _media_diagnostic_settings(project, owned_root=batch.runtime.owned_root)
        for identity, name in MEDIA_DIAGNOSTIC_SESSIONS:
            result = read(['query-object', '--exact-id', identity, '--include', 'class-id', '--max-results', '1'])
            rows = result['objects']
            assert len(rows) == 1 and rows[0]['id'] == identity and rows[0]['name'] == name and rows[0]['type'] == 'SoundcasterSession', 'Exact source session identity changed'
            session = {'id': identity, 'name': name, 'identity': rows[0], 'field_names': [], 'names_complete': False}
            report['sessions'].append(session)
            page, seen_pages, selections = None, set(), []
            for _ in range(4):
                argv = ['metadata', 'list', '--exact-id', identity, '--page-size', '64']
                if page is not None:
                    argv += ['--page', page]
                listed = read(argv)['agent_result']
                for field in listed['fields']:
                    token = field.get('name')
                    assert isinstance(token, str) and token not in session['field_names'], 'Incomplete or duplicate disclosed field name'
                    session['field_names'].append(token)
                    if any(word in token.casefold() for word in ('rtpc', 'state', 'switch', 'gameparameter')):
                        selections.append((token, field['selection']))
                page = listed['next_page']
                if page is None:
                    assert listed['complete'] is True and len(session['field_names']) == listed['total_count'], 'Incomplete disclosed field inventory'
                    session['names_complete'] = True
                    break
                assert page not in seen_pages, 'Repeated metadata page'
                seen_pages.add(page)
            assert session['names_complete'], 'Metadata inventory exceeds diagnostic page bound; not complete'
            for token, selection in selections:
                if len(report['field_details']) == 6:
                    report['detail_limit_reached'] = True
                    break
                detail = read(['metadata', 'detail', '--exact-id', identity, '--selection', selection])['agent_result']
                report['field_details'].append({'object_id': identity, 'disclosed_field': token, **detail})
        rev = '{29975930-6548-4A1B-BEE0-7AA549180D4F}'
        result = read(['query-object', '--exact-id', rev, '--include', 'class-id', '--include', 'plugin-name', '--max-results', '1'])
        assert len(result['objects']) == 1 and result['objects'][0]['id'] == rev, 'Exact REV source identity changed'
        report['plugin']['identity'] = result['objects'][0]
        report['plugin']['types'] = []
        page = None
        for _ in range(2):
            argv = ['metadata', 'types', '--meaning', 'CrankcaseAudio REV', '--page-size', '64']
            if page is not None:
                argv += ['--page', page]
            result = read(argv)['agent_result']
            report['plugin']['types'].extend(result['types'])
            page = result['next_page']
            if page is None:
                break
        assert page is None, 'Plugin type discovery exceeds diagnostic page bound'
        report['plugin']['native_backend_availability_proven'] = False
        for channel in ('project-load', 'general'):
            report['logs'][channel] = read(['core-call', 'ak.wwise.core.log.get', '--log-channel', channel, '--max-results', '40'])['agent_result']
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:2048],
            'original_gateway_replies': 'owner receipts and dispatcher evidence'})
    finally:
        try:
            report['settings']['after'] = _media_diagnostic_settings(project, owned_root=batch.runtime.owned_root)
        except Exception as exc:
            report['errors'].append({'phase': 'settings_after', 'type': type(exc).__name__, 'message': str(exc)[:2048]})
        report['complete'] = not report['errors']
        report['public_call_count'] = len(report['requests'])
        report['total_reply_bytes'] = total
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
    assert report['complete'], report['errors']


SOUNDCASTER_IMAGE_DIAGNOSTIC_NODE = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_authoring_2024_soundcaster_frontend_image_diagnostic')


def _soundcaster_source_witness(batch, destination):
    """Retain original saved expectations; never interpret these as live values."""
    from tests.destructive.support.console_file_observation import observe_console_file
    source = batch.runtime.sandbox.source_root
    files, sessions, members, total = [], [], {}, 0
    for directory in ('Soundcaster Sessions', 'States', 'Switches'):
        entries = []
        for entry in (source / directory).iterdir():
            assert len(entries) < 32, 'Source diagnostic directory exceeds entry bound'
            entries.append(entry)
        for path in sorted(entries):
            assert path.is_file() and path.suffix == '.wwu', 'Unexpected source diagnostic entry'
            observed = observe_console_file(path, io_root=source)
            raw = base64.b64decode(observed['content_base64'], validate=True)
            total += len(raw)
            assert len(raw) <= 1024 * 1024 and total <= 2 * 1024 * 1024, 'Source diagnostic byte bound exceeded'
            assert b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper()
            root = ET.fromstring(raw)
            assert root.tag == 'WwiseDocument' and root.get('Type') == 'WorkUnit'
            assert len(list(root.iter())) <= 16384, 'Source diagnostic XML node bound exceeded'
            relative = path.relative_to(source).as_posix()
            archive = destination / 'original-source' / relative
            archive.parent.mkdir(parents=True, exist_ok=True)
            with archive.open('xb') as stream:
                stream.write(raw)
            files.append({'source_path': relative, 'artifact_path': archive.relative_to(destination).as_posix(),
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'source_file_proof': observed['file_proof']})
            if directory == 'Soundcaster Sessions':
                for session in root.iter('SoundcasterSession'):
                    bindings = []
                    for row in session.findall('./RTPCValueList/RTPCValue'):
                        ref = row.find('GameParameterRef')
                        assert ref is not None and row.findtext('Value') is not None
                        bindings.append({'kind': 'RTPC', 'id': ref.attrib['ID'], 'name': ref.attrib['Name'],
                            'value': row.findtext('Value')})
                    for kind in ('State', 'Switch'):
                        for ref in session.findall(f'./Current{kind}List/Current{kind}Ref'):
                            bindings.append({'kind': kind, 'id': ref.attrib['ID'], 'name': ref.attrib['Name']})
                    sessions.append({'id': session.attrib['ID'], 'name': session.attrib['Name'],
                        'source_path': relative, 'bindings': bindings})
            else:
                kind = 'State' if directory == 'States' else 'Switch'
                for group in root.iter(kind + 'Group'):
                    for member in group.findall('./ChildrenList/' + kind):
                        key = (kind, member.attrib['ID'])
                        assert key not in members, 'Duplicate original group member'
                        members[key] = {'id': group.attrib['ID'], 'name': group.attrib['Name'],
                            'member_name': member.attrib['Name']}
    assert sorted((row['id'], row['name']) for row in sessions) == sorted(MEDIA_DIAGNOSTIC_SESSIONS)
    assert len({row['name'] for row in sessions}) == 3, 'Original session names are not unique'
    counts = {kind: 0 for kind in ('RTPC', 'State', 'Switch')}
    for session in sessions:
        for binding in session['bindings']:
            counts[binding['kind']] += 1
            if binding['kind'] != 'RTPC':
                group = members[(binding['kind'], binding['id'])]
                assert binding['name'] == group['member_name'], 'Original member identity/name mismatch'
                binding['group'] = {'id': group['id'], 'name': group['name']}
    assert counts == {'RTPC': 72, 'State': 16, 'Switch': 12}, 'Original saved binding set changed'
    return {'full_tree_hash': batch.runtime.source_hash_before.digest,
        'project_mtime_ns': batch.runtime.source_mtime_before_ns, 'files': files,
        'sessions': sessions, 'binding_counts': counts,
        'scope': 'original saved expectations only; not loaded session state'}


def test_authoring_2024_soundcaster_frontend_image_diagnostic(owned_authoring_layout_node):
    """Inspect one exact Minigun object; session activation requires image review."""
    batch, call = owned_authoring_layout_node
    assert batch.runtime.version == '2024.1' and batch.info['version']['build'] == 9056
    runtime = batch.node_runtimes[SOUNDCASTER_IMAGE_DIAGNOSTIC_NODE]
    destination = Path(runtime.runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'soundcaster-frontend-diagnostic.json'
    assert not path.exists() and not path.is_symlink(), 'Diagnostic cannot overwrite an earlier observation'
    report = {'contract': 'waapi-skill.soundcaster-frontend-diagnostic/v1', 'complete': False,
        'business_preservation_verified': False, 'runtime_session_values_observed': False,
        'coverage_credit': 'none; diagnostic observation only', 'visual_review': 'unobserved; independent review required',
        'media_operation_executed': False, 'host': batch.info, 'candidate': batch.candidate,
        'source_context': batch.source_context, 'sessions': [], 'requests': [], 'errors': [],
        'activation_request': 'Inspect one exact Minigun object; Soundcaster session loading is unproven',
        'remaining_preservation_scope': 'Music and the complete original 100 saved bindings remain unresolved',
        'limits': {'public_calls': 48, 'reply_bytes': 1024 * 1024, 'total_reply_bytes': 4 * 1024 * 1024,
            'image_base64_chars': 1024 * 1024, 'image_count': 1}}
    path.write_text(json.dumps(report) + '\n', encoding='utf-8')
    operator_enabled = runtime.runner_environment.get('WWISE_SOUNDCASTER_OPERATOR_OBSERVATION') == '1'
    if operator_enabled:
        report['limits']['image_count'] = 2
    total, executed = 0, {}
    def bounded_call(argv):
        nonlocal total
        assert len(report['requests']) < report['limits']['public_calls'], 'Diagnostic call bound exceeded'
        entry = {'argv': list(argv)}
        report['requests'].append(entry)
        payload = call(argv)
        size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        total += size
        assert size <= report['limits']['reply_bytes'] and total <= report['limits']['total_reply_bytes'], 'Diagnostic reply bound exceeded'
        entry.update(reply_bytes=size, complete_reply_retained_by_owner=True)
        if argv[0] == 'execute':
            executed[payload['transaction_id']] = payload
        return payload
    def effect(operation, fields):
        preview = _preview_business_plan(operation, fields, owner_call=bounded_call)
        verified = _execute_and_verify(preview, owner_call=bounded_call)
        assert verified['state'] == TransactionState.RESULT_SCHEMA_CHECKED.value, verified
        assert verified['verification']['business_state_verified'] is False, verified
        return {'transaction_id': preview['transaction_id'], 'artifact_hash': preview['artifact_hash'],
            'state': verified['state'], 'business_state_verified': False}
    def observe_inspection():
        selected = bounded_call(['selected'])
        current = bounded_call(['layout-read', 'current'])
        layout = current['result'].get('name')
        assert isinstance(layout, str) and layout, 'No exact current layout for inspection observation'
        instances = bounded_call(['layout-read', 'instances', '--layout-name', layout])
        return {'selected': selected, 'current_layout': current, 'instances': instances,
            'scope': 'active-view selection and current-layout views; not saved session values'}
    def capture_image(session, fields, image_scope, filename):
        capture = effect('ui.captureScreen', fields)
        original = executed[capture['transaction_id']]
        assert original['artifact_hash'] == capture['artifact_hash']
        captured = original['dispatch_result'].get('result')
        if not isinstance(captured, dict):
            # Execute deliberately digests large successes. Read its one
            # already-sealed offline event; never capture again or lift caps.
            shown = bounded_call(['transaction-show', capture['transaction_id']])
            assert (shown['transaction_id'] == capture['transaction_id']
                and shown['artifact_hash'] == capture['artifact_hash']
                and shown['state'] == TransactionState.RESULT_SCHEMA_CHECKED.value)
            events = [event for event in shown['events'] if event['event_type'] == 'execution_completed']
            assert len(events) == 1 and events[0]['artifact_hash'] == capture['artifact_hash']
            captured = events[0]['details']['dispatch_result']['result']
            capture['image_source'] = {'kind': 'public_transaction_show_execution_completed',
                'event_hash': events[0]['event_hash']}
        else:
            capture['image_source'] = {'kind': 'public_execute_dispatch_result'}
        assert isinstance(captured, dict), 'Exact image absent from bounded public result; session remains unobserved'
        encoded = captured.get('contentBase64')
        assert captured.get('contentType') == 'image/png' and isinstance(encoded, str) and 0 < len(encoded) <= 1024 * 1024
        raw = base64.b64decode(encoded, validate=True)
        assert raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Capture does not contain PNG bytes'
        image_path = destination / filename
        with image_path.open('xb') as stream:
            stream.write(raw)
        from wwise_waapi.operation_soundbank import capture_file_proof
        image_proof = capture_file_proof(image_path, field='Soundcaster diagnostic image',
            max_bytes=1024 * 1024, io_root=destination)
        assert image_proof['size'] == len(raw) and image_proof['sha256'] == hashlib.sha256(raw).hexdigest()
        image = {'scope': image_scope, 'file_proof': image_proof, 'path': image_path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'content_type': captured['contentType'], 'capture_transaction_id': capture['transaction_id'],
            'command_transaction_id': session['command']['transaction_id'], 'session_id': session['id'],
            'visual_review': 'unobserved; image/schema success grants no business credit'}
        return capture, image
    def publish():
        report['public_call_count'], report['total_reply_bytes'] = len(report['requests']), total
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
    def block_operator(reason):
        report.setdefault('operator', {}).update(status='blocked', reason=reason)
        pytest.skip('Operator observation incomplete: ' + reason)
    def exact_selected(payload, session):
        rows = payload.get('objects', [])
        return len(rows) == 1 and all(rows[0].get(field) == session['identity'].get(field)
            for field in ('id', 'name', 'type', 'path'))
    def simulation_values():
        results = []
        for identity, name in (('{EB92D28A-BB63-4332-8166-0AC95BAD9EFE}', 'Engine_Load'),
                ('{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'RPM')):
            payload = bounded_call(['query-object', '--exact-id', identity,
                '--include-field', 'SimulationValue', '--max-results', '1'])
            rows = payload['objects']
            assert len(rows) == 1 and rows[0]['id'] == identity and rows[0]['name'] == name and rows[0]['type'] == 'GameParameter', 'Exact GameParameter identity changed'
            results.append(payload)
        return results
    def operator_wait(session):
        # Developer-only synchronization in this owned node, never a Skill UI fallback.
        from wwise_waapi.operation_soundbank import capture_file_proof, open_regular_artifact_file
        if not exact_selected(session['after']['selected'], session):
            block_operator('Exact Minigun selection was not observed after Inspect')
        session['pre_operator_capture'], session['pre_operator_image'] = capture_image(session, [],
            {'kind': 'main-ui', 'phase': 'before-operator'}, 'minigun-before-operator.png')
        marker_path = destination / 'operator-resume.json'
        if marker_path.exists() or marker_path.is_symlink():
            block_operator('Operator marker already exists; stale gate cannot resume collection')
        saved = next(row for row in report['source']['sessions'] if row['id'] == session['id'])
        deadline = _operator_monotonic() + 180
        ready = {'contract': 'waapi-skill.developer-soundcaster-operator/v1', 'gate_id': uuid.uuid4().hex,
            'candidate': batch.candidate, 'nodeid': SOUNDCASTER_IMAGE_DIAGNOSTIC_NODE,
            'owner_root': str(batch.runtime.owned_root), 'node_root': str(runtime.owned_root),
            'evidence_root': str(batch.runtime.evidence_root), 'native_evidence_root': str(destination),
            'host': batch.info, 'endpoint': {'host': runtime.host, 'port': runtime.port},
            'launch_pid': batch.launch_pid, 'sandbox_project': str(batch.runtime.sandbox.sandbox_project),
            'selected': session['after']['selected']['objects'][0], 'pre_image': session['pre_operator_image'],
            'saved_value_checklist': saved['bindings'], 'marker_path': str(marker_path), 'timeout_seconds': 180,
            'deadline_monotonic': deadline,
            'instructions': 'First inventory CUA apps and identify this exact owned Wwise/Wine host/project. If unrecognized, do not launch an installed app: report blocked. Click only the documented RTPC Show All display button in the loaded Minigun ObjectTab. Do not change values, sliders, States, Switches, playback, reset, save, or user projects. Write the exact nonce/context-bound marker to resume collection only; it certifies no values or effect.',
            'marker_example': {'gate_id': None, 'decision': 'resume', 'host_session_id': batch.info['sessionId'],
                'host_process_id': batch.info['processId'], 'sandbox_project': str(batch.runtime.sandbox.sandbox_project),
                'owned_app_identified': True, 'action': 'rtpc-show-all-only'},
            'blocked_marker': 'Use the same gate_id with decision=blocked and a bounded reason if the owned app/control cannot be identified.'}
        ready['marker_example']['gate_id'] = ready['gate_id']
        ready_path = destination / 'operator-ready.json'
        with ready_path.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(ready, ensure_ascii=False, indent=2) + '\n')
        report['operator'] = {'status': 'waiting', 'ready_path': str(ready_path),
            'marker_path': str(marker_path), 'gate_id': ready['gate_id'], 'timeout_seconds': 180,
            'deadline_monotonic': deadline,
            'marker_certifies_values': False, 'scope': 'explicit developer operator observation only'}
        publish()
        print('SOUNDCASTER_OPERATOR_READY ' + str(ready_path), flush=True)
        while _operator_monotonic() < deadline:
            if marker_path.exists() or marker_path.is_symlink():
                try:
                    proof = capture_file_proof(marker_path, field='Operator marker', max_bytes=4096, io_root=destination)
                    _, descriptor, before = open_regular_artifact_file(marker_path, field='Operator marker', io_root=destination)
                    with os.fdopen(descriptor, 'rb') as stream:
                        raw = stream.read(4097)
                        after = os.fstat(stream.fileno())
                    assert len(raw) <= 4096 and len(raw) == proof['size'] and hashlib.sha256(raw).hexdigest() == proof['sha256']
                    assert all(getattr(before, key) == getattr(after, key)
                        for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
                    assert capture_file_proof(marker_path, field='Operator marker', max_bytes=4096, io_root=destination) == proof
                    marker = json.loads(raw)
                    report['operator']['marker'] = marker
                    report['operator']['marker_file_proof'] = proof
                    assert marker.get('gate_id') == ready['gate_id'], 'Marker belongs to a different gate'
                    if marker.get('decision') == 'blocked':
                        block_operator(str(marker.get('reason', 'Owned app/control unavailable'))[:2048])
                    assert marker == ready['marker_example'], 'Marker does not identify the exact owned app/context and permitted action'
                except Exception as exc:
                    block_operator('Invalid operator marker: ' + str(exc)[:1024])
                report['operator']['status'] = 'resumed'
                return
            _operator_sleep(min(0.25, max(0, deadline - _operator_monotonic())))
        block_operator('No operator marker before the fixed 180-second deadline')
    try:
        report['source'] = _soundcaster_source_witness(batch, destination)
        # This controlled activation experiment selects only Minigun. Keep all
        # original saved expectations, but verify the selected identity before UI writes.
        for identity, name in MEDIA_DIAGNOSTIC_SESSIONS[1:2]:
            rows = bounded_call(['query-object', '--exact-id', identity, '--include', 'class-id', '--max-results', '1'])['objects']
            assert (len(rows) == 1 and rows[0]['id'] == identity and rows[0]['name'] == name
                and rows[0]['type'] == 'SoundcasterSession' and rows[0]['class_id'] == 1703952), 'Exact source session identity/class changed'
            report['sessions'].append({'id': identity, 'name': name, 'identity': rows[0]})
        for session in report['sessions']:
            session['before'] = observe_inspection()
            if operator_enabled:
                session['simulation_values'] = {'before': simulation_values(),
                    'scope': 'global GameParameter SimulationValue before/after Inspect; relationship to session presets unproven'}
            session['command'] = effect('ui.commands.execute', ['--command-id', 'Inspect', '--command-object', session['id']])
            session['after'] = observe_inspection()
            if operator_enabled:
                session['simulation_values']['after'] = simulation_values()
            layout = session['after']['current_layout']['result']['name']
            types = bounded_call(['layout-read', 'types'])['result'].get('viewTypes', [])
            registered = [row for row in types if row.get('viewDisplayName') == 'Soundcaster']
            names = {row['viewName'] for row in registered if row.get('viewName')}
            instances = session['after']['instances']['result'].get('viewInstances', [])
            matches = [row for row in instances if row.get('viewName') in names]
            unique = (len(registered) == 1 and len(matches) == 1 and bool(matches[0].get('viewID'))
                and type(matches[0].get('viewIsDocked')) is bool)
            session['view_locator'] = {'complete': unique, 'layout_name': layout,
                'registered_types': registered, 'instances': matches, 'session_id': session['id'],
                'command_transaction_id': session['command']['transaction_id'],
                'binding_scope': 'observed view instance only; selected session requires independent image review'}
            if unique:
                session['view_locator']['instance'] = matches[0]
                fields = ['--view-name', matches[0]['viewName']]
                image_scope = {'kind': 'soundcaster-view', 'view_name': matches[0]['viewName']}
            else:
                # Normal absence/ambiguity must not hide Inspect's other UI
                # effects. This is one diagnostic main image, not a retry.
                fields = []
                image_scope = {'kind': 'main-ui',
                    'reason': 'Soundcaster instance absent or ambiguous; observe generic inspection effect'}
            if operator_enabled:
                operator_wait(session)
                fields, image_scope = [], {'kind': 'main-ui', 'phase': 'after-operator',
                    'marker_certifies_values': False}
            session['capture'], session['image'] = capture_image(session, fields, image_scope,
                session['name'].lower() + '.png')
            if operator_enabled:
                session['operator_selected_after'] = bounded_call(['selected'])
                if not exact_selected(session['operator_selected_after'], session):
                    block_operator('Exact Minigun selection changed during operator observation')
        report['complete'] = True
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:2048]})
    finally:
        publish()
    assert report['complete'], report['errors']


def _gateway_env(tmp_path: Path, *, version: str) -> dict[str, str]:
    sandbox = Path(os.environ["WWISE_AUTHORING_SANDBOX_PROJECT"]).resolve(
        strict=True
    )
    if sandbox.suffix.casefold() != ".wproj":
        raise AssertionError("WWISE_AUTHORING_SANDBOX_PROJECT must be a .wproj")
    source = Path(os.environ["WWISE_SAMPLE_PROJECT_PATH"]).resolve(strict=True)
    if sandbox == source or source.parent == sandbox.parent:
        raise AssertionError("Authoring business tests require a copied sandbox")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": os.getenv("WWISE_WAAPI_HOST", "127.0.0.1"),
                "waapi_port": int(os.getenv("WWISE_WAAPI_PORT", "8080")),
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        **os.environ,
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": version,
    }


def _call(
    argv: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
) -> dict[str, object]:
    code, payload = gateway.execute_gateway(
        ["--state-dir", str(state_dir), *argv],
        env=env,
    )
    assert code == 0, json.dumps(payload, indent=2, ensure_ascii=False)
    assert payload["ok"] is True
    return payload


def _preview_business_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str] | None = None,
    state_dir: Path | None = None,
    owner_call=None,
    registration_key: str | None = None,
) -> dict[str, object]:
    invoke = (lambda argv, **_: owner_call(argv)) if owner_call else (lambda argv, **_: _call(argv, env=env, state_dir=state_dir))
    started = invoke(
        ["draft-start", operation],
        env=env,
        state_dir=state_dir,
    )
    draft = started["draft"]
    assert isinstance(draft, dict)
    draft_id = str(draft["draft_id"])
    authority = str(started["task_authority"])
    declared = invoke(
        [
            "draft-declare-ui-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(draft["revision"]),
            *declaration_args,
        ],
        env=env,
        state_dir=state_dir,
    )
    current = declared["draft"]
    assert isinstance(current, dict)
    if operation == "ui.commands.register":
        assert registration_key is not None
        current = invoke(
            [
                "draft-add-ui-command",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(current["revision"]),
                "--key",
                registration_key,
                "--display-name",
                "WAAPI Skill live notification",
                "--handler-kind",
                "notification",
            ],
            env=env,
            state_dir=state_dir,
        )["draft"]
        assert isinstance(current, dict)
    checked = invoke(
        [
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )
    checked_draft = checked["draft"]
    assert isinstance(checked_draft, dict)
    return invoke(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked_draft["revision"]),
            "--apply",
        ],
        env=env,
        state_dir=state_dir,
    )


def _preview_host_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
) -> dict[str, object]:
    started = _call(
        ["draft-start", operation],
        env=env,
        state_dir=state_dir,
    )
    draft = started["draft"]
    assert isinstance(draft, dict)
    draft_id = str(draft["draft_id"])
    authority = str(started["task_authority"])
    declared = _call(
        [
            "draft-declare-host-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(draft["revision"]),
            *declaration_args,
        ],
        env=env,
        state_dir=state_dir,
    )
    current = declared["draft"]
    assert isinstance(current, dict)
    checked = _call(
        [
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )
    current = checked["draft"]
    assert isinstance(current, dict)
    return _call(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )


def _execute_and_verify(
    preview: dict[str, object],
    *,
    env: dict[str, str] | None = None,
    state_dir: Path | None = None,
    owner_call=None,
) -> dict[str, object]:
    transaction_id = str(preview["transaction_id"])
    invoke = (lambda argv, **_: owner_call(argv)) if owner_call else (lambda argv, **_: _call(argv, env=env, state_dir=state_dir))
    token = (owner_call(["transaction-show", transaction_id])["confirmation"]["token"]
             if owner_call else TransactionStore(state_dir).load_snapshot(transaction_id).confirmation_token)
    invoke(
        [
            "confirm",
            transaction_id,
            "--confirmation-token",
            token,
        ],
        env=env,
        state_dir=state_dir,
    )
    executed = invoke(
        ["execute", transaction_id],
        env=env,
        state_dir=state_dir,
    )
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return invoke(
        ["verify", transaction_id],
        env=env,
        state_dir=state_dir,
    )


def _preview_runtime_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
    target_id: str | None = None,
) -> dict[str, object]:
    started = _call(
        ["draft-start", operation],
        env=env,
        state_dir=state_dir,
    )
    draft = started["draft"]
    assert isinstance(draft, dict)
    draft_id = str(draft["draft_id"])
    authority = str(started["task_authority"])
    current = draft
    arguments = list(declaration_args)
    if target_id is not None:
        bound = _call(
            [
                "draft-bind-object",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(current["revision"]),
                "--role",
                "target",
                "--object-id",
                target_id,
            ],
            env=env,
            state_dir=state_dir,
        )
        current = bound["draft"]
        bound_object = bound["bound_object"]
        assert isinstance(current, dict)
        assert isinstance(bound_object, dict)
        arguments = ["--target-handle", str(bound_object["handle"]), *arguments]
    declared = _call(
        [
            "draft-declare-runtime-control-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
            *arguments,
        ],
        env=env,
        state_dir=state_dir,
    )
    current = declared["draft"]
    assert isinstance(current, dict)
    checked = _call(
        [
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )
    current = checked["draft"]
    assert isinstance(current, dict)
    return _call(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )


def _preview_soundengine_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
    role_bindings: tuple[tuple[str, str], ...] = (),
) -> dict[str, object]:
    started = _call(
        ["draft-start", operation],
        env=env,
        state_dir=state_dir,
    )
    draft = started["draft"]
    assert isinstance(draft, dict)
    draft_id = str(draft["draft_id"])
    authority = str(started["task_authority"])
    current = draft
    bound_handles: dict[str, str] = {}
    for role, object_id in role_bindings:
        bound = _call(
            [
                "draft-bind-object",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(current["revision"]),
                "--role",
                role,
                "--object-id",
                object_id,
            ],
            env=env,
            state_dir=state_dir,
        )
        current = bound["draft"]
        assert isinstance(current, dict)
        bound_object = bound["bound_object"]
        assert isinstance(bound_object, dict)
        bound_handles[role] = str(bound_object["handle"])
    declaration_args = [
        bound_handles[value.removeprefix("<bound:").removesuffix(">")]
        if value.startswith("<bound:") and value.endswith(">")
        else value
        for value in declaration_args
    ]
    declared = _call(
        [
            "draft-declare-soundengine-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
            *declaration_args,
        ],
        env=env,
        state_dir=state_dir,
    )
    current = declared["draft"]
    assert isinstance(current, dict)
    checked = _call(
        [
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )
    current = checked["draft"]
    assert isinstance(current, dict)
    return _call(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )


def _preview_zero_input_plan(
    operation: str,
    *,
    env: dict[str, str],
    state_dir: Path,
) -> dict[str, object]:
    schema = _call(
        ["request-schema", operation],
        env=env,
        state_dir=state_dir,
    )
    assert schema["input_shape"] == "zero"
    continuation = schema["continuation"]
    assert isinstance(continuation, dict)
    assert continuation["subcommand"] == "typed-zero-call"
    gateway_argv = continuation["gateway_argv"]
    assert isinstance(gateway_argv, list)
    assert all(isinstance(value, str) for value in gateway_argv)
    return _call(
        list(gateway_argv),
        env=env,
        state_dir=state_dir,
    )


def _runtime_business_result(verified: Mapping[str, object]) -> Mapping[str, object]:
    agent_result = verified.get("agent_result")
    assert isinstance(agent_result, Mapping), verified
    business_result = agent_result.get("business_result")
    assert isinstance(business_result, Mapping), agent_result
    return business_result


@pytest.mark.live
@pytest.mark.destructive
def test_host_ui_debug_project_close_and_open_transition(
    tmp_path: Path,
) -> None:
    """Close and reopen the exact private Authoring sandbox through host plans."""

    version = os.environ["WWISE_VERSION"]
    if version != "2022.1":
        pytest.skip("representative UI project open/close proof uses Wwise 2022.1")
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "host-ui-debug-project-state"
    project_file = Path(env["WWISE_AUTHORING_SANDBOX_PROJECT"]).resolve(
        strict=True
    )

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    assert Path(localize_waapi_host_path(project["path"])).resolve(
        strict=True
    ) == project_file

    saved = _preview_business_plan(
        "ui.commands.execute",
        ["--command-id", "SaveProject"],
        env=env,
        state_dir=state_dir,
    )
    _execute_and_verify(saved, env=env, state_dir=state_dir)

    project_may_be_closed = False
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None

    def open_exact_project(*, discard_current: bool) -> dict[str, object]:
        preview = _preview_host_plan(
            "ak.wwise.ui.project.open",
            [
                "--value", "project_file", str(project_file),
                "--toggle", "discard_unsaved_current_project",
                "enable" if discard_current else "disable",
                "--value", "upgrade_policy", "fail",
            ],
            env=env,
            state_dir=state_dir,
        )
        return _execute_and_verify(preview, env=env, state_dir=state_dir)

    try:
        close_preview = _preview_host_plan(
            "ak.wwise.ui.project.close",
            ["--toggle", "discard_unsaved_changes", "disable"],
            env=env,
            state_dir=state_dir,
        )
        project_may_be_closed = True
        closed = _execute_and_verify(
            close_preview,
            env=env,
            state_dir=state_dir,
        )
        assert closed["state"] == TransactionState.VERIFIED.value
        assert closed["verification"]["business_state_verified"] is True
        assert closed["guard_validation"]["project_transition"]["matched"] is True

        opened = open_exact_project(discard_current=False)
        assert opened["state"] == TransactionState.VERIFIED.value
        assert opened["verification"]["business_state_verified"] is True
        assert opened["guard_validation"]["project_transition"]["matched"] is True
        project_may_be_closed = False

        reopened_status = _call(["status"], env=env, state_dir=state_dir)
        reopened_project = reopened_status["project"]
        assert isinstance(reopened_project, dict)
        assert Path(localize_waapi_host_path(reopened_project["path"])).resolve(
            strict=True
        ) == project_file
    except BaseException as exc:
        primary_error = exc
    finally:
        if project_may_be_closed:
            try:
                cleanup = open_exact_project(discard_current=True)
                assert cleanup["state"] == TransactionState.VERIFIED.value
            except BaseException as exc:
                cleanup_error = exc
    if primary_error is not None and cleanup_error is not None:
        raise BaseExceptionGroup(
            "UI project transition failed and exact-project recovery failed",
            [primary_error, cleanup_error],
        )
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error


@pytest.mark.live
@pytest.mark.destructive
def test_authoring_ui_business_capture_execute_register_unregister(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version in {"2022.1", "2025.1"}
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "authoring-ui-state"
    key = f"live-notification-{uuid.uuid4().hex}"

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    observed_project = Path(
        localize_waapi_host_path(project["path"])
    ).resolve(strict=True)
    expected_project = Path(
        env["WWISE_AUTHORING_SANDBOX_PROJECT"]
    ).resolve(strict=True)
    assert observed_project == expected_project

    schema_code, schema = gateway.execute_gateway(
        ["operation-schema", "ui.commands.register"],
        env=env,
    )
    assert schema_code == 0, schema
    assert schema["operation"]["input_mode"] == "business_declaration"
    assert "typed_operation" not in schema
    assert "composer" not in schema

    capture = _preview_business_plan(
        "ui.captureScreen",
        [],
        env=env,
        state_dir=state_dir,
    )
    capture_verified = _execute_and_verify(
        capture,
        env=env,
        state_dir=state_dir,
    )
    assert capture_verified["state"] == (
        TransactionState.RESULT_SCHEMA_CHECKED.value
    )

    command = _preview_business_plan(
        "ui.commands.execute",
        ["--command-id", "SaveProject"],
        env=env,
        state_dir=state_dir,
    )
    command_verified = _execute_and_verify(
        command,
        env=env,
        state_dir=state_dir,
    )
    assert command_verified["state"] == (
        TransactionState.RESULT_SCHEMA_CHECKED.value
    )

    registration = _preview_business_plan(
        "ui.commands.register",
        ["--command-count", "1"],
        env=env,
        state_dir=state_dir,
        registration_key=key,
    )
    registration_may_exist = False
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        # Own cleanup before dispatch: a failed/ambiguous verification may follow
        # a successful non-retried registration call.
        registration_may_exist = True
        registration_verified = _execute_and_verify(
            registration,
            env=env,
            state_dir=state_dir,
        )
        assert registration_verified["state"] == TransactionState.VERIFIED.value
        unregister = _preview_business_plan(
            "ui.commands.unregister",
            ["--registered-command-key", key],
            env=env,
            state_dir=state_dir,
        )
        unregister_verified = _execute_and_verify(
            unregister,
            env=env,
            state_dir=state_dir,
        )
        assert unregister_verified["state"] == TransactionState.VERIFIED.value
        registration_may_exist = False
    except BaseException as exc:  # preserve interruption/failure through cleanup
        primary_error = exc
    finally:
        if registration_may_exist:
            try:
                cleanup = _preview_business_plan(
                    "ui.commands.unregister",
                    ["--registered-command-key", key],
                    env=env,
                    state_dir=state_dir,
                )
                cleanup_verified = _execute_and_verify(
                    cleanup,
                    env=env,
                    state_dir=state_dir,
                )
                assert cleanup_verified["state"] == TransactionState.VERIFIED.value
            except BaseException as exc:
                cleanup_error = exc
    if primary_error is not None and cleanup_error is not None:
        raise BaseExceptionGroup(
            "Authoring UI registration failed and bounded cleanup also failed",
            [primary_error, cleanup_error],
        )
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_business_profiler_and_transport_lifecycle_on_authoring(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version in {"2022.1", "2025.1"}
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "runtime-authoring-state"

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    observed_project = Path(
        localize_waapi_host_path(project["path"])
    ).resolve(strict=True)
    expected_project = Path(
        env["WWISE_AUTHORING_SANDBOX_PROJECT"]
    ).resolve(strict=True)
    assert observed_project == expected_project

    event_id = "{1AF4A3BA-682A-4664-AC31-45C0F0E6F8D1}"
    event = _call(
        ["query-object", "--exact-id", event_id],
        env=env,
        state_dir=state_dir,
    )
    assert event["count"] == 1
    rows = event["objects"]
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["type"] == "Event"

    profiler_enabled = False
    transport_handle: str | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    try:
        profiler = _preview_runtime_plan(
            "ak.wwise.core.profiler.enableProfilerData",
            ["--capture-data", "voices", "enable"],
            env=env,
            state_dir=state_dir,
        )
        # Cleanup ownership begins before execute: the call can succeed even if
        # its weak result-schema verification later fails.
        profiler_enabled = True
        profiler_verified = _execute_and_verify(
            profiler,
            env=env,
            state_dir=state_dir,
        )
        assert profiler_verified["state"] == (
            TransactionState.RESULT_SCHEMA_CHECKED.value
        )
        created = _preview_runtime_plan(
            "ak.wwise.core.transport.create",
            [],
            env=env,
            state_dir=state_dir,
            target_id=event_id,
        )
        created_verified = _execute_and_verify(
            created,
            env=env,
            state_dir=state_dir,
        )
        assert created_verified["state"] == TransactionState.VERIFIED.value
        create_result = _runtime_business_result(created_verified)
        transport_handle = str(create_result["transport_handle"])

        state = _call(
            [
                "core-call",
                "ak.wwise.core.transport.getState",
                "--transport-handle",
                transport_handle,
            ],
            env=env,
            state_dir=state_dir,
        )
        assert state["agent_result"]["transport_handle"] == transport_handle
        assert state["agent_result"]["state"] in {"playing", "paused", "stopped"}

        stopped = _preview_runtime_plan(
            "ak.wwise.core.transport.executeAction",
            [
                "--audition-action",
                "stop",
                "--transport-scope",
                "one-transport",
                "--transport-handle",
                transport_handle,
            ],
            env=env,
            state_dir=state_dir,
        )
        stopped_verified = _execute_and_verify(
            stopped,
            env=env,
            state_dir=state_dir,
        )
        assert stopped_verified["state"] == TransactionState.VERIFIED.value
        stop_observation = stopped_verified["verification"]["verification_scope"]["observation"]
        assert stop_observation["membership_matches"] is True
        assert len(stop_observation["targets"]) == 1
        assert stop_observation["targets"][0]["observed_state"] == "stopped"
        assert stop_observation["targets"][0]["outcome"] == "matched"

        destroyed = _preview_runtime_plan(
            "ak.wwise.core.transport.destroy",
            ["--transport-handle", transport_handle],
            env=env,
            state_dir=state_dir,
        )
        destroyed_verified = _execute_and_verify(
            destroyed,
            env=env,
            state_dir=state_dir,
        )
        assert destroyed_verified["state"] == TransactionState.VERIFIED.value
        assert _runtime_business_result(destroyed_verified)[
            "retired_transport_handle_count"
        ] == 1
        transport_handle = None
    except BaseException as exc:
        primary_error = exc
    finally:
        if transport_handle is not None:
            try:
                cleanup = _preview_runtime_plan(
                    "ak.wwise.core.transport.destroy",
                    ["--transport-handle", transport_handle],
                    env=env,
                    state_dir=state_dir,
                )
                _execute_and_verify(cleanup, env=env, state_dir=state_dir)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if profiler_enabled:
            try:
                cleanup = _preview_runtime_plan(
                    "ak.wwise.core.profiler.enableProfilerData",
                    ["--capture-data", "voices", "disable"],
                    env=env,
                    state_dir=state_dir,
                )
                _execute_and_verify(cleanup, env=env, state_dir=state_dir)
            except BaseException as exc:
                cleanup_errors.append(exc)
    if primary_error is not None or cleanup_errors:
        raise BaseExceptionGroup(
            "Authoring runtime lifecycle or bounded cleanup failed",
            [*([primary_error] if primary_error is not None else []), *cleanup_errors],
        )


@pytest.mark.live
@pytest.mark.destructive
def test_soundengine_business_runtime_and_spatial_families_on_authoring(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version in {"2022.1", "2025.1"}
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "soundengine-authoring-state"

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    assert Path(localize_waapi_host_path(project["path"])).resolve(
        strict=True
    ) == Path(env["WWISE_AUTHORING_SANDBOX_PROJECT"]).resolve(strict=True)

    handles: list[str] = []
    playing_handle: str | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []

    def complete(
        operation: str,
        declaration: list[str],
        *,
        role_bindings: tuple[tuple[str, str], ...] = (),
    ) -> dict[str, object]:
        return _execute_and_verify(
            _preview_soundengine_plan(
                operation,
                declaration,
                env=env,
                state_dir=state_dir,
                role_bindings=role_bindings,
            ),
            env=env,
            state_dir=state_dir,
        )

    try:
        monitor = complete(
            "ak.soundengine.postMsgMonitor",
            ["--monitor-message", f"waapi-skill authoring probe {version}"],
        )
        assert monitor["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value

        for name in ("WAAPI Skill Emitter", "WAAPI Skill Listener"):
            registered = complete(
                "ak.soundengine.registerGameObj",
                ["--game-object-name", name],
            )
            business = _runtime_business_result(registered)
            handle = str(business["game_object_handle"])
            assert handle.startswith("goh1-")
            handles.append(handle)
        emitter, listener = handles

        event_id = "{1AF4A3BA-682A-4664-AC31-45C0F0E6F8D1}"
        state_group_id = "{AF599241-DE64-4286-BB8B-B0260EE20B80}"
        state_id = "{43C6702F-3A30-4D5C-B16D-C862BE5989EF}"
        switch_group_id = "{9127B7FC-12D5-45F1-99E7-D9EC0CF8E8B1}"
        switch_id = "{E82D7064-8509-42A1-96E4-8E3AD2F878FA}"
        for object_id, object_type in (
            (event_id, "Event"),
            (state_group_id, "StateGroup"),
            (state_id, "State"),
            (switch_group_id, "SwitchGroup"),
            (switch_id, "Switch"),
        ):
            resolved = _call(
                ["query-object", "--exact-id", object_id],
                env=env,
                state_dir=state_dir,
            )
            rows = resolved["objects"]
            assert isinstance(rows, list) and len(rows) == 1
            assert rows[0]["type"] == object_type

        posted = complete(
            "ak.soundengine.postEvent",
            [
                "--event-handle", "<bound:event>",
                "--game-object-handle", emitter,
            ],
            role_bindings=(("event", event_id),),
        )
        posted_business = _runtime_business_result(posted)
        playing_handle = str(posted_business["playing_handle"])
        assert playing_handle.startswith("plh1-")
        seeked = complete(
            "ak.soundengine.seekOnEvent",
            [
                "--event-handle", "<bound:event>",
                "--playing-handle", playing_handle,
                "--position-percent", "25",
                "--nearest-marker",
            ],
            role_bindings=(("event", event_id),),
        )
        assert seeked["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
        stopped = complete(
            "ak.soundengine.stopPlayingID",
            ["--playing-handle", playing_handle],
        )
        retired_count = _runtime_business_result(stopped)[
            "retired_playing_handle_count"
        ]
        playing_handle = None
        assert retired_count == 1

        complete(
            "ak.soundengine.setState",
            [
                "--state-group-handle", "<bound:state_group>",
                "--state-handle", "<bound:state>",
            ],
            role_bindings=(
                ("state_group", state_group_id),
                ("state", state_id),
            ),
        )
        state = _call(
            [
                "core-call",
                "ak.soundengine.getState",
                "--state-group-id",
                state_group_id,
            ],
            env=env,
            state_dir=state_dir,
        )
        assert state["agent_result"] == {"id": state_id, "name": "a_Stealth"}

        complete(
            "ak.soundengine.setSwitch",
            [
                "--switch-group-handle", "<bound:switch_group>",
                "--switch-handle", "<bound:switch>",
                "--game-object-handle", emitter,
            ],
            role_bindings=(
                ("switch_group", switch_group_id),
                ("switch", switch_id),
            ),
        )
        switch = _call(
            [
                "core-call",
                "ak.soundengine.getSwitch",
                "--switch-group-id",
                switch_group_id,
                "--game-object-handle",
                emitter,
            ],
            env=env,
            state_dir=state_dir,
        )
        assert switch["agent_result"] == {"id": switch_id, "name": "Walking"}

        operations = (
            (
                "ak.soundengine.setPosition",
                [
                    "--game-object-handle", emitter,
                    "--position-frame", "1", "2", "3", "1", "0", "0", "0", "1", "0",
                ],
            ),
            (
                "ak.soundengine.setMultiplePositions",
                [
                    "--game-object-handle", emitter,
                    "--multi-position-mode", "MultiSources",
                    "--position-frame", "1", "2", "3", "1", "0", "0", "0", "1", "0",
                    "--position-frame", "4", "5", "6", "1", "0", "0", "0", "1", "0",
                ],
            ),
            (
                "ak.soundengine.setDefaultListeners",
                ["--listener-handle", listener],
            ),
            (
                "ak.soundengine.setListeners",
                ["--emitter-handle", emitter, "--listener-handle", listener],
            ),
            (
                "ak.soundengine.setObjectObstructionAndOcclusion",
                [
                    "--emitter-handle", emitter,
                    "--listener-handle", listener,
                    "--obstruction-percent", "25",
                    "--occlusion-percent", "50",
                ],
            ),
            (
                "ak.soundengine.setScalingFactor",
                ["--game-object-handle", emitter, "--attenuation-scale-percent", "150"],
            ),
            (
                "ak.soundengine.setGameObjectOutputBusVolume",
                [
                    "--emitter-handle", emitter,
                    "--listener-handle", listener,
                    "--volume-db", "-6",
                ],
            ),
            (
                "ak.soundengine.setListenerSpatialization",
                [
                    "--listener-handle", listener,
                    "--spatialization", "enabled",
                    "--channel-layout", "5.1",
                    "--speaker-offset-db", "C", "-3",
                ],
            ),
            (
                "ak.soundengine.stopAll",
                ["--game-object-handle", emitter],
            ),
        )
        for operation, declaration in operations:
            verified = complete(operation, declaration)
            assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    except BaseException as exc:
        primary_error = exc
    finally:
        if playing_handle is not None:
            try:
                stopped = complete(
                    "ak.soundengine.stopPlayingID",
                    ["--playing-handle", playing_handle],
                )
                assert _runtime_business_result(stopped)[
                    "retired_playing_handle_count"
                ] == 1
            except BaseException as exc:
                cleanup_errors.append(exc)
        for handle in reversed(handles):
            try:
                unregistered = complete(
                    "ak.soundengine.unregisterGameObj",
                    ["--game-object-handle", handle],
                )
                assert _runtime_business_result(unregistered)[
                    "retired_game_object_handle_count"
                ] == 1
            except BaseException as exc:
                cleanup_errors.append(exc)
    if primary_error is not None or cleanup_errors:
        raise BaseExceptionGroup(
            "SoundEngine Authoring workflow or bounded game-object cleanup failed",
            [*([primary_error] if primary_error is not None else []), *cleanup_errors],
        )


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_business_remote_connection_lifecycle_on_authoring(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version == "2022.1"
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "remote-authoring-state"

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    observed_project = Path(
        localize_waapi_host_path(project["path"])
    ).resolve(strict=True)
    expected_project = Path(
        env["WWISE_AUTHORING_SANDBOX_PROJECT"]
    ).resolve(strict=True)
    assert observed_project == expected_project

    remote_host = os.environ["WWISE_AUTHORING_REMOTE_HOST"]
    application_name = os.environ["WWISE_AUTHORING_REMOTE_APPLICATION_NAME"]
    command_port = int(os.environ["WWISE_AUTHORING_REMOTE_COMMAND_PORT"])
    assert remote_host.strip() == remote_host and remote_host
    assert application_name.strip() == application_name and application_name
    assert 1 <= command_port <= 65535

    remote_may_be_connected = False
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        connect = _preview_runtime_plan(
            "ak.wwise.core.remote.connect",
            [
                "--remote-host",
                remote_host,
                "--application-name",
                application_name,
                "--command-port",
                str(command_port),
            ],
            env=env,
            state_dir=state_dir,
        )
        # Own cleanup before dispatch: connect can take effect even when its
        # non-retried response or later verification is ambiguous.
        remote_may_be_connected = True
        connected = _execute_and_verify(
            connect,
            env=env,
            state_dir=state_dir,
        )
        assert connected["state"] == TransactionState.VERIFIED.value

        disconnect = _preview_zero_input_plan(
            "ak.wwise.core.remote.disconnect",
            env=env,
            state_dir=state_dir,
        )
        disconnected = _execute_and_verify(
            disconnect,
            env=env,
            state_dir=state_dir,
        )
        assert disconnected["state"] == TransactionState.VERIFIED.value
        remote_may_be_connected = False
    except BaseException as exc:
        primary_error = exc
    finally:
        if remote_may_be_connected:
            try:
                cleanup = _preview_zero_input_plan(
                    "ak.wwise.core.remote.disconnect",
                    env=env,
                    state_dir=state_dir,
                )
                cleanup_verified = _execute_and_verify(
                    cleanup,
                    env=env,
                    state_dir=state_dir,
                )
                assert cleanup_verified["state"] == TransactionState.VERIFIED.value
            except BaseException as exc:
                cleanup_error = exc
    if primary_error is not None and cleanup_error is not None:
        raise BaseExceptionGroup(
            "Authoring Remote lifecycle failed and bounded disconnect also failed",
            [primary_error, cleanup_error],
        )
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error

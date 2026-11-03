"""Representative owned layout witnesses; all host calls use the public Gateway."""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.authoring_layout import layout_identity_rows
from wwise_waapi.authoring_layout_business import layout_view_identities, require_layout_rectangle
from wwise_waapi.layout_blueprint import PLACEMENT_FIELDS

URI = 'ak.wwise.ui.layout.'
COMMON_NODE = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_layout_2024_construction_arrangement'
CLOSE_NODE = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_layout_2025_construction_close_reset'
NODES = {COMMON_NODE: '2024.1', CLOSE_NODE: '2025.1'}
CONTRACT = 'waapi-skill.owned-layout-cohort/v1'
FILENAME = 'layout-workflow-observations.json'


def construction_blueprint():
    placement = {'flags': '0', 'minimum_x': '-1', 'minimum_y': '-1', 'maximum_x': '0', 'maximum_y': '0',
        'left': '100', 'top': '120', 'right': '500', 'bottom': '420', 'state': 'normal'}
    return {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 'main', 'nodes': [
        {'key': 'main', 'kind': 'stack', 'label': 'Owned workspace', 'orientation': 'horizontal',
            'children': ['explorer', 'editor', 'tabs']},
        {'key': 'explorer', 'kind': 'view', 'view_type': 'ProjectExplorer', 'selection_channel': '1',
            'width': '300', 'height': '400', 'data_entries': []},
        {'key': 'editor', 'kind': 'object_panel', 'label': 'ObjectPanel', 'bottom_editor_state': 'normal',
            'editor_priority': [{'view_identifier': 'AttenuationEditor', 'plugin_identifier': '4294967295',
                'effect_index': '0', 'include_type': True}]},
        {'key': 'tabs', 'kind': 'object_tabs', 'label': 'ObjectTabPanel'},
        {'key': 'floating', 'kind': 'stack', 'label': 'Floating', 'orientation': 'vertical', 'children': ['transport']},
        {'key': 'transport', 'kind': 'view', 'view_type': 'Transport', 'selection_channel': '1'}],
        'floating_windows': [{'root': 'floating',
            'placement': {**placement, 'maximum_x': '-1', 'maximum_y': '-1'}}],
        'position_history': {'last_positions': [{'view_name': 'Transport', 'placement': placement}]}}


def _snapshot(call, name):
    document = call(['layout-read', 'contents', '--layout-name', name])['result']
    instances = call(['layout-read', 'instances', '--layout-name', name])['result']
    return {'workspace_name': document['Layout']['Name'], 'views': layout_view_identities(instances['viewInstances']),
        'document_sha256': canonical_sha256(document)}


def _unchanged(call, baseline):
    for name, before in baseline.items():
        after = _snapshot(call, name)
        # No cohort operation targets these layouts. Compare their complete
        # canonical serialization: topology/order, preferences, data and stored
        # placement are meaningful state; no source-proven volatile exception
        # is discarded. JSON object-key order alone is immaterial.
        assert after == before, 'Unrelated layout contents or canonical view identities/types changed'


def _view(inspected, name):
    rows = [row for row in inspected['views'] if row['kind'] == name]
    assert len(rows) == 1, 'Owned fixture requires one exact instantiated ' + name
    return rows[0]


def _view_id(call, layout_name, view_name):
    rows = [row for row in _snapshot(call, layout_name)['views'] if row['view_type'] == view_name]
    assert len(rows) == 1, 'Owned fixture requires one exact canonical ' + view_name
    return rows[0]['view_id']


def _selected_reset_observation(call, inspected, *, name, report):
    """One selected-owned-name observation; never a default-state business verifier."""
    assert name == report['owned_layout_name'] and name.startswith('WAAPI_Skill_Owned_')
    observation = report['reset'] = {'scope': 'selected_layouts', 'selected_layout_name': name,
        'business_state_verified': False, 'post_reset_layout_survived': None,
        'default_state_oracle': 'not established', 'before': _snapshot(call, name)}
    schema = call(['request-schema', URI + 'resetLayouts'])
    started = call(schema['continuation']['gateway_argv'])
    draft, authority = started['draft'], started['task_authority']
    declared = call(['draft-declare-layout-plan', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(draft['revision']), '--layout-handle', inspected['layout_handle'],
        '--reset-scope', 'selected_layouts', '--reset-layout-handle', inspected['layout_handle']])
    checked = call(['draft-check', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision'])])
    preview = call(['preview-from-draft', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])])
    tx = observation['transaction_id'] = preview['transaction_id']
    shown = call(['transaction-show', tx])
    call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
    call(['execute', tx])
    verified = call(['verify', tx])
    assert verified['verified'] is False and verified['verification']['business_state_verified'] is False
    assert verified['verification']['status'] == 'result_schema_checked'
    assert verified['verification']['verification_strength'] == 'result_schema_only'
    observation.update(verification_strength='result_schema_only', status='result_schema_checked')
    # A failed or missing-name read stops the cohort. Never guess survival and
    # blindly remove a resource after a reset, or continue after uncertainty.
    observation['after'] = _snapshot(call, name)
    call(['layout-inspect', '--layout-name', name])
    observation['post_reset_layout_survived'] = True


def collect_layout_workflow(batch, call, *, nodeid, strong_effect):
    assert nodeid in NODES and batch.runtime.version == NODES[nodeid]
    report = {'contract': CONTRACT, 'nodeid': nodeid, 'version': batch.runtime.version, 'candidate': batch.candidate,
        'complete': False, 'effects': [], 'reset': None, 'cleanup': {},
        'preservation_scope': 'complete canonical original/sentinel layout contents and canonical view identities/types; other private/global settings not certified'}
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR']) / FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        original = call(['layout-read', 'current'])['result']['name']
        assert original, 'A named current layout is required for explicit restoration'
        names = call(['layout-read', 'names'])['result']['layouts']
        sentinel = next((name for name in names if name != original), None)
        assert sentinel is not None, 'A separate private-profile preservation sentinel is required'
        baseline = {name: _snapshot(call, name) for name in (original, sentinel)}
        types = {row['viewName'] for row in call(['layout-read', 'types'])['result']['viewTypes']}
        assert {'ProjectExplorer', 'Transport', 'EventViewer'} <= types, 'Required owned view types are unavailable'
        name = 'WAAPI_Skill_Owned_' + uuid.uuid4().hex
        assert name not in names
        report.update(owned_layout_name=name, original_layout_name=original, baseline=baseline)
        def effect(suffix, handle, fields=()):
            observed = strong_effect(call, suffix, layout_handle=handle, fields=fields)
            report['effects'].append({'operation': URI + suffix, 'transaction_id': observed['transaction_id'],
                'business_state_verified': observed['verification']['business_state_verified']})
            _unchanged(call, baseline)
            return observed
        def inspect(): return call(['layout-inspect', '--layout-name', name])
        anchor = call(['layout-inspect', '--layout-name', original])
        blueprint = construction_blueprint()
        effect('setLayout', anchor['layout_handle'], ['--new-layout-name', name, '--blueprint', json.dumps(blueprint)])
        report['registered'] = _snapshot(call, name)
        effect('switchLayout', inspect()['layout_handle'])
        assert call(['layout-read', 'current'])['result']['name'] == name
        owned = inspect()
        explorer, transport = _view(owned, 'ProjectExplorer'), _view(owned, 'Transport')
        # Observe activation before another operation can change floating state.
        # WindowPlacement describes the holder's normal WINDOW coordinates;
        # getElementRectangle describes the allocated ELEMENT. No source proves
        # frame/content offsets, so these independent observations stay separate.
        document = call(['layout-read', 'contents', '--layout-name', name])['result']
        instances = call(['layout-read', 'instances', '--layout-name', name])['result']['viewInstances']
        floating = [row for row in instances if row.get('viewName') == 'Transport']
        assert len(floating) == 1 and floating[0].get('viewIsDocked') is False, 'Activated Transport is not independently floating'
        elements, _ = layout_identity_rows(document, {'viewInstances': instances})
        observed = [row for row in elements if row['native_id'].upper() == floating[0]['viewID'].upper()]
        assert len(observed) == 1 and observed[0]['location'].startswith('/Layout/Undocked/0/StackPanel/'), 'Activated Transport is outside its owned floating holder'
        windows = document['Layout'].get('Undocked', [])
        assert len(windows) == 1, 'Activated layout lacks its one declared floating holder'
        placement = blueprint['floating_windows'][0]['placement']
        expected = {native: placement[field] for field, native in PLACEMENT_FIELDS.items()}
        expected['WindowPlacement_ShowCmd'] = 'Normal'
        actual = {field: windows[0].get(field) for field in expected}
        report['activated_floating'] = {'view_id': floating[0]['viewID'], 'view_is_docked': False,
            'expected_holder_placement': expected, 'observed_holder_placement': actual,
            'placement_scope': 'same native WindowPlacement fields after activation; no frame/element conversion'}
        assert actual == expected, 'Activated floating holder placement differs from its declaration'
        allocated = [row for row in owned['elements'] if row['location'] == observed[0]['location']]
        assert len(allocated) == 1
        rectangle = require_layout_rectangle(call(['layout-read', 'rectangle', '--element-handle', allocated[0]['handle']])['result'])
        report['activated_floating'].update(element_rectangle=rectangle, element_scope='positive live allocation only')
        # Layout operations use the discovered view/element identities, not a
        # frontend GUID. getViewHandle remains a separate unfinished API under #188.
        effect('getOrCreateView', owned['layout_handle'], ['--view-type', 'EventViewer', '--initial-x', '17', '--initial-y', '29'])
        event_id = _view_id(call, name, 'EventViewer')
        if nodeid == COMMON_NODE:
            effect('getOrCreateView', inspect()['layout_handle'], ['--view-type', 'EventViewer'])
            assert _view_id(call, name, 'EventViewer') == event_id, 'Get-or-create did not reuse the same owned identity'
        owned = inspect()
        target = [row for row in owned['elements'] if row['kind'] == 'View' and row.get('name') == 'ProjectExplorer']
        assert len(target) == 1
        rectangle = call(['layout-read', 'rectangle', '--element-handle', target[0]['handle']])['result']
        assert rectangle['right'] > rectangle['left'] and rectangle['bottom'] > rectangle['top'], 'Dock target has no positive allocation'
        effect('dockView', owned['layout_handle'], ['--view-handle', _view(owned, 'Transport')['handle'],
            '--target-element-handle', target[0]['handle'], '--dock-side', 'right'])
        if nodeid == COMMON_NODE:
            owned = inspect()
            splitters = sorted((row for row in owned['elements'] if row['kind'] == 'Splitter'), key=lambda row: row['location'])
            selected = None
            for splitter in splitters[:16]:
                rectangle = call(['layout-read', 'rectangle', '--element-handle', splitter['handle']])['result']
                if (all(edge in rectangle for edge in ('left', 'top', 'right', 'bottom'))
                        and rectangle['right'] > rectangle['left'] and rectangle['bottom'] > rectangle['top']):
                    selected = splitter
                    break
            assert selected is not None, 'No positive allocated owned splitter was found in the bounded discovery'
            report['selected_splitter_location'] = selected['location']
            effect('moveSplitter', owned['layout_handle'], ['--splitter-handle', selected['handle'], '--pixel-delta', '5'])
            owned = inspect()
            before_undock = _snapshot(call, name)['views']
            effect('undockView', owned['layout_handle'], ['--view-handle', _view(owned, 'Transport')['handle'], '--position-x', '260', '--position-y', '180'])
            after_undock = _snapshot(call, name)['views']
            report['undock_views'] = {'before': before_undock, 'after': after_undock}
            assert after_undock == before_undock, 'Undocking changed other owned view identities/types'
        else:
            owned = inspect()
            effect('closeView', owned['layout_handle'], ['--view-handle', _view(owned, 'EventViewer')['handle']])
            assert all(row['view_id'] != event_id for row in _snapshot(call, name)['views']), 'Closed owned view remains present'
            _selected_reset_observation(call, inspect(), name=name, report=report)
            _unchanged(call, baseline)
        restore = call(['layout-inspect', '--layout-name', original])
        effect('switchLayout', restore['layout_handle'])
        assert call(['layout-read', 'current'])['result']['name'] == original
        report['cleanup']['original_current_restored'] = True
        effect('removeLayout', inspect()['layout_handle'])
        report['cleanup']['owned_layout_removed'] = True
        report['complete'] = True
    finally:
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        assert len(raw) <= 65536, 'Owned layout summary exceeded its fixed bound'
        with destination.open('xb') as stream: stream.write(raw)


def validate_layout_report(report, *, nodeid, candidate, version, receipts):
    """Final publication consumes the existing archived public verification receipts."""
    if (not isinstance(report, dict) or report.get('contract') != CONTRACT or report.get('nodeid') != nodeid
            or report.get('candidate') != candidate or report.get('version') != version or NODES.get(nodeid) != version
            or report.get('complete') is not True
            or report.get('cleanup') != {'original_current_restored': True, 'owned_layout_removed': True}
            or not str(report.get('owned_layout_name', '')).startswith('WAAPI_Skill_Owned_')):
        raise ValueError('Owned layout cohort report lacks its exact completed ownership context')
    expected = (['setLayout', 'switchLayout', 'getOrCreateView', 'getOrCreateView', 'dockView', 'moveSplitter', 'undockView', 'switchLayout', 'removeLayout']
        if nodeid == COMMON_NODE else ['setLayout', 'switchLayout', 'getOrCreateView', 'dockView', 'closeView', 'switchLayout', 'removeLayout'])
    effects = report.get('effects', [])
    verified = {row['payload']['transaction_id']: row['payload'] for row in receipts
        if row.get('argv', [None])[0] == 'verify' and row.get('exit_code') == 0 and isinstance(row.get('payload'), dict)}
    if ([row.get('operation') for row in effects] != [URI + suffix for suffix in expected]
            or len({row.get('transaction_id') for row in effects}) != len(expected)
            or any(row.get('business_state_verified') is not True
                or verified.get(row.get('transaction_id'), {}).get('verification', {}).get('business_state_verified') is not True for row in effects)):
        raise ValueError('Owned layout effects differ from their exact independent strong public verifications')
    reset = report.get('reset')
    if nodeid == CLOSE_NODE:
        observed = verified.get(reset.get('transaction_id'), {}) if isinstance(reset, dict) else {}
        if (not isinstance(reset, dict) or reset.get('scope') != 'selected_layouts'
                or reset.get('selected_layout_name') != report['owned_layout_name']
                or reset.get('business_state_verified') is not False or reset.get('post_reset_layout_survived') is not True
                or reset.get('transaction_id') in {row['transaction_id'] for row in effects}
                or observed.get('verified') is not False or observed.get('verification', {}).get('business_state_verified') is not False
                or observed.get('verification', {}).get('verification_strength') != 'result_schema_only'):
            raise ValueError('Selected-owned reset observation cannot become business acceptance')
    elif reset is not None:
        raise ValueError('The 2024 cohort cannot acquire a reset observation')
    return report

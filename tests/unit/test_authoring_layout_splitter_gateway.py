"""Splitter movement is a scoped business outcome, tested through the Gateway."""
from pathlib import Path
from copy import deepcopy
import pytest

from tests.unit.test_authoring_layout_mutation_gateway import (
    URI, NODE, switch_preview, confirm_execute_verify, gateway,
)
from wwise_waapi.transactions import TransactionStore


def _seed_splitter(client, *, orientation='Horizontal', identity='{44444444-4444-4444-4444-444444444444}'):
    stack = client.layouts['Designer']['Layout']['StackPanel']
    stack['Orientation'] = orientation
    # Actual READ reflection returned this exact Splitter shape without Name/Children.
    stack['@Children'] = [{'@type': 'Splitter', 'ID': identity}]
    client.rectangles[identity] = ({'left': 250.5, 'top': 100.5, 'right': 256.5, 'bottom': 500.5}
        if orientation == 'Horizontal' else {'left': 100.5, 'top': 250.5, 'right': 400.5, 'bottom': 256.5})
    original = client.call
    def move(uri, args=None, options=None):
        if uri == URI + 'moveSplitter':
            client.calls.append((uri, args, options))
            rectangle = client.rectangles[args['id']]
            for edge in (('left', 'right') if orientation == 'Horizontal' else ('top', 'bottom')):
                rectangle[edge] += args['delta']
            return {}
        return original(uri, args, options)
    client.call = move


def _fields(inspected, delta):
    splitter = next(row for row in inspected['elements'] if row['kind'] == 'Splitter')
    return ('--splitter-handle', splitter['handle'], '--pixel-delta', str(delta))


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('orientation,identity,axis', [
    ('Horizontal', '{44444444-4444-4444-4444-444444444444}', 'x'),
    ('Vertical', 'Splitter A 雨', 'y')])
@pytest.mark.parametrize('delta', [-12, 0, 15])
def test_splitter_owns_native_id_and_axis_and_verifies_exact_signed_delta(tmp_path, version, orientation, identity, axis, delta):
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='moveSplitter', layout_name='Designer',
        fields=lambda inspected: _fields(inspected, delta),
        client_setup=lambda client: _seed_splitter(client, orientation=orientation, identity=identity))
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch'] == {'uri': URI + 'moveSplitter', 'args': {'id': identity, 'delta': delta}, 'options': {}}
    assert prepared['verification_plan']['axis'] == axis
    assert prepared['verification_plan']['rectangle_before'] == client.rectangles[identity]
    assert URI + 'moveSplitter' not in [row[0] for row in client.calls]
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert [row[0] for row in client.calls].count(URI + 'moveSplitter') == 1


@pytest.mark.parametrize('failure', ['clipped', 'no-effect', 'wrong-axis', 'resized', 'missing-element', 'changed-axis', 'current-layout', 'missing-rectangle'])
def test_splitter_incomplete_or_different_effect_is_not_certified_or_replayed(tmp_path, failure):
    identity = '{44444444-4444-4444-4444-444444444444}'
    env, state, client, preview = switch_preview(tmp_path, operation='moveSplitter', layout_name='Designer',
        fields=lambda inspected: _fields(inspected, 20), client_setup=_seed_splitter)
    before = deepcopy(client.rectangles[identity])
    original = client.call
    def wrong_effect(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'moveSplitter':
            rectangle = client.rectangles[identity]
            if failure == 'clipped':
                rectangle.update(left=260.5, right=266.5)
            elif failure == 'no-effect':
                rectangle.update(before)
            elif failure == 'wrong-axis':
                rectangle.update(left=250.5, right=256.5, top=120.5, bottom=520.5)
            elif failure == 'resized':
                rectangle['right'] = 256.5
            elif failure == 'missing-element':
                client.layouts['Designer']['Layout']['StackPanel']['@Children'] = []
            elif failure == 'changed-axis':
                client.layouts['Designer']['Layout']['StackPanel']['Orientation'] = 'Vertical'
            elif failure == 'current-layout':
                client.current = 'Profiler'
            else:
                del rectangle['right']
        return result
    client.call = wrong_effect
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    assert [row[0] for row in client.calls].count(URI + 'moveSplitter') == 1


def test_splitter_revalidates_fractional_rectangle_before_single_write(tmp_path):
    identity = '{44444444-4444-4444-4444-444444444444}'
    env, state, client, preview = switch_preview(tmp_path, operation='moveSplitter', layout_name='Designer',
        fields=lambda inspected: _fields(inspected, 20), client_setup=_seed_splitter)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, _ = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0
    client.rectangles[identity]['left'] = 250.75
    code, result = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, result
    assert URI + 'moveSplitter' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('context', ['unknown-axis', 'non-stack-parent', 'duplicate-location', 'wrong-kind'])
def test_splitter_requires_unique_typed_serialized_parent_before_write(tmp_path, context):
    def seed(client):
        _seed_splitter(client)
        stack = client.layouts['Designer']['Layout']['StackPanel']
        if context == 'unknown-axis':
            stack['Orientation'] = 'Diagonal'
        elif context == 'non-stack-parent':
            stack['@Children'] = [{'@type': 'ObjectPanel', 'ID': 'panel', '@Children': stack['@Children']}]
        elif context == 'duplicate-location':
            stack['@Children'].append(deepcopy(stack['@Children'][0]))
    switch_preview(tmp_path, operation='moveSplitter', layout_name='Designer',
        fields=lambda inspected: ('--splitter-handle', next(row['handle'] for row in inspected['elements']
            if row['kind'] == ('StackPanel' if context == 'wrong-kind' else 'Splitter')), '--pixel-delta', '20'),
        client_setup=seed, expect_check_error=True)

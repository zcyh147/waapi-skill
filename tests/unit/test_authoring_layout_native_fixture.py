"""Exercise future native fixture calls through the public Gateway with a fake host."""
from types import SimpleNamespace
import importlib

import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_authoring_layout_mutation_gateway import LayoutClient, URI
from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_layout_registration_switch_fixture_uses_separate_verified_transactions(tmp_path, monkeypatch, version):
    for key in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(key, '1')
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path, version=version)
    receipts = []
    def call(argv):
        code, payload = gateway.execute_gateway([*state, *argv], env=env, client_factory=lambda _: client)
        receipts.append((argv, code, payload))
        assert code == 0, payload
        return payload
    native.test_authoring_layout_owned_registration_and_switch(
        owned_authoring_layout_node=(SimpleNamespace(runtime=SimpleNamespace(version=version)), call))
    assert client.current == 'Designer'
    assert set(client.layouts) == {'Designer', 'Profiler'}
    executed = [row for row in client.calls if row[0] in {URI + name for name in ('setLayout', 'switchLayout', 'removeLayout')}]
    assert [row[0] for row in executed] == [URI + 'setLayout', URI + 'switchLayout', URI + 'switchLayout', URI + 'removeLayout']
    assert len({payload['transaction_id'] for argv, _, payload in receipts if argv[0] == 'preview-from-draft'}) == 4
    assert len([argv for argv, _, payload in receipts if argv[0] == 'verify' and payload['verification']['business_state_verified']]) == 4


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_view_fixture_proves_creation_reuse_and_applicable_close(tmp_path, monkeypatch, version):
    for key in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(key, '1')
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
    client = LayoutClient(tmp_path, version=version)
    def call(argv):
        code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *argv], env=env, client_factory=lambda _: client)
        assert code == 0, payload
        return payload
    native.test_authoring_layout_owned_view_lifecycle(
        owned_authoring_layout_node=(SimpleNamespace(runtime=SimpleNamespace(version=version)), call),
        initial_position=('--initial-x', '17', '--initial-y', '29'))
    assert client.current == 'Designer'
    assert set(client.layouts) == {'Designer', 'Profiler'}
    creates = [args for uri, args, _ in client.calls if uri == URI + 'getOrCreateView']
    assert creates == [{'name': 'ProjectExplorer', 'posX': 17, 'posY': 29}, {'name': 'ProjectExplorer'}]
    assert len([uri for uri, _, _ in client.calls if uri == URI + 'closeView']) == (1 if version == '2025.1' else 0)

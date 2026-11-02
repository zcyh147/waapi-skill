"""The existing collected-test owner installs the one private Demo context."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from tests.destructive.support import authoring_batch, integration_demo as demo
from tests.unit.test_integration_demo_observation import _installed
from tests.unit.test_authoring_batch_owner import _config, _fakes, NODE


def _configuration(tmp_path, monkeypatch):
    context = _installed(tmp_path)
    console = context.bundle / 'Contents/Tools/WwiseConsole.sh'
    console.parent.mkdir(parents=True, exist_ok=True)
    console.write_text('#!/bin/sh\n')
    console.chmod(0o755)
    project = context.bundle.parent / 'SDK/samples/IntegrationDemo/WwiseProject/IntegrationDemo.wproj'
    project.parent.mkdir(parents=True)
    project.write_text('<WwiseDocument/>')
    root = tmp_path / 'batch'
    path = tmp_path / 'demo-live-environment.json'
    selected = {'wwise_console': str(console), 'sample_project': str(project),
        'sandbox_root': str(root / 'owned/sandbox-root')}
    path.write_text(json.dumps({'versions': {'2025.1': selected}}))
    monkeypatch.setattr(demo, 'INSTALLED_BUNDLE', context.bundle, raising=False)
    monkeypatch.setattr(demo, 'INSTALLED_SCHEMAS', context.schemas, raising=False)
    monkeypatch.setenv('WWISE_TEST_CONFIG', str(path))
    for key, value in zip(('WWISE_CONSOLE', 'WWISE_SAMPLE_PROJECT_PATH', 'WWISE_SANDBOX_ROOT'), selected.values()):
        monkeypatch.setenv(key, value)
    return context, path, root


def test_existing_batch_factory_loads_named_demo_context_before_owner_start(tmp_path, monkeypatch):
    events = _fakes(monkeypatch, tmp_path)
    context, path, root = _configuration(tmp_path, monkeypatch)
    config = _config(tmp_path)
    config.args = [demo.NODEID]
    authoring_batch.configure_authoring_batch_owner(config, [SimpleNamespace(nodeid=demo.NODEID)], repo_root=tmp_path)
    assert [event[0] for event in events] == ['construct', 'start', 'install']
    options = events[0][1]
    assert options['developer_observation'] == context
    assert options['live_environment']['AK_AUTOMATION_MODE'] == '1'
    assert options['scenario_root'] == root
    assert options['live_environment']['WWISE_TEST_CONFIG'] == str(path)
    assert events[2][1]['selected_nodeids'] == (demo.NODEID,)


@pytest.mark.parametrize('failure', ['mixed', 'unknown', 'missing-config', 'wrong-source', 'schema-mismatch'])
def test_named_demo_invalid_selection_or_source_never_allocates_owner(tmp_path, monkeypatch, failure):
    events = _fakes(monkeypatch, tmp_path)
    context, path, root = _configuration(tmp_path, monkeypatch)
    config = _config(tmp_path)
    config.args = [demo.NODEID]
    if failure == 'mixed':
        config.args.append(NODE)
    elif failure == 'unknown':
        config.args.append('tests/destructive/unknown.py::test_unknown')
    elif failure == 'missing-config':
        monkeypatch.delenv('WWISE_TEST_CONFIG')
    elif failure == 'wrong-source':
        payload = json.loads(path.read_text())
        payload['versions']['2025.1']['sample_project'] = str(tmp_path / 'user.wproj')
        path.write_text(json.dumps(payload))
    else:
        (context.schemas / 'WAAPI/ak.wwise.core.profiler.getLoadedMedia.json').write_text('{}')
    with pytest.raises((ValueError, pytest.UsageError)):
        authoring_batch.configure_authoring_batch_owner(config,
            [SimpleNamespace(nodeid=node) for node in config.args], repo_root=tmp_path)
    assert not events and not root.exists()

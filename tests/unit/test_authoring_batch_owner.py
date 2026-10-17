"""Owner installation tests never call OS/native launch boundaries."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import authoring_batch

NODE = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_layout_owned_registration_and_switch'


def _config(tmp_path, **changes):
    options = dict(owned_authoring_batch_root=str(tmp_path / 'batch'), collectonly=False,
        setupplan=False, keyword='', markexpr='', deselect=[], numprocesses=None, forked=False)
    options.update(changes)
    return SimpleNamespace(getoption=lambda name, default=None: options.get(name, default), args=[NODE])


def _fakes(monkeypatch, tmp_path):
    events = []
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    monkeypatch.setenv('WWISE_AUTHORING_LIVE', '1')
    monkeypatch.setenv('WWISE_VERSION', '2025.1')
    monkeypatch.setattr(authoring_batch, 'candidate_source_context', lambda root: {'candidate': 'a' * 40, 'sources': {'x': 'b' * 64}})
    class Owner:
        def __init__(self, **kwargs):
            events.append(('construct', kwargs))
            self._finished = False
            self.kwargs = kwargs
        def start(self):
            events.append(('start', None))
            self.kwargs['prelaunch_hook'](None, None, None)
        def finish(self, status, **kwargs):
            events.append(('finish', status))
            self._finished = True
    monkeypatch.setattr(authoring_batch, 'ScenarioLifecycle', Owner)
    def install(config, **kwargs):
        events.append(('install', kwargs))
        config._waapi_authoring_batch = object()
        return config._waapi_authoring_batch
    monkeypatch.setattr(authoring_batch, 'install_authoring_batch', install)
    return events


def test_after_exact_collection_the_existing_lifecycle_owns_the_single_batch(monkeypatch, tmp_path):
    events = _fakes(monkeypatch, tmp_path)
    config = _config(tmp_path)
    result = authoring_batch.configure_authoring_batch_owner(config, [SimpleNamespace(nodeid=NODE)], repo_root=tmp_path)
    assert result is config._waapi_authoring_batch
    assert [row[0] for row in events] == ['construct', 'start', 'install']
    options = events[0][1]
    assert options['host_kind'] == 'wwise-authoring'
    assert options['version'] == '2025.1'
    assert options['scenario_root'] == tmp_path / 'batch'
    assert options['launch_environment_overrides'] == {'HOME': str(tmp_path / 'batch/owned/private-home')}
    assert events[2][1]['selected_nodeids'] == (NODE,)


@pytest.mark.parametrize('failure', ['other-node', 'changed-selection', 'empty', 'filter', 'parallel', 'existing-root', 'wrong-version', 'no-live', 'dirty-source'])
def test_collection_or_context_failure_never_constructs_or_starts_owner(monkeypatch, tmp_path, failure):
    events = _fakes(monkeypatch, tmp_path)
    config = _config(tmp_path)
    items = [SimpleNamespace(nodeid=NODE)]
    if failure == 'other-node':
        config.args = ['tests/unowned.py::test_any']
        items = [SimpleNamespace(nodeid=config.args[0])]
    elif failure == 'changed-selection':
        config.args = [NODE, NODE + '_extra']
    elif failure == 'empty':
        items = []
    elif failure == 'filter':
        config = _config(tmp_path, keyword='only-one')
    elif failure == 'parallel':
        config = _config(tmp_path, numprocesses=2)
    elif failure == 'existing-root':
        (tmp_path / 'batch').mkdir()
    elif failure == 'wrong-version':
        monkeypatch.setenv('WWISE_VERSION', '2023.1')
    elif failure == 'no-live':
        monkeypatch.delenv('WWISE_AUTHORING_LIVE')
    elif failure == 'dirty-source':
        def dirty(_root):
            raise ValueError('dirty frozen source')
        monkeypatch.setattr(authoring_batch, 'candidate_source_context', dirty)
    with pytest.raises((ValueError, pytest.UsageError)):
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
    assert events == []


def test_collect_only_never_allocates_an_owner_or_launches(monkeypatch, tmp_path):
    events = _fakes(monkeypatch, tmp_path)
    result = authoring_batch.configure_authoring_batch_owner(_config(tmp_path, collectonly=True),
        [SimpleNamespace(nodeid=NODE)], repo_root=tmp_path)
    assert result is None
    assert events == []


def test_install_failure_stops_the_owner_once_without_claiming_pass(monkeypatch, tmp_path):
    events = _fakes(monkeypatch, tmp_path)
    def fail(*_args, **_kwargs):
        raise ValueError('installation failed')
    monkeypatch.setattr(authoring_batch, 'install_authoring_batch', fail)
    with pytest.raises(ValueError, match='installation failed'):
        authoring_batch.configure_authoring_batch_owner(_config(tmp_path), [SimpleNamespace(nodeid=NODE)], repo_root=tmp_path)
    assert [row[0] for row in events] == ['construct', 'start', 'finish']
    assert events[-1] == ('finish', 'BLOCKED')


def test_existing_driver_passes_only_explicit_nodes_to_the_owned_pytest_batch(monkeypatch, tmp_path):
    from ci import test_driver
    captured = []
    monkeypatch.setattr(test_driver, 'run_live_test_command', lambda arguments, **kwargs: captured.append((arguments, kwargs)) or 0)
    root_option = '--owned-authoring-batch-root=' + str(tmp_path / 'batch')
    driver = test_driver.TestDriver(repo_root=tmp_path, environment={}, windows=False)
    assert driver.run(test_driver.parse_request(['--version', '2025.1', '--mode', 'destructive', '--', root_option, NODE, '-q'])) == 0
    arguments, options = captured[0]
    assert tuple(arguments[arguments.index('python') + 1:]) == ('-m', 'pytest', root_option, NODE, '-q')
    assert options['environment']['WWISE_AUTHORING_LIVE'] == '1'
    assert not any('project_mutation_sandbox' in arg for arg in arguments)


@pytest.mark.parametrize('version,mode', [('all', 'destructive'), ('2023.1', 'destructive'), ('none', 'nonlive'), ('2025.1', 'live')])
def test_existing_driver_rejects_owned_batch_in_other_lanes_before_dispatch(version, mode):
    from ci import test_driver
    with pytest.raises(test_driver.TestDriverError, match='owned Authoring'):
        test_driver.parse_request(['--version', version, '--mode', mode, '--', '--owned-authoring-batch-root=/private/tmp/example', NODE])


@pytest.mark.parametrize('collection_failure', ['none', 'syntax', 'late-hook'])
def test_actual_pytest_owner_hook_waits_for_clean_collection_before_tests(monkeypatch, tmp_path, collection_failure):
    from tests import conftest as root_conftest
    events = []
    class Probe:
        def pytest_runtest_setup(self, item):
            events.append(('setup', item.nodeid))
        @pytest.hookimpl(trylast=True)
        def pytest_collection_finish(self, session):
            if collection_failure == 'late-hook':
                raise pytest.UsageError('late collection hook rejected selection')
    monkeypatch.setattr(authoring_batch, 'configure_authoring_batch_owner',
        lambda config, items, **kwargs: events.append(('installed', tuple(item.nodeid for item in items))))
    case = tmp_path / f'test_fake_owned_collection_{collection_failure.replace("-", "_")}.py'
    case.write_text('def test_one():\n    assert True\n')
    ini = tmp_path / 'pytest.ini'
    ini.write_text('[pytest]\n')
    arguments = [str(case), '-c', str(ini), '--owned-authoring-batch-root=' + str(tmp_path / 'batch'), '-q']
    if collection_failure == 'syntax':
        broken = tmp_path / 'test_broken.py'
        broken.write_text('invalid Python syntax ???')
        arguments.insert(1, str(broken))
    code = pytest.main(arguments, plugins=[root_conftest, Probe()])
    if collection_failure != 'none':
        assert code != 0
        assert events == []
    else:
        assert code == 0
        assert [row[0] for row in events] == ['installed', 'setup']


def test_source_change_after_collection_blocks_before_adapter_installation(monkeypatch, tmp_path):
    events = _fakes(monkeypatch, tmp_path)
    contexts = iter([{'candidate': 'a' * 40, 'sources': {'x': 'b' * 64}},
                     {'candidate': 'a' * 40, 'sources': {'x': 'c' * 64}}])
    monkeypatch.setattr(authoring_batch, 'candidate_source_context', lambda root: next(contexts))
    with pytest.raises(ValueError, match='source candidate changed'):
        authoring_batch.configure_authoring_batch_owner(_config(tmp_path), [SimpleNamespace(nodeid=NODE)], repo_root=tmp_path)
    assert [row[0] for row in events] == ['construct', 'start']


def test_windows_owned_driver_has_an_explicit_unfinished_boundary_before_dispatch(monkeypatch, tmp_path):
    from ci import test_driver
    monkeypatch.setattr(test_driver, 'run_live_test_command', lambda *_a, **_kw: pytest.fail('No native Windows strategy'))
    driver = test_driver.TestDriver(repo_root=tmp_path, environment={}, windows=True)
    request = test_driver.parse_request(['--version', '2025.1', '--mode', 'destructive', '--',
        '--owned-authoring-batch-root=' + str(tmp_path / 'batch'), NODE])
    with pytest.raises(test_driver.TestDriverError, match='Mac'):
        driver.run(request)

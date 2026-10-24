"""Authoring startup uses the existing lifecycle; all OS processes are faked."""
from __future__ import annotations

from pathlib import Path
import plistlib
from types import SimpleNamespace
import pytest

from wwise_waapi.headless import HeadlessLifecycle, HeadlessLifecycleError


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n')
    path.chmod(0o755)
    return path


def _bundle(tmp_path, build='2025.1.7.9143'):
    folder = ('Wwise_' if build == '2025.1.11.9262' else 'Wwise ') + build
    bundle = tmp_path / folder / 'Wwise.app'
    console = _executable(bundle / 'Contents/Tools/WwiseConsole.sh')
    (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': build}))
    cx = bundle / 'Contents/SharedSupport/Wwise2019x64'
    for name in ('wine', 'wineprefixcreate', 'wineloader64', 'wineserver'):
        _executable(cx / 'bin' / name)
    # Matching installed2024/25 bundles ship winepath as a Windows program,
    # without a host bin/winepath executable.
    _executable(cx / 'lib/wine/x86_64-windows/winepath.exe')
    managed = cx / 'support/Wwise2019x64'
    managed.mkdir(parents=True)
    (managed / 'system.reg').write_text('managed registry')
    (managed / 'cxbottle.conf').write_text('[Bottle]\n"Updater" = "wineprefixcreate"\n')

    _executable(bundle / 'Contents/SharedSupport/Wwise/bin/wwise_prepare')
    installed = tmp_path / 'Library/Application Support/Audiokinetic' / ('Wwise ' + build)
    _executable(installed / 'Authoring/x64/Release/bin/Wwise.exe')
    owned = tmp_path / 'owned'
    project = owned / 'sandbox/Sandbox 雨 & quote.wproj'
    project.parent.mkdir(parents=True)
    project.write_text('<WwiseDocument/>')
    home = owned / 'private-home'
    home.mkdir()
    prefix = home / 'Library/Application Support/Wwise2019/Bottles/Wwise2019x64'
    return SimpleNamespace(bundle=bundle, console=console, cx=cx, installed=installed,
                           owned=owned, project=project, home=home, prefix=prefix, build=build)


@pytest.mark.parametrize('build', ['2021.1.14.8108', '2022.1.19.8584', '2023.1.19.8928', '2024.1.13.9056', '2025.1.7.9143', '2025.1.11.9262'])
@pytest.mark.parametrize('automation_requested', [False, True], ids=['normal', 'automation-requested'])
def test_existing_lifecycle_owns_mac_authoring_command_environment_and_project_proof(tmp_path, monkeypatch, build, automation_requested):
    from tests.unit.test_headless_lifecycle import FakeClient
    facts = _bundle(tmp_path, build=build)
    native_project = 'Z:\\Owned fixture\\Sandbox 雨 & quote.wproj'
    started, preparation = [], []
    process = SimpleNamespace(pid=1234, poll=lambda: None, stdout=None, stderr=None)
    def process_factory(command, **kwargs):
        # Source-shaped CrossOver selection: a private stub's Updater also
        # resolves the SAME logical bottle name against the managed directory.
        env = kwargs['env']
        bottle = env['CX_BOTTLE']
        assert '/' not in bottle and bottle == 'Wwise2019x64'
        private = Path(env['CX_BOTTLE_PATH']) / bottle
        managed = Path(env['CX_MANAGED_BOTTLE_PATH']) / bottle
        assert private.resolve() == facts.prefix and (private / 'system.reg').is_file()
        assert managed.resolve() == facts.cx / 'support/Wwise2019x64'
        assert (private / 'cxbottle.conf').resolve() == managed.resolve() / 'cxbottle.conf'
        assert env['WINEPREFIX'] == str(private)
        started.append((command, kwargs))
        return process
    lifecycle = HeadlessLifecycle(console_path=facts.console, project_path=facts.project, port=8080,
        host_kind='wwise-authoring', authoring_build=facts.build, authoring_owned_root=facts.owned,
        launch_env={'HOME': str(facts.home), 'WINEPREFIX': str(facts.prefix),
                    **({'AK_AUTOMATION_MODE': '1'} if automation_requested else {}),
                    'CX_ENV': 'WINEPREFIX=/unowned/bottle HOME=/unowned/home', 'WINE_WAIT_CHILD_PIPE': '15',
                    'AK_AUTHORING_ARGS_OVERRIDE': 'unowned.wproj'},
        launch_cwd_path=facts.project.parent, process_factory=process_factory,
        waapi_client_factory=lambda _: FakeClient([], result={'displayName': 'Wwise', 'isCommandLine': False, 'version':
            dict(zip(('year', 'major', 'minor', 'build'), map(int, build.split('.'))))}))
    from wwise_waapi import authoring_launch
    monkeypatch.setattr(authoring_launch.sys, 'platform', 'darwin')
    monkeypatch.setattr(authoring_launch, 'MACOS_AUTHORING_INSTALL_ROOT', facts.installed.parent)
    def run(command, **kwargs):
        preparation.append((command, kwargs))
        executable = Path(command[0]).name
        stdout = ''
        if executable == 'wineprefixcreate':
            facts.prefix.mkdir(parents=True)
            (facts.prefix / 'system.reg').write_text('owned registry')
            (facts.prefix / 'cxbottle.conf').symlink_to(facts.cx / 'support/Wwise2019x64/cxbottle.conf')
        elif executable == 'wwise_prepare':
            link = facts.prefix / 'drive_c/Program Files/Audiokinetic' / ('Wwise ' + facts.build)
            link.parent.mkdir(parents=True)
            link.symlink_to(facts.installed, target_is_directory=True)
        elif command[1:] == [str(facts.cx / 'lib/wine/x86_64-windows/winepath.exe'), '-w', str(facts.project)]:
            stdout = native_project + '\n'
        elif command[1:] == [str(facts.cx / 'lib/wine/x86_64-windows/winepath.exe'), '-u', native_project]:
            stdout = str(facts.project) + '\n'
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')
    monkeypatch.setattr(authoring_launch.subprocess, 'run', run)
    import wwise_waapi.headless as headless
    checked_ports = []
    monkeypatch.setattr(headless, 'assert_port_free', lambda host, port: checked_ports.append((host, port)))
    lifecycle.run_until_ready()
    assert checked_ports == [('127.0.0.1', 8080)]
    assert len(started) == 1
    command, options = started[0]
    native_executable = {
        '2021.1.14.8108': 'c:/Program Files/Audiokinetic/Wwise 2021.1.14.8108/Authoring/x64/Release/bin/Wwise.exe',
        '2022.1.19.8584': 'c:/Program Files/Audiokinetic/Wwise 2022.1.19.8584/Authoring/x64/Release/bin/Wwise.exe',
        '2023.1.19.8928': 'c:/Program Files/Audiokinetic/Wwise 2023.1.19.8928/Authoring/x64/Release/bin/Wwise.exe',
        '2024.1.13.9056': 'c:/Program Files/Audiokinetic/Wwise 2024.1.13.9056/Authoring/x64/Release/bin/Wwise.exe',
        '2025.1.7.9143': 'c:/Program Files/Audiokinetic/Wwise 2025.1.7.9143/Authoring/x64/Release/bin/Wwise.exe',
        '2025.1.11.9262': 'c:/Program Files/Audiokinetic/Wwise 2025.1.11.9262/Authoring/x64/Release/bin/Wwise.exe'}[build]
    # Actual retained owned 2024/2025 readiness used this direct-Wine route,
    # without native-app alternate-loader/wait-child options.
    # The 2021 SDK documents the flag; exact later Wwiselib.dll builds retain
    # its command-line option string. This tests delivery, not native effect.
    startup_arguments = ['-AutomationMode'] if automation_requested else []
    assert command == [str(facts.cx / 'bin/wine'), 'start.exe', '/wait', native_executable,
                       *startup_arguments, native_project]
    assert options['cwd'] == str(facts.project.parent)
    assert options['env']['HOME'] == str(facts.home)
    assert options['env']['WINEPREFIX'] == str(facts.prefix)
    assert options['env'].get('AK_AUTOMATION_MODE') == ('1' if automation_requested else None)
    assert not {'CX_ENV', 'WINE_WAIT_CHILD_PIPE', 'AK_AUTHORING_ARGS_OVERRIDE'} & set(options['env'])
    assert lifecycle.process is process
    assert lifecycle.ready_result['isCommandLine'] is False
    assert lifecycle.launch_project_attestation == {'method': 'owned_winepath_roundtrip',
        'project': str(facts.project), 'native_project': native_project, 'roundtrip_project': str(facts.project),
        **({'requested_startup_environment': {'AK_AUTOMATION_MODE': '1'}} if automation_requested else {}),
        'build': build, 'bottle_resolution': {'name': 'Wwise2019x64', 'private_prefix': str(facts.prefix),
            'managed_reference': str(facts.cx / 'support/Wwise2019x64'),
            'configuration': str(facts.cx / 'support/Wwise2019x64/cxbottle.conf'),
            'environment': {key: options['env'][key] for key in
                ('HOME', 'WINEPREFIX', 'CX_BOTTLE', 'CX_BOTTLE_PATH', 'CX_MANAGED_BOTTLE_PATH')}}}
    from tests.destructive.support.sandbox_fixture import SandboxFixtureError, require_authoring_launch_proof
    require_authoring_launch_proof(lifecycle, project=facts.project, build=build)
    # The proof admits exactly the requested flag, never arbitrary startup argv.
    invalid_commands = [command[:-1] + ['-Unexpected', native_project]]
    if automation_requested:
        invalid_commands.extend((command[:4] + [native_project],
            command[:4] + ['-AutomationMode', '-AutomationMode', native_project]))
    else:
        invalid_commands.append(command[:4] + ['-AutomationMode', native_project])
    for invalid_command in invalid_commands:
        lifecycle.command = invalid_command
        with pytest.raises(SandboxFixtureError, match='private project path and fixed command'):
            require_authoring_launch_proof(lifecycle, project=facts.project, build=build)
    lifecycle.command = command
    assert [Path(row[0][0]).name for row in preparation] == ['wineprefixcreate', 'wwise_prepare', 'wine', 'wine']
    assert all(row[1]['env']['WINEPREFIX'] == str(facts.prefix) and 0 < row[1]['timeout'] <= 120 for row in preparation)


def test_failed_authoring_preparation_still_uses_the_owners_prefix_cleanup_once(tmp_path, monkeypatch):
    facts = _bundle(tmp_path)
    from wwise_waapi import authoring_launch
    import wwise_waapi.headless as headless
    monkeypatch.setattr(authoring_launch.sys, 'platform', 'darwin')
    monkeypatch.setattr(authoring_launch, 'MACOS_AUTHORING_INSTALL_ROOT', facts.installed.parent)
    monkeypatch.setattr(headless, 'assert_port_free', lambda *_: None)
    commands = []
    def run(command, **kwargs):
        commands.append((command, kwargs))
        name = Path(command[0]).name
        if name == 'wineprefixcreate':
            facts.prefix.mkdir(parents=True)
        return SimpleNamespace(returncode=2 if name == 'wwise_prepare' else 0,
            stdout='999 fake pytest process\n' if name == 'ps' else '', stderr='')
    monkeypatch.setattr(authoring_launch.subprocess, 'run', run)
    lifecycle = HeadlessLifecycle(console_path=facts.console, project_path=facts.project, port=8080,
        host_kind='wwise-authoring', authoring_build=facts.build, authoring_owned_root=facts.owned,
        launch_env={'HOME': str(facts.home), 'WINEPREFIX': str(facts.prefix)},
        process_factory=lambda *_args, **_kwargs: pytest.fail('No Authoring process after preparation failure'))
    with pytest.raises(ValueError, match='preparation'):
        lifecycle.launch()
    assert lifecycle.launch_preflight_failure is None
    assert lifecycle.cleanup_report is not None
    assert lifecycle.cleanup_report.is_clean
    assert lifecycle.cleanup_report.wine_prefix == str(facts.prefix)
    cleanup = [row for row in commands if Path(row[0][0]).name == 'wineserver']
    assert [row[0] for row in cleanup] == [[str(facts.cx / 'bin/wineserver'), '-k']]
    assert cleanup[0][1]['env']['WINEPREFIX'] == str(facts.prefix)
    before = len(commands)
    lifecycle.shutdown()
    assert len(commands) == before


@pytest.mark.parametrize('drift', ['managed-link', 'configuration', 'private-registry', 'private-search', 'managed-search'])
def test_authoring_bottle_resolution_drift_stops_before_owned_process(tmp_path, monkeypatch, drift):
    facts = _bundle(tmp_path)
    from wwise_waapi import authoring_launch
    import wwise_waapi.headless as headless
    monkeypatch.setattr(authoring_launch.sys, 'platform', 'darwin')
    monkeypatch.setattr(authoring_launch, 'MACOS_AUTHORING_INSTALL_ROOT', facts.installed.parent)
    monkeypatch.setattr(headless, 'assert_port_free', lambda *_: None)
    native = 'Z:\\owned.wproj'
    def run(command, **kwargs):
        name, stdout = Path(command[0]).name, ''
        if name == 'wineprefixcreate':
            facts.prefix.mkdir(parents=True)
            (facts.prefix / 'system.reg').write_text('owned registry')
            (facts.prefix / 'cxbottle.conf').symlink_to(facts.cx / 'support/Wwise2019x64/cxbottle.conf')
        elif name == 'wwise_prepare':
            link = facts.prefix / 'drive_c/Program Files/Audiokinetic' / ('Wwise ' + facts.build)
            link.parent.mkdir(parents=True)
            link.symlink_to(facts.installed, target_is_directory=True)
        elif name == 'wine' and command[-2] == '-w':
            stdout = native
        elif name == 'wine' and command[-2] == '-u':
            stdout = str(facts.project)
            if drift == 'managed-link':
                link = facts.home / 'Library/Application Support/Wwise2019/BuiltinBottles'
                link.unlink()
                link.symlink_to(tmp_path, target_is_directory=True)
            elif drift == 'configuration':
                config = facts.prefix / 'cxbottle.conf'
                config.unlink()
                config.symlink_to(_executable(tmp_path / 'foreign.conf'))
            elif drift == 'private-registry':
                (facts.prefix / 'system.reg').unlink()
            else:
                key = 'CX_BOTTLE_PATH' if drift == 'private-search' else 'CX_MANAGED_BOTTLE_PATH'
                kwargs['env'][key] = '/unowned/Bottles'
        elif name == 'ps':
            stdout = '999 fake pytest process\n'
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')
    monkeypatch.setattr(authoring_launch.subprocess, 'run', run)
    lifecycle = HeadlessLifecycle(console_path=facts.console, project_path=facts.project, port=8080,
        host_kind='wwise-authoring', authoring_build=facts.build, authoring_owned_root=facts.owned,
        launch_env={'HOME': str(facts.home), 'WINEPREFIX': str(facts.prefix)},
        process_factory=lambda *_a, **_kw: pytest.fail('No process after bottle resolution drift'))
    with pytest.raises((ValueError, OSError)):
        lifecycle.launch()
    assert lifecycle.process is None
    assert lifecycle.launch_project_attestation is None


@pytest.mark.parametrize('mismatch', ['console', 'build', 'field-type'])
def test_authoring_readiness_rejects_wrong_host_or_build_without_retry(tmp_path, monkeypatch, mismatch):
    from tests.unit.test_headless_lifecycle import FakeClient, FakeProcess
    info = {'isCommandLine': False, 'version': {'year': 2025, 'major': 1, 'minor': 7, 'build': 9143}}
    if mismatch == 'console':
        info['isCommandLine'] = True
    elif mismatch == 'build':
        info['version']['build'] = 9144
    else:
        info['version']['year'] = '2025'
    calls = []
    lifecycle = HeadlessLifecycle(host_kind='wwise-authoring', authoring_build='2025.1.7.9143', port=8080,
        waapi_client_factory=lambda _: FakeClient(calls, result=info))
    process = FakeProcess()
    lifecycle.process = process
    monkeypatch.setattr(HeadlessLifecycle, '_terminate', lambda self, value: value.terminate())
    monkeypatch.setattr(HeadlessLifecycle, '_cleanup_detached_waapi_servers', lambda self: [])
    with pytest.raises(HeadlessLifecycleError, match='Authoring.*host/build'):
        lifecycle.wait_ready()
    assert calls == ['ak.wwise.core.getInfo']
    assert lifecycle.ready_result is None
    assert process.terminated


@pytest.mark.parametrize('observed', [
    {'uri': 'ak.wwise.test_refusal', 'message': 'Fixture error envelope', 'details': {'code': 7}},
    {'result': {'isCommandLine': False, 'version': {'year': 2024, 'major': 1, 'minor': 13, 'build': 9056}}},
    {'isCommandLine': 0, 'version': {'year': '2024', 'major': 1, 'minor': 13, 'build': 9056}},
])
def test_authoring_readiness_preserves_client_response_without_retry(monkeypatch, observed):
    from tests.unit.test_headless_lifecycle import FakeClient, FakeProcess
    calls = []
    client = FakeClient(calls, result=observed)
    lifecycle = HeadlessLifecycle(host_kind='wwise-authoring', authoring_build='2024.1.13.9056', port=8080,
        waapi_client_factory=lambda _: client)
    process = FakeProcess()
    lifecycle.process = process
    monkeypatch.setattr(HeadlessLifecycle, '_terminate', lambda self, value: value.terminate())
    monkeypatch.setattr(HeadlessLifecycle, '_cleanup_detached_waapi_servers', lambda self: [])
    with pytest.raises(HeadlessLifecycleError, match='Authoring.*host/build') as failure:
        lifecycle.wait_ready()
    captured = failure.value.diagnostics['observed_host_info']['client_result']
    assert captured['boundary'] == 'waapi-client.call'
    assert captured['uri'] == 'ak.wwise.core.getInfo'
    assert captured['value'] == observed
    assert captured['value_present'] is True
    assert captured['complete'] is True
    assert captured['omitted'] == {}
    assert calls == ['ak.wwise.core.getInfo']
    assert client.disconnected and process.terminated
    assert lifecycle.ready_result is None


@pytest.mark.parametrize('pending', [{}, None], ids=['empty', 'none'])
def test_authoring_readiness_waits_for_identity_after_absent_client_response(monkeypatch, pending):
    from tests.unit.test_headless_lifecycle import FakeClient, FakeProcess
    from wwise_waapi.headless import LifecycleTimeouts
    import wwise_waapi.headless as headless
    clock = SimpleNamespace(now=0.0)
    def sleep(seconds):
        clock.now += seconds
    monkeypatch.setattr(headless, 'time', SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    expected = {'isCommandLine': False, 'version': {'year': 2024, 'major': 1, 'minor': 13, 'build': 9056}}
    responses = [pending, pending, expected]
    clients, calls = [], []
    def client_factory(_):
        client = FakeClient(calls, result={})
        client.result = responses[len(clients)]  # FakeClient's constructor uses None as its default.
        clients.append(client)
        return client
    lifecycle = HeadlessLifecycle(host_kind='wwise-authoring', authoring_build='2024.1.13.9056', port=8080,
        waapi_client_factory=client_factory,
        timeouts=LifecycleTimeouts(readiness=1, probe=5, probe_interval=0.25))
    process = FakeProcess()
    lifecycle.process = process
    monkeypatch.setattr(HeadlessLifecycle, '_terminate', lambda self, value: value.terminate())
    monkeypatch.setattr(HeadlessLifecycle, '_cleanup_detached_waapi_servers', lambda self: [])
    assert lifecycle.wait_ready() == expected
    assert lifecycle.ready_result is expected
    assert calls == ['ak.wwise.core.getInfo'] * 3
    assert clock.now == 0.5
    assert all(client.disconnected for client in clients)
    assert not process.terminated


@pytest.mark.parametrize('terminal', ['deadline', 'deadline-null', 'process-exit'])
def test_authoring_pending_identity_failure_retains_empty_observation(monkeypatch, terminal):
    from tests.unit.test_headless_lifecycle import FakeClient, FakeProcess
    from wwise_waapi.headless import EarlyProcessExit, LifecycleTimeouts, ReadinessTimeout
    import wwise_waapi.headless as headless
    is_deadline = terminal != 'process-exit'
    if is_deadline:
        clock = SimpleNamespace(now=0.0, sleeps=[])
        def sleep(seconds):
            clock.sleeps.append(seconds)
            clock.now += seconds
        # Replace this module's reference, never attributes on global time.
        # The threaded probe, client.call and disconnect remain real.
        monkeypatch.setattr(headless, 'time', SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    clients, calls = [], []
    process = FakeProcess()
    def client_factory(_):
        client = FakeClient(calls, result={})
        if is_deadline:
            responses = [None, {}] if terminal == 'deadline' else [{}, None]
            client.result = responses[len(clients) % 2]
        clients.append(client)
        if terminal == 'process-exit':
            process.returncode = 5
        return client
    lifecycle = HeadlessLifecycle(host_kind='wwise-authoring', authoring_build='2024.1.13.9056', port=8080,
        waapi_client_factory=client_factory,
        timeouts=(LifecycleTimeouts(readiness=1, probe=5, probe_interval=0.25) if is_deadline
                  else LifecycleTimeouts(readiness=0.02, probe=0.01, probe_interval=0.001)))
    lifecycle.process = process
    monkeypatch.setattr(HeadlessLifecycle, '_terminate', lambda self, value: value.terminate())
    monkeypatch.setattr(HeadlessLifecycle, '_cleanup_detached_waapi_servers', lambda self: [])
    expected_error = ReadinessTimeout if is_deadline else EarlyProcessExit
    with pytest.raises(expected_error) as failure:
        lifecycle.wait_ready()
    observed = failure.value.diagnostics['observed_host_info']
    assert observed['classification'] == 'identity_pending'
    assert observed['client_result']['value'] == (None if terminal == 'deadline-null' else {})
    assert observed['client_result']['value_present'] is True
    assert observed['result_type'] == ('NoneType' if terminal == 'deadline-null' else 'dict')
    assert observed['client_result']['complete'] is True
    assert observed['client_result']['omitted'] == {}
    assert failure.value.diagnostics['last_exception'] is None
    assert lifecycle.ready_result is None
    assert calls and set(calls) == {'ak.wwise.core.getInfo'}
    assert all(client.disconnected for client in clients)
    if is_deadline:
        assert len(calls) == 4 and clock.sleeps == [0.25] * 4
        assert failure.value.diagnostics['duration'] == 1
        assert process.terminated and lifecycle.cleanup_report.process_exited
    else:
        assert len(calls) == 1
        assert failure.value.diagnostics['exit_code'] == 5


def test_authoring_readiness_diagnostic_bounds_hostile_and_oversized_response(monkeypatch):
    import json
    from tests.unit.test_headless_lifecycle import FakeClient, FakeProcess

    class Hostile(dict):
        def items(self):
            pytest.fail('Do not iterate a custom mapping')
        def __iter__(self):
            pytest.fail('Do not iterate a custom mapping')
        def __repr__(self):
            pytest.fail('Do not render a custom object')

    cycle = []
    cycle.append(cycle)
    observed = {'': None, 'false': False, 'hostile': Hostile(), 'cycle': cycle,
        'deep': [[[[[True]]]]], 'oversized': '雨' * 1025,
        'key' * 1025: 1, 'escaped': ['"\\' * 256] * 32,
        'many': [dict.fromkeys([str(i) for i in range(32)], True)] * 32}
    calls = []
    client = FakeClient(calls, result=observed)
    lifecycle = HeadlessLifecycle(host_kind='wwise-authoring', authoring_build='2024.1.13.9056', port=8080,
        waapi_client_factory=lambda _: client)
    process = FakeProcess()
    lifecycle.process = process
    monkeypatch.setattr(HeadlessLifecycle, '_terminate', lambda self, value: value.terminate())
    monkeypatch.setattr(HeadlessLifecycle, '_cleanup_detached_waapi_servers', lambda self: [])
    with pytest.raises(HeadlessLifecycleError, match='Authoring.*host/build') as failure:
        lifecycle.wait_ready()
    captured = failure.value.diagnostics['observed_host_info']['client_result']
    assert len(json.dumps(captured).encode('utf-8')) <= 8192
    assert captured['complete'] is False
    assert captured['value'][''] is None and captured['value']['false'] is False
    assert 'hostile' not in captured['value'] and 'oversized' not in captured['value']
    assert 'key' not in captured['value']
    assert captured['omitted']['non_json_type'] == 1
    assert captured['omitted']['cycle'] == 1
    assert captured['omitted']['depth'] > 0
    assert captured['omitted']['string_bytes'] == 1
    assert captured['omitted']['key_bytes'] == 1
    assert captured['omitted']['bytes'] > 0
    assert calls == ['ak.wwise.core.getInfo']
    assert client.disconnected and process.terminated and lifecycle.ready_result is None


@pytest.mark.parametrize('invalid', ['project-alias', 'unowned-project', 'existing-prefix', 'bundle-build', 'port', 'extra-args', 'windows', 'winepath-absent', 'winepath-alias', 'winepath-directory', 'prefix-drift'])
def test_authoring_ownership_rejects_invalid_context_before_any_tool_or_process(tmp_path, monkeypatch, invalid):
    facts = _bundle(tmp_path)
    from wwise_waapi import authoring_launch
    import wwise_waapi.headless as headless
    monkeypatch.setattr(authoring_launch.sys, 'platform', 'win32' if invalid == 'windows' else 'darwin')
    monkeypatch.setattr(authoring_launch, 'MACOS_AUTHORING_INSTALL_ROOT', facts.installed.parent)
    monkeypatch.setattr(headless, 'assert_port_free', lambda *_: None)
    monkeypatch.setattr(authoring_launch.subprocess, 'run', lambda *_a, **_kw: pytest.fail('No tool before owned-context validation'))
    if invalid in {'winepath-absent', 'winepath-alias', 'winepath-directory'}:
        program = facts.cx / 'lib/wine/x86_64-windows/winepath.exe'
        program.unlink()
        if invalid == 'winepath-alias':
            program.symlink_to(_executable(tmp_path / 'foreign-winepath.exe'))
        elif invalid == 'winepath-directory':
            program.mkdir()
    project = facts.project
    if invalid == 'project-alias':
        project = facts.project.parent / 'alias.wproj'
        project.symlink_to(facts.project)
    if invalid == 'unowned-project':
        project = tmp_path / 'user-project.wproj'
        project.write_text('user')
    if invalid == 'existing-prefix':
        facts.prefix.mkdir(parents=True)
    lifecycle = HeadlessLifecycle(console_path=facts.console, project_path=project,
        port=8081 if invalid == 'port' else 8080, command_extra_args=['extra'] if invalid == 'extra-args' else [],
        host_kind='wwise-authoring', authoring_build='2025.1.7.9144' if invalid == 'bundle-build' else facts.build,
        authoring_owned_root=facts.owned, launch_env={'HOME': str(facts.home), 'WINEPREFIX': str(facts.prefix) + ('-foreign' if invalid == 'prefix-drift' else '')},
        process_factory=lambda *_a, **_kw: pytest.fail('No process before owned-context validation'))
    with pytest.raises((ValueError, HeadlessLifecycleError)):
        lifecycle.launch()
    assert lifecycle._authoring_context is None
    if invalid not in {'port', 'extra-args'}:
        assert lifecycle.launch_preflight_failure == {
            'phase': 'authoring_context_validation', 'tools_started': False, 'process_started': False}
        assert lifecycle.cleanup_report is None
        assert lifecycle.launch_preparation == []


@pytest.mark.parametrize('translation', ['relative', 'multiline', 'foreign-roundtrip'])
def test_authoring_invalid_project_translation_cleans_only_owned_prefix_without_launch(tmp_path, monkeypatch, translation):
    facts = _bundle(tmp_path)
    from wwise_waapi import authoring_launch
    import wwise_waapi.headless as headless
    monkeypatch.setattr(authoring_launch.sys, 'platform', 'darwin')
    monkeypatch.setattr(authoring_launch, 'MACOS_AUTHORING_INSTALL_ROOT', facts.installed.parent)
    monkeypatch.setattr(headless, 'assert_port_free', lambda *_: None)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        name = Path(command[0]).name
        stdout = ''
        if name == 'wineprefixcreate':
            facts.prefix.mkdir(parents=True)
        elif name == 'wwise_prepare':
            link = facts.prefix / 'drive_c/Program Files/Audiokinetic' / ('Wwise ' + facts.build)
            link.parent.mkdir(parents=True)
            link.symlink_to(facts.installed, target_is_directory=True)
        elif name == 'wine' and command[-2] == '-w':
            stdout = {'relative': 'relative.wproj', 'multiline': 'Z:\\one.wproj\nZ:\\two.wproj',
                      'foreign-roundtrip': 'Z:\\foreign.wproj'}[translation]
        elif name == 'wine' and command[-2] == '-u':
            stdout = str(_executable(tmp_path / 'foreign.wproj'))
        if name == 'ps':
            stdout = '999 fake pytest process\n'
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')
    monkeypatch.setattr(authoring_launch.subprocess, 'run', run)
    lifecycle = HeadlessLifecycle(console_path=facts.console, project_path=facts.project, port=8080,
        host_kind='wwise-authoring', authoring_build=facts.build, authoring_owned_root=facts.owned,
        launch_env={'HOME': str(facts.home), 'WINEPREFIX': str(facts.prefix)},
        process_factory=lambda *_a, **_kw: pytest.fail('No process after invalid translation'))
    with pytest.raises(ValueError, match='mapping|roundtrip'):
        lifecycle.launch()
    assert lifecycle.launch_preflight_failure is None
    assert lifecycle.cleanup_report.is_clean
    assert lifecycle.cleanup_report.launch_pid is None
    assert lifecycle.cleanup_report.wine_prefix == str(facts.prefix)
    assert not any('start.exe' in command for command in commands)
    assert [command for command in commands if Path(command[0]).name == 'wineserver'] == [
        [str(facts.cx / 'bin/wineserver'), '-k']]

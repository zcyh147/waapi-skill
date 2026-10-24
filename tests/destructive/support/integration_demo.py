"""Private, source-pinned context for one installed Integration Demo observation.

This is not an alternate public Gateway profile or a replacement native catalog.
The normal fixture pin remains unchanged. No process is launched by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import plistlib
import re

from wwise_waapi.filesystem_security import path_is_link_or_reparse
from wwise_waapi.capabilities import CapabilityCatalog

BUILD = '2025.1.11.9262'
SCOPE = 'integration-demo-prepare-area1-loaded-media'
INSTALLED_BUNDLE = Path('/Applications/Audiokinetic/Wwise_2025.1.11.9262/Wwise.app')
INSTALLED_SCHEMAS = Path('/Library/Application Support/Audiokinetic/Wwise 2025.1.11.9262/Authoring/Data/Schemas')
URIS = tuple('ak.wwise.' + suffix for suffix in (
    'core.getInfo', 'core.getProjectInfo', 'waapi.getSchema',
    'core.remote.getAvailableConsoles', 'core.remote.getConnectionStatus',
    'core.remote.connect', 'core.remote.disconnect', 'core.profiler.enableProfilerData',
    'core.profiler.startCapture', 'core.profiler.stopCapture',
    'core.profiler.getCursorTime', 'core.profiler.getLoadedMedia'))
DEFINITIONS = (('common_definitions.json', 'guid'), ('common_definitions.json', 'uint16'),
    ('common_definitions.json', 'uint32'), ('waapi_definitions.json', 'cursorTime'),
    ('waapi_definitions.json', 'profilerCursor'), ('waapi_definitions.json', 'profilerDataType'))
SKILL = Path(__file__).resolve().parents[3] / 'skills/waapi-skill'


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _read(path):
    if (not path.is_absolute() or any(path_is_link_or_reparse(p) for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024):
        raise ValueError('Scoped schema/source path is missing, aliased or oversized')
    return path.read_bytes()


def _function_schema(value):
    return {key: value[key] for key in ('argsSchema', 'description', 'optionsSchema', 'resultSchema')}


@dataclass(frozen=True)
class IntegrationDemoObservation:
    """Immutable exact-build/source identity; live parity is a separate gate."""
    bundle: Path
    schemas: Path
    schema_bytes: bytes
    source_files: tuple[tuple[str, str, int], ...]
    build: str = BUILD
    scope: str = SCOPE

    @classmethod
    def from_installed(cls, *, bundle: Path, schemas: Path):
        sources = []
        def read(path):
            raw = _read(path)
            sources.append((str(path), sha256(raw).hexdigest(), path.stat().st_mtime_ns))
            return raw
        controls = {uri: CapabilityCatalog().describe_for_profile('2025.1', uri,
            profile='wwise-authoring-ui').schema for uri in URIS}
        selected = {}
        try:
            for uri in URIS:
                functions = json.loads(read(schemas / 'WAAPI' / (uri + '.json')))['functions']
                matches = [row for row in functions if row['id'] == uri]
                if len(matches) != 1 or _function_schema(matches[0]) != _function_schema(controls[uri]):
                    raise ValueError('Scoped schema differs from packaged business control: ' + uri)
                selected[uri] = _function_schema(matches[0])
            definitions = json.loads((SKILL / 'resources/manifest/2025.1/definitions.json').read_bytes())['documents']
            documents = {name: json.loads(read(schemas / 'Definitions' / name)) for name in sorted({name for name, _ in DEFINITIONS})}
            for name, key in DEFINITIONS:
                if documents[name]['definitions'][key] != definitions[name]['definitions'][key]:
                    raise ValueError('Scoped schema definition differs: ' + name + '#/definitions/' + key)
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError('Scoped schema source is missing or malformed') from exc
        header = read(bundle.parent / 'SDK/include/AK/AkWwiseSDKVersion.h').decode('utf-8')
        components = [re.search(r'^#define\s+AK_WWISESDK_VERSION_' + key + r'\s+(\d+)', header, re.M)
            for key in ('MAJOR', 'MINOR', 'SUBMINOR', 'BUILD')]
        sdk_build = '.'.join(match.group(1) for match in components if match is not None)
        if sdk_build != BUILD:
            raise ValueError('Scoped SDK build differs from Authoring')
        for relative in ('DemoPages/DemoPrepare.cpp', 'Mac/main.m', 'Mac/Platform.h'):
            read(bundle.parent / 'SDK/samples/IntegrationDemo' / relative)
        info = plistlib.loads(read(bundle / 'Contents/Info.plist'))
        if info.get('CFBundleVersion') != BUILD:
            raise ValueError('Scoped Authoring bundle build mismatch')
        return cls(bundle, schemas, _json_bytes(selected), tuple(sources))

    @property
    def identity(self):
        return sha256(_json_bytes({'build': self.build, 'scope': self.scope,
            'bundle': str(self.bundle), 'schemas': str(self.schemas),
            'schema_sha256': sha256(self.schema_bytes).hexdigest(), 'sources': self.source_files})).hexdigest()

    def validate(self, *, version, host_kind, console):
        if (type(self) is not IntegrationDemoObservation or self.build != BUILD or self.scope != SCOPE
                or version != '2025.1' or host_kind != 'wwise-authoring'
                or Path(console) != self.bundle / 'Contents/Tools/WwiseConsole.sh'):
            raise ValueError('Scoped Integration Demo context/build/host/console mismatch')
        for name, digest, mtime in self.source_files:
            path = Path(name)
            if sha256(_read(path)).hexdigest() != digest or path.stat().st_mtime_ns != mtime:
                raise ValueError('Scoped schema/source context changed before launch')
        if self != type(self).from_installed(bundle=self.bundle, schemas=self.schemas):
            raise ValueError('Scoped schema context differs from its sealed installed sources')
        if set(json.loads(self.schema_bytes)) != set(URIS):
            raise ValueError('Scoped schema context is incomplete')
        return self.build

    def reflect(self, call, *, expected_info):
        """Exactly twelve public schema reads, bounded and session-attested."""
        self.validate(version='2025.1', host_kind='wwise-authoring',
            console=self.bundle / 'Contents/Tools/WwiseConsole.sh')
        def identity(info):
            return {key: info.get(key) for key in ('version', 'isCommandLine', 'sessionId', 'processId')}
        if ('.'.join(str(expected_info['version'][key]) for key in ('year', 'major', 'minor', 'build')) != self.build
                or expected_info.get('isCommandLine') is not False
                or not expected_info.get('processId') or not expected_info.get('sessionId')):
            raise ValueError('Scoped live Authoring build/session mismatch')
        expected = identity(expected_info)
        controls = json.loads(self.schema_bytes)
        receipts = []
        if identity(call(['status'])['wwise']) != expected:
            raise ValueError('Scoped reflection start session mismatch')
        for uri in URIS:
            payload = call(['waapi-schema', uri, '--exclude-examples'])
            if (len(_json_bytes(payload)) > 1024 * 1024
                    or identity(payload.get('reflection_context', {})) != expected
                    or payload.get('agent_result') != controls[uri]):
                raise ValueError('Scoped live schema/session mismatch: ' + uri)
            receipts.append({'uri': uri, 'sha256': sha256(_json_bytes(payload)).hexdigest()})
        if identity(call(['status'])['wwise']) != expected:
            raise ValueError('Scoped reflection end session mismatch')
        self.validate(version='2025.1', host_kind='wwise-authoring',
            console=self.bundle / 'Contents/Tools/WwiseConsole.sh')
        return {'build': self.build, 'scope': self.scope, 'identity': self.identity,
            'source_files': self.source_files, 'schemas': receipts,
            'boundary': '12 selected schemas and 6 source definitions only; not a full native catalog'}

def installed_demo_fixture_context(environment, *, root):
    """Closed one-case factory for the existing batch driver, before allocation."""
    config = Path(environment.get('WWISE_TEST_CONFIG', ''))
    raw = _read(config)
    expected = {'wwise_console': str(INSTALLED_BUNDLE / 'Contents/Tools/WwiseConsole.sh'),
        'sample_project': str(INSTALLED_BUNDLE.parent / 'SDK/samples/IntegrationDemo/WwiseProject/IntegrationDemo.wproj'),
        'sandbox_root': str(root / 'owned/sandbox-root')}
    if json.loads(raw) != {'versions': {'2025.1': expected}}:
        raise ValueError('Integration Demo requires its explicit isolated exact-build source/root config')
    for key, field in (('WWISE_CONSOLE', 'wwise_console'),
            ('WWISE_SAMPLE_PROJECT_PATH', 'sample_project'), ('WWISE_SANDBOX_ROOT', 'sandbox_root')):
        if environment.get(key) != expected[field]:
            raise ValueError('Integration Demo environment differs from its isolated config: ' + key)
    _read(Path(expected['sample_project']))
    context = IntegrationDemoObservation.from_installed(bundle=INSTALLED_BUNDLE, schemas=INSTALLED_SCHEMAS)
    context.validate(version='2025.1', host_kind='wwise-authoring', console=expected['wwise_console'])
    return context, (str(config), sha256(raw).hexdigest(), config.stat().st_mtime_ns)


NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_integration_demo_loaded_media')


class OwnedIntegrationDemo:
    """One stock Profile child, preserving its SDK-relative bank lookup."""
    def __init__(self, context, runtime):
        import secrets
        self.context, self.runtime = context, runtime
        self.sdk = context.bundle.parent / 'SDK'
        self.app_relative = Path('Mac_Xcode1600/Profile/bin/IntegrationDemo/IntegrationDemo.app')
        self.project_relative = Path('samples/IntegrationDemo/WwiseProject')
        self.owned_sdk = runtime.owned_root / 'integration-demo/SDK'
        self.process = None
        self.token = secrets.token_hex(24)
        self.before = None
        self.command_port = None
        self.ready = runtime.evidence_root / 'integration-demo-ready.json'
        self.action = runtime.evidence_root / 'integration-demo-action.json'
        self.used = False
        self.started_monotonic = None
        self._streams = {}
        self._readers = []
        if self.ready.exists() or self.action.exists():
            raise ValueError('Demo action/ready files must be absent before launch')

    def proof(self):
        from dataclasses import asdict
        from tests.destructive.support.sandbox_fixture import hash_project
        result = {}
        import xml.etree.ElementTree as ET
        banks = self.sdk / self.project_relative / 'GeneratedSoundBanks/Mac'
        for name in ('Init.bnk', 'PrepareDemo.bnk', 'Media/124871431.wem'):
            raw = _read(banks / name)
            if not raw:
                raise ValueError('Required Demo bank/media source is empty')
            result[name] = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw),
                'mtime_ns': (banks / name).stat().st_mtime_ns}
        metadata = ET.fromstring(_read(banks / 'SoundbanksInfo.xml'))
        expected = [bank for bank in metadata.iter('SoundBank') if bank.findtext('ShortName') == 'PrepareDemo'
            and any(event.get('Name') == 'Enter_Area_1' and any(ref.get('Id') == '124871431'
                for ref in event.iter('MediaRef')) for event in bank.iter('Event'))]
        if len(expected) != 1:
            raise ValueError('Demo metadata does not attribute Area1 to media124871431')
        for relative in (self.app_relative, self.project_relative):
            root = self.sdk / relative
            # Reject aliases before the shared full-tree hasher/copy follows them.
            entries = list(root.rglob('*'))
            if (not root.is_dir() or len(entries) > 20000
                    or any(path_is_link_or_reparse(p) for p in (root, *root.parents, *entries))
                    or sum(p.stat().st_size for p in entries if p.is_file()) > 1024 * 1024 * 1024):
                raise ValueError('Installed Demo source is missing, aliased or exceeds finite copy bounds')
            result[relative.as_posix()] = {'tree': asdict(hash_project(root, preferred_strategy='full')),
                'mtimes': [(p.relative_to(root).as_posix(), p.stat().st_mtime_ns)
                    for p in sorted(entries) if p.is_file()]}
        return result

    def start(self):
        import os
        import shutil
        import subprocess
        import threading
        import time
        from datetime import datetime, timezone
        from tests.semantic.support.codex_harness import subprocess_process_group_options
        expected_project = self.sdk / self.project_relative / 'IntegrationDemo.wproj'
        if self.runtime.sandbox.source_project != expected_project:
            raise ValueError('Demo Authoring source must be the matching installed IntegrationDemo project')
        self.context.validate(version='2025.1', host_kind='wwise-authoring',
            console=self.context.bundle / 'Contents/Tools/WwiseConsole.sh')
        if self.ready.exists() or self.action.exists() or self.owned_sdk.exists():
            raise ValueError('Demo owned copy/action state must be fresh before launch')
        self.before = self.proof()
        for relative in (self.app_relative, self.project_relative):
            destination = self.owned_sdk / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.sdk / relative, destination)
            from tests.destructive.support.sandbox_fixture import hash_project
            if hash_project(destination, preferred_strategy='full').digest != self.before[relative.as_posix()]['tree']['digest']:
                raise ValueError('Owned Demo copy differs from installed source')
        app = self.owned_sdk / self.app_relative
        binary = app / 'Contents/MacOS/IntegrationDemo'
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('Stock Profile Demo executable is unavailable')
        self.started_monotonic = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        self.process = subprocess.Popen([str(binary)], cwd=app.parent,
            env={**os.environ, **self.runtime.runner_environment}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **subprocess_process_group_options())
        for name in ('stdout', 'stderr'):
            state = self._streams[name] = {'data': bytearray(), 'bytes_seen': 0, 'error': None}
            def drain(pipe, state):
                try:
                    while chunk := getattr(pipe, 'read1', pipe.read)(4096):
                        state['bytes_seen'] += len(chunk)
                        state['data'].extend(chunk[:max(0, 65536 - len(state['data']))])
                except Exception as exc:
                    state['error'] = str(exc)[:1024]
                finally:
                    pipe.close()
            reader = threading.Thread(target=drain, args=(getattr(self.process, name), state), daemon=True)
            self._readers.append(reader)
            reader.start()
        return {'build': self.context.build, 'pid': self.process.pid, 'binary': str(binary),
            'cwd': str(app.parent), 'source': self.before, 'token': self.token,
            'started_at': started_at, 'pgid': self.process.pid,
            'process_output_receipt': str(self.runtime.evidence_root / ('integration-demo-process-' + self.token + '.json'))}

    def process_observation(self, *, include_output=False):
        """Bounded exact-child state; output is retained even after a startup failure."""
        import time
        streams = {}
        for name, state in self._streams.items():
            raw = bytes(state['data'])
            streams[name] = {'bytes_seen': state['bytes_seen'], 'bytes_retained': len(raw),
                'overflow': state['bytes_seen'] > 65536, 'error': state['error']}
            if include_output:
                streams[name].update(sha256=sha256(raw).hexdigest(), text=raw.decode('utf-8', 'replace'))
        return {'pid': self.process.pid, 'poll': self.process.poll(),
            'elapsed_seconds': time.monotonic() - self.started_monotonic, 'streams': streams}

    def startup_observation(self, *, timeout_seconds):
        """Observe stock SDK communication sockets, without sending network traffic."""
        import subprocess
        receipt = self.process_observation()
        receipt.update(ready=False, command_ports=[])
        if receipt['poll'] is not None:
            return receipt
        argv = ['/usr/sbin/lsof', '-nP', '-a', '-p', str(self.process.pid), '-iUDP', '-iTCP', '-FpcnPT']
        result = subprocess.run(argv, capture_output=True, timeout=timeout_seconds, check=False)
        if len(result.stdout) > 16384 or len(result.stderr) > 16384:
            raise ValueError('Owned Demo socket evidence exceeds byte bound')
        receipt.update(socket_argv=argv, socket_exit=result.returncode,
            socket_stdout=result.stdout.decode('utf-8', 'replace'),
            socket_stderr=result.stderr.decode('utf-8', 'replace'), post_poll=self.process.poll())
        if result.returncode not in (0, 1) or result.stderr:
            raise ValueError('Owned Demo socket observation failed: ' + receipt['socket_stderr'][:1024])
        lines = receipt['socket_stdout'].splitlines()
        if not lines:
            return receipt
        if [line for line in lines if line.startswith('p')] != ['p' + str(self.process.pid)]:
            raise ValueError('Owned Demo socket PID differs')
        sockets, current = [], {}
        for line in lines:
            if line.startswith('f'):
                current = {}
                sockets.append(current)
            elif line.startswith(('P', 'n')):
                current[line[0]] = line[1:]
            elif line.startswith('TST='):
                current['state'] = line[4:]
        ports = [int(match.group(1)) for row in sockets
            if row.get('P') == 'TCP' and row.get('state') == 'LISTEN'
            and (match := re.search(r':(\d+)$', row.get('n', ''))) and 1 <= int(match.group(1)) <= 65535]
        receipt['command_ports'] = sorted(set(ports))
        receipt['ready'] = (receipt['post_poll'] is None and bool(ports)
            and any(row.get('P') == 'UDP' and row.get('n', '').endswith(':24024') for row in sockets))
        return receipt

    def owns_port(self, port, host, *, timeout_seconds=5):
        """One bounded OS receipt binds discovery's actual port to our child."""
        import subprocess
        import time
        deadline = time.monotonic() + timeout_seconds
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError('Owned Demo port ownership deadline exceeded')
            return value
        if self.process is None or self.process.poll() is not None or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Demo process/port ownership is unavailable')
        result = subprocess.run(['/usr/sbin/lsof', '-nP', '-a', '-p', str(self.process.pid),
            '-iTCP:' + str(port), '-sTCP:LISTEN', '-Fp'], capture_output=True, timeout=remaining(), check=False)
        if result.returncode or len(result.stdout) > 4096 or result.stdout.decode().splitlines() != ['p' + str(self.process.pid)]:
            raise ValueError('Remote command port is not owned by the exact Demo PID')
        import ipaddress
        address = ipaddress.ip_address(host)
        interface_proof = None
        if not address.is_loopback:
            interfaces = subprocess.run(['/sbin/ifconfig'], capture_output=True, timeout=remaining(), check=False)
            if (interfaces.returncode or len(interfaces.stdout) > 65536
                    or host not in re.findall(r'\binet ([0-9.]+)', interfaces.stdout.decode('utf-8'))):
                raise ValueError('Discovered Demo host is not a local interface')
            interface_proof = interfaces.stdout.decode('utf-8')
        remaining()
        self.command_port, self.remote_host = port, host
        return {'pid': self.process.pid, 'host': host, 'command_port': port,
            'stdout': result.stdout.decode(), 'local_interface_proof': interface_proof}

    def __call__(self):
        """Main performs CUA once; this callback only coordinates bounded files."""
        import time
        if self.used or self.process is None or self.process.poll() is not None or self.action.exists():
            raise ValueError('Demo producer must run once with fresh Main action evidence')
        self.used = True
        expected = {'token': self.token, 'pid': self.process.pid, 'build': self.context.build,
            'page': 'Prepare Event & Bank Demo', 'area': 1}
        ready = {**expected, 'app': str(self.owned_sdk / self.app_relative),
            'source': self.before, 'menu': ['Bank & Event Loading Demos', 'Prepare Event/Bank Demo']}
        with self.ready.open('xb') as stream:
            stream.write(_json_bytes(ready))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ValueError('Owned Demo exited before Main CUA receipt')
            if self.action.exists():
                payload = json.loads(_read(self.action))
                if (any(payload.get(key) != value for key, value in expected.items())
                        or payload.get('action') != 'focused-stock-prepare-area1'
                        or not isinstance(payload.get('screenshot'), str)):
                    raise ValueError('Main CUA receipt context differs from the owned Demo')
                screenshot = Path(payload['screenshot'])
                if not screenshot.is_relative_to(self.runtime.evidence_root):
                    raise ValueError('Main CUA screenshot must belong to owned evidence')
                image = _read(screenshot)
                return {**payload, 'screenshot_sha256': sha256(image).hexdigest(),
                    'boundary': 'UI action evidence only; native LoadedMedia row decides success'}
            time.sleep(0.25)
        raise TimeoutError('Main CUA stock Prepare page receipt not received in 120 seconds')

    def stop(self):
        from tests.semantic.support.codex_harness import terminate_process_group, kill_process_group
        from tests.destructive.support.sandbox_fixture import wait_for_port_release
        pre_cleanup = None if self.process is None else self.process_observation()
        output_path = self.runtime.evidence_root / ('integration-demo-process-' + self.token + '.json')
        if self.process is not None:
            # Preserve partial output even if termination/group verification later fails.
            output_path.write_bytes(_json_bytes(self.process_observation(include_output=True)))
        action = 'already-exited'
        if self.process is not None:
            if self.process.poll() is None:
                action = 'terminate'
                terminate_process_group(self.process)
                try:
                    self.process.wait(timeout=5)
                except __import__('subprocess').TimeoutExpired:
                    action = 'kill'
                    kill_process_group(self.process)
                    self.process.wait(timeout=5)
            if self.process.poll() is None:
                raise ValueError('Owned Demo did not exit')
            import os
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError('Owned Demo process group still has residual processes')
        for reader in self._readers:
            reader.join(timeout=2)
        if any(reader.is_alive() for reader in self._readers):
            raise ValueError('Owned Demo process output did not close')
        if self.process is not None:
            output_path.write_bytes(_json_bytes(self.process_observation(include_output=True)))
        if self.command_port is not None:
            wait_for_port_release(self.remote_host, self.command_port)
        self.context.validate(version='2025.1', host_kind='wwise-authoring',
            console=self.context.bundle / 'Contents/Tools/WwiseConsole.sh')
        after = self.proof()
        if self.before is not None and self.before != after:
            raise ValueError('Installed Demo source changed')
        return {'process_exited': self.process is None or self.process.poll() is not None,
            'source_preserved': True, 'command_port_released': self.command_port,
            'pre_cleanup_returncode': None if pre_cleanup is None else pre_cleanup['poll'],
            'cleanup_action': action, 'final_returncode': None if self.process is None else self.process.poll(),
            'process_group_absent': True,
            **({} if self.process is None else self.process_observation(include_output=True))}

"""Owned Mac Authoring preparation for HeadlessLifecycle's fixed host strategy.

This module never launches the Authoring process. The existing lifecycle owns
that process, readiness, shutdown and prefix cleanup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path, PureWindowsPath
import plistlib
import re
import subprocess
import sys

from .filesystem_security import path_is_link_or_reparse

MACOS_AUTHORING_INSTALL_ROOT = Path('/Library/Application Support/Audiokinetic')


class AuthoringLaunchError(ValueError):
    pass


def _real(path: Path, *, directory: bool = True) -> Path:
    if not path.is_absolute() or any(path_is_link_or_reparse(part) for part in (path, *path.parents)):
        raise AuthoringLaunchError('Authoring ownership paths must be absolute without aliases')
    result = path.resolve(strict=True)
    if not (result.is_dir() if directory else result.is_file()):
        raise AuthoringLaunchError('Authoring ownership path has the wrong filesystem kind')
    return result


def _executable(path: Path) -> Path:
    result = path.resolve(strict=True)
    if not result.is_file() or not os.access(result, os.X_OK):
        raise AuthoringLaunchError(f'Authoring preparation tool is not executable: {path}')
    return result


@dataclass
class OwnedMacAuthoringContext:
    bundle: Path
    cx: Path
    owned_root: Path
    project: Path
    home: Path
    prefix: Path
    installed: Path
    build: str
    environment: dict[str, str]
    receipts: list[dict] = field(default_factory=list)

    def _run(self, command: list[str], *, timeout: int) -> str:
        try:
            result = subprocess.run(command, env=self.environment, cwd=str(self.owned_root),
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', errors='strict',
                timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            self.receipts.append({'argv': command, 'error': {'type': type(exc).__name__, 'message': str(exc)[:2048]}})
            raise AuthoringLaunchError('Owned Authoring preparation failed') from exc
        stdout, stderr = result.stdout or '', result.stderr or ''
        self.receipts.append({'argv': command, 'exit_code': result.returncode,
                              'stdout': stdout[:16384], 'stderr': stderr[:16384]})
        if result.returncode != 0 or len(stdout.encode('utf-8')) > 16384 or len(stderr.encode('utf-8')) > 16384:
            raise AuthoringLaunchError('Owned Authoring preparation returned a failed or oversized result')
        return stdout

    def prepare(self) -> tuple[list[str], dict]:
        support = self.home / 'Library/Application Support/Wwise2019'
        support.mkdir(parents=True, exist_ok=True)
        builtin = support / 'BuiltinBottles'
        if os.path.lexists(builtin):
            raise AuthoringLaunchError('Owned Authoring BuiltinBottles already exists')
        builtin.symlink_to(self.cx / 'support', target_is_directory=True)
        self.prefix.parent.mkdir(parents=True, exist_ok=True)
        self._run([str(self.cx / 'bin/wineprefixcreate'), '--copy', str(self.prefix)], timeout=120)
        self._run([str(self.bundle / 'Contents/SharedSupport/Wwise/bin/wwise_prepare')], timeout=60)
        installed_link = self.prefix / 'drive_c/Program Files/Audiokinetic' / ('Wwise ' + self.build)
        if not installed_link.is_symlink() or installed_link.resolve(strict=True) != self.installed:
            raise AuthoringLaunchError('Owned Authoring installation link does not match the pinned installation')
        native = self._run([str(self.cx / 'bin/wine'), str(self.cx / 'lib/wine/x86_64-windows/winepath.exe'), '-w', str(self.project)], timeout=10).strip()
        if len(native.splitlines()) != 1 or not PureWindowsPath(native).is_absolute():
            raise AuthoringLaunchError('Owned Authoring native project mapping is invalid')
        roundtrip = self._run([str(self.cx / 'bin/wine'), str(self.cx / 'lib/wine/x86_64-windows/winepath.exe'), '-u', native], timeout=10).strip()
        if len(roundtrip.splitlines()) != 1 or _real(Path(roundtrip), directory=False) != self.project:
            raise AuthoringLaunchError('Owned Authoring project path roundtrip differs from the sandbox')
        resolution = self._require_bottle_resolution()
        # Retained owned 2024/2025 readiness proves this direct-Wine strategy.
        # Native-app macdrv/wait-child options belong to its enclosing app strategy.
        # The validated environment retains the logical private/managed bottle.
        command = [str(self.cx / 'bin/wine'), 'start.exe', '/wait',
            f'c:/Program Files/Audiokinetic/Wwise {self.build}/Authoring/x64/Release/bin/Wwise.exe', native]
        requested_startup_environment = {key: self.environment[key] for key in ('AK_AUTOMATION_MODE',)
            if key in self.environment}
        return command, {'method': 'owned_winepath_roundtrip', 'project': str(self.project), 'native_project': native,
                         **({'requested_startup_environment': requested_startup_environment} if requested_startup_environment else {}),
                         'roundtrip_project': str(self.project), 'build': self.build, 'bottle_resolution': resolution}

    def _require_bottle_resolution(self) -> dict:
        builtin = self.home / 'Library/Application Support/Wwise2019/BuiltinBottles'
        expected = {'HOME': str(self.home), 'WINEPREFIX': str(self.prefix), 'CX_BOTTLE': 'Wwise2019x64',
            'CX_BOTTLE_PATH': str(self.prefix.parent), 'CX_MANAGED_BOTTLE_PATH': str(builtin)}
        if any(self.environment.get(key) != value for key, value in expected.items()):
            raise AuthoringLaunchError('Owned Authoring bottle resolution environment differs')
        if not builtin.is_symlink() or builtin.resolve(strict=True) != self.cx / 'support':
            raise AuthoringLaunchError('Owned Authoring managed bottle mapping differs')
        managed = _real(self.cx / 'support/Wwise2019x64')
        _real(managed / 'system.reg', directory=False)
        managed_config = _real(managed / 'cxbottle.conf', directory=False)
        if _real(self.prefix) != self.prefix:
            raise AuthoringLaunchError('Owned Authoring private bottle mapping differs')
        _real(self.prefix / 'system.reg', directory=False)
        config = (self.prefix / 'cxbottle.conf').resolve(strict=True)
        if not config.is_file() or (config != managed_config and config != self.prefix / 'cxbottle.conf'):
            raise AuthoringLaunchError('Owned Authoring bottle configuration is outside its owned or matching managed scope')
        return {'name': 'Wwise2019x64', 'private_prefix': str(self.prefix), 'managed_reference': str(managed),
            'configuration': str(config), 'environment': expected}


def owned_mac_authoring_context(*, console: Path, project: Path | None, owned_root: Path | None,
                                build: str | None, environment: dict[str, str] | None) -> OwnedMacAuthoringContext:
    if sys.platform != 'darwin':
        raise AuthoringLaunchError('Owned Authoring launch strategy requires Mac; native Windows ownership proof remains required')
    if not isinstance(build, str) or not re.fullmatch(r'202[1-5]\.1\.\d+\.\d+', build):
        raise AuthoringLaunchError('Authoring launch requires an exact supported build')
    if project is None or owned_root is None or environment is None:
        raise AuthoringLaunchError('Authoring launch requires a private owned project, root and user environment')
    console = _real(console, directory=False)
    if console.name != 'WwiseConsole.sh' or console.parent.name != 'Tools' or console.parent.parent.name != 'Contents':
        raise AuthoringLaunchError('Authoring launch requires the selected bundle Console entrypoint')
    bundle = console.parents[2]
    with (bundle / 'Contents/Info.plist').open('rb') as stream:
        if plistlib.load(stream).get('CFBundleVersion') != build:
            raise AuthoringLaunchError('Authoring bundle build differs from the pinned native build')
    root, project = _real(owned_root), _real(project, directory=False)
    home = _real(Path(environment.get('HOME', '')))
    if (not home.is_relative_to(root) or home == root or not project.is_relative_to(root)
            or project.suffix.casefold() != '.wproj'):
        raise AuthoringLaunchError('Authoring project and private HOME must belong to the owned root')
    prefix = home / 'Library/Application Support/Wwise2019/Bottles/Wwise2019x64'
    if environment.get('WINEPREFIX') != str(prefix) or os.path.lexists(prefix):
        raise AuthoringLaunchError('Authoring requires a fresh default bottle under its private HOME')
    if any(path_is_link_or_reparse(path) for path in prefix.parents if path.exists()):
        raise AuthoringLaunchError('Authoring private prefix contains an aliased parent')
    cx = bundle / 'Contents/SharedSupport/Wwise2019x64'
    for name in ('wine', 'wineprefixcreate', 'wineloader64', 'wineserver'):
        _executable(cx / 'bin' / name)
    # The matching CrossOver bundles ship this as a Windows program, not
    # a host bin/winepath command. Use the same selected Wine and private prefix.
    try:
        _executable(_real(cx / 'lib/wine/x86_64-windows/winepath.exe', directory=False))
    except OSError as exc:
        raise AuthoringLaunchError('Required bundled winepath.exe is unavailable') from exc
    _executable(bundle / 'Contents/SharedSupport/Wwise/bin/wwise_prepare')
    installed = (MACOS_AUTHORING_INSTALL_ROOT / ('Wwise ' + build)).resolve(strict=True)
    if not (installed / 'Authoring/x64/Release/bin/Wwise.exe').is_file():
        raise AuthoringLaunchError('Pinned Authoring installation is unavailable')
    env = dict(environment)
    for key in ('AK_AUTHORING_ARGS_OVERRIDE', 'CX_ENV', 'WINE_WAIT_CHILD_PIPE'):
        env.pop(key, None)
    env.update(HOME=str(home), WINEPREFIX=str(prefix), CX_DEBUGMSG='-all', LD_PRELOAD='',
        CX_MANAGED_BOTTLE_PATH=str(home / 'Library/Application Support/Wwise2019/BuiltinBottles'),
        DYLD_LIBRARY_PATH=str(cx / 'lib'), CX_APP_BUNDLE_PATH=str(bundle), WINELOADER=str(cx / 'bin/wineloader64'),
        CX_BOTTLE='Wwise2019x64', CX_BOTTLE_PATH=str(prefix.parent), PYTHONPATH=str(cx / 'lib/python'),
        WINELOADERNOEXEC='1', CX_ROOT=str(cx), WINESERVER=str(cx / 'bin/wineserver'),
        CX_INITIALIZED='1043406810:wwise', __CHECKFIX1436934='1', WINEDEBUG='-all', VERSIONER_PERL_PREFER_32_BIT='yes',
        PULSE_LATENCY_MSEC='20', WINEDLLPATH=str(cx / 'lib/wine'), PATH=environment.get('PATH', os.defpath) + os.pathsep + str(cx / 'bin'))
    return OwnedMacAuthoringContext(bundle, cx, root, project, home, prefix, installed, build, env)

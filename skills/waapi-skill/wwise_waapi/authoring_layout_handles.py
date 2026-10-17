"""Bounded, session-bound read capabilities for Authoring layout identities."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse

_HANDLE = re.compile(r'^lh1-[0-9a-f]{32}$')
_MAX_RECORD_BYTES = 300 * 1024
_MAX_RECORDS = 4096
HANDLE_TTL_SECONDS = 900
_MAX_EXPIRED_RECLAIMS = 64


class LayoutHandleError(ValueError):
    pass


class LayoutHandleStore:
    """Opaque identities never replace live scope and exact-row revalidation."""

    def __init__(self, state_dir: Path):
        self.root = state_dir / 'authoring-layout-handles-v1'
        for path in [*reversed(self.root.parents), self.root]:
            if path.exists():
                if path_is_link_or_reparse(path) or not path.is_dir():
                    raise LayoutHandleError('Layout handle storage rejects links and non-directories')
            else:
                path.mkdir(mode=0o700)

    def issue(self, *, context: Mapping[str, Any], layout_name: str, role: str,
              native_id: str, observation: Mapping[str, Any]) -> str:
        if self._at_capacity():
            self._reclaim_expired()
            if self._at_capacity():
                raise LayoutHandleError('Layout handle store reached its bounded record ceiling')
        handle = 'lh1-' + secrets.token_hex(16)
        body = {'contract': 'waapi-skill.authoring-layout-handle/v1', 'handle': handle,
                'context': dict(context), 'layout_name': layout_name, 'role': role,
                'native_id': native_id, 'observation': dict(observation),
                'expires_at': time.time() + HANDLE_TTL_SECONDS}
        encoded = canonical_json_bytes({**body, 'sha256': canonical_sha256(body)})
        if len(encoded) > _MAX_RECORD_BYTES:
            raise LayoutHandleError('Layout handle observation exceeds its byte ceiling')
        path = self.root / (handle + '.json')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return handle

    def _at_capacity(self) -> bool:
        for index, _ in enumerate(self.root.iterdir()):
            if index >= _MAX_RECORDS - 1:
                return True
        return False

    def _reclaim_expired(self) -> None:
        """Reclaim bounded, intact expired capabilities; preserve everything else."""
        fields = {'contract', 'handle', 'context', 'layout_name', 'role', 'native_id', 'observation', 'expires_at', 'sha256'}
        reclaimed = 0
        now = time.time()
        for index, path in enumerate(self.root.iterdir()):
            if index >= _MAX_RECORDS or reclaimed >= _MAX_EXPIRED_RECLAIMS:
                break
            if not path.name.endswith('.json') or not _HANDLE.fullmatch(path.name[:-5]) or path_is_link_or_reparse(path):
                continue
            try:
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                with os.fdopen(descriptor, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_RECORD_BYTES:
                        continue
                    payload = json.loads(stream.read(_MAX_RECORD_BYTES + 1))
                if not isinstance(payload, dict) or set(payload) != fields:
                    continue
                digest = payload.pop('sha256')
                expiry = payload['expires_at']
                if (canonical_sha256(payload) != digest
                        or payload['contract'] != 'waapi-skill.authoring-layout-handle/v1'
                        or payload['handle'] != path.name[:-5]
                        or payload['role'] not in {'layout', 'element', 'view'}
                        or not isinstance(payload['context'], dict) or not isinstance(payload['observation'], dict)
                        or not isinstance(payload['layout_name'], str) or not isinstance(payload['native_id'], str)
                        or type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry >= now):
                    continue
                current = path.stat(follow_symlinks=False)
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                    continue
                path.unlink()
                reclaimed += 1
            except (OSError, ValueError, TypeError):
                # Unknown/malformed records remain available for inspection; never delete them.
                continue

    def resolve(self, handle: str, *, context: Mapping[str, Any], role: str) -> dict[str, Any]:
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle):
            raise LayoutHandleError('Expected one Gateway-issued layout identity handle')
        path = self.root / (handle + '.json')
        if path_is_link_or_reparse(path):
            raise LayoutHandleError('Layout identity handle record rejects links/reparse points')
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_RECORD_BYTES:
                    raise LayoutHandleError('Layout identity handle is not a bounded regular file')
                payload = json.loads(stream.read(_MAX_RECORD_BYTES + 1))
        except (OSError, ValueError) as exc:
            raise LayoutHandleError('Layout identity handle is missing or malformed; inspect the layout again') from exc
        fields = {'contract', 'handle', 'context', 'layout_name', 'role', 'native_id', 'observation', 'expires_at', 'sha256'}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise LayoutHandleError('Malformed layout identity handle record')
        digest = payload.pop('sha256')
        if (canonical_sha256(payload) != digest or payload['handle'] != handle
                or payload['contract'] != 'waapi-skill.authoring-layout-handle/v1'
                or payload['role'] != role or payload['context'] != dict(context)):
            raise LayoutHandleError('Layout identity handle role or live session/configuration/project context drifted')
        expiry = payload['expires_at']
        if type(expiry) not in (int, float) or not time.time() < expiry <= time.time() + HANDLE_TTL_SECONDS:
            raise LayoutHandleError('Layout identity handle expired; inspect the layout again')
        if not isinstance(payload['layout_name'], str) or not isinstance(payload['native_id'], str) or not isinstance(payload['observation'], dict):
            raise LayoutHandleError('Malformed layout identity handle binding')
        return payload

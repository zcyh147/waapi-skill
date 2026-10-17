"""Durable ownership receipts for Gateway-created Authoring resources."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse

RESOURCE_PATTERN = r'ar1-[0-9a-f]{32}'
MAX_RESOURCE_BYTES = 512 * 1024
MAX_RESOURCES = 4096


class AuthoringResourceStore:
    def __init__(self, state_dir: Path):
        self.root = state_dir / 'authoring-resources-v1'
        for path in [*reversed(self.root.parents), self.root]:
            if path.exists():
                if path_is_link_or_reparse(path) or not path.is_dir():
                    raise ValueError('Authoring resource storage rejects links and non-directories')
            else:
                path.mkdir(mode=0o700)

    def _path(self, handle: str) -> Path:
        if not isinstance(handle, str) or not re.fullmatch(RESOURCE_PATTERN, handle):
            raise ValueError('Expected an exact Gateway-issued Authoring resource handle')
        return self.root / (handle + '.json')

    def issue(self, *, transaction_id: str, context: Mapping[str, Any], kind: str,
              native_id: str, description: Mapping[str, Any], parents: list[str]) -> dict[str, Any]:
        handle = 'ar1-' + canonical_sha256({'transaction': transaction_id, 'kind': kind})[:32]
        record = {'contract': 'waapi-skill.authoring-resource/v1', 'handle': handle,
                  'context': dict(context), 'kind': kind, 'native_id': native_id,
                  'description': dict(description), 'parents': list(parents),
                  'transaction_id': transaction_id, 'status': 'active'}
        path = self._path(handle)
        if path.exists():
            existing = self.resolve(handle, context=context, kind=kind)
            if existing != record:
                raise ValueError('Creation receipt conflicts with an existing resource; never recreate it')
            return existing
        if sum(1 for _ in self.root.iterdir()) >= MAX_RESOURCES:
            raise ValueError('Authoring owned-resource store reached its record ceiling; retain evidence and close owned resources')
        self._write(path, record, exclusive=True)
        return record

    def _write(self, path: Path, record: Mapping[str, Any], *, exclusive: bool = False) -> None:
        payload = canonical_json_bytes({**record, 'sha256': canonical_sha256(record)})
        if len(payload) > MAX_RESOURCE_BYTES:
            raise ValueError('Authoring resource exceeds its bounded receipt size')
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
        # A consumed resource remains evidence and never becomes reusable.
        flags |= os.O_EXCL if exclusive else os.O_TRUNC
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def resolve(self, handle: str, *, context: Mapping[str, Any], kind: str | None = None,
                _ancestors: frozenset[str] = frozenset()) -> dict[str, Any]:
        if handle in _ancestors or len(_ancestors) > 4:
            raise ValueError('Authoring resource parent graph is invalid')
        path = self._path(handle)
        if path_is_link_or_reparse(path):
            raise ValueError('Authoring resource receipt cannot be a link')
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RESOURCE_BYTES:
                    raise ValueError('Authoring resource receipt is not a bounded regular file')
                record = json.loads(stream.read(MAX_RESOURCE_BYTES + 1))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError('Authoring resource is missing or its ownership receipt is invalid') from exc
        if not isinstance(record, dict):
            raise ValueError('Authoring resource receipt must be an object')
        digest = record.pop('sha256', None)
        if (canonical_sha256(record) != digest or record.get('handle') != handle
                or record.get('contract') != 'waapi-skill.authoring-resource/v1'
                or record.get('context') != context or record.get('status') != 'active'
                or (kind is not None and record.get('kind') != kind)
                or not isinstance(record.get('parents'), list)):
            raise ValueError('Authoring resource is closed, stale, wrong-kind or belongs to another configuration/host/session/project')
        for parent in record['parents']:
            self.resolve(parent, context=context, _ancestors=_ancestors | {handle})
        return record

    def consume(self, handle: str, *, context: Mapping[str, Any], transaction_id: str) -> None:
        record = self.resolve(handle, context=context)
        self._write(self._path(handle), {**record, 'status': 'consumed', 'consumed_by': transaction_id})

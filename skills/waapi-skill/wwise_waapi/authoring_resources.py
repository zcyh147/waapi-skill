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
            self.finish_creation(transaction_id)
            return existing
        if sum(1 for _ in self.root.iterdir()) >= MAX_RESOURCES:
            raise ValueError('Authoring owned-resource store reached its record ceiling; retain evidence and close owned resources')
        self._write(path, record, exclusive=True)
        self.finish_creation(transaction_id)
        return record

    def _write(self, path: Path, record: Mapping[str, Any], *, exclusive: bool = False) -> None:
        payload = canonical_json_bytes({**record, 'sha256': canonical_sha256(record)})
        if len(payload) > MAX_RESOURCE_BYTES:
            raise ValueError('Authoring resource exceeds its bounded receipt size')
        from .transactions import _atomic_write_json
        if path.exists() or path.is_symlink():
            raise ValueError('An immutable Authoring ownership receipt already exists')
        # All publishers hold the existing cross-process execution lease.
        # The repository atomic writer fsyncs its private temporary file and
        # replaces only after the complete document has been persisted.
        _atomic_write_json(path, {**record, 'sha256': canonical_sha256(record)})

    def resolve(self, handle: str, *, context: Mapping[str, Any], kind: str | None = None,
                _ancestors: frozenset[str] = frozenset()) -> dict[str, Any]:
        if handle in _ancestors or len(_ancestors) > 4:
            raise ValueError('Authoring resource parent graph is invalid')
        path = self._path(handle)
        if (self.root / (handle + '.consumed.json')).exists() or (self.root / (handle + '.consumed.json')).is_symlink():
            raise ValueError('Authoring resource was consumed by a prior close/destroy attempt; its native outcome cannot be replayed')
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

    def require_no_children(self, handle: str, *, context: Mapping[str, Any]) -> None:
        self.resolve(handle, context=context)
        for index, path in enumerate(self.root.iterdir()):
            if index >= MAX_RESOURCES:
                raise ValueError('Owned-resource inventory exceeds its bounded ceiling')
            if path.name.startswith('pending-') and path.name.endswith('.json'):
                pending = self._read(path)
                resolved = self.root / path.name.replace('pending-', 'resolved-', 1)
                complete = False
                if resolved.exists() or resolved.is_symlink():
                    marker = self._read(resolved)
                    if marker != {'transaction_id': pending['transaction_id'], 'ownership_receipt_persisted': True}:
                        raise ValueError('Frontend ownership resolution marker is invalid')
                    complete = True
                if pending['context'] == context and handle in pending['parents'] and not complete:
                    raise ValueError('A frontend creation still has unresolved cleanup ownership; recover its creation transaction or retain the unknown outcome')
                continue
            if not path.name.endswith('.json') or not re.fullmatch(RESOURCE_PATTERN, path.name[:-5]):
                continue
            # Every owned receipt is integrity checked before it can affect close ordering.
            try:
                row = self.resolve(path.name[:-5], context=context)
            except ValueError:
                # A consumed or previous-session receipt is retained evidence.
                row = self._read(path)
                if row.get('context') != context or (self.root / (row['handle'] + '.consumed.json')).exists():
                    continue
                raise
            if handle in row['parents']:
                raise ValueError('Destroy the owned frontend models before closing their owning window')

    def reserve_creation(self, transaction_id: str, *, parents: list[str], context: Mapping[str, Any]) -> None:
        for parent in parents: self.resolve(parent, context=context)
        path = self.root / ('pending-' + canonical_sha256(transaction_id) + '.json')
        record = {'transaction_id': transaction_id, 'parents': list(parents), 'context': dict(context)}
        self._write(path, record, exclusive=True)

    def finish_creation(self, transaction_id: str) -> None:
        token = canonical_sha256(transaction_id)
        pending = self.root / ('pending-' + token + '.json')
        resolved = self.root / ('resolved-' + token + '.json')
        if pending.exists() and not resolved.exists():
            self._write(resolved, {'transaction_id': transaction_id, 'ownership_receipt_persisted': True}, exclusive=True)

    def lease(self):
        from .transactions import TransactionStore
        return TransactionStore(self.root / 'lifetime-lease').execution_lease('authoring-resources')

    def _read(self, path: Path) -> dict[str, Any]:
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
            raise ValueError('Authoring ownership receipt is missing or invalid') from exc
        if not isinstance(record, dict): raise ValueError('Authoring ownership receipt must be an object')
        digest = record.pop('sha256', None)
        if canonical_sha256(record) != digest:
            raise ValueError('Authoring ownership receipt digest mismatch')
        return record

    def consume(self, handle: str, *, context: Mapping[str, Any], transaction_id: str) -> None:
        self.resolve(handle, context=context)
        self._write(self.root / (handle + '.consumed.json'), {'handle': handle, 'context': dict(context),
            'consumed_by': transaction_id, 'outcome': 'dispatch_reserved_once'}, exclusive=True)

"""Lossless delivery of one bounded retained WAL observation."""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from .wal_peak_observations import NativePageLocator, parse_native_page
from .media_pool_continuation import MediaPoolContinuationError
from .metadata_detail import detail_entries


def wal_read_contract(*, native_limit: int, maximum: int) -> dict[str, Any]:
    return {'contract': 'waapi-skill.wal-read/v1',
        'page_size': {'arguments': ['--max-nodes', f'<1..{maximum}>'], 'default': 128,
            'minimum': 1, 'maximum': maximum,
            'meaning': 'Maximum node summaries for a small complete reply, or document fragments per page; byte limits may reduce each page'},
        'continuation': {'argument': '--wal-page', 'source_field': 'agent_result.next_command',
            'copy_exactly': True, 'expires_after_seconds': 900,
            'binding': ['page_size', 'selected_configuration', 'endpoint', 'all_available_getInfo_facts', 'available_project_identity', 'complete_native_result'],
            'context_change': 'A changed context or invalid locator requires a new original read'},
        'delivery': {'preserves_all_native_fields': True, 'mutation_authority': False,
            'native_transport_limit_bytes': native_limit, 'page_projection_limit_bytes': 16 * 1024,
            'small_reply': 'agent_result.native_result is the complete native document',
            'paged_reply': 'Concatenate native_result_fragments value strings in page/offset order, then parse the single JSON document',
            'ordering': 'Canonical object keys; native array order and values preserved',
            'completion': 'observation_complete requires every preceding fragment from the same observation',
            'scope': 'One retained historical native reply; the current binding is checked before later pages',
            'optional_host_ids': 'May be absent; presence and every available value must remain unchanged',
            'transport_failure': 'Explicit bounded resource failure; no native absence claim'}}


class WalContinuationError(ValueError):
    code = 'WAL_CONTINUATION_CHANGED'


class WalProjectionLimitError(WalContinuationError):
    code = 'WAL_PROJECTION_LIMIT_EXCEEDED'


def parse_wal_page(token: str) -> NativePageLocator:
    try:
        return parse_native_page(token, kind="wal2", maximum_offset=1024 * 1024)
    except MediaPoolContinuationError as exc:
        raise WalContinuationError(str(exc)) from exc


def inline_wal_result(raw: Mapping[str, Any], normalized: Mapping[str, Any]) -> dict[str, Any] | None:
    if normalized['possibly_truncated']:
        return None
    inline = {**normalized, 'native_result': raw, 'observation_complete': True}
    if len(json.dumps(inline, ensure_ascii=False, indent=2).encode('utf-8')) <= 12 * 1024:
        return inline
    return None


def finish_wal_page(document: str, *, offset: int, observed_at: int, result_sha256: str,
                    total_count: int | None, take: int,
                    next_command: Callable[[int], Mapping[str, Any]]) -> dict[str, Any]:
    # Fragment the canonical document itself: even an enormous native key fits
    # without repeating it in every descendant JSON pointer. Arrays stay ordered.
    entries = detail_entries(document)
    if not 0 <= offset < len(entries):
        raise WalContinuationError('WAL page position is outside this exact observation')
    end = min(len(entries), offset + min(take, 32))
    while True:
        complete = end == len(entries)
        result = {'nodes': [], 'returned_count': 0, 'total_count': total_count,
            'take': take, 'node_summaries_complete': False,
            'native_result_fragments': entries[offset:end],
            'entries_encoding': 'json-document-fragments',
            'entry_reconstruction': 'Concatenate value strings in page/offset order, then parse the single JSON document; all native keys and values remain exact',
            'observation_complete': complete,
            'page': {'offset': offset, 'next_offset': end, 'total_positions': len(entries),
                'position_unit': 'canonical JSON document string fragments with exact character offsets',
                'native_read': 'retained_historical_observation',
                'observed_at_unix_seconds': observed_at,
                'observation_scope': 'one bounded native reply',
                'completion_requires_all_preceding_fragments': True,
                'native_result_sha256': result_sha256, 'expires_at': observed_at + 900, 'mutation_authority': False}}
        if not complete:
            result['next_command'] = dict(next_command(end))
        if len(json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')) <= 16 * 1024:
            return result
        if end <= offset + 1:
            raise WalProjectionLimitError('One WAL fragment exceeds the bounded output envelope')
        end = offset + max(1, (end - offset) // 2)

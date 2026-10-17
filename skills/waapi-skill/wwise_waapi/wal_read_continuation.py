"""Lossless WAL delivery using the existing bounded reread/fragment pattern.

The native call has no offset. Each page repeats exactly that closed read and
checks the whole observation. Locators grant no mutation authority.
"""
from __future__ import annotations

import hmac
import json
import time
from typing import Any, Callable, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .metadata_detail import detail_entries


def wal_read_contract(*, native_limit: int, maximum: int) -> dict[str, Any]:
    return {'contract': 'waapi-skill.wal-read/v1',
        'page_size': {'arguments': ['--max-nodes', f'<1..{maximum}>'], 'default': 128,
            'minimum': 1, 'maximum': maximum,
            'meaning': 'Maximum node summaries for a small complete reply, or document fragments per page; byte limits may reduce each page'},
        'continuation': {'argument': '--wal-page', 'source_field': 'agent_result.next_command',
            'copy_exactly': True, 'expires_after_seconds': 900,
            'binding': ['page_size', 'selected_configuration', 'endpoint', 'all_available_getInfo_facts', 'complete_native_result'],
            'changed_observation': 'Discard all prior fragments and restart the original read'},
        'delivery': {'preserves_all_native_fields': True, 'mutation_authority': False,
            'native_transport_limit_bytes': native_limit, 'page_projection_limit_bytes': 16 * 1024,
            'small_reply': 'agent_result.native_result is the complete native document',
            'paged_reply': 'Concatenate native_result_fragments value strings in page/offset order, then parse the single JSON document',
            'ordering': 'Canonical object keys; native array order and values preserved',
            'completion': 'observation_complete requires every preceding fragment from the same observation',
            'scope': 'One full native reply revalidated per page; no atomic cross-call snapshot',
            'optional_host_ids': 'May be absent; presence and every available value must remain unchanged',
            'transport_failure': 'Explicit bounded resource failure; no native absence claim'}}


class WalContinuationError(ValueError):
    code = 'WAL_CONTINUATION_CHANGED'


class WalProjectionLimitError(WalContinuationError):
    code = 'WAL_PROJECTION_LIMIT_EXCEEDED'


def parse_wal_page(token: str) -> tuple[int, int, str, str, str]:
    try:
        if not isinstance(token, str) or len(token) > 512:
            raise ValueError('token bound')
        kind, stamp, position, query, context, result, digest = token.split('.')
        issued, offset = int(stamp), int(position)
        valid = (kind == 'wal1' and str(issued) == stamp and str(offset) == position
            and 0 < offset < 1024 * 1024 and issued <= time.time() <= issued + 900
            and all(len(value) == 64 and all(char in '0123456789abcdef' for char in value)
                    for value in (query, context, result, digest))
            and hmac.compare_digest(canonical_sha256(token.rsplit('.', 1)[0]), digest))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise WalContinuationError('WAL page is malformed or expired; restart the original read')
    return issued, offset, query, context, result


def prepare_wal_page(*, token: str | None, maximum: int, context: Mapping[str, Any]) -> tuple[int, int, str, str, str]:
    query = canonical_sha256({'api': 'ak.wwise.debug.getWalTree', 'max_nodes': maximum})
    scope = canonical_sha256(context)
    if token is None:
        return int(time.time()), 0, query, scope, ''
    page = parse_wal_page(token)
    if not hmac.compare_digest(page[2], query) or not hmac.compare_digest(page[3], scope):
        raise WalContinuationError('WAL page choice, configuration, endpoint, build or host session changed; restart the original read')
    return page


def finish_wal_page(page: tuple[int, int, str, str, str], *, raw: Mapping[str, Any],
                    normalized: Mapping[str, Any],
                    next_command: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    issued, offset, query, context, previous = page
    digest = canonical_sha256(raw)
    if offset and not hmac.compare_digest(previous, digest):
        raise WalContinuationError('The complete native WAL observation changed; discard prior pages and restart')
    inline = {**normalized, 'native_result': raw, 'observation_complete': True}
    if not offset and not normalized['possibly_truncated'] and len(json.dumps(inline, ensure_ascii=False, indent=2).encode('utf-8')) <= 12 * 1024:
        return inline
    # Fragment the canonical document itself: even an enormous native key fits
    # without repeating it in every descendant JSON pointer. Arrays stay ordered.
    document = canonical_json_bytes(raw).decode('utf-8')
    entries = detail_entries(document)
    if not 0 <= offset < len(entries):
        raise WalContinuationError('WAL page position is outside this exact observation')
    end = min(len(entries), offset + min(normalized['take'], 32))
    while True:
        complete = end == len(entries)
        result = {'nodes': [], 'returned_count': 0, 'total_count': normalized['total_count'],
            'take': normalized['take'], 'node_summaries_complete': False,
            'native_result_fragments': entries[offset:end],
            'entries_encoding': 'json-document-fragments',
            'entry_reconstruction': 'Concatenate value strings in page/offset order, then parse the single JSON document; all native keys and values remain exact',
            'observation_complete': complete,
            'page': {'offset': offset, 'next_offset': end, 'total_positions': len(entries),
                'position_unit': 'canonical JSON document string fragments with exact character offsets',
                'native_read': 'repeat_same_bounded_read_and_verify_entire_result',
                'observation_scope': 'one full reply revalidated per page; no atomic cross-call snapshot',
                'completion_requires_all_preceding_fragments': True,
                'native_result_sha256': digest, 'expires_at': issued + 900, 'mutation_authority': False}}
        if not complete:
            unsigned = f'wal1.{issued}.{end}.{query}.{context}.{digest}'
            result['next_command'] = dict(next_command(unsigned + '.' + canonical_sha256(unsigned)))
        if len(json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')) <= 16 * 1024:
            return result
        if end <= offset + 1:
            raise WalProjectionLimitError('One WAL fragment exceeds the bounded output envelope')
        end = offset + max(1, (end - offset) // 2)

"""Explicit public Topic views; reflected native schemas remain immutable."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_sha256
from .schema_inventory import SchemaInventoryError, topic_publish_schema


NOTES_TOPIC = 'ak.wwise.core.object.structureChanged'
NOTES_SCHEMA_SHA256 = 'cc6b46578244813850fb27e64d658756676f8cd5e4340ab501052e20cf08c5d4'
_NATIVE_ROOT = Path(__file__).resolve().parents[1] / 'resources/native-catalog'
_HOST_CATALOG_SHA256 = {
    'wwise-console': 'd0135cdd7e53ead98c50b6dc7f6be161d212a7d1feb9b2e52daf38e63acb6e1d',
    'wwise-authoring': 'b7602cd4e66c008fb80b321ef1841a0d61386f1d31fe9710ff268198b94fe906',
}


@lru_cache(maxsize=2)
def _attest_notes_source(host: str, raw: bytes) -> None:
    # Cache by exact immutable bytes, never path/mtime or host alone.
    if hashlib.sha256(raw).hexdigest() != _HOST_CATALOG_SHA256[host]:
        raise SchemaInventoryError(f'Notes public compatibility source changed for {host}; review required')
    catalog = json.loads(raw)
    if (catalog['version'] != '2025.1' or catalog['provenance']['host'] != host
            or catalog['provenance']['build'] != '2025.1.7.9143'
            or canonical_sha256(catalog['schemas'][NOTES_TOPIC]) != NOTES_SCHEMA_SHA256):
        raise SchemaInventoryError(f'Notes public compatibility schema changed for {host}; review required')


def public_topic_publish_schema(
    version: str, uri: str, schema: Mapping[str, Any], *, host: str = 'wwise-console',
) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    """Share one closed construction/validation view for two observed strings.

    Native inventory walkers keep using topic_publish_schema. This view neither
    repairs arbitrary required names nor interprets string-false as a Boolean.
    """
    publish = topic_publish_schema(version, uri, schema)
    if version != '2025.1' or uri != NOTES_TOPIC:
        return publish, None
    if host not in _HOST_CATALOG_SHA256 or canonical_sha256(schema) != NOTES_SCHEMA_SHA256:
        raise SchemaInventoryError('Notes public compatibility requires the exact pinned host schema')
    try:
        for source_host in _HOST_CATALOG_SHA256:
            _attest_notes_source(source_host, (_NATIVE_ROOT / '2025.1' / (source_host + '.json')).read_bytes())
    except OSError as exc:
        raise SchemaInventoryError('Notes public compatibility source evidence unavailable') from exc
    notes = publish['properties']['objects']['items']['properties']['changes']['items']['properties']['notesChange']
    notes['properties'].update({
        'oldNotes': {'type': 'string', 'description': 'The previous notes of the object.'},
        'newNotes': {'type': 'string', 'description': 'The new notes of the object.'},
    })
    return publish, {
        'rule_id': 'structure-changed-notes-strings/v1', 'version': version, 'host': host,
        'reflected_schema_sha256': NOTES_SCHEMA_SHA256,
        'mapping': 'resources/semantic/2025.1/structure-changed-notes-compatibility.json',
        'fields': ['oldNotes', 'newNotes'], 'native_delivery_credit': False,
    }

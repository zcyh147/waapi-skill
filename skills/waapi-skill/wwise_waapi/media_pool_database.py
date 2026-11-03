"""Matching-SDK authority for database-owned anonymous directory entries."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .host_paths import HostPathError, parse_absolute_host_path

VERSION = '2025.1'
DATABASE_CLASS = 5832720
PATH_CLASS = 5898240
MEMBER = 'ak_wwise_core_object_set_example_creating_a_media_pool_database.html'
MEMBER_SHA256 = 'de5de9c1908f5dbcd810714bb1f9dc693bb05764da85a1cdd0493cc75bc5d708'
SOURCE = Path(__file__).resolve().parents[1] / 'references/semantic/2025.1/media-pool-database-sources' / MEMBER
MAX_DIRECTORY_BYTES = 4096


def authority(version):
    if version != VERSION:
        return None
    from .documented_list_fields import load_catalog, resolve_class_list_evidence
    catalog = load_catalog(version)
    evidence = resolve_class_list_evidence(version, DATABASE_CLASS, 'Paths')
    classes = {row['class_id']: row['name'] for row in catalog['classes']}
    if (hashlib.sha256(SOURCE.read_bytes()).hexdigest() != MEMBER_SHA256
            or catalog['source']['build'] != '2025.1.7.9143'
            or classes.get(DATABASE_CLASS) != 'MediaPoolDatabase'
            or evidence['declaration']['element_classes'] != [{'name': 'MediaPoolDatabasePath', 'class_id': PATH_CLASS}]
            or evidence['declaration']['unresolved_element_types']):
        raise ValueError('Media Pool database constructor lost its matching SDK/class/List authority')
    return {'contract': 'waapi-skill.media-pool-database-construction/v1', 'version': VERSION,
        'build': catalog['source']['build'], 'sdk_member': MEMBER, 'sdk_sha256': MEMBER_SHA256,
        'database_class': DATABASE_CLASS, 'path_class': PATH_CLASS, 'list': 'Paths',
        'list_source': evidence, 'native_name': '',
        'example_parent': {'id': '{8452BD49-9264-4A56-A3BB-047FA7F119BE}', 'path': r'\Databases\User Databases'},
        'directory': {'field': 'Path', 'required': True, 'absolute_host_path': True,
            'maximum_utf8_bytes': MAX_DIRECTORY_BYTES, 'purpose': 'stored_audio_directory_configuration'},
        'verification': 'exact_GUID_class_owner_membership_and_stored_Path; filesystem_scan_and_index_completion_not_claimed'}


def is_path_class(version, name, class_id):
    return version == VERSION and name == 'MediaPoolDatabasePath' and type(class_id) is int and class_id == PATH_CLASS


def certify(spec, binding):
    proof = spec.get('media_pool_database')
    if proof is None:
        return
    expected = authority(binding.get('version'))
    if (expected is None or proof != expected or binding.get('scope', {}).get('class_id') != DATABASE_CLASS
            or any(binding.get(key) != expected['list_source'][key] for key in
                ('kind', 'version', 'catalog_sha256', 'source_member', 'source_sha256', 'declaration'))
            or spec.get('class_id') != PATH_CLASS or spec.get('class_metadata') !=
                {'classId': PATH_CLASS, 'name': 'MediaPoolDatabasePath', 'type': 'Inner'}):
        raise ValueError('Anonymous directory entry requires exact MediaPoolDatabase/Paths/MediaPoolDatabasePath source placement')


def validate_directory(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > MAX_DIRECTORY_BYTES:
        raise ValueError('Media Pool Path requires one nonempty absolute directory of at most 4096 UTF-8 bytes')
    try:
        parse_absolute_host_path(value, allow_trailing_separator=True)
    except HostPathError as exc:
        raise ValueError('Media Pool Path requires an absolute host directory without NUL or dot segments') from exc
    return value


def current(proof):
    try:
        return authority(proof['version']) == proof
    except (OSError, ValueError, KeyError, TypeError):
        return False

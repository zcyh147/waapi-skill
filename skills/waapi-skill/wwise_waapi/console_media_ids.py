"""Observed Wwise media-ID storage records, without native or filesystem I/O."""
from __future__ import annotations

import hashlib
import json
import re

SOURCE_TAGS = frozenset({'AudioFileSource', 'MidiFileSource', 'PluginMediaSource'})
_GUID = re.compile(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}')


def _uint(value):
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,9}', value) or int(value) > 0xffffffff:
        raise ValueError('Media storage requires a canonical uint32 identifier')
    return value


def language_id(name):
    # AK::FNVHash32::ComputeLowerCase in each matching 2021–2025 SDK:
    # FNV-1 over UTF-8 octets, ASCII A–Z folding (not Unicode casefold).
    value = 2166136261
    for octet in name.encode('utf-8'):
        value = ((value * 16777619) & 0xffffffff) ^ (octet + 32 if 65 <= octet <= 90 else octet)
    return str(value)


def _text(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('Media storage omitted a required language or filename')
    return value


def _owner(value):
    if not isinstance(value, str) or not _GUID.fullmatch(value):
        raise ValueError('Media storage omitted its exact source GUID')
    return value.upper()


def _media(node):
    _uint(node.get('ID'))
    if len(node) or node.text and node.text.strip():
        raise ValueError('MediaID contains an unestablished nested value')
    return sorted(node.attrib.items())


def compact_records(rows):
    serialized = json.dumps(sorted(rows, key=repr), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'count': len(rows), 'sha256': hashlib.sha256(serialized.encode()).hexdigest()}


def work_unit_records(document):
    """Retain exact owner, language, file and every MediaID attribute."""
    rows, descriptors, unresolved = [], [], set()
    for source in document.iter():
        lists = source.findall('MediaIDList')
        if not lists and source.tag not in SOURCE_TAGS:
            continue
        try:
            if source.tag not in SOURCE_TAGS or len(lists) > 1:
                raise ValueError('Unestablished media owner or repeated MediaIDList')
            owner = _owner(source.get('ID'))
            if source.tag == 'PluginMediaSource':
                lang_id, lang_name = _uint(source.findtext('ParentPluginID')), None
                fields = source.findall('./PropertyList/Property[@Name="DataFileName"]')
                if len(fields) != 1:
                    raise ValueError('Plugin media filename is not unique')
                field = fields[0]
                values = field.findall('./ValueList/Value')
                filename = field.get('Value') if not values else (values[0].text if len(values) == 1 and not values[0].attrib else None)
            else:
                lang_name = _text(source.findtext('Language'))
                lang_id = language_id(lang_name)
                filename = source.findtext('AudioFile' if source.tag == 'AudioFileSource' else 'MidiFile')
            filename = _text(filename)
            descriptor = [owner, lang_id, lang_name, filename]
            descriptors.append(descriptor)
            for media in (lists[0] if lists else ()):
                if media.tag != 'MediaID':
                    raise ValueError('MediaIDList contains an unestablished row')
                rows.append([*descriptor, _media(media)])
        except ValueError:
            unresolved.add('work_unit_media_owner_or_descriptor')
    return rows, descriptors, sorted(unresolved)


def mapping_records(document):
    """Parse the five-version observed central XML without guessing a wrapper."""
    if document.tag != 'WwiseDocument' or document.get('Type') != 'MediaIDs':
        return None
    if [n.tag for n in document] != ['MediaIDInfo'] or [n.tag for n in document[0]] != ['MediaIDs']:
        raise ValueError('Central media mapping has an invalid container')
    rows, seen_languages, seen_owners = [], set(), set()
    for language in document[0][0]:
        if language.tag != 'Language' or set(language.attrib) not in ({'ID'}, {'ID', 'Name'}):
            raise ValueError('Central mapping has an invalid language group')
        lang_id, name = _uint(language.get('ID')), language.get('Name')
        if name is not None and language_id(_text(name)) != lang_id:
            raise ValueError('Central mapping language name and ID disagree')
        if lang_id in seen_languages:
            raise ValueError('Central mapping repeats a language group')
        seen_languages.add(lang_id)
        seen_files = set()
        for file in language:
            if file.tag != 'File' or set(file.attrib) != {'Name'}:
                raise ValueError('Central mapping has an invalid file row')
            filename = _text(file.get('Name'))
            if filename in seen_files:
                raise ValueError('Central mapping repeats a file group')
            seen_files.add(filename)
            for source in file:
                if source.tag != 'WObject' or set(source.attrib) != {'ID'}:
                    raise ValueError('Central mapping has an invalid source row')
                owner = _owner(source.get('ID'))
                if owner in seen_owners:
                    raise ValueError('Central mapping repeats a source GUID')
                seen_owners.add(owner)
                seen_hashes, count = set(), 0
                for child in source:
                    if child.tag == 'MediaID':
                        rows.append([owner, lang_id, name, filename, _media(child)])
                        count += 1
                    elif child.tag == 'Hash' and set(child.attrib) == {'Platform', 'Value'} and not len(child):
                        platform = _text(child.get('Platform'))
                        _uint(child.get('Value'))
                        if platform in seen_hashes:
                            raise ValueError('Central mapping repeats a platform hash')
                        seen_hashes.add(platform)
                    else:
                        raise ValueError('Central mapping has an unestablished source field')
                if not count:
                    raise ValueError('Central mapping source has no MediaID')
    return rows


def project_storage_mode(document):
    fields = document.findall('./ProjectInfo/Project/PropertyList/Property[@Name="MediaIDsInSingleFile"]')
    if not fields:
        return None
    if len(fields) != 1 or fields[0].get('Type') != 'bool':
        raise ValueError('Project media storage mode is ambiguous')
    field = fields[0]
    if 'Value' in field.attrib and field.find('ValueList') is not None:
        raise ValueError('Project media storage mode has multiple value encodings')
    values = field.findall('./ValueList/Value')
    value = field.get('Value') if not values else (values[0].text if len(values) == 1 and not values[0].attrib else None)
    if value not in {'True', 'False'}:
        raise ValueError('Project media storage mode is unestablished')
    return value == 'True'

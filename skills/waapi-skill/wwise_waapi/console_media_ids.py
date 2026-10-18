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
                if 'Value' in field.attrib and field.find('ValueList') is not None:
                    raise ValueError('Plugin media filename has multiple value encodings')
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


def none_state_source(version):
    """Exact installed-build sources; no runtime help/SDK dependency or sentinel."""
    from pathlib import Path
    if version not in {'2021.1', '2022.1', '2023.1', '2024.1', '2025.1'}:
        raise ValueError('None-state source proof is pinned only for the five supported release lines')
    path = Path(__file__).resolve().parents[1] / 'resources' / 'semantic' / version / 'none_state_materialization.json'
    raw = path.read_bytes()
    if len(raw) > 32768:
        raise ValueError('None-state source proof exceeds its packaged bound')
    source = json.loads(raw)
    if source['version'] != version or source['schema'] != 'waapi-skill.none-state-materialization-sources/v1':
        raise ValueError('None-state source proof does not match this version')
    return source, {'version': version, 'installed_build': source['installed_build'],
        'resource': 'resources/semantic/' + version + '/none_state_materialization.json',
        'sha256': hashlib.sha256(raw).hexdigest(), 'xsd': source['xsd']['file']}


def _blank(node):
    return not (node.text or '').strip() and not (node.tail or '').strip()


def _reference(node, name, identity, work_unit):
    return (node is not None and set(node.attrib) in ({'Name', 'ID'}, {'Name', 'ID', 'WorkUnitID'})
        and not len(node) and _blank(node) and node.get('Name') == name
        and _canonical_guid(node.get('ID')) == identity
        and ('WorkUnitID' not in node.attrib or work_unit is not None and _canonical_guid(node.get('WorkUnitID')) == work_unit))


def _canonical_guid(value):
    if isinstance(value, str) and _GUID.fullmatch(value) and value != '{00000000-0000-0000-0000-000000000000}':
        return value.upper()
    return None


def _saved_state_object_shape(node, optional_children):
    tags = [child.tag for child in node]
    if (set(node.attrib) - {'Name', 'ID', 'ShortID', 'ExcludeFromStore'}
            or 'Name' not in node.attrib or not _canonical_guid(node.get('ID')) or not _blank(node)
            or tags != [tag for tag in optional_children if tag in tags]):
        return False
    try:
        if 'ShortID' in node.attrib:
            _uint(node.get('ShortID'))
    except ValueError:
        return False
    return True


def none_state_eligibility(documents, version):
    """Prove exact saved subscriptions; ambiguous/hidden shapes earn no allowance.

    documents is the already bounded, complete project-model observation, indexed
    by relative path. This does not predict that a save must persist any additional record or establish when a live object came into existence.
    """
    source, proof = none_state_source(version)
    nodes = [(path, node) for path, doc in documents.items() for node in doc.iter()]
    definitions = {}
    from collections import Counter
    owner_counts = Counter(_canonical_guid(node.get('ID')) for _, node in nodes
        if 'Name' in node.attrib and not node.tag.endswith('Ref'))
    work_units = {}
    for path, doc in documents.items():
        for unit in doc.iter('WorkUnit'):
            for node in unit.iter():
                work_units[id(node)] = _canonical_guid(unit.get('ID'))
    for path, node in nodes:
        if node.tag in {'StateGroup', 'State'}:
            definitions.setdefault(_canonical_guid(node.get('ID')), []).append((path, node))
    groups = {}
    for path, group in nodes:
        group_id = _canonical_guid(group.get('ID'))
        if group.tag != 'StateGroup' or not group_id or not group.get('Name') or len(definitions.get(group_id, ())) != 1:
            continue
        if (set(group.attrib) - {'Name', 'ID', 'ShortID', 'ExcludeFromStore'}
                or any(child.tag not in {'Comment', 'PropertyList', 'ChildrenList', 'TransitionList',
                    *({'ReferenceList'} if version != '2025.1' else set())} for child in group)):
            continue
        lists = group.findall('ChildrenList')
        if len(lists) != 1 or lists[0].attrib or not _blank(lists[0]):
            continue
        children = list(lists[0])
        names = [n.get('Name') for n in children]
        if (not children or any(n.tag != 'State' or not _canonical_guid(n.get('ID'))
                or len(definitions.get(_canonical_guid(n.get('ID')), ())) != 1
                or not n.get('Name') for n in children) or len(set(names)) != len(names)):
            continue
        none = [n for n in children if n.get('Name') == 'None']
        # None must itself be empty, so a hidden default override earns no proof.
        if len(none) != 1 or len(none[0]) or not _blank(none[0]) or set(none[0].attrib) - {'Name', 'ID', 'ShortID'}:
            continue
        unit_id = work_units.get(id(group))
        if unit_id is None:
            continue
        try:
            if 'ShortID' in none[0].attrib:
                _uint(none[0].get('ShortID'))
        except ValueError:
            continue
        groups[group_id] = (path, group, none[0], unit_id, children)
    bindings = []
    owners = source['xsd']['state_info_direct_owners']
    for path, owner in nodes:
        owner_id = _canonical_guid(owner.get('ID'))
        if owner.tag not in owners or not owner_id or not owner.get('Name'):
            continue
        if owner_counts[owner_id] != 1:
            continue
        infos = owner.findall('StateInfo')
        if len(infos) != 1 or infos[0].attrib or not _blank(infos[0]):
            continue
        info = infos[0]
        if any(n.tag not in {'StatePropertyList', 'StateGroupList', 'CustomStateList'} for n in info):
            continue
        if any(len(info.findall(tag)) > 1 for tag in {'StatePropertyList', 'StateGroupList', 'CustomStateList'}):
            continue
        state_properties = info.findall('StatePropertyList')
        if state_properties and (state_properties[0].attrib or not _blank(state_properties[0])
                or len(state_properties[0]) < source['xsd']['shape']['state_property_rows_min_occurs']
                or any(n.tag != 'Property' or set(n.attrib) != {'Name'} or not n.get('Name')
                    or len(n) or not _blank(n) for n in state_properties[0])):
            continue
        group_lists, custom_lists = info.findall('StateGroupList'), info.findall('CustomStateList')
        if len(group_lists) != 1 or group_lists[0].attrib or not _blank(group_lists[0]):
            continue
        if custom_lists and (custom_lists[0].attrib or not _blank(custom_lists[0])):
            continue
        refs = []
        valid = True
        for row in group_lists[0]:
            allowed_attrs = {'MusicSyncType'} if version != '2025.1' else set()
            if (row.tag != 'StateGroupInfo' or set(row.attrib) - allowed_attrs or not _blank(row)
                    or 'MusicSyncType' in row.attrib and not re.fullmatch(r'[+-]?[0-9]+', row.get('MusicSyncType'))):
                valid = False
                break
            tags = [n.tag for n in row]
            if tags != ['StateGroupRef']:
                shape = source['xsd']['shape'].get('state_group_info_object')
                if (version != '2025.1' or tags != ['StateGroupRef', 'StateGroupInfo'] or shape is None
                        or not _saved_state_object_shape(row[1], shape['optional_children'])):
                    valid = False
                    break
            ref = row[0]
            group_id = _canonical_guid(ref.get('ID'))
            group = groups.get(group_id)
            if group is None or not _reference(ref, group[1].get('Name'), group_id, group[3]):
                valid = False
                break
            refs.append(group_id)
        if not valid or len(refs) != len(set(refs)):
            continue
        all_states = { _canonical_guid(state.get('ID')): (state, group[3])
            for group_id in refs for group in [groups[group_id]] for state in group[4] }
        existing = []
        wrappers = {}
        for row in (custom_lists[0] if custom_lists else ()):
            state_refs = row.findall('StateRef')
            state_id = _canonical_guid(state_refs[0].get('ID')) if len(state_refs) == 1 else None
            state = all_states.get(state_id)
            if (row.tag != 'CustomState' or row.attrib or not _blank(row)
                    or [n.tag for n in row] not in (['StateRef'], ['StateRef', 'CustomState'])
                    or state is None or not _reference(state_refs[0], state[0].get('Name'), state_id, state[1])):
                valid = False
                break
            if len(row) == 2:
                inner = row[1]
                allowed_children = [n['ref'] for n in source['xsd']['shape']['custom_state_object_optional_children']]
                if not _saved_state_object_shape(inner, allowed_children):
                    valid = False
                    break
            existing.append(state_id)
            wrappers[state_id] = len(row) == 1
        if not valid or len(existing) != len(set(existing)):
            continue
        for group_id in refs:
            group_path, group, none, unit_id, _ = groups[group_id]
            none_id = _canonical_guid(none.get('ID'))
            if none_id not in existing or wrappers[none_id]:
                bindings.append({'file': path, 'owner': {'id': owner_id, 'type': owner.tag, 'name': owner.get('Name')},
                    'group': {'id': group_id, 'name': group.get('Name'), 'file': group_path, 'work_unit_id': unit_id},
                    'none_state': {'id': none_id, 'name': 'None'},
                    'custom_state_list_present': bool(custom_lists), 'none_wrapper_present': none_id in existing})
    return {'may_materialize_saved_internal_records': bool(bindings), 'inevitable': False,
        'force_save_scope': 'all_project_work_units', 'source': proof, 'eligible_bindings': bindings,
        'outcome': 'may_persist_zero_or_one_fresh_empty_CustomState_record_per_binding; added_saved_model_identities_reported; remaining_model_strict'}


def project_none_state_additions(documents, expected):
    """Recognize/report the disclosed additions, then project their strict remainder.

    Mutates only the local parsed verification trees, AFTER actual hashes and
    anchors were captured. Never used by generic XML equivalence. A malformed
    addition stays in the tree and therefore fails the ordinary model check.
    """
    occurrences = {}
    token = re.compile(r'(?<![0-9a-fA-F])[{]?([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})[}]?(?![0-9a-fA-F])')
    for document in documents.values():
        for node in document.iter():
            for value in [*node.attrib.values(), node.text or '', node.tail or '']:
                for match in token.finditer(value):
                    key = '{' + match[1].upper() + '}'
                    occurrences[key] = occurrences.get(key, 0) + 1
    additions = []
    for binding in expected['eligible_bindings']:
        document = documents.get(binding['file'])
        if document is None:
            continue
        owners = [n for n in document.iter(binding['owner']['type'])
            if _canonical_guid(n.get('ID')) == binding['owner']['id']]
        if len(owners) != 1:
            continue
        lists = owners[0].findall('./StateInfo/CustomStateList')
        if len(lists) != 1 or lists[0].attrib or not _blank(lists[0]):
            continue
        custom = lists[0]
        rows = [n for n in custom if any(_canonical_guid(r.get('ID')) == binding['none_state']['id'] for r in n.findall('StateRef'))]
        if len(rows) != 1:
            continue
        row = rows[0]
        if row.tag != 'CustomState' or row.attrib or not _blank(row) or [n.tag for n in row] != ['StateRef', 'CustomState']:
            continue
        ref, inner = row
        identity = _canonical_guid(inner.get('ID'))
        if (not _reference(ref, 'None', binding['none_state']['id'], binding['group']['work_unit_id'])
                or inner.tag != 'CustomState' or inner.get('Name') != '' or not identity
                or set(inner.attrib) not in ({'Name', 'ID'}, {'Name', 'ID', 'ShortID'})
                or len(inner) or not _blank(inner) or occurrences.get(identity) != 1):
            continue
        try:
            if 'ShortID' in inner.attrib:
                _uint(inner.get('ShortID'))
        except ValueError:
            continue
        additions.append({**binding, 'object': {'type': 'CustomState', 'id': identity,
            'name': '', 'short_id': inner.get('ShortID')},
            'created_custom_state_list': not binding['custom_state_list_present'],
            'created_state_ref_wrapper': not binding['none_wrapper_present']})
        if binding['none_wrapper_present']:
            row.remove(inner)
        else:
            custom.remove(row)
        if not binding['custom_state_list_present'] and not len(custom):
            owners[0].find('StateInfo').remove(custom)
    return additions


def none_state_notice(expected):
    """Deduplicate repeated targets for public review; preserve every exact owner."""
    groups = {}
    for row in expected['eligible_bindings']:
        key = (row['group']['id'], row['none_state']['id'])
        group = groups.setdefault(key, {'group': {'id': row['group']['id'], 'name': row['group']['name']},
            'none_state': row['none_state'], 'owners': []})
        group['owners'].append(row['owner'])
    return {key: value for key, value in expected.items() if key != 'eligible_bindings'} | {
        'eligible_binding_count': len(expected['eligible_bindings']),
        'eligible_groups': list(groups.values()), 'relationships_complete': True}


def none_state_outcome_page(value, *, scope, total_count, cursor=None, max_entries=64):
    """Fixed read-only lossless detail page over one already sealed local value."""
    from .canonical import canonical_json_bytes
    from .metadata_detail import detail_entries
    from .metadata_discovery import MetadataDiscoveryError, _require_result_size
    value_sha = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    rows = detail_entries(value)
    def locator(offset):
        digest = hashlib.sha256(canonical_json_bytes([scope, value_sha, offset])).hexdigest()
        return 'nso1.' + str(offset) + '.' + digest
    offset = 0
    if cursor is not None:
        try:
            _, raw_offset, _ = cursor.split('.')
            offset = int(raw_offset)
            valid = (str(offset) == raw_offset and 0 <= offset < len(rows)
                and cursor == locator(offset))
        except (ValueError, AttributeError, TypeError):
            valid = False
        if not valid:
            raise ValueError('None-state outcome page does not match this immutable transaction, artifact, view, event and value')
    end = min(len(rows), offset + min(64, max_entries))
    while True:
        result = {'contract': 'waapi-skill.transaction-none-state-outcome-page/v1',
            'scope': scope, 'value_sha256': value_sha, 'total_count': total_count,
            'entries': rows[offset:end], 'entries_encoding': 'lossless_JSON_pointer_entries_with_string_fragments',
            'offset': offset, 'total_entries': len(rows), 'remaining_entries': len(rows) - end,
            'complete': end == len(rows), 'next_page': locator(end) if end < len(rows) else None,
            'mutation_authority': False, 'limits': {'page_entries': 64, 'page_bytes': 16 * 1024}}
        try:
            _require_result_size(result, maximum_bytes=16 * 1024, pretty=True)
            return result
        except MetadataDiscoveryError:
            if end <= offset + 1:
                raise ValueError('None-state outcome entry cannot fit the existing bounded detail projection')
            end -= 1

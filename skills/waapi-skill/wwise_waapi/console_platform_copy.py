"""Saved platform-copy semantics, pinned by platform-copy-sources.json per lane.

Only new Conversion-owned codec object identities are copy-local. Existing model
preservation and every other GUID remain the Console effect owner's concern.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from .conversion_plugin import ConversionPluginError, _guid


# WObjects SoundbanksSettings/Properties with SupportLink=true in all five
# pinned definitions. Help's platform-copy list excludes these Project tabs.
PROJECT_COPY_EXCLUSIONS = frozenset({
    'SoundBankPaths', 'SoundBankPreGenerateCustomCmdDescription',
    'SoundBankPreGenerateCustomCmdLines', 'SoundBankPostGenerateCustomCmdDescription',
    'SoundBankPostGenerateCustomCmdLines', 'ExternalSourcesInputPath',
    'ExternalSourcesOutputPath',
})


def _identity(value):
    try:
        return _guid(value)
    except ConversionPluginError:
        return None


class PlatformCopyObservation:
    def __init__(self, platforms, project_relative):
        self.project_relative = project_relative
        self.identities = Counter()
        self.platforms = {name: {'settings': {}, 'codec_ids': [],
            'codec_shapes_valid': True, 'codec_classes': {}, 'conversion_sample_rates': [],
            'excluded_project_settings': []} for name in platforms}

    def visit(self, node, ancestors, relative, key, value, digest):
        identity = _identity(node.get('ID'))
        if identity and node.tag not in {'ObjectRef', 'MediaID'}:
            self.identities[identity] += 1
        platform = node.get('Platform')
        if platform not in self.platforms:
            return
        observed = self.platforms[platform]
        tags = tuple(parent.tag for parent in ancestors)
        if (relative == self.project_relative
                and tags == ('WwiseDocument', 'ProjectInfo', 'Project', 'PropertyList', 'Property', 'ValueList')
                and ancestors[-2].get('Name') in PROJECT_COPY_EXCLUSIONS
                and dict(ancestors[-2].attrib) == {'Name': ancestors[-2].get('Name'), 'Type': 'string'}
                and not ancestors[-1].attrib and node.tag == 'Value'
                and set(node.attrib) == {'Platform'} and not len(node)):
            observed['excluded_project_settings'].append({'property': ancestors[-2].get('Name'),
                'type': 'string', 'value': node.text or ''})
            return
        if (node.tag == 'ConversionPluginInfo' and tags[-2:] == ('Conversion', 'ConversionPluginInfoList')):
            children = list(node)
            valid = (set(node.attrib) == {'Platform'} and not (node.text or '').strip()
                and not ancestors[-1].attrib and _identity(ancestors[-2].get('ID')) is not None
                and len(children) == 1 and children[0].tag == 'ConversionPlugin')
            codec = children[0] if valid else None
            required = {'Name', 'ID', 'PluginName', 'CompanyID', 'PluginID'}
            if codec is not None:
                valid = (required <= set(codec.attrib)
                    and set(codec.attrib) <= required | {'ShortID', 'ExcludeFromStore'}
                    and codec.get('CompanyID', '').isascii() and codec.get('CompanyID', '').isdecimal()
                    and 0 <= int(codec.get('CompanyID')) <= 4095
                    and codec.get('PluginID', '').isascii() and codec.get('PluginID', '').isdecimal()
                    and 0 <= int(codec.get('PluginID')) <= 65535)
            codec_id = _identity(codec.get('ID')) if codec is not None else None
            observed['codec_shapes_valid'] &= valid and codec_id is not None
            observed['codec_ids'].append(codec_id)
            if valid and codec_id is not None:
                observed['codec_classes'][key] = [codec.get(name) for name in ('PluginName', 'CompanyID', 'PluginID')]
                value = deepcopy(value)
                # Exact owned child only; no recursive GUID stripping, reference
                # rewriting, property omission, or codec-class normalization.
                value[3][0][1] = [(name, item) for name, item in value[3][0][1] if name != 'ID']
        if (node.tag == 'Value' and tags[-4:] == ('Conversion', 'PropertyList', 'Property', 'ValueList')
                and ancestors[-2].get('Name') in {'SampleRate', 'MinSampleRate', 'MaxSampleRate'}):
            observed['conversion_sample_rates'].append(key)
        observed['settings'].setdefault(key, []).append(digest(value))

    def finish(self):
        for observed in self.platforms.values():
            for rows in observed['settings'].values():
                rows.sort()
            observed['codec_ids'].sort(key=str)
            observed['codec_identities_valid'] = (observed.pop('codec_shapes_valid')
                and all(identity is not None and self.identities[identity] == 1 for identity in observed['codec_ids']))
            observed['excluded_project_settings'].sort(key=lambda row: (row['property'], row['value']))
        return self.platforms


def compare_platform_copy(before, after, source, target, *, cross_base=False):
    expected, actual = before[source], after[target]
    required, observed = expected['settings'], actual['settings']
    missing, extra = set(required) - set(observed), set(observed) - set(required)
    different = {key for key in set(required) & set(observed) if observed[key] != required[key]}
    fallback = {key for key in different if cross_base and (
        key in expected['codec_classes'] and key in actual['codec_classes']
        and expected['codec_classes'][key] != actual['codec_classes'][key]
        or key in expected['conversion_sample_rates'] and key in actual['conversion_sample_rates'])}
    valid_ids = expected['codec_identities_valid'] and actual['codec_identities_valid']
    return {'source_platform': source, 'target_platform': target,
        'required_entries': len(required),
        'matched_entries': sum(observed.get(key) == values for key, values in required.items()),
        'missing_entries': len(missing), 'unexpected_entries': len(extra),
        'conflicting_entries': len(different - fallback), 'codec_identities_valid': valid_ids,
        'cross_base_copy': cross_base, 'native_fallback_uncertain_entries': len(fallback),
        'target_codec_ids': actual['codec_ids'],
        'excluded_project_settings': {'source': expected['excluded_project_settings'],
            'target': actual['excluded_project_settings']}}

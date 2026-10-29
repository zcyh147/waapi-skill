"""Reviewed literal scalar packets, not recordings of native co-occurrence.

These exercise schema-valid injected callbacks only. Real object applicability,
include behavior, emission, omission and lifecycle require separate native proof.
"""
from copy import deepcopy

URI = 'ak.wwise.core.object.created'
BUILDS = {'2021.1': '2021.1.14.8108', '2022.1': '2022.1.19.8584',
          '2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}
_BASE = {
    'category': 'Containers', 'childrenCount': 0, 'convertedWemFilePath': '/injected/converted.wem',
    'filePath': '/injected/workunit.wwu', 'isPlayable': False, 'mediaSize': 0,
    'name': 'Injected café', 'notes': 'Injected notes', 'objectSize': 0,
    'originalWavFilePath': '/injected/original.wav', 'path': '\\Actor-Mixer Hierarchy\\Injected café',
    'pluginName': 'Injected plugin', 'shortId': 0, 'soundbankBnkFilePath': '/injected/bank.bnk',
    'structureSize': 0, 'totalSize': 0, 'type': 'Sound', 'workunitIsDefault': False,
    'workunitIsDirty': False, 'workunitType': 'folder',
}
_2022 = {'convertedFilePath': '/injected/converted.wem', 'originalFilePath': '/injected/original.wav',
         'isExplicitMute': False, 'isExplicitSolo': False, 'isImplicitMute': False,
         'isImplicitSolo': False, 'isIncluded': False}
_2023 = {'originalRelativeFilePath': 'Injected/original.wav'}
_2025 = {'hasEmptySwitchStateAssignment': False, 'isLanguageIncluded': False,
         'supportsStates': False, 'workunitIsLoaded': False}
# Literal alternatives deliberately distinguish sibling occurrences and scalar types.
_ALTERNATE = {
    'category': '', 'childrenCount': 1, 'convertedWemFilePath': '', 'filePath': '',
    'isPlayable': True, 'mediaSize': 1, 'name': '', 'notes': '', 'objectSize': 1,
    'originalWavFilePath': '', 'path': '', 'pluginName': '', 'shortId': 1,
    'soundbankBnkFilePath': '', 'structureSize': 1, 'totalSize': 1, 'type': '',
    'workunitIsDefault': True, 'workunitIsDirty': True, 'workunitType': 'rootFile',
    'convertedFilePath': '', 'originalFilePath': '', 'isExplicitMute': True,
    'isExplicitSolo': True, 'isImplicitMute': True, 'isImplicitSolo': True,
    'isIncluded': True, 'originalRelativeFilePath': '', 'hasEmptySwitchStateAssignment': True,
    'isLanguageIncluded': True, 'supportsStates': True, 'workunitIsLoaded': True,
}


def created_packets(version):
    if version not in BUILDS:
        raise ValueError('Unreviewed created packet version')
    fields = deepcopy(_BASE)
    if version != '2021.1':
        fields.update(_2022)
    if version in ('2023.1', '2024.1', '2025.1'):
        fields.update(_2023)
    if version == '2025.1':
        fields.update(_2025)
    return [{'object': {}}, {'object': fields},
            {'object': {key: deepcopy(_ALTERNATE[key]) for key in fields}},
            {'object': {'workunitType': 'nestedFile'}}]


def created_fields(version):
    return sorted(created_packets(version)[1]['object'])

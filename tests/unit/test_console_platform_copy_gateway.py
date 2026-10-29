"""Platform copy semantics through the public Gateway; no native process."""
from copy import deepcopy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests.unit.test_console_project_alternatives_gateway import CliProjectTask, saved_fixture_project

SOURCE_CODEC = '{33333333-3333-3333-3333-333333333333}'
TARGET_CODEC = '{44444444-4444-4444-4444-444444444444}'


class PlatformCopyTask(CliProjectTask):
    def __init__(self, path, version='2025.1', fault=None):
        super().__init__(path, version, 'ak.wwise.cli.addNewPlatform')
        self.fault = fault
        self.unit = saved_fixture_project(self)
        tree = ET.parse(self.unit)
        conversion = ET.SubElement(tree.find('.//Sound'), 'Conversion', Name='Custom',
            ID='{55555555-5555-5555-5555-555555555555}')
        infos = ET.SubElement(conversion, 'ConversionPluginInfoList')
        info = ET.SubElement(infos, 'ConversionPluginInfo', Platform='Windows')
        plugin = ET.SubElement(info, 'ConversionPlugin', Name='', ID=SOURCE_CODEC,
            PluginName='Vorbis', CompanyID='0', PluginID='4')
        ET.SubElement(ET.SubElement(plugin, 'PropertyList'), 'Property',
            Name='QualityFactor', Type='Real32', Value='3')
        if fault == 'missing-codec-class':
            del plugin.attrib['PluginName']
        if fault == 'misplaced-output':
            field = ET.SubElement(tree.find('.//Sound/PropertyList'), 'Property', Name='SoundBankPaths', Type='string')
            ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value', Platform='Windows').text = 'Keep Windows text'
        tree.write(self.unit)
        tree = ET.parse(self.project_file)
        props = ET.SubElement(tree.find('./ProjectInfo/Project'), 'PropertyList')
        for name, text in [('SoundBankPaths', r'GeneratedSoundBanks\Windows'),
                           ('ExternalSourcesOutputPath', r'External\Windows')]:
            field = ET.SubElement(props, 'Property', Name=name, Type='string')
            ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value', Platform='Windows').text = text
        tree.write(self.project_file)

    def call(self, uri, args=None, options=None):
        if uri == self.operation:
            tree = ET.parse(self.project_file)
            ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform', Name='Studio',
                ReferencePlatform=args['new-platform-base'], ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
            for field in tree.findall('./ProjectInfo/Project/PropertyList/Property'):
                if field.find('./ValueList/Value') is None:
                    continue
                copied = deepcopy(field.find('./ValueList/Value'))
                copied.set('Platform', 'Studio')
                copied.text = copied.text.replace('Windows', 'Studio')
                field.find('ValueList').append(copied)
            tree.write(self.project_file)
            tree = ET.parse(self.unit)
            for parent in list(tree.iter()):
                for child in list(parent):
                    if child.get('Platform') == 'Windows':
                        copied = deepcopy(child)
                        copied.set('Platform', 'Studio')
                        plugin = copied.find('ConversionPlugin')
                        if plugin is not None:
                            plugin.set('ID', TARGET_CODEC)
                        parent.append(copied)
            target_info = tree.find('.//ConversionPluginInfo[@Platform="Studio"]')
            target_codec = target_info.find('ConversionPlugin')
            if self.fault == 'wrong-codec':
                target_codec.set('PluginID', '1')
                target_codec.set('PluginName', 'PCM')
            elif self.fault == 'wrong-quality':
                target_codec.find('./PropertyList/Property').set('Value', '9')
            elif self.fault == 'same-guid':
                target_codec.set('ID', SOURCE_CODEC)
            elif self.fault == 'colliding-guid':
                target_codec.set('ID', '{22222222-2222-2222-2222-222222222222}')
            elif self.fault == 'invalid-guid':
                target_codec.set('ID', 'not-a-guid')
            elif self.fault == 'wrong-owner':
                target_info.set('Owner', '{77777777-7777-7777-7777-777777777777}')
            elif self.fault == 'missing-value':
                values = tree.find('.//Sound/PropertyList/Property/ValueList')
                values.remove(values.find('Value[@Platform="Studio"]'))
            elif self.fault == 'extra-value':
                ET.SubElement(tree.find('.//Sound/PropertyList/Property'), 'Value', Platform='Studio').text = '-6'
            elif self.fault == 'wrong-reference':
                target_codec.find('./PropertyList/Property').set('ID', '{77777777-7777-7777-7777-777777777777}')
            elif self.fault == 'misplaced-output':
                tree.find('.//Sound/PropertyList/Property[@Name="SoundBankPaths"]/ValueList/Value[@Platform="Studio"]').text = 'Changed Studio text'
            tree.write(self.unit)
        return super().call(uri, args, options)

    def copy(self, base='Windows'):
        return self.execute_plan('--value', 'base_platform', base, '--value', 'platform_name', 'Studio',
            '--value', 'copy_settings_from_platform', 'Windows')


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_platform_copy_preserves_settings_with_fresh_codec_and_separate_output_paths(tmp_path, version):
    task = PlatformCopyTask(tmp_path, version)
    tx = task.copy()
    code, result = task.run('verify', tx)
    assert code == 0 and result['verified'] is True, result
    observed = result['verification']['readbacks'][-1]['copy_settings']
    assert observed['required_entries'] == observed['matched_entries'] == 2
    assert observed['codec_identities_valid'] is True
    assert observed['excluded_project_settings']['target'] == [
        {'property': 'ExternalSourcesOutputPath', 'type': 'string', 'value': r'External\Studio'},
        {'property': 'SoundBankPaths', 'type': 'string', 'value': r'GeneratedSoundBanks\Studio'}]
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('fault', ['wrong-codec', 'wrong-quality', 'same-guid', 'colliding-guid',
    'invalid-guid', 'wrong-owner', 'missing-value', 'extra-value', 'wrong-reference', 'missing-codec-class',
    'misplaced-output'])
def test_platform_copy_never_accepts_changed_settings_missing_values_or_unowned_id_changes(tmp_path, fault):
    task = PlatformCopyTask(tmp_path, fault=fault)
    tx = task.copy()
    code, result = task.run('verify', tx)
    assert result['verified'] is False, result
    assert result['state'] == ('result_schema_checked' if fault == 'missing-value' else 'verification_failed'), result
    assert code == (0 if fault == 'missing-value' else 2), result
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_platform_copy_schema_discloses_scoped_source_proven_exceptions(tmp_path, version):
    task = PlatformCopyTask(tmp_path, version)
    code, schema = task.run('--version', version, 'request-schema', task.operation)
    assert code == 0, schema
    verification = schema['business_adapter']['effect_verification']
    assert verification['copied_codec_identity'] == 'fresh_unique_Conversion_owned_object_ID_only'
    source = Path(__file__).resolve().parents[2] / 'skills/waapi-skill' / verification['copy_source_evidence']
    pinned = json.loads(source.read_text())
    assert pinned['version'] == version
    assert pinned['project_copy_exclusions'] == verification['project_copy_exclusions']
    assert verification['project_copy_exclusions'] == [
        'ExternalSourcesInputPath', 'ExternalSourcesOutputPath', 'SoundBankPaths',
        'SoundBankPostGenerateCustomCmdDescription', 'SoundBankPostGenerateCustomCmdLines',
        'SoundBankPreGenerateCustomCmdDescription', 'SoundBankPreGenerateCustomCmdLines']


def test_cross_base_codec_fallback_is_unresolved_instead_of_proven_wrong_effect(tmp_path):
    task = PlatformCopyTask(tmp_path, fault='wrong-codec')
    tx = task.copy(base='Mac')
    code, result = task.run('verify', tx)
    assert code == 0 and result['state'] == 'result_schema_checked' and result['verified'] is False, result
    observation = result['verification']['readbacks'][-1]
    assert observation['copy_settings']['native_fallback_uncertain_entries'] == 1
    assert observation['unresolved'] == ['copy_settings_cross_base_native_fallback_unestablished']

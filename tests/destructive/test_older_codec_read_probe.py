"""Exact older codec read, using the existing copied-project lifecycle only."""
import hashlib
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime
from wwise_waapi.host_paths import localize_waapi_host_path


pytestmark = [pytest.mark.live, pytest.mark.destructive]
MEMBER = 'Conversion Settings/Default Work Unit.wwu'
SOURCES = {
    '2021.1': ((2021, 1, 14, 8108),
        '9738709ded6b69efe831a71f2106703ee5d7421d46856d244e1dee601a6ed726',
        'ff34b54bec62409a1e09c3467a6f000836544398bca3af33fa8d557d2c67c8be'),
    '2022.1': ((2022, 1, 19, 8584),
        '1f5403a754ccd81d48e7e330d7627385a1cc4b90abe99b7e98217035c5e42426',
        '6ef42c1b859c3ab578169079b0d01c2650da38cad44cda8a357f052fdc0b1aa7'),
    '2023.1': ((2023, 1, 19, 8928),
        '482697fa609e691831a3df166fd6791289ad3e84d864812693a140ad2fdde107',
        '6936b9719114606e3e9883afa970979b5d5105246506a14b6d939033ac0f54ce'),
}

# Original read-r1 packets establish only this exact old wrapper representation.
OLDER_WRAPPER_SOURCES = {
    '2021.1': {'observation': 'older-codec179-2021-read-r1/pytest/gateway-workflows-2021-10/state/older-codec-read-probe.json',
        'observation_sha256': 'da12a3c7d5570eb27a0da464fe708a2fc13d1865bb1061fe9055b497e5079f4b',
        'native_record_sha256': '3a054be2b3f126ebf71811c7a06fe93015a8e160faaf16795ec7ed603d52a27f'},
    '2022.1': {'observation': 'older-codec179-2022-read-r1/pytest/gateway-workflows-2022-10/state/older-codec-read-probe.json',
        'observation_sha256': '645822436713273baf10da840727216b604a4fb043ee19d5d085ba196be2c046',
        'native_record_sha256': 'd91831514fcf3b0c6c9a9ca4402f71a39f7fb10fbe29c65442fd856dec90cee5'},
}


@pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2021.1', reason='Exact 2021.1.14.8108 codec read')
def test_2021_codec_read_metadata(workflow_sandbox_runtime):
    collect_older_codec_read(workflow_sandbox_runtime)


@pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2022.1', reason='Exact 2022.1.19.8584 codec read')
def test_2022_codec_read_metadata(workflow_sandbox_runtime):
    collect_older_codec_read(workflow_sandbox_runtime)


@pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2023.1', reason='Exact 2023.1.19.8928 codec read')
def test_2023_codec_read_metadata(workflow_sandbox_runtime):
    collect_older_codec_read(workflow_sandbox_runtime)


def source_identity(source_root, version):
    """Serialized IDs select a research read only, never production mutation."""
    build, member_sha, project_sha = SOURCES[version]
    raw, project_raw = (source_root / MEMBER).read_bytes(), (source_root / 'SampleProject.wproj').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == member_sha, 'Matching Conversion Work Unit changed'
    assert hashlib.sha256(project_raw).hexdigest() == project_sha, 'Matching source project changed'
    document, project = ET.fromstring(raw), ET.fromstring(project_raw)
    owner, = [node for node in document.iter('Conversion') if node.get('Name') == 'Voice']
    codec, = owner.findall('./ConversionPluginInfoList/ConversionPluginInfo[@Platform="Mac"]/ConversionPlugin')
    platform, = [node for node in project.iter('Platform') if node.get('Name') == 'Mac']
    assert (owner.get('ID'), codec.get('ID'), platform.get('ID')) == (
        '{E9AAECFC-E18A-40E5-91F8-BFCF00FD8CAA}', '{6DBA16C0-4F5A-4268-8760-61425C95747B}',
        '{9C6217D5-DD11-4795-87C1-6CE02853C541}')
    assert codec.get('Name') == '' and codec.get('PluginName') == 'Vorbis'
    quality, = codec.findall('./PropertyList/Property[@Name="QualityFactor"]')
    assert quality.get('Type') == 'Real32' and quality.get('Value') == '3'
    unit, = document.iter('WorkUnit')
    project_object, = project.iter('Project')
    return {'build': build, 'member': MEMBER, 'member_sha256': member_sha, 'project_sha256': project_sha,
        'project_id': project_object.get('ID'), 'owner_id': owner.get('ID'), 'codec_id': codec.get('ID'),
        'platform_id': platform.get('ID'), 'codec_name': codec.get('PluginName'), 'quality_factor': 3,
        'owner_path': '\\Conversion Settings\\' + unit.get('Name') + '\\' + owner.get('Name'),
        'authority': 'source-pinned read selector only; no mutation authority or inferred live platform association'}


def collect_older_codec_read(runtime):
    output = runtime.state_dir / 'older-codec-read-probe.json'
    assert not output.exists(), 'Never overwrite a prior codec observation'
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'transactions': [],
        'project_mutation_count': 0, 'business_effect_verified': False, 'platform_association_proven': False,
        'read_metadata_complete': False, 'access_outcome': 'not_attempted',
        'identity_representation': 'unresolved', 'concrete_codec_class_id': None,
        'limits': {'public_calls': 9, 'identity_rows': 2, 'field_list_pages': 1, 'listed_fields': 64,
            'detail_pages': 1, 'observation_bytes': 2 * 1024 * 1024}}
    category = {'category': 'older-codec-read-metadata', 'status': 'FAIL', 'business_effect_verified': False,
        'verifier_strength': 'read_only_exact_source_codec_and_disclosed_metadata', 'observation_path': str(output)}
    runtime.category_results.append(category)
    baseline = None

    def read(argv, *, live=True):
        assert len(receipt['calls']) < receipt['limits']['public_calls'], 'Older codec public call bound exceeded'
        full = ['--evidence-dir', str(runtime.state_dir / 'older-codec-native'), *argv]
        record = {'argv': full}
        receipt['calls'].append(record)
        code, payload = runtime.raw_gateway(full)
        record.update(exit_code=code, payload=payload)
        if live and payload.get('ok') is True:
            assert payload['detected_version'] == runtime.version, payload
            if baseline is not None:
                assert payload['endpoint'] == baseline['endpoint'], payload
        return code, payload

    def successful(argv):
        code, payload = read(argv)
        assert code == 0 and payload.get('ok') is True, payload
        return payload

    def exact(identity, *includes):
        return successful(['query-object', '--exact-id', identity, '--max-results', '2',
            *[token for field in includes for token in ('--include', field)]])

    def unresolved(outcome):
        receipt['access_outcome'] = outcome
        current = successful(['status'])
        assert current['wwise'] == baseline['wwise'] and current['project'] == baseline['project'], current
        category['status'] = 'blocked'
        pytest.skip('Older codec observation unresolved: ' + outcome + '; no native absence or mutation claim')

    try:
        pin = receipt['source'] = source_identity(runtime.sandbox.source_root, runtime.version)
        assert tuple(runtime.sandbox.metadata.get_info_version.get(key) for key in
            ('year', 'major', 'minor', 'build')) == pin['build']
        baseline = successful(['status'])
        assert baseline['is_command_line'] is True and baseline['project']['id'] == pin['project_id'], baseline
        assert tuple(baseline['wwise']['version'].get(key) for key in ('year', 'major', 'minor', 'build')) == pin['build'], baseline
        assert Path(runtime.sandbox.metadata.launch_project_path).resolve() == runtime.sandbox.sandbox_project.resolve()
        assert runtime.sandbox.sandbox_project.resolve() != runtime.sandbox.source_project.resolve()
        project_path = baseline['project']['path']
        if runtime.version == '2021.1':
            project_witness = receipt['project_file_witness'] = exact(pin['project_id'], 'file-path')
            project_row, = project_witness['agent_result']
            assert project_row['id'] == pin['project_id'] and project_row['type'] == 'Project', project_witness
            project_path = project_row['file_path']
        assert Path(localize_waapi_host_path(project_path)).resolve() == runtime.sandbox.sandbox_project.resolve()
        owner_result = receipt['owner_result'] = exact(pin['owner_id'], 'class-id')
        owner, = owner_result['agent_result']
        assert (owner['id'], owner['name'], owner['type'], owner['class_id'], owner['path']) == (
            pin['owner_id'], 'Voice', 'Conversion', 3604496, pin['owner_path']), owner
        code, result = read(['query-object', '--exact-id', pin['codec_id'], '--max-results', '2',
            '--include', 'owner', '--include', 'class-id', '--include', 'plugin-name',
            '--platform', pin['platform_id'], '--detail'])
        receipt['codec_result'] = result
        native_path = result.get('call', {}).get('evidence_path') or result.get('details', {}).get('evidence_path')
        if native_path:
            path = Path(native_path).resolve(strict=True)
            assert path.is_relative_to((runtime.state_dir / 'older-codec-native').resolve()) and path.stat().st_size <= 256 * 1024
            raw = path.read_bytes()
            receipt.update(native_record=json.loads(raw), native_record_sha256=hashlib.sha256(raw).hexdigest())
        if code != 0 or result.get('ok') is not True:
            unresolved('native_read_unresolved' if 'native_record' in receipt else 'gateway_read_unresolved')
        rows = result.get('agent_result')
        if (not isinstance(rows, list) or len(rows) != 1 or result.get('projection_complete') is False
                or result.get('limit_reached') is True):
            unresolved('identity_facts_unresolved')
        row = rows[0]
        owner_reference = row.get('owner')
        if (row.get('id') != pin['codec_id'] or row.get('type') != 'ConversionPlugin'
                or not isinstance(owner_reference, dict) or owner_reference.get('id') != pin['owner_id']
                or row.get('identity_completeness', {}).get('complete') is False):
            unresolved('identity_facts_unresolved')
        if (type(row.get('class_id')) is int and row['class_id'] == 262145
                and row.get('plugin_name') == 'Vorbis'):
            receipt.update(identity_representation='concrete_codec', concrete_codec_class_id=262145)
        elif (runtime.version in OLDER_WRAPPER_SOURCES and type(row.get('class_id')) is int
                and row['class_id'] == 2818064 and row.get('plugin_name') == ''
                and row.get('name') == '' and row.get('path') == '<Unnamed Conversion plugin>'):
            # Identity is readable; concrete codec class and platform association remain unresolved.
            receipt.update(identity_representation='pinned_older_generic_wrapper',
                wrapper_source=OLDER_WRAPPER_SOURCES[runtime.version])
        else:
            unresolved('identity_facts_unresolved')
        code, listed = read(['metadata', 'list', '--exact-id', pin['codec_id'], '--page-size', '64'])
        receipt['field_list_result'] = listed
        if code != 0 or listed.get('ok') is not True:
            unresolved('metadata_unresolved')
        fields = receipt['field_list'] = listed['agent_result']
        assert fields.get('mutation_authority') is False and len(fields['fields']) <= 64, fields
        matches = [field for field in fields['fields'] if field['name'] == 'QualityFactor']
        if len(matches) != 1:
            unresolved('quality_field_not_disclosed_within_bound')
        code, detail = read(['metadata', 'detail', '--exact-id', pin['codec_id'], '--selection', matches[0]['selection']])
        receipt['detail_result'] = detail
        if code != 0 or detail.get('ok') is not True:
            unresolved('metadata_unresolved')
        facts = detail['agent_result']
        metadata = facts.get('metadata', facts.get('field', {}))
        if (facts.get('complete') is not True or facts.get('mutation_authority') is not False
                or facts.get('scope') != fields['scope'] or metadata.get('name') != 'QualityFactor'
                or not isinstance(metadata.get('type'), str) or not metadata['type']):
            unresolved('metadata_unresolved')
        current = successful(['status'])
        assert current['wwise'] == baseline['wwise'] and current['project'] == baseline['project'], current
        receipt.update(read_metadata_complete=True, access_outcome='read_and_metadata_observed')
        category.update(status='PASS', reason='Exact object identity and one disclosed field observed; concrete codec facts retained separately; no write or platform-association acceptance')
    except BaseException as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= receipt['limits']['observation_bytes']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(access_outcome=receipt['access_outcome'], read_metadata_complete=receipt['read_metadata_complete'],
            observation_sha256=hashlib.sha256(body).hexdigest())

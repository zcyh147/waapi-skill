"""Owned capture collector through the real Gateway and final category writer.

The external host is fake. These tests grant no native capture evidence.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_authoring_batch_adapter import owned_authoring
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway
from tests.support.gateway_config import set_gateway_config


def _committed_capture_objects(version='2025.1'):
    """Fixture relationships come from WWU structure, not collector constants."""
    fixture = Path(__file__).resolve().parents[1] / '_org' / version
    sections = ('Containers', 'Busses') if version == '2025.1' else ('Actor-Mixer Hierarchy', 'Master-Mixer Hierarchy')
    rows = {}
    for section in sections:
        root = ET.parse(fixture / section / 'Default Work Unit.wwu').getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        for name in ('RFL_Tail', 'WAAPI_V2_Weapons', 'Default Work Unit', 'Main Audio Bus'):
            matches = [node for node in root.iter() if node.tag in ('Sound', 'Bus', 'WorkUnit') and node.get('Name') == name]
            if not matches:
                continue
            node, = matches
            ancestors, current = [], node
            while current is not root:
                if current.get('Name'):
                    ancestors.append(current)
                current = parents[current]
            row = {'id': node.get('ID'), 'name': name, 'type': node.tag,
                'path': '\\' + '\\'.join([section, *[item.get('Name') for item in reversed(ancestors)]])}
            if section == sections[1] and node.tag == 'Bus':
                parent = ancestors[1]
                row['parent'] = {'id': parent.get('ID'), 'name': parent.get('Name')}
                row['@Volume'] = 0.0
            if section == sections[1] and node.tag == 'WorkUnit':
                row['workunitIsDefault'] = True
            rows[row['id']] = row
    sound = next(row for row in rows.values() if row['name'] == 'RFL_Tail')
    sound_node, = [node for node in ET.parse(fixture / sections[0] / 'Default Work Unit.wwu').iter()
        if node.get('ID') == sound['id']]
    bus = next(row for row in rows.values() if row['name'] == 'WAAPI_V2_Weapons')
    assert sound_node.find("ReferenceList/Reference[@Name='OutputBus']/ObjectRef").get('ID') == bus['id']
    source = sound_node.find('ChildrenList/AudioFileSource')
    assert source.findtext('AudioFile') == r'WAAPI Skill Integration V2\audit_tail.wav'
    assert sound_node.find('ActiveSourceList/ActiveSource').get('ID') == source.get('ID')
    bus['parent.workunitIsDefault'] = rows[bus['parent']['id']]['workunitIsDefault']
    return rows


def _committed_2024_capture_objects():
    fixture = Path(__file__).resolve().parents[1] / '_org/2024.1'
    rows = {}
    for section, filename, names in (
        ('Actor-Mixer Hierarchy', 'Minigun.wwu', ('MnGn_Barrel_Loop',)),
        ('Master-Mixer Hierarchy', 'Default Work Unit.wwu', ('Guns', 'SFX', 'Master Audio Bus')),
    ):
        root = ET.parse(fixture / section / filename).getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        for node in root.iter():
            if node.tag not in ('Sound', 'Bus') or node.get('Name') not in names:
                continue
            lineage, current = [], node
            while current is not root:
                if current.get('Name'):
                    lineage.append(current)
                current = parents[current]
            row = {'id': node.get('ID'), 'name': node.get('Name'), 'type': node.tag,
                'path': '\\' + '\\'.join([section, *[item.get('Name') for item in reversed(lineage)]])}
            if node.tag == 'Bus':
                row.update({'classId': 1376272, '@Volume': 0.0,
                    'parent': {'id': lineage[1].get('ID'), 'name': lineage[1].get('Name')},
                    'parent.classId': 1376272 if lineage[1].tag == 'Bus' else 1638416})
                if lineage[1].tag == 'Bus':
                    row['parent.@Volume'] = 0.0
                # Matching WObjects default: Same as parent, hence Guns has no
                # independent processing/meter until configured explicitly.
                if node.get('Name') == 'Guns':
                    assert node.find("PropertyList/Property[@Name='BusChannelConfig']") is None
                    row['@BusChannelConfig'] = 0
            else:
                assert node.find("PropertyList/Property[@Name='IsLoopingEnabled']").get('Value') == 'True'
                # Stored child Master references are unused: no child overrides;
                # the top ActorMixer's ordinary OutputBus resolves to Guns.
                assert all(item.find("PropertyList/Property[@Name='OverrideOutput']") is None for item in lineage[:-2])
                output = lineage[-2].find("ReferenceList/Reference[@Name='OutputBus']/ObjectRef")
                row.update({'classId': 65552, '@IsLoopingEnabled': True, '@IsLoopingInfinite': True,
                    'OutputBus': {'id': output.get('ID'), 'name': output.get('Name')}})
                source = node.find('ChildrenList/AudioFileSource')
                assert source.findtext('AudioFile') == r'Minigun\MnGn_Barrel_Loop.wav'
                assert node.find('ActiveSourceList/ActiveSource').get('ID') == source.get('ID')
            rows[row['id']] = row
    return rows


def _committed_car_capture_objects(version):
    fixture = Path(__file__).resolve().parents[1] / '_org' / version
    section = 'Containers' if version == '2025.1' else 'Actor-Mixer Hierarchy'
    root = ET.parse(fixture / section / 'Car Engine.wwu').getroot()
    parents = {child: parent for parent in root.iter() for child in parent}
    sound, = [node for node in root.iter('Sound') if node.get('Name') == 'Outside_Idle_1000']
    source = sound.find('ChildrenList/AudioFileSource')
    assert source.get('ID') == sound.find('ActiveSourceList/ActiveSource').get('ID')
    assert source.findtext('AudioFile') == r'Car Engine\Porsche_Outside_Idle_1000_01.wav'
    assert source.find('MediaIDList/MediaID').get('ID') == '416741917'
    rows = {}
    lineage, node = [], sound
    while node is not root:
        if node.get('Name'):
            lineage.append(node)
        node = parents[node]
    for node in (sound, source, lineage[1]):
        node_lineage, current = [], node
        while current is not root:
            if current.get('Name'):
                node_lineage.append(current.get('Name'))
            current = parents[current]
        rows[node.get('ID')] = {'id': node.get('ID'), 'name': node.get('Name'), 'type': node.tag,
            'path': '\\' + '\\'.join([section, *reversed(node_lineage)])}
    output = next(ancestor.find("ReferenceList/Reference[@Name='OutputBus']/ObjectRef")
        for ancestor in reversed(lineage[1:])
        if ancestor.find("ReferenceList/Reference[@Name='OutputBus']/ObjectRef") is not None)
    row = rows[sound.get('ID')]
    row.update({'classId': 65552, '@IsLoopingEnabled': True, '@IsLoopingInfinite': True,
        '@IsStreamingEnabled': False, '@OverrideOutput': False,
        'parent': {'id': lineage[1].get('ID'), 'name': lineage[1].get('Name')},
        'activeSource': {'id': source.get('ID'), 'name': source.get('Name')},
        'OutputBus': {'id': output.get('ID'), 'name': output.get('Name')}})
    bus_section = 'Busses' if version == '2025.1' else 'Master-Mixer Hierarchy'
    buses = ET.parse(fixture / bus_section / 'Default Work Unit.wwu').getroot()
    parents = {child: parent for parent in buses.iter() for child in parent}
    bus, = [node for node in buses.iter('Bus') if node.get('ID') == output.get('ID')]
    lineage, node = [], bus
    while node is not buses:
        if node.get('Name'):
            lineage.append(node)
        node = parents[node]
    rows[bus.get('ID')] = {'id': bus.get('ID'), 'name': bus.get('Name'), 'type': 'Bus', 'classId': 1376272,
        'path': '\\' + '\\'.join([bus_section, *[item.get('Name') for item in reversed(lineage)]]),
        '@Volume': 0.0, 'parent': {'id': lineage[1].get('ID'), 'name': lineage[1].get('Name')}}
    rpm_root = ET.parse(fixture / 'Game Parameters/Car Engine.wwu')
    rpm, = [node for node in rpm_root.iter('GameParameter') if node.get('Name') == 'RPM']
    props = {'Min': 0.0, **{item.get('Name'): float(item.get('Value')) for item in rpm.findall('PropertyList/Property')
        if item.get('Name') in ('Min', 'Max')}}
    rows[rpm.get('ID')] = {'id': rpm.get('ID'), 'name': 'RPM', 'type': 'GameParameter',
        'path': r'\Game Parameters\Car Engine\RPM', **{'@' + key: value for key, value in props.items()}}
    return rows


# Exact retained Authoring2024 native rows; source receipt SHA256 05dc4a6c6c28c2f1635bd3e741f208ad2630a379f6a2b57da5bdbe9d4bbf43a0.
NATIVE_CPU_2024 = json.loads(r'''{"return":[{"elementName":"CAkAudioMgr::Perform","id":0,"instances":2,"millisecondsExclusive":0.014000000432133675,"millisecondsInclusive":0.2167000025510788,"percentExclusive":0.13124999403953552,"percentInclusive":2.031562328338623,"type":""},{"elementName":"AK Acquire GlobalLock","id":0,"instances":1,"millisecondsExclusive":0.00039999998989515007,"millisecondsInclusive":0.00039999998989515007,"percentExclusive":0.0037499996833503246,"percentInclusive":0.0037499996833503246,"type":""},{"elementName":"CAkAudioMgr::BeginPerformIteration","id":0,"instances":2,"millisecondsExclusive":0.0006000000284984708,"millisecondsInclusive":0.0006000000284984708,"percentExclusive":0.005624999757856131,"percentInclusive":0.005624999757856131,"type":""},{"elementName":"AK::JobMgr::WorkUntilDone","id":0,"instances":2,"millisecondsExclusive":0.010499999858438969,"millisecondsInclusive":0.20229999721050262,"percentExclusive":0.09843749552965164,"percentInclusive":1.8965623378753662,"type":""},{"elementName":"CAkAudioMgr::PerformPrologue","id":0,"instances":1,"millisecondsExclusive":0.0017000000225380063,"millisecondsInclusive":0.0027000000700354576,"percentExclusive":0.015937499701976776,"percentInclusive":0.025312498211860657,"type":""},{"elementName":"CAkAudioMgr::ProcessPlayCmds","id":0,"instances":2,"millisecondsExclusive":0.0020000000949949026,"millisecondsInclusive":0.0032999999821186066,"percentExclusive":0.01874999888241291,"percentInclusive":0.030937498435378075,"type":""},{"elementName":"Global Extension","id":0,"instances":1,"millisecondsExclusive":0.000699999975040555,"millisecondsInclusive":0.0010000000474974513,"percentExclusive":0.006562499329447746,"percentInclusive":0.009374999441206455,"type":""},{"elementName":"CAkAudioMgr::BeginPerform","id":0,"instances":1,"millisecondsExclusive":0.004000000189989805,"millisecondsInclusive":0.004000000189989805,"percentExclusive":0.03749999776482582,"percentInclusive":0.03749999776482582,"type":""},{"elementName":"AK::SoundEngine::RenderAudio","id":0,"instances":1,"millisecondsExclusive":0.0003000000142492354,"millisecondsInclusive":0.0003000000142492354,"percentExclusive":0.0028124998789280653,"percentInclusive":0.0028124998789280653,"type":""},{"elementName":"CAkAudioMgr::ProcessMsgQueue","id":0,"instances":4,"millisecondsExclusive":0.0010999999940395355,"millisecondsInclusive":0.00139999995008111,"percentExclusive":0.010312499478459358,"percentInclusive":0.013124998658895493,"type":""},{"elementName":"CAkMusicRenderer::ProcessNextFrame","id":0,"instances":1,"millisecondsExclusive":0.0005000000237487257,"millisecondsInclusive":0.0005000000237487257,"percentExclusive":0.004687499720603228,"percentInclusive":0.004687499720603228,"type":""},{"elementName":"CAkLEngine::SoftwarePerformEpilogue","id":0,"instances":1,"millisecondsExclusive":0.00559999980032444,"millisecondsInclusive":0.008100000210106373,"percentExclusive":0.05249999463558197,"percentInclusive":0.07593749463558197,"type":""},{"elementName":"CAkAudioMgr::EndRender","id":0,"instances":1,"millisecondsExclusive":0.00039999998989515007,"millisecondsInclusive":0.00039999998989515007,"percentExclusive":0.0037499996833503246,"percentInclusive":0.0037499996833503246,"type":""},{"elementName":"CAkLEngine::PostRunVpls","id":0,"instances":1,"millisecondsExclusive":0.004100000020116568,"millisecondsInclusive":0.004100000020116568,"percentExclusive":0.03843749687075615,"percentInclusive":0.03843749687075615,"type":""},{"elementName":"CAkAudioMgr::ProcessAllCommands","id":0,"instances":1,"millisecondsExclusive":0.003800000064074993,"millisecondsInclusive":0.013199999928474426,"percentExclusive":0.035624995827674866,"percentInclusive":0.1237499937415123,"type":""},{"elementName":"CAkLEngineCmds::ProcessPendingCommands","id":0,"instances":1,"millisecondsExclusive":0.0003000000142492354,"millisecondsInclusive":0.0003000000142492354,"percentExclusive":0.0028124998789280653,"percentInclusive":0.0028124998789280653,"type":""},{"elementName":"CAkAudioMgr::EndPerformIteration","id":0,"instances":2,"millisecondsExclusive":0.02630000002682209,"millisecondsInclusive":0.02630000002682209,"percentExclusive":0.24656248092651367,"percentInclusive":0.24656248092651367,"type":""},{"elementName":"CAkAudioMgr::EndPerform","id":0,"instances":1,"millisecondsExclusive":0.0003000000142492354,"millisecondsInclusive":0.0003000000142492354,"percentExclusive":0.0028124998789280653,"percentInclusive":0.0028124998789280653,"type":""},{"elementName":"CAkAudioMgr::PerformEpilogue","id":0,"instances":1,"millisecondsExclusive":0.0007999999797903001,"millisecondsInclusive":0.08980000019073486,"percentExclusive":0.007499999366700649,"percentInclusive":0.8418749570846558,"type":""},{"elementName":"AkMonitor::DispatchNotification","id":0,"instances":2,"millisecondsExclusive":0.13590000569820404,"millisecondsInclusive":0.13590000569820404,"percentExclusive":1.2740623950958252,"percentInclusive":1.2740623950958252,"type":""},{"elementName":"CAkLEngine::ReleaseBuffersAndFeedback","id":0,"instances":1,"millisecondsExclusive":0.000699999975040555,"millisecondsInclusive":0.000699999975040555,"percentExclusive":0.006562499329447746,"percentInclusive":0.006562499329447746,"type":""},{"elementName":"CAkLEngine::AnalyzeMixingGraph","id":196608,"instances":1,"millisecondsExclusive":0.006300000008195639,"millisecondsInclusive":0.006300000008195639,"percentExclusive":0.059062495827674866,"percentInclusive":0.059062495827674866,"type":""},{"elementName":"CAkLEngine::PreprocessSources","id":262144,"instances":1,"millisecondsExclusive":0.0012000000569969416,"millisecondsInclusive":0.0012000000569969416,"percentExclusive":0.011249999515712261,"percentInclusive":0.011249999515712261,"type":""},{"elementName":"CAkLEngine::VoiceTask","id":327680,"instances":1,"millisecondsExclusive":0.0032999999821186066,"millisecondsInclusive":0.005100000184029341,"percentExclusive":0.030937498435378075,"percentInclusive":0.04781249538064003,"type":""},{"elementName":"CAkLEngine::VoiceTaskParallelAsync","id":393216,"instances":1,"millisecondsExclusive":0.0006000000284984708,"millisecondsInclusive":0.0006000000284984708,"percentExclusive":0.005624999757856131,"percentInclusive":0.005624999757856131,"type":""},{"elementName":"AkPerf::PostPipelineStats","id":458752,"instances":1,"millisecondsExclusive":0.0024999999441206455,"millisecondsInclusive":0.0024999999441206455,"percentExclusive":0.02343749813735485,"percentInclusive":0.02343749813735485,"type":""},{"elementName":"Original WAV","id":458753,"instances":1,"millisecondsExclusive":0.0017999999690800905,"millisecondsInclusive":0.0017999999690800905,"percentExclusive":0.016874998807907104,"percentInclusive":0.016874998807907104,"type":"Codec"},{"elementName":"AK::CommunicationCentral::Process","id":524288,"instances":1,"millisecondsExclusive":0.08900000154972076,"millisecondsInclusive":0.08900000154972076,"percentExclusive":0.8343749642372131,"percentInclusive":0.8343749642372131,"type":""},{"elementName":"AK SwVoice","id":655360,"instances":1,"millisecondsExclusive":0.00019999999494757503,"millisecondsInclusive":0.0052999998442828655,"percentExclusive":0.0018749998416751623,"percentInclusive":0.049687497317790985,"type":""},{"elementName":"AK BusTask","id":786432,"instances":1,"millisecondsExclusive":0.01269999984651804,"millisecondsInclusive":0.03189999982714653,"percentExclusive":0.11906249076128006,"percentInclusive":0.29906249046325684,"type":""},{"elementName":"CAkLEngine::DispatchBusGraphAsync","id":2949120,"instances":1,"millisecondsExclusive":0.0010000000474974513,"millisecondsInclusive":0.0010000000474974513,"percentExclusive":0.009374999441206455,"percentInclusive":0.009374999441206455,"type":""},{"elementName":"Peak Limiter","id":7208963,"instances":1,"millisecondsExclusive":0.019200000911951065,"millisecondsInclusive":0.019200000911951065,"percentExclusive":0.17999999225139618,"percentInclusive":0.17999999225139618,"type":"Effect"},{"elementName":"Interactive Music","id":52494344,"instances":1,"millisecondsExclusive":0.0003000000142492354,"millisecondsInclusive":0.0007999999797903001,"percentExclusive":0.0028124998789280653,"percentInclusive":0.007499999366700649,"type":"Global Extension"},{"elementName":"MIDI Device Manager","id":52559880,"instances":1,"millisecondsExclusive":0.0005000000237487257,"millisecondsInclusive":0.0005000000237487257,"percentExclusive":0.004687499720603228,"percentInclusive":0.004687499720603228,"type":"Global Extension"}]}''')

# Exact retained Authoring2025 native rows; source receipt SHA256 2866fe3e2238f485a4acdb86532734086847a8e01556903444046f1a63634ba1.
NATIVE_CPU_2025 = json.loads(r'''{"return":[{"elementName":"CAkAudioMgr::Perform","id":0,"instances":2,"millisecondsExclusive":0.013700000010430813,"millisecondsInclusive":0.24310000240802765,"percentExclusive":0.12843748927116394,"percentInclusive":2.279062271118164,"type":""},{"elementName":"AK Acquire GlobalLock","id":0,"instances":1,"millisecondsExclusive":0.000699999975040555,"millisecondsInclusive":0.000699999975040555,"percentExclusive":0.006562499329447746,"percentInclusive":0.006562499329447746,"type":""},{"elementName":"CAkAudioMgr::BeginPerformIteration","id":0,"instances":2,"millisecondsExclusive":0.0005000000237487257,"millisecondsInclusive":0.0005000000237487257,"percentExclusive":0.004687499720603228,"percentInclusive":0.004687499720603228,"type":""},{"elementName":"AK::JobMgr::WorkUntilDone","id":0,"instances":2,"millisecondsExclusive":0.013899999670684338,"millisecondsInclusive":0.22869999706745148,"percentExclusive":0.1303124874830246,"percentInclusive":2.1440622806549072,"type":""},{"elementName":"CAkAudioMgr::PerformPrologue","id":0,"instances":1,"millisecondsExclusive":0.0015999999595806003,"millisecondsInclusive":0.0024999999441206455,"percentExclusive":0.014999998733401299,"percentInclusive":0.02343749813735485,"type":""},{"elementName":"CAkAudioMgr::ProcessPlayCmds","id":0,"instances":2,"millisecondsExclusive":0.002199999988079071,"millisecondsInclusive":0.0026000000070780516,"percentExclusive":0.020624998956918716,"percentInclusive":0.02437499724328518,"type":""},{"elementName":"Global Extension","id":0,"instances":1,"millisecondsExclusive":0.0006000000284984708,"millisecondsInclusive":0.0008999999845400453,"percentExclusive":0.005624999757856131,"percentInclusive":0.008437499403953552,"type":""},{"elementName":"CAkAudioMgr::BeginPerform","id":0,"instances":1,"millisecondsExclusive":0.00419999985024333,"millisecondsInclusive":0.00419999985024333,"percentExclusive":0.03937499597668648,"percentInclusive":0.03937499597668648,"type":""},{"elementName":"AK::SoundEngine::RenderAudio","id":0,"instances":1,"millisecondsExclusive":0.0003000000142492354,"millisecondsInclusive":0.0003000000142492354,"percentExclusive":0.0028124998789280653,"percentInclusive":0.0028124998789280653,"type":""},{"elementName":"CAkAudioMgr::ProcessMsgQueue","id":0,"instances":4,"millisecondsExclusive":0.0017999999690800905,"millisecondsInclusive":0.002199999988079071,"percentExclusive":0.016874998807907104,"percentInclusive":0.020624998956918716,"type":""},{"elementName":"CAkAudioMgr::ProcessAllCommands","id":0,"instances":1,"millisecondsExclusive":0.00430000014603138,"millisecondsInclusive":0.016599999740719795,"percentExclusive":0.040312495082616806,"percentInclusive":0.15562498569488525,"type":""},{"elementName":"CAkLEngineCmds::ProcessPendingCommands","id":0,"instances":1,"millisecondsExclusive":9.999999747378752e-05,"millisecondsInclusive":9.999999747378752e-05,"percentExclusive":0.0009374999208375812,"percentInclusive":0.0009374999208375812,"type":""},{"elementName":"CAkLEngine::SoftwarePerformEpilogue","id":0,"instances":1,"millisecondsExclusive":0.006399999838322401,"millisecondsInclusive":0.00989999994635582,"percentExclusive":0.059999994933605194,"percentInclusive":0.09281249344348907,"type":""},{"elementName":"CAkAudioMgr::EndRender","id":0,"instances":1,"millisecondsExclusive":0.0005000000237487257,"millisecondsInclusive":0.0005000000237487257,"percentExclusive":0.004687499720603228,"percentInclusive":0.004687499720603228,"type":""},{"elementName":"CAkMusicRenderer::ProcessNextFrame","id":0,"instances":1,"millisecondsExclusive":0.0003000000142492354,"millisecondsInclusive":0.0003000000142492354,"percentExclusive":0.0028124998789280653,"percentInclusive":0.0028124998789280653,"type":""},{"elementName":"CAkLEngine::PostRunVpls","id":0,"instances":1,"millisecondsExclusive":0.004100000020116568,"millisecondsInclusive":0.004100000020116568,"percentExclusive":0.03843749687075615,"percentInclusive":0.03843749687075615,"type":""},{"elementName":"CAkAudioMgr::EndPerformIteration","id":0,"instances":2,"millisecondsExclusive":0.03579999879002571,"millisecondsInclusive":0.03579999879002571,"percentExclusive":0.33562496304512024,"percentInclusive":0.33562496304512024,"type":""},{"elementName":"CAkAudioMgr::EndPerform","id":0,"instances":1,"millisecondsExclusive":9.999999747378752e-05,"millisecondsInclusive":9.999999747378752e-05,"percentExclusive":0.0009374999208375812,"percentInclusive":0.0009374999208375812,"type":""},{"elementName":"CAkAudioMgr::PerformEpilogue","id":0,"instances":1,"millisecondsExclusive":0.0010000000474974513,"millisecondsInclusive":0.09790000319480896,"percentExclusive":0.009374999441206455,"percentInclusive":0.9178124070167542,"type":""},{"elementName":"AkMonitor::DispatchNotification","id":0,"instances":3,"millisecondsExclusive":0.15129999816417694,"millisecondsInclusive":0.15129999816417694,"percentExclusive":1.4184373617172241,"percentInclusive":1.4184373617172241,"type":""},{"elementName":"CAkLEngine::ReleaseBuffersAndFeedback","id":0,"instances":1,"millisecondsExclusive":0.000699999975040555,"millisecondsInclusive":0.000699999975040555,"percentExclusive":0.006562499329447746,"percentInclusive":0.006562499329447746,"type":""},{"elementName":"CAkLEngine::AnalyzeMixingGraph","id":196608,"instances":1,"millisecondsExclusive":0.008700000122189522,"millisecondsInclusive":0.008700000122189522,"percentExclusive":0.08156249672174454,"percentInclusive":0.08156249672174454,"type":""},{"elementName":"CAkLEngine::PreprocessSources","id":262144,"instances":1,"millisecondsExclusive":0.001500000013038516,"millisecondsInclusive":0.001500000013038516,"percentExclusive":0.014062498696148396,"percentInclusive":0.014062498696148396,"type":""},{"elementName":"CAkLEngine::VoiceTask","id":327680,"instances":1,"millisecondsExclusive":0.0032999999821186066,"millisecondsInclusive":0.005200000014156103,"percentExclusive":0.030937498435378075,"percentInclusive":0.04874999448657036,"type":""},{"elementName":"CAkLEngine::VoiceTaskParallelAsync","id":393216,"instances":1,"millisecondsExclusive":0.000699999975040555,"millisecondsInclusive":0.000699999975040555,"percentExclusive":0.006562499329447746,"percentInclusive":0.006562499329447746,"type":""},{"elementName":"AkPerf::PostPipelineStats","id":458752,"instances":1,"millisecondsExclusive":0.0035000001080334187,"millisecondsInclusive":0.0035000001080334187,"percentExclusive":0.03281249850988388,"percentInclusive":0.03281249850988388,"type":""},{"elementName":"Original WAV","id":458753,"instances":1,"millisecondsExclusive":0.0019000000320374966,"millisecondsInclusive":0.0019000000320374966,"percentExclusive":0.017812497913837433,"percentInclusive":0.017812497913837433,"type":"Codec"},{"elementName":"AK::CommunicationCentral::Process","id":524288,"instances":1,"millisecondsExclusive":0.09690000116825104,"millisecondsInclusive":0.09690000116825104,"percentExclusive":0.9084374308586121,"percentInclusive":0.9084374308586121,"type":""},{"elementName":"AK SwVoice","id":655360,"instances":1,"millisecondsExclusive":0.00039999998989515007,"millisecondsInclusive":0.00559999980032444,"percentExclusive":0.0037499996833503246,"percentInclusive":0.05249999463558197,"type":""},{"elementName":"AK BusTask","id":786432,"instances":1,"millisecondsExclusive":0.013000000268220901,"millisecondsInclusive":0.03200000151991844,"percentExclusive":0.12187498807907104,"percentInclusive":0.29999998211860657,"type":""},{"elementName":"CAkLEngine::DispatchBusGraphAsync","id":3145728,"instances":1,"millisecondsExclusive":0.0010000000474974513,"millisecondsInclusive":0.0010000000474974513,"percentExclusive":0.009374999441206455,"percentInclusive":0.009374999441206455,"type":""},{"elementName":"Peak Limiter","id":7208963,"instances":1,"millisecondsExclusive":0.01899999938905239,"millisecondsInclusive":0.01899999938905239,"percentExclusive":0.17812497913837433,"percentInclusive":0.17812497913837433,"type":"Effect"},{"elementName":"MIDI Device Manager","id":52559880,"instances":1,"millisecondsExclusive":0.00039999998989515007,"millisecondsInclusive":0.00039999998989515007,"percentExclusive":0.0037499996833503246,"percentInclusive":0.0037499996833503246,"type":"Global Extension"}]}''')


def _capture_host(owner, tmp_path, monkeypatch, *, failure=None, version='2025.1', readers=False,
        capture_reads=False, cpu_native_version=None, native_rtpc=False, mixing_bus=None, missing_reads=False,
        partial_seed=None, cursor_moves=False):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import (
        NODEID, SOUND_ID, BUS_ID, collect_owned_capture,
    )
    runtime = owner.runtime
    capture_reads = capture_reads or missing_reads
    game_object = 18446744073709551614 if native_rtpc else 1
    capture_time = 100 if failure == 'cursor-single-frame' else {'2024.1': 45621, '2025.1': 46869}.get(cpu_native_version, 1500)
    nodeid, sound_id, bus_id = NODEID, SOUND_ID, BUS_ID
    if cursor_moves:
        from tests.destructive.support.profiler_capture import CURSOR_MOVES_NODEID
        nodeid = CURSOR_MOVES_NODEID
    if readers:
        from tests.destructive.support.profiler_capture import READERS_2025_NODEID
        nodeid = READERS_2025_NODEID
    if capture_reads:
        from tests.destructive.support.profiler_capture import CAPTURE_READS_NODEID
        nodeid = CAPTURE_READS_NODEID
        if missing_reads:
            from tests.destructive.support.profiler_capture import CAPTURE_MISSING_NODEID
            nodeid = CAPTURE_MISSING_NODEID
    media_relative = 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav'
    build = '2025.1.7.9143'
    if capture_reads:
        sound_id = '{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}'
        car_rows = _committed_car_capture_objects(version)
        bus_id = car_rows[sound_id]['OutputBus']['id']
        media_relative = 'Originals/SFX/Car Engine/Porsche_Outside_Idle_1000_01.wav'
        minor, number = {'2021.1': (14, 8108), '2022.1': (19, 8584), '2023.1': (19, 8928),
            '2024.1': (13, 9056), '2025.1': (7, 9143)}[version]
        build = f'{version}.{minor}.{number}'
        owner.version = version
        owner.runtime = runtime = replace(runtime, version=version)
        runtime.sandbox.metadata.wwise_version = version
        runtime.lifecycle.ready_result['version'].update(year=int(version[:4]), minor=minor, build=number)
    if version == '2024.1' and not capture_reads:
        nodeid = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_2024_meter_projection'
        sound_id, bus_id = '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}', '{06362E8D-5A32-497A-B063-3DA95963CE47}'
        media_relative, build = 'Originals/SFX/Minigun/MnGn_Barrel_Loop.wav', '2024.1.13.9056'
        owner.version = version
        owner.runtime = runtime = replace(runtime, version=version)
        runtime.sandbox.metadata.wwise_version = version
        runtime.lifecycle.ready_result['version'].update(year=2024, minor=13, build=9056)
    runtime.lifecycle.ready_result['version']['displayName'] = 'v' + build
    media = (tmp_path / 'installed' / ('SampleProject' + ('2025.1.7.9143' if version == '2022.1' else build)) / 'SampleProject' / media_relative
        if capture_reads else tmp_path / 'matching-installed-originals/SFX/Minigun/MnGn_Barrel_Loop.wav'
        if version == '2024.1' else runtime.sandbox.sandbox_path / media_relative)
    import wave
    if not cursor_moves:
        media.parent.mkdir(parents=True)
        with wave.open(str(media), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(48000)
            output.writeframes(b'\x01\x00' * 5567)
    if capture_reads:
        from tests.destructive.support import profiler_capture
        monkeypatch.setattr(profiler_capture, 'CAPTURE_SAMPLE_ROOT', tmp_path / 'installed')
        monkeypatch.setattr(profiler_capture, 'CAPTURE_CAR_SHA256',
            'e352d2a9e296b862eebc1a2d357a0dea696774b257db04da1abd2ecccb70fa52')
        runtime.io_root.mkdir(parents=True, exist_ok=True)
        profiler_capture.stage_owned_capture_read_media(runtime.sandbox, runtime.io_root, version=version)
    elif version == '2024.1':
        from tests.destructive.support import profiler_capture
        monkeypatch.setattr(profiler_capture, 'METER_2024_MEDIA_SOURCE', media)
        # Synthetic external file, pinned independently; no native media credit.
        monkeypatch.setattr(profiler_capture, 'METER_2024_MEDIA_SHA256',
            'e352d2a9e296b862eebc1a2d357a0dea696774b257db04da1abd2ecccb70fa52')
        runtime.io_root.mkdir(parents=True, exist_ok=True)
        profiler_capture.stage_owned_2024_meter_media(runtime.sandbox, runtime.io_root)

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path, version=version)
            self.calls, self.transport, self.playing, self.user_time = [], False, False, 100 if cursor_moves else 0
            self.registered = False
            self.logs = {'general': [], 'sourceControl': [{'message': 'preserve unselected channel',
                'severity': 'Message', 'time': 1, 'messageId': 'Custom'}]}
            self.rows = car_rows if capture_reads else _committed_2024_capture_objects() if version == '2024.1' else _committed_capture_objects(version)
            self.rows['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'] = {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}',
                'name': 'SampleProject', 'type': 'Project', 'path': '\\', 'filePath': str(runtime.sandbox.sandbox_project)}
            if capture_reads and version == '2021.1':
                self.rows['{44444444-4444-4444-4444-444444444444}'] = {
                    'id': '{44444444-4444-4444-4444-444444444444}', 'name': 'Mac', 'type': 'Platform', 'path': 'Mac'}
                language = {'id': '{55555555-5555-5555-5555-555555555555}', 'name': 'SFX'}
                self.rows[language['id']] = {**language, 'type': 'Language', 'path': r'\Languages\SFX'}
                self.rows[sound_id].update({'originalWavFilePath': str(runtime.sandbox.sandbox_path / media_relative),
                    'audioSource:language': language})
                self.rows['{48770A4D-B8C3-41CF-AE3E-FB8651347736}'].update({'classId': 16,
                    'parent': {'id': sound_id}, 'audioSource:language': language,
                    'originalWavFilePath': str(runtime.sandbox.sandbox_path / media_relative)})
            if version in ('2022.1', '2025.1') and not capture_reads:
                self.rows[sound_id].update({'classId': 65552, '@IsLoopingEnabled': False, '@IsLoopingInfinite': True})
                self.rows[sound_id]['OutputBus'] = {'id': bus_id, 'name': 'WAAPI_V2_Weapons'}
            self.rows[bus_id]['classId'] = 1376272
            if failure == 'wrong-parent':
                sibling = next(row for row in self.rows.values() if row['name'] == 'Main Audio Bus')
                self.rows[bus_id]['parent'] = {key: sibling[key] for key in ('id', 'name')}

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                info = super().call(uri, args, options)
                info['version'].update(runtime.lifecycle.ready_result['version'])
                info['version']['displayName'] = 'v' + build
                return {**info, **deepcopy(runtime.lifecycle.ready_result), 'version': info['version']}
            if uri.endswith('getProjectInfo'):
                return {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject',
                    'path': str(runtime.sandbox.sandbox_project), 'isDirty': False}
            if uri.endswith('object.getTypes'):
                return {'return': [{'classId': 65552, 'name': 'Sound', 'type': 'WObject'},
                    {'classId': 16, 'name': 'AudioSource', 'type': 'WObject'}]}
            if uri.endswith('object.get'):
                ids = args.get('from', {}).get('id', [])
                if 'waql' in args:
                    ids = [identity for identity in self.rows if identity in args['waql']]
                    if args['waql'] == 'from type Project take 1':
                        ids = ['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}']
                    elif args['waql'].startswith('from type Platform'):
                        ids = ['{44444444-4444-4444-4444-444444444444}']
                    elif args['waql'].startswith('from type Language'):
                        ids = ['{55555555-5555-5555-5555-555555555555}']
                    elif 'select children' in args['waql']:
                        ids = ['{48770A4D-B8C3-41CF-AE3E-FB8651347736}']
                return {'return': [{key: deepcopy(row[key] if key in row else row['@' + key])
                    for key in options['return'] if key in row or '@' + key in row}
                    for identity in ids if (row := self.rows.get(identity))]}
            if uri.endswith('getPropertyAndReferenceNames'):
                return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite', *(['IsStreamingEnabled'] if capture_reads else [])] if args.get('object') == sound_id
                    else ['Min', 'Max'] if args.get('object') == '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}'
                    else ['Volume', 'BusChannelConfig'] if version == '2024.1' and args.get('object') == bus_id else ['Volume']}
            if uri.endswith('getPropertyInfo'):
                token = args['property']
                if version == '2024.1' and token == 'BusChannelConfig':
                    return {'name': token, 'type': 'int32', 'display': {'name': 'Bus Configuration'},
                        'default': 0, 'dependencies': [], 'supports': {},
                        'restriction': {'type': 'enum', 'values': [
                            {'value': 0, 'displayName': 'Same as parent'}, {'value': 12546, 'displayName': '2.0'}]}}
                return {'name': token, 'type': 'bool' if token.startswith('Is') else 'Real64',
                    'display': {'name': token}, 'default': token == 'IsLoopingInfinite',
                    'dependencies': ([{'type': 'property', 'name': 'IsLoopingEnabled', 'action': 'Enable',
                        'values': [True]}] if token == 'IsLoopingInfinite' else []), 'supports': {}, 'restriction': {}}
            if uri.endswith('object.setProperty'):
                self.rows[args['object']]['@' + args['property']] = args['value']
                return {}
            if uri.endswith('transport.getList'):
                return {'list': [{'transport': 74, 'object': sound_id, 'gameObject': game_object}] if self.transport else []}
            if uri.endswith('transport.create'):
                self.transport = True
                return {'transport': 74}
            if uri.endswith('transport.destroy'):
                self.transport = False
                return {}
            if uri.endswith('transport.executeAction'):
                self.playing = args['action'] == 'play'
                return {}
            if uri.endswith('transport.getState'):
                return {'state': 'playing' if self.playing else 'stopped'}
            if uri.endswith('profiler.getCursorTime'):
                return {'return': capture_time if args['cursor'] == 'capture' else self.user_time}
            if uri.endswith('profiler.moveCursor'):
                self.user_time = {'first': 100, 'next': 110, 'last': 1500, 'previous': 1490}[args['position']]
                if failure == 'cursor-single-frame':
                    self.user_time = 100
                if failure == 'cursor-unavailable' and args['position'] == 'next':
                    self.user_time = -1
                if failure == 'cursor-mismatch' and args['position'] == 'next':
                    self.user_time = 111
                    return {'return': 110}
                return {'return': self.user_time}
            if uri.endswith('profiler.getRTPCs'):
                if native_rtpc:
                    return {'return': [{'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'name': 'RPM',
                        'gameObjectId': 18446744073709551614, 'value': 1000.0},
                        {'id': '{EB92D28A-BB63-4332-8166-0AC95BAD9EFE}', 'name': 'Engine_Load',
                            'gameObjectId': 18446744073709551614, 'value': 1.0}]}
                return {'return': [] if failure == 'empty-extra' else [
                    {'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'name': 'RPM',
                        'gameObjectId': game_object, 'value': 1000.0}]}
            if uri.endswith('profiler.getVoiceContributions'):
                if failure in ('empty-extra', 'missing-contribution'):
                    return {}
                obj = {'name': self.rows[sound_id]['name'], 'volume': 0.0, 'LPF': 0.0, 'HPF': 0.0,
                    'parameters': [], 'children': []}
                if version in ('2024.1', '2025.1'):
                    obj['index'] = 0
                result = {'volume': 0.0, 'LPF': 0.0, 'HPF': 0.0, 'objects': [obj]}
                if failure == 'scalar-contribution':
                    result['objects'] = []
                if version == '2025.1':
                    obj['DSF'] = result['DSF'] = 0.0
                return {'return': result}
            if uri.endswith('profiler.getCpuUsage'):
                if cpu_native_version is not None:
                    return deepcopy(NATIVE_CPU_2024 if cpu_native_version == '2024.1' else NATIVE_CPU_2025)
                rows = [] if failure == 'empty-extra' else [{'id': 1, 'elementName': 'PCM',
                    'type': 'Codec', 'instances': 1, 'percentInclusive': 0.0, 'percentExclusive': 0.0,
                    'millisecondsInclusive': 0.0, 'millisecondsExclusive': 0.0}]
                if failure == 'cpu-page-bound':
                    rows = [{**rows[0], 'id': i, 'elementName': 'x' * 3000} for i in range(64)]
                return {'return': rows * (65 if failure == 'partial-extra' else 1)}
            if uri.endswith('profiler.getPerformanceMonitor'):
                return {'return': [] if failure == 'empty-extra' else [{'id': 'totalCPU', 'name': 'Total CPU', 'value': 0.0}]}
            if uri.endswith(('profiler.getLoadedMedia', 'profiler.getStreamedMedia')):
                if failure in ('nonempty-media', 'disable-readers', 'scalar-contribution', 'missing-contribution'):
                    if uri.endswith('getLoadedMedia'):
                        return {'return': [{'mediaId': 17, 'fileName': 'some-media.wem', 'format': 'PCM',
                            'size': 1024, 'soundBank': 'Some Bank'}]}
                    return {'return': [{'deviceName': 'Default device', 'streamName': 'Stream 17', 'fileSize': 1024,
                        'filePosition': 0.0, 'priority': 50, 'bandwidthTotal': 0, 'bandwidthLowLevel': 0,
                        'referencedMemory': 0, 'estimatedThroughput': 0, 'active': True,
                        'targetBufferSize': 1024, 'bufferStatusBuffered': 0.0}]}
                return {'return': []}
            if uri.endswith(('profiler.getVoices', 'profiler.getBusses', 'profiler.getAudioObjects')):
                if failure == 'reader-error' and uri.endswith('getVoices'):
                    raise RuntimeError('fake voice read unavailable')
                common = {'gameObjectID': game_object, 'gameObjectName': 'Transport/Soundcaster'}
                if uri.endswith('getVoices'):
                    row = {**common, 'pipelineID': 42, 'objectGUID': sound_id, 'objectName': self.rows[sound_id]['name'],
                        'playingID': 7, 'soundID': 8, 'playTargetID': 8, 'playTargetGUID': sound_id,
                        'playTargetName': self.rows[sound_id]['name'], 'baseVolume': -3.5, 'gameAuxSendVolume': 0,
                        'envelope': 0, 'normalizationGain': 0, 'lowPassFilter': 0, 'highPassFilter': 0,
                        'priority': 50, 'isStarted': True, 'isVirtual': False, 'isForcedVirtual': False}
                elif uri.endswith('getBusses'):
                    row = {**common, 'pipelineID': 43, 'objectGUID': bus_id, 'objectName': self.rows[bus_id]['name'],
                        'mixBusID': 123, 'deviceID': 0, 'volume': 0, 'downstreamGain': 0,
                        'voiceCount': 1, 'depth': 1, 'effectCount': 0}
                    if version in ('2021.1', '2022.1'):
                        row['mixerID'] = row.pop('effectCount')
                    if mixing_bus:
                        # R104 actually observed Main's mixing pipeline while
                        # query-object correctly returned logical OutputBus Cars.
                        row.update(pipelineID=2, objectGUID='{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}',
                            objectName='Main Audio Bus' if version == '2025.1' else 'Master Audio Bus', depth=0)
                        if mixing_bus == 'wrong-game-object':
                            row['gameObjectID'] = 2
                        elif mixing_bus == 'malformed':
                            row['gameObjectID'] = 'not-a-native-uint64'
                else:
                    row = {**common, 'audioObjectID': 44, 'audioObjectName': '', 'busPipelineID': 43,
                        'busGUID': bus_id, 'busID': 123, 'busName': self.rows[bus_id]['name'], 'instigatorPipelineID': 42,
                        'effectClassID': 0, 'effectIndex': 0, 'effectPluginName': '', 'spatializationMode': 0,
                        'x': 0, 'y': 0, 'z': 0, 'spread': 0, 'focus': 0, 'channelConfig': 4,
                        'metadata': [], 'rmsMeter': [-12.5], 'peakMeter': [-10.5]}
                    if mixing_bus:
                        row.update(busPipelineID=2, busGUID='{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}',
                            busName='Main Audio Bus' if version == '2025.1' else 'Master Audio Bus')
                if failure == 'unattributed-readers':
                    row.update(gameObjectID=2, gameObjectName='Unrelated capture participant')
                    row['busGUID' if uri.endswith('getAudioObjects') else 'objectGUID'] = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
                rows = [] if failure == 'empty-readers' else [row]
                if mixing_bus == 'mixed' and uri.endswith('getBusses'):
                    rows.append({**row, 'pipelineID': 3})
                if partial_seed is not None and partial_seed == ('voices' if uri.endswith('getVoices') else 'busses' if uri.endswith('getBusses') else None):
                    rows = [{**row, 'pipelineID': 99}, *[
                        {**row, 'gameObjectID': 2, 'pipelineID': 100 + i,
                            'objectGUID': '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'} for i in range(31)], row]
                    # The public newest-range page hides the earlier owned
                    # candidate. Native validation still returns the exact
                    # selected instance, so its legal handle cannot prove uniqueness.
                    native_filter = args.get('voicePipelineID', args.get('busPipelineID'))
                    if native_filter is not None:
                        rows = [item for item in rows if item['pipelineID'] == native_filter]
                return {'return': [{key: value for key, value in item.items() if key in options['return']} for item in rows]}
            if uri.endswith('profiler.getGameObjects'):
                return {'return': [] if failure == 'empty-readers' else [
                    {'id': 2 if failure == 'unattributed-readers' else game_object,
                        'name': 'Transport/Soundcaster',
                        'registrationTime' if version == '2022.1' else 'registerTime': 0,
                        'unregistrationTime' if version == '2022.1' else 'unregisterTime': -1}]}
            if uri.endswith('profiler.setCursorTime'):
                self.user_time = 1490
                return {'return': self.user_time}
            if uri.endswith('profiler.getMeters'):
                if failure == 'empty-meter':
                    return {'meters': []}
                row = self.rows[bus_id]
                if version == '2024.1' and row['@BusChannelConfig'] == 0:
                    row = next(item for item in self.rows.values() if item['name'] == 'Master Audio Bus')
                return {'meters': [{'object': {key: deepcopy(row[key]) for key in options.get('return', ['id', 'name']) if key in row},
                    'source': 'Bus', 'configurationName': '1.0', 'configurationMask': 4,
                    'configurationType': 'Standard', 'channels': [{'name': 'C', 'value': -12.5}]}]}
            if uri.endswith('profiler.registerMeter'):
                self.registered = True
                return {}
            if uri.endswith('profiler.unregisterMeter'):
                if failure == 'cleanup':
                    raise RuntimeError('fake unregister failure')
                self.registered = False
                return {}
            if uri.endswith('profiler.saveCapture'):
                Path(args['file']).write_bytes(b'opaque fake capture; no native format claim')
                return {}
            if uri.endswith('log.get'):
                return {'items': deepcopy(self.logs[args['channel']])}
            if uri.endswith('log.addItem'):
                self.logs['general'].append({'message': args['message'], 'severity': args['severity'],
                    'time': 2, 'messageId': 'Custom'})
                return {}
            if uri.endswith('log.clear'):
                self.logs[args['channel']] = []
                return {}
            if uri.endswith('profiler.stopCapture') and failure == 'explicit-stop-capture':
                raise RuntimeError('fake explicit stop capture failure')
            if uri.endswith('profiler.startCapture') and failure == 'cursor-setup-verification':
                return {'return': 'not an integer capture time'}
            if uri.endswith(('profiler.startCapture', 'profiler.stopCapture')):
                return {'return': 1500}
            if uri.endswith(('profiler.enableProfilerData', 'transport.useOriginals', 'transport.prepare')):
                if failure == 'cursor-cleanup' and uri.endswith('enableProfilerData') and not args['dataTypes'][0]['enable']:
                    raise RuntimeError('fake cursor capture-data cleanup uncertainty')
                if failure == 'disable-readers' and uri.endswith('enableProfilerData') and not args['dataTypes'][0]['enable']:
                    raise RuntimeError('fake capture-data cleanup uncertainty')
                return {}
            return super().call(uri, args, options)

    client = Client()
    def factory(*, skill_source, runtime, version, receipts):
        env = _env(runtime.owned_root, version=version)
        set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
        env['WWISE_EVIDENCE_DIR'] = runtime.runner_environment['WWISE_EVIDENCE_DIR']
        def call(argv):
            native_calls_before = len(client.calls)
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            if '--runtime-page' in argv:
                assert len(client.calls) == native_calls_before, 'Cached continuation dispatched an external native call'
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            if not (failure == 'cursor-setup-verification' and argv[0] == 'verify'):
                assert code == 0, json.dumps(payload, ensure_ascii=False)
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[nodeid])
    call = batch.node_gateway(nodeid)
    return batch, call, client, collect_owned_capture


def _finish(batch, tmp_path, monkeypatch, *, passed):
    from tests.destructive.support import authoring_batch
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    target = tmp_path / 'capture-categories.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    item = SimpleNamespace(nodeid=batch.selected_nodeids[0],
        _waapi_phase_reports={'setup': 'passed', 'call': 'passed' if passed else 'failed'})
    batch.prepare_stop([item])
    item._waapi_phase_reports['teardown'] = 'passed'
    final = batch.finalize([item], terminal=True, exitstatus=0 if passed else 1)
    return final, json.loads(target.read_text().splitlines()[-1])


def test_cursor_moves_reach_four_persisted_final_categories(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, cursor_moves=True)
    assert not (batch.runtime.sandbox.sandbox_path / 'Originals').exists()
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    categories = record['categories']
    assert [row['category'] for row in categories] == [
        'profiler-cursor-first-frame', 'profiler-cursor-next-frame',
        'profiler-cursor-last-frame', 'profiler-cursor-previous-frame']
    assert all(row['status'] == row['business_outcome'] == 'PASS' and row['batch_finalization']
        for row in categories)
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report_path = Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json'
    report = json.loads(report_path.read_text())
    assert report['complete'] is True and report['cleanup']['complete'] is True
    assert [row['evidence']['returned_time_ms'] for row in report['outcomes'].values()] == [100, 110, 1500, 1490]
    assert all(row['evidence']['observed_time_ms'] == row['evidence']['returned_time_ms']
        and row['evidence']['capture_data_completeness_verified'] is False
        for row in report['outcomes'].values())
    moves = [args['position'] for uri, args, _ in client.calls if uri.endswith('profiler.moveCursor')]
    assert moves == ['first', 'next', 'last', 'previous']
    assert sum(uri.endswith('profiler.getCursorTime') and args['cursor'] == 'user'
        for uri, args, _ in client.calls) == 4
    assert not any(uri.endswith(('setCursorTime', 'getMeters', 'saveCapture', 'log.addItem',
        'log.clear', 'object.setProperty', 'getRTPCs', 'getCpuUsage', 'getLoadedMedia'))
        for uri, _, _ in client.calls)
    assert not any(uri.startswith('ak.wwise.core.transport.') for uri, _, _ in client.calls)
    assert report['public_call_count'] == len(archive['receipts'])
    assert report['total_reply_bytes'] == sum(len(json.dumps(row.get('payload', row), ensure_ascii=False).encode())
        for row in archive['receipts'])
    assert not client.transport and not client.registered and not batch.runtime.owned_root.exists()
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert report['public_call_count'] <= report['limits']['public_calls']
    (tmp_path / 'cursor-measured-budget.json').write_text(json.dumps({
        'public_calls': report['public_call_count'], 'substituted_native_calls': len(client.calls),
        'total_reply_bytes': report['total_reply_bytes'], 'report_bytes': report_path.stat().st_size,
        'archive_bytes': Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).stat().st_size,
        'limits': report['limits'], 'report_path': str(report_path)}, indent=2) + '\n')


def test_cursor_move_unavailable_retains_other_moves_and_blocks_final_acceptance(
        owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        cursor_moves=True, failure='cursor-unavailable')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    categories = {row['category']: row for row in record['categories']}
    unavailable = report['outcomes']['profiler-cursor-next-frame']
    assert unavailable['outcome'] == 'BLOCKED'
    assert unavailable['evidence']['returned_time_ms'] == unavailable['evidence']['observed_time_ms'] == -1
    assert unavailable['evidence']['transaction']['state'] == 'result_schema_checked'
    assert categories['profiler-cursor-next-frame']['business_outcome'] == 'BLOCKED'
    assert all(row['business_outcome'] == 'PASS' for name, row in categories.items()
        if name != 'profiler-cursor-next-frame')
    assert all(row['status'] != 'PASS' and 'batch_finalization' not in row for row in categories.values())
    assert report['cleanup']['complete'] is True and not client.transport
    assert [args['position'] for uri, args, _ in client.calls if uri.endswith('profiler.moveCursor')] == [
        'first', 'next', 'last', 'previous']


def test_cursor_move_failed_setup_verification_stops_before_moves_and_retains_cleanup(
        owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        cursor_moves=True, failure='cursor-setup-verification')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert all(row['business_outcome'] == 'BLOCKED' and row['status'] != 'PASS' for row in record['categories'])
    assert report['cleanup']['complete'] is True
    assert not any(uri.endswith('profiler.moveCursor') or uri.startswith('ak.wwise.core.transport.')
        for uri, _, _ in client.calls)
    failed = [row for row in archive['receipts'] if row['argv'][0] == 'verify'
        and row['payload'].get('state') == 'verification_failed']
    assert len(failed) == 1 and failed[0]['payload']['automatic_retry'] is False
    assert sum(uri.endswith('profiler.stopCapture') for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('failure', ['cursor-mismatch', 'cursor-cleanup', 'cursor-single-frame'])
def test_cursor_move_failures_preserve_partial_final_writer_evidence(
        owned_authoring, tmp_path, monkeypatch, failure):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        cursor_moves=True, failure=failure)
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    outcomes = {name: row['outcome'] for name, row in report['outcomes'].items()}
    categories = {row['category']: row for row in record['categories']}
    assert all(row['status'] != 'PASS' and 'batch_finalization' not in row for row in categories.values())
    assert {name: row['business_outcome'] for name, row in categories.items()} == outcomes
    assert report['public_call_count'] == len(archive['receipts'])
    assert report['total_reply_bytes'] == sum(len(json.dumps(row.get('payload', row), ensure_ascii=False).encode())
        for row in archive['receipts'])
    assert sum(uri.endswith('profiler.moveCursor') for uri, _, _ in client.calls) == 4
    assert sum(uri.endswith('profiler.stopCapture') for uri, _, _ in client.calls) == 1
    assert not client.transport and not batch.batch_seal_path.exists()
    assert record['source']['hash_before'] == record['source']['hash_after']
    if failure == 'cursor-mismatch':
        assert outcomes == {'profiler-cursor-first-frame': 'PASS', 'profiler-cursor-next-frame': 'FAIL',
            'profiler-cursor-last-frame': 'PASS', 'profiler-cursor-previous-frame': 'PASS'}
        failed = [row for row in archive['receipts'] if row['argv'][0] == 'verify'
            and row['payload'].get('state') == 'verification_failed']
        assert len(failed) == 1 and failed[0]['payload']['automatic_retry'] is False
        scope = failed[0]['payload']['verification']['verification_scope']['cursor_observation']
        assert scope['returned_time_ms'] == 110 and scope['observed_time_ms'] == 111
        assert report['cleanup']['complete'] is True


    elif failure == 'cursor-cleanup':
        assert set(outcomes.values()) == {'PASS'}
        assert report['cleanup']['complete'] is False
        assert [row['action'] for row in report['cleanup']['errors']] == ['disable-voices-data']
        failed = [row for row in archive['receipts'] if row['argv'][0] == 'execute'
            and row['payload'].get('state') == 'indeterminate']
        assert len(failed) == 1 and failed[0]['payload']['automatic_retry'] is False
        assert sum(uri.endswith('enableProfilerData') and args['dataTypes'][0]['enable'] is False
            for uri, args, _ in client.calls) == 1
    else:
        assert outcomes == {'profiler-cursor-first-frame': 'PASS', 'profiler-cursor-next-frame': 'BLOCKED',
            'profiler-cursor-last-frame': 'PASS', 'profiler-cursor-previous-frame': 'BLOCKED'}
        assert report['frame_relationship_scope']['distinct_endpoint_times_observed'] is False
        assert report['cleanup']['complete'] is True


@pytest.mark.parametrize('version,extra', [('2021.1', False), ('2022.1', False), ('2023.1', False),
    ('2024.1', False), ('2025.1', True), ('2025.1', False)])
def test_cursor_move_owner_requires_exact_single_2025_node(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import CURSOR_MOVES_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [CURSOR_MOVES_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        message = 'not available on the requested version' if version != '2025.1' else 'exact single 2025'
        with pytest.raises(pytest.UsageError, match=message):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_missing_only_capture_collects_new_facts_without_repeating_passed_reads_or_effects(
        owned_authoring, tmp_path, monkeypatch, version):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version=version, missing_reads=True, native_rtpc=True, mixing_bus='unique')
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    assert {row['category'] for row in record['categories']} == ({'profiler-contributions-bus-observation'}
        if version == '2021.1' else {'profiler-rtpcs-observation', 'profiler-contributions-bus-observation'})
    assert all(row['status'] == 'PASS' and row['parent_workflow_complete'] is False for row in record['categories'])
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['reader_call_count'] == (3 if version == '2021.1' else 4) and report['public_call_count'] <= 192
    assert report['reused_capture_evidence']['capture_time_ms'] == {
        '2021.1': 34752, '2022.1': 39861, '2023.1': 45888, '2024.1': 45621, '2025.1': 46869}[version]
    assert report['reused_capture_evidence']['candidate'] == 'a5884dcbb655d03a4537ed1e3553ac01e1d2fdb8'
    assert report['capture_position']['position_ms'] == 1500
    assert report['remaining_same_parent_obligations']['profiler-loaded-media-observation'] == ['2023.1', '2024.1', '2025.1']
    assert not any(uri.endswith(('getCpuUsage', 'getLoadedMedia', 'getStreamedMedia', 'getPerformanceMonitor',
        'getGameObjects', 'getAudioObjects', 'getMeters', 'registerMeter', 'setCursorTime', 'saveCapture',
        'log.addItem', 'log.clear', 'transport.prepare', 'object.setProperty')) for uri, _, _ in client.calls)
    contributions = [args for uri, args, _ in client.calls if uri.endswith('getVoiceContributions')]
    assert len(contributions) == 1 and contributions[0]['bussesPipelineID'] == [2]
    data = [args['dataTypes'] for uri, args, _ in client.calls if uri.endswith('enableProfilerData')]
    types = ('voices', 'voiceInspector') if version == '2021.1' else ('voices', 'voiceInspector', 'gameSyncs')
    assert data == [[{'dataType': item, 'enable': True} for item in types],
        [{'dataType': item, 'enable': False} for item in types]]
    targeted = [uri for uri, _, _ in client.calls if uri.endswith(('getVoices', 'getBusses', 'getRTPCs', 'getVoiceContributions'))]
    assert len(targeted) == (5 if version == '2021.1' else 6)
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']


@pytest.mark.parametrize('missing_only,partial_seed', [(True, 'voices'), (True, 'busses'),
    (False, 'voices'), (False, 'busses')])
def test_partial_capture_seed_never_certifies_unique_owned_contribution_in_final_writer(
        owned_authoring, tmp_path, monkeypatch, missing_only, partial_seed):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version='2025.1' if missing_only else '2021.1', capture_reads=True, missing_reads=missing_only,
        native_rtpc=True, mixing_bus='unique', partial_seed=partial_seed)
    collector_passed = True
    try:
        collect(batch, call)
    except AssertionError:
        collector_passed = False
    final, record = _finish(batch, tmp_path, monkeypatch, passed=collector_passed)
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert final['outcome'] == 'FAIL'
    name = 'profiler-voices-observation' if partial_seed == 'voices' else 'profiler-busses-observation'
    observation = (report['seed_observations'] if missing_only else report['outcomes'])[name]
    assert observation['outcome'] == 'BLOCKED' and observation['evidence']['complete'] is False
    raw = observation['evidence']['agent_result']
    assert raw['complete'] is False and raw['total_count'] == 33 and 0 < raw['returned_count'] < 33
    assert report['runtime_mixing_bus']['selected_observed_instance'] is None
    category = next(row for row in record['categories'] if row['category'] == 'profiler-contributions-bus-observation')
    assert category['business_outcome'] == 'BLOCKED' and category['status'] == 'blocked'
    assert not any(args.get('bussesPipelineID') for uri, args, _ in client.calls if uri.endswith('getVoiceContributions'))
    assert sum(uri.endswith('getVoices') for uri, _, _ in client.calls) == 1
    assert sum(uri.endswith('getBusses') for uri, _, _ in client.calls) == 1
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert record['source']['hash_before'] == record['source']['hash_after']


def test_retained_main_bus_read_and_filter_facts_are_meaningful_owned_observations(
        owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version='2021.1', capture_reads=True, native_rtpc=True, mixing_bus='unique')
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    for name in ('profiler-busses-observation', 'profiler-bus-instance-filter'):
        evidence = report['outcomes'][name]['evidence']
        assert evidence['owned_identity_observed'] is True
        assert evidence['agent_result']['return'][0]['objectGUID'] == '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}'
        assert next(row for row in record['categories'] if row['category'] == name)['status'] == 'PASS'
    assert report['runtime_mixing_bus']['logical_output_equals_runtime_bus'] is False
    assert report['fixture_before'] == report['fixture_after']


def test_retained_cpu_page_ceiling_keeps_partial_data_without_another_native_read(
        owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        capture_reads=True, failure='cpu-page-bound')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    cpu = report['outcomes']['profiler-cpu-observation']
    assert cpu['outcome'] == 'BLOCKED' and cpu['evidence']['complete'] is False
    assert len(cpu['evidence']['agent_result_pages']) == 8
    assert len(cpu['evidence']['rows_native_order']) == 8
    assert sum(uri.endswith('getCpuUsage') for uri, _, _ in client.calls) == 1
    assert report['retained_page_call_count'] == 7 and report['public_call_count'] <= 192
    assert next(row for row in record['categories'] if row['category'] == 'profiler-cpu-observation')['business_outcome'] == 'BLOCKED'


@pytest.mark.parametrize('mixing_bus', ['unique', 'mixed', 'wrong-game-object', 'malformed'])
def test_observed_mixing_bus_and_logical_output_remain_distinct_through_final_writer(
        owned_authoring, tmp_path, monkeypatch, mixing_bus):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        capture_reads=True, failure='nonempty-media', native_rtpc=True, mixing_bus=mixing_bus)
    if mixing_bus == 'unique':
        collect(batch, call)
    else:
        with pytest.raises(AssertionError):
            collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=mixing_bus == 'unique')
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    category = next(row for row in record['categories'] if row['category'] == 'profiler-contributions-bus-observation')
    if mixing_bus == 'unique':
        assert final['outcome'] == category['status'] == 'PASS'
        association = report['runtime_mixing_bus']
        assert association['logical_output_bus_id'] == '{33329D23-BCDD-4D1A-9734-2403A3428FAE}'
        assert association['selected_observed_instance']['objectGUID'] == '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}'
        assert association['selected_observed_instance']['pipelineID'] == 2
        assert association['logical_output_equals_runtime_bus'] is False
        assert any(args.get('bussesPipelineID') == [2] for uri, args, _ in client.calls if uri.endswith('getVoiceContributions'))
    else:
        assert final['outcome'] == 'FAIL' and category['business_outcome'] == 'BLOCKED'
        assert not any(args.get('bussesPipelineID') for uri, args, _ in client.calls if uri.endswith('getVoiceContributions'))
        assert report['outcomes']['profiler-contributions-dry-observation']['outcome'] == 'PASS'
    assert report['fixture_before'] == report['fixture_after'] and report['cleanup']['complete']
    assert not any(args.get('property') == 'BusChannelConfig' for uri, args, _ in client.calls if uri.endswith('setProperty'))


def test_owned_rtpc_read_preserves_actual_native_value_without_global_setter_effect(
        owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version='2021.1', capture_reads=True, native_rtpc=True)
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    evidence = report['outcomes']['profiler-rtpcs-observation']['evidence']
    assert evidence['rpm_read_row_indexes'] == [0]
    assert evidence['agent_result']['return'][0] == {'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}',
        'name': 'RPM', 'gameObjectId': 18446744073709551614, 'value': 1000.0}
    assert evidence['setter_effect_verified'] is False
    assert not any(uri.startswith('ak.soundengine.') for uri, _, _ in client.calls)
    assert next(row for row in record['categories'] if row['category'] == 'profiler-rtpcs-observation')['status'] == 'PASS'


@pytest.mark.parametrize('cpu_native_version,row_count', [('2024.1', 34), ('2025.1', 33)])
def test_retained_native_cpu_rows_reach_final_writer_without_a_second_native_read(
        owned_authoring, tmp_path, monkeypatch, cpu_native_version, row_count):
    import hashlib
    original = tmp_path / 'retained-original-cpu-receipt.json'
    original.write_text(json.dumps(NATIVE_CPU_2024 if cpu_native_version == '2024.1' else NATIVE_CPU_2025))
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version=cpu_native_version, capture_reads=True, failure='nonempty-media', cpu_native_version=cpu_native_version)
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['version'] == cpu_native_version
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archived['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    cpu = report['outcomes']['profiler-cpu-observation']
    assert cpu['outcome'] == 'PASS' and cpu['evidence']['complete'] is True
    pages = cpu['evidence']['agent_result_pages']
    assert len(pages) == 3 and sum(len(page['return']) for page in pages) == row_count
    assert len({page['snapshot_sha256'] for page in pages}) == 1
    capture_time, snapshot = {'2024.1': ('45621', '307fa2b3b5fac363b5146d671cc6679dbabe5d00f1800631daf7179d75fd15b6'),
        '2025.1': ('46869', '155343dcd3b55706c21969f876d80162b7466493c7e70e919516f0c37f55a1b7')}[cpu_native_version]
    assert pages[0]['snapshot_sha256'] == snapshot
    assert all(page['total_count'] == row_count and page['profiler_position'] == capture_time for page in pages)
    assert cpu['evidence']['rows_native_order'] == json.loads(original.read_text())['return']
    assert pages[0]['complete'] is False and pages[-1]['complete'] is True
    continuations = [receipt for receipt in archived['receipts']
        if receipt['argv'][:2] == ['core-call', 'ak.wwise.core.profiler.getCpuUsage']
        and '--runtime-page' in receipt['argv']]
    assert len(continuations) == 2
    assert all(receipt['payload']['native_read_dispatched'] is False for receipt in continuations)
    assert sum(uri.endswith('getCpuUsage') for uri, _, _ in client.calls) == 1
    assert next(row for row in record['categories'] if row['category'] == 'profiler-cpu-observation')['status'] == 'PASS'
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before


def test_capture_read_extension_keeps_new_data_and_empty_media_in_final_archive(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, capture_reads=True)
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['reader_call_count'] == 9 and report['public_call_count'] <= 192
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    categories = {row['category']: row for row in record['categories']}
    assert set(categories) == {'profiler-rtpcs-observation', 'profiler-contributions-dry-observation',
        'profiler-contributions-bus-observation', 'profiler-cpu-observation', 'profiler-loaded-media-observation',
        'profiler-performance-observation', 'profiler-streamed-media-observation'}
    assert all(row['business_outcome'] == ('BLOCKED' if name in (
        'profiler-loaded-media-observation', 'profiler-streamed-media-observation') else 'PASS')
        and row['status'] == 'blocked' for name, row in categories.items())
    assert all(report['outcomes'][name]['evidence']['observation_status'] == 'PASS' for name in (
        'profiler-loaded-media-observation', 'profiler-streamed-media-observation'))
    contribution = report['outcomes']['profiler-contributions-dry-observation']['evidence']['agent_result']
    assert contribution['contribution_reported'] is True and contribution['dsf']['value'] == 0.0
    assert set(report['seed_observations']) == {'profiler-voices-observation', 'profiler-busses-observation'}
    assert not any(uri.endswith(('getGameObjects', 'getAudioObjects', 'getMeters', 'setCursorTime', 'saveCapture',
        'log.addItem', 'log.clear')) for uri, _, _ in client.calls)
    targeted = [(uri, args) for uri, args, _ in client.calls if '.profiler.get' in uri and not uri.endswith('getCursorTime')]
    assert len(targeted) == 12 and all(args['time'] == 1500 for _, args in targeted)
    assert [args.get('bussesPipelineID', []) for uri, args in targeted if uri.endswith('getVoiceContributions')] == [[], [43]]
    assert not client.transport and batch.lifecycle_result.quarantine_path and not batch.batch_seal_path.exists()


def test_2022_capture_read_flow_preserves_older_fields_in_persisted_final_acceptance(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version='2022.1', capture_reads=True)
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['version'] == '2022.1'
    assert len(record['categories']) == 10 and all(row['status'] == 'PASS' for row in record['categories'])
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['reader_call_count'] == 10 and report['public_call_count'] <= 192
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    bus = report['outcomes']['profiler-busses-observation']['evidence']['agent_result']['return'][0]
    assert bus['mixerID'] == 0 and 'effectCount' not in bus
    game = report['outcomes']['profiler-game-objects-observation']['evidence']['agent_result']['game_objects'][0]
    assert game == {'id': 1, 'name': 'Transport/Soundcaster', 'register_time': 0, 'unregister_time': -1}
    contribution = report['outcomes']['profiler-contributions-dry-observation']['evidence']['agent_result']
    assert contribution['dsf'] == {'feature_available': False, 'reported': False, 'value': None}
    assert 'index' not in contribution['objects'][0] and 'DSF' not in contribution['objects'][0]
    assert sum(uri.endswith('transport.prepare') for uri, _, _ in client.calls) == 1
    assert not any(uri.endswith(('transport.useOriginals', 'getCpuUsage', 'getLoadedMedia', 'getPerformanceMonitor',
        'getStreamedMedia', 'getMeters', 'setCursorTime', 'saveCapture', 'log.addItem', 'log.clear')) for uri, _, _ in client.calls)
    assert not client.transport and not batch.runtime.owned_root.exists()


def test_capture_level_media_rows_pass_without_inventing_sound_or_control_attribution(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        capture_reads=True, failure='nonempty-media')
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and len(record['categories']) == 7
    assert all(row['status'] == row['business_outcome'] == 'PASS' for row in record['categories'])
    for row in record['categories']:
        if row['category'] in ('profiler-loaded-media-observation', 'profiler-streamed-media-observation'):
            assert row['attribution_scope'] == 'capture' and row['owned_identity_observed'] is False
            assert row['preparation_or_streaming_control_effect_verified'] is False
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['public_call_count'] <= 192 and report['reader_call_count'] == 9
    assert report['outcomes']['profiler-rtpcs-observation']['evidence'].get('setter_effect_verified', False) is False
    assert report['outcomes']['profiler-rtpcs-observation']['evidence']['rpm_read_row_indexes'] == [0]
    assert [(args['property'], args['value']) for uri, args, _ in client.calls if uri.endswith('object.setProperty')] == [
        ('IsStreamingEnabled', True), ('IsStreamingEnabled', False)]
    assert not any(uri.startswith('ak.soundengine.') for uri, _, _ in client.calls)
    assert not client.transport and not batch.runtime.owned_root.exists()


@pytest.mark.parametrize('version', ['2021.1', '2023.1', '2024.1'])
def test_older_capture_read_batch_keeps_version_fields_and_independent_file_log_outcomes(
        owned_authoring, tmp_path, monkeypatch, version):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        version=version, capture_reads=True, failure='nonempty-media')
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['version'] == version
    assert all(row['status'] == 'PASS' for row in record['categories'])
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['public_call_count'] <= 192
    assert report['reader_call_count'] == (9 if version == '2021.1' else 14)
    assert report['fixture_before'] == report['fixture_after'] and report['cleanup']['complete']
    bus = report['outcomes']['profiler-busses-observation']['evidence']['agent_result']['return'][0]
    assert ('mixerID' in bus) is (version == '2021.1')
    assert ('effectCount' in bus) is (version != '2021.1')
    obj = report['outcomes']['profiler-contributions-dry-observation']['evidence']['agent_result']['objects'][0]
    assert ('index' in obj) is (version == '2024.1') and 'DSF' not in obj
    assert not any(uri.endswith(('getMeters', 'registerMeter', 'setCursorTime')) for uri, _, _ in client.calls)
    if version == '2021.1':
        assert len(record['categories']) == 9
        assert not any(uri.endswith(('getGameObjects', 'transport.prepare', 'transport.useOriginals', 'saveCapture',
            'log.addItem', 'log.clear')) for uri, _, _ in client.calls)
    else:
        assert len(record['categories']) == 17
        budget = report['optional_effect_budget']
        assert budget['admitted'] and budget['calls_before'] + 29 + 52 <= 192
        assert all(report['outcomes'][name]['outcome'] == 'PASS' for name in (
            'profiler-saved-capture-artifact', 'runtime-owned-log-add', 'runtime-owned-log-clear'))
        assert all('reader_observation_status' not in row for row in record['categories']
            if row['category'] in ('profiler-saved-capture-artifact', 'runtime-owned-log-add', 'runtime-owned-log-clear'))
        assert sum(uri.endswith('profiler.saveCapture') for uri, _, _ in client.calls) == 1
        assert sum(uri.endswith('log.addItem') for uri, _, _ in client.calls) == 1
        assert sum(uri.endswith('log.clear') for uri, _, _ in client.calls) == 1
    assert not client.transport and not batch.runtime.owned_root.exists()


@pytest.mark.parametrize('reported', [True, False])
def test_reported_scalar_contribution_and_unreported_payload_remain_distinct_in_final_writer(
        owned_authoring, tmp_path, monkeypatch, reported):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        capture_reads=True, failure='scalar-contribution' if reported else 'missing-contribution')
    if reported:
        collect(batch, call)
    else:
        with pytest.raises(AssertionError):
            collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=reported)
    assert final['outcome'] == ('PASS' if reported else 'FAIL')
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    for name in ('profiler-contributions-dry-observation', 'profiler-contributions-bus-observation'):
        observation = report['outcomes'][name]
        evidence = observation['evidence']
        assert observation['outcome'] == ('PASS' if reported else 'BLOCKED')
        assert evidence['observation_status'] == 'PASS'
        assert evidence['agent_result']['contribution_reported'] is reported
        if reported:
            assert evidence['agent_result']['objects'] == []
            assert evidence['tree_nonempty'] is False and evidence['nonempty'] is True
            assert evidence['owned_identity_observed'] is True
            assert evidence['agent_result']['volume'] == evidence['agent_result']['lpf'] == evidence['agent_result']['hpf'] == 0.0
        category = next(row for row in record['categories'] if row['category'] == name)
        assert category['business_outcome'] == ('PASS' if reported else 'BLOCKED')
        assert category['status'] == ('PASS' if reported else 'blocked')
    assert report['reader_call_count'] == 9 and report['public_call_count'] <= 192
    assert next(row for row in record['categories'] if row['category'] == 'profiler-rtpcs-observation')[
        'attribution_scope'] == 'owned-rtpc-read'
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert sum(uri.endswith('getVoiceContributions') for uri, _, _ in client.calls) == 2


@pytest.mark.parametrize('failure', ['empty-extra', 'partial-extra', 'disable-readers'])
def test_capture_read_missing_partial_and_cleanup_results_reach_final_writer(
        owned_authoring, tmp_path, monkeypatch, failure):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        capture_reads=True, failure=failure)
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    assert not batch.batch_seal_path.exists()
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['reader_call_count'] == 9 and report['public_call_count'] <= 192
    assert all(row['status'] == 'blocked' and 'batch_finalization' not in row for row in record['categories'])
    assert report['outcomes']['profiler-rtpcs-observation']['evidence'].get('setter_effect_verified', False) is False
    assert not client.transport and report['fixture_before'] == report['fixture_after']
    if failure == 'empty-extra':
        assert all(row['outcome'] == 'BLOCKED' and row['evidence']['observation_status'] == 'PASS'
            and row['evidence']['nonempty'] is False for row in report['outcomes'].values())
    elif failure == 'partial-extra':
        cpu = report['outcomes']['profiler-cpu-observation']
        assert cpu['outcome'] == 'BLOCKED' and cpu['evidence']['complete'] is False
        assert cpu['evidence']['agent_result']['returned_count'] == 25
        assert len(cpu['evidence']['agent_result']['return']) == 25
        assert cpu['evidence']['agent_result']['total_count'] == 65
        assert sum(uri.endswith('profiler.getCpuUsage') for uri, _, _ in client.calls) == 1
        assert report['outcomes']['profiler-rtpcs-observation']['outcome'] == 'PASS'
    else:
        assert all(row['outcome'] == 'PASS' for row in report['outcomes'].values())
        assert [row['action'] for row in report['cleanup']['errors']] == ['disable-capture-read-data']
        assert sum(uri.endswith('enableProfilerData') and not args['dataTypes'][0]['enable']
            for uri, args, _ in client.calls) == 1
        failed = [row for row in archive['receipts'] if row['argv'][0] == 'execute'
            and row['exit_code'] != 0
            and row['payload'].get('dispatch_result', {}).get('api') == 'ak.wwise.core.profiler.enableProfilerData']
        assert len(failed) == 1 and failed[0]['payload']['state'] == 'indeterminate'
        assert failed[0]['payload']['automatic_retry'] is False
    assert report['cleanup']['complete'] is (failure != 'disable-readers')
    assert record['source']['hash_before'] == record['source']['hash_after']


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('extra', [False, True])
def test_missing_capture_owner_requires_its_exact_single_node(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import CAPTURE_MISSING_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    staged = []
    def stage(sandbox, io_root, *, version):
        assert sandbox.sandbox_path.is_dir() and sandbox.source_root.is_dir()
        assert sandbox.sandbox_path != sandbox.source_root
        assert sandbox.sandbox_path.is_relative_to(tmp_path / 'batch/owned/sandbox-root')
        assert io_root == tmp_path / 'batch/owned/io' and io_root.is_dir()
        staged.append(version)
    monkeypatch.setattr(authoring_batch, 'stage_owned_capture_read_media', stage)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [CAPTURE_MISSING_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if extra:
        with pytest.raises(pytest.UsageError, match='exact single node|not available'):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events and not staged
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
        assert staged == [version] and events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
        assert events[-1][1]['selected_nodeids'] == (CAPTURE_MISSING_NODEID,)


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('extra', [False, True])
def test_capture_read_owner_admits_only_one_node_on_each_pinned_version(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import CAPTURE_READS_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    staged = []
    def stage(sandbox, io_root, *, version):
        assert sandbox.sandbox_path.is_dir() and sandbox.source_root.is_dir()
        assert sandbox.sandbox_path != sandbox.source_root
        assert sandbox.sandbox_path.is_relative_to(tmp_path / 'batch/owned/sandbox-root')
        assert io_root == tmp_path / 'batch/owned/io' and io_root.is_dir()
        staged.append(version)
    monkeypatch.setattr(authoring_batch, 'stage_owned_capture_read_media', stage)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [CAPTURE_READS_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if extra:
        with pytest.raises(pytest.UsageError, match='exact single node|not available'):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
        assert staged == [version]
        assert events[-1][1]['selected_nodeids'] == (CAPTURE_READS_NODEID,)


def test_owned_2025_reader_flow_reaches_seven_independent_archived_categories(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, readers=True)
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert {row['category'] for row in record['categories']} == {
        'profiler-voices-observation', 'profiler-busses-observation', 'profiler-audio-objects-observation',
        'profiler-game-objects-observation', 'profiler-voice-instance-filter',
        'profiler-bus-instance-filter', 'profiler-audio-objects-bus-filter'}
    assert all(row['status'] == row['business_outcome'] == 'PASS' and row['cleanup_complete']
        and row['batch_finalization'] and row['reader_observation_status'] == 'PASS'
        and row['owned_identity_observed'] is True for row in record['categories'])
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['reader_call_count'] == 7 and report['capture_position']['position_ms'] == 1500
    assert all(row['evidence']['position_ms'] == 1500 for row in report['outcomes'].values())
    voice = report['outcomes']['profiler-voices-observation']['evidence']
    assert voice['agent_result']['return'][0]['baseVolume'] == -3.5
    assert voice['identity_ties']['sound_row_indexes'] == [0]
    assert voice['identity_ties']['transport_game_object_row_indexes'] == [0]
    assert report['outcomes']['profiler-audio-objects-observation']['evidence']['agent_result']['return'][0]['metadata'] == []
    assert report['outcomes']['profiler-game-objects-observation']['evidence']['agent_result']['game_objects'] == [
        {'id': 1, 'name': 'Transport/Soundcaster', 'register_time': 0, 'unregister_time': -1}]
    reader_argv = [row['argv'] for row in archive['receipts'] if row['argv'][0] == 'profiler-game-objects'
        or row['argv'][:1] == ['core-call'] and row['argv'][1].endswith(('getVoices', 'getBusses', 'getAudioObjects'))]
    assert len(reader_argv) == 7
    native = [(uri, args) for uri, args, _ in client.calls if uri.endswith(('getVoices', 'getBusses', 'getAudioObjects', 'getGameObjects'))]
    assert len(native) == 10 and all(args['time'] == 1500 for _, args in native)
    assert [args for uri, args in native if 'voicePipelineID' in args] == [{'time': 1500, 'voicePipelineID': 42}]
    assert [args for uri, args in native if 'busPipelineID' in args] == [
        {'time': 1500, 'busPipelineID': 43}, {'time': 1500, 'busPipelineID': 43}]
    assert not any(uri.endswith(('getMeters', 'registerMeter', 'unregisterMeter', 'setCursorTime', 'saveCapture', 'log.addItem', 'log.clear'))
        for uri, _, _ in client.calls)
    assert not client.transport and report['fixture_before'] == report['fixture_after']
    assert not batch.runtime.owned_root.exists()
    assert [(args['dataTypes'][0]['dataType'], args['dataTypes'][0]['enable'])
        for uri, args, _ in client.calls if uri.endswith('enableProfilerData')] == [
        ('voices', True), ('audioObjects', True), ('audioObjects', False), ('voices', False)]


@pytest.mark.parametrize('failure', ['empty-readers', 'reader-error', 'disable-readers', 'explicit-stop-capture'])
def test_owned_reader_missing_or_uncertain_results_retain_independent_archive_without_acceptance(
        owned_authoring, tmp_path, monkeypatch, failure):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        readers=True, failure=failure)
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert all(row['status'] != 'PASS' and 'batch_finalization' not in row for row in record['categories'])
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archived['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    categories = {row['category']: row for row in record['categories']}
    assert report['complete'] is False and len(report['outcomes']) == 7
    assert not client.transport
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert sum(uri.endswith('profiler.stopCapture') for uri, _, _ in client.calls) == 1
    assert report['fixture_before'] == report['fixture_after']
    if failure == 'empty-readers':
        assert report['reader_call_count'] == 4
        assert all(row['outcome'] == 'BLOCKED' for row in report['outcomes'].values())
        assert all(row['business_outcome'] == 'BLOCKED' for row in categories.values())
        assert all(row['evidence']['nonempty'] is False for row in list(report['outcomes'].values())[:4])
        assert not any('voicePipelineID' in args or 'busPipelineID' in args
            for uri, args, _ in client.calls if uri.endswith(('getVoices', 'getBusses', 'getAudioObjects')))
    elif failure == 'reader-error':
        assert report['reader_call_count'] == 6
        assert categories['profiler-voices-observation']['business_outcome'] == 'FAIL'
        assert categories['profiler-voice-instance-filter']['business_outcome'] == 'BLOCKED'
        assert all(row['business_outcome'] == 'PASS' for name, row in categories.items()
            if name not in ('profiler-voices-observation', 'profiler-voice-instance-filter'))
        assert 'fake voice read unavailable' in json.dumps(archived['receipts'])
    else:
        assert report['reader_call_count'] == 7
        assert all(row['business_outcome'] == 'PASS' and row['cleanup_complete'] is False for row in categories.values())
        failed = [row for row in archived['receipts'] if row['argv'][0] == 'execute'
            and row['payload'].get('state') == 'indeterminate']
        assert len(failed) == (2 if failure == 'disable-readers' else 1)
        assert all(row['payload']['automatic_retry'] is False for row in failed)
        assert report['cleanup']['complete'] is False
        assert len(report['cleanup']['errors']) == len(failed)
    if failure in ('empty-readers', 'reader-error'):
        assert report['cleanup']['complete'] is True
    assert not batch.batch_seal_path.exists()


def test_nonempty_unattributed_reader_rows_never_grant_owned_capture_credit(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch,
        readers=True, failure='unattributed-readers')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archived['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['reader_call_count'] == 7 and report['cleanup']['complete'] is True
    assert all(row['outcome'] == 'BLOCKED' and row['evidence']['observation_status'] == 'PASS'
        and row['evidence']['nonempty'] is True and row['evidence']['owned_identity_observed'] is False
        for row in report['outcomes'].values())
    assert all(row['business_outcome'] == 'BLOCKED' and row['status'] == 'blocked'
        and row['reader_observation_status'] == 'PASS' and row['owned_identity_observed'] is False
        and 'batch_finalization' not in row for row in record['categories'])
    assert not client.transport and not batch.batch_seal_path.exists()


@pytest.mark.parametrize('version,extra', [('2021.1', False), ('2022.1', False), ('2023.1', False),
    ('2024.1', False), ('2025.1', True), ('2025.1', False)])
def test_reader_owner_requires_exact_single_2025_selection(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import READERS_2025_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [READERS_2025_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        message = 'Selected owned Authoring node is not available on the requested version' if version != '2025.1' else 'only their matching 2025'
        with pytest.raises(pytest.UsageError, match=message):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'


def test_owned_2024_meter_public_flow_reaches_its_archived_final_category(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, version='2024.1')
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['version'] == '2024.1'
    category, = record['categories']
    assert category['category'] == 'profiler-meter-object-observation'
    assert category['status'] == category['business_outcome'] == 'PASS' and category['batch_finalization']
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert list(report['outcomes']) == ['profiler-meter-object-observation']
    obj = report['outcomes']['profiler-meter-object-observation']['evidence']['meters'][0]['object']
    assert obj['path'] == r'\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\Environmental\SFX\Guns'
    assert obj['volume_db'] == 0.0 and obj['related']['parent']['volume_db'] == 0.0
    assert obj['related']['parent']['object'] == {'id': '{ED2BCAC8-D7B6-4448-8900-439B557894F4}', 'name': 'SFX'}
    assert report['fixture_before']['sound']['output_bus']['id'] == '{06362E8D-5A32-497A-B063-3DA95963CE47}'
    assert report['fixture_after'] == report['fixture_before'] and report['cleanup']['complete'] is True
    assert report['fixture_before']['bus']['properties']['BusChannelConfig'] == 0
    assert next(row['bus_processing'] for row in report['setup'] if 'bus_processing' in row)['verification']['business_state_verified'] is True
    assert any(row['action'] == 'restore-bus-configuration' for row in report['cleanup']['receipts'])
    assert report['fixture_media']['proof']['sha256'] == report['fixture_media']['staging']['source']['sha256']
    assert report['cleanup']['capture_settings_prior_state_restored'] is False
    assert report['cleanup']['audition_media_prior_state_restored'] is False
    assert not client.transport and not client.registered and not batch.runtime.owned_root.exists()
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert not any(uri.endswith(('setCursorTime', 'saveCapture', 'log.addItem', 'log.clear')) for uri, _, _ in client.calls)
    assert [(args['object'], args['property'], args['value']) for uri, args, _ in client.calls if uri.endswith('object.setProperty')] == [
        ('{06362E8D-5A32-497A-B063-3DA95963CE47}', 'BusChannelConfig', 12546),
        ('{06362E8D-5A32-497A-B063-3DA95963CE47}', 'BusChannelConfig', 0)]


def test_owned_2024_empty_meter_fails_final_acceptance_after_complete_cleanup(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, version='2024.1', failure='empty-meter')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and record['version'] == '2024.1'
    category, = record['categories']
    assert category['category'] == 'profiler-meter-object-observation'
    assert category['status'] == category['business_outcome'] == 'FAIL'
    assert category['cleanup_complete'] is True and 'batch_finalization' not in category
    assert batch.lifecycle_result.quarantine_path and not client.transport and not client.registered
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    observation, = report['outcomes'].values()
    assert observation['outcome'] == 'FAIL' and 'missing from actual meter frame' in observation['error']['message']
    assert report['fixture_after'] == report['fixture_before']
    assert report['fixture_after']['bus']['properties']['BusChannelConfig'] == 0
    assert [args['value'] for uri, args, _ in client.calls if uri.endswith('object.setProperty')] == [12546, 0]
    assert any(row['action'] == 'restore-bus-configuration' for row in report['cleanup']['receipts'])
    assert record['source']['hash_before'] == record['source']['hash_after']
    cleanup = [uri for uri, _, _ in client.calls if uri.endswith(('profiler.stopCapture', 'transport.destroy', 'profiler.unregisterMeter'))]
    assert cleanup == ['ak.wwise.core.profiler.stopCapture', 'ak.wwise.core.transport.destroy', 'ak.wwise.core.profiler.unregisterMeter']


def test_owned_capture_public_flow_reaches_archived_final_categories(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch)
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    categories = record['categories']
    assert {row['category'] for row in categories} == {
        'profiler-meter-object-observation', 'profiler-cursor-snap-readback', 'profiler-saved-capture-artifact',
        'runtime-owned-log-add', 'runtime-owned-log-clear'}
    assert all(row['status'] == row['business_outcome'] == 'PASS' for row in categories)
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report_root = Path(archive['artifacts']['native-evidence']['path'])
    report = json.loads((report_root / 'profiler-capture.json').read_text())
    assert report['cleanup']['complete'] is True
    assert report['outcomes']['profiler-meter-object-observation']['evidence']['meters'][0]['channels'] == [{'name': 'C', 'value': -12.5}]
    meter_object = report['outcomes']['profiler-meter-object-observation']['evidence']['meters'][0]['object']
    assert meter_object['path'] == r'\Busses\Default Work Unit\WAAPI_V2_Weapons'
    assert meter_object['volume_db'] == 0.0
    assert meter_object['related']['parent']['object'] == {
        'id': '{A74EEB4A-0805-4AFA-969C-53DCB862B550}', 'name': 'Default Work Unit'}
    assert meter_object['related']['parent']['work_unit_is_default'] is True
    assert report['outcomes']['profiler-cursor-snap-readback']['evidence']['snapped_time_ms'] == 1490
    assert report['outcomes']['profiler-saved-capture-artifact']['evidence']['capture_format_validity_verified'] is False
    assert (report_root / 'saved-capture/OwnedCapture.prof').read_bytes().startswith(b'opaque fake')
    assert not client.transport and not client.registered
    assert not batch.runtime.owned_root.exists()
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert all(row['batch_finalization'] for row in categories)
    controls = [uri for uri, _, _ in client.calls if uri.endswith(('transport.destroy', 'log.addItem', 'log.clear'))]
    assert controls == ['ak.wwise.core.transport.destroy', 'ak.wwise.core.log.addItem', 'ak.wwise.core.log.clear']
    assert client.logs == {'general': [], 'sourceControl': [{'message': 'preserve unselected channel',
        'severity': 'Message', 'time': 1, 'messageId': 'Custom'}]}


def test_mismatched_structural_parent_stops_before_writes_and_final_acceptance(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='wrong-parent')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    assert all(row['business_outcome'] == 'BLOCKED' and row['status'] == 'blocked'
        and 'batch_finalization' not in row for row in record['categories'])
    artifact = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(artifact['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['setup'] == [] and report['public_call_count'] == 3
    assert 'Main Audio Bus' in report['errors'][0]['message']
    assert report['cleanup']['complete'] is True and report['cleanup']['receipts'] == []
    assert not client.transport and not client.registered
    assert {uri for uri, _, _ in client.calls} <= {
        'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}
    assert record['source']['hash_before'] == record['source']['hash_after']


def test_empty_meter_retains_cursor_file_and_cleanup_as_separate_observations(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='empty-meter')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    categories = {row['category']: row for row in record['categories']}
    assert categories['profiler-meter-object-observation']['status'] == 'FAIL'
    for name in ('profiler-cursor-snap-readback', 'profiler-saved-capture-artifact'):
        assert categories[name]['business_outcome'] == 'PASS' and categories[name]['status'] == 'blocked'
    assert all(row['cleanup_complete'] is True and 'batch_finalization' not in row for row in categories.values())
    assert not client.transport and not client.registered
    assert batch.lifecycle_result.quarantine_path
    assert record['source']['hash_before'] == record['source']['hash_after']
    artifact = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report_root = Path(artifact['artifacts']['native-evidence']['path'])
    report = json.loads((report_root / 'profiler-capture.json').read_text())
    assert report['outcomes']['profiler-meter-object-observation']['outcome'] == 'FAIL'
    assert (report_root / 'saved-capture/OwnedCapture.prof').is_file()


def test_cleanup_failure_retains_each_business_observation_without_acceptance(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='cleanup')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    assert all(row['status'] == 'blocked' and row['business_outcome'] == 'PASS'
        and row['cleanup_complete'] is False and 'batch_finalization' not in row for row in record['categories'])
    assert sum(uri.endswith('profiler.unregisterMeter') for uri, _, _ in client.calls) == 1
    assert not client.transport and client.registered
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    root = Path(archived['artifacts']['native-evidence']['path'])
    report = json.loads((root / 'profiler-capture.json').read_text())
    assert report['cleanup']['errors'][0]['action'] == 'unregister-meter'
    assert any('fake unregister failure' in json.dumps(row['payload']) for row in archived['receipts'])
    assert batch.lifecycle_result.quarantine_path and not batch.batch_seal_path.exists()


def test_failed_explicit_stop_capture_persists_incomplete_cleanup_without_retry(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='explicit-stop-capture')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    assert all(row['cleanup_complete'] is False and row['status'] == 'blocked'
        and 'batch_finalization' not in row for row in record['categories'])
    assert sum(uri == 'ak.wwise.core.profiler.stopCapture' for uri, _, _ in client.calls) == 1
    assert batch.lifecycle_result.quarantine_path and not batch.batch_seal_path.exists()
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    root = Path(archived['artifacts']['native-evidence']['path'])
    report = json.loads((root / 'profiler-capture.json').read_text())
    assert report['complete'] is False and report['cleanup']['complete'] is False
    assert [row['action'] for row in report['cleanup']['errors']] == ['stop-capture']
    assert report['outcomes']['profiler-meter-object-observation']['outcome'] == 'PASS'
    assert not any(row['action'] == 'stop-capture' for row in report['cleanup']['receipts'])
    failed = [row for row in archived['receipts'] if row['argv'][0] == 'execute'
        and row['payload'].get('dispatch_result', {}).get('api') == 'ak.wwise.core.profiler.stopCapture']
    assert len(failed) == 1 and failed[0]['exit_code'] == 2
    assert failed[0]['payload']['state'] == 'indeterminate'
    assert failed[0]['payload']['automatic_retry'] is False
    assert record['source']['hash_before'] == record['source']['hash_after']


@pytest.mark.parametrize('version,extra', [('2024.1', False), ('2025.1', True), ('2025.1', False)])
def test_capture_owner_requires_exact_single_2025_selection(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        message = 'Selected owned Authoring node is not available on the requested version' if version != '2025.1' else 'only its matching 2025'
        with pytest.raises(pytest.UsageError, match=message):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']

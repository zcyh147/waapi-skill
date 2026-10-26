"""Closed import-created DialogueEvent associations through the public Gateway."""
import json
from copy import deepcopy
from pathlib import Path
import pytest

from tests.unit.test_import_switch_assignment_gateway import SwitchImportClient, WAV_BYTES
from tests.unit.test_audio_import_business_gateway import _import_fields_draft, waapi_gateway, _env
from tests.support.gateway_config import set_gateway_config

AUDIO_NODE = json.loads((Path(__file__).parents[1] / 'fixtures/metadata-conditions/dialogue-audio-node-2025.json').read_text())['metadata']


class DialogueImportClient(SwitchImportClient):
    EVENT_PARENT = '{88888888-8888-8888-8888-888888888888}'
    EVENT = '{99999999-9999-9999-9999-999999999999}'
    ENTRY = '{AAAAAAAA-1111-1111-1111-111111111111}'

    def __init__(self, tmp_path, version='2025.1', *, existing=False):
        super().__init__(tmp_path, media=True, version=version)
        self.parent['type'] = 'PropertyContainer' if version == '2025.1' else 'ActorMixer'
        self.parent.pop('SwitchGroupOrStateGroup')
        self.child.pop('@Volume')
        self.event_parent = {'id': self.EVENT_PARENT, 'name': 'Default Work Unit', 'type': 'WorkUnit',
                             'path': r'\Dynamic Dialogue\Default Work Unit'}
        self.event = {'id': self.EVENT, 'name': 'Greeting', 'type': 'DialogueEvent', 'classId': 3014672,
                      'path': self.event_parent['path'] + r'\Greeting', 'parent': {'id': self.EVENT_PARENT}}
        self.entry_class = 655360016 if version in {'2021.1','2022.1'} else 5439504
        # Empty names and opaque display paths are present in the native read;
        # neither is interpreted as a conditional/default decision path.
        self.entry = {'id': self.ENTRY, 'name': '', 'type': 'MultiSwitchEntry', 'classId': self.entry_class,
                      'path': self.event['path'] + r'\[opaque display (MultiSwitchEntry)]',
                      'owner': {'id': self.EVENT}, 'AudioNode': {'id': self.CHILD}}
        self.event_created = False
        self.linked = False
        self.metadata = deepcopy(AUDIO_NODE)
        self.existing = existing
        self.before_links = []
        if existing:
            self.created = True
            self.child['notes'] = 'keep owner notes'
            self.source['notes'] = 'keep source notes'
            self.source['audioSource:language']['id'] = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
            self.source['originalFilePath'] = str(tmp_path / 'project/Originals/SFX/Footsteps/Snow.wav')
            self.source['originalWavFilePath'] = self.source['originalFilePath']
            self.child['sound:originalWavFilePath'] = self.source['originalFilePath']
            copied = Path(self.source['originalFilePath']); copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(b'old media')
            self.before_links = [{**deepcopy(self.entry), 'id':'{BBBBBBBB-1111-1111-1111-111111111111}',
                'owner':{'id':'{CCCCCCCC-1111-1111-1111-111111111111}'}, 'path':'opaque unrelated entry display'}]

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.getTypes':
            result = super().call(uri, args, options)
            result['return'] += [{'name':'DialogueEvent','classId':3014672,'type':'WObject'},
                                 {'name':'MultiSwitchEntry','classId':self.entry_class,'type':'WObject'}]
            return result
        if uri == 'ak.wwise.core.object.getPropertyInfo' and args['property'] == 'AudioNode':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return deepcopy(self.metadata)
        if uri == 'ak.wwise.core.object.get' and args.get('waql') == f'from object "{self.CHILD}" select referencesTo take 129':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{k:deepcopy(v) for k,v in row.items() if k in options['return']}
                for row in [*self.before_links, *([self.entry] if self.linked else [])]]}
        if uri == 'ak.wwise.core.object.get' and args.get('waql') == f'from object "{self.CHILD}" select children take 129':
            self.calls.append((uri,deepcopy(args),deepcopy(options)))
            return {'return':[{k:deepcopy(v) for k,v in self.source.items() if k in options['return']}]}
        if uri == 'ak.wwise.core.object.get':
            known = [self.parent, self.event_parent, *([self.child, self.source] if self.created else []), *([self.event] if self.event_created else []), *([self.entry] if self.linked else [])]
            selected = [r for r in known if r['id'] in args.get('from',{}).get('id',[]) or r['path'] in args.get('from',{}).get('path',[])]
            if selected:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': [{k:deepcopy(v) for k,v in row.items() if k in options['return']} for row in selected]}
        if uri == 'ak.wwise.core.audio.import':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            owner, source = args['imports']
            assert owner['dialogueEvent'] == r'\Dynamic Dialogue\Default Work Unit\Greeting'
            assert 'audioFile' not in owner and 'dialogueEvent' not in source
            if self.existing:
                assert owner['objectPath'] == self.child['path']
                assert source['objectPath'] == '' and source['importLocation'] == self.source['id']
            else:
                assert owner['objectPath'].endswith(r'\<Sound SFX>SnowSounds')
                assert source['objectPath'].endswith(r'\<Sound SFX>SnowSounds\<AudioFileSource>Snow')
            copied = Path(self.source['originalFilePath']); copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(Path(source['audioFile']).read_bytes())
            self.created = self.event_created = True
            self.linked = self.effect
            result = {'objects':deepcopy([self.child,self.source,self.event])}
            if self.version in {'2023.1','2024.1','2025.1'}:result.update(log=[],files=[self.source['originalFilePath']])
            return result
        return super().call(uri,args,options)


def _draft(tmp_path, version='2025.1', *, existing=False):
    client = DialogueImportClient(tmp_path,version,existing=existing)
    command, parent, _ = _import_fields_draft(tmp_path,version,client)
    (tmp_path / 'Snow.wav').write_bytes(WAV_BYTES)
    event_parent = command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
    declaration = ('draft-declare-existing','--declaration-id','snow','--object-handle',
        command('draft-bind-object','--object-id',client.CHILD)['bound_object']['handle']) if existing else (
        'draft-declare-new','--declaration-id','snow','--parent-handle',parent,'--name','SnowSounds','--kind','sound-sfx')
    command(*declaration,
            '--field','media_file',str(tmp_path / 'Snow.wav'),
            '--dialogue-event-parent-handle',event_parent,'--dialogue-event-name','Greeting')
    return command,client


@pytest.mark.parametrize('version',('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_import_creates_bound_dialogue_event_and_verifies_actual_owner_link(tmp_path,version):
    command,client = _draft(tmp_path,version)
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    assert shown['artifact']['prepared_operation']['verification_plan']['native_directive_boundaries'] == []
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    command('execute',tx)
    result=command('verify',tx)
    assert result['verified'] is True,result
    assert client.entry['owner']['id']==client.EVENT and client.entry['AudioNode']['id']==client.CHILD
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES
    assert len([u for u,_,_ in client.calls if u=='ak.wwise.core.audio.import'])==1
    assert not any(u.endswith(('.setReference','.set','.create')) for u,_,_ in client.calls)


def test_existing_sfx_media_and_dialogue_only_reuse_preserves_owner_and_unrelated_entry(tmp_path):
    command,client = _draft(tmp_path,existing=True)
    before_owner,before_source,before_links = deepcopy(client.child),deepcopy(client.source),deepcopy(client.before_links)
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    rows=shown['artifact']['prepared_operation']['dispatch']['args']['imports']
    assert len(rows)==2 and 'dialogueEvent' in rows[0] and 'dialogueEvent' not in rows[1]
    assert not any('@Volume' in row or 'event' in row for row in rows)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    assert command('verify',tx)['verified'] is True
    assert (client.child,client.source,client.before_links)==(before_owner,before_source,before_links)
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES


@pytest.mark.parametrize('fault',('missing','wrong-event'))
def test_event_creation_and_media_cannot_verify_an_ignored_dialogue_association(tmp_path,fault):
    command,client = _draft(tmp_path)
    client.effect=fault!='missing'
    if fault=='wrong-event':client.entry['owner']={'id':'{DDDDDDDD-1111-1111-1111-111111111111}'}
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2,result
    assert result['verified'] is False and client.event_created
    assert client.linked == (fault!='missing')
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES
    assert any(not row['passed'] and 'Dialogue association' in row['name'] for row in result['verification']['assertions'])


@pytest.mark.parametrize('drift',('event-path','metadata','membership'))
def test_dialogue_event_identity_metadata_and_membership_drift_block_import(tmp_path,drift):
    command,client = _draft(tmp_path,existing=True)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    if drift=='event-path':client.event_created=True
    elif drift=='metadata':client.metadata['restriction']['restrictions'][0]['type']=['Music Segment']
    else:client.before_links.clear()
    command('execute',tx,expected_error='ROLE_GUARD_MISMATCH')
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


@pytest.mark.parametrize('fault',('wrong-parent','event-exists','native-name'))
def test_dialogue_declaration_rejects_wrong_scope_existing_event_and_directive_name(tmp_path,fault):
    command,client = _draft(tmp_path)
    error={'wrong-parent':'OPERATION_DRAFT_ACTION_INVALID','event-exists':'DIALOGUE_EVENT_TARGET_EXISTS','native-name':'OPERATION_DRAFT_ACTION_INVALID'}[fault]
    if fault=='wrong-parent':
        # Rebind an ordinary owner parent as the requested Dialogue parent.
        wrong=command('draft-bind-object','--object-id',client.parent['id'])['bound_object']['handle']
        command('draft-revise-declaration','--declaration-id','snow','--dialogue-event-parent-handle',wrong,'--dialogue-event-name','Greeting')
    elif fault=='event-exists':client.event_created=True
    else:
        correct=command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
        command('draft-revise-declaration','--declaration-id','snow','--dialogue-event-parent-handle',correct,'--dialogue-event-name','Greeting@Path:State.Value')
    command('draft-check',expected_error=error)
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


def test_ordinary_import_does_not_accept_legacy_caller_native_dialogue_directive(tmp_path):
    command,client = _draft(tmp_path)
    command('draft-revise-declaration','--declaration-id','snow','--field','dialogue_event_directive','Greeting@Path:State.Value',expected_error='GatewayInputError')
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


def test_dialogue_import_reserves_readback_capacity_before_any_write(tmp_path):
    command,client = _draft(tmp_path,existing=True)
    template=client.before_links[0]
    client.before_links=[{**deepcopy(template),'id':f'{{BBBBBBBB-1111-1111-1111-{index:012d}}}'} for index in range(128)]
    command('draft-check',expected_error='DIALOGUE_ASSOCIATION_LIMIT_EXCEEDED')
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)

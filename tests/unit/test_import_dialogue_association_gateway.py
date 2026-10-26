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
    REGULAR_PARENT = '{E1111111-1111-1111-1111-111111111111}'
    REGULAR_EVENT = '{E2222222-2222-2222-2222-222222222222}'
    ACTION = '{E3333333-3333-3333-3333-333333333333}'

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
        self.effect = False  # Name/path-only native r1 created no Entry.
        self.event_class = 3014672
        self.event_created = False
        self.linked = False
        self.metadata = deepcopy(AUDIO_NODE)
        self.existing = existing
        self.switch_requested = False
        self.regular_requested = False
        self.regular_parent = {'id':self.REGULAR_PARENT,'name':'Default Work Unit','type':'WorkUnit',
                               'path':r'\Events\Default Work Unit'}
        self.regular_event = {'id':self.REGULAR_EVENT,'name':'Play_Greeting','type':'Event',
                              'path':self.regular_parent['path']+r'\Play_Greeting'}
        self.action = {'id':self.ACTION,'name':'Play','type':'Action','classId':327696,
                       'path':self.regular_event['path']+r'\Play','parent':{'id':self.REGULAR_EVENT},
                       'ActionType':1,'Target':{'id':self.CHILD,'path':self.child['path']}}
        self.state_group = {'id':'{A1111111-1111-1111-1111-111111111112}', 'name':'Hostile', 'type':'StateGroup', 'path':r'\States\Default Work Unit\World\Hostile'}
        self.extra_referrers = []
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
            if self.switch_requested:
                for row in result['return']:
                    if row['name']=='SwitchContainer':row['classId']=655376
            result['return'] += [{'name':'DialogueEvent','classId':self.event_class,'type':'WObject'},
                                 {'name':'MultiSwitchEntry','classId':self.entry_class,'type':'WObject'}]
            return result
        if uri == 'ak.wwise.core.object.getPropertyInfo' and args['property'] in {'Probability','Weight'}:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'name':args['property'], 'type':'Real32', 'default':100 if args['property']=='Probability' else 50, 'range':{'min':0,'max':100}}
        if uri == 'ak.wwise.core.object.getPropertyInfo' and args['property'] == 'AudioNode':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return deepcopy(self.metadata)
        if uri == 'ak.wwise.core.object.get' and args.get('waql') == f'from object "{self.CHILD}" select referencesTo take 129':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{k:deepcopy(v) for k,v in row.items() if k in options['return']}
                for row in [*self.before_links, *([self.entry] if self.linked else []),
                    *([self.action] if self.event_created and self.regular_requested and self.action['Target']['id']==self.CHILD else []),
                    *([self.parent] if self.event_created and self.switch_requested else []),
                    *(self.extra_referrers if self.event_created else [])]]}
        if uri == 'ak.wwise.core.object.get' and args.get('waql') == f'from object "{self.CHILD}" select children take 129':
            self.calls.append((uri,deepcopy(args),deepcopy(options)))
            return {'return':[{k:deepcopy(v) for k,v in self.source.items() if k in options['return']}]}
        if uri == 'ak.wwise.core.object.get' and args.get('from',{}).get('id') == [self.REGULAR_EVENT] and args.get('transform') == [{'select':['children']}]:
            self.calls.append((uri,deepcopy(args),deepcopy(options)))
            return {'return':[{k:deepcopy(v) for k,v in self.action.items() if k in options['return']}]}
        if uri == 'ak.wwise.core.object.get':
            known = [self.parent, self.group, self.value, self.state_group, self.event_parent, self.regular_parent,
                *([self.regular_event,self.action] if self.event_created and self.regular_requested else []), *([self.child, self.source] if self.created else []), *([self.event] if self.event_created else []), *([self.entry] if self.linked else [])]
            selected = [r for r in known if r['id'] in args.get('from',{}).get('id',[]) or r['path'] in args.get('from',{}).get('path',[])]
            if selected:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': [{k:deepcopy(v) for k,v in row.items() if k in options['return']} for row in selected]}
        if uri == 'ak.wwise.core.audio.import':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            owner, source = args['imports']
            assert owner['dialogueEvent'] == getattr(self, 'expected_dialogue', r'\Dynamic Dialogue\Default Work Unit\Greeting')
            assert 'audioFile' not in owner and 'dialogueEvent' not in source
            if self.switch_requested:
                assert owner['switchAssignation']=='<Switch Group:Surface>Snow' and 'switchAssignation' not in source
            if self.regular_requested:
                assert owner['event'] == self.regular_event['path']+'@Play' and 'event' not in source
                assert not any('@Volume' in row for row in args['imports'])
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
            if self.switch_requested:self.assignments.append({"child":self.CHILD,"stateOrSwitch":self.VALUE})
            result = {'objects':deepcopy([self.child,self.source,self.event])}
            if self.version in {'2023.1','2024.1','2025.1'}:result.update(log=[],files=[self.source['originalFilePath']])
            return result
        return super().call(uri,args,options)


def _draft(tmp_path, version='2025.1', *, existing=False, regular_event=False, switch=False):
    client = DialogueImportClient(tmp_path,version,existing=existing)
    client.switch_requested = switch
    if switch:client.parent.update(type="SwitchContainer",classId=655376,SwitchGroupOrStateGroup={"id":client.GROUP})
    command, parent, _ = _import_fields_draft(tmp_path,version,client)
    (tmp_path / 'Snow.wav').write_bytes(WAV_BYTES)
    event_parent = command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
    client.regular_requested = regular_event
    regular = ('--event-parent-handle',command('draft-bind-object','--object-id',client.REGULAR_PARENT)['bound_object']['handle'],
        '--event-name','Play_Greeting') if regular_event else ()
    declaration = ('draft-declare-existing','--declaration-id','snow','--object-handle',
        command('draft-bind-object','--object-id',client.CHILD)['bound_object']['handle']) if existing else (
        'draft-declare-new','--declaration-id','snow','--parent-handle',parent,'--name','SnowSounds','--kind','sound-sfx')
    command(*declaration,
            '--field','media_file',str(tmp_path / 'Snow.wav'),
            '--dialogue-event-parent-handle',event_parent,'--dialogue-event-name','Greeting',*regular,
            *(('--switch-value','Snow') if switch else ()))
    return command,client


@pytest.mark.parametrize('version',('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_import_creates_bound_dialogue_event_without_implied_association(tmp_path,version):
    command,client = _draft(tmp_path,version)
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    assert shown['artifact']['prepared_operation']['verification_plan']['native_directive_boundaries'] == []
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    command('execute',tx)
    result=command('verify',tx)
    assert result['verified'] is True,result
    assert client.event_created and not client.linked
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
def test_name_only_creation_accepts_absent_entry_but_rejects_foreign_entry(tmp_path,fault):
    command,client = _draft(tmp_path)
    client.effect=fault!='missing'
    if fault=='wrong-event':client.entry['owner']={'id':'{DDDDDDDD-1111-1111-1111-111111111111}'}
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    if fault=='missing':
        assert code==0 and result['verified'] is True,result
        return
    assert code==2,result
    assert result['verified'] is False and client.event_created
    assert client.linked == (fault!='missing')
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES
    assert any(not row['passed'] and 'Dialogue creation' in row['name'] for row in result['verification']['assertions'])


@pytest.mark.parametrize('drift',('event-path','metadata','membership'))
def test_dialogue_event_identity_metadata_and_membership_drift_block_import(tmp_path,drift):
    command,client = _draft(tmp_path,existing=True)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    if drift=='event-path':client.event_created=True
    elif drift=='metadata':client.event_class=3014673
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


def test_event_and_dialogue_import_verify_both_planned_referrers(tmp_path):
    command,client = _draft(tmp_path,regular_event=True)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verified'] is True,result
    assert client.event_created and not client.linked
    assert client.action['parent']['id']==client.REGULAR_EVENT and client.action['Target']['id']==client.CHILD
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES
    assert len([u for u,_,_ in client.calls if u=='ak.wwise.core.audio.import'])==1


@pytest.mark.parametrize('fault',('unexpected','wrong-action-target'))
def test_combined_dialogue_rejects_unplanned_or_incorrect_event_referrers(tmp_path,fault):
    command,client = _draft(tmp_path,regular_event=True)
    if fault=='unexpected':
        client.extra_referrers=[{**deepcopy(client.action),'id':'{E4444444-4444-4444-4444-444444444444}',
            'path':r'\Events\Other\Unexpected'}]
    else:client.action['Target']={'id':client.source['id'],'path':client.source['path']}
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2 and result['verified'] is False,result
    assert client.event_created and Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES
    expected='Dialogue creation' if fault=='unexpected' else 'Action target is the imported object'
    assert any(not row['passed'] and expected in row['name'] for row in result['verification']['assertions'])


def test_combined_event_and_dialogue_capacity_counts_both_planned_links(tmp_path):
    command,client = _draft(tmp_path,existing=True,regular_event=True)
    template=client.before_links[0]
    client.before_links=[{**deepcopy(template),'id':f'{{BBBBBBBB-1111-1111-1111-{index:012d}}}'} for index in range(127)]
    command('draft-check',expected_error='DIALOGUE_ASSOCIATION_LIMIT_EXCEEDED')
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


def test_existing_switch_and_dialogue_reconcile_only_bound_container_and_entry(tmp_path):
    # This models an optional identity member; no new Switch getter or native
    # claim is introduced. The existing complete pair/group oracle must pass.
    command,client = _draft(tmp_path,existing=True,switch=True)
    before=deepcopy(client.assignments);links=deepcopy(client.before_links)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    assert command('verify',tx)['verified'] is True
    assert client.assignments==[*before,{'child':client.CHILD,'stateOrSwitch':client.VALUE}]
    assert client.before_links==links


def test_name_only_dialogue_creation_does_not_require_an_entry(tmp_path):
    # Exact native r1 outcome: media + Play Event + DialogueEvent creation,
    # Sound referencesTo contains only the Play Action; no @Path was requested.
    command,client = _draft(tmp_path,regular_event=True)
    client.effect=False
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verified'] is True,result
    assert client.event_created and not client.linked
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES
    assert not any(u.endswith('getPropertyInfo') and a.get('property')=='AudioNode' for u,a,_ in client.calls)


@pytest.mark.parametrize('version', ('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_explicit_dialogue_conditions_bind_values_and_verify_requested_numeric_effects(tmp_path, version):
    command, client = _draft(tmp_path, version)
    group = command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value = command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    parent = command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
    state = command('draft-bind-object','--object-id',client.state_group['id'])['bound_object']['handle']
    command('draft-revise-declaration','--declaration-id','snow',
        '--dialogue-event-parent-handle',parent,'--dialogue-event-name','Greeting',
        '--dialogue-condition',group,value,'--dialogue-condition',state,'*','--dialogue-probability','80','--dialogue-weight','20',
        '--field','media_file',str(tmp_path/'Snow.wav'))
    client.expected_dialogue = client.event['path']+'@Path:<Switch Group:Surface>Snow.<State Group:World\\Hostile>*|Probability:80|Weight:20'
    client.effect = True
    client.entry.update(Probability=80, Weight=20)
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    assert 'decision_path_sequence_not_read_back' in shown['artifact']['prepared_operation']['verification_plan']['native_directive_boundaries']
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verification']['failed_assertion_count'] == 0,result
    assert result['verified'] is False
    assert result['verification']['business_state_verified'] is False
    assert client.linked and Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES


@pytest.mark.parametrize('version', ('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_repeated_tsv_dialogue_columns_preserve_exact_table_and_bind_each_event(tmp_path, version):
    command, run, client, table = _dialogue_table_draft(tmp_path, version)
    original = table.read_bytes()
    command('draft-check'); tx=command('preview-from-draft')['transaction_id']
    code, shown=run('transaction-show',tx); assert code==0,shown
    bindings=shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['dialogue_association_bindings']
    assert [b['path'] for b in bindings]==[client.event['path'],client.second_event['path']]
    assert run('confirm',tx,'--confirmation-token',shown['confirmation']['token'])[0]==0
    assert run('execute',tx)[0]==0
    code,result=run('verify',tx);assert code==0,result
    assert result['verification']['failed_assertion_count']==0,result
    assert result['verified'] is False and result['verification']['business_state_verified'] is False
    assert table.read_bytes()==original and Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES


def _dialogue_table_draft(tmp_path, version='2025.1'):
    from tests.unit.test_transaction_gateway import z_wire_path
    from wwise_waapi.host_paths import localize_waapi_host_path
    import csv
    class TableClient(DialogueImportClient):
        def __init__(self):
            super().__init__(tmp_path,version)
            self.second_event={**deepcopy(self.event),'id':'{99999999-9999-9999-9999-999999999998}', 'name':'Reply',
                'path':self.event_parent['path']+r'\Reply'}
            self.second_entry={**deepcopy(self.entry),'id':'{AAAAAAAA-1111-1111-1111-111111111112}', 'owner':{'id':self.second_event['id']}}
            self.effect_count=2
        def call(self,uri,args=None,options=None):
            args,options=args or {},options or {}
            if uri=='ak.wwise.core.object.get':
                if self.event_created and (self.second_event['path'] in args.get('from',{}).get('path',[]) or self.second_event['id'] in args.get('from',{}).get('id',[])):
                    self.calls.append((uri,deepcopy(args),deepcopy(options)))
                    return {'return':[{k:v for k,v in self.second_event.items() if k in options['return']}]}
                if args.get('waql')==f'from object "{self.CHILD}" select referencesTo take 129':
                    self.calls.append((uri,deepcopy(args),deepcopy(options)))
                    return {'return':deepcopy([self.entry,self.second_entry][:self.effect_count]) if self.linked else []}
            if uri=='ak.wwise.core.audio.importTabDelimited':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                with Path(args['importFile']).open(encoding='utf-8',newline='') as stream:rows=list(csv.reader(stream,delimiter='\t'))
                assert rows[0][-2:]==['Dialogue Event','Dialogue Event']
                copied=Path(self.source['originalFilePath']);copied.parent.mkdir(parents=True,exist_ok=True)
                copied.write_bytes(Path(localize_waapi_host_path(rows[1][1])).read_bytes())
                self.created=self.event_created=self.linked=True
                return {'objects':deepcopy([self.child,self.source,self.event,self.second_event])}
            return super().call(uri,args,options)
    client=TableClient()
    media=tmp_path/'Snow.wav';media.write_bytes(WAV_BYTES)
    table=tmp_path/'dialogue.tsv'
    table.write_text('Object Path\tAudio File\tDialogue Event\tDialogue Event\n<Sound SFX>SnowSounds\t'+z_wire_path(media)+'\t'+client.event['path']+'@Path:<Switch Group:Surface>Snow\t'+client.second_event['path']+'@Path:<Switch Group:Surface>*\n')
    env=set_gateway_config(_env(tmp_path),wwise_version=version)
    def run(*argv):return waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),*argv],env=env,client_factory=lambda _url:client)
    code,started=run('draft-start','audio.importTabDelimited');assert code==0,started
    draft,authority,revision=started['draft']['draft_id'],started['task_authority'],1
    def command(name,*argv,expected_error=None):
        nonlocal revision
        code,result=run(name,draft,'--task-authority',authority,'--expected-revision',str(revision),*argv)
        assert code==(2 if expected_error else 0),json.dumps(result,indent=2)
        if expected_error:assert result['error_code']==expected_error,result
        if 'draft' in result:revision=result['draft']['revision']
        return result
    bound=command('draft-bind-object','--role','import_location','--object-id',client.parent['id'])
    command('draft-declare-artifact-plan','--table-file',str(table),'--location-handle',bound['bound_object']['handle'],'--language','SFX','--mode','reimport')
    return command,run,client,table


@pytest.mark.parametrize('fault', ('missing-second','wrong-group','table-drift'))
def test_repeated_dialogue_columns_reject_missing_effect_and_prewrite_drift(tmp_path, fault):
    command,run,client,table=_dialogue_table_draft(tmp_path)
    if fault=='wrong-group':
        client.value['parent']={'id':client.OTHER_VALUE}
        command('draft-check',expected_error='IDENTITY_MISMATCH')
        assert not any(u.endswith('.importTabDelimited') for u,_,_ in client.calls)
        return
    command('draft-check');tx=command('preview-from-draft')['transaction_id']
    _,shown=run('transaction-show',tx)
    run('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    if fault=='table-drift':
        table.write_text(table.read_text().replace('>Snow','>*'))
        code,result=run('execute',tx)
        assert code==2 and not result['executed'],result
        assert not any(u.endswith('.importTabDelimited') for u,_,_ in client.calls)
    else:
        client.effect_count=1
        assert run('execute',tx)[0]==0
        code,result=run('verify',tx)
        assert code==2 and result['verification']['status']=='verification_failed',result
        assert any(not a['passed'] and 'Dialogue creation' in a['name'] for a in result['verification']['assertions'])


@pytest.mark.parametrize('fault', ('numeric','missing-entry','group-drift','number-without-path','metadata-drift'))
def test_explicit_dialogue_requested_effects_and_prerequisites_are_not_silently_ignored(tmp_path, fault):
    command,client=_draft(tmp_path)
    group=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    parent=command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
    condition=() if fault=='number-without-path' else ('--dialogue-condition',group,value)
    command('draft-revise-declaration','--declaration-id','snow','--field','media_file',str(tmp_path/'Snow.wav'),
        '--dialogue-event-parent-handle',parent,'--dialogue-event-name','Greeting',*condition,'--dialogue-probability','80')
    if fault=='number-without-path':
        command('draft-check',expected_error='INVALID_ARGUMENT')
        return
    client.expected_dialogue=client.event['path']+'@Path:<Switch Group:Surface>Snow|Probability:80'
    client.effect=fault!='missing-entry';client.entry['Probability']=10 if fault=='numeric' else 80
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    if fault in {'group-drift','metadata-drift'}:
        if fault=='group-drift':client.group['name']='Different'
        else:client.metadata['restriction']={'type':'reference','restrictions':[{'type':['Bus']}]}
        command('execute',tx,expected_error='ROLE_GUARD_MISMATCH')
        assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)
        return
    command('execute',tx)
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2 and result['verification']['status']=='verification_failed',result
    assert any(not a['passed'] and ('Probability/Weight' in a['name'] or 'Dialogue creation' in a['name']) for a in result['verification']['assertions'])

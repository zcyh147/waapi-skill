"""Closed import-created DialogueEvent associations through the public Gateway."""
import json
from copy import deepcopy
from pathlib import Path
import pytest

from tests.unit.test_import_switch_assignment_gateway import SwitchImportClient, WAV_BYTES
from tests.unit.test_audio_import_business_gateway import _import_fields_draft, waapi_gateway, _env, LocalizedFieldsClient
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
            known = [self.parent, self.group, self.value, self.state_group, self.event_parent, self.regular_parent, *self.before_links,
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
                if self.version=='2025.1':assert source['objectPath'] == '' and source['importLocation'] == self.source['id']
                else:assert source['objectPath']==self.child['path']+r'\<AudioFileSource>Snow' and 'importLocation' not in source
            else:
                assert owner['objectPath'].endswith(r'\<Sound SFX>SnowSounds')
                assert source['objectPath'].endswith(r'\<Sound SFX>SnowSounds\<AudioFileSource>Snow')
            copied = Path(self.source['originalFilePath']); copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(Path(source['audioFile']).read_bytes())
            self.created = self.event_created = True
            if hasattr(self, 'requested_probability_effect'):
                self.entry['Probability']=self.requested_probability_effect
                if hasattr(self,'requested_entry_display'):self.entry['path']=self.requested_entry_display
                for old_entry in self.before_links:
                    if old_entry['id']==self.ENTRY:
                        old_entry['Probability']=self.requested_probability_effect
                        old_entry['path']=self.entry['path']
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
                    return {'return':[{k:deepcopy(v) for k,v in row.items() if k in options['return']} for row in [self.parent,self.event_parent,self.event,self.second_event,self.group,self.value,*([self.child,self.source] if self.created else [])] if row['id'] in args.get('from',{}).get('id',[]) or row['path'] in args.get('from',{}).get('path',[])]}
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


@pytest.mark.parametrize('version', ('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_existing_dialogue_event_handle_updates_requested_path_without_recreating_event(tmp_path, version):
    command,client=_existing_event_lifecycle_draft(tmp_path,version)
    before=deepcopy(client.before_links)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    binding=shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['dialogue_association_binding']
    assert binding['event_id']==client.EVENT
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verification']['failed_assertion_count']==0,result
    assert result['verified'] is False and result['verification']['business_state_verified'] is False
    before[-1]['Probability']=80
    before[-1]['path']=client.requested_entry_display
    assert client.before_links==before and client.event['id']==client.EVENT
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES


class LocalizedDialogueClient(LocalizedFieldsClient):
    DIALOGUE_PARENT='{D1111111-1111-1111-1111-111111111111}'
    DIALOGUE_EVENT='{D2222222-2222-2222-2222-222222222222}'
    ENTRY='{D3333333-3333-3333-3333-333333333333}'
    GROUP=SwitchImportClient.GROUP
    VALUE=SwitchImportClient.VALUE

    def __init__(self,tmp_path,version):
        super().__init__(tmp_path,version)
        self.dialogue_parent={'id':self.DIALOGUE_PARENT,'type':'WorkUnit','name':'Default Work Unit','path':r'\Dynamic Dialogue\Default Work Unit'}
        self.dialogue={'id':self.DIALOGUE_EVENT,'type':'DialogueEvent','classId':3014672,'name':'Greeting',
            'path':self.dialogue_parent['path']+r'\Greeting','parent':{'id':self.DIALOGUE_PARENT}}
        self.group={'id':self.GROUP,'type':'SwitchGroup','name':'Surface','path':r'\Switches\Default Work Unit\Surface'}
        self.value={'id':self.VALUE,'type':'Switch','name':'Snow','path':self.group['path']+r'\Snow','parent':{'id':self.GROUP}}
        self.entry_class=655360016 if version in {'2021.1','2022.1'} else 5439504
        self.entry={'id':self.ENTRY,'name':'','type':'MultiSwitchEntry','classId':self.entry_class,'path':'opaque entry display',
            'owner':{'id':self.DIALOGUE_EVENT},'AudioNode':{'id':self.OWNER}}
        self.owner['sound:originalWavFilePath']=str(self.copied)
        self.associated=False
        self.ignore_link=False

    def call(self,uri,args=None,options=None):
        args,options=args or {},options or {}
        if uri=='ak.wwise.core.object.getTypes':
            result=super().call(uri,args,options)
            result['return'] += [{'name':'DialogueEvent','type':'WObject','classId':3014672},{'name':'MultiSwitchEntry','type':'WObject','classId':self.entry_class}]
            return result
        if uri=='ak.wwise.core.object.getPropertyInfo' and args['property']=='AudioNode':
            self.calls.append((uri,deepcopy(args),deepcopy(options)));return deepcopy(AUDIO_NODE)
        if uri=='ak.wwise.core.object.get':
            if args.get('waql')==f'from object "{self.OWNER}" select referencesTo take 129':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                return {'return':[deepcopy(self.entry)] if self.associated else []}
            known=[self.parent,self.owner,*self.sources,self.dialogue_parent,self.dialogue,self.group,self.value,*([self.entry] if self.associated else [])]
            selected=[r for r in known if r['id'] in args.get('from',{}).get('id',[]) or r['path'] in args.get('from',{}).get('path',[])]
            if self.GROUP in args.get('waql','') and 'Snow' in args['waql']:selected=[self.value]
            if options.get('language'):selected=[r for r in selected if r['type']!='AudioFileSource' or r['audioSource:language']['name']==options['language']]
            if selected:
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                return {'return':[{k:deepcopy(v) for k,v in r.items() if k in options['return']} for r in selected]}
        if uri=='ak.wwise.core.audio.import':
            self.calls.append((uri,deepcopy(args),deepcopy(options)))
            owner,media=args['imports']
            assert owner['dialogueEvent']==self.dialogue['path']+'@Path:<Switch Group:Surface>Snow'
            assert 'audioFile' not in owner and 'dialogueEvent' not in media
            assert owner['objectPath'].endswith('Voice')
            assert media['importLanguage']=='English(US)'
            if self.version=='2025.1':assert media['objectPath']=='' and media['importLocation']==self.SOURCE
            else:assert media['objectPath'].endswith(r'\<Sound Voice>Voice\<AudioFileSource>Line')
            self.copied.write_bytes(Path(media['audioFile']).read_bytes())
            self.associated=not self.ignore_link;self.imported=True
            return {'objects':deepcopy([self.owner,self.sources[0]]),**({'log':[],'files':[str(self.copied)]} if self.version in {'2023.1','2024.1','2025.1'} else {})}
        return super().call(uri,args,options)


@pytest.mark.parametrize('version',('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_localized_media_and_existing_dialogue_event_keep_other_language_and_owner(tmp_path,version):
    command,client=_localized_dialogue_lifecycle_draft(tmp_path,version)
    before=deepcopy(client.sources[1]);before_bytes=client.other_file.read_bytes();before_owner=deepcopy(client.owner)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and not result['verification']['business_state_verified']
    assert client.owner==before_owner and client.sources[1]==before and client.other_file.read_bytes()==before_bytes
    assert client.copied.read_bytes()==WAV_BYTES


class ReplacingDialogueClient(DialogueImportClient):
    NEW_OWNER='{F1111111-1111-1111-1111-111111111111}'

    def __init__(self,tmp_path,version):
        super().__init__(tmp_path,version,existing=True)
        self.event_created=True
        self.before_links.append(deepcopy(self.entry))
        self.child.pop("activeSource",None)
        self.child.pop("sound:originalWavFilePath",None)
        self.replaced=False
        self.keep_old_link=False

    def call(self,uri,args=None,options=None):
        args,options=args or {},options or {}
        if uri=='ak.wwise.core.object.get' and self.replaced:
            if args.get('waql')==f'from object "{self.NEW_OWNER}" select referencesTo take 129':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                return {'return':[deepcopy(self.entry)]}
            if args.get('from',{}).get('id')==[self.CHILD] or args.get('from',{}).get('id')==[self.source['id']]:
                self.calls.append((uri,deepcopy(args),deepcopy(options)));return {'return':[]}
        if uri=='ak.wwise.core.audio.import':
            self.calls.append((uri,deepcopy(args),deepcopy(options)))
            assert args['importOperation']=='replaceExisting'
            assert args['imports']==[{'objectPath':self.child['path'],'objectType':'Sound SFX',
                'dialogueEvent':self.event['path']+'@Path:<Switch Group:Surface>Snow'}]
            self.replaced=True;self.event_created=True;self.child['id']=self.NEW_OWNER
            self.entry['AudioNode']={'id':self.CHILD if self.keep_old_link else self.NEW_OWNER}
            self.before_links[0]['AudioNode']=None
            for index,old in enumerate(self.before_links):
                if old['id']==self.ENTRY:self.before_links[index]=deepcopy(self.entry)
            self.linked=False
            return {'objects':[deepcopy(self.child)],**({'log':[],'files':[]} if self.version in {'2023.1','2024.1','2025.1'} else {})}
        return super().call(uri,args,options)


def _replacing_dialogue_draft(tmp_path,version='2025.1',*,existing_event=True):
    client=ReplacingDialogueClient(tmp_path,version)
    if not existing_event:
        client.event_created=False
        client.before_links=[r for r in client.before_links if r["id"]!=client.ENTRY]
    command,_,_=_import_fields_draft(tmp_path,version,client)
    owner=command('draft-bind-object','--object-id',client.CHILD)['bound_object']['handle']
    event=command('draft-bind-object','--object-id',client.EVENT if existing_event else client.EVENT_PARENT)['bound_object']['handle']
    group=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    command('draft-business-configure','--mode','replace')
    command('draft-declare-existing','--declaration-id','snow','--object-handle',owner,
        *(('--dialogue-event-handle',event) if existing_event else ('--dialogue-event-parent-handle',event,'--dialogue-event-name','Greeting')),
        '--dialogue-condition',group,value)
    return command,client


@pytest.mark.parametrize('version',('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_new_dialogue_event_with_sound_replacement_reconciles_requested_entry_and_other_referrers(tmp_path,version):
    command,client=_replacing_dialogue_draft(tmp_path,version,existing_event=False)
    old_event=deepcopy(client.event)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and client.event==old_event
    assert client.entry['AudioNode']['id']==client.NEW_OWNER
    assert client.before_links[0]['AudioNode'] is None


def _table_lifecycle_draft(tmp_path,version,client,table,*,language='SFX',mode='reimport'):
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
    parent=command('draft-bind-object','--role','import_location','--object-id',client.parent['id'])['bound_object']['handle']
    command('draft-declare-artifact-plan','--table-file',str(table),'--location-handle',parent,'--language',language,'--mode',mode)
    return command,run


@pytest.mark.parametrize('version',('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_repeated_tsv_existing_dialogue_events_retain_identity_and_table_bytes(tmp_path,version):
    command,run,client,table=_dialogue_table_draft(tmp_path,version)
    client.event_created=True
    before=table.read_bytes()
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];_,shown=run('transaction-show',tx)
    bindings=shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['dialogue_association_bindings']
    assert [b['event_id'] for b in bindings]==[client.EVENT,client.second_event['id']]
    run('confirm',tx,'--confirmation-token',shown['confirmation']['token']);assert run('execute',tx)[0]==0
    code,result=run('verify',tx);assert code==0 and result['verification']['failed_assertion_count']==0,result
    assert table.read_bytes()==before and not result['verified']


@pytest.mark.parametrize('version',('2021.1','2022.1','2023.1','2024.1','2025.1'))
@pytest.mark.parametrize('media', (False, True))
def test_localized_tsv_dialogue_existing_event_preserves_unplanned_sources_and_exact_file(tmp_path,version,media):
    import csv
    from tests.unit.test_transaction_gateway import z_wire_path
    from wwise_waapi.host_paths import localize_waapi_host_path
    class TableClient(LocalizedDialogueClient):
        def call(self,uri,args=None,options=None):
            if uri=='ak.wwise.core.audio.importTabDelimited':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                with Path(args['importFile']).open(encoding='utf-8',newline='') as stream:rows=list(csv.reader(stream,delimiter='\t'))
                assert rows[1][2]==self.dialogue['path']+'@Path:<Switch Group:Surface>Snow'
                if rows[1][1]:self.copied.write_bytes(Path(localize_waapi_host_path(rows[1][1])).read_bytes())
                self.associated=True
                return {'objects':deepcopy([self.owner,*([self.sources[0]] if rows[1][1] else [])])}
            return super().call(uri,args,options)
    client=TableClient(tmp_path,version)
    wav=tmp_path/'Line.wav';wav.write_bytes(WAV_BYTES)
    table=tmp_path/'dialogue.tsv'
    table.write_text('Object Path\tAudio File\tDialogue Event\n<Sound Voice>Voice\t'+(z_wire_path(wav) if media else '')+'\t'+client.dialogue['path']+'@Path:<Switch Group:Surface>Snow\n')
    command,run=_table_lifecycle_draft(tmp_path,version,client,table,language='English(US)')
    before=table.read_bytes();before_other=deepcopy(client.sources[1]);other_bytes=client.other_file.read_bytes();english_bytes=client.copied.read_bytes()
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];_,shown=run('transaction-show',tx)
    run('confirm',tx,'--confirmation-token',shown['confirmation']['token']);assert run('execute',tx)[0]==0
    code,result=run('verify',tx);assert code==0 and result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and table.read_bytes()==before
    assert client.sources[1]==before_other and client.other_file.read_bytes()==other_bytes
    assert client.copied.read_bytes()==(WAV_BYTES if media else english_bytes)


def test_tsv_dialogue_replacement_reconciles_new_owner_without_rewriting_file(tmp_path):
    class TableReplacingClient(ReplacingDialogueClient):
        def call(self,uri,args=None,options=None):
            if uri=='ak.wwise.core.audio.importTabDelimited':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                assert args['importOperation']=='replaceExisting'
                self.replaced=True;self.event_created=True;self.child['id']=self.NEW_OWNER
                self.entry['AudioNode']={'id':self.NEW_OWNER}
                self.before_links[0]['AudioNode']=None
                return {'objects':[deepcopy(self.child)]}
            return super().call(uri,args,options)
    client=TableReplacingClient(tmp_path,'2025.1')
    client.event_created=False;client.before_links=[r for r in client.before_links if r['id']!=client.ENTRY]
    table=tmp_path/'replace.tsv';table.write_text('Object Path\tDialogue Event\n<Sound SFX>SnowSounds\t'+client.event['path']+'@Path:<Switch Group:Surface>Snow\n')
    command,run=_table_lifecycle_draft(tmp_path,'2025.1',client,table,mode='replace')
    before=table.read_bytes()
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];_,shown=run('transaction-show',tx)
    run('confirm',tx,'--confirmation-token',shown['confirmation']['token']);assert run('execute',tx)[0]==0
    code,result=run('verify',tx);assert code==0 and result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and table.read_bytes()==before and client.child['id']==client.NEW_OWNER


def _existing_event_lifecycle_draft(tmp_path,version="2025.1"):
    command,client=_draft(tmp_path,version,existing=True)
    client.event_created=True
    client.event['notes']='keep existing Dialogue Event notes'
    client.before_links.append(deepcopy(client.entry))
    event=command('draft-bind-object','--object-id',client.EVENT)['bound_object']['handle']
    group=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    command('draft-revise-declaration','--declaration-id','snow','--field','media_file',str(tmp_path/'Snow.wav'),
        '--dialogue-event-handle',event,'--dialogue-condition',group,value,'--dialogue-probability','80')
    client.expected_dialogue=client.event['path']+'@Path:<Switch Group:Surface>Snow|Probability:80'
    client.entry['Probability']=10
    client.before_links[-1]['Probability']=10
    client.requested_probability_effect=80
    client.requested_entry_display='opaque updated decision display'

    return command,client


@pytest.mark.parametrize('fault',('event-drift','ignored-numeric','unrelated-loss','event-notes'))
def test_existing_dialogue_event_lifecycle_rejects_drift_and_unobserved_requested_effects(tmp_path,fault):
    command,client=_existing_event_lifecycle_draft(tmp_path)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    if fault=='event-drift':
        client.event['id']='{F2222222-2222-2222-2222-222222222222}'
        command('execute',tx,expected_error='ROLE_GUARD_MISMATCH')
        assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)
        return
    if fault=='ignored-numeric':client.requested_probability_effect=10
    command('execute',tx)
    if fault=='unrelated-loss':client.before_links.pop(0)
    if fault=='event-notes':client.event['notes']='unrequested Event notes change'
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2 and result['verification']['status']=='verification_failed',result


@pytest.mark.parametrize('fault',('stale-link','unrelated-referrer-loss'))
def test_dialogue_replacement_rejects_stale_owner_links_and_unrelated_loss(tmp_path,fault):
    command,client=_replacing_dialogue_draft(tmp_path,existing_event=False)
    client.keep_old_link=fault=='stale-link'
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    if fault=='unrelated-referrer-loss':client.before_links.pop(0)
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2 and result['verification']['status']=='verification_failed',result
    assert any(not a['passed'] and ('Dialogue creation' in a['name'] or 'captured referrer' in a['name']) for a in result['verification']['assertions'])


def test_existing_media_replacement_keeps_dialogue_directive_on_owner_and_rebinds_entry(tmp_path):
    class MediaReplacingClient(ReplacingDialogueClient):
        NEW_SOURCE='{F3333333-3333-3333-3333-333333333333}'
        def __init__(self):
            super().__init__(tmp_path,'2025.1')
            self.event_created=False;self.before_links=[r for r in self.before_links if r['id']!=self.ENTRY]
            self.old_source_id=self.source['id']
            self.child['activeSource']={'id':self.old_source_id}
        def call(self,uri,args=None,options=None):
            args,options=args or {},options or {}
            if uri=='ak.wwise.core.object.get' and self.replaced:
                if args.get('from',{}).get('id')==[self.old_source_id]:
                    self.calls.append((uri,deepcopy(args),deepcopy(options)));return {'return':[]}
                if args.get('from',{}).get('id')==[self.NEW_SOURCE]:
                    self.calls.append((uri,deepcopy(args),deepcopy(options)))
                    return {'return':[{k:deepcopy(v) for k,v in self.source.items() if k in options['return']}]}
            if uri=='ak.wwise.core.audio.import':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                owner,source=args['imports']
                assert args['importOperation']=='replaceExisting'
                assert owner['dialogueEvent']==self.event['path']+'@Path:<Switch Group:Surface>Snow'
                assert 'audioFile' not in owner and 'dialogueEvent' not in source
                assert source['objectPath']==self.child['path']+r'\<AudioFileSource>Snow'
                self.child['id']=self.NEW_OWNER;self.child['activeSource']={'id':self.NEW_SOURCE}
                self.source['id']=self.NEW_SOURCE;self.source['parent']={'id':self.NEW_OWNER}
                Path(self.source['originalFilePath']).write_bytes(Path(source['audioFile']).read_bytes())
                self.entry['AudioNode']={'id':self.NEW_OWNER};self.event_created=True
                self.before_links[0]['AudioNode']=None;self.replaced=True
                return {'objects':deepcopy([self.child,self.source]),'log':[],'files':[self.source['originalFilePath']]}
            return super().call(uri,args,options)
    client=MediaReplacingClient()
    command,_,_=_import_fields_draft(tmp_path,'2025.1',client)
    media=tmp_path/'Snow.wav';media.write_bytes(WAV_BYTES)
    owner=command('draft-bind-object','--object-id',client.CHILD)['bound_object']['handle']
    event=command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
    group=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    command('draft-business-configure','--mode','replace')
    command('draft-declare-existing','--declaration-id','snow','--object-handle',owner,'--field','media_file',str(media),
        '--dialogue-event-parent-handle',event,'--dialogue-event-name','Greeting','--dialogue-condition',group,value)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and client.entry['AudioNode']['id']==client.NEW_OWNER
    assert Path(client.source['originalFilePath']).read_bytes()==WAV_BYTES


def _localized_dialogue_lifecycle_draft(tmp_path,version="2025.1"):
    client=LocalizedDialogueClient(tmp_path,version)
    command,_,_=_import_fields_draft(tmp_path,version,client)
    media=tmp_path/'Line.wav';media.write_bytes(WAV_BYTES)
    owner=command('draft-bind-object','--object-id',client.OWNER)['bound_object']['handle']
    event=command('draft-bind-object','--object-id',client.DIALOGUE_EVENT)['bound_object']['handle']
    group=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    command('draft-declare-existing','--declaration-id','voice','--object-handle',owner,
        '--field','language','English(US)','--field','media_file',str(media),'--field','originals_subfolder','Dialogue',
        '--dialogue-event-handle',event,'--dialogue-condition',group,value)
    return command,client


def test_dialogue_localized_reuse_cannot_hide_other_language_media_change(tmp_path):
    command,client=_localized_dialogue_lifecycle_draft(tmp_path)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    client.other_file.write_bytes(b'unrequested changed Japanese media')
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2 and result['verification']['status']=='verification_failed',result
    assert any(not a['passed'] and 'Sources and media outside planned' in a['name'] for a in result['verification']['assertions'])


def test_existing_dialogue_event_handle_rejects_other_class_before_preview(tmp_path):
    command,client=_draft(tmp_path,existing=True)
    wrong=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    command('draft-revise-declaration','--declaration-id','snow','--field','media_file',str(tmp_path/'Snow.wav'),'--dialogue-event-handle',wrong)
    command('draft-check',expected_error='OPERATION_DRAFT_ACTION_INVALID')
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


@pytest.mark.parametrize('conflict',(False,True))
def test_two_table_owners_can_share_new_dialogue_event_but_not_one_decision_path(tmp_path,conflict):
    class TwoOwnerClient(DialogueImportClient):
        SECOND='{F4444444-4444-4444-4444-444444444444}'
        def __init__(self):
            super().__init__(tmp_path)
            self.child.pop('activeSource',None);self.child.pop('sound:originalWavFilePath',None)
            self.second={**deepcopy(self.child),'id':self.SECOND,'name':'RainSounds','path':self.parent['path']+r'\RainSounds'}
            self.second_entry={**deepcopy(self.entry),'id':'{F5555555-5555-5555-5555-555555555555}','AudioNode':{'id':self.SECOND}}
        def call(self,uri,args=None,options=None):
            args,options=args or {},options or {}
            if uri=='ak.wwise.core.object.get' and self.created:
                if args.get('waql')==f'from object "{self.SECOND}" select referencesTo take 129':
                    self.calls.append((uri,deepcopy(args),deepcopy(options)));return {'return':[deepcopy(self.second_entry)]}
                if self.SECOND in args.get('from',{}).get('id',[]) or self.second['path'] in args.get('from',{}).get('path',[]):
                    self.calls.append((uri,deepcopy(args),deepcopy(options)));return {'return':[{k:v for k,v in self.second.items() if k in options['return']}]}
            if uri=='ak.wwise.core.audio.importTabDelimited':
                self.calls.append((uri,deepcopy(args),deepcopy(options)));self.created=self.event_created=self.linked=True
                return {'objects':deepcopy([self.child,self.second,self.event])}
            return super().call(uri,args,options)
    client=TwoOwnerClient()
    table=tmp_path/'shared.tsv';prefix=client.event['path']+'@Path:<Switch Group:Surface>'
    table.write_text('Object Path\tDialogue Event\n<Sound SFX>SnowSounds\t'+prefix+'Snow\n<Sound SFX>RainSounds\t'+prefix+('Snow' if conflict else '*')+'\n')
    command,run=_table_lifecycle_draft(tmp_path,'2025.1',client,table)
    before=table.read_bytes()
    if conflict:
        command('draft-check',expected_error='AMBIGUOUS_EVENT_MAPPING')
        assert not client.created and table.read_bytes()==before
        return
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];_,shown=run('transaction-show',tx)
    run('confirm',tx,'--confirmation-token',shown['confirmation']['token']);assert run('execute',tx)[0]==0
    code,result=run('verify',tx);assert code==0 and result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and table.read_bytes()==before


def test_existing_dialogue_event_with_localized_tsv_replace_rejects_before_preview(tmp_path):
    class ReplacingVoiceClient(LocalizedDialogueClient):
        NEW_OWNER='{F6666666-6666-6666-6666-666666666666}'
        def call(self,uri,args=None,options=None):
            args,options=args or {},options or {}
            if uri=='ak.wwise.core.audio.importTabDelimited':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                assert args['importOperation']=='replaceExisting'
                self.owner['id']=self.NEW_OWNER;self.owner.pop('activeSource',None);self.owner.pop('sound:originalWavFilePath',None)
                self.sources=[];self.associated=True;self.entry['AudioNode']={'id':self.NEW_OWNER}
                return {'objects':[deepcopy(self.owner)]}
            if uri=='ak.wwise.core.object.get' and self.associated and args.get('waql')==f'from object "{self.NEW_OWNER}" select referencesTo take 129':
                self.calls.append((uri,deepcopy(args),deepcopy(options)));return {'return':[deepcopy(self.entry)]}
            return super().call(uri,args,options)
    client=ReplacingVoiceClient(tmp_path,'2025.1')
    table=tmp_path/'voice-replace.tsv';table.write_text('Object Path\tDialogue Event\n<Sound Voice>Voice\t'+client.dialogue['path']+'@Path:<Switch Group:Surface>Snow\n')
    command,run=_table_lifecycle_draft(tmp_path,'2025.1',client,table,language='English(US)',mode='replace')
    before=table.read_bytes()
    command('draft-check',expected_error='IMPORT_DIALOGUE_EXISTING_EVENT_MODE_UNSAFE')
    assert table.read_bytes()==before and client.owner['id']==client.OWNER


@pytest.mark.parametrize('route',('ordinary','table'))
def test_existing_dialogue_event_with_global_replace_rejects_before_preview_or_write(tmp_path,route):
    if route=='ordinary':
        command,client=_replacing_dialogue_draft(tmp_path)
    else:
        client=ReplacingDialogueClient(tmp_path,'2025.1')
        table=tmp_path/'unsafe.tsv';table.write_text('Object Path\tDialogue Event\n<Sound SFX>SnowSounds\t'+client.event['path']+'@Path:<Switch Group:Surface>Snow\n')
        command,_=_table_lifecycle_draft(tmp_path,'2025.1',client,table,mode='replace')
    event=deepcopy(client.event)
    result=command('draft-check',expected_error='IMPORT_DIALOGUE_EXISTING_EVENT_MODE_UNSAFE')
    assert result['details']['safe_workflow'][0]['mode']=='replace'
    assert result['details']['safe_workflow'][1]['mode']=='reimport'
    assert 'existing Event' in result['message']
    assert client.event==event and not client.replaced
    assert not any(u in {'ak.wwise.core.audio.import','ak.wwise.core.audio.importTabDelimited'} for u,_,_ in client.calls)
    assert not list((tmp_path/'state/transactions').glob('tx1-*'))


@pytest.mark.parametrize('occupied',(False,True))
def test_new_sound_with_existing_dialogue_event_uses_one_reimport_and_keeps_new_owner_absence(tmp_path,occupied):
    command,client=_draft(tmp_path)
    client.event_created=True;client.effect=True
    event=command('draft-bind-object','--object-id',client.EVENT)['bound_object']['handle']
    group=command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    command('draft-revise-declaration','--declaration-id','snow','--field','media_file',str(tmp_path/'Snow.wav'),
        '--dialogue-event-handle',event,'--dialogue-condition',group,value)
    client.expected_dialogue=client.event['path']+'@Path:<Switch Group:Surface>Snow'
    if occupied:
        client.created=True
        copied=Path(client.source['originalFilePath']);copied.parent.mkdir(parents=True,exist_ok=True);copied.write_bytes(b'old owned media')
        command('draft-check',expected_error='NEW_IMPORT_TARGET_EXISTS')
        assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)
        return
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    assert shown['artifact']['prepared_operation']['dispatch']['args']['importOperation']=='useExisting'
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    assert result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and client.event['id']==client.EVENT and client.linked
    assert len([u for u,_,_ in client.calls if u=='ak.wwise.core.audio.import'])==1


def test_sound_replacement_then_existing_dialogue_reuse_use_two_separate_public_transactions(tmp_path):
    class StagedClient(ReplacingDialogueClient):
        def call(self,uri,args=None,options=None):
            args,options=args or {},options or {}
            if uri=='ak.wwise.core.object.get' and args.get('waql')==f'from object "{self.NEW_OWNER}" select referencesTo take 129':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                return {'return':[deepcopy(self.entry)] if self.entry['AudioNode'] and self.entry['AudioNode']['id']==self.NEW_OWNER else []}
            if uri=='ak.wwise.core.audio.import':
                self.calls.append((uri,deepcopy(args),deepcopy(options)))
                row,=args['imports']
                if args['importOperation']=='replaceExisting':
                    assert 'dialogueEvent' not in row
                    self.child['id']=self.NEW_OWNER;self.replaced=True
                    for old in self.before_links:old['AudioNode']=None
                    self.entry['AudioNode']=None
                else:
                    assert args['importOperation']=='useExisting'
                    assert row['dialogueEvent']==self.event['path']+'@Path:<Switch Group:Surface>Snow'
                    self.entry['AudioNode']={'id':self.NEW_OWNER}
                return {'objects':[deepcopy(self.child)],'log':[],'files':[]}
            return super().call(uri,args,options)
    client=StagedClient(tmp_path,'2025.1');event_before=deepcopy(client.event)
    first,_,_=_import_fields_draft(tmp_path,'2025.1',client)
    old=first('draft-bind-object','--object-id',client.CHILD)['bound_object']['handle']
    first('draft-business-configure','--mode','replace')
    first('draft-declare-existing','--declaration-id','replacement','--object-handle',old)
    first('draft-check');tx1=first('preview-from-draft')['transaction_id'];shown=first('transaction-show',tx1)
    first('confirm',tx1,'--confirmation-token',shown['confirmation']['token']);first('execute',tx1)
    assert first('verify',tx1)['verified'] is True
    second,_,_=_import_fields_draft(tmp_path,'2025.1',client)
    owner=second('draft-bind-object','--object-id',client.NEW_OWNER)['bound_object']['handle']
    event=second('draft-bind-object','--object-id',client.EVENT)['bound_object']['handle']
    group=second('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
    value=second('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
    second('draft-declare-existing','--declaration-id','association','--object-handle',owner,
        '--dialogue-event-handle',event,'--dialogue-condition',group,value)
    second('draft-check');tx2=second('preview-from-draft')['transaction_id'];shown=second('transaction-show',tx2)
    second('confirm',tx2,'--confirmation-token',shown['confirmation']['token']);second('execute',tx2)
    result=second('verify',tx2)
    assert result['verification']['failed_assertion_count']==0,result
    assert not result['verified'] and client.event==event_before and tx1!=tx2
    assert client.entry['AudioNode']['id']==client.NEW_OWNER
    writes=[a for u,a,_ in client.calls if u=='ak.wwise.core.audio.import']
    assert [a['importOperation'] for a in writes]==['replaceExisting','useExisting']
    assert not any(u.endswith(('.setReference','.create','.addAssignment')) for u,_,_ in client.calls)


@pytest.mark.parametrize('mode,legacy',(('replaceExisting',False),('createNew',True)))
def test_historical_dialogue_prewrite_guard_rejects_existing_event_under_replacement(tmp_path,mode,legacy):
    from wwise_waapi.operation_registry import validate_prepared_roles,OperationContractError
    command,client=_existing_event_lifecycle_draft(tmp_path)
    command('draft-check');tx=command('preview-from-draft')['transaction_id'];shown=command('transaction-show',tx)
    # A pre-boundary persisted prepared state had this exact unsafe global mode.
    # Exercise the exported prewrite validator without bypassing a transaction's
    # immutable seal or authorizing any native call.
    historical=deepcopy(shown['artifact']['prepared_operation'])
    historical['dispatch']['args']['importOperation']=mode
    historical['request']['arguments']['import_operation']=mode
    historical['verification_plan']['import_operation']=mode
    if legacy:
        for binding in historical['pre_state']['import_guard']['dialogue_associations']:
            binding.pop('event_id',None);binding.pop('event_before',None)
    with pytest.raises(OperationContractError) as caught:
        validate_prepared_roles(historical,read_call=client.call)
    assert caught.value.error_code=='IMPORT_DIALOGUE_EXISTING_EVENT_MODE_UNSAFE'
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


def test_existing_tsv_dialogue_event_with_create_mode_rejects_before_preview(tmp_path):
    client=ReplacingDialogueClient(tmp_path,'2025.1');client.created=False
    table=tmp_path/'create.tsv';table.write_text('Object Path\tDialogue Event\n<Sound SFX>SnowSounds\t'+client.event['path']+'@Path:<Switch Group:Surface>Snow\n')
    command,_=_table_lifecycle_draft(tmp_path,'2025.1',client,table,mode='create')
    result=command('draft-check',expected_error='IMPORT_DIALOGUE_EXISTING_EVENT_MODE_UNSAFE')
    assert result['details']['safe_workflow'][0]['mode']=='create'
    assert not any(u=='ak.wwise.core.audio.importTabDelimited' for u,_,_ in client.calls)


class StructuralDialogueImportClient(DialogueImportClient):
    """Fake only native structural import/readback; no media Source is created."""
    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        self.media = False
        self.child = {key: value for key, value in self.child.items()
                      if key in {'id', 'name', 'path', 'parent'}}
        self.child.update(type='SwitchContainer', classId=655376)
        self.effect = True

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.getTypes':
            result = super().call(uri, args, options)
            result['return'].append({'name':'SwitchContainer','type':'WObject','classId':655376})
            return result
        if uri == 'ak.wwise.core.audio.import':
            self.calls.append((uri,deepcopy(args),deepcopy(options)))
            assert args['imports'] == [{'objectPath': self.parent['path']+r'\<Switch Container>SnowSounds',
                'objectType':'SwitchContainer', 'dialogueEvent':self.expected_dialogue}]
            self.created = self.event_created = True
            self.linked = self.effect
            result = {'objects':deepcopy([self.child,self.event])}
            if self.version in {'2023.1','2024.1','2025.1'}:result.update(log=[],files=[])
            return result
        return super().call(uri,args,options)


def _structural_dialogue_draft(tmp_path, version='2025.1', *, kind='switch-container', conditions=True):
    client = StructuralDialogueImportClient(tmp_path, version)
    command,parent,_ = _import_fields_draft(tmp_path, version, client)
    event_parent = command('draft-bind-object','--object-id',client.EVENT_PARENT)['bound_object']['handle']
    condition = ()
    if conditions:
        group = command('draft-bind-object','--object-id',client.GROUP)['bound_object']['handle']
        value = command('draft-bind-object','--object-id',client.VALUE)['bound_object']['handle']
        condition = ('--dialogue-condition',group,value)
    command('draft-declare-new','--declaration-id','snow','--parent-handle',parent,
        '--name','SnowSounds','--kind',kind,
        '--dialogue-event-parent-handle',event_parent,'--dialogue-event-name','Greeting',*condition)
    client.expected_dialogue=client.event['path']+('@Path:<Switch Group:Surface>Snow' if conditions else '')
    return command,client


@pytest.mark.parametrize('version', ('2021.1','2022.1','2023.1','2024.1','2025.1'))
def test_structural_dialogue_import_admits_owner_from_matching_live_audio_node_metadata(tmp_path, version):
    command,client = _structural_dialogue_draft(tmp_path, version)
    command('draft-check');tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    result=command('verify',tx)
    # Observable association succeeds; exact decision sequence remains disclosed.
    assert result['verified'] is False and result['verification']['status']=='result_schema_checked',result
    assert result['verification']['failed_assertion_count']==0,result
    assert client.entry['owner']['id']==client.EVENT and client.entry['AudioNode']['id']==client.CHILD
    assert client.child['type']=='SwitchContainer'
    assert len([u for u,_,_ in client.calls if u=='ak.wwise.core.audio.import'])==1
    assert not any(u.endswith(('.setReference','.create','.set')) for u,_,_ in client.calls)
    assert not Path(client.source['originalFilePath']).exists()


def test_structural_dialogue_import_rejects_metadata_disallowed_actor_mixer_even_without_conditions(tmp_path):
    command,client = _structural_dialogue_draft(tmp_path,kind='actor-mixer',conditions=False)
    command('draft-check',expected_error='INVALID_REFERENCE_TARGET')
    assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)


@pytest.mark.parametrize('fault', ('metadata-drift','missing-association'))
def test_structural_dialogue_import_preserves_metadata_drift_and_requested_effect_guards(tmp_path, fault):
    command,client = _structural_dialogue_draft(tmp_path)
    command('draft-check');tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token'])
    if fault=='metadata-drift':
        client.metadata['restriction']={'type':'reference','restrictions':[{'type':['Sound']}]}
        command('execute',tx,expected_error='ROLE_GUARD_MISMATCH')
        assert not any(u=='ak.wwise.core.audio.import' for u,_,_ in client.calls)
        return
    client.effect=False
    command('execute',tx)
    code,result=waapi_gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'verify',tx],
        env=set_gateway_config(_env(tmp_path),wwise_version='2025.1'),client_factory=lambda _url:client)
    assert code==2 and result['verification']['status']=='verification_failed',result
    assert any(not row['passed'] and 'Dialogue creation' in row['name'] for row in result['verification']['assertions'])


def test_structural_name_only_dialogue_creation_uses_metadata_admission_without_implied_entry(tmp_path):
    command,client = _structural_dialogue_draft(tmp_path,conditions=False)
    client.effect=False
    command('draft-check');tx=command('preview-from-draft')['transaction_id']
    shown=command('transaction-show',tx)
    command('confirm',tx,'--confirmation-token',shown['confirmation']['token']);command('execute',tx)
    assert command('verify',tx)['verified'] is True
    assert client.event_created and not client.linked
    assert any(u.endswith('getPropertyInfo') and args.get('property')=='AudioNode' for u,args,_ in client.calls)
    assert not Path(client.source['originalFilePath']).exists()

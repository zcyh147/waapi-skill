"""Compare pinned native SoundEngine parameters with closed public inputs.

This is a source comparison, without execution receipts or completion admission.
"""
from __future__ import annotations

from collections import Counter
import json

from tests.maintenance.branch_coverage_audit import digest, schema_branches

BASE = 'tests/fixtures/branch-evidence/product/soundengine-195-r1/'
LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
GROUPS = {
    'registration': ('registerGameObj', 'unregisterGameObj'),
    'playback': ('postEvent', 'executeActionOnEvent', 'seekOnEvent', 'stopAll', 'stopPlayingID'),
    'state-switch': ('setState', 'setSwitch'),
    'getter-projection': ('getState', 'getSwitch'),
    'values-trigger': ('setRTPCValue', 'resetRTPCValue', 'postTrigger'),
    'listener-spatial': ('setDefaultListeners', 'setListeners', 'setPosition', 'setMultiplePositions',
        'setObjectObstructionAndOcclusion', 'setScalingFactor', 'setGameObjectOutputBusVolume',
        'setListenerSpatialization', 'setGameObjectAuxSendValues'),
    'banks': ('loadBank', 'unloadBank'),
    'monitor': ('postMsgMonitor',),
}
GETTERS = {'getState', 'getSwitch'}




def discover_soundengine(root):
    """Expand the five pinned native SoundEngine schemas and reachable definitions."""
    from wwise_waapi.native_catalog import load_native_catalog
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.soundengine_business_contracts import soundengine_control_business_operations, soundengine_control_business_versions
    operations = soundengine_control_business_operations()
    if operations != {'ak.soundengine.' + name for names in GROUPS.values() for name in names}:
        raise ValueError('SoundEngine closed URI roster changed')
    routes, rows, catalogs = [], [], {}
    for version in VERSIONS:
        wanted = {uri for uri in operations if version in soundengine_control_business_versions(uri)}
        for host in ('wwise-console', 'wwise-authoring'):
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            if {uri for uri in catalog['functions'] if uri.startswith('ak.soundengine.')} != wanted:
                raise ValueError('SoundEngine native version/host/URI roster differs')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            definitions = catalog['definitions']
            graph = DefinitionGraph(**{key: definitions[key] for key in ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            for uri in sorted(wanted):
                identity = f'{version}|{host}|{build}|function|{uri}'
                routes.append({'id': identity, 'version': version, 'host': host, 'build': build,
                    'kind': 'function', 'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]),
                    'public_route': f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    schema = catalog['schemas'][uri][section]
                    visited = set()
                    def visit(value, pointer, context, document, active):
                        for item in schema_branches(value, pointer):
                            row = {'id': identity + '|' + item['pointer'], 'route': identity,
                                'pointer': item['pointer'], 'kind': item['kind'], 'shape_sha256': digest(item['value'])}
                            if item['kind'] != 'schema':
                                row['value'] = item['value']
                            rows.append(row)
                            if item['kind'] != 'reference':
                                continue
                            target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                            doc = document if target.document_name == '<schema>' else target.document_name
                            key = (doc, target.pointer)
                            ptr = '/' + section + '/@definition/' + doc + target.pointer
                            row['reference'] = {'target': identity + '|' + ptr, 'recursive': key in active,
                                'document': doc, 'target_sha256': digest(target.target)}
                            if key not in visited:
                                visited.add(key)
                                visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc], doc, active | {key})
                    visit(schema, '/' + section, schema, '<schema>', set())
    if len(routes) != 248 or len(rows) != len({row['id'] for row in rows}):
        raise ValueError('SoundEngine exact native component changed')
    return {'routes': routes, 'catalogs': catalogs, 'parameters': rows}

def soundengine_component(root):
    """Compare the reflected fields with current closed public contracts."""
    from wwise_waapi.soundengine_business_contracts import soundengine_control_business_contract_data
    native = discover_soundengine(root)
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    observed = {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']}
                for row in native['parameters']}
    if roster['entries'] != observed or roster['catalogs'] != native['catalogs']:
        raise ValueError('Unhandled or missing SoundEngine native field/choice/version/definition')
    wanted = {row['public_route'] for row in native['routes']}
    surface = json.loads((root / 'skills/waapi-skill/resources/manifest/typed-request-surface.json').read_bytes())
    packaged = {f"{row['version']}|{row['item_type']}|{row['uri']}": row for row in surface['lanes']}
    if not wanted <= packaged.keys():
        raise ValueError('SoundEngine current public version/route missing')
    public = []
    for identity in sorted(wanted):
        version, _, uri = identity.split('|')
        contract = soundengine_control_business_contract_data(uri, version)
        public.append({'id': identity, 'public_contract': contract,
                       'correct_host': packaged[identity]['correct_host']})
    return {'routes': public, 'native': native}


def field_rules(name, version):
    """Finite business encodings, independently read from #185's compiler."""
    handle = lambda field: ([field], 'bound exact role GUID; live identity/type/relationship revalidation')
    runtime = (['game_object_handle'], 'active context-bound game-object generation; never caller numeric ID')
    emitter = (['emitter_handle'], 'active context-bound emitter game-object generation')
    listener = (['listener_handle'], 'active context-bound listener game-object generation')
    fields = {
        'postMsgMonitor': {'message': (['monitor_message'], 'exact nonempty UTF-8 message; 16384-byte Gateway ceiling; no monitor receipt claim')},
        'registerGameObj': {'gameObject': (['game_object_name'], 'nonzero 63-bit context/name digest; Gateway-owned allocation'), 'name': (['game_object_name'], 'exact nonempty UTF-8 monitoring name; 512-byte Gateway ceiling')},
        'unregisterGameObj': {'gameObject': (['game_object_handle', 'all_game_objects'], 'one active generation or explicit all-game-objects uint64 sentinel; consumes registration authority, preserves playing authority')},
        'postEvent': {'event': handle('event_handle'), 'gameObject': runtime},
        'executeActionOnEvent': {'event': handle('event_handle'), 'actionType': (['action'], 'Stop=0; Pause=1; Resume=2; Break=3; ReleaseEnvelope=4'), 'gameObject': (['game_object_handle'], 'active generation or omitted public handle emits uint64 all-object sentinel'), 'transitionDuration': (['fade_duration_ms'], 'whole 0..2147483647 ms; default 0'), 'fadeCurve': (['fade_curve'], 'Log3=0; Sine=1; Log1=2; InvSCurve=3; Linear=4; SCurve=5; Exp1=6; SineRecip=7; Exp3=8; default Linear; SDK Constant=9 is invalid for fades')},
        'stopAll': {'gameObject': (['game_object_handle'], 'active generation or omitted public handle emits uint64 all-object sentinel; retires matching active and pending playing authority')},
        'seekOnEvent': {'event': handle('event_handle'), 'gameObject': (['game_object_handle'], 'active generation or uint64 all-object sentinel; mutually exclusive with playing_handle'), 'playingId': (['playing_handle'], 'active Event-matched playing generation or zero for Event scope; never transfers reused native IDs'), 'position': (['position_ms'], 'whole nonnegative int32 ms; exactly one of position_ms or position_percent'), 'percent': (['position_percent'], 'position_percent / 100; exactly one of position_ms or position_percent'), 'seekToNearestMarker': (['nearest_marker'], 'boolean identity; default false')},
        'setState': {'stateGroup': handle('state_group_handle'), 'state': handle('state_handle')},
        'setSwitch': {'switchGroup': handle('switch_group_handle'), 'switchState': handle('switch_handle'), 'gameObject': runtime},
        'postTrigger': {'trigger': handle('trigger_handle'), 'gameObject': runtime},
        'setRTPCValue': {'rtpc': handle('game_parameter_handle'), 'value': (['value'], 'finite scalar identity'), 'gameObject': runtime},
        'resetRTPCValue': {'rtpc': handle('game_parameter_handle'), 'gameObject': runtime},
        'loadBank': {'soundBank': handle('sound_bank_handle')},
        'unloadBank': {'soundBank': handle('sound_bank_handle')},
        'setDefaultListeners': {'listeners': (['listener_handles', 'clear_listeners'], '1..64 distinct active generations or explicit empty clear; Gateway ceiling, native uint32 capacity retained')},
        'setListeners': {'emitter': emitter, 'listeners': (['listener_handles', 'clear_listeners'], '1..64 distinct active generations or explicit empty clear; Gateway ceiling')},
        'setPosition': {'gameObject': runtime, 'position': (['position_frame'], 'nine finite values: position xyz, front xyz, top xyz; nonzero nonparallel orientation')},
        'setMultiplePositions': {'gameObject': runtime, 'positions': (['position_frames', 'clear_positions'], '1..256 frames or explicit empty clear; each native item.position holds nine-value xyz/front/top frame; Gateway ceiling'), 'multiPositionType': (['multi_position_mode'], 'SingleSource=0; MultiSources=1; MultiDirections=2')},
        'setObjectObstructionAndOcclusion': {'emitter': emitter, 'listener': listener, 'obstructionLevel': (['obstruction_percent'], '0..100 percent / 100'), 'occlusionLevel': (['occlusion_percent'], '0..100 percent / 100')},
        'setScalingFactor': {'gameObject': runtime, 'attenuationScalingFactor': (['attenuation_scale_percent'], 'positive finite percentage / 100')},
        'setGameObjectOutputBusVolume': {'emitter': emitter, 'listener': (['listener_handle', 'all_listeners'], 'one active generation or explicit all-listener uint64 sentinel'), 'controlValue': (['volume_percent', 'volume_db'], 'exactly one: 0..1600 percent / 100 (zero=silence), or 10**(dB/20) with gain <=16')},
        'setListenerSpatialization': {'listener': listener, 'spatialized': (['spatialization'], 'enabled=true; disabled=false'), 'channelConfig': (['channel_layout', 'channel_layout_kind', 'channel_speakers', 'channel_count'], 'preset or Standard speaker mask: count | 1<<8 | mask<<12; Anonymous=count; Ambisonic=count | 2<<8; Objects=3<<8; HSL/HSR only 2024.1+'), 'volumeOffsets': (['speaker_offsets_db', 'channel_offsets_db'], 'ordered named speakers (LFE last) or one-based channels; omitted offsets zero dB; Objects empty; finite -200..200 dB')},
        'setGameObjectAuxSendValues': {'gameObject': (['emitter_handle'], emitter[1]), 'auxSendValues': (['aux_sends', 'aux_sends_all_listeners', 'clear_aux_sends'], '1..4 distinct listener/AuxBus pairs or explicit empty clear; each row listener=active generation or uint64 sentinel, auxBus=bound exact AuxBus GUID, controlValue=0..1600 percent / 100')},
        'getState': {'stateGroup': (['state_group_id'], 'exact GUID from Gateway read; live StateGroup type revalidation')},
        'getSwitch': {'switchGroup': (['switch_group_id'], 'exact GUID from Gateway read; live SwitchGroup type revalidation'), 'gameObject': runtime},
    }[name]
    if name in {'setRTPCValue', 'resetRTPCValue'}:
        fields['gameObject'] = (['game_object_handle', 'global_scope'], 'object generation or explicit global uint64 sentinel; omission only 2023.1+ means transport game object, not global')
    if name in {'postTrigger', 'setSwitch'}:
        fields['gameObject'] = (['game_object_handle'], 'active generation; required 2021.1/2022.1; omission 2023.1+ uses native transport default')
    if name == 'postEvent':
        fields['gameObject'] = (['game_object_handle'], 'active generation; required through 2023.1; omission 2024.1+ uses native invalid-game-object default')
    if name == 'getSwitch':
        fields['gameObject'] = (['game_object_handle'],
            'required active context-bound runtime generation; omitted public handle is rejected' if version == '2022.1' else
            'present handle binds an active context-bound runtime generation; absent handle omits native gameObject; '
            + ('2025.1 pinned description specifies AK_INVALID_GAME_OBJECT' if version == '2025.1'
                else 'pinned schema permits omission without stating its default value')
            + '; no equivalence to the setter omitted-object scope is claimed')
    return fields

def _rules(name, version):
    if name == 'stopPlayingID':
        fade = field_rules('executeActionOnEvent', version)
        return {'playingId': (['playing_handle'], 'active playing generation consumed after durable execution start; never replayed'),
            **{key: fade[key] for key in ('transitionDuration', 'fadeCurve')}}
    return field_rules(name, version)

def _nested_value_paths(name, pointer):
    """Index exact closed tuple members rather than inheriting a parent label."""
    parts = pointer.split('/')
    if name in {'setPosition', 'setMultiplePositions'} and len(parts) >= 4 and parts[-2] == 'properties' and parts[-1] in {'x', 'y', 'z'}:
        vector = parts[-3]
        # The immediately enclosing property appears before /properties/x.
        if vector in {'position', 'orientationFront', 'orientationTop'}:
            index = {'position': 0, 'orientationFront': 3, 'orientationTop': 6}[vector] + {'x': 0, 'y': 1, 'z': 2}[parts[-1]]
            return [('position_frame' if name == 'setPosition' else 'position_frames[*]') + f'[{index}]']
    if name == 'setGameObjectAuxSendValues' and '/items/properties/' in pointer:
        field = pointer.split('/items/properties/', 1)[1].split('/')[0]
        return {'listener': ['aux_sends[*][0]', 'aux_sends_all_listeners: Gateway uint64 sentinel'],
            'auxBus': ['aux_sends[*][1]', 'aux_sends_all_listeners[*][0]'],
            'controlValue': ['aux_sends[*][2] / 100', 'aux_sends_all_listeners[*][1] / 100']}.get(field, [])
    return []

def _getter_correspondence(row, version):
    """Join concrete compilers and rejection, never full-language equivalence."""
    from wwise_waapi.soundengine_object_returns import soundengine_object_outputs
    pointer = row['pointer']
    section = pointer.split('/')[1]
    outputs = soundengine_object_outputs(version)
    if section == 'optionsSchema' and '/definitions/returnExpression/items/anyOf/1' in pointer:
        # 2022 has a nonempty accessor/function regex (a constraint node),
        # whereas later schemas merely describe dot property/reference reads.
        # A string schema does not enumerate every possible caller program.
        # Map the delivered closed positive mechanisms and the rejected empty
        # input separately, without inventing native absence or a language gap.
        rule = ('gateway_empty_accessor_rejection' if row['kind'] == 'empty_string'
            else 'native_accessor_grammar_constraint' if row['kind'] == 'constraint'
            else 'metadata_compiled_getter_accessor')
        return {'rule': rule, 'native_pointer': pointer, 'native_fields': ['return'],
            'public_fields': ['fields', 'override_source_values', 'local_references',
                'related_outputs', 'related_fields', 'related_override_source_values', 'related_local_references'],
            'value_paths': [], 'native_language_equivalence': 'not_claimed',
            'helper_values_are_native_getter_values': False,
            'native_constraint': row.get('value') if row['kind'] == 'constraint' else None,
            'encoding': ('empty meanings and caller raw accessor/function grammar are rejected before connection; this is a Gateway input boundary, not native absence'
                if row['kind'] == 'empty_string' else
                'live exact State/Switch class metadata owns @property, @@property and resolved/local reference tokens; '
                'closed related paths compile through existing RelatedListPlan.render (for example parent.@Volume); '
                '2022 generated native tokens retain its pinned nonempty accessor/function regex; '
                'each preparation/final getter guards exact identity and runtime generation; '
                'final getter supplies singleton/native-composed values; grouped/sequence/context helper values remain separately observed and non-atomic'),
            'mechanisms': {'direct': LIB + 'soundengine_object_returns.py#compile_soundengine_field_meanings',
                'metadata': GATEWAY + '#_bind_query_custom_fields_from_live_metadata',
                'related': LIB + 'soundengine_related_outputs.py#SoundEngineRelatedProjection',
                'native_render': LIB + 'object_query_related_lists.py#RelatedListPlan',
                'input_rejection': LIB + 'object_query_related.py#_meaning'}}
    native = row.get('value') if row['kind'] == 'enum_value' and section == 'optionsSchema' else None
    choices = [name for name, (token, output) in outputs.items() if token == native] if native else []
    if native is not None and not choices:
        raise ValueError('Unhandled SoundEngine native getter return choice: ' + str(native))
    if '/definitions/objectReturn/properties/' in pointer:
        native = pointer.split('/definitions/objectReturn/properties/', 1)[1].split('/')[0]
        choices = [name for name, (token, output) in outputs.items() if token == native]
        if not choices:
            raise ValueError('Unhandled SoundEngine native getter result accessor: ' + native)
    fields = ['outputs', 'platform', 'language'] if section == 'optionsSchema' else ['outputs', 'fields',
        'override_source_values', 'local_references', 'related_outputs', 'related_fields',
        'related_override_source_values', 'related_local_references']
    if section == 'optionsSchema':
        if '/properties/platform' in pointer:
            fields = ['platform']
        elif '/properties/language' in pointer:
            fields = ['language']
        elif '/properties/return' in pointer or '/definitions/returnExpression' in pointer:
            fields = ['outputs']
    return {'rule': 'forwarded_closed_getter_return_options' if section == 'optionsSchema' else 'selected_getter_result_projection',
        'native_pointer': pointer, 'native_fields': [native] if native else [], 'public_fields': fields,
        'public_choices': choices, 'value_paths': [],
        'encoding': ('--include selects only versioned business choices; compiler forwards fixed native return spellings, always retains id/name; '
            '--platform/--language forward validated literal names or GUIDs; omitted scopes preserve native defaults; '
            'no arbitrary caller-authored return expression'
            if section == 'optionsSchema' else
            'requested fixed accessor values are preserved under disclosed business keys; absent requested values remain unavailable_fields; '
            'null stays null; declared-return observations retain actual raw keys and values without alias-equivalence claims; '
            'metadata-compiled fields and final native singleton/composed related values use the existing projector; '
            'grouped/sequence/context helper values keep separate provenance; schema/result shape proves no runtime setter effect'),
        **({'native_choice': row['value']} if row['kind'] in {'enum_value', 'boolean_value', 'optional_presence', 'default', 'collection_cardinality'} else {})}

def soundengine_bindings(root, inventory):
    """Exact field joins for the reviewed closed business surface."""
    from wwise_waapi.soundengine_business_contracts import soundengine_control_business_contract_data
    public = {row['id']: row for row in inventory['routes']}
    branches = inventory['native']['parameters']
    grouped = {}
    for row in branches:
        grouped.setdefault(row['route'], []).append(row)
    bindings = {}
    for route in inventory['native']['routes']:
        version, name = route['version'], route['uri'].rsplit('.', 1)[1]
        rules = _rules(name, version)
        contract = soundengine_control_business_contract_data(route['uri'], version)
        exposed = set(contract['declaration']['required_fields']) | set(contract['declaration']['optional_fields'])
        if {field for fields, encoding in rules.values() for field in fields} - exposed:
            raise ValueError('SoundEngine mapped public field/choice is not disclosed')
        rows = grouped[route['id']]
        roots = [row for row in rows if row['pointer'].startswith('/argsSchema/properties/') and row['pointer'].count('/') == 3]
        if {row['pointer'].split('/')[3] for row in roots} != set(rules):
            raise ValueError('Unhandled or missing SoundEngine native argument field')
        origins = {row['id']: set() for row in rows}
        # A shared definition records all reaching native fields, rather than
        # attributing one arbitrary first reference to every identity union.
        for field in rules:
            prefix = route['id'] + '|/argsSchema/properties/' + field
            pending = [row['id'] for row in rows if row['id'] == prefix or row['id'].startswith(prefix + '/')]
            visited = set()
            while pending:
                identity = pending.pop()
                if identity in visited:
                    continue
                visited.add(identity)
                origins[identity].add(field)
                row = next(row for row in rows if row['id'] == identity)
                if 'reference' in row:
                    target = row['reference']['target']
                    pending.extend(row['id'] for row in rows if row['id'] == target or row['id'].startswith(target + '/'))
        for row in rows:
            pointer = row['pointer']
            section = pointer.split('/')[1]
            getter = _getter_correspondence(row, version) if name in GETTERS and section in {'optionsSchema', 'resultSchema'} else None
            if getter and set(getter['public_fields']) - exposed:
                raise ValueError('SoundEngine mapped getter field/choice is not disclosed')
            fields = sorted(origins[row['id']])
            if section == 'argsSchema':
                fields = fields or sorted(rules)
                public_fields = sorted({field for native in fields for field in rules[native][0]})
                encoding = '; '.join(dict.fromkeys(rules[native][1] for native in fields))
                rule = 'closed_field_encoding' if origins[row['id']] else 'closed_argument_envelope'
            elif section == 'optionsSchema':
                public_fields, encoding, rule = [], 'Gateway emits {}', 'fixed_empty_options'
            else:
                public_fields, rule = [], 'bounded_native_result'
                encoding = ('native return playing ID: zero is failure, positive uint32 becomes opaque Event/object-bound playing generation'
                    if name == 'postEvent' else 'empty acknowledgement; no independent native effect certified by schema validation')
            read = name in GETTERS
            binding = {'parameter_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
                'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
                'input': {'gateway_argv': ['core-call' if read else 'draft-start', route['uri']],
                    'declaration': 'core-call' if read else 'draft-declare-soundengine-plan', 'selector': pointer,
                    'correspondence': getter or {'rule': rule, 'native_pointer': pointer, 'native_fields': fields,
                        'public_fields': public_fields, 'value_paths': _nested_value_paths(name, pointer), 'encoding': encoding,
                        **({'native_choice': row['value']} if row['kind'] in {'enum_value', 'boolean_value', 'optional_presence', 'default', 'collection_cardinality'} else {})}},
            }
            if name == 'getSwitch' and section == 'argsSchema' and 'gameObject' in fields:
                scope = {'required': version == '2022.1', 'present': 'active_context_bound_runtime_generation',
                    'absent': 'rejected_required_field' if version == '2022.1' else 'native_argument_omitted',
                    'native_default': 'AK_INVALID_GAME_OBJECT' if version == '2025.1' else 'not_stated_by_pinned_schema',
                    'setter_omission_equivalence': 'not_claimed'}
                if row['kind'] == 'optional_presence':
                    scope['selected_native_presence'] = 'omitted' if row['value'] == 'absent' else 'present_bound_generation'
                    binding['input']['correspondence']['encoding'] = (
                        'absent game_object_handle omits native gameObject; ' +
                        ('2025.1 pinned default is AK_INVALID_GAME_OBJECT' if version == '2025.1'
                         else 'pinned schema does not state the omitted native default')
                        if row['value'] == 'absent' else 'present game_object_handle resolves one active context-bound runtime generation')
                binding['input']['correspondence']['game_object_scope'] = scope
            bindings[row['id']] = binding
    return bindings

def soundengine_gaps(inventory, bindings):
    """Report native fields without a closed public correspondence."""
    missing = [row for row in inventory['native']['parameters'] if row['id'] not in bindings]
    return {'counts': dict(Counter(row['id'].split('|')[0] for row in missing)),
            'members': {row['id']: row['shape_sha256'] for row in missing}}

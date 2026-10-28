"""Exact #185 native/public joins; mappings never assert native execution.

The checked-in roster seals the reviewed five-version definitions. A changed
field, choice, reference or version fails before it can inherit a family rule.
Getter projection omissions remain explicit gaps, never approved boundaries.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json

from tests.maintenance.branch_coverage_audit import digest, schema_branches

BASE = 'tests/fixtures/branch-evidence/product/soundengine-195-r1/'
LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
TICKET = 'docs/plans/full-waapi-coverage/tickets/11-complete-soundengine-control-branches-and-capability-lifetimes.md'
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
    """Bounded source expansion matching native_coverage's exact identities."""
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
                                'pointer': item['pointer'], 'kind': item['kind'], 'shape_sha256': digest(item['value']),
                                'owner_issue': 185, 'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
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
    return {'routes': routes, 'catalogs': catalogs, 'obligations': rows}


def soundengine_component(root):
    """Read the existing public snapshot, checking it against current contracts."""
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    from wwise_waapi.soundengine_business_contracts import soundengine_control_business_contract_data
    from wwise_waapi.operation_registry import operation_business_contract
    native = discover_soundengine(root)
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    observed = {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in native['obligations']}
    if roster['entries'] != observed or roster['catalogs'] != native['catalogs']:
        raise ValueError('Unhandled or missing SoundEngine native field/choice/version/definition')
    wanted = {row['public_route'] for row in native['routes']}
    public = [deepcopy(row) for row in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes'] if row['id'] in wanted]
    if {row['id'] for row in public} != wanted:
        raise ValueError('SoundEngine current public version/route missing')
    surface = json.loads((root / 'skills/waapi-skill/resources/manifest/typed-request-surface.json').read_bytes())
    packaged = {f"{row['version']}|{row['item_type']}|{row['uri']}": row for row in surface['lanes']}
    for row in public:
        version, _, uri = row['id'].split('|')
        expected = digest(soundengine_control_business_contract_data(uri, version))
        # Adapter contract digests seal the version-aware public declaration;
        # named registry rows can additionally expose the operation envelope.
        if row['execution_policy'] != packaged[row['id']]['execution_policy']:
            raise ValueError('SoundEngine public snapshot no longer matches current execution policy')
        # Component-local current contract projection. The canonical snapshot's
        # native field-contract seal is unchanged by a closed business addition;
        # global regeneration remains the integration owner's publication step.
        row['public_contracts'] = [expected]
        for named in row['named_operations']:
            if named['contract'] != digest(operation_business_contract(named['name'], version)):
                raise ValueError('SoundEngine named public contract changed')
    sources = debug_control_component(root)['sources']
    for name in (TICKET, 'tests/maintenance/soundengine_branch_mapping.py',
            'tests/semantic/support/codex_archive_paths.py', BASE + 'source-roster.json'):
        sources[name] = digest((root / name).read_text(encoding='utf-8'))
    inventory = {'component': 'soundengine-195-r1', 'routes': public, 'sources': sources, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, inventory, native['catalogs'], digest=digest)
    return inventory


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
    branches = inventory['native_coverage']['obligations']
    grouped = {}
    for row in branches:
        grouped.setdefault(row['route'], []).append(row)
    bindings = {}
    for route in inventory['native_coverage']['routes']:
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
        mechanism = next(group for group, names in GROUPS.items() if name in names)
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
            source = GATEWAY + '#dispatch_soundengine_business_read' if read else LIB + 'soundengine_business.py#materialize_soundengine_control_business_request'
            binding = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
                'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
                'input': {'gateway_argv': ['core-call' if read else 'draft-start', route['uri']],
                    'declaration': 'core-call' if read else 'draft-declare-soundengine-plan', 'selector': pointer,
                    'correspondence': getter or {'rule': rule, 'native_pointer': pointer, 'native_fields': fields,
                        'public_fields': public_fields, 'value_paths': _nested_value_paths(name, pointer), 'encoding': encoding,
                        **({'native_choice': row['value']} if row['kind'] in {'enum_value', 'boolean_value', 'optional_presence', 'default', 'collection_cardinality'} else {})}},
                'construction': {'source': source, 'selector': pointer},
                'validation': {'source': LIB + 'builders/schema.py#' + ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': pointer},
                'verifier': {'source': GATEWAY + '#dispatch_soundengine_business_read' if read else LIB + 'operation_registry.py#verify_prepared_operation', 'selector': pointer},
                'representative_mechanism': 'soundengine195-' + mechanism + '-v1', 'evidence': {}}
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
    """Retain every unresolved field as assigned work, with no exclusion credit."""
    missing = [row for row in inventory['native_coverage']['obligations'] if row['id'] not in bindings]
    return {'contract': 'waapi-skill.soundengine-mapping-gaps/v1', 'owner_issue': 195,
        'reason': 'Exact source review found no concrete legitimate documented getter field/path missing from finite, live-metadata or existing related mechanisms; generic string schemas are not an infinite caller-language requirement. Bounded raw/empty-input rejection and helper-value provenance remain explicit in each mapping.',
        'disposition': 'no_concrete_functional_gap_found' if not missing else 'unresolved_public_support_not_native_absence_or_approved_exclusion',
        'counts': dict(Counter(row['id'].split('|')[0] for row in missing)),
        'members': {row['id']: row['shape_sha256'] for row in missing}}


SELECTED_TESTS = {
    # #185 already accepted the family field/lifetime controls. The new capture
    # establishes their unchanged shared Draft/registration seam, rather than
    # repeating twelve family functions or implying leaf execution receipts.
    **{group: ['test_monitor_message_uses_one_business_draft_and_seals_native_preview',
        'test_register_game_object_derives_native_id_and_binds_cleanup']
        for group in ('registration', 'playback', 'values-trigger', 'listener-spatial', 'banks')},
    'state-switch': ['test_state_switch_write_is_verified_by_independent_exact_scope_getter'],
    'getter-projection': ['test_getter_binds_custom_field_meanings_to_live_state_class_before_one_dispatch',
        'test_getter_related_projection_uses_the_final_native_getter_value',
        'test_getter_existing_related_list_form_preserves_native_or_grouped_value_provenance',
        'test_getter_custom_fields_reject_raw_meanings_duplicates_limits_and_unrelated_options[extra3]'],
    'monitor': ['test_monitor_message_uses_one_business_draft_and_seals_native_preview'],
}
TEST_FILE = 'tests/unit/test_soundengine_business_gateway.py'
RUNTIME_SOURCES = {
    GATEWAY, TEST_FILE, 'tests/support/gateway_config.py',
    *(LIB + name + '.py' for name in ('soundengine_business', 'soundengine_business_contracts',
        'soundengine_lifecycle', 'runtime_game_object_handles', 'runtime_playing_handles',
        'business_adapters', 'business_declaration_state', 'business_declarations',
        'operation_registry', 'operation_drafts', 'operation_composer', 'transactions',
        'transaction_runtime', 'transaction_cleanup', 'dispatcher', 'config',
        'capabilities', 'execution_contracts', 'builders/schema', 'io_policy',
        'soundengine_object_returns', 'soundengine_related_outputs', 'object_query_outputs', 'builders/query',
        'metadata_discovery', 'builders/metadata', 'object_query_related', 'object_query_related_lists',
        'object_query_related_metadata', 'object_query_related_runtime', 'reference_kind_evidence')),
}


def soundengine_artifact_coordinates(output, product):
    """Derive publication identities with the shared archive-path boundary."""
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    relative = archive_relative_from_absolute(output, product)
    return relative.canonical, '/'.join('..' for _ in relative.parts)


def soundengine_export(root, output, run):
    """Publish component-local attachments at the existing portable reader seam.

    ``run`` is an actual finalized ordinary run, not a test-name declaration.
    Its aggregate strength and lack of per-node/native observations survive.
    """
    import subprocess
    from tests.maintenance.branch_audit_completion import binding_semantics
    from tests.support.ordinary_test_run_evidence import RUNNER_SOURCES
    inventory = soundengine_component(root)
    bindings = soundengine_bindings(root, inventory)
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    plan = json.loads((run / 'run.plan.json').read_bytes())
    result = json.loads((run / 'run.result.json').read_bytes())
    summary = json.loads((run / 'run.summary.json').read_bytes())
    if (result.get('candidate_unchanged') is not True or result.get('exit_code') != 0
            or result.get('git_status') != '' or result.get('remaining_owned_processes') != []
            or summary.get('status') != 'PASS' or summary.get('source_unchanged') is not True
            or summary.get('skipped') != 0 or result.get('head_after') != plan.get('candidate')):
        raise ValueError('SoundEngine selected code anchor is missing or unfinalized')
    selected = {group: [TEST_FILE + '::' + name for name in names] for group, names in SELECTED_TESTS.items()}
    if not {node for nodes in selected.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('SoundEngine code anchor omits a selected mechanism')
    # Relevant current behavior must match the captured Git sources. Later
    # publication may restamp the global candidate, never silently rewrite this.
    sources = set(RUNTIME_SOURCES)
    original_sources = {}
    for name in sources | RUNNER_SOURCES:
        original = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        seal = hashlib.sha256(original).hexdigest()
        original_sources[name] = seal
        if name in sources and hashlib.sha256((root / name).read_bytes()).hexdigest() != seal:
            raise ValueError('SoundEngine selected code source changed: ' + name)
    product = root / 'tests/fixtures/branch-evidence/product'
    prefix, archive_base = soundengine_artifact_coordinates(output, product)
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        raw = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        (output / name).write_bytes(raw)
        return {'artifact': prefix + '/' + name, 'sha256': hashlib.sha256(raw).hexdigest()}
    files = {}
    for key, filename in {'plan': 'run.plan.json', 'result': 'run.result.json', 'summary': 'run.summary.json', 'log': 'run.log', 'exit': 'run.exit'}.items():
        raw = (run / filename).read_bytes()
        (output / filename).write_bytes(raw)
        files[key] = {'artifact': prefix + '/' + filename, 'sha256': hashlib.sha256(raw).hexdigest()}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1',
        'branches': {}, 'representative_mechanisms': {}}
    predecessors, entries = {}, []
    for group in GROUPS:
        mechanism = 'soundengine195-' + group + '-v1'
        members = {identity: binding for identity, binding in bindings.items()
            if binding['representative_mechanism'] == mechanism}
        anchor = next(identity for identity in members if '|wwise-authoring|' in identity and identity.endswith('|/argsSchema'))
        binding = members[anchor]
        binding.update(ordinary_test_run_attachment=True, relevant_sources=sorted(sources))
        policy = {'native_shape_sha256': rows[anchor]['shape_sha256'], 'categories': ['program'],
            'reason': 'Selected ordinary aggregate code mechanism; accepted #185 representative native history remains separately attributed, with no per-leaf/native execution claim'}
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': original_sources,
            'review': {'reason': 'Current selected SoundEngine sources exactly match this actual focused code run; no native or per-node observation is inferred',
                'selection_reason': 'Existing shared Draft/registration controls plus selected getter compiler/provenance/rejection controls; accepted #185 family construction/lifetime history is retained, not rerun per field/API; no per-member execution quota',
                'sources': {name: {'original_sha256': original_sources[name], 'current_sha256': original_sources[name],
                    'reviewed_reason': 'Byte-identical relevant source'} for name in sorted(sources)}, 'skip_attribution': {}},
            'mechanism': {'branch_id': anchor, 'native_route': rows[anchor]['route'], 'native_shape_sha256': rows[anchor]['shape_sha256'],
                'binding_semantics_sha256': digest(binding_semantics(binding)), 'selected_tests': selected[group]}, 'skip_lines': []}
        proof_descriptor = write(group + '-program.json', proof)
        original = deepcopy(binding)
        original['evidence']['program'] = proof_descriptor
        original_document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {anchor: original}}
        original_policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {anchor: policy}}
        origin = {'bindings': write(group + '-original-bindings.json', original_document), 'program': proof_descriptor,
            'requirements': write(group + '-original-requirements.json', original_policy),
            'capture': write(group + '-capture.json', {'scope': 'actual ordinary aggregate run only; no per-node observations', 'files': files})}
        entries.append({'id': 'soundengine195-' + group, 'origin': origin, 'bindings': origin['bindings']})
        predecessors[anchor] = {'binding_sha256': digest(original), 'policy_sha256': digest(policy)}
        for identity in members:
            requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'], 'categories': ['program'],
                'reason': 'User-approved representative #185 mechanism policy; exact legitimate input/result mapping retained; native history gives no invented per-member observation',
                'representative_mechanism': mechanism}
            predecessors.setdefault(identity, None)
        mapping_sources = {members[identity][key]['source'].split('#')[0]
            for identity in members for key in ('construction', 'validation', 'verifier')}
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact source-sealed #185 ' + group + ' mappings; selected existing public Gateway code controls provide aggregate representative support; no member native effect inferred',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in mapping_sources},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({key: value for key, value in binding.items() if key != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': [anchor]}}
    write('requirements.json', requirements)
    attachment = {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'product',
        'requirements_sha256': digest(requirements), 'mechanisms': list(requirements['representative_mechanisms']),
        'bindings': bindings, 'predecessors': predecessors}
    mapping_descriptor = write('mapping.json', attachment)
    index = {'contract': 'waapi-skill.branch-evidence-index/v1',
        'base': archive_base, 'entries': entries,
        'mapping_attachments': [mapping_descriptor]}
    write('index.json', index)
    gaps = soundengine_gaps(inventory, bindings)
    write('gaps.json', gaps)
    write('acceptance.json', {'contract': 'waapi-skill.soundengine-acceptance-attribution/v1',
        'authority': TICKET, 'scope': '26 URIs / 124 version rows; seven accepted business families plus the reviewed getter-projection extension',
        'historical_native': {'records': ['https://github.com/zcyh147/waapi-skill/issues/88#issuecomment-5465036074',
            'https://github.com/zcyh147/waapi-skill/issues/59#issuecomment-5470272661'],
            'observed_candidate': 'ea36a60', 'versions': ['2022.1', '2025.1'], 'hosts': ['macOS', 'Windows'],
            'observed_scope': 'registration, post/seek/stop/release, spatial/listener and exact State/Switch observations',
            'raw_ledgers': 'unavailable in current archive; accepted historical record reuse only',
            'current_candidate_native_rerun': False, 'per_member_native_effect_credit': False},
        'code_scope': 'actual current focused ordinary aggregate code mechanism; no per-node outcome or Gateway observation receipt',
        'native_or_fresh_started': False, 'unresolved_members': len(gaps['members'])})
    return inventory, requirements, index

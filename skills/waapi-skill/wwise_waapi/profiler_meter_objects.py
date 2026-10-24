"""Closed object projections within one bounded, frozen Profiler meter frame."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .builders.query import query_return_scope_options
from .canonical import canonical_json_bytes, canonical_sha256
from .object_query_outputs import available_query_outputs, QUERY_FIELD_MODES, QUERY_FIELD_OUTPUT_GROUPS
from .object_query_related import (related_native_fields, _meaning,
    parse_related_request, related_sequence_specs, related_query_contract)
from .object_query_related_metadata import RelatedFieldBinder
from .object_query_related_runtime import RelatedQueryError, canonical_guid, IDENTITY

METERS_URI = 'ak.wwise.core.profiler.getMeters'
MAX_OUTPUTS = 32
MAX_CUSTOM_OUTPUTS = 16
MAX_METADATA_ROWS = 4096
MAX_METER_OBSERVATIONS = 64
MAX_METER_OBSERVATION_BYTES = MAX_METER_OBSERVATIONS * 1024 * 1024
MAX_CLARIFICATION_BYTES = 16 * 1024
# Fixed object-return choices are legal root selections even when a particular
# metered object has no applicable value. Preserve that absence as unavailable;
# a related-object projection is a separate selection, never a substitute.
METER_OUTPUT_NAMES = frozenset('''
notes volume-db output-bus parent owner work-unit included playable
explicitly-muted explicitly-soloed implicitly-muted implicitly-soloed child-count
plugin-name category file-path override-output class-id short-id
work-unit-is-default work-unit-is-dirty work-unit-type work-unit-is-loaded
object-size-bytes structure-size-bytes total-size-bytes media-size-bytes state-groups
state-properties custom-states supports-randomizer supports-states
converted-wem-file-path original-file-path original-relative-file-path
converted-file-path original-wav-file-path soundbank-file-path
music-transition-root music-playlist-root music-transition-object
playback-duration duration longest-duration-source audio-source-trim-values
largest-radius-attenuation audio-source-language switch-container-child-context
curve-points blend-tracks source-language-included original-state
switch-group-game-parameter has-empty-switch-state-assignment
extracted-events extracted-structures extracted-media soundbanks-referencing-event
active-source converted-anonymous-channel-count converted-bit-depth
converted-channel-configuration converted-channel-mask converted-codec
converted-data-size-bytes converted-duration converted-file-size-bytes
converted-height-channel-count converted-lfe-channel-count
converted-normal-channel-count converted-sample-count converted-sample-rate
converted-total-channel-count original-anonymous-channel-count original-bit-depth
original-channel-configuration original-channel-mask original-codec
original-data-size-bytes original-duration original-file-size-bytes
original-height-channel-count original-lfe-channel-count
original-normal-channel-count original-sample-count original-sample-rate
original-total-channel-count conversion-format converted-ambisonics-channel-count
converted-non-lfe-channel-count converted-sample-rate-setting
converted-trimmed-duration original-ambisonics-channel-count original-non-lfe-channel-count
'''.split())
METER_FIELD_MODES = (
    ('meter_object_fields','meter_object_include_field',QUERY_FIELD_MODES[0]),
    ('meter_object_override_source_values','meter_object_include_override_source_value',QUERY_FIELD_MODES[1]),
    ('meter_object_local_references','meter_object_include_local_reference',QUERY_FIELD_MODES[2]),
)
METER_RELATED_ARGUMENTS = [('meter_object_related_outputs','meter_object_include_related','--include-related')]
METER_RELATED_ARGUMENTS.extend((name.replace('meter_object_','meter_object_related_'),
    attribute.replace('include_','include_related_'),mode.option.replace('--include-','--include-related-'))
    for name,attribute,mode in METER_FIELD_MODES)


def add_meter_object_arguments(parser):
    parser.add_argument('--meter-object-include', action='append', default=[])
    for _,attribute,mode in METER_FIELD_MODES:
        parser.add_argument('--meter-object-'+mode.option[2:],dest=attribute,action='append',default=[])
    for _,attribute,option in METER_RELATED_ARGUMENTS:
        parser.add_argument('--meter-object-'+option[2:],dest=attribute,nargs='+',action='append',default=[])
    parser.add_argument('--meter-object-empty-selection', action='store_true')
    parser.add_argument('--meter-platform')
    parser.add_argument('--meter-language')


def meter_arguments_supplied(args):
    return bool(args.meter_object_include or any(getattr(args,attribute) for _,attribute,_ in METER_FIELD_MODES) or args.meter_object_empty_selection
        or any(getattr(args,attribute) for _,attribute,_ in METER_RELATED_ARGUMENTS)
        or args.meter_platform is not None or args.meter_language is not None)


def meter_named_outputs(version):
    return {name:binding for name,binding in available_query_outputs(version).items()
        if name in METER_OUTPUT_NAMES}


def meter_object_contract(version):
    related = related_query_contract(version,maximum_outputs=MAX_OUTPUTS,maximum_custom_outputs=MAX_CUSTOM_OUTPUTS)
    related_contract = {key:deepcopy(related[key]) for key in (
        'relations','list_members','custom_terminal_modes','reference_hops','randomizers','local_object_lists',
        'terminal_semantics','path_result','field_token_boundary','metadata_scope','native_limits')}
    related_contract['outputs'] = {name:detail for name,detail in related['outputs'].items() if detail['available']}
    related_contract['list_members']['provenance'] = (
        'Meter-root observations use getMeters at one frozen time. Closed sequences use separately bounded '
        'object.get helpers against current Authoring objects. Compact API association digests are retained '
        'with every meter result page; no native function-return equality or atomic snapshot is claimed.')
    related_contract['list_members']['limits']['deadline'] = 'existing per-call dispatch timeout and independent cumulative read budgets'
    return {'fields': {
        'meter_object_outputs': {'flag':'--meter-object-include', 'repeatable':True,
            'choices':[*IDENTITY, *meter_named_outputs(version)],
            'type':'array of closed business output names',
            'applicability':'Actual returned presence applies per Bus/AuxBus/device; absent fields remain unavailable, never inferred null'},
        **{name:{'flag':'--meter-object-'+mode.option[2:],'repeatable':True,
            'type':'array of user-facing field meanings',
            'meaning':'user-facing field meaning, bound to every actual class/object scope',
            'selected_kinds':list(mode.bindings),'output_groups':[QUERY_FIELD_OUTPUT_GROUPS[kind] for kind,_ in mode.bindings.values()]}
            for name,_,mode in METER_FIELD_MODES},
        **{name:{'flag':'--meter-object-'+option[2:],'repeatable':True,
            'type':'array of closed path/terminal token lists','values_per_occurrence':'closed path plus terminal'}
            for name,_,option in METER_RELATED_ARGUMENTS},
        'meter_object_empty_selection': {'flag':'--meter-object-empty-selection', 'repeatable':False,'type':'boolean'},
        'meter_platform': {'flag':'--meter-platform', 'repeatable':False,'type':'literal name or GUID',
            'omitted':'native current platform; no platform option sent'},
        'meter_language': {'flag':'--meter-language', 'repeatable':False,'type':'literal name or GUID',
            'omitted':'native default; no language option sent'}},
        'related_outputs':related_contract,
        'related_condition_vocabulary':{'source':['query-schema'],'path':'predicates / field_conditions; same closed business meanings, never native expressions'},
        'selection':{'omitted':'omit native return and preserve native defaults',
            'empty':'explicit return: []; conflicts with all output selections',
            'selected':'retain id/name/type/path plus requested outputs; helper fields are not silently published'},
        'scope':'platform/language select nested Authoring object values, not captured runtime meter values',
        'presence':'unavailable_fields preserves absence; explicit null is preserved',
        'limits':{'named_outputs':MAX_OUTPUTS, 'custom_outputs':MAX_CUSTOM_OUTPUTS,
            'metadata_preparation_rows':MAX_METADATA_ROWS,'clarification_bytes':MAX_CLARIFICATION_BYTES,
            'meter_observations':MAX_METER_OBSERVATIONS,'cumulative_meter_bytes':MAX_METER_OBSERVATION_BYTES},
        'mutation_authority':False}


def compile_meter_object_options(args, version, *, compile_condition=None):
    outputs = tuple(args.meter_object_include)
    meanings = []
    for _,attribute,mode in METER_FIELD_MODES:
        selected = tuple(_meaning(value) for value in getattr(args,attribute))
        if len({value.casefold() for value in selected}) != len(selected):
            raise ValueError('Meter field meanings must be unique within each declared mode')
        meanings.extend((mode,value) for value in selected)
    related = [parse_related_request(version,values,option) for _,attribute,option in METER_RELATED_ARGUMENTS
        for values in getattr(args,attribute)]
    if len({canonical_sha256(request) for request in related}) != len(related):
        raise ValueError('Meter related output declarations must be unique')
    for request in related:
        for spec in related_sequence_specs(version,request):
            for stage in spec['stages']:
                if stage['selection'] == 'matching' and compile_condition is not None:
                    compile_condition(stage)
            if 'condition' in spec.get('reducer',{}) and compile_condition is not None:
                compile_condition(spec['reducer']['condition'])
    if args.meter_object_empty_selection and (outputs or meanings or related):
        raise ValueError('Empty meter object selection cannot be combined with requested outputs')
    if len(outputs) + len(related) > MAX_OUTPUTS or len(meanings) + sum(request['option'] != '--include-related' for request in related) > MAX_CUSTOM_OUTPUTS:
        raise ValueError('Meter object projection exceeds its declared output budget')
    if len(set(outputs)) != len(outputs):
        raise ValueError('Meter object outputs and field meanings must be unique')
    available = meter_named_outputs(version)
    if any(value not in IDENTITY and value not in available for value in outputs):
        raise ValueError('Meter object output must be one disclosed business output')
    bindings = [('business', name, name) if name in IDENTITY else ('business', *available[name]) for name in outputs]
    scope = query_return_scope_options(platform=args.meter_platform, language=args.meter_language)
    return MeterObjectOptions(version, outputs, meanings, bindings, scope, empty=args.meter_object_empty_selection,
        related=related,compile_condition=compile_condition)


def meter_root_comparison_view(rows):
    """Copy actual roots for internal planning; normalize only their GUIDs."""
    objects = []
    for row in rows:
        obj = row.get('object')
        if not isinstance(obj, dict) or not canonical_guid(obj.get('id')) or not all(key in obj for key in IDENTITY):
            raise RelatedQueryError('Meter metadata requires complete actual object identities', code='METER_OBJECT_IDENTITY_INCOMPLETE')
        comparison = deepcopy(obj)
        comparison['id'] = comparison['id'].upper()
        objects.append(comparison)
    return objects


def meter_scope(rows):
    facts = []
    for row,obj in zip(rows,meter_root_comparison_view(rows),strict=True):
        identity = {key:deepcopy(obj[key]) for key in (*IDENTITY,'classId') if key in obj}
        facts.append({key:deepcopy(value) for key,value in row.items() if key != 'object'} | {'object':identity})
    return facts


def bounded_clarification(payload):
    if payload is not None and len(canonical_json_bytes(payload)) > MAX_CLARIFICATION_BYTES:
        raise RelatedQueryError('Meter field clarification exceeds its result budget; select a smaller field set',
            code='METER_OBJECT_CLARIFICATION_LIMIT', details={
                'unresolved_count':len(payload.get('unresolved',[])),
                'clarification_sha256':canonical_sha256(payload),'limit_bytes':MAX_CLARIFICATION_BYTES})
    return payload


@dataclass
class MeterObjectOptions:
    version: str
    outputs: tuple
    meanings: list
    bindings: list
    scope: dict
    empty: bool = False
    related: list = field(default_factory=list)
    compile_condition: object = None
    related_plan: object = None
    row_bindings: list = field(default_factory=list)
    observed_scope: list | None = None
    unavailable: dict = field(default_factory=dict)
    binder: object = None
    time: int | None = None
    meter_reads: list = field(default_factory=list)
    meter_bytes: int = 0

    def record_meter_read(self, result, options):
        self.meter_bytes += len(canonical_json_bytes(result))
        if len(self.meter_reads) >= MAX_METER_OBSERVATIONS or self.meter_bytes > MAX_METER_OBSERVATION_BYTES:
            raise RelatedQueryError('Meter preparation exceeded its cumulative observation budget; refine the projection',
                code='METER_OBJECT_OBSERVATION_LIMIT')
        self.meter_reads.append({'api':METERS_URI,'args':{'time':self.time},
            'options':deepcopy(options),'result_sha256':canonical_sha256(result)})

    def proof(self):
        metadata = self.binder.observations if self.binder is not None else []
        related = self.related_plan.proof() if self.related_plan is not None else None
        return {'root_api':METERS_URI,'time':self.time,'return_scope':dict(self.scope),
            'object_value_semantics':'Authoring configuration; not captured runtime mix values',
            'atomic_snapshot':False,'mutation_authority':False,
            'observed_frame_sha256':canonical_sha256(self.observed_scope),
            'meter_reads':{'count':len(self.meter_reads),'associations_sha256':canonical_sha256(self.meter_reads)},
            'metadata_reads':{'count':len(metadata),'associations_sha256':canonical_sha256(metadata)},
            **({'related':{'strategy':related['strategy'],
                'sequence_semantics':related.get('sequence_semantics'),
                'helper_apis':sorted({row['api'] for row in related['read_associations']}),
                'helper_read_count':len(related['read_associations']),
                'proof_sha256':canonical_sha256(related)}} if related is not None else {}),
            'limits':{'meter_observations':MAX_METER_OBSERVATIONS,
                'cumulative_meter_bytes':MAX_METER_OBSERVATION_BYTES,'preparation_rows':MAX_METADATA_ROWS}}

    def options(self):
        if self.empty:
            return {**self.scope,'return':[]}
        if self.related_plan is not None:
            return {**self.scope,'return':list(self.related_plan.render(self.related_plan.root,root=True))}
        if not self.outputs and not self.meanings:
            return dict(self.scope)
        fields = related_native_fields([*self.bindings, *(binding for row in self.row_bindings for binding in row)], IDENTITY)
        if self.observed_scope is not None:
            fields = related_native_fields([('scope', value, '') for value in (*fields,'classId')], ())
        return {**self.scope, 'return':list(fields)}

    def prepare(self, *, read_meter, read_metadata, time):
        self.time = time
        if not self.meanings and not self.related:
            return None
        native_read_meter = read_meter
        def read_meter(options):
            result = native_read_meter(options)
            self.record_meter_read(result,options)
            return result
        result = read_meter({**self.scope, 'return':[*IDENTITY,'classId']})
        rows = result.get('meters')
        if not isinstance(rows,list) or len(rows) > MAX_METADATA_ROWS:
            raise RelatedQueryError('Meter metadata preparation exceeds its bounded row scope', code='METER_OBJECT_SCOPE_LIMIT')
        self.observed_scope = meter_scope(rows)
        binder = self.binder = RelatedFieldBinder(read_metadata, RelatedQueryError, version=self.version)
        unresolved = []
        ambiguous_bytes = 0
        matched = set()
        for index,row in enumerate(rows):
            obj = row['object']
            bindings = []
            for mode,meaning in self.meanings:
                selected = binder.bind(meaning,obj,obj.get('classId'),'',index,mode.option.replace('--include-','--include-related-'),namespaced_property=True)
                candidate = selected['candidate']
                if candidate is None:
                    selection = {'row_index':index,'requested_option':mode.option,'meaning':meaning,**selected}
                    # A large ambiguous candidate list must not be multiplied
                    # across repeated meter rows before the result ceiling is
                    # checked. Definite no-match scopes can still become
                    # unavailable when another actual scope binds below.
                    if selected['candidate_names'] or not selected['complete']:
                        ambiguous_bytes += len(canonical_json_bytes(selection))
                        if ambiguous_bytes > MAX_CLARIFICATION_BYTES:
                            raise RelatedQueryError('Meter field ambiguity exceeds its clarification budget; refine the field set',
                                code='METER_OBJECT_CLARIFICATION_LIMIT', details={
                                    'unresolved_count_at_least':len(unresolved)+1,'limit_bytes':MAX_CLARIFICATION_BYTES})
                    unresolved.append(selection)
                    continue
                if candidate['kind'] not in mode.bindings:
                    raise RelatedQueryError(f'{mode.option} does not admit this actual field kind',code='METER_OBJECT_FIELD_KIND')
                kind,prefix = mode.bindings[candidate['kind']]
                bindings.append((kind,prefix+candidate['name'],candidate['name']))
                matched.add((mode.option,meaning))
            self.row_bindings.append(bindings)
        pending = []
        for selection in unresolved:
            if (selection['requested_option'],selection['meaning']) in matched and selection['complete'] and not selection['candidate_names']:
                self.unavailable.setdefault(selection['row_index'],[]).append({
                    'meaning':selection['meaning'],'requested_option':selection['requested_option'],
                    'reason':'no matching field in the complete actual metadata scope'})
            else:
                pending.append(selection)
        if pending:
            return bounded_clarification({'metadata_authority':'live-waapi','unresolved':pending,
                'repair':'Refine each meaning in its actual meter object scope; no other class token is substituted'})
        if self.related:
            from .object_query_related_lists import RelatedListPlan
            def observe_root(fields):
                observed = read_meter({**self.scope,'return':list(fields)})
                rows = observed['meters']
                self.validate_scope(rows)
                return meter_root_comparison_view(rows),self.scope
            self.related_plan = RelatedListPlan(version=self.version,requests=self.related,
                bindings=[*self.bindings,*(binding for row in self.row_bindings for binding in row)],
                build_preview=None,read=read_metadata,maximum_rows=MAX_METADATA_ROWS,
                maximum_read_bytes=1024*1024,compile_condition=self.compile_condition,
                binder=binder,root_observer=observe_root)
            return bounded_clarification(self.related_plan.prepare())
        return None

    def validate_scope(self, rows):
        if self.observed_scope is not None and canonical_json_bytes(meter_scope(rows)) != canonical_json_bytes(self.observed_scope):
            raise RelatedQueryError('Meter frame or actual metadata scope changed during preparation', code='METER_OBJECT_SCOPE_CHANGED')

    def project(self, result):
        if not self.outputs and not self.meanings and not self.related:
            return result
        rows = result['meters']
        self.record_meter_read(result,self.options())
        self.validate_scope(rows)
        related = self.related_plan.project(meter_root_comparison_view(rows)) if self.related_plan is not None else None
        projected = []
        for index,row in enumerate(rows):
            obj = row['object']
            item = {key:deepcopy(obj[key]) for key in IDENTITY if key in obj}
            bindings = [*self.bindings, *(self.row_bindings[index] if self.row_bindings else [])]
            for kind,native,output in bindings:
                group = QUERY_FIELD_OUTPUT_GROUPS.get(kind)
                if native not in obj:
                    item.setdefault('unavailable_fields',[]).append(f'{group}.{output}' if group else output)
                else:
                    target = item.setdefault(group,{}) if group else item
                    target[output] = deepcopy(obj[native])
            if index in self.unavailable:
                item['unavailable_field_requests'] = deepcopy(self.unavailable[index])
            if related is not None:
                item.update(related[index])
            projected.append({**row,'object':item})
        return {**result,'meters':projected,'meter_object_projection':self.proof()}

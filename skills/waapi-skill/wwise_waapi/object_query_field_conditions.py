"""Closed scalar/reference conditions bound to live metadata, evaluated by WAQL.

This module owns no Python predicate evaluator. Binding and ordered occurrence
association are Gateway work; only native WHERE decides which identities match.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass

from .builders.query import (QueryPredicate, _where_clause, build_object_get_query,
    MAX_STRUCTURED_SOURCE_ITEMS, MAX_ADVANCED_RETURN_EXPRESSIONS, MAX_STRUCTURED_LITERAL_LENGTH)
from .canonical import canonical_sha256, canonical_json_bytes
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS
from .metadata_discovery import metadata_typed_value_type, MAX_METADATA_DISCOVERY_QUERY_CHARS
from .object_query_related_runtime import IDENTITY, OBJECT_GET, canonical_guid, RelatedQueryError

MODES = {'ordinary': ('property', '@'), 'override-source-value': ('property', '@@'),
    'reference': ('reference', '@@'), 'local-reference': ('reference', '@')}


def reference_constant(value):
    from .operation_object import normalize_object_identity, DEFAULT_MAX_REQUEST_BYTES
    if len(value.encode('utf-8')) > DEFAULT_MAX_REQUEST_BYTES:
        raise ValueError('Reference selector exceeds the owning identity request budget')
    if canonical_guid(value): return {'kind':'id','value':value.upper()}
    def unique(pairs):
        result = {}
        for key,item in pairs:
            if key in result: raise ValueError('Reference selectors reject duplicate JSON keys')
            result[key] = item
        return result
    try:
        selector = json.loads(value,object_pairs_hook=unique)
        if selector is None: return None
        if len(canonical_json_bytes(selector)) > DEFAULT_MAX_REQUEST_BYTES:
            raise ValueError('Reference selector exceeds the owning identity request budget')
        return normalize_object_identity(selector,path='field_condition.value').as_dict()
    except (TypeError, ValueError) as exc:
        raise ValueError('Reference comparisons require a canonical GUID, a closed identity selector or null: '+str(exc)) from exc


@dataclass(frozen=True)
class BoundCondition:
    # Only a freshly metadata-bound token reaches this record. Neither the
    # renderer nor its grammar is a public expression input.
    field: str
    reference: bool
    operator: str
    value: object

    def clause(self):
        from .builders.query import _literal
        if not self.reference:
            return _where_clause(QueryPredicate(self.field,self.operator,self.value))
        if self.value is None:
            present = self.field+' != null'
            return 'where '+('!('+present+')' if self.operator=='=' else present)
        return 'where '+self.field+'.id '+self.operator+' '+_literal(self.value)


def observed_field(row, field):
    return {'present':field in row, **({'value':row[field]} if field in row else {})}


COMPARISONS = {'is':'=', 'is-not':'!=', 'below':'<', 'at-most':'<=', 'above':'>', 'at-least':'>=', 'matches-text':':'}


def parse_field_condition(values):
    if len(values) != 4:
        raise ValueError('field conditions require MODE MEANING COMPARISON VALUE')
    mode, meaning, comparison, value = values
    if mode not in MODES:
        raise ValueError('field mode must be one of: '+', '.join(MODES))
    if (not isinstance(meaning, str) or not meaning or meaning != meaning.strip()
            or len(meaning) > MAX_METADATA_DISCOVERY_QUERY_CHARS
            or any(ord(c) < 32 or ord(c) == 127 or c in "@.\\;\"'()" for c in meaning)):
        raise ValueError('field conditions require a bounded user-facing meaning, not native accessor grammar')
    if comparison not in COMPARISONS:
        raise ValueError('field comparison must be one of: ' + ', '.join(COMPARISONS))
    if not isinstance(value,str): raise ValueError('Field comparison value must be text')
    if MODES[mode][0]=='reference':
        if comparison not in {'is','is-not'}: raise ValueError('Reference conditions admit is/is-not identity or null comparisons')
        reference_constant(value)  # Owning identity limits, not scalar literal limits.
    elif len(value.encode('utf-8')) > MAX_STRUCTURED_LITERAL_LENGTH:
        raise ValueError('field comparison value exceeds the existing literal budget')
    return {'field_condition':{'mode':mode, 'meaning':meaning, 'comparison':comparison, 'value':value}}


def condition_value(metadata, condition):
    kind = metadata_typed_value_type(metadata.get('type'))
    value = condition['value']
    if kind == 'integer':
        if re.fullmatch(r'0|-?[1-9][0-9]*', value) is None:
            raise ValueError('integer field comparisons require a canonical integer')
        value = int(value)
    elif kind == 'number':
        try: value = float(value)
        except ValueError as exc: raise ValueError('numeric field comparison requires a number') from exc
        if not math.isfinite(value): raise ValueError('numeric field comparison must be finite')
    elif kind == 'boolean':
        if value not in {'true','false'}: raise ValueError('Boolean field comparison requires true or false')
        value = value == 'true'
    elif kind != 'string':
        raise RelatedQueryError('The actual field has insufficient scalar type authority; refine its meaning',
            code='QUERY_FIELD_CONDITION_UNAVAILABLE', details={'condition':condition, 'metadata_type':metadata.get('type')})
    if condition['comparison']=='matches-text' and kind!='string':
        raise ValueError('text matching requires a live string property')
    if condition['comparison'] not in {'is','is-not','matches-text'} and kind not in {'integer','number'}:
        raise ValueError('ordered field comparisons require a live numeric property')
    # A query threshold is not a mutation assignment. Do not impose assignment
    # range/enum-choice constraints on otherwise well-typed comparison constants.
    return value


class ScalarConditionPlan:
    def __init__(self, *, version, read, binder, validate_rows, platform=None, language=None, charge_selection=None):
        self.version, self.read, self.binder = version, read, binder
        self.validate_rows, self.platform, self.language = validate_rows, platform, language
        self.observations, self.value_reads = [], {}
        self.charge_selection = charge_selection
        self.target_cache, self.target_observations = {}, []

    def target_value(self, condition):
        selector = reference_constant(condition['value'])
        if selector is None: return None
        if selector['kind']=='id' and canonical_guid(selector['value']):
            # Literal comparison values have no target existence/name authority.
            return selector['value'].upper()
        from .operation_registry import _resolve_identity, OperationContractError
        key = canonical_sha256(selector)
        if key not in self.target_cache:
            try:
                target = _resolve_identity(selector,role='query comparison',read=self.read,identity_cache={})
            except OperationContractError as exc:
                raise RelatedQueryError(str(exc),code='QUERY_FIELD_CONDITION_TARGET',details=exc.details) from exc
            if not canonical_guid(target.object):
                raise RelatedQueryError('Named reference comparison must resolve one canonical GUID',code='QUERY_FIELD_CONDITION_TARGET')
            self.target_cache[key] = str(target.object).upper()
            self.target_observations.append({'selector':selector,'identity':copy.deepcopy(dict(target.row))})
            self.observations.append({'comparison_target':self.target_observations[-1]})
        return self.target_cache[key]

    def validate_targets(self):
        # Canonical GUID literals never enter this list. Only selectors whose
        # meaning required a live identity resolution are revalidated.
        from .operation_registry import _resolve_identity, OperationContractError
        for observation in self.target_observations:
            try:
                current = _resolve_identity(observation['selector'],role='query comparison',read=self.read,identity_cache={})
            except OperationContractError as exc:
                raise RelatedQueryError(str(exc),code='QUERY_FIELD_CONDITION_TARGET',details=exc.details) from exc
            if canonical_json_bytes(dict(current.row)) != canonical_json_bytes(observation['identity']):
                raise RelatedQueryError('Named comparison selector changed its observed identity',code='QUERY_FIELD_CONDITION_TARGET')

    def actual_rows(self, rows):
        ids = list(dict.fromkeys(row['id'].upper() for row in rows))
        found = {}
        for start in range(0,len(ids),MAX_STRUCTURED_SOURCE_ITEMS):
            chunk = ids[start:start+MAX_STRUCTURED_SOURCE_ITEMS]
            preview = build_object_get_query(object_ids=chunk, return_fields=(*IDENTITY,'classId'),
                version=self.version, platform=self.platform, language=self.language)
            result = self.read(OBJECT_GET, preview.envelope.args, preview.envelope.options)
            values = self.validate_rows(result,len(chunk))
            batch = {}
            for row in values:
                identity = row['id'].upper()
                if identity not in chunk or identity in batch:
                    raise RelatedQueryError('Field-condition scope read returned extra or duplicate identities',code='QUERY_FIELD_CONDITION_BATCH')
                batch[identity] = row
            if set(batch) != set(chunk):
                raise RelatedQueryError('Field-condition scope read omitted identities',code='QUERY_FIELD_CONDITION_BATCH')
            found.update(batch)
            self.observations.append({'scope_result_sha256':canonical_sha256(result),'ids':chunk})
        for row in rows:
            actual = found[row['id'].upper()]
            for key in (*IDENTITY,'classId'):
                if key in row and canonical_json_bytes(row[key]) != canonical_json_bytes(actual.get(key)):
                    raise RelatedQueryError('A field-condition endpoint identity/class changed during binding')
        return [found[row['id'].upper()] for row in rows]

    def bind(self, rows, condition, *, option="matching-field"):
        condition = condition['field_condition']
        groups = {}
        for index,row in enumerate(rows):
            selection = self.binder.bind(condition['meaning'],row,row.get('classId'),'',index,option)
            candidate = selection['candidate']
            if candidate is None or not selection['complete']:
                raise RelatedQueryError('The field condition cannot be decided in every actual metadata scope; refine the meaning or source',
                    code='QUERY_FIELD_CONDITION_UNAVAILABLE', details={'condition':condition,'requested_option':option,'unresolved_scope':selection})
            kind,prefix = MODES[condition['mode']]
            if candidate.get('kind') != kind:
                raise RelatedQueryError('The field condition mode requires a live '+kind,code='QUERY_FIELD_CONDITION_KIND')
            value = self.target_value(condition) if kind=='reference' else condition_value(candidate.get('metadata',{}),condition)
            predicate = BoundCondition(prefix+candidate['name'],kind=='reference',COMPARISONS[condition['comparison']],value)
            clause = predicate.clause()
            key = canonical_sha256({'scope':selection['scope'],'clause':clause})
            group = groups.setdefault(key,{'scope':selection['scope'],'predicate':predicate,'clause':clause,'ids':[],
                'value_type':'reference' if kind=='reference' else metadata_typed_value_type(candidate.get('metadata',{}).get('type')), 'condition':condition})
            identity = row['id'].upper()
            if identity not in group['ids']: group['ids'].append(identity)
        return list(groups.values())

    def observe_values(self, group, actual):
        """Prove read applicability without evaluating the predicate in Python."""
        expected = {row['id'].upper():row for row in actual}
        values = {}
        for start in range(0,len(group['ids']),MAX_STRUCTURED_SOURCE_ITEMS):
            chunk = group['ids'][start:start+MAX_STRUCTURED_SOURCE_ITEMS]
            field = group['predicate'].field
            preview = build_object_get_query(object_ids=chunk,return_fields=(*IDENTITY,'classId',field),
                version=self.version,platform=self.platform,language=self.language)
            result = self.read(OBJECT_GET,preview.envelope.args,preview.envelope.options)
            rows = self.validate_rows(result,len(chunk))
            batch = {}
            for row in rows:
                identity = row['id'].upper()
                if identity not in chunk or identity in batch:
                    raise RelatedQueryError('Field-value scope returned extra/duplicate identities',code='QUERY_FIELD_CONDITION_BATCH')
                if identity not in expected or any(canonical_json_bytes(row.get(key))!=canonical_json_bytes(expected[identity].get(key)) for key in (*IDENTITY,'classId')):
                    raise RelatedQueryError('Field-value identity or actual class changed during binding')
                value,kind = row.get(field),group['value_type']
                valid = (type(value) is bool if kind=='boolean' else type(value) is int if kind=='integer'
                    else (type(value) is int or type(value) is float and math.isfinite(value)) if kind=='number' else isinstance(value,str))
                if kind=='reference':
                    valid = field not in row or value is None or isinstance(value,dict) and canonical_guid(value.get('id'))
                if (kind!='reference' and (field not in row or value is None)) or not valid:
                    raise RelatedQueryError('A predicate value is unavailable or incompatible with its bound field kind/type; it is not a nonmatch',
                        code='QUERY_FIELD_CONDITION_UNAVAILABLE',details={'condition':group['condition'],'scope':group['scope'],
                            'object':identity,'field':field,'presence':'absent' if field not in row else 'null' if value is None else 'incompatible_type'})
                batch[identity] = row
            if set(batch)!=set(chunk):
                raise RelatedQueryError('Field-value scope omitted identities',code='QUERY_FIELD_CONDITION_BATCH')
            key=canonical_sha256({'args':preview.envelope.args,'options':preview.envelope.options})
            digest=canonical_sha256(result)
            if key in self.value_reads and self.value_reads[key]!=digest:
                raise RelatedQueryError('Observed predicate values changed during the read; restart the original query')
            self.value_reads[key]=digest
            self.observations.append({'value_scope':key,'result_sha256':digest})
            values.update(batch)
        return values

    def filter(self, rows, condition):
        if not rows: return []  # Empty data conveys no metadata authority.
        actual = self.actual_rows(rows)
        groups = self.bind(actual,condition)
        selected = set()
        for group in groups:
            observed = self.observe_values(group,actual)
            for start in range(0,len(group['ids']),MAX_STRUCTURED_SOURCE_ITEMS):
                chunk = group['ids'][start:start+MAX_STRUCTURED_SOURCE_ITEMS]
                from .builders.query import build_advanced_object_get_query, ADVANCED_QUERY_CONTRACT
                source = build_object_get_query(object_ids=chunk,return_fields=IDENTITY,version=self.version)
                preview = build_advanced_object_get_query({'contract':ADVANCED_QUERY_CONTRACT,
                    'waql':source.envelope.args['waql']+' '+group['clause'],
                    'return':[*IDENTITY,'classId',group['predicate'].field],'max_results':len(chunk)},
                    version=self.version,platform=self.platform,language=self.language)
                result = self.read(OBJECT_GET,preview.envelope.args,preview.envelope.options)
                values = self.validate_rows(result,len(chunk))
                ids = [row['id'].upper() for row in values]
                if len(set(ids)) != len(ids) or set(ids)-set(chunk):
                    raise RelatedQueryError('Field-condition read returned extra or duplicate selected identities',code='QUERY_FIELD_CONDITION_BATCH')
                bound = {row['id'].upper():row for row in actual}
                if any(any(canonical_json_bytes(row.get(key))!=canonical_json_bytes(bound[row['id'].upper()].get(key))
                           for key in (*IDENTITY,'classId')) for row in values):
                    raise RelatedQueryError('Selected field-condition identity or actual class changed during the native read')
                field = group['predicate'].field
                if any(canonical_json_bytes(observed_field(row,field)) != canonical_json_bytes(observed_field(observed[row['id'].upper()],field))
                       for row in values):
                    raise RelatedQueryError('Selected predicate value differs from its checked source observation')
                if self.charge_selection is not None:
                    self.charge_selection(values)
                selected.update(ids)
                self.observations.append({'condition':condition,'scope':group['scope'], 'api':OBJECT_GET,
                    'args':preview.envelope.args,'options':preview.envelope.options,'result_sha256':canonical_sha256(result)})
        self.validate_targets()
        return [row for row in rows if row['id'].upper() in selected]


class RootScalarConditionPlan:
    """Complete source authority, then native conditions before final root take."""
    def __init__(self, *, version, body, conditions, read, maximum_read_bytes,
                 final_limit, platform=None, language=None):
        from .object_query_related_metadata import RelatedFieldBinder
        self.version, self.body, self.conditions = version, body, conditions
        self.raw_read, self.maximum_read_bytes = read, maximum_read_bytes
        self.final_limit, self.platform, self.language = final_limit, platform, language
        self.total_bytes = 0
        self.descriptors = []
        self.binder = RelatedFieldBinder(self.read,RelatedQueryError)
        self.scalar = ScalarConditionPlan(version=version,read=self.read,binder=self.binder,
            validate_rows=self.validate_rows,platform=platform,language=language)
        self.clauses, self.predicate_fields, self.bound_groups = [], [], []

    def read(self, api, args, options):
        result = self.raw_read(api,args,options)
        self.total_bytes += len(canonical_json_bytes(result))
        if self.total_bytes > MAX_ADVANCED_RETURN_EXPRESSIONS*self.maximum_read_bytes:
            raise RelatedQueryError('Root and related field-condition reads exceeded the shared byte budget',code='QUERY_FIELD_CONDITION_LIMIT')
        self.descriptors.append({'api':api,'args':copy.deepcopy(args),'options':copy.deepcopy(options),'result_sha256':canonical_sha256(result)})
        return result

    @staticmethod
    def validate_rows(result, maximum):
        rows = result.get('return')
        if not isinstance(rows,list) or len(rows)>maximum or any(not isinstance(row,dict) or not canonical_guid(row.get('id')) for row in rows):
            raise RelatedQueryError('Field-condition source returned malformed or oversized identities',code='QUERY_FIELD_CONDITION_BATCH')
        return copy.deepcopy(rows)

    def preview(self, fields, *, body=None, limit=None, view=None):
        from .builders.query import build_advanced_object_get_query, ADVANCED_QUERY_CONTRACT
        return build_advanced_object_get_query({'contract':ADVANCED_QUERY_CONTRACT,
            'waql':body if body is not None else ' '.join([self.body,*self.clauses]),
            'return':list(dict.fromkeys((*fields,'classId',*(self.predicate_fields if body is None else ())))),'max_results':limit or self.final_limit},
            version=self.version,platform=(view or {}).get('platform',self.platform),language=(view or {}).get('language',self.language))

    def scan(self):
        from .builders.query import MAX_QUERY_TAKE
        rows = []
        while True:
            count = min(MAX_QUERY_TAKE,MULTI_IDENTITY_READ_MAX_IDS-len(rows)+1)
            body = self.body + (f' skip {len(rows)}' if rows else '')
            preview = self.preview(IDENTITY,body=body,limit=count)
            chunk = self.validate_rows(self.read(OBJECT_GET,preview.envelope.args,preview.envelope.options),count)
            rows.extend(chunk)
            if len(rows)>MULTI_IDENTITY_READ_MAX_IDS:
                raise RelatedQueryError('Complete root field metadata scope exceeds the existing identity budget; refine the business source',code='QUERY_FIELD_CONDITION_LIMIT')
            if len(chunk)<count: return rows

    def prepare(self):
        from .builders.query import _predicate_clause
        self.source_rows = self.scan()
        for condition in self.conditions:
            groups = self.scalar.bind(self.source_rows,condition,option="--where-field")
            if not groups: continue
            self.bound_groups.extend(groups)
            for group in groups: self.scalar.observe_values(group,self.source_rows)
            self.predicate_fields.extend(group['predicate'].field for group in groups if group['predicate'].field not in self.predicate_fields)
            if len({group['clause'] for group in groups})==1:
                # Every source object has independently bound authority. An
                # identical predicate needs no redundant class/GUID guards.
                clause = groups[0]['clause']
            else:
                parts = []
                for group in groups:
                    scope = group['scope']
                    guard = QueryPredicate('classId','=',scope['classId']) if 'classId' in scope else QueryPredicate('id','=',scope['object'])
                    parts.append('('+_predicate_clause(guard)+' and '+group['clause'][len('where '):]+')')
                clause = 'where ('+' or '.join(parts)+')'
            if clause in self.clauses:
                raise ValueError('Field meanings resolved duplicate scalar conditions')
            self.clauses.append(clause)
        # Validate the complete owned expression before any final projection.
        self.preview(IDENTITY)

    def validate(self, rows):
        expected = {row['id'].upper():row for row in self.source_rows}
        for row in rows:
            reference = expected.get(row['id'].upper())
            if reference is None or any(canonical_json_bytes(row.get(key))!=canonical_json_bytes(reference.get(key)) for key in (*IDENTITY,'classId')):
                raise RelatedQueryError('The final field-condition result left its observed source/metadata scope')
        after = self.scan()
        if canonical_json_bytes(after)!=canonical_json_bytes(self.source_rows):
            raise RelatedQueryError('Root predicate source membership or actual class changed during the read')
        self.scalar.validate_targets()
        for group in self.bound_groups:
            values = self.scalar.observe_values(group,after)
            for row in rows:
                if row['id'].upper() in values and canonical_json_bytes(observed_field(row,group['predicate'].field))!=canonical_json_bytes(observed_field(values[row['id'].upper()],group['predicate'].field)):
                    raise RelatedQueryError('The final predicate value differs from its actual source observation')

    def proof(self):
        return {'conditions':self.conditions,'source_complete':True,'source_rows':len(self.source_rows),
            'source_scope_sha256':canonical_sha256(self.source_rows),'scopes':self.binder.selections,
            'metadata_observations_sha256':canonical_sha256(self.binder.observations),
            'scalar_condition_observations_sha256':canonical_sha256(self.scalar.observations),
            'native_predicates':self.clauses,'read_associations':self.descriptors,
            'final_root_limit_applied_after_predicates':True,'mutation_authority':False,
            'empty_source_establishes_field_authority':False,
            'limits':{'complete_source_identities':MULTI_IDENTITY_READ_MAX_IDS,'cumulative_read_bytes':MAX_ADVANCED_RETURN_EXPRESSIONS*self.maximum_read_bytes}}


def field_condition_contract(version, *, maximum_conditions):
    from pathlib import Path
    from .object_query_outputs import _definition_graph
    source = json.loads((Path(__file__).resolve().parents[1]/'references/semantic'/version/'query-field-condition-sources.json').read_text())
    if source['version']!=version or source['wwise_build']!=_definition_graph(version).wwise_build:
        raise ValueError('Scalar query condition sources do not match selected definitions')
    reference_source = json.loads((Path(__file__).resolve().parents[1]/'references/semantic'/version/'query-reference-condition-sources.json').read_text())
    if reference_source['version']!=version or reference_source['wwise_build']!=_definition_graph(version).wwise_build:
        raise ValueError('Reference condition source does not match selected definitions')
    from .operation_object import DEFAULT_MAX_REQUEST_BYTES, DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH, DEFAULT_MAX_NAME_LENGTH, DEFAULT_MAX_TYPE_LENGTH
    return {'root_option':'--where-field MODE MEANING COMPARISON VALUE',
        'related_selection':'matching-field MODE MEANING COMPARISON VALUE',
        'related_reducers':['any-match-field MODE MEANING COMPARISON VALUE','all-match-field MODE MEANING COMPARISON VALUE'],
        'modes':list(MODES),'value_source':{'ordinary':'direct object-local scalar property',
            'override-source-value':'query authoring override-resolved scalar property; value, not override ancestor identity or runtime RTPC/mix',
            'reference':'override-resolved reference identity, explicitly disambiguated from built-in accessors',
            'local-reference':'directly stored reference identity, potentially hidden by an override'},
        'reference_constants':{'comparisons':['is','is-not'],'canonical_guid_requires_existence':False,
            'target':'bare canonical GUID or existing closed id/path/exact-type-name/direct-child/scoped-name selector; canonical GUIDs are literal IDs, other selectors resolve bounded unique GUIDs',
            'null':'native reference setness/complement; RETURN absence stays absent and does not establish unset versus inapplicable; identity inequality is native, not Python complement',
            'selector_limits':{'request_bytes':DEFAULT_MAX_REQUEST_BYTES,'scoped_parent_characters':DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH,
                'name_characters':DEFAULT_MAX_NAME_LENGTH,'type_characters':DEFAULT_MAX_TYPE_LENGTH},
            'assignment_constraints':False},
        'comparisons':list(COMPARISONS),'types':'properties use exact live scalar metadata; references require discovered reference kind and canonical identity/null observations; ordered comparisons numeric only, matches-text native word-prefix/wildcard string matching; comparison constants are not mutation assignments or enum choices',
        'field_token_boundary':'metadata-selected ASCII alphanumeric/underscore tokens; namespaced custom-token WHERE spelling is not yet established by the retained query evidence and is not classified as native absence',
        'authority':'complete actual source/member class or GUID live metadata; unknown is not false or zero',
        'root_limit_order':'native field predicates before final root take',
        'root_unknown':'bounded refinement/failure; never return unfiltered roots as matches',
        'related_unknown':'preserve roots and independent views; scoped unavailable_predicates without definitive items/value',
        'scope':'ordinary, broad and advanced roots and nested/combined object lists; no exact-ID-only requirement',
        'limits':{'root_condition_declarations':maximum_conditions,'complete_source_identities':MULTI_IDENTITY_READ_MAX_IDS,
            'literal_utf8_bytes':MAX_STRUCTURED_LITERAL_LENGTH,'literal_scope':'scalar property constants only; reference selector limits are separately disclosed',
            'other':'existing member/path/native expression, aggregate bytes, deadline and sealed-page bounds; no hidden prefix'},
        'source':source,'reference_source':reference_source,'source_boundary':'pinned query WHERE/SELECT evidence, separate from RETURN; no runtime SDK dependency',
        'followup':'reference-chain condition operands, non-object records and functions remain unavailable; native unset/collision edge observations remain distinct from documented syntax; this does not establish native absence'}

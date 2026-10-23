"""Owned related member records, with explicit native/grouped read provenance.

Frames describe one list boundary, not one root or class. Each occurrence stays
attached to its original owner. Older lanes associate separately read rows only
by canonical GUID; they never zip unrelated arrays or claim an atomic snapshot.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from .canonical import canonical_json_bytes, canonical_sha256
from .builders.query import (build_object_get_query, build_advanced_object_get_query, ADVANCED_QUERY_CONTRACT, MAX_QUERY_TAKE, MAX_STRUCTURED_SOURCE_ITEMS,
    MAX_ADVANCED_RETURN_EXPRESSIONS)
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS
from .object_query_outputs import QUERY_FIELD_OUTPUT_GROUPS, available_query_outputs
from .object_query_related import (RELATED_QUERY_RELATIONS, RELATED_QUERY_LIST_RELATIONS,
    RELATED_FIELD_MODES, RelatedQueryOutput, related_native_fields, parse_related_request, related_sequence_source)
from .object_query_related_runtime import RelatedQueryError, canonical_guid, IDENTITY, OBJECT_GET
from .object_query_related_metadata import RelatedFieldBinder

# Gateway-owned aggregate limits, independent of native source/projection caps.
MAX_RELATED_MEMBER_OCCURRENCES = MULTI_IDENTITY_READ_MAX_IDS
MAX_RELATED_MEMBER_OBSERVATIONS = MAX_ADVANCED_RETURN_EXPRESSIONS * MULTI_IDENTITY_READ_MAX_IDS


def context_at(item, path):
    """Only create Gateway-owned contexts; native terminal values stay opaque."""
    for slot, name in path:
        nested = item.setdefault('related', {})
        item = nested.setdefault(name, {}) if slot == 'relation' else nested.setdefault(slot, {}).setdefault(name, {})
    return item


@dataclass
class Frame:
    number: int
    fields: list = field(default_factory=lambda: [*IDENTITY, 'classId'])
    scope: list = field(default_factory=lambda: [*IDENTITY, 'classId'])
    lists: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)
    origins: dict = field(default_factory=dict)


@dataclass
class ListEdge:
    native: str
    path: tuple
    child: Frame
    states: dict = field(default_factory=dict)
    sequence: dict | None = None


class RelatedListPlan:
    def __init__(self, *, version, requests, bindings, build_preview, read, maximum_rows, maximum_read_bytes, compile_condition):
        self.version, self.requests, self.bindings = version, requests, tuple(binding for binding in bindings if not binding[0].startswith('related'))
        self.build_preview, self.read = build_preview, read
        self.compile_condition = compile_condition
        self.maximum_rows, self.maximum_read_bytes = maximum_rows, maximum_read_bytes
        self.composed = version not in {'2021.1', '2022.1'}
        self.strategy = 'native-composed-members' if self.composed else 'gateway-guid-grouped-reads'
        self.root = Frame(0, fields=list(dict.fromkeys((*IDENTITY, 'classId', *(native for kind, native, _ in self.bindings if kind != 'derived')))), scope=[*IDENTITY, 'classId'])
        self.frames = [self.root]
        self.snapshot, self.descriptors = {}, []
        self.observed_extra_fields = {}
        self.return_scope = {}
        self.total_bytes = self.total_occurrences = 0
        self.unique_ids = set()
        self.binder = RelatedFieldBinder(self.measured_read, RelatedQueryError)
        self.aliases = set()
        self.sequence_origins = {}
        self.has_sequences = any(kind == 'sequence' for request in requests for kind,_ in request['hops'])

    def charge_sequence_members(self, rows):
        if not self.has_sequences: return
        self.unique_ids.update(row['id'].upper() for row in rows)
        self.total_occurrences += len(rows)
        if len(self.unique_ids) > MULTI_IDENTITY_READ_MAX_IDS or self.total_occurrences > MAX_RELATED_MEMBER_OBSERVATIONS:
            raise RelatedQueryError('Sequence helper reads exceeded their owned identity/observation budget',code='RELATED_QUERY_MEMBER_LIMIT')

    def measured_read(self, uri, args, options):
        result = self.read(uri, args, options)
        self.total_bytes += len(canonical_json_bytes(result))
        if self.total_bytes > MAX_ADVANCED_RETURN_EXPRESSIONS * self.maximum_read_bytes:
            raise RelatedQueryError('Related reads exceeded their cumulative byte budget; refine the query', code='RELATED_QUERY_OBSERVATION_LIMIT')
        self.descriptors.append({'api': uri, 'args': copy.deepcopy(args), 'options': copy.deepcopy(options), 'result_sha256': canonical_sha256(result)})
        return result

    def render(self, frame, *, root=False):
        result = list(frame.fields)
        for edge in frame.lists.values():
            if edge.sequence:
                continue  # Selection is owned query SELECT, never guessed return syntax.
            if self.composed:
                expression = f'{edge.native}.{{{",".join(self.render(edge.child))}}}'
                if root:
                    expression += f' as related{edge.child.number - 1}'
            else:
                # Older lanes establish membership with query SELECT, not an
                # unsupported return accessor. Prefix owner references already
                # belong to frame.fields when the path requires them.
                continue
            result.append(expression)
        return related_native_fields([('related_scope', value, {}) for value in result], ())

    def edge_key(self, frame, edge):
        if edge.sequence:
            return f'projection{edge.child.number}'
        if not self.composed:
            return edge.native
        if frame is self.root:
            return f'related{edge.child.number - 1}'
        return f'{edge.native}.{{{",".join(self.render(edge.child))}}}'

    def validate_rows(self, result, maximum):
        rows = result.get('return')
        if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, Mapping) or not canonical_guid(row.get('id')) for row in rows):
            raise RelatedQueryError('Related read returned malformed, oversized or noncanonical object rows', code='RELATED_QUERY_RESULT_SHAPE')
        return copy.deepcopy(rows)

    def grouped_rows(self, ids, frame):
        unique = list(dict.fromkeys(identity.upper() for identity in ids))
        found = {}
        fields = self.render(frame)
        for start in range(0, len(unique), MAX_STRUCTURED_SOURCE_ITEMS):
            chunk = unique[start:start + MAX_STRUCTURED_SOURCE_ITEMS]
            preview = build_object_get_query(object_ids=chunk, return_fields=fields, version=self.version,
                platform=self.return_scope.get('platform'), language=self.return_scope.get('language'))
            result = self.measured_read(OBJECT_GET, preview.envelope.args, preview.envelope.options)
            rows = self.validate_rows(result, len(chunk))
            batch = {}
            for row in rows:
                identity = row['id'].upper()
                if identity not in chunk or identity in batch:
                    raise RelatedQueryError('Grouped member read returned duplicate or extra identities', code='RELATED_QUERY_MEMBER_BATCH')
                batch[identity] = row
            if set(batch) != set(chunk):
                raise RelatedQueryError('Grouped member read omitted requested identities', code='RELATED_QUERY_MEMBER_BATCH')
            found.update(batch)
        return found

    def relationship_rows(self, owner, relation, sequence=None):
        """Return a complete bounded sequence for one actual owner/relation.

        The compiler owns SELECT, skip and final take. A final overflow sentinel
        distinguishes exactly4096 members from a silently truncated prefix.
        """
        if sequence and sequence['source'] == 'combine':
            return self.combination_rows(owner,sequence)
        source = build_object_get_query(object_id=owner, select=relation,
            return_fields=IDENTITY, version=self.version)
        rows = []
        limit, suffix, after = None, '', []
        stages = list((sequence or {}).get('stages', []))
        reducer = (sequence or {}).get('reducer',{})
        if reducer.get('operation') == 'any-match':
            stages.append({'selection':'matching', **reducer['condition']})
        if reducer.get('operation') in {'any','any-match'}:
            stages.append({'selection':'first'})
        for stage in stages:
            selection = stage['selection']
            if after or selection == 'last':
                after.append(stage); continue
            if selection in {'first','take','at'}:
                count = stage['count'] if selection == 'take' else 1
                if selection == 'at' and stage['count']:
                    suffix += f" skip {stage['count']}"
                    if limit is not None: limit = max(0,limit-stage['count'])
                limit = min(limit,count) if limit is not None else count
                if count: suffix += f' take {count}'
            elif selection == 'skip':
                if stage['count']: suffix += f" skip {stage['count']}"
                if limit is not None: limit = max(0,limit-stage['count'])
            elif selection == 'matching':
                suffix += ' ' + self.compile_condition(stage)
        if limit == 0: return []
        while True:
            count = min(MAX_QUERY_TAKE, MAX_RELATED_MEMBER_OCCURRENCES - len(rows) + 1)
            if limit is not None: count = min(count, limit-len(rows))
            # COUNT is not documented to accept zero, and pinned2021 native
            # rejects skip 0. The initial sequence needs no skip transform.
            waql = source.envelope.args["waql"] + suffix
            if rows:
                waql += f" skip {len(rows)}"
            preview = build_advanced_object_get_query({"contract": ADVANCED_QUERY_CONTRACT,
                "waql": waql,
                "return": list(IDENTITY), "max_results": count}, version=self.version,
                platform=self.return_scope.get('platform'), language=self.return_scope.get('language'))
            result = self.measured_read(OBJECT_GET, preview.envelope.args, preview.envelope.options)
            chunk = self.validate_rows(result, count)
            self.charge_sequence_members(chunk)
            rows.extend(chunk)
            if len(rows) > MAX_RELATED_MEMBER_OCCURRENCES:
                raise RelatedQueryError('Relationship membership exceeded its owned occurrence budget; refine the query', code='RELATED_QUERY_MEMBER_LIMIT')
            if len(chunk) < count or limit is not None and len(rows) == limit:
                for stage in after:
                    kind, count = stage['selection'], stage.get('count')
                    if kind == 'last': rows = rows[-1:]
                    elif kind == 'first': rows = rows[:1]
                    elif kind == 'at': rows = rows[count:count+1]
                    elif kind == 'take': rows = rows[:count]
                    elif kind == 'skip': rows = rows[count:]
                    elif kind == 'matching': rows = self.filter_rows(rows,stage)
                return rows

    def filter_rows(self, rows, condition):
        """Keep native predicate semantics and original occurrence order."""
        identities = list(dict.fromkeys(row['id'].upper() for row in rows))
        selected = set()
        for start in range(0,len(identities),MAX_STRUCTURED_SOURCE_ITEMS):
            chunk = identities[start:start+MAX_STRUCTURED_SOURCE_ITEMS]
            source = build_object_get_query(object_ids=chunk,return_fields=IDENTITY,version=self.version)
            preview = build_advanced_object_get_query({'contract':ADVANCED_QUERY_CONTRACT,
                'waql':source.envelope.args['waql']+' '+self.compile_condition(condition),
                'return':list(IDENTITY),'max_results':len(chunk)},version=self.version,
                platform=self.return_scope.get('platform'),language=self.return_scope.get('language'))
            values = self.validate_rows(self.measured_read(OBJECT_GET,preview.envelope.args,preview.envelope.options),len(chunk))
            ids = [row['id'].upper() for row in values]
            if len(set(ids)) != len(ids) or set(ids)-set(chunk):
                raise RelatedQueryError('Conditional member reads returned extra or duplicate identities',code='RELATED_QUERY_MEMBER_BATCH')
            selected.update(ids)
            self.charge_sequence_members(values)
        return [row for row in rows if row['id'].upper() in selected]

    def object_row(self, owner, extra=()):
        preview = build_object_get_query(object_id=owner,return_fields=(*IDENTITY,'classId',*extra),version=self.version,
            platform=self.return_scope.get('platform'),language=self.return_scope.get('language'))
        rows = self.validate_rows(self.measured_read(OBJECT_GET,preview.envelope.args,preview.envelope.options),1)
        if len(rows) != 1 or rows[0]['id'].upper() != owner.upper():
            raise RelatedQueryError('A combination arm lost its actual canonical owner',code='RELATED_QUERY_MEMBER_BATCH')
        return rows[0]

    def arm_rows(self, owner, arm, limit=None, conditions=()):
        if limit == 0: return []
        if arm == ['self']:
            rows = [self.object_row(owner)]
            for condition in conditions: rows = self.filter_rows(rows,condition)
            return rows
        hops = parse_related_request(self.version,[*arm,'volume-db'],'--include-related')['hops']
        values = [self.object_row(owner)]
        for hop_index,(kind,name) in enumerate(hops):
            following = []
            for row in values:
                if kind in {'list','sequence'}:
                    spec = json.loads(name) if kind == 'sequence' else {'source':name,'stages':[]}
                    if hop_index == len(hops)-1:
                        spec = {**spec,'stages':[*spec['stages'],*conditions]}
                        if limit is not None:
                            spec['stages'].append({'selection':'take','count':max(0,limit-len(following))})
                    selected = self.relationship_rows(row['id'],RELATED_QUERY_LIST_RELATIONS.get(spec['source'],'__combine__'),spec)
                    following.extend(selected)
                else:
                    if kind == 'relation': token = RELATED_QUERY_RELATIONS[name]
                    else:
                        selected = self.binder.bind(name,row,row.get('classId'),'',{'arm':arm,'object':row['id']},kind)
                        candidate = selected['candidate']
                        if candidate is None:
                            raise RelatedQueryError('Combination reference metadata is unresolved in its actual scope; refine the meaning',
                                code='RELATED_QUERY_SEQUENCE_SCOPE_UNAVAILABLE',details={'unresolved':selected,'requested_option':kind,'meaning':name})
                        if candidate['kind'] != 'reference':
                            raise RelatedQueryError('Combination reference hops require actual reference metadata',code='RELATED_QUERY_FIELD_KIND')
                        token = ('@' if kind == 'local-reference' else '') + candidate['name']
                    observation = self.object_row(row['id'],(token,))
                    reference = observation.get(token)
                    if reference is None: continue
                    if not isinstance(reference,Mapping) or not canonical_guid(reference.get('id')):
                        raise RelatedQueryError('Combination singleton arms require one canonical reference',code='RELATED_QUERY_RESULT_SHAPE')
                    target = self.object_row(reference['id'])
                    for key,value in reference.items():
                        if key in target and canonical_json_bytes(value) != canonical_json_bytes(target[key]):
                            raise RelatedQueryError('Combination reference identity changed during its read')
                    following.append({**target,**reference})
                    self.charge_sequence_members([target])
            values = following
            if hop_index == len(hops)-1 and kind not in {'list','sequence'}:
                for condition in conditions: values = self.filter_rows(values,condition)
            if len(values) > MAX_RELATED_MEMBER_OCCURRENCES:
                raise RelatedQueryError('Combination arm exceeded its member occurrence budget',code='RELATED_QUERY_MEMBER_LIMIT')
        return values[:limit] if limit is not None else values

    def combination_rows(self, owner, sequence):
        rows, origins = [], {}
        stages = list(sequence['stages'])
        reducer = sequence.get('reducer',{}).get('operation')
        if reducer == 'any-match':
            stages.append({'selection':'matching',**sequence['reducer']['condition']})
        if reducer in {'any','any-match'}: stages.append({'selection':'first'})
        conditions = []
        while stages and stages[0]['selection'] == 'matching': conditions.append(stages.pop(0))
        # Later filtering/last cannot enlarge a leading finite window. Retain
        # that input bound, then run every stage below in its declared order.
        required, offset, limit = None, 0, None
        if any(stage['selection'] == 'take' and stage['count'] == 0 for stage in stages):
            required = 0  # Empty remains empty through every admitted stage.
        else:
            for stage in stages:
                kind,count = stage['selection'],stage.get('count',1)
                if kind not in {'first','at','skip','take'}: break
                if kind in {'skip','at'}:
                    amount = min(count,limit) if limit is not None else count
                    offset += amount
                    if limit is not None: limit -= amount
                if kind in {'first','at','take'}:
                    count = count if kind == 'take' else 1
                    limit = min(limit,count) if limit is not None else count
                if limit is not None:
                    required = offset+limit if limit else 0
                    if limit == 0: break
        for arm_index,arm in enumerate(sequence['arms']):
            if required is not None and len(rows) >= required: break
            values = self.arm_rows(owner,arm,None if required is None else required-len(rows),conditions)
            for occurrence,value in enumerate(values):
                value = copy.deepcopy(value)
                origins[id(value)] = {'arm':arm_index,'occurrence':occurrence,
                    **({'occurrence_scope':'arm sequence after pushed matching'} if conditions else {})}
                rows.append(value)
            if len(rows) > MAX_RELATED_MEMBER_OCCURRENCES:
                raise RelatedQueryError('Combined sequence exceeded its member occurrence budget',code='RELATED_QUERY_MEMBER_LIMIT')
        for stage in stages:
            kind,count = stage['selection'],stage.get('count',1)
            if kind == 'first': rows = rows[:1]
            elif kind == 'last': rows = rows[-1:]
            elif kind == 'at': rows = rows[count:count+1]
            elif kind == 'take': rows = rows[:count]
            elif kind == 'skip': rows = rows[count:]
            else: rows = self.filter_rows(rows,stage)
        self.sequence_origins[(owner.upper(),canonical_sha256(sequence))] = [origins[id(row)] for row in rows]
        return rows

    def decode(self, root_rows):
        self.root.rows = {(index,): row for index, row in enumerate(root_rows)}
        occurrences = 0
        record_bytes = 0
        memberships = {}
        membership_facts = {}
        self.reductions = {}
        for frame in self.frames:
            for edge in frame.lists.values():
                edge.states, edge.child.rows, edge.child.origins = {}, {}, {}
                members = []
                key = self.edge_key(frame, edge)
                for loc, row in frame.rows.items():
                    if not self.composed or edge.sequence:
                        prefix, _, relation = edge.native.rpartition('.')
                        owner = row.get(prefix) if prefix else row
                        if owner is None:
                            edge.states[loc] = ('absent', None)
                            continue
                        if not isinstance(owner, Mapping) or not canonical_guid(owner.get('id')):
                            raise RelatedQueryError('Relationship membership requires an actual canonical owner', code='RELATED_QUERY_RESULT_SHAPE')
                        association = (owner['id'].upper(), relation, canonical_sha256(edge.sequence))
                        if association not in memberships:
                            values = self.relationship_rows(association[0], relation, edge.sequence)
                            reducer = (edge.sequence or {}).get('reducer',{})
                            matched = self.filter_rows(values,reducer['condition']) if reducer.get('operation') == 'all-match' else values
                            origins = self.sequence_origins.get((association[0],canonical_sha256(edge.sequence)))
                            memberships[association] = (values,matched,origins)
                        values,matched,origins = memberships[association]
                        if origins is not None:
                            edge.child.origins.update({loc+(index,):origin for index,origin in enumerate(origins)})
                        self.reductions[(edge.child.number,loc)] = bool(values) and len(matched) == len(values)
                        membership_facts[(frame.number,loc,edge.native,edge.child.number)] = {'owner':association[0], 'relation':relation, 'members':values,'matched':matched,'origins':origins}
                    else:
                        if key not in row:
                            edge.states[loc] = ('absent', None)
                            continue
                        values = row[key]
                        if values is None:
                            edge.states[loc] = ('null', None)
                            continue
                    if not isinstance(values, list) or any(not isinstance(value, Mapping) or not canonical_guid(value.get('id')) for value in values):
                        raise RelatedQueryError('A related list must contain canonical object records, null or absence', code='RELATED_QUERY_RESULT_SHAPE')
                    occurrences += len(values)
                    self.unique_ids.update(value['id'].upper() for value in values)
                    if occurrences > MAX_RELATED_MEMBER_OCCURRENCES or len(self.unique_ids) > MULTI_IDENTITY_READ_MAX_IDS:
                        raise RelatedQueryError('Related members exceeded their occurrence or unique-identity budget; refine the query', code='RELATED_QUERY_MEMBER_LIMIT')
                    edge.states[loc] = ('items', [(loc + (index,)) for index in range(len(values))])
                    members.extend((loc + (index,), value) for index, value in enumerate(values))
                if not self.composed or edge.sequence:
                    records = self.grouped_rows([value['id'] for _, value in members], edge.child)
                    sizes = {identity: len(canonical_json_bytes(record)) for identity,record in records.items()}
                    for loc, reference in members:
                        record_bytes += sizes[reference['id'].upper()] + len(canonical_json_bytes(reference))
                        if record_bytes > self.maximum_read_bytes:
                            raise RelatedQueryError('Grouped member reconstruction exceeded its owned byte budget; refine the query', code='RELATED_QUERY_OBSERVATION_LIMIT')
                        record = records[reference['id'].upper()]
                        for key, value in reference.items():
                            if key in record and key != 'id' and canonical_json_bytes(value) != canonical_json_bytes(record[key]):
                                raise RelatedQueryError('Membership reference facts conflict with the independently read member; restart the query')
                        # Native reference extensions belong to that occurrence.
                        edge.child.rows[loc] = {**copy.deepcopy(reference), **copy.deepcopy(record)}
                else:
                    edge.child.rows.update(members)
        self.total_occurrences += occurrences
        if self.total_occurrences > MAX_RELATED_MEMBER_OBSERVATIONS:
            raise RelatedQueryError('Related reads exceeded their cumulative member observation budget', code='RELATED_QUERY_MEMBER_LIMIT')
        snapshot = {}
        for frame in self.frames:
            for loc, row in frame.rows.items():
                requested = set(self.render(frame, root=frame is self.root))
                requested.update(self.edge_key(frame, edge) for edge in frame.lists.values())
                extras = self.observed_extra_fields.setdefault((frame.number,loc), set())
                extras.update(key for key in row if key not in requested)
                for key in extras:
                    snapshot[f'{frame.number}:{loc}:native_extension:{key}'] = {'present':key in row,'value':row.get(key)}
                for native in frame.scope:
                    snapshot[f'{frame.number}:{loc}:{native}'] = {'present': native in row, 'value': row.get(native)}
            for edge in frame.lists.values():
                for loc, state in edge.states.items():
                    snapshot[f'{frame.number}:{loc}:list:{edge.child.number}'] = state
                    if not self.composed or edge.sequence:
                        snapshot[f'{frame.number}:{loc}:membership:{edge.child.number}'] = membership_facts.get((frame.number,loc,edge.native,edge.child.number))
        return snapshot

    def accept(self, root_rows):
        snapshot = self.decode(root_rows)
        previous = {key: snapshot.get(key) for key in self.snapshot}
        if canonical_json_bytes(previous) != canonical_json_bytes(self.snapshot):
            raise RelatedQueryError('Query membership, related identities or actual metadata scopes changed; restart the original read',
                details={'restart_original_read': True, 'expected_scope_sha256': canonical_sha256(self.snapshot), 'actual_scope_sha256': canonical_sha256(previous)})
        self.snapshot = copy.deepcopy(snapshot)

    def observe(self):
        preview = self.build_preview(self.render(self.root, root=True))
        self.return_scope = {key:value for key,value in preview.envelope.options.items() if key != 'return'}
        result = self.measured_read(OBJECT_GET, preview.envelope.args, preview.envelope.options)
        self.accept(self.validate_rows(result, self.maximum_rows))

    def add_scope(self, frame, native):
        for value in (native, f'{native}.classId' if native else 'classId'):
            if value:
                if value not in frame.fields: frame.fields.append(value)
                if value not in frame.scope: frame.scope.append(value)

    def field(self, frame, loc, prefix, meaning, option):
        row = frame.rows[loc]
        reference = row.get(prefix) if prefix else row
        if reference is None: return None
        if not isinstance(reference, Mapping) or not canonical_guid(reference.get('id')):
            raise RelatedQueryError('A singleton path requires one canonical reference, null or absence', code='RELATED_QUERY_RESULT_SHAPE')
        return self.binder.bind(meaning, reference, row.get(f'{prefix}.classId' if prefix else 'classId'), prefix, {'frame':frame.number,'occurrence':list(loc)}, option)

    def unresolved(self, candidates, matched, option, meaning, pending):
        for frame, loc, prefix, path, selected in candidates:
            if matched and selected['complete'] and not selected['candidate_names']:
                frame.outputs.append((loc, path, 'unavailable', '', None, {'meaning':meaning,'requested_option':option,'reason':'no matching field in the complete actual metadata scope'}))
            else:
                pending.append({'option':option,'meaning':meaning,'path':prefix,'occurrence':list(loc), **selected})

    def prepare(self):
        self.observe()
        pending = []
        for request in self.requests:
            states = [(self.root, loc, '', ()) for loc in self.root.rows]
            terminal_states = []
            for kind, name in request['hops']:
                next_states, unresolved = [], []
                if kind in {'list','sequence'}:
                    sequence = json.loads(name) if kind == 'sequence' else None
                    relation = sequence['source'] if sequence else name
                    # One frame per structural edge; no per-row schema/discovery.
                    edges = {}
                    for frame, loc, prefix, path in states:
                        native = '.'.join(value for value in (prefix, RELATED_QUERY_LIST_RELATIONS.get(relation,'__combine__')) if value)
                        business = (*path, ('relation', relation))
                        edge_id = native if sequence is None else native + ':' + canonical_sha256(sequence)
                        if edge_id not in frame.lists:
                            child = Frame(len(self.frames)); self.frames.append(child)
                            frame.lists[edge_id] = ListEdge(native, business, child, sequence=sequence)
                        edges[(frame.number, native)] = frame.lists[edge_id]
                    self.observe()
                    for frame, loc, prefix, path in states:
                        native = '.'.join(value for value in (prefix, RELATED_QUERY_LIST_RELATIONS.get(relation,'__combine__')) if value)
                        edge = edges[(frame.number, native)]
                        status, locations = edge.states[loc]
                        if status == 'items':
                            next_states.extend((edge.child, child_loc, '', ()) for child_loc in locations)
                else:
                    for frame, loc, prefix, path in states:
                        if kind == 'relation':
                            token, slot = RELATED_QUERY_RELATIONS[name], 'relation'
                        else:
                            selected = self.field(frame, loc, prefix, name, kind)
                            if selected is None: continue
                            candidate = selected['candidate']
                            if candidate is None:
                                unresolved.append((frame,loc,prefix,path,selected)); continue
                            if candidate.get('kind') != 'reference':
                                raise RelatedQueryError('Reference hops require freshly discovered reference metadata', code='RELATED_QUERY_FIELD_KIND')
                            token = ('@' if kind == 'local-reference' else '') + candidate['name']
                            slot = 'local_references' if kind == 'local-reference' else 'references'
                        native = '.'.join(value for value in (prefix,token) if value)
                        business = (*path, (slot, name if kind == 'relation' else candidate['name']))
                        self.add_scope(frame, native)
                        next_states.append((frame,loc,native,business))
                        frame.outputs.append((loc,business,'identity',native,None,'object'))
                    self.unresolved(unresolved, next_states, kind, name, pending)
                    self.observe()
                    terminal_states = next_states
                    valid = []
                    for frame, loc, prefix, path in next_states:
                        reference = frame.rows[loc].get(prefix)
                        if reference is None: continue
                        if not isinstance(reference, Mapping) or not canonical_guid(reference.get('id')):
                            raise RelatedQueryError('A singleton hop must return one canonical object reference', code='RELATED_QUERY_RESULT_SHAPE')
                        valid.append((frame,loc,prefix,path))
                    next_states = valid
                states = next_states
            if request['option'] == '--include-related' and request['hops'][-1][0] not in {'list','sequence'}:
                states = terminal_states
            if request['option'] == '--include-related' and request.get('reducer') is not None:
                continue
            unresolved, matched = [], []
            for frame, loc, prefix, path in states:
                if request['option'] == '--include-related':
                    terminal, output = available_query_outputs(self.version)[request['terminal']]
                    group = None
                else:
                    selected = self.field(frame,loc,prefix,request['terminal'],request['option'])
                    if selected is None: continue
                    candidate = selected['candidate']
                    if candidate is None:
                        unresolved.append((frame,loc,prefix,path,selected)); continue
                    mode = RELATED_FIELD_MODES[request['option']]
                    if candidate.get('kind') not in mode.bindings:
                        raise RelatedQueryError(f"{request['option']} does not admit this live field kind", code='RELATED_QUERY_FIELD_KIND')
                    binding_kind, native_prefix = mode.bindings[candidate['kind']]
                    terminal, output = native_prefix + candidate['name'], candidate['name']
                    group = QUERY_FIELD_OUTPUT_GROUPS[binding_kind]
                _, native, location = RelatedQueryOutput('', prefix, terminal, output, group, path=path).binding()
                group, output = location['group'], location['field']
                alias = (frame.number,loc,native,group,output)
                if alias in self.aliases:
                    raise RelatedQueryError('Related declarations resolved duplicate result fields', code='RELATED_QUERY_DUPLICATE_FIELD')
                self.aliases.add(alias)
                if native not in frame.fields: frame.fields.append(native)
                frame.outputs.append((loc,path,'terminal',native,group,output))
                matched.append(loc)
            self.unresolved(unresolved,matched,request['option'],request['terminal'],pending)
        if pending:
            return {'metadata_authority':'live-waapi','unresolved':pending,'repair':'Refine each unresolved meaning within its actual scope, retaining its option and path; no other class token is substituted'}
        self.observe()  # Observe full values and revalidate every prepared scope.
        return None

    def proof(self):
        return {'strategy':self.strategy,'atomic_snapshot':False,
            **({'sequence_semantics':'Gateway business derivation; no native function-return equality or atomic snapshot'}
               if self.has_sequences else {}),
            **({'sequence_source':related_sequence_source(self.version)}
               if self.has_sequences else {}),
            'observed_scope_sha256':canonical_sha256(self.snapshot),
            'metadata_observations_sha256':canonical_sha256(self.binder.observations),
            'scopes':self.binder.selections,'read_associations':self.descriptors,
            'limits':{'unique_member_ids':MULTI_IDENTITY_READ_MAX_IDS,'member_occurrences':MAX_RELATED_MEMBER_OCCURRENCES,
                'cumulative_member_observations':MAX_RELATED_MEMBER_OBSERVATIONS,'source_ids_per_read':MAX_STRUCTURED_SOURCE_ITEMS,
                **({'relationship_rows_per_read':MAX_QUERY_TAKE} if not self.composed else {}),
                'cumulative_read_bytes':MAX_ADVANCED_RETURN_EXPRESSIONS*self.maximum_read_bytes,'grouped_member_reconstruction_bytes':self.maximum_read_bytes},
            'metadata_authority':'live-waapi','mutation_authority':False}

    def project(self, rows):
        # For grouped lanes this repeats bounded member reads against the final
        # root membership. Their exact values enter the page seal, not a fiction
        # that the final root transport supplied member property values.
        self.accept(self.validate_rows({'return':list(rows)}, self.maximum_rows))
        projected = {}
        for frame in reversed(self.frames):
            for loc, row in frame.rows.items():
                if frame is self.root:
                    item = {}
                else:
                    hidden = set(frame.fields) - set(IDENTITY)
                    hidden.update(self.edge_key(frame, edge) for edge in frame.lists.values())
                    item = {'object':copy.deepcopy({key:value for key,value in row.items() if key not in hidden})}
                    if loc in frame.origins: item['origin'] = copy.deepcopy(frame.origins[loc])
                    missing = [key for key in IDENTITY if key not in row]
                    if missing:
                        item['identity_completeness'] = {'complete':False,'unavailable_fields':missing,'mutation_authority':False}
                for output_loc, path, kind, native, group, output in frame.outputs:
                    if output_loc != loc: continue
                    target = context_at(item,path)
                    if kind == 'unavailable':
                        target.setdefault('unavailable_field_requests',[]).append(output); continue
                    if kind == 'identity':
                        reference = row.get(native)
                        missing_identity = [key for key in ('id','name') if not isinstance(reference, Mapping) or key not in reference]
                        if missing_identity:
                            target['identity_completeness'] = {'complete':False,'unavailable_fields':missing_identity,'mutation_authority':False}
                    if native not in row:
                        missing = target.setdefault('unavailable_fields',[])
                        name = f'{group}.{output}' if group else output
                        if name not in missing: missing.append(name)
                    else:
                        (target.setdefault(group,{}) if group else target)[output] = copy.deepcopy(row[native])
                for edge in frame.lists.values():
                    if edge.sequence:
                        context = context_at(item,edge.path[:-1]).setdefault('related',{})
                        target = {'spec':copy.deepcopy(edge.sequence)}
                        target['derivation'] = 'gateway-business-sequence'
                        context.setdefault('projections',[]).append(target)
                    else:
                        target = context_at(item,edge.path)
                    status, locations = edge.states[loc]
                    if status == 'absent': target.setdefault('unavailable_fields',[]).append('items')
                    elif status == 'null': target['items'] = None
                    elif edge.sequence and edge.sequence.get('reducer'):
                        operation = edge.sequence['reducer']['operation']
                        target['value'] = (len(locations) if operation == 'count' else self.reductions[(edge.child.number,loc)]
                                           if operation == 'all-match' else bool(locations))
                    else: target['items'] = [projected[(edge.child.number,childloc)] for childloc in locations]
                projected[(frame.number,loc)] = item
        return [projected[(0,(index,))] for index in range(len(rows))]

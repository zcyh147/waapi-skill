"""Invocation-local, bounded binding of singleton paths to actual native scopes.

Fixed paths bypass this planner. Custom terminals and reference hops observe the
unchanged query membership, share class metadata, then seal those prefix facts
against the final data read. No endpoint is inferred from a root type or name.
"""
from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .builders.query import MAX_ADVANCED_RETURN_EXPRESSIONS
from .metadata_discovery import discover_metadata, MAX_METADATA_DISCOVERY_RESULT_BYTES
from .object_query_outputs import QUERY_FIELD_OUTPUT_GROUPS, available_query_outputs
from .object_query_related import (RELATED_FIELD_MODES, RELATED_QUERY_RELATIONS,
    RelatedQueryOutput, related_native_fields)

OBJECT_GET = 'ak.wwise.core.object.get'
IDENTITY = ('id', 'name', 'type', 'path')


class RelatedQueryError(ValueError):
    def __init__(self, message, *, code='RELATED_QUERY_SCOPE_CHANGED', details=None):
        super().__init__(message)
        self.code, self.details = code, details or {}


def canonical_guid(value):
    try:
        return isinstance(value, str) and value.startswith('{') and value.endswith('}') and str(uuid.UUID(value[1:-1])).upper() == value[1:-1].upper()
    except (ValueError, AttributeError):
        return False


def validate_related_observation(rows, proof):
    fields = proof['observed_fields']
    actual = [{key: copy.deepcopy(row[key]) for key in fields if key in row} for row in rows]
    if actual != proof['observed_rows']:
        raise RelatedQueryError('Query membership, related identity or metadata scope changed during the read; restart the original query',
            details={'restart_original_read': True, 'native_query_dispatched': True, 'expected_rows': len(proof['observed_rows']), 'actual_rows': len(rows),
                'expected_scope_sha256': canonical_sha256(proof['observed_rows']), 'actual_scope_sha256': canonical_sha256(actual)})


def prepare_related_outputs(*, version, requests, bindings, build_preview, read, maximum_rows, maximum_read_bytes):
    """Return owned bindings, scope proof and optional public clarification."""
    bindings = list(bindings)
    observed_fields = list(IDENTITY)
    fields = []
    rows = None
    observations, metadata_cache, selections, discoveries = [], {}, [], {}
    total_bytes = metadata_bytes = 0

    def observe(wanted):
        nonlocal rows, total_bytes
        wanted = tuple(dict.fromkeys((*fields, *wanted)))
        if rows is not None and all(field in fields for field in wanted):
            return
        # Enforce the same projection ceiling on every prefix read and final read.
        related_native_fields([('related_scope', field, {}) for field in wanted], IDENTITY)
        preview = build_preview(wanted)
        result = read(OBJECT_GET, preview.envelope.args, preview.envelope.options)
        native_rows = result.get('return')
        if (not isinstance(native_rows, list) or len(native_rows) > maximum_rows
                or any(not isinstance(row, Mapping) for row in native_rows)):
            raise RelatedQueryError('Related scope preparation returned malformed or oversized rows', code='RELATED_QUERY_RESULT_SHAPE')
        total_bytes += len(canonical_json_bytes(result))
        if total_bytes > MAX_ADVANCED_RETURN_EXPRESSIONS * maximum_read_bytes:
            raise RelatedQueryError('Related scope observation exceeded its aggregate byte budget', code='RELATED_QUERY_OBSERVATION_LIMIT')
        if rows is not None:
            validate_related_observation(native_rows, {'observed_fields': observed_fields,
                'observed_rows': [{key: row[key] for key in observed_fields if key in row} for row in rows]})
        rows = copy.deepcopy(native_rows)
        fields[:] = wanted

    def cache_read(uri, args, options):
        nonlocal total_bytes, metadata_bytes
        key = canonical_sha256({'uri': uri, 'args': args, 'options': options})
        if key not in metadata_cache:
            result = read(uri, args, options)
            size = len(canonical_json_bytes(result))
            total_bytes += size
            metadata_bytes += size
            # Scope/metadata remains bounded across heterogeneous queries as well
            # as within each discover_metadata invocation.
            if metadata_bytes > MAX_METADATA_DISCOVERY_RESULT_BYTES:
                raise RelatedQueryError('Related metadata observation exceeded its aggregate byte budget; refine the query', code='RELATED_QUERY_METADATA_LIMIT')
            metadata_cache[key] = copy.deepcopy(result)
            observations.append({'api': uri, 'args': copy.deepcopy(args), 'result': copy.deepcopy(result)})
        return copy.deepcopy(metadata_cache[key])

    def bind(meaning, native, index, option):
        row = rows[index]
        reference = row if not native else row.get(native)
        if not isinstance(reference, Mapping) or not canonical_guid(reference.get('id')):
            return None
        class_id = row.get(f'{native}.classId' if native else 'classId')
        scope = {'classId': class_id} if type(class_id) is int and 0 <= class_id <= 4294967295 else {'object': reference['id'].upper()}
        def lookup(scope):
            key = (canonical_sha256(scope), meaning)
            if key not in discoveries:
                discovery = discover_metadata(read_call=cache_read, queries=(meaning,),
                    class_id=scope.get('classId'), object=scope.get('object'))
                query = discovery.query_results[0]
                candidates = {item['name']: item for item in discovery.candidates}
                names = query.get('candidate_names', [])
                exact = [name for name in names if name.casefold() == meaning.casefold() or
                    (isinstance(candidates[name].get('metadata', {}).get('display'), Mapping) and
                     candidates[name]['metadata']['display'].get('name', '').casefold() == meaning.casefold())]
                chosen = exact if len(exact) == 1 else names
                candidate = candidates.get(chosen[0]) if len(chosen) == 1 else None
                complete = discovery.fallback_detail_scan.get('status') in {'complete', 'not_needed'}
                if candidate and not re.fullmatch(r'[A-Za-z0-9_]+', candidate.get('name', '')):
                    raise RelatedQueryError('The discovered field token cannot be safely composed by this related-output contract; refine the field request', code='RELATED_QUERY_FIELD_TOKEN')
                discoveries[key] = {'scope': scope, 'meaning': meaning, 'candidate': candidate,
                    'candidate_names': names, 'complete': complete}
            return discoveries[key]
        selection = lookup(scope)
        # Shared class facts need no per-row reads when they bind. A complete
        # class no-match does not rule out instance/plugin-specific metadata.
        if 'classId' in scope and selection['complete'] and not selection['candidate_names']:
            selection = lookup({'object': reference['id'].upper()})
        selections.append({'path': native, 'requested_option': option, 'row_index': index,
            **{key: value for key, value in selection.items() if key != 'candidate'},
            'selected': ({'name': selection['candidate'].get('name'), 'kind': selection['candidate'].get('kind')}
                         if selection['candidate'] else None)})
        return selection

    # Read all statically known prefixes together, including actual endpoint class.
    initial = list(IDENTITY)
    for request in requests:
        native = ''
        for kind, name in request['hops']:
            if kind != 'relation':
                break
            native = f'{native}.' if native else ''
            native += RELATED_QUERY_RELATIONS[name]
            initial.extend((native, f'{native}.classId'))
        if not native:
            initial.append('classId')
    observe(initial)
    observed_fields[:] = list(dict.fromkeys(initial))
    if any(not canonical_guid(row.get('id')) for row in rows):
        raise RelatedQueryError('Custom related projections require canonical root object identities; this observation does not establish such a scope',
            code='RELATED_QUERY_IDENTITY_INCOMPLETE', details={'native_observation': {'return': rows}, 'mutation_authority': False})

    pending, aliases = [], {}
    for request in requests:
        states = [(index, '', ()) for index in range(len(rows))]
        for kind, name in request['hops']:
            next_states, added = [], []
            if kind == 'relation':
                for index, prefix, path in states:
                    native = f'{prefix}.' if prefix else ''
                    native += RELATED_QUERY_RELATIONS[name]
                    next_states.append((index, native, (*path, ('relation', name))))
            else:
                scope_matches = []
                for index, prefix, path in states:
                    selected = bind(name, prefix, index, kind)
                    if selected is None:
                        continue
                    if selected['candidate'] is None:
                        scope_matches.append((index, prefix, path, selected))
                        continue
                    candidate = selected['candidate']
                    if candidate.get('kind') != 'reference':
                        raise RelatedQueryError(f'{kind} hops require a freshly discovered reference field', code='RELATED_QUERY_FIELD_KIND')
                    token = candidate['name']
                    native = f'{prefix}.' if prefix else ''
                    native += ('@' if kind == 'local-reference' else '') + token
                    slot = 'local_references' if kind == 'local-reference' else 'references'
                    next_states.append((index, native, (*path, (slot, token))))
                # An unresolved hop cannot acquire another scope's token.
                for index, prefix, path, selected in scope_matches:
                    if next_states and selected['complete'] and not selected['candidate_names']:
                        bindings.append(('related_unavailable', '', {'path': path, 'row_indices': (index,),
                            'meaning': name, 'requested_option': kind, 'reason': 'no matching reference in the complete actual metadata scope'}))
                    else:
                        pending.append({'option': kind, 'meaning': name, 'path': prefix, 'row_index': index, **selected})
            for index, native, path in next_states:
                added.extend((native, f'{native}.classId'))
            observe((*fields, *added))
            observed_fields[:] = list(dict.fromkeys((*observed_fields, *added)))
            states = []
            for index, native, path in next_states:
                reference = rows[index].get(native)
                bindings.append(('related_identity', native, {'path': path, 'row_indices': (index,)}))
                if reference is None:
                    continue
                if not isinstance(reference, Mapping) or not canonical_guid(reference.get('id')):
                    raise RelatedQueryError('A related hop must return one canonical object reference, null or absence; list composition requires a separate interface', code='RELATED_QUERY_RESULT_SHAPE')
                states.append((index, native, path))
        if request['option'] == '--include-related':
            terminal, output = available_query_outputs(version)[request['terminal']]
            for index, native, path in next_states:
                bindings.append(RelatedQueryOutput(path[0][1], native, terminal, output, path=path, row_indices=(index,)).binding())
            continue
        mode = RELATED_FIELD_MODES[request['option']]
        matched, unresolved = [], []
        for index, native, path in states:
            selected = bind(request['terminal'], native, index, request['option'])
            if selected is None:
                continue
            candidate = selected['candidate']
            if candidate is None:
                unresolved.append((index, native, path, selected))
                continue
            kind, token = candidate.get('kind'), candidate.get('name')
            if kind not in mode.bindings:
                raise RelatedQueryError(f"{request['option']} only admits live {', '.join(mode.bindings)} fields", code='RELATED_QUERY_FIELD_KIND')
            binding_kind, prefix = mode.bindings[kind]
            identity = (index, native, prefix + token)
            if identity in aliases:
                raise RelatedQueryError('Related field meanings resolved duplicate result fields', code='RELATED_QUERY_DUPLICATE_FIELD')
            aliases[identity] = request['terminal']
            bindings.append(RelatedQueryOutput(path[0][1], native, prefix + token, token,
                QUERY_FIELD_OUTPUT_GROUPS[binding_kind], path=path, row_indices=(index,)).binding())
            matched.append(index)
        for index, native, path, selected in unresolved:
            if matched and selected['complete'] and not selected['candidate_names']:
                bindings.append(('related_unavailable', '', {'path': path, 'row_indices': (index,),
                    'meaning': request['terminal'], 'requested_option': request['option'], 'reason': 'no matching field in the complete actual metadata scope'}))
            else:
                pending.append({'option': request['option'], 'meaning': request['terminal'], 'path': native, 'row_index': index, **selected})

    if pending:
        return None, None, {'metadata_authority': 'live-waapi', 'unresolved': pending,
            'repair': 'Refine each unresolved meaning within its disclosed actual scope, retaining its option and path; no other class token is substituted'}
    # Prefix helpers remain hidden but are retained in the final native read and seal.
    bindings.extend(('related_scope', field, {}) for field in observed_fields if field not in IDENTITY)
    # Shared path prefixes add no second output, while scoped differences remain
    # explicit. No deduplication changes the native root occurrences.
    bindings = list({canonical_sha256(binding): binding for binding in bindings}.values())
    related_native_fields(bindings, IDENTITY)
    proof = {'observed_fields': observed_fields,
        'observed_rows': [{key: row[key] for key in observed_fields if key in row} for row in rows],
        'metadata_observations_sha256': canonical_sha256(observations), 'scopes': selections,
        'metadata_authority': 'live-waapi', 'mutation_authority': False}
    return tuple(bindings), proof, None

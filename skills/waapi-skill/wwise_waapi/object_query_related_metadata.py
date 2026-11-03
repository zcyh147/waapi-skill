"""Invocation-local exact-scope field binding shared by related cardinalities."""
from __future__ import annotations
import copy
import re
from collections.abc import Mapping
from .canonical import canonical_json_bytes, canonical_sha256
from .metadata_discovery import discover_metadata, MAX_METADATA_DISCOVERY_RESULT_BYTES


def namespaced_property_token(value):
    """Scalar property lexical shape; fresh property metadata supplies authority."""
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_]+:[A-Za-z0-9_]+', value) is not None


class RelatedFieldBinder:
    def __init__(self, read, error, *, version=None):
        self.read, self.error, self.version = read, error, version
        self.reference_kind_proofs = {}
        self.metadata_cache, self.discoveries = {}, {}
        self.observations, self.selections = [], []
        self.metadata_bytes = 0

    def cached_read(self, uri, args, options):
        key = canonical_sha256({'uri': uri, 'args': args, 'options': options})
        if key not in self.metadata_cache:
            result = self.read(uri, args, options)
            size = len(canonical_json_bytes(result))
            self.metadata_bytes += size
            # Scope/metadata remains bounded across heterogeneous queries as well
            # as within each discover_metadata invocation.
            if self.metadata_bytes > MAX_METADATA_DISCOVERY_RESULT_BYTES:
                raise self.error('Related metadata observation exceeded its aggregate byte budget; refine the query', code='RELATED_QUERY_METADATA_LIMIT')
            self.metadata_cache[key] = copy.deepcopy(result)
            self.observations.append({'api': uri, 'args': copy.deepcopy(args), 'result': copy.deepcopy(result)})
        return copy.deepcopy(self.metadata_cache[key])

    def bind(self, meaning, reference, class_id, native, index, option, *, namespaced_property=False, status=None):
        if option == 'curve-selection':
            from .object_query_functions import curve_argument
            candidate = curve_argument(self.version, meaning, class_id, self.error)
            selection = {'scope': {'object': reference['id'].upper(), 'classId': class_id}, 'meaning': meaning,
                'candidate': candidate, 'candidate_names': [meaning], 'complete': True}
            self.selections.append({'path': native, 'requested_option': option, 'row_index': index,
                'scope': selection['scope'], 'selected': candidate})
            return selection
        if option == 'field-status':
            from .object_query_functions import documented_status_field, known_presence_field
            selected = documented_status_field(self.version, meaning, class_id)
            if selected is None and status == 'present':
                selected = known_presence_field(self.version, meaning)
            if selected is not None:
                selection = {'scope': {'object': reference['id'].upper(), 'classId': class_id},
                    'meaning': meaning, 'candidate': selected, 'candidate_names': [selected['name']], 'complete': True}
                self.selections.append({'path': native, 'requested_option': option, 'row_index': index,
                    **{key: value for key, value in selection.items() if key != 'candidate'},
                    'selected': selected})
                return selection
        scope = {'classId': class_id} if type(class_id) is int and 0 <= class_id <= 4294967295 else {'object': reference['id'].upper()}
        def lookup(scope):
            key = (canonical_sha256(scope), meaning)
            if key not in self.discoveries:
                discovery = discover_metadata(read_call=self.cached_read, queries=(meaning,),
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
                self.discoveries[key] = {'scope': scope, 'meaning': meaning, 'candidate': candidate,
                    'candidate_names': names, 'complete': complete}
            return self.discoveries[key]
        selection = lookup(scope)
        # Shared class facts need no per-row reads when they bind. A complete
        # class no-match does not rule out instance/plugin-specific metadata.
        unknown_kind = selection['candidate'] is not None and selection['candidate'].get('kind') not in {'property', 'reference'}
        if 'classId' in scope and selection['complete'] and (not selection['candidate_names'] or unknown_kind):
            selection = lookup({'object': reference['id'].upper()})
        if (selection['candidate'] is not None and selection['candidate'].get('kind') == 'unknown'
                and 'object' in selection['scope'] and option in {'reference', 'local-reference',
                    '--include-related-field', '--include-related-local-reference', 'field-status'}):
            from .reference_kind_evidence import certify_query_candidate
            candidate = certify_query_candidate(selection['candidate'], version=self.version,
                object_id=reference['id'].upper(), class_id=class_id, read=self.cached_read)
            selection = {**selection, 'candidate': candidate}
            if candidate.get('kind_evidence'):
                self.reference_kind_proofs[canonical_sha256(candidate['kind_evidence'])] = candidate['kind_evidence']
        # Unknown kind is insufficient authority, not a known wrong kind. If
        # exact-object facts remain insufficient, retain scoped clarification.
        if selection['candidate'] is not None and selection['candidate'].get('kind') not in {'property', 'reference'}:
            selection = {**selection, 'insufficient_kind': selection['candidate'].get('kind'), 'candidate': None}
        if status == 'present' and selection['candidate'] is not None:
            candidate = selection['candidate']
            display = candidate.get('metadata', {}).get('display')
            if meaning.casefold() not in {candidate['name'].casefold(),
                    display.get('name', '').casefold() if isinstance(display, Mapping) else ''}:
                selection = {**selection, 'candidate': None, 'exact_concept_required': True}
        candidate = selection['candidate']
        # Apply the current use's policy after exact-object kind fallback, on
        # every bind. Cached property discovery cannot grant its token permission
        # to a later reference hop or reference output using the same meaning.
        if candidate and not (re.fullmatch(r'[A-Za-z0-9_]+', candidate.get('name', ''))
                or namespaced_property and candidate.get('kind') == 'property'
                and namespaced_property_token(candidate.get('name'))):
            raise self.error('The discovered field token cannot be safely composed by this related-output contract; refine the field request', code='RELATED_QUERY_FIELD_TOKEN')
        self.selections.append({'path': native, 'requested_option': option, 'row_index': index,
            **{key: value for key, value in selection.items() if key != 'candidate'},
            'selected': ({'name': selection['candidate'].get('name'), 'kind': selection['candidate'].get('kind')}
                         if selection['candidate'] else None)})
        return selection

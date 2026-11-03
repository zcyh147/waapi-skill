"""Closed nonhierarchical object contexts, observed with bounded native SELECT."""
import json

CONTEXTS = {
    'panner': {'native': 'panner', 'first': '2024.1', 'types': ('Panner',)},
    'state': {'native': 'state', 'first': '2025.1', 'types': ('CustomState',)},
    'maximum-duration-source': {'native': 'maxDurationSourceObject', 'first': '2023.1', 'types': None},
    'maximum-radius-attenuation': {'native': 'maxRadiusAttenuationObject', 'first': '2023.1', 'types': ('Attenuation',)},
}


def context_spec(version, name, selector=None):
    if version < CONTEXTS[name]['first']:
        raise ValueError('This context lacks matching version source; native absence is not established')
    result = {'name': name}
    if name == 'state':
        from .object_query_field_conditions import reference_constant
        selected = reference_constant(selector)
        if selected is None:
            raise ValueError('state requires an exact original State selector, not null')
        result['selector'] = selected
    return result


def context_expression(spec):
    if spec['name'] == 'state':
        return f'state({json.dumps(spec["state_guid"])})'
    return CONTEXTS[spec['name']]['native']


def validate_context_rows(spec, rows, error):
    if len(rows) > 1:
        raise error('A singleton object context returned more than one object', code='RELATED_QUERY_CONTEXT_CARDINALITY')
    for row in rows:
        if any(not isinstance(row.get(key), str) for key in ('id', 'name', 'type', 'path')) or (CONTEXTS[spec['name']]['types'] is not None and row['type'] not in CONTEXTS[spec['name']]['types']):
            raise error('Object context returned incomplete identity or incompatible type', code='RELATED_QUERY_CONTEXT_IDENTITY')


def context_contract(version):
    from pathlib import Path
    import hashlib
    from .schema_inventory import load_definition_graph
    source = None
    if version >= '2023.1':
        root = Path(__file__).resolve().parents[1]
        raw = (root / 'references/semantic' / version / 'query-context-sources.json').read_bytes()
        if len(raw) > 32 * 1024:
            raise ValueError('Context source exceeded its packaged byte ceiling')
        source = json.loads(raw)
        if (source['version'], source['wwise_build']) != (version, load_definition_graph(version).wwise_build) or source['definitions_sha256'] != hashlib.sha256(
                (root / 'resources/manifest' / version / 'definitions.json').read_bytes()).hexdigest():
            raise ValueError('Context source does not match selected definitions')
    return {'hops': {name: {'available': version >= spec['first'], 'first_documented_version': spec['first'],
            'result_types': list(spec['types']) if spec['types'] is not None else 'actual Audio Source type; not a hard-coded subclass allowlist'}
            for name, spec in CONTEXTS.items()},
        'grammar': 'existing closed hops plus panner / maximum-duration-source / maximum-radius-attenuation / state STATE_SELECTOR, followed by existing fixed/custom terminal',
        'state_selector': 'canonical State GUID or the existing closed id/path/exact-type-name/direct-child/scoped-name selector; resolve and revalidate one actual original State before generating state(GUID)',
        'state_selector_examples': [{'kind': 'id', 'value': '<canonical-State-GUID>'},
            {'kind': 'path', 'value': '<exact-State-path>'},
            {'kind': 'exact-type-name', 'type': 'State', 'name': '<exact-State-name>'},
            {'kind': 'direct-child', 'parent': {'kind': 'id', 'value': '<StateGroup-GUID>'}, 'type': 'State'},
            {'kind': 'scoped-name', 'parent': {'kind': 'id', 'value': '<StateGroup-GUID>'}, 'type': 'State', 'name': '<exact-State-name>'}],
        'state_result': 'associated CustomState, distinct from original State; result under related.states.<StateGUID>',
        'applicability': 'Panner on objects supporting Positioning; extrema on Actor-Mixer/Interactive-Music objects and Events in2023/24, Containers and Events in2025; native selection determines the actual context, never direct-reference/XML equivalence',
        'result': 'owner-preserving singleton related.<context>.object plus existing selected values; list/selected/combined contexts retain occurrences and original arms',
        'empty_selection': 'completed SELECT no-match becomes object:null with selection_status:no-match; no claim of native absence, a conversion/cache prerequisite, or complete query exhaustion',
        'execution': 'Gateway-owned SELECT take2 overflow sentinel then bounded grouped exact-ID reads; existing identity/scope/metadata/result/deadline/continuation ceilings',
        'native_return_context_syntax_required': False, 'atomic_snapshot': False,
        'identity': 'actual canonical selected GUID and exact read facts; empty names and opaque paths retained; no inferred immediate parent/owner relationship',
        'mutation_authority': False, 'source': source}

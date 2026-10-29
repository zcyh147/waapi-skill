"""Closed, property-bound randomizer read terminals, never modifier identity."""
import json
import math
from pathlib import Path

from .schema_inventory import load_definition_graph


RANDOMIZER_OUTPUTS = {
    'enabled': ('Enabled', 'enabled'),
    'min-offset': ('Min', 'min_offset'),
    'max-offset': ('Max', 'max_offset'),
}


def randomizer_terminal(candidate, terminal, error):
    if candidate.get('kind') != 'property':
        raise error('A randomizer argument requires a freshly discovered property', code='RELATED_QUERY_FIELD_KIND')
    native, output = RANDOMIZER_OUTPUTS[terminal]
    return f'randomizer({json.dumps(candidate["name"], ensure_ascii=False)}).@{native}', output


def validate_randomizer_value(output, value, error):
    valid = (type(value) is bool if output == 'enabled' else
        type(value) in {int, float} and (type(value) is int or math.isfinite(value)))
    if not valid:
        raise error('Randomizer returned an incompatible scalar value; no default is substituted',
            code='RELATED_QUERY_RANDOMIZER_VALUE')


def randomizer_contract(version):
    source = json.loads((Path(__file__).resolve().parents[1] / 'references/semantic' / version /
        'query-randomizer-sources.json').read_text(encoding='utf-8'))
    if (source['version'], source['wwise_build']) != (version, load_definition_graph(version).wwise_build):
        raise ValueError('Randomizer source does not match selected definitions')
    return {'option': '--include-related <owner-path>... randomizer MEANING <terminal>',
        'hop': 'randomizer MEANING', 'terminals': list(RANDOMIZER_OUTPUTS), 'metadata_reads': True,
        'argument': 'one freshly selected actual owner property; Gateway quotes its metadata token, including a safe namespace:property token',
        'scope': 'root, singleton, list and selected/combined member contexts; randomizer is the terminal context, not a reference or arbitrary function hop',
        'result': 'related.randomizers.<actual-property-token> with enabled Boolean and min_offset/max_offset finite numbers in the selected property units; unknown units stay unknown',
        'presence': 'omitted native fields remain unavailable_fields; disabled false and zero offsets are actual values; present incompatible values stop',
        'modifier_identity_required': False, 'mutation_authority': False,
        'value_authority': 'actual native values required; no defaults, enabled state or randomizer support inferred from omission',
        'source': source}

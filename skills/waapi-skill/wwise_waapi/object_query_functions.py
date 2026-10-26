"""Finite source-bound scalar query terminals; no callable-name input."""
import json
import hashlib
import re
from pathlib import Path

from .schema_inventory import load_definition_graph

FIELD_STATUSES = {
    'linked': 'isLinked',
    'overridable': 'isOverridable',
    'override-source': 'isSourceOfOverride',
    'present': 'hasProperty',
}


def field_status_terminal(candidate, status, error):
    if candidate.get('kind') not in {'property', 'reference', 'list'}:
        raise error('Field status requires an exact property, reference or List', code='RELATED_QUERY_FIELD_KIND')
    return f'{FIELD_STATUSES[status]}({json.dumps(candidate["name"], ensure_ascii=False)})', status


def validate_function_value(kind, value, error):
    if value is None:
        return
    valid = type(value) is str if kind == 'source' else type(value) is bool
    if not valid:
        raise error('Query function returned an incompatible scalar; no false/default is substituted',
            code='RELATED_QUERY_FUNCTION_VALUE')


def documented_status_field(version, meaning, class_id):
    from .documented_list_fields import load_catalog
    catalog = load_catalog(version)
    rows = [row for row in catalog['classes'] if row['class_id'] == class_id]
    if not rows:
        return None
    choices = [field for field in rows[0]['lists'] if meaning.casefold() in
        {field['name'].casefold(), field['display_name'].casefold()}]
    if len(choices) != 1:
        return None
    return {'name': choices[0]['name'], 'kind': 'list',
        'authority': {'catalog_sha256': catalog['catalog_sha256'], 'class_id': class_id,
            'source_sha256': rows[0]['source_sha256'], 'declaration': choices[0]}}


def function_source(version):
    graph = load_definition_graph(version)
    root = Path(__file__).resolve().parents[1]
    raw = (root / 'references/semantic' / version / 'query-function-sources.json').read_bytes()
    if len(raw) > 128 * 1024:
        raise ValueError('Query function source exceeds its byte ceiling')
    source = json.loads(raw)
    if (source['version'], source['wwise_build']) != (version, graph.wwise_build) or source['definitions_sha256'] != hashlib.sha256(
            (root / 'resources/manifest' / version / 'definitions.json').read_bytes()).hexdigest():
        raise ValueError('Query function source does not match selected definitions')
    return source


def known_presence_field(version, meaning):
    """Exact concept authority is independent of target applicability."""
    from .object_query_outputs import available_query_outputs
    source = function_source(version)
    for business in ('volume-db', 'pitch-cents', 'output-bus'):
        if meaning.casefold() == business:
            meaning = available_query_outputs(version)[business][0].lstrip('@')
    candidates = {}
    for kind, tokens in source['known_fields'].items():
        for token in tokens:
            if meaning.casefold() == token.casefold() and re.fullmatch(r'[A-Za-z0-9_]+', token):
                candidates.setdefault(token, {'name': token, 'kind': kind,
                    'authority': {'known_field_source': source['known_field_source']}})
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def curve_choices(version):
    from .builders.common import ManifestSchemaLoader
    from .core_business_contracts import _CURVE_KINDS
    schema = ManifestSchemaLoader().schema_for('ak.wwise.core.object.setAttenuationCurve', version)
    native = schema['argsSchema']['properties']['curveType']['enum']
    if set(native) - set(_CURVE_KINDS.values()):
        raise ValueError('Unmapped reflected attenuation curve role')
    return {role: token for role, token in _CURVE_KINDS.items() if token in native}


def curve_argument(version, role, class_id, error):
    from .documented_list_fields import load_catalog
    catalog = load_catalog(version)
    owner = next((row for row in catalog['classes'] if row['class_id'] == class_id and row['name'] == 'Attenuation'), None)
    if owner is None:
        raise error('curve-selection requires the actual Attenuation class', code='RELATED_QUERY_FUNCTION_SCOPE')
    return {'name': role, 'kind': 'curve-role', 'native_token': curve_choices(version)[role], 'authority': {'catalog_sha256': catalog['catalog_sha256'],
        'class_id': class_id, 'source_sha256': owner['source_sha256']}}


def curve_selection_terminal(candidate, role, error):
    # The role was checked at offline parse time against the matching SET schema.
    return f'curveToUse({json.dumps(candidate["native_token"])})', 'source'


def function_contract(version):
    available = version == '2025.1'
    from .builders.common import ManifestSchemaLoader
    values = ManifestSchemaLoader().schema_for('ak.wwise.core.object.setAttenuationCurve', version)['argsSchema']['properties']['use']['enum']
    source = function_source(version) if available else None
    return {'available': available, 'supported_versions': ['2025.1'],
        'boundary': 'older matching WAQL source does not document these functions; native absence is not established',
        'field_status': {'grammar': 'field-status MEANING linked|overridable|override-source|present',
            'argument_kinds': ['property', 'reference', 'list'], 'terminals': list(FIELD_STATUSES),
            'argument': 'fresh exact owner property/reference selection or documented List at its actual class; present additionally admits exact source-certified field concepts independent of target applicability',
            'presence': 'actual native Boolean; fuzzy/unknown no-match cannot produce false; explicit null stays null and omission remains unavailable_fields',
            'meanings': {'linked': 'field is linked', 'overridable': 'field has an override property',
                'override-source': 'object is the source of override', 'present': 'object has this exact field'},
            'known_business_meanings': ['volume-db', 'pitch-cents', 'output-bus']},
        'curve_selection': {'grammar': 'curve-selection CURVE_ROLE', 'owner': 'actual Attenuation class',
            'roles': list(curve_choices(version)) if available else [], 'values': values if available else [],
            'semantics': 'actual curve-use source string; explicit null stays null, omission stays unavailable, and unknown strings stay lossless; SET curve-type spelling, no GET DualShelf/DSF equivalence'},
        'scope': 'root, singleton, selected/combined member; existing query/metadata/result/deadline/page ceilings',
        'mutation_authority': False, 'source': source}

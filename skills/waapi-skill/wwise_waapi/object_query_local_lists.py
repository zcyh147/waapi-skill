"""Two fixed local object-list contexts; exact class/source admission, no raw tokens."""
import math

from .documented_list_fields import load_catalog
from .schema_inventory import load_definition_graph

LOCAL_LISTS = {
    'local-rtpcs': {'native': '@RTPC', 'field': 'RTPC', 'first': '2022.1'},
    'local-effect-slots': {'native': '@Effects', 'field': 'Effects', 'first': '2023.1'},
}


def descriptor(native):
    return next((value for value in LOCAL_LISTS.values() if value['native'] == native), None)


def certify_local_list(version, native, class_id, error):
    selected = descriptor(native)
    if selected is None: return None
    catalog = load_catalog(version)
    owner = next((row for row in catalog['classes'] if type(class_id) is int and row['class_id'] == class_id), None)
    field = next((row for row in owner['lists'] if row['name'] == selected['field']), None) if owner else None
    if version < selected['first'] or field is None or not field['element_classes'] or field['unresolved_element_types']:
        raise error('The exact owner class has no complete matching source for this local List; empty membership is not established',
            code='RELATED_QUERY_LOCAL_LIST_SOURCE', details={'native': native, 'class_id': class_id, 'version': version,
                'native_absence_proven': False})
    return {'version': version, 'catalog_sha256': catalog['catalog_sha256'], 'class_id': class_id,
        'source_member': owner['source_member'], 'source_sha256': owner['source_sha256'], 'declaration': field}


def validate_local_member(row, owner_id, source, error):
    allowed = {item['class_id'] for item in source['declaration']['element_classes']}
    owner = row.get('owner')
    if (type(row.get('classId')) is not int or row['classId'] not in allowed or not isinstance(owner, dict)
            or not isinstance(owner.get('id'), str) or owner['id'].upper() != owner_id.upper()):
        raise error('A local List member lost its declared class or exact native owner', code='RELATED_QUERY_LOCAL_LIST_MEMBER')


def local_list_contract(version):
    catalog = load_catalog(version)
    return {'contexts': {name: {**value, 'available': version >= value['first']} for name, value in LOCAL_LISTS.items()},
        'membership': 'directly stored local List only; no ordinary/override equivalence claim',
        'scope': 'fresh exact owner classId certified by matching per-class documented List source; unknown class never borrows a base by type name',
        'source': {'version': version, 'catalog_sha256': catalog['catalog_sha256'], **catalog['source']},
        'identity': 'canonical native GUID plus declared element class/exact owner; empty names valid, order and duplicate occurrences retained separately',
        'unresolved': 'missing class/source is not empty membership or native absence',
        'remaining': ['2021 RTPC inspection semantics', '2021/2022 fixed Effect0-3 inspection uses existing scalar/reference paths',
            'modern Marker transport identity and older Inner Marker representation', 'precise source-proven plugin-to-base bridges']}


def validate_curve_points(version, value, error):
    # Native null/omission retain the ordinary query presence contract. Actual
    # non-null point arrays follow the matching read schema, not mutation caps.
    if value is None: return
    definitions = load_definition_graph(version).documents['waapi_definitions.json']['definitions']
    schema = definitions['pointsDefinition']['items']['properties']['shape']
    shapes = schema.get('enum') or definitions[schema['$ref'].rsplit('/', 1)[-1]]['enum']
    if (not isinstance(value, list) or any(not isinstance(point, dict) or set(point) != {'x', 'y', 'shape'}
            or point['shape'] not in shapes or any(type(point[key]) not in (int, float)
                or type(point[key]) is float and not math.isfinite(point[key]) for key in ('x', 'y')) for point in value)):
        raise error('Related Curve points must retain ordered typed x/y/shape values from the matching schema',
            code='RELATED_QUERY_CURVE_POINTS')

"""Exact source-certified constructor inputs, separate from setter nullability.

MetadataSlot's owned Metadata placement is certified by matching WObjects/SDK
and the retained 9143 constructor rejection. This is not a generic notNull rule.
"""
from copy import deepcopy
from collections.abc import Mapping
from uuid import UUID

from .documented_list_fields import load_catalog

VERSION = '2025.1'
CLASS_ID = 5570560
FIELD = 'Metadata'
SOURCE = {
    'version': VERSION, 'build': '2025.1.7.9143', 'class_id': CLASS_ID,
    'collection': 'Metadata', 'required_references': [FIELD],
    'wobjects_member': 'Authoring/Data/WObjects/WObjects.xml',
    'wobjects_sha256': '3b363c24b7ffa032d7efc12f36023cd944b8f53323af33fcbe738c2193918454',
    'sdk_member': 'wwiseobject_metadataslot.html',
    'sdk_sha256': '16e40547f33b6c8972be454943821c488bcddc9bbbc8af3d2f9f1dcf19a2f4a2',
    'constructor_packet_sha256': '329be379a076778155b1374d2f81c5bede6b867cfd8daff9fa3460b93b96f7af',
    'constructor_evidence': 'r84-named-list-2a3037eb-2025-r2:MetadataSlot.Metadata:ak.wwise.invalid_reference',
}


def authority(spec, *, version=VERSION):
    if (version != VERSION or spec.get('class_id') != CLASS_ID
            or spec.get('collection') != 'Metadata' or spec.get('existing_target') or spec.get('preexisting_id')):
        return None
    catalog = load_catalog(version)
    row, = [row for row in catalog['classes'] if row['class_id'] == CLASS_ID]
    if (row['name'] != 'MetadataSlot' or row['source_member'] != SOURCE['sdk_member']
            or row['source_sha256'] != SOURCE['sdk_sha256'] or FIELD not in row['scalar_references']):
        raise ValueError('Required constructor input lost its matching class/placement source')
    return {**deepcopy(SOURCE), 'catalog_sha256': catalog['catalog_sha256']}


def public_requirements(proof):
    """Project the business requirement without exposing developer provenance."""
    if not isinstance(proof, Mapping):
        return None
    return {"version": proof["version"], "class_name": "MetadataSlot",
        "class_id": proof["class_id"], "collection": proof["collection"],
        "required_references": list(proof["required_references"])}


def complete(spec):
    proof = authority(spec)
    if proof is None:
        return 'constructor_inputs' not in spec
    if spec.get('constructor_inputs') != proof:
        return False
    for name in proof['required_references']:
        fields = [row for row in spec.get('references', []) if row.get('name') == name]
        if len(fields) != 1:
            return False
        field = fields[0]
        if 'target_request_path' in field:
            continue  # A constructor stage must additionally prove this dependency.
        try:
            if not isinstance(field.get('target_id'), str) or UUID(field['target_id']).int == 0:
                return False
        except ValueError:
            return False
    return True


def observe(specs, identities, *, read):
    """Keep required scalar references intact before each dependent write."""
    for spec in specs:
        proof = authority(spec)
        identity = identities.get(spec.get('request_path'))
        if proof is None or identity is None:
            continue
        if not complete(spec):
            raise ValueError('Required constructor input proof is incomplete')
        fields = proof['required_references']
        result = read('ak.wwise.core.object.get', {'from': {'id': [identity['id']]}},
            {'return': ['id', *('@' + name for name in fields)]})
        rows = result.get('return')
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get('id')).upper() != identity['id'].upper():
            raise ValueError('Required constructor reference owner is not one exact GUID')
        for name in fields:
            field, = [row for row in spec['references'] if row['name'] == name]
            actual = rows[0].get('@' + name)
            actual = actual.get('id') if isinstance(actual, dict) else actual
            if not isinstance(actual, str) or actual.upper() != field.get('target_id', '').upper():
                raise ValueError('Required constructor reference changed before dependent write')

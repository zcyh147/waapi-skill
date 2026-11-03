"""Pinned field-kind evidence, separate from native restrictions and values.

An omitted native kind is not general permission to treat a token as a
reference. Only an exact documented class/field and fresh object identity can
use this proof. It supplies no target-domain or activation semantics.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from .canonical import canonical_sha256

_SOURCE = Path(__file__).resolve().parents[1] / "resources/metadata/reference-kind-sources.json"
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


def certify(info, *, version, object_id, read):
    """Attach source authority without changing any native metadata member."""
    if info.name != "Target" or info.type not in (None, "") or info.restriction.get("type") == "reference":
        return info
    # A restriction describing a scalar contradicts this source, rather than
    # becoming an empty native reference restriction through normalization.
    if info.restriction and info.restriction.get("type") != "reference":
        return info
    source = json.loads(_SOURCE.read_text(encoding="utf-8"))
    if (source.get("contract") != "waapi-skill.reference-kind-source/v1"
            or canonical_sha256({k: v for k, v in source.items() if k != "sha256"}) != source.get("sha256")):
        raise ValueError("Reference-kind source seal changed")
    lane = source["versions"].get(version)
    if lane is None:
        return info
    catalog_bytes = (_SOURCE.parent / version / "object-types.json").read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != lane["types_sha256"]:
        raise ValueError("Reference-kind class source changed")
    if not isinstance(object_id, str) or not _GUID.fullmatch(object_id):
        return info
    from .builders.metadata import parse_property_and_reference_names_result
    names = parse_property_and_reference_names_result(read(
        "ak.wwise.core.object.getPropertyAndReferenceNames", {"object": object_id}, {}))
    if [item.name for item in names].count(info.name) != 1:
        return info
    result = read("ak.wwise.core.object.get", {"from": {"id": [object_id]}},
        {"return": ["id", "type", "classId", "ActionType"]})
    rows = result.get("return") if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get("id"), str) or rows[0]["id"].casefold() != object_id.casefold()):
        return info
    row = rows[0]
    catalog = json.loads(catalog_bytes)["types"]
    matches = [field for field in source["fields"]
        if field["field"] == info.name and field["native_type"] == row.get("type")
        and type(row.get("classId")) is int and field["class_id"] == row["classId"]]
    if len(matches) != 1 or type(row.get("ActionType")) is not int:
        return info
    selected = matches[0]
    if len([item for item in catalog if item["name"] == selected["native_type"]
            and item["classId"] == selected["class_id"]]) != 1:
        raise ValueError("Reference-kind class contradicts its pinned catalog")
    proof = {"kind": "documented-reference-kind", "version": version, "object_id": object_id,
        "field": info.name, "value_kind": "reference", "source_sha256": source["sha256"],
        "sdk": lane["sdk"], "identity": {key: row[key] for key in ("id", "type", "classId", "ActionType")},
        "restrictions_authority": "native_getPropertyInfo", "native_metadata_sha256": canonical_sha256(info.raw)}
    return replace(info, reference_kind_evidence=proof)


def certify_class(info, *, version, class_id, read):
    """Use the same exact SDK field-kind authority for a selected Action class."""
    if (class_id != 327696 or info.name != 'Target' or info.type not in (None, '')
            or info.restriction):
        return info
    source = json.loads(_SOURCE.read_text(encoding='utf-8'))
    if canonical_sha256({k: v for k, v in source.items() if k != 'sha256'}) != source.get('sha256'):
        raise ValueError('Reference-kind source seal changed')
    lane = source['versions'].get(version)
    if lane is None: return info
    raw = (_SOURCE.parent / version / 'object-types.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != lane['types_sha256']:
        raise ValueError('Reference-kind class source changed')
    matches = [row for row in json.loads(raw)['types'] if row['classId'] == class_id and row['name'] == 'Action']
    if len(matches) != 1: raise ValueError('Action reference-kind class contradicts pinned catalog')
    from .builders.metadata import parse_get_types_result
    current = [row for row in parse_get_types_result(read('ak.wwise.core.object.getTypes', {}, {}))
        if row.class_id == class_id]
    if len(current) != 1 or current[0].name != 'Action': return info
    proof = {'kind': 'documented-class-reference-kind', 'version': version, 'class_id': class_id,
        'field': info.name, 'value_kind': 'reference', 'source_sha256': source['sha256'], 'sdk': lane['sdk'],
        'restrictions_authority': 'native_getPropertyInfo', 'native_metadata_sha256': canonical_sha256(info.raw)}
    return replace(info, reference_kind_evidence=proof)


def certify_query_candidate(candidate, *, version, object_id, read, class_id=None):
    """Certify the one legacy read field after exact-object metadata fallback.

    This proof never enters mutation discovery and does not supply restrictions.
    Its original bounded observations are revalidated before returning a read.
    """
    if (version != '2021.1' or candidate.get('name') != 'ControlInput'
            or candidate.get('kind') != 'unknown' or not isinstance(object_id, str)
            or not _GUID.fullmatch(object_id)):
        return candidate
    metadata = candidate['metadata']
    if metadata.get('type') not in (None, '') or metadata.get('restriction'):
        return candidate
    source = json.loads(_SOURCE.read_text(encoding='utf-8'))
    if (source.get('contract') != 'waapi-skill.reference-kind-source/v1'
            or canonical_sha256({k: v for k, v in source.items() if k != 'sha256'}) != source.get('sha256')):
        raise ValueError('Reference-kind source seal changed')
    selected, = source['query_read_fields']
    catalog_bytes = (_SOURCE.parent / version / 'object-types.json').read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != source['versions'][version]['types_sha256']:
        raise ValueError('Reference-kind class source changed')
    catalog = json.loads(catalog_bytes)['types']
    if (selected['version'], selected['native_type'], selected['class_id'], selected['field']) != ('2021.1', 'RTPC', 1441808, 'ControlInput'):
        raise ValueError('Legacy read field source changed')
    if len([row for row in catalog if row['name'] == selected['registered_name'] and row['classId'] == selected['class_id']]) != 1:
        raise ValueError('Legacy read class contradicts its pinned catalog')
    observations = []
    def observe(uri, args, options):
        result = read(uri, args, options)
        observations.append({'api': uri, 'args': args, 'options': options, 'result_sha256': canonical_sha256(result)})
        return result
    from .builders.metadata import parse_property_and_reference_names_result, parse_get_property_info_result
    names = parse_property_and_reference_names_result(observe(
        'ak.wwise.core.object.getPropertyAndReferenceNames', {'object': object_id}, {}))
    if [item.name for item in names].count('ControlInput') != 1:
        return candidate
    current = parse_get_property_info_result(observe('ak.wwise.core.object.getPropertyInfo',
        {'object': object_id, 'property': 'ControlInput'}, {}), require_identity=False)
    if canonical_sha256(current.raw) != canonical_sha256(metadata):
        return candidate
    result = observe('ak.wwise.core.object.get', {'from': {'id': [object_id]}}, {'return': ['id', 'type', 'classId']})
    rows = result.get('return') if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get('id'), str) or rows[0]['id'].upper() != object_id.upper()
            or rows[0].get('type') != 'RTPC'
            or type(rows[0].get('classId')) is not int or rows[0]['classId'] != 1441808
            or class_id is not None and (type(class_id) is not int or class_id != rows[0]['classId'])):
        return candidate
    proof = {'kind': 'documented-query-reference-kind', 'version': version, 'object_id': object_id,
        'field': 'ControlInput', 'source_sha256': source['sha256'], 'identity': rows[0],
        'observations': observations, 'restrictions_authority': 'native_getPropertyInfo', 'mutation_authority': False}
    return {**candidate, 'kind': 'reference', 'kind_evidence': proof}


def revalidate_query_read_proofs(proofs, *, read):
    """No cached kind proof can replace current inventory, metadata or identity."""
    seen = set()
    for proof in proofs:
        for observation in proof['observations']:
            key = canonical_sha256(observation)
            if key in seen:
                continue
            seen.add(key)
            actual = read(observation['api'], observation['args'], observation['options'])
            if canonical_sha256(actual) != observation['result_sha256']:
                raise ValueError('Legacy read field inventory, metadata or exact object identity changed; restart the original read')


def query_read_kind_contract(version):
    """Disclose the exact read exception; other unknown kinds stay unresolved."""
    source = json.loads(_SOURCE.read_text(encoding='utf-8'))
    if canonical_sha256({k: v for k, v in source.items() if k != 'sha256'}) != source.get('sha256'):
        raise ValueError('Reference-kind source seal changed')
    return {'fields': [{key: row[key] for key in ('class_id', 'registered_name', 'native_type', 'field')}
            for row in source['query_read_fields'] if row['version'] == version],
        'source_sha256': source['sha256'], 'root_scope': 'exact current object GUID',
        'related_scope': 'actual canonical endpoint GUID and class; exact-object metadata after class fallback',
        'revalidation': 'current field inventory, native metadata and exact identity before returning the read',
        'target_restrictions_authority': 'native metadata only', 'mutation_authority': False}

"""Source-certified new anonymous objects use the owned List's population mode."""
import json
from pathlib import Path

from .canonical import canonical_sha256

SOURCE = Path(__file__).resolve().parents[1] / 'resources/metadata/owned-list-mode-sources.json'
RULE = {'append': 'add_new_objects_keep_existing', 'replaceAll': 'remove_all_existing_then_add_new',
        'duplicate_restrictions': 'per_list_restrictions_remain_authoritative'}


def authority(version):
    from .documented_list_fields import load_catalog
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    if (source.get('contract') != 'waapi-skill.owned-list-mode-source/v1' or source.get('rule') != RULE
            or source.get('sha256') != canonical_sha256({key: value for key, value in source.items() if key != 'sha256'})):
        raise ValueError('Owned List population source changed')
    lane = source['versions'][version]
    sdk = load_catalog(version)['source']
    if lane['build'] != sdk['build'] or lane['archive_sha256'] != sdk['archive_sha256']:
        raise ValueError('Owned List population source differs from the class/List source')
    return {'kind': source['contract'], 'version': version, 'source_sha256': source['sha256'],
            'sdk': lane, 'rule': RULE}


def certify(spec, *, collection, list_mode, version):
    """Keep exact class/owner/prerequisite proofs; never select an old blank name."""
    effect = collection == 'Effects' and spec.get('class_id') == 5505040 and spec.get('canonical_type') == 'EffectSlot'
    marker = (collection == 'Markers' and spec.get('class_id') == 5373968
              and isinstance(spec.get('manual_marker'), dict))
    if (version not in {'2023.1', '2024.1', '2025.1'} or not spec.get('anonymous_list_member')
            or list_mode not in {'append', 'replaceAll'} or not (effect or marker or
                collection == 'Paths' and spec.get('media_pool_database') and spec.get('class_id') == 5898240)):
        return False
    spec['anonymous_list_mode_source'] = authority(version)
    return True

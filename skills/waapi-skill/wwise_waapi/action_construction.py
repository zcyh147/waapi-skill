"""Pinned unnamed Action constructor facts, distinct from native execution proof."""
import json
from pathlib import Path
from .canonical import canonical_sha256

SOURCE = Path(__file__).resolve().parents[1] / 'resources/metadata/action-constructor-sources.json'


def authority(version):
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    if (source.get('contract') != 'waapi-skill.action-constructor-source/v1'
            or source.get('sha256') != canonical_sha256({k: v for k, v in source.items() if k != 'sha256'})
            or (source['class_id'], source['native_type'], source['parent_type']) != (327696, 'Action', 'Event')):
        raise ValueError('Action constructor source changed')
    lane = source['versions'][version]
    example = lane['request']['children'][0]
    action = example['children'][0]
    returned = lane['result']['children'][0]['children'][0]
    if (example['type'] != 'Event' or action['type'] != 'Action' or action['name'] != '' or returned['name'] != ''
            or action['@ActionType'] != 1 or not isinstance(action['@Target'], str)):
        raise ValueError('Action constructor source has no exact unnamed Event child')
    return {'version': version, 'build': lane['build'], 'class_id': 327696, 'type': 'Action',
        'parent_type': 'Event', 'name': '', 'source_sha256': source['sha256'],
        'sdk_member': lane['sdk_member'], 'sdk_sha256': lane['sdk_sha256'], 'native_effect': 'not_claimed'}


def declaration_contract():
    return {'status': 'supported_targeted_fail_mode', 'parent': 'exact_Event_parent_handle',
        'kind': 'selected_Action_Type_Handle', 'name': 'local_declaration_label; Gateway_emits_source_certified_empty_native_name',
        'required_class_fields': ['ActionType', 'Target'],
        'values': 'selected_live_ActionType_enum_value_and_bound_existing_Target_Object_Handle',
        'verification': 'fresh_actual_GUID_class_Event_parent_empty_name_and_requested_fields; derived_path_observed_not_synthesized',
        'remaining_same_parent_work': ['non_fail_collision_semantics', 'multiple_new_Actions_under_one_Event_in_one_Preview', 'targetless_Action_constructors'],
        'native_execution': 'not_claimed_from_SDK_example', 'tracking_issue': 180}

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
    fields = lane['class_source']['fields']
    if fields['Target'][2:5] != ['Reference', '', 'None'] or fields['ActionType'][2] != 'int16':
        raise ValueError('Action class field source changed')
    return {'version': version, 'build': lane['build'], 'class_id': 327696, 'type': 'Action',
        'parent_type': 'Event', 'name': '', 'source_sha256': source['sha256'],
        'sdk_member': lane['sdk_member'], 'sdk_sha256': lane['sdk_sha256'],
        'class_source': {key: lane['class_source'][key] for key in ('sdk_member', 'sdk_sha256')}, 'native_effect': 'not_claimed'}


def declaration_contract():
    return {'status': 'supported', 'parent': 'exact_Event_parent_handle',
        'kind': 'selected_Action_Type_Handle', 'name': 'local_declaration_label; Gateway_emits_source_certified_empty_native_name',
        'required_class_fields': ['ActionType', 'Target'],
        'values': 'selected_live_ActionType_enum_value_and_bound_existing_Target_Object_Handle_or_explicit_null',
        'occurrences': 'multiple_new_Actions_bind_by_exact_ID_full_requested_fields_and_complete_Event_population; no_association_order_authority',
        'verification': 'fresh_or_sealed_unique_merge_GUID_class_Event_parent_empty_name_and_requested_fields; derived_path_observed_not_synthesized',
        'name_conflict': {'fail': 'fresh_creation', 'rename': 'append_fresh_occurrences_and_preserve_existing_Event_roster',
            'merge': 'one_unique_empty_name_collision_and_one_declaration; exact_existing_object_metadata; preserve_existing_notes',
            'replace': 'one_unique_empty_name_collision_and_one_declaration; exact_old_subtree_absence_and_fresh_GUID; object.create_requires_reviewed_replacement_owner'},
        'ambiguity': 'multiple_empty_name_collisions_refused; use_exact_existing_Action_GUID_for_configuration',
        'planned_Event_parent': 'one_Action_under_proven_fresh_Event_is_creation; nested_merged_existing_Event_uses_complete_exact_roster',
        'remaining_same_parent_work': ['multiple_Actions_under_planned_Event_with_merge_replace_require_separate_Event_Preview_or_rename'],
        'native_execution': 'not_claimed_from_SDK_example', 'tracking_issue': 180}

"""Closed business contracts for named object graphs and curve operations."""

from __future__ import annotations

from .documented_list_fields import discovery_contract as documented_list_discovery_contract, manual_marker_profile
from .effect_render_conditions import CLEAR_SUFFIX_OBSERVATIONS

from typing import Any

from .business_declarations import SUPPORTED_BUSINESS_KINDS, SUPPORTED_WWISE_VERSIONS
from .business_fields import ACTION_DURATION_FIELDS, ACTION_DURATION_SEMANTICS, OBJECT_BUSINESS_FIELD_TYPES
from .metadata_condition_contracts import existing_field_condition_contract
from .operation_object import OBJECT_SET_REFERENCE_ARRAY_VERSIONS, RTPC_POINT_SHAPES


OBJECT_GRAPH_BUSINESS_CONTRACT = "waapi-skill.object-graph-business/v1"
OBJECT_GRAPH_BUSINESS_OPERATIONS = (
    "object.create",
    "object.createPlugin",
    "object.set",
    "object.setRTPC",
)

OBJECT_CREATE_BUSINESS_VALUE_TYPES = {
    name: value_type
    for name, value_type in OBJECT_BUSINESS_FIELD_TYPES.items()
    if name not in ACTION_DURATION_FIELDS
}

from .action_construction import declaration_contract
ACTION_CREATION_BOUNDARY = declaration_contract()

RTPC_PROPERTY_CARDINALITY = {
    "metadata_source": "selected_owner_property_supports.rtpc",
    "Exclusive": "at_most_one_RTPC_per_property_regardless_of_ControlInput",
    "Additive": "distinct_ControlInput_pairs_remain_allowed_within_the_list_bounds",
    "Multiplicative": "distinct_ControlInput_pairs_remain_allowed_within_the_list_bounds",
    "same_pair_update": "retain_the_exact_existing_RTPC_GUID",
    "different_input_append": "cannot_remove_an_unrequested_existing_Exclusive_pair",
    "replace_all": "explicit_complete_list_replacement_still_obeys_each_Exclusive_property_limit",
}


_SUPPORTED_VERSIONS = {
    "object.create": SUPPORTED_WWISE_VERSIONS,
    "object.createPlugin": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "object.set": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "object.setRTPC": ("2022.1", "2023.1", "2024.1", "2025.1"),
}


def _sound_semantics(operation):
    return {
        "sound_voice": {"native_class": "Sound", "initial_fields": {"IsVoice": True}, "empty_container": True},
        "explicit_flag_conflict": "reject_before_dispatch",
        "generic_Sound_Type_Handle": "explicit_class_fields_remain_available",
        "verification": "actual_Boolean_IsVoice_and_bound_fields_identity_and_metadata",
        "language_and_media": ("use_audio_import_for_localized_media" if operation == "object.create"
            else "requested_media_language_independently_verified;new_empty_Voice_language_is_optional_validated_Gateway_context_not_emitted_on_Sound_no_native_language_effect;existing_merge_language_effect_unresolved;declared_Source_plugins_have_separate_language_and_closed_childset_verification"),
    }


def object_graph_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the operation-local business interface for one exact lane."""

    if operation not in OBJECT_GRAPH_BUSINESS_OPERATIONS:
        raise ValueError("unsupported object graph business operation")
    if version not in _SUPPORTED_VERSIONS[operation]:
        raise ValueError("unsupported Wwise version for object graph operation")
    if operation == "object.createPlugin":
        return {
            "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
            "operation": operation,
            "version": version,
            "input_mode": "business_declaration",
            "start": {
                "subcommand": "draft-start",
                "gateway_argv": ["draft-start", operation],
                "copy_exactly": True,
                "append_arguments": "forbidden",
            },
            "binding": {
                "target": "bound_object_handle",
                "plugin_type": "live_discovered_type_handle",
                "properties_and_references": "class_scoped_field_handles",
                "placement_targets": {
                    "owner": "compatible audio object; never a Work Unit",
                    "shareset": "Effect: WorkUnit or fresh source-proven Folder under Effects; Sink/Metadata: matching WorkUnit under Audio Devices/Metadata",
                },
            },
            "type_discovery": {
                "subcommand": "draft-discover-types",
                "roles": ["source", "effect", "sink", "metadata"],
                "result": "copy_one_gateway_returned_type_handle",
            },
            "declaration": {
                "subcommand": "draft-declare-existing",
                "required_fields": [
                    "object_handle",
                    "plugin_role",
                    "plugin_name",
                    "plugin_type_handle",
                ],
                "optional_fields": [
                    "plugin_placement",
                    "field_values",
                    "language",
                    "notes",
                    "platform",
                ],
                "placement": {
                    "owner": "attach a local Source or Effect, or create Metadata in the version-correct List of a compatible audio object",
                    "shareset": "create an independent Effect, AudioDevice, or Metadata child in its matching hierarchy",
                    "default": "owner",
                },
                "field_value_types": {
                    "plugin_placement": "string",
                    "language": "string",
                    "notes": "string",
                    "platform": "string",
                    "plugin_name": "string",
                    "plugin_role": "string",
                    "plugin_type_handle": "string",
                },
            },
            "gateway_derivations": [
                "plugin_class_id",
                "versioned_plugin_topology",
                "metadata_property_and_reference_tokens",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
            "plugin_kind_routes": {
                "SourcePlugin": {"role": "source", "placement": ["owner"], "native_type": "Source"},
                "EffectPlugin": {"role": "effect", "placement": ["owner", "shareset"], "native_type": "Effect"},
                "SinkPlugin": {"role": "sink", "placement": ["shareset"], "native_type": "AudioDevice", "hierarchy": "Audio Devices"},
                "MetadataPlugin": {"role": "metadata", "placement": ["shareset"], "native_type": "Metadata", "hierarchy": "Metadata",
                    "owner_local_placement": {"status": "supported" if version != "2021.1" else "unresolved_native_mapping",
                        "supported_versions": ["2022.1", "2023.1", "2024.1", "2025.1"], "collection": "Metadata",
                        "member": "MetadataSlot" if version == "2025.1" else "selected_class_Metadata",
                        "behavior": "append_one_fresh_instance_preserve_complete_ordered_membership",
                        "intrinsic_ownership": "exact_owned_slot_and_custom_reference" if version == "2025.1" else "observed_key_presence_and_value_only",
                        "verification": "class_fields_and_exact_placement" if version == "2025.1" else "direct_metadata_list_and_plugin_fields; business_state_verified=false",
                        "tracking_issue": 179}},
                "ConversionPlugin": {"discovery_role": "conversion", "native_type": "Conversion",
                    "attachment": {"request_schema_command": ["request-schema", "ak.wwise.core.audio.setConversionPlugin"],
                        "supported_versions": ["2024.1", "2025.1"]},
                    "older_version_alternatives": {"status": "unresolved_native_mapping", "tracking_issue": 179}},
            },
            "version_boundaries": {"2021.1": {"creation": "missing_implementation", "tracking_issue": 179,
                "reason": "The older create schema lacks classId and object.set is absent; alternative native construction still requires matching evidence."}},
            "legacy_shallow_composer_public": False,
            "safety": {
                "immutable_preview": True,
                "single_execute": True,
                "type_revalidation": "exact_live_catalog_row",
                "field_revalidation": "exact_class_metadata",
            },
        }
    if operation == "object.setRTPC":
        return {
            "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
            "operation": operation,
            "version": version,
            "input_mode": "business_declaration",
            "start": {
                "subcommand": "draft-start",
                "gateway_argv": ["draft-start", operation],
                "copy_exactly": True,
                "append_arguments": "forbidden",
            },
            "binding": {
                "object": "bound_object_handle",
                "control_input": "bound_object_handle_or_new_owned_Modulator",
                "property": "live_discovered_field_handle",
            },
            "field_discovery": {
                "subcommand": "draft-discover-fields",
                "input": "user_facing_property_meaning",
                "result": "copy_one_gateway_returned_property_handle",
                "native_property_token": "forbidden",
            },
            "declaration": {
                "subcommand": "draft-declare-rtpc",
                "required_fields": [
                    "object_handle",
                    "field_handle",
                    "curve_points",
                ],
                "optional_fields": ["mode", "notes"],
                "control_input_choice": ["control_input_handle", "new_control_input"],
                "new_control_input": {
                    "kind": "selected_Modulator_Type_Handle",
                    "required": ["kind_handle", "name"],
                    "optional": ["notes", "class_Field_Handle_scalar_assignments"],
                    "types": ["ModulatorLfo", "ModulatorEnvelope", "ModulatorTime"],
                    "pair_semantics": "always_add_fresh_pair;_never_replace_an_unrequested_existing_input",
                    "platform_intent": "preserve_one_exact_class_Field_Handle_platform_including_generic_None",
                    "mixed_platform_workflow": ["create_and_verify_input_with_one_class_Field_Handle_scope",
                        "bind_the_verified_input_exact_GUID_in_a_new_object.setProperty_Draft",
                        "discover_its_property_Field_Handle_for_each_requested_platform",
                        "separately_preview_authorize_execute_and_verify_each_platform_change"],
                    "same_parent_issue": 180,
                    "time_axis": {"unit": "seconds", "effective_duration": "explicit_Duration_class_Field_Handle_value_or_fresh_typed_class_default",
                        "interim_admission": "all_explicit_or_preserved_Curve_X_values_within_0_and_effective_Duration",
                        "missing_default_repair": "discover_Duration_with_selected_Time_Type_Handle_and_supply_new_control_input_field_value",
                        "normalization": "never_change_points_or_Duration", "native_domain_complete": False,
                        "unresolved": ["outside_duration_native_semantics", "partial_duration_endpoints", "native_field_order"]},
                    "version_boundary": {"2021.1": "constructor_introduced_2022.1", "scope": "this_property_bound_RTPC_owned_ControlInput_constructor_only"},
                    "old_custom_replacement": "explicit_removal_intent;_exact_old_GUID_absence_is_a_required_postcondition_not_an_assumed_native_guarantee",
                },
                "mode_values": ["add-only", "add-or-update"],
                "point_fields": ["x", "y", "shape"],
                "shape_semantics": "outgoing_segment",
                "terminal_shape": "gateway_normalized_to_Linear",
                "point_shapes": [
                    "Constant",
                    "Linear",
                    "Log3",
                    "Log2",
                    "Log1",
                    "InvertedSCurve",
                    "SCurve",
                    "Exp1",
                    "Exp2",
                    "Exp3",
                ],
                "point_limit": 256,
                "property_cardinality": dict(RTPC_PROPERTY_CARDINALITY),
            },
            "gateway_derivations": [
                "native_property_token",
                "control_input_identity",
                "rtpc_list_row",
                "add_or_replace_mode",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
            "legacy_shallow_composer_public": False,
            "safety": {
                "immutable_preview": True,
                "single_execute": True,
                "object_revalidation": "exact_guid_name_type_path",
                "field_revalidation": "exact_object_metadata",
            },
        }
    if operation == "object.set":
        return {
            "activation_prerequisites": existing_field_condition_contract(version),
            "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
            "operation": operation,
            "version": version,
            "input_mode": "business_declaration",
            "sound_semantics": _sound_semantics(operation),
            "start": {
                "subcommand": "draft-start",
                "gateway_argv": ["draft-start", operation],
                "copy_exactly": True,
                "append_arguments": "forbidden",
            },
            "binding": {
                "existing_targets": "bound_object_handles",
                "new_descendants": "bound_or_planned_parent_handles",
                "fields": "live_discovered_field_handles",
                "long_tail_types": "live_discovered_type_handles",
            },
            "field_discovery": {
                "subcommand": "draft-discover-fields",
                "input": "one_to_eight_distinct_user_facing_meanings",
                "scope": "one_bound_target_or_declared_semantic_kind",
                "documented_lists": documented_list_discovery_contract(),
                "result": (
                    "one_ordered_meaning_result_with_bounded_candidates_per_input"
                ),
                "native_property_or_reference_token": "forbidden",
            },
            "declaration": {
                "subcommands": [
                    "draft-declare-existing",
                    "draft-declare-existing-batch",
                    "draft-declare-new",
                    "draft-declare-rtpc",
                    "draft-declare-field-change",
                ],
                "existing_batch": {
                    "maximum_rows": 8,
                    "field_input": "fixed_business_fields_or_selected_scoped_field_handles",
                    "business_quantities": {
                        "action_time": {
                            "accepted_units": ["seconds", "milliseconds"],
                            "canonical_unit": "seconds",
                        }
                    },
                    "metadata_revalidation": "each_exact_bound_object",
                    "atomic_revision": True,
                },
                "existing_required_fields": ["object_handle"],
                "new_required_fields": ["parent_handle", "name", "kind"],
                "source_certified_inner_names": {
                    "initial_profile": {"version": "2025.1", "owner_classes": ["AuxBus", "BlendContainer", "Bus", "MusicPlaylistContainer", "MusicSegment", "MusicSwitchContainer", "MusicTrack", "PropertyContainer", "RandomSequenceContainer", "Sound", "SwitchContainer"], "collection": "Metadata", "class": "MetadataSlot"},
                    "additional_profiles": [{"version": "2025.1", "owner_class": "RandomSequenceContainer",
                        "collection": "Playlist", "class": "PlaylistSlot", "native_name": "Gateway_owned_empty_string",
                        "initial_reference": "selected_existing_exact_direct_child",
                        "scope": "new_member_with_inline_PlaylistObject; append_or_replaceAll; older_list_representations_remain_separate"}],
                    "name_meaning": "declaration_label_not_intrinsic_Wwise_name",
                    "observed_native_name": "", "identity": "actual_GUID_class_owner_ordered_collection",
                    "other_profiles": "require_their_own_source_and_representation_proof"},
                "anonymous_list_member": {
                    "subcommand": "draft-declare-new", "omit": ["name"],
                    "requires": ["selected_profile_Type_Handle", "source_proven_owner_List_Field_Handle"],
                    "versions": ["2023.1", "2024.1", "2025.1"],
                    "profiles": {"effect_slot": {"class": "EffectSlot", "collection": "Effects"},
                        "manual_marker": manual_marker_profile(version)},
                    "native_name": "Gateway_owned_empty_string",
                    "on_name_conflict": {"supported": ["fail"],
                        "pending_source_native_proof": ["rename", "merge", "replace"],
                        "pending_behavior": "reject_before_dispatch_without_selecting_old_blank_name_members_or_changing_policy"},
                    "result_binding": "independent_ordered_owner_membership_then_exact_GUID_class_owner_and_values",
                    "render_conditions": {
                        "applies_to": "EffectSlot",
                        "explicit_false_before_later_true": "reject_before_preview_or_write",
                        "omitted_predecessors": "derive_visible_true_from_actual_state_or_fresh_class_default",
                        "verification": "complete_stored_slot_state_not_rendered_audio",
                        "bypass": "preserve_stored_flags; Bypass takes precedence during processing",
                        "clearing_before_retained_true": ("derive_visible_false_for_retained_successors; exact_complete_chain_verification"
                            if version in CLEAR_SUFFIX_OBSERVATIONS else "pending_native_suffix_observation; reject_before_write"),
                    },
                },
                "graph_plugin": {"types": {"effect": "effect_Type_Handle", "source": "source_Type_Handle"},
                    "plugin_placement": {"effect": ["shareset", "owner"], "source": ["owner"]},
                    "shareset_parent": "bound_Effects_WorkUnit_or_fresh_source_proven_Folder",
                    "source_parent": "bound_existing_Sound_or_Voice_or_planned_result_handle; ordinary_child_not_Effect_slot",
                    "source_language": "separate_from_Voice_construction_context; exact_selected_Project_language_on_actual_Boolean_Voice_owner",
                    "existing_source_owner": {"target": "exact_bound_Sound_GUID_and_class",
                        "Voice_flag": "actual_live_Boolean_preserved; change_in_separate_verified_Preview",
                        "retained_children": "complete_GUID_childset_plus_observed_plugin_and_file_Source_class_notes_language_original_path_and_live_discovered_fields_preserved",
                        "retained_field_reads": "all_discovered_fields_in_Gateway_bounded_projection_pages; existing_result_bytes_and_deadline_limits_apply",
                        "explicit_locale": "nonSFX_Project_locale_requires_actual_Voice; explicit_SFX_is_not_an_admitted_declaration",
                        "name_conflict": "fail; other_Source_collision_modes_remain_unresolved"},
                    "source_verification": "actual_graph_GUID_class_parent_owner_fields_and_requested_language; closed_declared_childset",
                    "native_class_id": "Gateway_owned_from_Type_Handle"},
                "optional_fields": [
                    "field_values",
                    "language",
                    "list_behavior",
                    "loop",
                    "max_instances",
                    "media_files",
                    "name_conflict",
                    "new_name",
                    "notes",
                    "object_list",
                    "output_bus",
                    "ignore_parent_instance_limit",
                    "platform",
                    "volume_db",
                    "fade_time_ms",
                    "delay_ms",
                ],
                "field_value_types": {
                    **OBJECT_BUSINESS_FIELD_TYPES,
                    "language": "string",
                    "list_behavior": "string",
                    "name_conflict": "string",
                    "new_name": "string",
                    "object_list": "string",
                    "platform": "string",
                    "plugin_placement": "string",
                },
                "field_semantics": ACTION_DURATION_SEMANTICS,
                "existing_target_choices": {
                    "new_name": "exact_requested_name_of_bound_existing_GUID;_known_collisions_reject_before_preview;_no_creation_suffix_substitution",
                    "name_conflict": ["fail", "rename", "merge", "replace"],
                    "scope": "new_children_and_list_members_of_this_existing_target",
                    "overrides": "batch_name_conflict",
                },
            },
            "rtpc_declaration": {
                "subcommand": "draft-declare-rtpc", "supported_versions": ["2022.1", "2023.1", "2024.1", "2025.1"],
                "required_fields": ["declaration_id", "object_handle", "field_handle", "curve_points"],
                "optional_fields": ["mode", "notes"],
                "owner": "bound_existing_object_or_same_Draft_new_result_handle",
                "property": "object_scoped_Field_Handle_for_existing_owner;_matching_class_Field_Handle_for_planned_owner",
                "control_input": "exactly_one_bound_existing_input_or_new_owned_Modulator",
                "new_control_input": object_graph_business_contract_data("object.setRTPC", version)["declaration"]["new_control_input"],
                "identity": "unique_property_and_ControlInput_pair;_never_empty_name_matching",
                "property_cardinality": dict(RTPC_PROPERTY_CARDINALITY),
                "mode_values": ["add-only", "add-or-update"], "default_mode": "add-or-update",
                "existing_pair_update": "exact_actual_RTPC_GUID_row_in_same_object_set;_no_name_merge",
                "replace_all": "complete_selected_list_contains_only_declared_pairs;_old_pairs_are_removed",
                "result": "stable_same_Draft_result_handle_bound_to_actual_GUID_class_owner_and_pair",
                "equivalent_new_outcomes": "full_input_platform_fields_and_derived_fields_RTPC_notes_Curve_points_match_independently;_identical_undistinguished_outcomes_use_canonical_GUID_occurrence_bijection_without_native_order_assumption",
                "points": {"fields": ["x", "y", "shape"], "limit": 256, "shape_semantics": "outgoing_segment",
                    "point_shapes": sorted(RTPC_POINT_SHAPES), "terminal_shape": "gateway_normalized_to_Linear"},
                "native_fragments": "forbidden", "unrequested_state": "preserve_other_lists_children_fields_and_append_mode_old_curves",
                "2021.1": {"status": "version_boundary", "reason": "constructor_introduced_2022.1", "scope": "this_property_bound_constructor_only"},
            },
            "object_list_declaration": {
                "member_fields": {
                    "object_list": "selected_List_Field_Handle_or_exact_source_proven_alias_for_this_owner",
                    "list_behavior": ["append", "replace-all"],
                },
                "recursive_placement": "bound_or_planned_parent_handles;_ordinary_children_and_owned_lists_may_nest",
                "planned_binding": "stable_declaration_result_handle_and_normalized_owner_path_plus_exact_class_source;_actual_GUID_class_owner_membership_verified_after_write",
                "list_behavior_scope": "one_inherited_existing_target_row;_conflicting_descendant_choices_are_rejected",
                "clear_subcommand": "draft-clear-object-list",
                "clear_fields": [
                    "declaration_id",
                    "object_handle",
                    "list_name",
                ],
                "clear_owner": "bound_object_handle_or_matching_planned_declaration_result_handle",
                "native_at_prefix": "forbidden",
                "empty_clear_requires": "replace-all",
            },
            "media_declaration": {
                "subcommand": "draft-add-media",
                "source_forms": ["media-file", "inline-wav"],
                "optional_fields": [
                    "add_to_source_control",
                    "kind",
                    "language",
                    "originals_subfolder",
                ],
                "add_to_source_control": {"type": "boolean", "scope": "one_import_group_for_this_declaration",
                    "omitted": "preserve_native_default", "explicit_false": "preserved", "explicit_true": "preserved",
                    "repeated_explicit_choices": "must_agree; conflicts_reject_atomically"},
                "exact_user_artifacts": ["media_file", "inline_wav"],
                "native_import_fragment_input": "forbidden",
                "supported_versions": ["2023.1", "2024.1", "2025.1"],
            },
            "settings": {
                "name_conflict": ["fail", "rename", "merge", "replace"],
                "list_behavior": ["append", "replace-all"],
                "voice_source_completion": {"choices": ["separate-previews", "atomic-required"],
                    "configure": "draft-business-configure --voice-source-completion separate-previews",
                    "scope": "one_new_fail_mode_Voice_root_and_one_localized_Source; complete_declarations_preserved",
                    "previews": "Voice_creation_then_Source_on_verified_existing_Voice; separate_authorization",
                    "default_atomic_boundary": {"host": "wwise-console", "build": "2025.1.7.9143",
                        "Source_class_id": 6684674, "shape": "one_new_fail_mode_Voice_and_one_explicitly_localized_Source",
                        "view": "no_explicit_platform_on_batch_target_Voice_Source_or_plugin; default_source_control",
                        "outcome": "prewrite_staged_choice; atomic_request_unresolved",
                        "other_hosts_builds_classes_views_graphs": "admitted_without_atomic_classification"},
                    "older_atomic_native_behavior": "unobserved; no_native_absence_claim",
                    "continuation": "continue-voice-source VERIFIED_CREATION_TRANSACTION; no_recipe_or_target_input",
                    "failure": "Voice_created_Source_incomplete; never_repeat_creation_or_indeterminate_Source"},
                "platform": "exact_user_requested_platform;_per_target_platform_overrides",
                "add_to_source_control": "boolean",
            },
            "gateway_derivations": [
                "target_rows",
                "recursive_children",
                "native_object_types",
                "metadata_tokens",
                "platform_views",
                "dependency_order",
                "batch_layout",
                "object_list_rows",
                "per_target_list_mode",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
            "legacy_shallow_composer_public": False,
            "reference_values": {
                "forms": ["bound_object_handle", "same_Draft_new_declaration_result_handle", "null_to_clear_reference"] +
                         (["json_array_of_bound_object_handles"] if version in OBJECT_SET_REFERENCE_ARRAY_VERSIONS else []),
                **({"maximum_array_members": 32} if version in OBJECT_SET_REFERENCE_ARRAY_VERSIONS else {}),
                "inline_curve": {
                    "input": {"curve_points": "array_of_x_y_shape_points"},
                    "maximum_points": 256,
                    "native_type": "Gateway_owned_exact_live_Curve_class",
                    "applicability": "fresh_explicit_Curve_type_allowance;_custom_target_classifier_requirements_must_be_proven",
                    "verification": "exact_owner_field_points_and_independent_Curve_class_readback",
                },
                "replace_owned_control_input": {
                    "subcommand": "draft-declare-field-change",
                    "target": "exact_existing_RTPC_and_its_ControlInput_Reference_Field_Handle",
                    "required": ["object_handle", "field_handle", "new_control_input_kind_Type_Handle", "new_control_input_name"],
                    "optional": ["new_control_input_notes", "new_control_input_class_Field_Handle_scalar_values"],
                    "current_input": "native_proven_shared_target_or_exact_owned_Modulator_with_selected_RTPC_owner",
                    "preservation": "same_RTPC_GUID_owner_PropertyName_Curve_GUID_points_notes_complete_owning_list_and_old_shared_fields;_previous_custom_must_be_absent",
                    "new_input": object_graph_business_contract_data("object.setRTPC", version)["declaration"]["new_control_input"],
                    "native_fragments": "forbidden",
                },
                "array_requires": "documented_List_Field_Handle_for_exact_owner_class_and_version; scalar_Reference_metadata_is_insufficient",
                "verification": "ordered_canonical_GUIDs_or_native_null_from_exact_field_readback",
                "planned_target": "Gateway_derives_native_path_from_exact_root_and_normalized_graph_occurrence;_verify_actual_result_GUID_and_independent_class_parent_readback",
                "planned_target_rename": "Gateway_discloses_a_proved_unoccupied_candidate_name_for_referenced_rename_collisions;_native_rename_policy_preserved_and_collision_state_revalidated",
            },
            "creation_boundaries": {"Action": dict(ACTION_CREATION_BOUNDARY)},
            "safety": {
                "immutable_preview": True,
                "single_execute": True,
                "object_revalidation": "exact_guid_name_type_path",
                "field_revalidation": "exact_scope_metadata_platform",
            },
        }
    if operation != "object.create":
        raise ValueError("object graph business operation is not migrated yet")
    return {
        "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "sound_semantics": _sound_semantics(operation),
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "declaration": {
            "subcommand": "draft-declare-new",
            "target_fields": ["parent_handle", "name", "kind"],
            "stable_fields": {**OBJECT_CREATE_BUSINESS_VALUE_TYPES, "object_list": "string"},
            "field_semantics": {},
            "field_value_types": {**OBJECT_CREATE_BUSINESS_VALUE_TYPES, "object_list": "string"},
            "object_list": {
                "scope": "new_root_only",
                "input": "selected_List_Field_Handle_or_exact_source_proven_alias_for_this_owner",
                "proof": "exact_version_class_source_and_actual_ordered_membership_and_owner",
                "placement": "owned_list_instead_of_hierarchy_child",
                "descendants": "ordinary_recursive_children",
            },
            "bound_field_handle_container": "field_values",
            "reference_values": {
                "forms": ["bound_object_handle", "same_Draft_new_declaration_result_handle", "null_to_clear_reference"],
                "native_value_boundary": "pinned_propertyValue_is_scalar_or_null;_array_inline_and_curve_values_require_an_available_object.set_lane",
                "verification": "ordered_canonical_GUIDs_or_native_null_from_exact_field_readback",
                "planned_target": "Gateway_derives_native_path_from_exact_root_and_normalized_graph_occurrence;_verify_actual_result_GUID_and_independent_class_parent_readback",
                "planned_target_rename": "Gateway_discloses_a_proved_unoccupied_candidate_name_for_referenced_rename_collisions;_native_rename_policy_preserved_and_collision_state_revalidated",
            },
            "semantic_kinds": list(SUPPORTED_BUSINESS_KINDS),
            "planned_parent": "copy_previous_declaration_result_handle",
        },
        "settings": {
            "name_conflict": ["fail", "rename", "merge", "replace"],
            "merge_existing_same_name_root": (
                "bind_exact_existing_root_direct_parent_then_declare_root_name_"
                "once_with_merge"
            ),
            "replace_owner_handle": "required_only_for_explicit_replace",
            "platform": "exact_user_requested_platform",
            "add_to_source_control": "boolean",
        },
        "type_discovery": {
            "subcommand": "draft-discover-types",
            "input": "user_facing_meaning",
            "roles": ["object"],
            "result": "copy_one_gateway_returned_type_handle",
            "native_type_or_class_id_input": "forbidden_unless_exact_user_artifact",
        },
        "gateway_derivations": [
            "native_object_type",
            "recursive_object_tree",
            "canonical_parent_identity",
            "property_tokens",
            "dependency_order",
            "native_request",
            "preview_change_intent",
            "continuation",
        ],
        "legacy_shallow_composer_public": False,
        "creation_boundaries": {"Action": dict(ACTION_CREATION_BOUNDARY)},
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
        },
    }


__all__ = [
    "OBJECT_GRAPH_BUSINESS_CONTRACT",
    "OBJECT_GRAPH_BUSINESS_OPERATIONS",
    "OBJECT_CREATE_BUSINESS_VALUE_TYPES",
    "object_graph_business_contract_data",
]

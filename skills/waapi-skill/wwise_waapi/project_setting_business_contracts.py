"""Closed contracts for high-level project-setting Core mutations."""

from __future__ import annotations

from typing import Any

from .selection_guidance import selection_guidance_for_uri


PROJECT_SETTING_BUSINESS_CONTRACT = "waapi-skill.project-setting-business/v1"
GAME_PARAMETER_SET_RANGE_URI = "ak.wwise.core.gameParameter.setRange"
SOUND_SET_ACTIVE_SOURCE_URI = "ak.wwise.core.sound.setActiveSource"

_CONTRACTS: dict[str, dict[str, Any]] = {
    SOUND_SET_ACTIVE_SOURCE_URI: {
        "versions": ("2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("sound", "source"),
        "required_fields": ("sound_handle", "source_handle"),
        "optional_fields": ("platform_name",),
        "field_types": {
            "sound_handle": "bound_sound_handle",
            "source_handle": "bound_sound_source_handle",
            "platform_name": "platform_name",
        },
    },
    GAME_PARAMETER_SET_RANGE_URI: {
        "versions": ("2024.1", "2025.1"),
        "roles": ("game_parameter",),
        "required_fields": (
            "game_parameter_handle",
            "minimum",
            "maximum",
            "curve_update_outcome",
        ),
        "optional_fields": (),
        "field_types": {
            "game_parameter_handle": "bound_game_parameter_handle",
            "minimum": "finite_number",
            "maximum": "finite_number",
            "curve_update_outcome": "range_curve_update_outcome",
        },
    },
}
_INTENTS = {
    SOUND_SET_ACTIVE_SOURCE_URI: (
        "Select which AudioFileSource or Source-plugin child is active in a Sound platform view using existing "
        "source linkage; linked selection may affect other linked platforms and this operation does not unlink."
    ),
    GAME_PARAMETER_SET_RANGE_URI: (
        "Change one existing Game Parameter minimum and maximum and choose how dependent "
        "curves respond; does not create a parameter or set its default InitialValue."
    ),
}


def active_source_linkage_disclosure() -> dict[str, Any]:
    """Describe the setter's unchanged scope without inventing observed link state."""
    return {
        "selection": "uses_existing_source_linkage",
        "changes_linkage": False,
        "linkage_observed": False,
        "platform_isolation_implied": False,
        "may_affect_other_linked_platforms": True,
    }


def active_source_native_limitations(version: str) -> list[dict[str, Any]]:
    """Keep observed native kind rejection distinct from unproved alternatives."""
    build = {"2022.1": "2022.1.19.8584", "2023.1": "2023.1.19.8928"}.get(version)
    if build is None:
        return []
    return [{
        "source_type_name": "Wwise Tone Generator",
        "source_class_id": 6684674,
        "admission": "rejected_before_preview_in_this_version",
        "observed_native_build": build,
        "observed_request_scope": "Console_current_default_platform_view",
        "observed_native_error": "The object is not a source.",
        "other_plugin_classes": "not_classified_by_this_observation",
        "alternative_status": "required_unresolved_under_#181",
        "next_step": (
            "Keep the requested Tone selection pending under #181 until a version-correct "
            "alternative is proved; do not retry this setter or substitute another source."
        ),
    }]


def project_setting_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def project_setting_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported project-setting business operation") from exc


def project_setting_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "api": operation,
            "intent": _INTENTS[operation],
            "supported_versions": list(project_setting_business_versions(operation)),
        }
        for operation in sorted(_CONTRACTS)
    )


def project_setting_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported project-setting business operation") from exc
    if version not in row["versions"]:
        raise ValueError("project-setting operation is unavailable in this version")
    role_fields = []
    for role in row["roles"]:
        field = {
            "sound": "sound_handle",
            "source": "source_handle",
            "game_parameter": "game_parameter_handle",
        }[role]
        role_fields.append(
            {"role": role, "field": field, "cardinality": "exactly_one"}
        )
    return {
        "contract": PROJECT_SETTING_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": "draft_mutation",
        **({"source_linkage": active_source_linkage_disclosure(),
             "native_source_limitations": active_source_native_limitations(version)}
           if operation == SOUND_SET_ACTIVE_SOURCE_URI else {}),
        **({"selection_guidance": dict(selection_guidance_for_uri(operation))}
           if operation == GAME_PARAMETER_SET_RANGE_URI else {}),
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {
            "roles": list(row["roles"]),
            "role_fields": role_fields,
            "role_required": True,
            "identity": "live_bound_object_handle",
            "validation": "exact_guid_name_type_path_and_relationship",
        },
        "declaration": {
            "subcommand": "draft-declare-project-setting-plan",
            "required_fields": list(row["required_fields"]),
            "optional_fields": list(row["optional_fields"]),
            "field_types": dict(row["field_types"]),
        },
        "gateway_derivations": [
            "exact_object_identities",
            "object_type_and_relationship_validation",
            "native_curve_update_enum",
            "native_request",
            "request_revision",
            "preview",
            "continuation",
        ],
        "legacy_typed_call_public": False,
        "safety": {
            "object_revalidation": "exact_guid_name_type_path",
            "result_bound": True,
            "native_request_input": "forbidden",
        },
    }


__all__ = [
    "active_source_linkage_disclosure",
    "active_source_native_limitations",
    "GAME_PARAMETER_SET_RANGE_URI",
    "PROJECT_SETTING_BUSINESS_CONTRACT",
    "SOUND_SET_ACTIVE_SOURCE_URI",
    "project_setting_business_catalog_rows",
    "project_setting_business_contract_data",
    "project_setting_business_operations",
    "project_setting_business_versions",
]

"""Closed business contracts for reviewed generic Core routes."""

from __future__ import annotations

from typing import Any


CORE_BUSINESS_CONTRACT = "waapi-skill.core-business/v1"

_CONTRACTS: dict[str, dict[str, Any]] = {
    "ak.wwise.core.object.setAttenuationCurve": {
        "versions": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("attenuation",),
        "required_fields": ("attenuation_handle", "curve_kind", "curve_source", "points"),
        "optional_fields": ("platform_name",),
        "field_types": {
            "attenuation_handle": "bound_object_handle",
            "curve_kind": "attenuation_curve_kind",
            "curve_source": "attenuation_curve_source",
            "points": "attenuation_curve_points",
            "platform_name": "platform_name",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.object.setRandomizer": {
        "versions": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("object",),
        "required_fields": ("object_handle", "field_handle"),
        "optional_fields": ("enabled", "minimum_offset", "maximum_offset", "platform_name"),
        "field_types": {
            "object_handle": "bound_object_handle",
            "field_handle": "bound_field_handle",
            "enabled": "boolean",
            "minimum_offset": "finite_number_lte_zero",
            "maximum_offset": "finite_number_gte_zero",
            "platform_name": "platform_name",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.switchContainer.getAssignments": {
        "versions": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("switch_container",),
        "required_fields": ("switch_container_handle",),
        "optional_fields": (),
        "field_types": {"switch_container_handle": "bound_object_handle"},
        "execution_shape": "bounded_read",
    },
    "ak.wwise.core.object.diff": {
        "versions": ("2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("source", "target"),
        "required_fields": ("source_handle", "target_handle"),
        "optional_fields": (),
        "field_types": {
            "source_handle": "bound_object_handle",
            "target_handle": "bound_object_handle",
        },
        "execution_shape": "bounded_read",
    },
    "ak.wwise.core.object.pasteProperties": {
        "versions": ("2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("source", "target"),
        "required_fields": ("source_handle", "target_handles"),
        "optional_fields": ("include_field_handles", "exclude_field_handles", "list_mode"),
        "field_types": {
            "source_handle": "bound_object_handle",
            "target_handles": "bound_object_handle_list",
            "include_field_handles": "bound_field_handle_list",
            "exclude_field_handles": "bound_field_handle_list",
            "list_mode": "paste_list_mode",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.audio.mute": {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("object",),
        "required_fields": ("object_handles", "muted"),
        "optional_fields": (),
        "field_types": {
            "object_handles": "bound_object_handle_list",
            "muted": "boolean",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.audio.solo": {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("object",),
        "required_fields": ("object_handles", "soloed"),
        "optional_fields": (),
        "field_types": {
            "object_handles": "bound_object_handle_list",
            "soloed": "boolean",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.object.isLinked": {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("object",),
        "required_fields": ("object_handle", "field_handle", "platform_name"),
        "optional_fields": (),
        "field_types": {
            "object_handle": "bound_object_handle",
            "field_handle": "bound_field_handle",
            "platform_name": "platform_name",
        },
        "execution_shape": "bounded_read",
    },
    "ak.wwise.core.object.setStateGroups": {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("object", "state_group"),
        "required_fields": ("object_handle", "state_group_handles"),
        "optional_fields": (),
        "field_types": {
            "object_handle": "bound_object_handle",
            "state_group_handles": "bound_object_handle_list",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.object.setStateProperties": {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": ("object",),
        "required_fields": ("object_handle", "field_handles"),
        "optional_fields": (),
        "field_types": {
            "object_handle": "bound_object_handle",
            "field_handles": "bound_field_handle_list",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.project.save": {
        "versions": ("2023.1", "2024.1", "2025.1"),
        "roles": (),
        "required_fields": (),
        "optional_fields": ("auto_check_out",),
        "field_types": {"auto_check_out": "boolean"},
        "field_semantics": {
            "auto_check_out": {
                "intent_binding": "include_when_user_explicitly_allows_or_forbids_auto_checkout",
                "omitted_effect": "wwise_native_default_true",
                "true_effect": "automatically_checkout_affected_work_units_and_project",
                "false_effect": "do_not_automatically_checkout",
            }
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.audio.convert": {
        "versions": ("2024.1", "2025.1"),
        "roles": ("audio_object",),
        "required_fields": ("audio_object_handles", "platform_names", "languages", "io_root"),
        "optional_fields": (),
        "field_types": {
            "audio_object_handles": "bound_object_handle_list",
            "platform_names": "platform_name_list",
            "languages": "language_name_list",
            "io_root": "exact_user_io_root",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.audio.setConversionPlugin": {
        "versions": ("2024.1", "2025.1"),
        "roles": ("conversion",),
        "required_fields": ("conversion_handle", "platform_name", "plugin_name"),
        "optional_fields": (),
        "field_types": {
            "conversion_handle": "bound_object_handle",
            "platform_name": "platform_name",
            "plugin_name": "installed_conversion_plugin_name",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.blendContainer.addAssignment": {
        "versions": ("2024.1", "2025.1"),
        "roles": ("blend_track", "child"),
        "required_fields": ("blend_track_handle", "child_handle"),
        "optional_fields": ("insertion_index", "edges"),
        "field_types": {
            "blend_track_handle": "bound_object_handle",
            "child_handle": "bound_object_handle",
            "insertion_index": "nonnegative_integer",
            "edges": "blend_assignment_edges",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.blendContainer.addTrack": {
        "versions": ("2024.1", "2025.1"),
        "roles": ("blend_container",),
        "required_fields": ("blend_container_handle", "track_name"),
        "optional_fields": (),
        "field_types": {
            "blend_container_handle": "bound_object_handle",
            "track_name": "wwise_object_name",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.blendContainer.getAssignments": {
        "versions": ("2024.1", "2025.1"),
        "roles": ("blend_track",),
        "required_fields": ("blend_track_handle",),
        "optional_fields": (),
        "field_types": {"blend_track_handle": "bound_object_handle"},
        "execution_shape": "bounded_read",
    },
    "ak.wwise.core.blendContainer.removeAssignment": {
        "versions": ("2024.1", "2025.1"),
        "roles": ("blend_track", "child"),
        "required_fields": ("blend_track_handle", "child_handle"),
        "optional_fields": (),
        "field_types": {
            "blend_track_handle": "bound_object_handle",
            "child_handle": "bound_object_handle",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.workUnit.load": {
        "versions": ("2025.1",),
        "roles": ("work_unit",),
        "required_fields": ("work_unit_handle",),
        "optional_fields": (),
        "field_types": {"work_unit_handle": "bound_object_handle"},
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.workUnit.unload": {
        "versions": ("2025.1",),
        "roles": ("work_unit",),
        "required_fields": ("work_unit_handle",),
        "optional_fields": (),
        "field_types": {"work_unit_handle": "bound_object_handle"},
        "execution_shape": "draft_mutation",
    },
}

_READ_DECLARATIONS: dict[str, dict[str, Any]] = {
    "ak.wwise.core.object.diff": {
        "required_fields": ("source_id", "target_id"),
        "field_types": {
            "source_id": "gateway_evidence_object_id",
            "target_id": "gateway_evidence_object_id",
        },
        "input_forms": {
            "source_id": {"flag": "--source-id", "repeatable": False},
            "target_id": {"flag": "--target-id", "repeatable": False},
        },
        "role_fields": {"source": "source_id", "target": "target_id"},
    },
    "ak.wwise.core.switchContainer.getAssignments": {
        "required_fields": ("object_id",),
        "field_types": {"object_id": "gateway_evidence_object_id"},
        "input_forms": {"object_id": {"flag": "--object-id", "repeatable": False}},
        "role_fields": {"switch_container": "object_id"},
    },
    "ak.wwise.core.blendContainer.getAssignments": {
        "required_fields": ("object_id",),
        "field_types": {"object_id": "gateway_evidence_object_id"},
        "input_forms": {"object_id": {"flag": "--object-id", "repeatable": False}},
        "role_fields": {"blend_track": "object_id"},
    },
    "ak.wwise.core.object.isLinked": {
        "required_fields": ("object_id", "field_meaning", "platform_name"),
        "field_types": {
            "object_id": "gateway_evidence_object_id",
            "field_meaning": "user_facing_field_meaning",
            "platform_name": "platform_name",
        },
        "input_forms": {
            "object_id": {"flag": "--object-id", "repeatable": False},
            "field_meaning": {"flag": "--field-meaning", "repeatable": False},
            "platform_name": {"flag": "--platform-name", "repeatable": False},
        },
        "role_fields": {"object": "object_id"},
    },
}

_CATALOG_INTENTS = {
    "ak.wwise.core.object.setAttenuationCurve": "set one attenuation curve",
    "ak.wwise.core.object.setRandomizer": "configure one property randomizer",
    "ak.wwise.core.switchContainer.getAssignments": "read Switch Container assignments",
    "ak.wwise.core.object.diff": "compare two Wwise objects",
    "ak.wwise.core.object.pasteProperties": "copy selected properties between objects",
    "ak.wwise.core.audio.mute": "mute or unmute authoring objects",
    "ak.wwise.core.audio.solo": "solo or unsolo authoring objects",
    "ak.wwise.core.object.isLinked": "inspect one platform-linked property",
    "ak.wwise.core.object.setStateGroups": "set an object's State Groups",
    "ak.wwise.core.object.setStateProperties": "set an object's State properties",
    "ak.wwise.core.project.save": "save the current Wwise project with optional source-control auto-checkout",
    "ak.wwise.core.audio.convert": "convert selected audio for platforms and languages",
    "ak.wwise.core.audio.setConversionPlugin": "select an installed Conversion plug-in",
    "ak.wwise.core.blendContainer.addAssignment": "assign a child to a Blend Track",
    "ak.wwise.core.blendContainer.addTrack": "add a Blend Track",
    "ak.wwise.core.blendContainer.getAssignments": "read Blend Track assignments",
    "ak.wwise.core.blendContainer.removeAssignment": "remove a Blend Track assignment",
    "ak.wwise.core.workUnit.load": "load one Work Unit",
    "ak.wwise.core.workUnit.unload": "unload one Work Unit",
}


def _mutation_input_form(field: str, value_type: str) -> dict[str, Any]:
    if value_type == "bound_object_handle":
        return {"flag": "--role", "repeatable": False, "arguments": [field, "HANDLE"]}
    if value_type == "bound_object_handle_list":
        return {"flag": "--role", "repeatable": True, "arguments": [field, "HANDLE"]}
    if value_type == "bound_field_handle":
        return {"flag": "--field", "repeatable": False, "arguments": [field, "HANDLE"]}
    if value_type == "bound_field_handle_list":
        return {"flag": "--field", "repeatable": True, "arguments": [field, "HANDLE"]}
    if value_type in {"platform_name_list", "language_name_list"}:
        return {"flag": "--item", "repeatable": True, "arguments": [field, "VALUE"]}
    if value_type == "attenuation_curve_points":
        return {"flag": "--curve-point", "repeatable": True, "arguments": ["X", "Y", "SHAPE"]}
    if value_type == "blend_assignment_edges":
        return {
            "flag": "--blend-edge",
            "repeatable": True,
            "arguments": ["EDGE_POSITION", "FADE_MODE", "FADE_POSITION_OR_NONE", "SHAPE"],
        }
    return {"flag": "--value", "repeatable": False, "arguments": [field, "VALUE"]}


def core_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def core_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported generic Core business operation") from exc


def core_business_draft_operations() -> frozenset[str]:
    return frozenset(
        operation
        for operation, row in _CONTRACTS.items()
        if row["execution_shape"] == "draft_mutation"
    )


def core_business_read_operations() -> frozenset[str]:
    return frozenset(
        operation
        for operation, row in _CONTRACTS.items()
        if row["execution_shape"] == "bounded_read"
    )


def core_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    """Expose every reviewed raw Core route for natural-intent discovery."""

    if set(_CATALOG_INTENTS) != set(_CONTRACTS):  # pragma: no cover - invariant
        raise ValueError("generic Core catalog intent coverage drifted")
    return tuple(
        {
            "api": operation,
            "intent": _CATALOG_INTENTS[operation],
            "supported_versions": list(_CONTRACTS[operation]["versions"]),
        }
        for operation in sorted(_CONTRACTS)
    )


def core_business_contract_data(operation: str, version: str) -> dict[str, Any]:
    """Return one URI-local declaration without reflected request mechanics."""

    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported generic Core business operation") from exc
    if version not in row["versions"]:
        raise ValueError("generic Core business operation is unavailable in this version")
    bounded_read = row["execution_shape"] == "bounded_read"
    read_declaration = _READ_DECLARATIONS.get(operation) if bounded_read else None
    public_field_types = (
        read_declaration["field_types"]
        if read_declaration is not None
        else row["field_types"]
    )
    public_required_fields = (
        read_declaration["required_fields"]
        if read_declaration is not None
        else row["required_fields"]
    )
    public_optional_fields = () if read_declaration is not None else row["optional_fields"]
    input_forms = (
        read_declaration["input_forms"]
        if read_declaration is not None
        else {
            name: _mutation_input_form(name, value_type)
            for name, value_type in row["field_types"].items()
        }
    )
    role_fields = []
    for role in row["roles"]:
        if read_declaration is not None:
            field = read_declaration["role_fields"][role]
        else:
            candidates = [
                name
                for name, value_type in row["field_types"].items()
                if name.startswith(f"{role}_")
                and value_type in {"bound_object_handle", "bound_object_handle_list"}
            ]
            if len(candidates) != 1:  # pragma: no cover - static contract invariant
                raise ValueError("generic Core role does not map to one business field")
            field = candidates[0]
        role_fields.append(
            {
                "role": role,
                "field": field,
                "cardinality": (
                    "one_or_more"
                    if public_field_types[field] == "bound_object_handle_list"
                    else "exactly_one"
                ),
            }
        )
    declaration = {
        "subcommand": "core-call" if bounded_read else "draft-declare-core-plan",
        "required_fields": list(public_required_fields),
        "optional_fields": list(public_optional_fields),
        "field_types": dict(public_field_types),
        "input_forms": dict(input_forms),
    }
    field_semantics = row.get("field_semantics")
    if field_semantics is not None:
        declaration["field_semantics"] = {
            field: dict(semantics)
            for field, semantics in field_semantics.items()
        }
    return {
        "contract": CORE_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": row["execution_shape"],
        "start": {
            "subcommand": "core-call" if bounded_read else "draft-start",
            (
                "gateway_argv_prefix" if bounded_read else "gateway_argv"
            ): ["core-call" if bounded_read else "draft-start", operation],
            "copy_exactly": True,
            "append_arguments": (
                "disclosed_business_fields_only" if bounded_read else "forbidden"
            ),
        },
        "binding": {
            "roles": list(row["roles"]),
            "role_fields": role_fields,
            "role_required": bool(row["roles"]),
            "identity": (
                "gateway_evidence_object_id"
                if bounded_read
                else "live_bound_object_handle"
            ),
            "validation": "exact_guid_name_type_path",
        },
        "declaration": declaration,
        "gateway_derivations": [
            "exact_object_identities",
            "native_request",
            "request_revision",
            "preview_or_bounded_read_lifecycle",
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
    "CORE_BUSINESS_CONTRACT",
    "core_business_contract_data",
    "core_business_catalog_rows",
    "core_business_draft_operations",
    "core_business_operations",
    "core_business_read_operations",
    "core_business_versions",
]

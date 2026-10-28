"""Closed business contracts for reviewed generic Core routes."""

from __future__ import annotations

from typing import Any

from .edit_history_contracts import HISTORY_VERSIONS, history_declaration


CORE_BUSINESS_CONTRACT = "waapi-skill.core-business/v1"

# Single compiler-owned mappings; public disclosures expose only business keys.
_CURVE_KINDS = {
    "volume-dry": "VolumeDryUsage",
    "volume-wet-game": "VolumeWetGameUsage",
    "volume-wet-user": "VolumeWetUserUsage",
    "low-pass-filter": "LowPassFilterUsage",
    "high-pass-filter": "HighPassFilterUsage",
    "high-shelf": "HighShelfUsage",
    "spread": "SpreadUsage",
    "focus": "FocusUsage",
    "obstruction-volume": "ObstructionVolumeUsage",
    "obstruction-high-pass": "ObstructionHPFUsage",
    "obstruction-low-pass": "ObstructionLPFUsage",
    "obstruction-high-shelf": "ObstructionHSFUsage",
    "occlusion-volume": "OcclusionVolumeUsage",
    "occlusion-high-pass": "OcclusionHPFUsage",
    "occlusion-low-pass": "OcclusionLPFUsage",
    "occlusion-high-shelf": "OcclusionHSFUsage",
    "diffraction-volume": "DiffractionVolumeUsage",
    "diffraction-high-pass": "DiffractionHPFUsage",
    "diffraction-low-pass": "DiffractionLPFUsage",
    "diffraction-high-shelf": "DiffractionHSFUsage",
    "transmission-volume": "TransmissionVolumeUsage",
    "transmission-high-pass": "TransmissionHPFUsage",
    "transmission-low-pass": "TransmissionLPFUsage",
    "transmission-high-shelf": "TransmissionHSFUsage",
}
_CURVE_SOURCES = {
    "none": "None",
    "custom": "Custom",
    "volume-dry": "UseVolumeDry",
    "project": "UseProject",
}
_CURVE_SHAPES = {
    "constant": "Constant",
    "linear": "Linear",
    "log-3": "Log3",
    "log-2": "Log2",
    "log-1": "Log1",
    "inverted-s-curve": "InvertedSCurve",
    "s-curve": "SCurve",
    "exp-1": "Exp1",
    "exp-2": "Exp2",
    "exp-3": "Exp3",
}
_PASTE_MODES = {
    "replace": "replaceEntire",
    "merge-replace": "addReplace",
    "merge-keep": "addKeep",
}
_FADE_MODES = {
    "none": "None",
    "manual": "Manual",
    "automatic": "Automatic",
}


MAX_CURVE_POINTS = 64

_CONTRACTS: dict[str, dict[str, Any]] = {
    "ak.wwise.core.object.setAttenuationCurve": {
        "versions": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
        "roles": ("attenuation",),
        "role_live_types": {"attenuation": "Attenuation"},
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
        "empty_collections": ("state_group_handles",),
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
        "empty_collections": ("field_handles",),
        "required_fields": ("object_handle", "field_handles"),
        "optional_fields": (),
        "field_types": {
            "object_handle": "bound_object_handle",
            "field_handles": "bound_field_handle_list",
        },
        "execution_shape": "draft_mutation",
    },
    "ak.wwise.core.project.save": {
        "versions": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
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
        "role_live_types": {"conversion": "Conversion"},
        "required_fields": ("conversion_handle", "platform_name", "plugin_type_handle"),
        "optional_fields": (),
        "field_types": {
            "conversion_handle": "bound_object_handle",
            "platform_name": "platform_name",
            "plugin_type_handle": "bound_type_handle",
        },
        "field_semantics": {"plugin_type_handle": {
            "discovery": "draft-discover-types --role conversion",
            "selection": "one installed Conversion class; its discovered name becomes the native codec name",
            "configuration": "no codec GUID is produced; configuration needs a separately chosen exact live codec identity and live object.setProperty Field Handles in a separate Preview",
            "property_reset": "prior codec properties may reset",
        }, "platform_name": {"selection": "exact unique live project platform; Gateway binds its GUID",
            "verification": "result_schema_checked", "business_state_verified": False,
            "unverified": ["actual codec replacement", "platform-to-codec GUID association",
                "other platform codec and field preservation"]}},
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
            "insertion_index": "integer_clamped_to_assignment_count",
            "edges": "blend_assignment_edges",
        },
        "field_semantics": {
            "insertion_index": {"input": "integer_including_negative", "omitted_effect": "append",
                                "effective_position": "clamp_to_zero_through_current_assignment_count",
                                "preview_authority": "fresh_complete_indexed_assignments"},
            "edges": {"effect_scope": "crossfade_GameParameter_only",
                      "verification_boundary": "applicability_and_effect_unproved; bounded_read_observation_only"},
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

for _history_uri, _history_versions in HISTORY_VERSIONS.items():
    _CONTRACTS[_history_uri] = {
        "versions": _history_versions, "roles": (), "required_fields": ("history_scope",),
        "optional_fields": ("expectation_receipt",), "field_types": {"history_scope": "latest_project_history_scope", "expectation_receipt": "owned_history_expectation_receipt"},
        "execution_shape": "draft_mutation",
    }


_CATALOG_INTENTS = {
    "ak.wwise.core.undo.undo": "undo the latest project history action with an owned state expectation",
    "ak.wwise.core.undo.redo": "redo the latest project history action with an owned state expectation",
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
    if value_type == "bound_type_handle":
        return {"flag": "--type", "repeatable": False, "arguments": [field, "HANDLE"]}
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


def core_business_role_live_type(operation: str, version: str, role: str | None) -> str | None:
    """Return a pinned role's required live class, never a creatable kind.

    Only explicit per-operation facts qualify. Other roles retain their normal
    semantic/discriminator resolution and ambiguity boundary.
    """
    row = _CONTRACTS[operation]
    if version not in row["versions"]:
        raise ValueError("generic Core business operation is unavailable in this version")
    return row.get("role_live_types", {}).get(role)


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


def attenuation_curve_value_domains(version: str) -> dict[str, Any]:
    """Project compiler tokens through the exact version's reflected enums."""
    from .builders.common import ManifestSchemaLoader

    schema = ManifestSchemaLoader().schema_for(
        "ak.wwise.core.object.setAttenuationCurve", version)
    properties = schema["argsSchema"]["properties"]
    return {
        "curve_kind": {"choices": sorted(
            key for key, native in _CURVE_KINDS.items()
            if native in properties["curveType"]["enum"])},
        "curve_source": {"choices": sorted(
            key for key, native in _CURVE_SOURCES.items()
            if native in properties["use"]["enum"])},
        "points": {
            "maximum_items": MAX_CURVE_POINTS,
            "custom_minimum_items": 1,
            "non_custom_items": 0,
            "item_fields": ["x", "y", "shape"],
            "coordinates": "finite_numbers",
            "shape_choices": sorted(_CURVE_SHAPES),
            "order": "preserve_supplied_order",
        },
    }


def core_business_contract_data(operation: str, version: str) -> dict[str, Any]:
    """Return one URI-local declaration without reflected request mechanics."""

    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported generic Core business operation") from exc
    if version not in row["versions"]:
        raise ValueError("generic Core business operation is unavailable in this version")
    if operation == "ak.wwise.core.project.save" and version in {"2021.1", "2022.1"}:
        # These reflected lanes accept only an empty Save request. Keep the
        # business lifecycle while withholding the later checkout choice.
        row = {**row, "optional_fields": (), "field_types": {}, "field_semantics": None}
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
    for field in row.get("empty_collections", ()):
        input_forms[field] = {**input_forms[field], "empty": {"flag": "--empty", "arguments": [field]}}
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
                    ("zero_or_more" if field in row.get("empty_collections", ()) else "one_or_more")
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
    if operation in HISTORY_VERSIONS:
        declaration["history"] = history_declaration()
    if operation == "ak.wwise.core.object.setAttenuationCurve":
        declaration["value_domains"] = attenuation_curve_value_domains(version)
    if operation == "ak.wwise.core.object.pasteProperties":
        declaration["value_domains"] = {
            "list_mode": {"choices": sorted(_PASTE_MODES), "omitted_effect": "replace"},
        }
    if operation == "ak.wwise.core.blendContainer.addAssignment":
        declaration["value_domains"] = {"edges": {
            "items": 2, "order": ["left", "right"],
            "fade_mode_choices": sorted(_FADE_MODES),
            "shape_choices": sorted(_CURVE_SHAPES),
            "fade_position": {"required_for": "manual", "otherwise": "optional; native ignores it"},
        }}
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
    "core_business_role_live_type",
]

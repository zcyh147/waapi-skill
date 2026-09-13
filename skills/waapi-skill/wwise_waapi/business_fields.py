"""Shared fixed field vocabulary; operation Adapters retain graph semantics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .business_declaration_state import BusinessDeclarationSession
    from .business_declarations import BoundFieldHandle


OBJECT_BUSINESS_FIELD_TYPES = {
    "loop": "string",
    "max_instances": "integer",
    "notes": "string",
    "output_bus": "reference",
    "ignore_parent_instance_limit": "boolean",
    "volume_db": "number",
    "fade_time_ms": "number",
    "delay_ms": "number",
}
ACTION_DURATION_FIELDS = {"fade_time_ms": "FadeTime", "delay_ms": "Delay"}
ACTION_DURATION_SEMANTICS = {
    name: {"unit": "milliseconds", "applicable_object_types": ["Action"],
           "minimum": 0, "omitted": "unchanged"}
    for name in ACTION_DURATION_FIELDS
}


def field_is_action_duration(
    session: BusinessDeclarationSession, field: BoundFieldHandle,
) -> bool:
    """A token alone cannot assign units to a plug-in or unrelated class."""

    if field.token not in ACTION_DURATION_FIELDS.values() or field.value_type != "number":
        return False
    if field.scope_kind == "class":
        if field.scope_value == "Action":
            return True
        return any(
            row["class_id"] == field.scope_value and row["name"] == "Action"
            and row["type_category"].casefold() in {"wobject", "action"}
            for row in session.handles.as_dict()["types"]
        )
    return any(
        row["object_id"] == field.scope_value and row["object_type"] == "Action"
        for row in session.handles.as_dict()["objects"]
    )


def field_value_input(
    session: BusinessDeclarationSession, field: BoundFieldHandle,
) -> dict[str, Any]:
    """Disclose how to express a value, without exposing its native token."""

    result: dict[str, Any] = {"type": field.value_type}
    if field_is_action_duration(session, field):
        result.update({"bare_number_unit": "seconds", "accepted_units": ["seconds", "milliseconds"]})
    if "enum_choices" in field.restrictions:
        result["enum_selection"] = "copy_choice_input;_unambiguous_labels_or_disclosed_values_are_also_accepted"
        result["duplicate_label"] = "copy_the_selected_choice_input"
        result["choices"] = [
            {"input": f"choice:{index}", "value": value,
             "labels": [row["label"] for row in field.restrictions.get("enum_labels", [])
                        if row["value"] == value]}
            for index, value in enumerate(field.restrictions["enum_choices"])
        ]
    return result

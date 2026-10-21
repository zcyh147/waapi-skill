"""Closed custom Modulator inputs owned by RTPC.ControlInput.

Authority: matching 2022.1--2025.1 WObjects.xml RTPC.ControlInput custom
restrictions and the matching SDK object.set custom ModulatorTime example.
This property-bound constructor was introduced in 2022.1. Nested RTPCs,
old-custom replacement disposition and non-fail conflicts remain unfinished
under issue #180; the 2021.1 boundary does not classify other creation routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CONTROL_INPUT_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
CONTROL_INPUT_CLASSES = {"ModulatorLfo": 4194320, "ModulatorEnvelope": 4259856, "ModulatorTime": 5111824}


@dataclass(frozen=True, slots=True)
class OwnedControlInputDescriptor:
    type: str
    name: str
    properties: tuple[tuple[str, Any], ...]
    notes: str | None = None
    platform: str | None = None

    def as_dict(self):
        return {"new_control_input": {"type": self.type, "name": self.name,
            "properties": [{"name": name, "value": value} for name, value in self.properties],
            **({"notes": self.notes} if self.notes is not None else {}),
            **({"platform": self.platform} if self.platform is not None else {})}}

    def native(self, derived=None):
        return {"type": self.type, "name": self.name,
            **({"platform": self.platform} if self.platform is not None else {}),
            **({"notes": self.notes} if self.notes is not None else {}),
            **{"@" + name: value for name, value in self.properties},
            **{"@" + name: value for name, value in (derived or {}).items()}}


def compile_owned_control_input(session, payload):
    """Resolve only Gateway-issued class/field authority, never native input."""
    from .business_declarations import business_repair
    def reject(code, field, action):
        raise business_repair(code, field=field, action=action, tracking_issue=180)
    if session.context.wwise_version not in CONTROL_INPUT_VERSIONS:
        reject("CONTROL_INPUT_CONSTRUCTION_VERSION_BOUNDARY", "new_control_input", "this property-bound owned ControlInput constructor was introduced in 2022.1")
    if not isinstance(payload, Mapping) or not {"kind_handle", "name", "field_values"} <= set(payload) or set(payload) - {"kind_handle", "name", "field_values", "notes"}:
        reject("OWNED_CONTROL_INPUT_INVALID", "new_control_input", "use the complete disclosed new Control Input business fields")
    kind = session.handles.resolve_type(payload["kind_handle"])
    if kind.name not in CONTROL_INPUT_CLASSES or kind.class_id != CONTROL_INPUT_CLASSES[kind.name]:
        reject("INVALID_CONTROL_INPUT_TYPE", "new_control_input", "choose a discovered LFO, Envelope, or Time Modulator")
    name = payload["name"]
    if not isinstance(name, str) or not name.strip():
        reject("OWNED_CONTROL_INPUT_NAME_REQUIRED", "new_control_input.name", "provide the requested nonblank new Control Input name")
    values = payload["field_values"]
    if not isinstance(values, Mapping) or len(values) > 32:
        reject("OWNED_CONTROL_INPUT_FIELDS_INVALID", "new_control_input.field_values", "provide bounded selected class properties")
    properties, used, platforms = [], set(), set()
    for handle, value in values.items():
        field = session.handles.bound_field(handle)
        if field.scope_kind != "class" or field.scope_value != kind.class_id or field.field_kind != "property":
            reject("FIELD_HANDLE_SCOPE_MISMATCH", "new_control_input.field_values", "discover scalar properties for this exact selected Modulator class")
        if field.token.casefold() in used:
            reject("OBJECT_GRAPH_FIELD_CONFLICT", "new_control_input.field_values", "assign each new Control Input property once")
        used.add(field.token.casefold())
        platforms.add(field.platform)
        properties.append({"name": field.token, "value": session.handles.validate_field_value(field, value)})
    if len(platforms) > 1:
        reject("OWNED_CONTROL_INPUT_PLATFORM_ASSIGNMENTS_UNRESOLVED", "new_control_input.field_values",
            "mixed generic and explicit or distinct platform assignments need a separately proved construction under issue #180")
    platform = next(iter(platforms), None)
    return {"new_control_input": {"type": kind.name, "name": name, "properties": properties,
        **({"platform": platform} if platform is not None else {}),
        **({"notes": payload["notes"]} if "notes" in payload else {})}}

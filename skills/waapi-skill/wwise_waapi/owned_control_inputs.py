"""Closed custom Modulator inputs owned by RTPC.ControlInput.

Authority: matching 2022.1--2025.1 WObjects.xml RTPC.ControlInput custom
restrictions and the matching SDK object.set custom ModulatorTime example.
Exact fragments, matching schema/class/example digests and introduction facts
are packaged per version in resources/metadata/*/owned-control-input-construction.json.
This property-bound constructor was introduced in 2022.1. The previous
custom input replacement disposition remains unfinished
under issue #180; the 2021.1 boundary does not classify other creation routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping
from xml.etree import ElementTree

from .canonical import canonical_sha256

CONTROL_INPUT_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
CONTROL_INPUT_CLASSES = {"ModulatorLfo": 4194320, "ModulatorEnvelope": 4259856, "ModulatorTime": 5111824}
CONSTRUCTION_AUTHORITY_ROOT = Path(__file__).resolve().parents[1] / "resources/metadata"
_MANIFEST_ROOT = Path(__file__).resolve().parents[1] / "resources/manifest"
_BUILDS = {"2022.1": "2022.1.19.8584", "2023.1": "2023.1.19.8928",
    "2024.1": "2024.1.13.9056", "2025.1": "2025.1.7.9143"}


def constructor_authority(version):
    """Validate packaged matching-version primary facts without an installed SDK."""
    try:
        return _load_constructor_authority(version)
    except (KeyError, TypeError, AttributeError, StopIteration, ElementTree.ParseError) as exc:
        raise ValueError("Constructor authority facts are malformed") from exc


def _load_constructor_authority(version):
    if version not in CONTROL_INPUT_VERSIONS:
        raise ValueError("No constructor authority for this version")
    raw = (CONSTRUCTION_AUTHORITY_ROOT / version / "owned-control-input-construction.json").read_bytes()
    if len(raw) > 32 * 1024:
        raise ValueError("Constructor authority exceeds its packaged bound")
    value = json.loads(raw)
    if (set(value) != {"contract", "version", "build", "sources", "scope", "authority_sha256"}
            or value["contract"] != "waapi-skill.owned-control-input-construction/v1"
            or value["version"] != version or value["build"] != _BUILDS[version]
            or canonical_sha256({key: item for key, item in value.items() if key != "authority_sha256"}) != value["authority_sha256"]):
        raise ValueError("Constructor authority version/source seal is invalid")
    sources = value["sources"]
    axis = sources["time_axis"]
    if (set(axis) != {"guide_member", "guide_sha256", "duration_member", "duration_sha256", "x_quantity", "unit", "duration_quantity", "policy", "complete_native_domain"}
            or axis["guide_member"] != {"2022.1": "ch22s06.html", "2023.1": "ch17s06.html", "2024.1": "ch18s06.html", "2025.1": "ch19s06.html"}[version]
            or any(re.fullmatch(r"[0-9a-f]{64}", axis[key]) is None for key in ("guide_sha256", "duration_sha256"))
            or axis["duration_member"] != "Authoring/Data/WObjects/Html/en/TimeModDuration.html"
            or axis["x_quantity"] != "time" or axis["unit"] != "seconds"
            or axis["duration_quantity"] != "one_iteration_at_normal_playback_rate"
            or axis["policy"] != "interim_gateway_intent_preservation_within_effective_duration"
            or axis["complete_native_domain"] is not False):
        raise ValueError("Time-axis source authority is invalid")
    introduction = sources["constructor_introduction"]
    if (introduction["build"] != _BUILDS["2022.1"] or introduction["rtpc_work_item"] != "WG-38235"
            or introduction["release_member"] != "whatsnew_2022_1.html"
            or introduction["feature_member"] != "whatsnew_2022_1_new_features.html"
            or introduction["custom_modulator_statement"] != "Custom and ShareSets Modulators can now be created."
            or any(re.fullmatch(r"[0-9a-f]{64}", introduction[key]) is None for key in ("release_sha256", "feature_sha256"))):
        raise ValueError("Constructor introduction authority is invalid")
    xml, example = sources["wobjects"], sources["sdk_example"]
    fragment = xml["control_input_fragment"]
    reference = ElementTree.fromstring(fragment)
    types = reference.findall("Restrictions/TypeEnumerationRestriction/Type")
    expected_types = {**CONTROL_INPUT_CLASSES, "GameParameter": 1507344, "MidiParameter": 4128784}
    classes = {row["name"]: row for row in sources["sdk_classes"]}
    expected_classes = {"RTPC": 1441808, **expected_types}
    if (xml["member"] != "Authoring/Data/WObjects/WObjects.xml"
            or sha256(fragment.encode()).hexdigest() != xml["fragment_sha256"]
            or reference.tag != "Reference" or reference.get("Name") != "ControlInput"
            or reference.get("SupportCustom") != "true" or reference.get("SupportLink") != "false"
            or len(types) != len(expected_types) or {row.get("Name") for row in types} != set(expected_types)
            or any(row.get("SupportCustom", "true") != ("true" if row.get("Name") in CONTROL_INPUT_CLASSES else "false") for row in types)
            or len(classes) != len(sources["sdk_classes"]) or set(classes) != set(expected_classes)
            or any(type(row["class_id"]) is not int or row["class_id"] != expected_classes[name]
                or row["source_member"] != "wwiseobject_" + name.lower() + ".html"
                or re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]) is None for name, row in classes.items())):
        raise ValueError("Constructor authority does not prove exact custom classes/ownership")
    member = "ak_wwise_core_object_set_example_" + ("adds" if version == "2022.1" else "adding") + "_an_rtpc_with_curve_to_an_object_and_creates_a_new_custom_controlinput.html"
    if (example["member"] != member or example["placement"] != ["@RTPC", "@ControlInput"]
            or example["rtpc_type"] != "RTPC" or example["curve_type"] != "Curve"
            or example["control_input"] != {"type": "ModulatorTime", "name": "TimeMod", "@TimeModDuration": 5, "@EnvelopeStopPlayback": False}
            or example["control_input"]["@EnvelopeStopPlayback"] is not False
            or any(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None for item in (xml, example))):
        raise ValueError("Constructor authority example is invalid")
    manifest = (_MANIFEST_ROOT / version / "schemas.json").read_bytes()
    args = next(row["schema"]["argsSchema"] for row in json.loads(manifest)["schemas"] if row["uri"] == "ak.wwise.core.object.set")
    grammar = sources["reflected_set"]
    if (sha256(manifest).hexdigest() != grammar["manifest_sha256"]
            or canonical_sha256(args) != grammar["args_schema_sha256"]
            or grammar["object_definition"] != ("localDefinitions" if "localDefinitions" in args else "definitions")):
        raise ValueError("Constructor authority differs from its reflected grammar")
    return {"contract": value["contract"], "version": version, "build": value["build"],
        "resource_sha256": sha256(raw).hexdigest(), "authority_sha256": value["authority_sha256"], "time_axis": axis}


def constructor_authority_current(proof):
    try:
        return constructor_authority(proof["version"]) == proof
    except (ValueError, KeyError, TypeError, OSError, StopIteration, ElementTree.ParseError):
        return False


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
            "create and verify the input with one field scope, then bind its verified exact GUID in a new object.setProperty Draft for separately previewed platform assignments")
    platform = next(iter(platforms), None)
    return {"new_control_input": {"type": kind.name, "name": name, "properties": properties,
        **({"platform": platform} if platform is not None else {}),
        **({"notes": payload["notes"]} if "notes" in payload else {})}}

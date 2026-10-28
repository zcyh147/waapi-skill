"""Closed object-return selections for the two SoundEngine runtime getters."""
from __future__ import annotations

from .builders.query import query_return_scope_options
from .object_query_outputs import available_query_outputs, DECLARED_QUERY_RETURN_SPELLINGS, QUERY_FIELD_MODES
from .object_query_related import _meaning

MAX_SOUNDENGINE_OUTPUTS = 32
MAX_SOUNDENGINE_CUSTOM_OUTPUTS = 8
SOUNDENGINE_FIELD_INPUTS = (
    ("fields", "include_field", QUERY_FIELD_MODES[0]),
    ("override_source_values", "include_override_source_value", QUERY_FIELD_MODES[1]),
    ("local_references", "include_local_reference", QUERY_FIELD_MODES[2]),
)
_IDENTITY = ("id", "name", "type", "path")


def soundengine_object_outputs(version):
    return {**{name: (name, name) for name in _IDENTITY}, **available_query_outputs(version)}


def soundengine_object_return_contract(version):
    return {
        "outputs": {"choices": list(soundengine_object_outputs(version)), "maximum": MAX_SOUNDENGINE_OUTPUTS,
            "selection": "id/name are always retained; requested fields use the closed object-query business meanings",
            "presence": "absent requested values are unavailable_fields; explicit null and actual declared-return observations are preserved"},
        "platform_language": "trimmed literal name or GUID, at most 512 UTF-8 bytes; omission preserves native defaults",
        "class_fields": {"inputs": {name: {"flag": mode.option, "repeatable": True,
                "kinds": list(mode.bindings)} for name, _, mode in SOUNDENGINE_FIELD_INPUTS},
            "maximum": MAX_SOUNDENGINE_CUSTOM_OUTPUTS, "maximum_total_meaning_characters": 640,
            "authority": "live exact State/Switch class metadata; one getter dispatch after binding",
            "returned_type": "must match the selected metadata class", "raw_accessors": "forbidden"},
        "custom_fields": {"route": "query-object --exact-id <returned-id>",
            "scope": "additional instance-specific and related reads outside the class-bound getter outputs",
            "native_getter_expression_equivalence": "not claimed for the separate read",
            "discovery": "query-schema exposes --include-field and closed related-output selectors",
            "return_scope": "copy explicit platform/language to the later query when required",
            "observation": "separate current Authoring object read after runtime selection; no atomic snapshot or runtime-effect claim",
            "native_return_expression_input": "forbidden"},
    }


def compile_soundengine_object_returns(version, outputs, *, platform=None, language=None):
    available = soundengine_object_outputs(version)
    if len(outputs) > MAX_SOUNDENGINE_OUTPUTS or len(set(outputs)) != len(outputs):
        raise ValueError("SoundEngine outputs must be unique and contain at most 32 selections")
    if any(value not in available for value in outputs):
        raise ValueError("SoundEngine output must be one version-available disclosed business output")
    scope = query_return_scope_options(platform=platform, language=language)
    bindings = tuple(("declared_return" if name in DECLARED_QUERY_RETURN_SPELLINGS else "business", *available[name])
        for name in outputs)
    if outputs:
        scope = {"return": list(dict.fromkeys(["id", "name", *(native for _, native, _ in bindings)])), **scope}
    return scope, bindings


def compile_soundengine_field_meanings(args):
    declarations = {}
    unique = {}
    count = 0
    for name, attribute, mode in SOUNDENGINE_FIELD_INPUTS:
        values = [_meaning(value) for value in getattr(args, attribute)]
        count += len(values)
        keys = [" ".join(value.split()).casefold() for value in values]
        if len(set(keys)) != len(keys):
            raise ValueError("SoundEngine field meanings must be unique within each selected mode")
        for key, value in zip(keys, values):
            unique.setdefault(key, value)
        setattr(args, mode.selected_attribute, tuple(unique[key] for key in keys))
        if values:
            declarations[name] = values
    if count > MAX_SOUNDENGINE_CUSTOM_OUTPUTS or sum(map(len, unique.values())) > 640:
        raise ValueError("SoundEngine custom fields exceed the eight-output or 640-character meaning budget")
    args.query_custom_field_meanings = tuple(unique.values())
    return declarations

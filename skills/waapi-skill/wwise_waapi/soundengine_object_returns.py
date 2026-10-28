"""Closed object-return selections for the two SoundEngine runtime getters."""
from __future__ import annotations

from .builders.query import query_return_scope_options
from .object_query_outputs import available_query_outputs, DECLARED_QUERY_RETURN_SPELLINGS

MAX_SOUNDENGINE_OUTPUTS = 32
_IDENTITY = ("id", "name", "type", "path")
# The pinned 2025 enum contains this exact spelling. It proves availability,
# not equivalence to supportsRandomizer or a particular returned key/shape.
_DECLARED_OUTPUT_VERSIONS = {"suppportsRandomizer": ("2025.1",)}


def soundengine_object_outputs(version):
    return {**{name: (name, name) for name in _IDENTITY}, **available_query_outputs(version),
        **{name: (name, "declared_return_observation") for name, versions in _DECLARED_OUTPUT_VERSIONS.items()
            if version in versions}}


def soundengine_object_return_contract(version):
    return {
        "outputs": {"choices": list(soundengine_object_outputs(version)), "maximum": MAX_SOUNDENGINE_OUTPUTS,
            "selection": "id/name are always retained; requested fields use the closed object-query business meanings",
            "presence": "absent requested values are unavailable_fields; explicit null and actual declared-return observations are preserved"},
        "platform_language": "trimmed literal name or GUID, at most 512 UTF-8 bytes; omission preserves native defaults",
        "custom_fields": {"route": "query-object --exact-id <returned-id>",
            "discovery": "query-schema exposes --include-field and closed related-output selectors",
            "scope": "copy explicit platform/language to the later query when required",
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
    bindings = tuple(("declared_return" if name in DECLARED_QUERY_RETURN_SPELLINGS or name in _DECLARED_OUTPUT_VERSIONS else "business", *available[name])
        for name in outputs)
    if outputs:
        scope = {"return": list(dict.fromkeys(["id", "name", *(native for _, native, _ in bindings)])), **scope}
    return scope, bindings

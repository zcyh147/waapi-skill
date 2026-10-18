"""Closed business outputs for the versioned object-query declaration.

The registry fixes every caller spelling. Reflected definitions provide version
availability and result facts; a new reflected field never becomes a caller
input without a registry entry.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from .schema_inventory import DefinitionGraph, load_definition_graph, resolve_schema_reference
from .versions import SUPPORTED_WWISE_VERSION_KEYS


LEGACY_OUTPUTS: Mapping[str, tuple[str, str]] = {
    "notes": ("notes", "notes"),
    "volume-db": ("@Volume", "volume_db"),
    "pitch-cents": ("@Pitch", "pitch_cents"),
    "output-bus": ("OutputBus", "output_bus"),
    "source-language": ("audioSource:language", "source_language"),
    "parent": ("parent", "parent"),
    "owner": ("owner", "owner"),
    "included": ("isIncluded", "included"),
    "playable": ("isPlayable", "playable"),
    "explicitly-muted": ("isExplicitMute", "explicitly_muted"),
    "explicitly-soloed": ("isExplicitSolo", "explicitly_soloed"),
    "child-count": ("childrenCount", "child_count"),
    "plugin-name": ("pluginName", "plugin_name"),
    "category": ("category", "category"),
    "file-path": ("filePath", "file_path"),
    "original-file-path": ("originalFilePath", "original_file_path"),
    "active-source": ("activeSource", "active_source"),
    "override-output": ("OverrideOutput", "override_output"),
    "action-type": ("ActionType", "action_type"),
    "target": ("Target", "target"),
    "work-unit": ("workunit", "work_unit"),
    "source-duration": ("audioSource:playbackDuration", "source_duration"),
    "max-radius": ("audioSource:maxRadiusAttenuation", "max_radius"),
    "switch-container-child-context": ("switchContainerChildContext", "switch_container_child_context"),
}

# Explicit native/business pairs, not an arbitrary native-accessor input lane.
_NAMED_OUTPUT_PAIRS = (
    ("audioSourceLanguage", "audio-source-language"),
    ("audioSourceTrimValues", "audio-source-trim-values"),
    ("classId", "class-id"),
    ("convertedWemFilePath", "converted-wem-file-path"),
    ("maxDurationSource", "longest-duration-source"),
    ("maxRadiusAttenuation", "largest-radius-attenuation"),
    ("mediaSize", "media-size-bytes"),
    ("musicPlaylistRoot", "music-playlist-root"),
    ("musicTransitionRoot", "music-transition-root"),
    ("objectSize", "object-size-bytes"),
    ("originalWavFilePath", "original-wav-file-path"),
    ("playbackDuration", "playback-duration"),
    ("shortId", "short-id"),
    ("soundbankBnkFilePath", "soundbank-file-path"),
    ("structureSize", "structure-size-bytes"),
    ("totalSize", "total-size-bytes"),
    ("workunitIsDefault", "work-unit-is-default"),
    ("workunitIsDirty", "work-unit-is-dirty"),
    ("workunitType", "work-unit-type"),
    ("convertedFilePath", "converted-file-path"),
    ("duration", "duration"),
    ("isImplicitMute", "implicitly-muted"),
    ("isImplicitSolo", "implicitly-soloed"),
    ("points", "curve-points"),
    ("originalRelativeFilePath", "original-relative-file-path"),
    ("stateGroups", "state-groups"),
    ("stateProperties", "state-properties"),
    ("convertedAnonymousChannelCount", "converted-anonymous-channel-count"),
    ("convertedBitDepth", "converted-bit-depth"),
    ("convertedChannelConfig", "converted-channel-configuration"),
    ("convertedChannelMask", "converted-channel-mask"),
    ("convertedCodec", "converted-codec"),
    ("convertedDataSize", "converted-data-size-bytes"),
    ("convertedDuration", "converted-duration"),
    ("convertedFileSize", "converted-file-size-bytes"),
    ("convertedHeightChannelCount", "converted-height-channel-count"),
    ("convertedLFEChannelCount", "converted-lfe-channel-count"),
    ("convertedNormalChannelCount", "converted-normal-channel-count"),
    ("convertedSampleCount", "converted-sample-count"),
    ("convertedSampleRate", "converted-sample-rate"),
    ("convertedTotalChannelCount", "converted-total-channel-count"),
    ("originalAnonymousChannelCount", "original-anonymous-channel-count"),
    ("originalBitDepth", "original-bit-depth"),
    ("originalChannelConfig", "original-channel-configuration"),
    ("originalChannelMask", "original-channel-mask"),
    ("originalCodec", "original-codec"),
    ("originalDataSize", "original-data-size-bytes"),
    ("originalDuration", "original-duration"),
    ("originalFileSize", "original-file-size-bytes"),
    ("originalHeightChannelCount", "original-height-channel-count"),
    ("originalLFEChannelCount", "original-lfe-channel-count"),
    ("originalNormalChannelCount", "original-normal-channel-count"),
    ("originalSampleCount", "original-sample-count"),
    ("originalSampleRate", "original-sample-rate"),
    ("originalTotalChannelCount", "original-total-channel-count"),
    ("conversionFormat", "conversion-format"),
    ("convertedAmbisonicsChannelCount", "converted-ambisonics-channel-count"),
    ("convertedNonLFEChannelCount", "converted-non-lfe-channel-count"),
    ("convertedSampleRateSetting", "converted-sample-rate-setting"),
    ("convertedTrimmedDuration", "converted-trimmed-duration"),
    ("customStates", "custom-states"),
    ("extractEvents", "extracted-events"),
    ("extractMedia", "extracted-media"),
    ("extractStructures", "extracted-structures"),
    ("hasEmptySwitchStateAssignment", "has-empty-switch-state-assignment"),
    ("isLanguageIncluded", "source-language-included"),
    ("musicTransitionObject", "music-transition-object"),
    ("originalAmbisonicsChannelCount", "original-ambisonics-channel-count"),
    ("originalNonLFEChannelCount", "original-non-lfe-channel-count"),
    ("originalState", "original-state"),
    ("soundbanksReferencingEvent", "soundbanks-referencing-event"),
    ("supportsRandomizer", "supports-randomizer"),
    ("supportsStates", "supports-states"),
    ("switchGroupGameParameter", "switch-group-game-parameter"),
    ("workunitIsLoaded", "work-unit-is-loaded"),
)
QUERY_BUSINESS_OUTPUTS = {
    **LEGACY_OUTPUTS,
    **{business: (native, business.replace("-", "_")) for native, business in _NAMED_OUTPUT_PAIRS},
}


@lru_cache(maxsize=5)
def _definition_graph(version: str) -> DefinitionGraph:
    return load_definition_graph(version)


def _return_properties(version: str) -> Mapping[str, Any]:
    graph = _definition_graph(version)
    return graph.documents["waapi_definitions.json"]["definitions"]["objectReturn"]["properties"]


def available_query_outputs(version: str) -> dict[str, tuple[str, str]]:
    properties = _return_properties(version)
    outputs = {name: binding for name, binding in QUERY_BUSINESS_OUTPUTS.items()
               if name in LEGACY_OUTPUTS or binding[0] in properties}
    if version == "2021.1":
        # The pinned 2021 object.get return contract uses the older WAV accessor.
        # activeSource is documented as a WAQL object expression, not a return
        # accessor; its separate closed relationship preserves that distinction.
        outputs["original-file-path"] = ("originalWavFilePath", "original_file_path")
        outputs.pop("active-source")
    return outputs


def query_output_detail(version: str, name: str) -> dict[str, Any]:
    native, output = available_query_outputs(version).get(name, QUERY_BUSINESS_OUTPUTS[name])
    supported = [item for item in SUPPORTED_WWISE_VERSION_KEYS if name in available_query_outputs(item)]
    schema = _return_properties(version).get(native)
    return {
        "name": name, "output_field": output, "available": version in supported,
        "supported_versions": supported,
        "description": schema.get("description", "") if schema else f"Existing business output {name}.",
        "result_schema": schema,
        "result_shape": _result_shape(schema, graph=_definition_graph(version)) if schema else None,
        "native_definition": {"version": version, "document": "waapi_definitions.json",
                              "pointer": "/definitions/objectReturn/properties/" + native} if schema else None,
        "presence": "optional; unavailable_fields preserves absence and explicit null stays null",
        **({"alternative": {"relationship": "active-source", "source": "one exact Sound GUID or path",
                             "gateway_option": "--relationship active-source", "version": "2021.1",
                             "result": "selected source identity; then read that exact GUID"}}
           if version == "2021.1" and name == "active-source" else {}),
    }


def _result_shape(value: Any, *, graph: DefinitionGraph, document: str = "waapi_definitions.json", depth: int = 0) -> Any:
    """Resolve same-version result facts without exposing caller return grammar."""

    if depth > 16:
        raise ValueError("Object-query result shape exceeds the packaged schema depth bound")
    if isinstance(value, list):
        return [_result_shape(item, graph=graph, document=document, depth=depth + 1) for item in value]
    if not isinstance(value, Mapping):
        return value
    expanded: dict[str, Any] = {}
    if "$ref" in value:
        resolved = resolve_schema_reference(value["$ref"], root_schema=graph.documents[document], graph=graph)
        ref_document = document if resolved.document_name == "<schema>" else resolved.document_name
        expanded = _result_shape(resolved.target, graph=graph, document=ref_document, depth=depth + 1)
    expanded.update({key: _result_shape(item, graph=graph, document=document, depth=depth + 1)
                     for key, item in value.items() if key != "$ref"})
    return expanded

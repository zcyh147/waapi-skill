"""Closed singleton-related projections sharing the fixed business output registry."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .object_query_outputs import QUERY_BUSINESS_OUTPUTS, available_query_outputs
from .schema_inventory import load_definition_graph
from .versions import SUPPORTED_WWISE_VERSION_KEYS

RELATED_QUERY_RELATIONS = {"parent": "parent", "owner": "owner", "work-unit": "workunit"}

# Reviewed SDK OBJECT/VALUE descriptors, never inferred from a live enum or input.
_COMMON_OUTPUTS = frozenset("""
volume-db pitch-cents output-bus notes parent owner work-unit playable explicitly-muted
explicitly-soloed implicitly-muted implicitly-soloed child-count plugin-name category
file-path class-id short-id audio-source-language longest-duration-source
largest-radius-attenuation music-playlist-root music-transition-root soundbank-file-path
switch-container-child-context work-unit-is-default work-unit-is-dirty work-unit-type
""".split())
_ADDITIONAL_OUTPUTS = {
    "2022.1": frozenset("included original-file-path converted-file-path active-source".split()),
    "2023.1": frozenset("original-relative-file-path state-groups state-properties".split()),
    "2024.1": frozenset("""
converted-anonymous-channel-count converted-bit-depth converted-channel-configuration
converted-channel-mask converted-codec converted-data-size-bytes converted-duration
converted-file-size-bytes converted-height-channel-count converted-lfe-channel-count
converted-normal-channel-count converted-sample-count converted-sample-rate converted-total-channel-count
original-anonymous-channel-count original-bit-depth original-channel-configuration original-channel-mask
original-codec original-data-size-bytes original-duration original-file-size-bytes
original-height-channel-count original-lfe-channel-count original-normal-channel-count
original-sample-count original-sample-rate original-total-channel-count
""".split()),
    "2025.1": frozenset("""
conversion-format converted-ambisonics-channel-count converted-non-lfe-channel-count
converted-sample-rate-setting converted-trimmed-duration custom-states extracted-events
extracted-media extracted-structures has-empty-switch-state-assignment source-language-included
music-transition-object original-ambisonics-channel-count original-non-lfe-channel-count
original-state soundbanks-referencing-event supports-randomizer supports-states
switch-group-game-parameter work-unit-is-loaded
""".split()),
}


def related_output_detail(version: str, name: str) -> dict[str, Any]:
    outputs = available_query_outputs(version)
    allowed = set(_COMMON_OUTPUTS)
    for first_version, additions in _ADDITIONAL_OUTPUTS.items():
        if SUPPORTED_WWISE_VERSION_KEYS.index(version) >= SUPPORTED_WWISE_VERSION_KEYS.index(first_version):
            allowed.update(additions)
    if version == "2021.1":
        allowed.update({"original-file-path", "original-wav-file-path", "converted-wem-file-path"})
    available = name in outputs and name in allowed
    if name == "active-source" and version == "2021.1":
        reason = "2021.1 active-source is a Gateway-owned multi-read derivation, not a composable native return field"
    elif name not in outputs:
        reason = "the existing business output is unavailable in the selected version"
    elif name not in allowed:
        reason = "related composition is not established by the reviewed matching SDK descriptor; remains #181 work, not native absence"
    else:
        reason = "matching SDK object/value descriptor and dot-chain rule"
    return {"available": available, "reason": reason, "output_field": outputs.get(name, (None, None))[1]}


@dataclass(frozen=True)
class RelatedQueryOutput:
    """One owned relation path and terminal binding; custom terminals can reuse it."""
    relation: str
    relation_native: str
    terminal_native: str
    output_name: str
    output_group: str | None = None

    def binding(self) -> tuple[str, str, dict[str, Any]]:
        return ("related", f"{self.relation_native}.{self.terminal_native}",
                {"relation": self.relation, "group": self.output_group, "field": self.output_name})


def compile_related_output(version: str, relation: str, name: str) -> RelatedQueryOutput:
    if relation not in RELATED_QUERY_RELATIONS:
        raise ValueError("--include-related requires one disclosed singleton relation: " + ", ".join(RELATED_QUERY_RELATIONS))
    detail = related_output_detail(version, name)
    if not detail["available"]:
        raise ValueError(f"--include-related {relation} {name}: {detail['reason']}")
    native, output = available_query_outputs(version)[name]
    assert native is not None
    return RelatedQueryOutput(relation, RELATED_QUERY_RELATIONS[relation], native, output)


def related_query_contract(version: str, *, maximum_outputs: int) -> dict[str, Any]:
    source_file = Path(__file__).resolve().parents[1] / "references" / "semantic" / version / "query-related-output-sources.json"
    source = json.loads(source_file.read_text(encoding="utf-8"))
    graph = load_definition_graph(version)
    if source["version"] != version or source["wwise_build"] != graph.wwise_build:
        raise ValueError("Related-query source evidence does not match the selected definitions")
    patterns = graph.documents["waapi_definitions.json"]["definitions"]["objectReturn"]["patternProperties"]
    return {"option": "--include-related <singleton-relation> <business-output> (repeat)",
            "relations": dict(RELATED_QUERY_RELATIONS),
            "outputs": {name: related_output_detail(version, name) for name in QUERY_BUSINESS_OUTPUTS},
            "result_schema": patterns,
            "result_schema_source": {"version": version, "wwise_build": graph.wwise_build, "document": "waapi_definitions.json", "pointer": "/definitions/objectReturn/patternProperties"},
            "source": {key: source[key] for key in ("version", "wwise_build", "page", "page_sha256")},
            "chain_html_lines": [rule["html_line"] for rule in source["chain_rules"]],
            "return_options_source": source["return_options_source"],
            "budget": {"shared_fixed_outputs": maximum_outputs, "automatic_identity_fields_per_relation": 1, "singleton_relations": len(RELATED_QUERY_RELATIONS)},
            "terminal_semantics": "same existing output contract; volume-db/pitch-cents read local values on the related object, not cumulative levels or runtime audio",
            "identity": "root id/name/type/path unchanged; related.<relation>.object is the native singleton reference; canonical GUID supports read-only hops, not mutation authority",
            "presence": "native absence uses group-local unavailable_fields; null/extensions/order preserved; no inferred join",
            "metadata_reads": False,
            "followup": "custom related fields, multiple declared hops, list compositions, unresolved legacy spellings and the native states accessor remain #181 work"}

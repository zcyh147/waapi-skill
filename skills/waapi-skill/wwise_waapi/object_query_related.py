"""Closed singleton-related projections sharing the fixed business output registry."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .object_query_outputs import QUERY_BUSINESS_OUTPUTS, QUERY_FIELD_MODES, reference_value_source_contract, available_query_outputs
from .builders.query import MAX_ADVANCED_RETURN_EXPRESSIONS, MAX_ADVANCED_RETURN_EXPRESSION_BYTES, MAX_QUERY_TAKE
from .schema_inventory import load_definition_graph
from .versions import SUPPORTED_WWISE_VERSION_KEYS
from .metadata_discovery import MAX_METADATA_DISCOVERY_QUERY_CHARS

RELATED_QUERY_LIST_RELATIONS = {"children": "children", "descendants": "descendants", "ancestors": "ancestors", "references-to": "referencesTo"}

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
        reason = "related composition is not yet supported by the related-output contract; this does not establish native absence"
    else:
        reason = "matching SDK object/value descriptor and dot-chain rule"
    return {"available": available, "reason": reason, "output_field": outputs.get(name, (None, None))[1]}


@dataclass(frozen=True)
class RelatedQueryOutput:
    """A rendered singleton path, terminal and collision-free business location."""
    relation: str
    relation_native: str
    terminal_native: str
    output_name: str
    output_group: str | None = None
    path: tuple[tuple[str, str], ...] = ()
    row_indices: tuple[int, ...] | None = None

    def binding(self) -> tuple[str, str, dict[str, Any]]:
        location = {"path": self.path or (("relation", self.relation),),
                    "group": self.output_group, "field": self.output_name}
        if self.row_indices is not None:
            location["row_indices"] = self.row_indices
        return ("related", ".".join(value for value in (self.relation_native, self.terminal_native) if value), location)


RELATED_FIELD_MODES = {mode.option.replace("--include-", "--include-related-"): mode for mode in QUERY_FIELD_MODES}


def _meaning(value: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip() or len(value) > MAX_METADATA_DISCOVERY_QUERY_CHARS
            or any(ord(c) < 32 or ord(c) == 127 or c in "@.\\;\"'()" for c in value)):
        raise ValueError("related field meanings must be bounded user-facing phrases, not native accessor or function grammar")
    return value


def parse_related_request(version: str, values: list[str], option: str) -> dict[str, Any]:
    if len(values) < 2:
        raise ValueError(f"{option} requires a related path and one terminal")
    tokens, terminal = values[:-1], values[-1]
    hops, index = [], 0
    while index < len(tokens):
        name = tokens[index]
        if name in RELATED_QUERY_RELATIONS or name in RELATED_QUERY_LIST_RELATIONS:
            hops.append(("list" if name in RELATED_QUERY_LIST_RELATIONS else "relation", name))
            index += 1
        elif name in {"reference", "local-reference"} and index + 1 < len(tokens):
            hops.append((name, _meaning(tokens[index + 1])))
            index += 2
        else:
            raise ValueError(f"{option} requires disclosed relation or reference/local-reference MEANING hops")
    if len(hops) > MAX_ADVANCED_RETURN_EXPRESSIONS:
        raise ValueError(f"closed related paths accept at most {MAX_ADVANCED_RETURN_EXPRESSIONS} hops")
    if option == "--include-related":
        detail = related_output_detail(version, terminal)
        if not detail["available"]:
            raise ValueError(f"{option} {' '.join(values)}: {detail['reason']}")
    else:
        _meaning(terminal)
    return {"hops": tuple(hops), "terminal": terminal, "option": option}


def compile_related_output(version: str, relation: str, name: str) -> RelatedQueryOutput:
    request = parse_related_request(version, [relation, name], "--include-related")
    native, output = available_query_outputs(version)[request["terminal"]]
    return RelatedQueryOutput(relation, RELATED_QUERY_RELATIONS[relation], native, output)


def related_native_fields(bindings, identity_fields):
    fields = tuple(dict.fromkeys((*identity_fields, *(native for kind, native, _ in bindings
                  if kind not in {"derived", "related_unavailable"}))))
    if len(fields) > MAX_ADVANCED_RETURN_EXPRESSIONS:
        raise ValueError(f"related projection accepts at most {MAX_ADVANCED_RETURN_EXPRESSIONS} native return expressions including identity and scope helpers")
    if any(len(field.encode("utf-8")) > MAX_ADVANCED_RETURN_EXPRESSION_BYTES for field in fields):
        raise ValueError(f"each related return expression is limited to {MAX_ADVANCED_RETURN_EXPRESSION_BYTES} UTF-8 bytes")
    return fields


def fixed_related_bindings(version: str, requests):
    """Render the fixed prefix once; metadata-bound suffixes are prepared live."""
    bindings, seen = [], set()
    for request in requests:
        native, path = "", []
        for kind, name in request["hops"]:
            if kind != "relation":
                break
            native = f"{native}." if native else ""
            native += RELATED_QUERY_RELATIONS[name]
            path.append((kind, name))
            if native not in seen:
                bindings.append(("related_identity", native, {"path": tuple(path)}))
                seen.add(native)
        else:
            if request["option"] == "--include-related":
                terminal, output = available_query_outputs(version)[request["terminal"]]
                bindings.append(RelatedQueryOutput(path[0][1], native, terminal, output, path=tuple(path)).binding())
    return bindings


def related_query_contract(version: str, *, maximum_outputs: int, maximum_custom_outputs: int) -> dict[str, Any]:
    source_file = Path(__file__).resolve().parents[1] / "references" / "semantic" / version / "query-related-output-sources.json"
    source = json.loads(source_file.read_text(encoding="utf-8"))
    graph = load_definition_graph(version)
    if source["version"] != version or source["wwise_build"] != graph.wwise_build:
        raise ValueError("Related-query source evidence does not match the selected definitions")
    patterns = graph.documents["waapi_definitions.json"]["definitions"]["objectReturn"]["patternProperties"]
    list_source = json.loads((source_file.parent / "query-list-output-sources.json").read_text(encoding="utf-8"))
    if (list_source["version"], list_source["wwise_build"], list_source["page_sha256"]) != (version, graph.wwise_build, source["page_sha256"]):
        raise ValueError("Related-list evidence does not match the selected definitions")
    from .canonical import canonical_sha256
    from .builders.query import MAX_STRUCTURED_SOURCE_ITEMS
    from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS
    return {"option": "--include-related <closed-hop>... <business-output> (repeat)",
            "relations": dict(RELATED_QUERY_RELATIONS),
            "list_members": {"relations": dict(RELATED_QUERY_LIST_RELATIONS), "strategy": list_source["strategy"],
                "membership": "2021/2022: each actual canonical owner/relation is read with documented query SELECT, repeated bounded skip/final-take windows and overflow detection; no bare list return accessor is assumed",
                "result": "related.<list>.items contains ordered independent member records with object identities and the same fixed/custom terminal modes; nested paths retain their grouping",
                "source": {**{key: list_source[key] for key in ("version", "wwise_build", "page", "page_sha256")}, "sections_sha256": canonical_sha256(list_source["sections"])},
                "limits": {"closed_path_hops": MAX_ADVANCED_RETURN_EXPRESSIONS, "unique_member_ids": MULTI_IDENTITY_READ_MAX_IDS, "member_occurrences": MULTI_IDENTITY_READ_MAX_IDS,
                    "cumulative_member_observations": MAX_ADVANCED_RETURN_EXPRESSIONS * MULTI_IDENTITY_READ_MAX_IDS,
                    "source_ids_per_read": MAX_STRUCTURED_SOURCE_ITEMS, "relationship_rows_per_read": MAX_QUERY_TAKE, "grouped_member_reconstruction_bytes": "existing per-read result byte limit", "cumulative_read_result_bytes": "64 times the existing per-read result byte limit", "deadline": "existing shared query deadline"},
                "presence": "native composition preserves omitted/null/empty list distinctions. Older owner relationship queries return a sequence: zero selected rows means items []; no unsupported bare-return null/absence fact is inferred. Missing owners remain unavailable. Member absence never removes that member; native extensions and duplicate occurrences are retained",
                "provenance": "unpaged detail related_read_evidence is current invocation; paged evidence is pinned origin-invocation data in the existing query plan and bound by digest; current final call remains separate. API/args/projection associations are explicit. Original request limit: 256 KiB and request/context record limit: 512 KiB are independent of origin evidence allowance: 15.5 MiB; each record and total store: 16 MiB, 128 records, 900 seconds. Capacity failures never truncate. Grouped reads are Gateway-composed, not native composition or an atomic snapshot",
                "authority": "canonical GUID membership associates read-only member values only; root and member references never certify mutation selection"},
            "outputs": {name: related_output_detail(version, name) for name in QUERY_BUSINESS_OUTPUTS},
            "result_schema": patterns,
            "result_schema_source": {"version": version, "wwise_build": graph.wwise_build, "document": "waapi_definitions.json", "pointer": "/definitions/objectReturn/patternProperties"},
            "source": {key: source[key] for key in ("version", "wwise_build", "page", "page_sha256")},
            "chain_html_lines": [rule["html_line"] for rule in source["chain_rules"]],
            "return_options_source": source["return_options_source"],
            "budget": {"shared_fixed_outputs": maximum_outputs, "shared_custom_terminals_with_root": maximum_custom_outputs, "automatic_identity_fields_per_relation": 1, "identity_and_class_helpers": "each distinct path prefix counts against the native return-expression limit", "singleton_relations": len(RELATED_QUERY_RELATIONS)},
            "terminal_semantics": "same existing output contract; volume-db/pitch-cents read local values on the related object, not cumulative levels or runtime audio",
            "identity": "root id/name/type/path unchanged; related.<singleton>.object is the native reference and related.<list>.items preserves each member identity; canonical GUID supports read-only hops, not mutation authority",
            "presence": "native absence uses group-local unavailable_fields; null/extensions/order preserved; grouped member association uses checked canonical GUIDs",
            "metadata_reads": False,
            "custom_metadata_reads": "actual related class/object discovery for custom terminals and reference hops; fixed paths and fixed outputs require none",
            "custom_terminal_options": list(RELATED_FIELD_MODES),
            "custom_terminal_modes": {option: {kind: {"native_prefix": prefix, "output_group": {"property": "properties", "reference": "references", "override_source_value": "override_source_values", "local_reference": "local_references"}[binding_kind]}
                for kind, (binding_kind, prefix) in mode.bindings.items()} for option, mode in RELATED_FIELD_MODES.items()},
            "field_value_source_evidence": reference_value_source_contract(version)["source"],
            "reference_hops": {"reference MEANING": "override-resolved singleton reference", "local-reference MEANING": "directly stored singleton reference"},
            "path_result": "one-hop keys retained; further contexts under related; reference contexts under related.references.<discovered token> or related.local_references.<discovered token>",
            "field_token_boundary": "only freshly discovered single identifier tokens compose; unexpressible tokens are an interface boundary, not native absence",
            "metadata_scope": "actual endpoint classId or canonical GUID only; complete no-match scopes can report unavailable_field_requests when another actual scope binds; empty roots or absent contexts establish no metadata authority",
            "applicability": "ordinary, broad and bounded advanced reads retain root membership, ordered identities and prefix scope facts through preparation/final read/paging; no mutation authority",
            "native_limits": {"return_expressions_including_helpers": MAX_ADVANCED_RETURN_EXPRESSIONS, "each_expression_utf8_bytes": MAX_ADVANCED_RETURN_EXPRESSION_BYTES},
            "followup": "list compositions with selectors/reducers, other functions, additional legacy spellings, states and other unproved fixed-output combinations remain unavailable through this related-output interface; this does not establish native absence"}

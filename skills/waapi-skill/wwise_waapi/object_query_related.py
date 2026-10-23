"""Closed singleton-related projections sharing the fixed business output registry."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
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
    if len(values) > MAX_ADVANCED_RETURN_EXPRESSIONS * 4:
        raise ValueError('related paths and sequence arguments exceed their bounded declaration size')
    reducer = None
    if option == '--include-related' and len(values) >= 6 and values[-5] in {'any-match-field','all-match-field'}:
        from .object_query_field_conditions import parse_field_condition
        reducer = {'operation':values[-5].removesuffix('-field'), 'condition':parse_field_condition(values[-4:])}
        values = [*values[:-5], '__sequence_value__']
    elif option == '--include-related' and len(values) >= 4 and values[-3] in {'any-match','all-match'}:
        reducer = {'operation':values[-3], 'condition':{'condition':values[-2],'value':values[-1]}}
        values = [*values[:-3], '__sequence_value__']
    elif option == '--include-related' and values[-1] in {'count','any'}:
        reducer, values = {'operation':values[-1]}, [*values[:-1], '__sequence_value__']
    tokens, terminal = values[:-1], values[-1]
    hops, index = [], 0
    while index < len(tokens):
        name = tokens[index]
        if name == 'combine' or name in RELATED_QUERY_RELATIONS or name in RELATED_QUERY_LIST_RELATIONS:
            spec = None
            if name == 'combine':
                arms, arm, depth = [], [], 0
                index += 1
                while index < len(tokens):
                    token = tokens[index]; index += 1
                    if token == 'end' and depth == 0:
                        arms.append(arm); break
                    if token == 'and' and depth == 0:
                        arms.append(arm); arm = []; continue
                    if token == 'combine': depth += 1
                    if token == 'end': depth -= 1
                    arm.append(token)
                else:
                    raise ValueError('combine requires closed arms separated by and, followed by end')
                if len(arms) < 2 or any(not arm for arm in arms):
                    raise ValueError('combine requires at least two nonempty closed path arms')
                for arm in arms:
                    if arm != ['self']:
                        parse_related_request(version,[*arm,'volume-db'],'--include-related')
                spec = {'source':'combine','arms':arms,'stages':[]}
                hops.append(('sequence',json.dumps(spec,separators=(',',':'))))
            else:
                hops.append(("list" if name in RELATED_QUERY_LIST_RELATIONS else "relation", name))
                index += 1
            if spec is not None or name in RELATED_QUERY_LIST_RELATIONS:
                stages = []
                while index < len(tokens) and tokens[index] in {"first", "last", "at", "skip", "take", "matching", "matching-field"}:
                    selection = tokens[index]; index += 1
                    stage = {"selection": selection}
                    if selection == 'matching-field':
                        from .object_query_field_conditions import parse_field_condition
                        stage = {'selection':'matching', **parse_field_condition(tokens[index:index+4])}
                        index += 4
                    if selection == 'matching':
                        if index+1 >= len(tokens):
                            raise ValueError('matching requires one disclosed business condition and value')
                        stage.update({'condition':tokens[index], 'value':tokens[index+1]}); index += 2
                    if selection in {'at','skip','take'}:
                        if index >= len(tokens) or len(tokens[index]) > MAX_ADVANCED_RETURN_EXPRESSION_BYTES or re.fullmatch(r'0|[1-9][0-9]*',tokens[index]) is None:
                            raise ValueError("related selection counts must be nonnegative decimal integers")
                        stage["count"] = int(tokens[index]); index += 1
                    stages.append(stage)
                if stages:
                    hops[-1] = ("sequence", json.dumps({**(spec or {'source':name}), 'stages': stages}, separators=(",", ":")))
        elif name in {"reference", "local-reference"} and index + 1 < len(tokens):
            hops.append((name, _meaning(tokens[index + 1])))
            index += 2
        else:
            raise ValueError(f"{option} requires disclosed relation or reference/local-reference MEANING hops")
    if reducer:
        if not hops or hops[-1][0] not in {'list','sequence'}:
            raise ValueError('related reducers require an object sequence')
        kind, name = hops[-1]
        spec = json.loads(name) if kind == 'sequence' else {'source':name,'stages':[]}
        spec['reducer'] = reducer
        hops[-1] = ('sequence',json.dumps(spec,separators=(',',':')))
    nodes = len(hops)
    for kind,name in hops:
        if kind != 'sequence': continue
        spec = json.loads(name)
        nodes += len(spec['stages'])
        for arm in spec.get('arms',[]):
            nodes += 1 if arm == ['self'] else parse_related_request(version,[*arm,'volume-db'],'--include-related')['nodes']
    if nodes > MAX_ADVANCED_RETURN_EXPRESSIONS:
        raise ValueError(f"closed related paths accept at most {MAX_ADVANCED_RETURN_EXPRESSIONS} hops")
    if option == "--include-related" and not reducer:
        detail = related_output_detail(version, terminal)
        if not detail["available"]:
            raise ValueError(f"{option} {' '.join(values)}: {detail['reason']}")
    elif option != '--include-related':
        _meaning(terminal)
    return {"hops": tuple(hops), "terminal": terminal, "option": option, "nodes":nodes, "reducer":reducer}


def related_sequence_specs(version, request):
    """Walk the same bounded record for preflight and runtime disclosure."""
    for kind,name in request['hops']:
        if kind != 'sequence': continue
        spec = json.loads(name)
        yield spec
        for arm in spec.get('arms',[]):
            if arm != ['self']:
                yield from related_sequence_specs(version,parse_related_request(version,[*arm,'volume-db'],'--include-related'))


def related_sequence_source(version):
    from .canonical import canonical_sha256
    source_path = Path(__file__).resolve().parents[1]/'references'/'semantic'/version/'query-list-output-sources.json'
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if source['version'] != version or source['wwise_build'] != load_definition_graph(version).wwise_build:
        raise ValueError('Related sequence source does not match the selected definitions')
    return {**{key:source[key] for key in ('version','wwise_build','archive','archive_sha256','page','page_sha256')},
            'sections_sha256':canonical_sha256(source['sequence_sources'])}


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
                "sequences": {"versions":list(SUPPORTED_WWISE_VERSION_KEYS),
                    "selection_tokens":['matching','matching-field','first','last','at','skip','take'],
                    "reducer_tokens":['count','any','any-match','all-match','any-match-field','all-match-field'],
                    "condition_vocabulary":"fixed matching uses exact query-schema /predicates and /predicates/kind-is/choices; metadata-bound forms use /field_conditions, freshly bound on actual members; no native accessor/operator input",
                    "combination":"combine <closed relative path> and <closed relative path> ... end; self names the current context; arm and selected-arm occurrence origins retained, explicitly scoped after any pushed matching",
                    "examples":[['children','matching','kind-is','sound','first','volume-db'],['children','count'],['children','all-match','kind-is','sound'],['combine','self','and','ancestors','end','volume-db']],
                    "arguments":"canonical nonnegative decimal integers; skip 0 is omitted; zero selection is Gateway-empty, never an unproved native take 0",
                    "result_location":"related.projections",
                    "result_shape":"ordered records with canonical spec and derivation; selected members in items (first/last/at zero-or-one), reducers in value; equal specs merge requested terminal modes; untransformed paths unchanged",
                    "derivation":"Gateway business sequence/count/any/all/concat, backed by actual bounded native query-selection/member reads; no native function-return equality or atomic snapshot. Count is an integer; any/all false on empty. Unknown data is never false/zero",
                    "execution":"owned chainable SELECT/where/positive skip/take before bounded GUID member projection; last may require a complete bounded sequence; matching keeps native predicate semantics; native member composition remains separately versioned",
                    "bounds":"existing path/selection node and declaration/output/member/read/deadline/page bounds; overflow is explicit, never a counted hidden prefix",
                    "source":{**{key:list_source[key] for key in ('version','wwise_build','archive','archive_sha256','page','page_sha256')},
                        "sections_sha256":canonical_sha256(list_source['sequence_sources'])},
                    "native_domains":"2023+ function examples are query predicates/selection; concat and one filtered return chain have explicit return examples. 2021/22 missing function sections do not establish native absence",
                    "followup":"non-object record-list descriptors, randomizer and other typed functions remain unavailable through this contract; this is not native absence"},
                "membership": "2021/2022: each actual canonical owner/relation is read with documented query SELECT, an initial window without skip, positive-offset bounded skip/final-take windows and overflow detection; no bare list return accessor is assumed",
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
            "followup": "non-object record lists, other typed functions, additional legacy spellings, states and other unproved fixed-output combinations remain unavailable through this related-output interface; this does not establish native absence"}

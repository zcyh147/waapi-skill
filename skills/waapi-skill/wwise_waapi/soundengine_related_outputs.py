"""Bounded related projections rooted in an observed runtime State or Switch."""
from __future__ import annotations

from collections.abc import Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .object_query_related import parse_related_request, RELATED_FIELD_MODES, related_query_contract
from .object_query_related_lists import RelatedListPlan
from .object_query_related_runtime import RelatedQueryError, canonical_guid

MAX_RELATED_OUTPUTS = 4
MAX_GETTER_READS = 32
MAX_HELPER_READS = 128
MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
MAX_CLARIFICATION_BYTES = 16 * 1024
RELATED_INPUTS = (("related_outputs", "soundengine_related_outputs", "--include-related"),
    *(("related_" + option.removeprefix("--include-related-").replace("-", "_") + "s",
       "soundengine_" + option[2:].replace("-", "_"), option) for option in RELATED_FIELD_MODES))


def add_soundengine_related_arguments(parser):
    for _, attribute, option in RELATED_INPUTS:
        parser.add_argument(option, dest=attribute, nargs="+", action="append", default=[])


def compile_soundengine_related_requests(args, version):
    requests, declarations = [], {}
    for name, attribute, option in RELATED_INPUTS:
        values = getattr(args, attribute)
        if values:
            declarations[name] = values
        requests.extend(parse_related_request(version, value, option) for value in values)
    if len(requests) > MAX_RELATED_OUTPUTS:
        raise ValueError("SoundEngine getter accepts at most four related output declarations")
    if len({canonical_sha256(request) for request in requests}) != len(requests):
        raise ValueError("SoundEngine related output declarations must be unique")
    return requests, declarations


def soundengine_related_contract(version):
    shared = related_query_contract(version, maximum_outputs=MAX_RELATED_OUTPUTS, maximum_custom_outputs=8)
    return {"inputs": {name: {"flag": option, "repeatable": True, "values": "closed path followed by terminal"}
            for name, _, option in RELATED_INPUTS},
        "vocabulary": "query-schema /related_outputs for the selected Wwise version",
        "relations": shared["relations"], "list_members": shared["list_members"],
        "reference_hops": shared["reference_hops"], "custom_terminal_modes": shared["custom_terminal_modes"],
        "outputs": {name: detail for name, detail in shared["outputs"].items() if detail["available"]},
        "observation": "bounded runtime getter preparation; exact State/Switch GUID/type/identity scope guarded on every getter including final read",
        "values": "final native getter supplies singleton and native-composed values; grouped members, sequences and contexts retain separately disclosed helper-read provenance",
        "atomic_snapshot": False, "mutation_authority": False,
        "limits": {"declarations": MAX_RELATED_OUTPUTS, "getter_reads": MAX_GETTER_READS,
            "helper_reads": MAX_HELPER_READS, "aggregate_observation_bytes": MAX_OBSERVATION_BYTES,
            "clarification_bytes": MAX_CLARIFICATION_BYTES}}


class SoundEngineRelatedProjection:
    def __init__(self, *, version, requests, bindings, getter, read, scope, expected_type, before_getter, compile_condition):
        self.getter, self.read, self.scope = getter, read, dict(scope)
        self.expected_type, self.before_getter = expected_type, before_getter
        self.getter_count = self.helper_count = self.total_bytes = 0
        self.identity = None
        self.plan = RelatedListPlan(version=version, requests=requests, bindings=bindings, build_preview=None,
            read=self.read_helper, maximum_rows=1, maximum_read_bytes=MAX_OBSERVATION_BYTES,
            compile_condition=compile_condition, root_observer=self.observe)

    def charge(self, result):
        self.total_bytes += len(canonical_json_bytes(result))
        if self.total_bytes > MAX_OBSERVATION_BYTES:
            raise RelatedQueryError("SoundEngine related preparation exceeded its aggregate byte budget", code="SOUNDENGINE_RELATED_OBSERVATION_LIMIT")

    def reserve_getter(self):
        if self.getter_count >= MAX_GETTER_READS:
            raise RelatedQueryError("SoundEngine related preparation exceeded its getter-read budget", code="SOUNDENGINE_RELATED_OBSERVATION_LIMIT")
        self.before_getter()
        self.getter_count += 1

    def read_helper(self, uri, args, options):
        if self.helper_count >= MAX_HELPER_READS:
            raise RelatedQueryError("SoundEngine related preparation exceeded its helper-read budget", code="SOUNDENGINE_RELATED_OBSERVATION_LIMIT")
        self.helper_count += 1
        result = self.read(uri, args, options)
        self.charge(result)
        return result

    def accept_result(self, result):
        self.charge(result)
        row = result.get("return") if isinstance(result, Mapping) else None
        if (not isinstance(row, Mapping) or not canonical_guid(row.get("id"))
                or row.get("type") != self.expected_type
                or not all(isinstance(row.get(key), str) and row[key] for key in ("name", "path"))
                or type(row.get("classId")) is not int or not 0 <= row["classId"] <= 0xFFFFFFFF):
            raise RelatedQueryError("Runtime related projection requires one complete State/Switch identity and class", code="SOUNDENGINE_RELATED_RESULT_SHAPE")
        identity = {key: row[key] for key in ("id", "name", "type", "path", "classId")}
        identity["id"] = identity["id"].upper()
        if self.identity is not None and identity != self.identity:
            raise RelatedQueryError("Runtime State/Switch identity changed during related projection; restart the read", code="SOUNDENGINE_RELATED_SCOPE_CHANGED")
        self.identity = identity
        return dict(row)

    def observe(self, fields):
        self.reserve_getter()
        row = self.accept_result(self.getter({**self.scope, "return": list(fields)}))
        return [row], self.scope

    def prepare(self):
        clarification = self.plan.prepare()
        if clarification is not None:
            if len(canonical_json_bytes(clarification)) > MAX_CLARIFICATION_BYTES:
                raise RelatedQueryError("SoundEngine related clarification exceeded its byte budget", code="SOUNDENGINE_RELATED_OBSERVATION_LIMIT")
            raise RelatedQueryError("Refine the related field meanings in their actual metadata scopes", code="SOUNDENGINE_FIELD_SELECTION_REQUIRED", details=clarification)

    def final_options(self):
        self.reserve_getter()
        return {**self.scope, "return": list(self.plan.render(self.plan.root, root=True))}

    def project(self, result):
        row = self.accept_result(result)
        return self.plan.project([row])[0]

    def proof(self):
        helper_values = self.plan.has_sequences or self.plan.context_observed or (not self.plan.composed and bool(self.plan.root.lists))
        return {"native_final_getter_values": not helper_values,
            "helper_value_semantics": "separately observed members/sequences/contexts" if helper_values else "metadata preparation only",
            "atomic_snapshot": False, "mutation_authority": False,
            "getter_read_count": self.getter_count, "helper_read_count": self.helper_count,
            "observation_bytes": self.total_bytes, "scope_sha256": canonical_sha256(self.identity),
            "related_scope_sha256": self.plan.proof()["observed_scope_sha256"]}

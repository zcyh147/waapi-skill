"""Closed pre-Codex business-plan sections for the five heavy SoundBank APIs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_archive_paths import (
    ArchiveAbsolutePath,
    ArchiveRelativePathError,
    archive_relative_from_absolute,
    parse_archive_absolute_path,
    parse_archive_relative_path,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    V3GatewayProtocol,
    build_direct_protocol,
    build_transaction_protocol,
    wait_topic_step,
)
from tests.semantic.support.codex_filesystem_security import (
    CodexFileSecurityError,
    read_bounded_exclusive_regular_file,
)
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    MAX_FILE_BYTES,
    OPERATION_REQUEST_CONTRACT,
    PROCESS_REFUSAL_ERROR_CODE,
    SOUNDBANK_APIS,
    SOUNDBANK_TOPIC,
    SUPPORTED_VERSIONS,
    MaterializedSoundBankCase,
    SoundBankSnapshot,
    TopicPlan,
)


class SoundBankBusinessPlanError(ValueError):
    """A SoundBank typed plan is misbound, mutable, or incomplete."""


SOUNDBANK_SCHEMA = "waapi-skill.soundbank-business-plan/v3"
TOPIC_ACK_REQUIREMENT_CONTRACT = (
    "waapi-skill.soundbank-topic-subscription-ack-requirement/v1"
)
TOPIC_ACK_CONTRACT = "waapi-skill.broker-subscription-ack/v2"
TOPIC_ACK_PROOF_CONTRACT = "waapi-skill.soundbank-topic-ack-proof/v1"
_GUID = re.compile(r"^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$", re.IGNORECASE)
_FUNCTION_ASSERTIONS = (
    "soundbank.request.exact", "soundbank.files.exact", "soundbank.live_ids",
    "soundbank.before_snapshot", "soundbank.delta.exact",
)
_TOPIC_ASSERTIONS = (
    "soundbank.topic.subscription", "soundbank.topic.publisher_runner_only",
    "soundbank.topic.subscribe_ack_before_publish",
    "soundbank.topic.events_exact", "soundbank.before_snapshot", "soundbank.delta.artifacts",
)
_REFUSAL_ASSERTIONS = (
    "soundbank.refusal.exact", "soundbank.refusal.unknown_identity", "soundbank.refusal.before_equals_after",
)
_DEFINITION_FILTER_TO_INCLUSION = MappingProxyType(
    {
        "Event": "events",
        "Structure": "structures",
        "Media": "media",
    }
)


@dataclass(frozen=True, slots=True)
class SoundBankBusinessPlanSections:
    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]

    def writer_kwargs(self) -> dict[str, Any]:
        return {
            "fixture_spec": _plain(self.fixture_spec), "payload_bindings": _plain(self.payload_bindings),
            "assertion_ids": list(self.assertion_ids), "static_expectation": _plain(self.static_expectation),
            "live_binding": _plain(self.live_binding), "delta_rules": [_plain(item) for item in self.delta_rules],
        }


def compile_soundbank_business_plan(
    materialized: MaterializedSoundBankCase,
    before: SoundBankSnapshot,
    protocol: V3GatewayProtocol,
) -> SoundBankBusinessPlanSections:
    """Compile one closed family section after fixture materialization only."""

    _validate_inputs(materialized, before, protocol)
    blueprint = materialized.blueprint
    static = _static(materialized)
    live = _live(materialized, before)
    if blueprint.api == SOUNDBANK_TOPIC:
        topic = materialized.topic_plan
        assert topic is not None
        return _sections(
            "soundbank_topic_materialized_v1", ("soundbank.generated.wait",), (), _TOPIC_ASSERTIONS,
            static, live, (_topic_delta(topic, before),),
        )
    if blueprint.expected_primary_dispatch_count == 0:
        return _sections(
            "soundbank_refusal_materialized_v1", (), ("tx01.operation-schema", "tx01.preview"), _REFUSAL_ASSERTIONS,
            static, live, (_refusal_delta(blueprint.zero_dispatch_error_code or "", before),),
        )
    primary = tuple(step["name"] for step in _protocol(protocol)["steps"] if step["subcommand"] == "execute")
    verification = tuple(step["name"] for step in _protocol(protocol)["steps"] if step["subcommand"] != "execute")
    return _sections("soundbank_function_materialized_v1", primary, verification, _FUNCTION_ASSERTIONS, static, live, (_function_delta(materialized, before),))


def validate_soundbank_business_plan(
    sections: SoundBankBusinessPlanSections,
    materialized: MaterializedSoundBankCase,
    before: SoundBankSnapshot,
    protocol: V3GatewayProtocol,
    *,
    verify_files: bool = False,
) -> None:
    expected = compile_soundbank_business_plan(materialized, before, protocol)
    if not isinstance(sections, SoundBankBusinessPlanSections) or sections.writer_kwargs() != expected.writer_kwargs():
        raise SoundBankBusinessPlanError("SoundBank sections differ from runner-owned recomputation")
    if verify_files:
        _verify_files(before.input_files)


def soundbank_archive_identity(materialized: MaterializedSoundBankCase) -> dict[str, Any]:
    """Return the runner-owned identity record required for archive checks."""

    if not isinstance(materialized, MaterializedSoundBankCase):
        raise SoundBankBusinessPlanError("archive identity requires a materialized SoundBank case")
    blueprint = materialized.blueprint
    fixture = getattr(blueprint.scenario, "fixture", None)
    if not isinstance(fixture, Mapping):
        raise SoundBankBusinessPlanError("archive identity requires the reviewed scenario fixture")
    return {
        "scenario_id": blueprint.scenario_id,
        "api": blueprint.api,
        "version": blueprint.version,
        "primary_dispatch_count": blueprint.expected_primary_dispatch_count,
        "fixture": _json(fixture),
    }


def parse_soundbank_business_plan_sections(payload: Mapping[str, Any]) -> SoundBankBusinessPlanSections:
    required = {"fixture_spec", "payload_bindings", "assertion_ids", "static_expectation", "live_binding", "delta_rules"}
    if not isinstance(payload, Mapping) or not required.issubset(payload):
        raise SoundBankBusinessPlanError("persisted SoundBank plan lacks typed sections")
    values = {name: payload[name] for name in required}
    if not all(isinstance(values[name], Mapping) for name in ("fixture_spec", "payload_bindings", "static_expectation", "live_binding")) or not isinstance(values["assertion_ids"], (list, tuple)) or not isinstance(values["delta_rules"], (list, tuple)):
        raise SoundBankBusinessPlanError("persisted SoundBank section types are invalid")
    sections = SoundBankBusinessPlanSections(
        MappingProxyType(_json(values["fixture_spec"])), MappingProxyType(_json(values["payload_bindings"])), tuple(_json(values["assertion_ids"])),
        MappingProxyType(_json(values["static_expectation"])), MappingProxyType(_json(values["live_binding"])),
        tuple(MappingProxyType(_json(item)) for item in values["delta_rules"]),
    )
    _archive_shape(sections)
    return sections


def validate_soundbank_business_plan_archive(
    sections: SoundBankBusinessPlanSections,
    protocol: V3GatewayProtocol,
    *,
    scenario: Any,
) -> None:
    """Validate archived sections without a live Wwise object graph."""

    _archive_shape(sections)
    static, live = sections.static_expectation, sections.live_binding
    api = static["api"]
    kind = sections.fixture_spec["kind"]
    if static["family_schema_version"] != SOUNDBANK_SCHEMA or api not in SOUNDBANK_APIS:
        raise SoundBankBusinessPlanError("archived SoundBank family/API is invalid")
    expected_identity = _scenario_identity(scenario)
    if expected_identity != {
        "scenario_id": static["scenario_id"], "api": api, "version": static["version"],
        "primary_dispatch_count": static["expected_primary_dispatch_count"],
        "scenario_fixture_sha256": static["scenario_fixture_sha256"],
    }:
        raise SoundBankBusinessPlanError("archived SoundBank scenario identity is not independently bound")
    if live["before_snapshot_sha256"] != _sha(live["before_snapshot"]):
        raise SoundBankBusinessPlanError("archived SoundBank before snapshot fingerprint drifted")
    _validate_archive_inputs(static, live)
    if api == SOUNDBANK_TOPIC:
        if kind != "soundbank_topic_materialized_v1" or sections.assertion_ids != _TOPIC_ASSERTIONS:
            raise SoundBankBusinessPlanError("archived topic kind/assertions drifted")
        expected_primary, expected_verification = ["soundbank.generated.wait"], []
        expected_delta = _topic_archive_delta(static, live)
        if live["topic"]["event_count"] != len(live["topic"]["expected_events"]):
            raise SoundBankBusinessPlanError("topic event count is not closed")
        if any(name == "soundbank.generated.wait" for name in live["topic"]["publisher_steps"]):
            raise SoundBankBusinessPlanError("runner publisher was recorded as a model wait step")
    elif static["zero_dispatch_error_code"] is not None:
        if kind != "soundbank_refusal_materialized_v1" or sections.assertion_ids != _REFUSAL_ASSERTIONS:
            raise SoundBankBusinessPlanError("archived refusal kind/assertions drifted")
        expected_primary, expected_verification = [], ["tx01.operation-schema", "tx01.preview"]
        expected_delta = _refusal_archive_delta(static, live)
    else:
        if kind != "soundbank_function_materialized_v1" or sections.assertion_ids != _FUNCTION_ASSERTIONS:
            raise SoundBankBusinessPlanError("archived function kind/assertions drifted")
        expected = build_transaction_protocol(static["operation_requests"])
        serial = _protocol(expected)
        expected_primary = [step["name"] for step in serial["steps"] if step["subcommand"] == "execute"]
        expected_verification = [step["name"] for step in serial["steps"] if step["subcommand"] != "execute"]
        expected_delta = _function_archive_delta(static, live)
    if _protocol(protocol) != _expected_protocol_archive(static, live, protocol):
        raise SoundBankBusinessPlanError("archived SoundBank protocol drifted")
    if sections.payload_bindings != {"primary_steps": expected_primary, "verification_steps": expected_verification} or sections.delta_rules != (expected_delta,):
        raise SoundBankBusinessPlanError("archived SoundBank dispatch/delta drifted")
    if sections.fixture_spec["sha256"] != _sha({"static": static, "live": live}):
        raise SoundBankBusinessPlanError("archived SoundBank fixture digest drifted")


def validate_soundbank_archived_verification(sections: SoundBankBusinessPlanSections, verification: Mapping[str, Any]) -> None:
    """Bind post-run oracle evidence to a sealed SoundBank plan."""

    _archive_shape(sections)
    value = verification.get("verification", verification) if isinstance(verification, Mapping) else None
    if not isinstance(value, Mapping):
        raise SoundBankBusinessPlanError("archived SoundBank verification is invalid")
    live = sections.live_binding
    static = sections.static_expectation
    _io_root, source_flavor, _dynamic_roots, _managed = (
        _archive_output_policy(static)
    )
    _validate_snapshot_path_sets(
        live["before_snapshot"], source_flavor=source_flavor
    )
    if static["api"] == SOUNDBANK_TOPIC:
        if set(value) != {"topic", "artifacts"}:
            raise SoundBankBusinessPlanError("archived topic verification schema is not closed")
        _validate_topic_result(value["topic"], static["scenario_id"], live["topic"])
        _validate_runtime_result(value["artifacts"], static["scenario_id"], "topic_artifacts", live["before_snapshot"])
        _validate_after_delta(static, live, value["artifacts"]["after"])
        return
    phase = "zero_dispatch" if static["zero_dispatch_error_code"] is not None else "after_execution"
    allowed = {"scenario_id", "phase", "passed", "failures", "before", "after"}
    if set(value) != allowed:
        raise SoundBankBusinessPlanError("archived SoundBank verification schema is not closed")
    _validate_runtime_result(value, static["scenario_id"], phase, live["before_snapshot"])
    if static["zero_dispatch_error_code"] is not None:
        _validate_snapshot_path_sets(
            value["after"], source_flavor=source_flavor
        )
        if value["after"] != live["before_snapshot"]:
            raise SoundBankBusinessPlanError("archived refusal verification must prove before equals after")
        return
    _validate_after_delta(static, live, value["after"])


def _validate_inputs(materialized: MaterializedSoundBankCase, before: SoundBankSnapshot, protocol: V3GatewayProtocol) -> None:
    if not isinstance(materialized, MaterializedSoundBankCase) or not isinstance(before, SoundBankSnapshot):
        raise SoundBankBusinessPlanError("compiler requires materialized SoundBank case and snapshot")
    blueprint = materialized.blueprint
    if blueprint.version not in SUPPORTED_VERSIONS or blueprint.api not in SOUNDBANK_APIS or before.scenario_id != blueprint.scenario_id:
        raise SoundBankBusinessPlanError("SoundBank materialization identity is invalid")
    if blueprint.api == SOUNDBANK_TOPIC:
        if materialized.topic_plan is None or materialized.operation_requests or materialized.topic_plan.event_count != blueprint.expected_primary_dispatch_count:
            raise SoundBankBusinessPlanError("topic must have only a closed topic plan")
        topic = materialized.topic_plan
        expected = build_direct_protocol([
            wait_topic_step("soundbank.generated.wait", topic.topic, event_count=topic.event_count, match=topic.match, options=topic.options),
        ])
    elif materialized.topic_plan is not None or not materialized.operation_requests:
        raise SoundBankBusinessPlanError("function/refusal materialization has invalid request topology")
    else:
        if blueprint.expected_primary_dispatch_count > 0 and len(materialized.operation_requests) != blueprint.expected_primary_dispatch_count:
            raise SoundBankBusinessPlanError("function request count does not close primary dispatches")
        if blueprint.expected_primary_dispatch_count == 0 and len(materialized.operation_requests) != 1:
            raise SoundBankBusinessPlanError("zero-dispatch refusal must retain its one refused request")
        expected = build_transaction_protocol(
            materialized.operation_requests,
            refusal=StructuredRefusal(blueprint.zero_dispatch_error_code) if blueprint.expected_primary_dispatch_count == 0 else None,
        )
    if blueprint.expected_primary_dispatch_count == 0:
        if blueprint.zero_dispatch_error_code != PROCESS_REFUSAL_ERROR_CODE:
            raise SoundBankBusinessPlanError("zero-dispatch refusal lacks exact unknown-identity code")
    if _protocol(protocol) != _protocol(expected):
        raise SoundBankBusinessPlanError("SoundBank protocol does not exactly bind sealed requests and transaction order")


def _static(case: MaterializedSoundBankCase) -> dict[str, Any]:
    blue = case.blueprint
    fixture = getattr(blue.scenario, "fixture", None)
    if not isinstance(fixture, Mapping):
        raise SoundBankBusinessPlanError("SoundBank materialization lacks its reviewed scenario fixture")
    return _json({
        "family_schema_version": SOUNDBANK_SCHEMA, "scenario_id": blue.scenario_id, "api": blue.api, "version": blue.version,
        "scenario_fixture_sha256": _sha(fixture),
        "expected_primary_dispatch_count": blue.expected_primary_dispatch_count, "zero_dispatch_error_code": blue.zero_dispatch_error_code,
        "operation_requests": case.operation_requests, "definitions": blue.definitions, "external_documents": blue.external_documents,
        "expected_artifacts": case.expected_artifacts, "soundbanks": blue.soundbanks,
        "io_root": str(blue.io_root.resolve(strict=False)),
        "dynamic_output_policy": _dynamic_output_policy(case),
        "managed_side_effects": _managed_side_effects(case),
    })


def _live(case: MaterializedSoundBankCase, before: SoundBankSnapshot) -> dict[str, Any]:
    topic = case.topic_plan
    return _json({
        "before_snapshot": before, "before_snapshot_sha256": _sha(before), "input_files": case.input_files,
        "object_ids": case.object_ids, "short_ids": case.short_ids, "media_ids": case.media_ids,
        "platform_ids": case.platform_ids, "language_ids": case.language_ids,
        "set_inclusion_after": _set_inclusion_after(case),
        "topic": None if topic is None else {
            "topic": topic.topic, "event_count": topic.event_count, "match": topic.match, "options": topic.options,
            "expected_events": topic.expected_events, "publisher_requests": [item.operation_request for item in topic.publishers],
            "publisher_steps": [f"publisher.{index:02d}" for index, _item in enumerate(topic.publishers, 1)],
            "reject_n_plus_one": topic.reject_n_plus_one,
            "subscription_ack_requirement": _topic_ack_requirement(topic),
        },
    })


def _function_delta(case: MaterializedSoundBankCase, before: SoundBankSnapshot) -> dict[str, Any]:
    inclusion = case.blueprint.api == "ak.wwise.core.soundbank.setInclusions"
    return _json({"enum": "soundbank.set_inclusions_delta_v1" if inclusion else "soundbank.function_delta_v1",
                  "before_set_algebra": before.banks if inclusion else None,
                  "before_bank_sets": before.banks if not inclusion else None,
                  "expected_artifacts": case.expected_artifacts, "input_files_sha256": _sha(before.input_files),
                  "project_files_sha256": _sha(before.project_files), "output_files_sha256": _sha(before.output_files)})


def _topic_delta(topic: TopicPlan, before: SoundBankSnapshot) -> dict[str, Any]:
    return _json({"enum": "soundbank.topic_delta_v1", "event_count": topic.event_count,
                  "expected_event_keys": [item.key for item in topic.expected_events],
                  "publisher_request_sha256": [_sha(item.operation_request) for item in topic.publishers],
                  "subscription_ack_requirement": _topic_ack_requirement(topic),
                  "before_output_files_sha256": _sha(before.output_files), "before_project_files_sha256": _sha(before.project_files)})


def _refusal_delta(error_code: str, before: SoundBankSnapshot) -> dict[str, Any]:
    return _json({"enum": "soundbank.refusal_no_delta_v1", "error_code": error_code,
                  "before_snapshot_sha256": _sha(before), "unknown_identity_required": True})


def _function_archive_delta(static: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    before = live["before_snapshot"]
    inclusion = static["api"] == "ak.wwise.core.soundbank.setInclusions"
    return {"enum": "soundbank.set_inclusions_delta_v1" if inclusion else "soundbank.function_delta_v1",
            "before_set_algebra": before["banks"] if inclusion else None,
            "before_bank_sets": before["banks"] if not inclusion else None,
            "expected_artifacts": static["expected_artifacts"],
            "input_files_sha256": _sha(before["input_files"]), "project_files_sha256": _sha(before["project_files"]), "output_files_sha256": _sha(before["output_files"])}


def _topic_archive_delta(static: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    topic, before = live["topic"], live["before_snapshot"]
    return {"enum": "soundbank.topic_delta_v1", "event_count": topic["event_count"], "expected_event_keys": [_event_key(item) for item in topic["expected_events"]],
            "publisher_request_sha256": [_sha(item) for item in topic["publisher_requests"]],
            "subscription_ack_requirement": topic["subscription_ack_requirement"],
            "before_output_files_sha256": _sha(before["output_files"]), "before_project_files_sha256": _sha(before["project_files"])}


def _topic_ack_requirement(topic: TopicPlan) -> dict[str, Any]:
    return {
        "contract": TOPIC_ACK_REQUIREMENT_CONTRACT,
        "ack_contract": TOPIC_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": topic.topic,
        "fresh_exclusive_path_required": True,
        "publisher_requires_valid_ack": True,
    }


def _refusal_archive_delta(static: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    return {"enum": "soundbank.refusal_no_delta_v1", "error_code": static["zero_dispatch_error_code"], "before_snapshot_sha256": _sha(live["before_snapshot"]), "unknown_identity_required": True}


def _expected_protocol_archive(static: Mapping[str, Any], live: Mapping[str, Any], protocol: V3GatewayProtocol) -> dict[str, Any]:
    if static["api"] == SOUNDBANK_TOPIC:
        topic = live["topic"]
        return _protocol(build_direct_protocol([wait_topic_step("soundbank.generated.wait", topic["topic"], event_count=topic["event_count"], match=topic["match"], options=topic["options"])]))
    return _protocol(build_transaction_protocol(static["operation_requests"], refusal=None if static["zero_dispatch_error_code"] is None else _refusal(static["zero_dispatch_error_code"])))


def _refusal(code: str):
    return StructuredRefusal(code)


def _sections(kind: str, primary: Sequence[str], verify: Sequence[str], assertions: Sequence[str], static: Mapping[str, Any], live: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]) -> SoundBankBusinessPlanSections:
    return SoundBankBusinessPlanSections(MappingProxyType({"kind": kind, "sha256": _sha({"static": static, "live": live})}), MappingProxyType({"primary_steps": list(primary), "verification_steps": list(verify)}), tuple(assertions), MappingProxyType(_json(static)), MappingProxyType(_json(live)), tuple(MappingProxyType(_json(item)) for item in rules))


def _archive_shape(value: SoundBankBusinessPlanSections) -> None:
    if not isinstance(value, SoundBankBusinessPlanSections) or set(value.fixture_spec) != {"kind", "sha256"} or set(value.payload_bindings) != {"primary_steps", "verification_steps"}:
        raise SoundBankBusinessPlanError("SoundBank archive common shape is not closed")
    static = value.static_expectation
    keys = {"family_schema_version", "scenario_id", "api", "version", "scenario_fixture_sha256", "expected_primary_dispatch_count", "zero_dispatch_error_code", "operation_requests", "definitions", "external_documents", "expected_artifacts", "soundbanks", "io_root", "dynamic_output_policy", "managed_side_effects"}
    live = {"before_snapshot", "before_snapshot_sha256", "input_files", "object_ids", "short_ids", "media_ids", "platform_ids", "language_ids", "set_inclusion_after", "topic"}
    if set(static) != keys or set(value.live_binding) != live or len(value.delta_rules) != 1:
        raise SoundBankBusinessPlanError("SoundBank archive family shape is not closed")


def _protocol(protocol: V3GatewayProtocol) -> dict[str, Any]:
    if not isinstance(protocol, V3GatewayProtocol):
        raise SoundBankBusinessPlanError("SoundBank protocol has the wrong type")
    return _json(serialize_protocol(protocol))


def _event_key(value: Mapping[str, Any]) -> list[Any]:
    return [str(value["soundbank_id"]).casefold(), str(value["platform_id"]).casefold(), str(value["language_id"]).casefold() if value.get("language_id") is not None else None]


def _scenario_identity(scenario: Any) -> dict[str, Any]:
    if isinstance(scenario, Mapping):
        values = scenario
        count = values.get("primary_dispatch_count", values.get("expected_primary_dispatch_count"))
        scenario_id = values.get("scenario_id", values.get("id"))
        fixture = values.get("fixture")
    else:
        values = scenario
        dispatch = getattr(values, "primary_dispatch", None)
        count = getattr(values, "primary_dispatch_count", getattr(values, "expected_primary_dispatch_count", getattr(dispatch, "count", None)))
        scenario_id = getattr(values, "scenario_id", getattr(values, "id", None))
        fixture = getattr(values, "fixture", None)
    result = {"scenario_id": scenario_id, "api": values.get("api") if isinstance(values, Mapping) else getattr(values, "api", None),
              "version": values.get("version") if isinstance(values, Mapping) else getattr(values, "version", None),
              "primary_dispatch_count": count, "scenario_fixture_sha256": _sha(fixture) if isinstance(fixture, Mapping) else None}
    if not isinstance(result["scenario_id"], str) or not isinstance(result["api"], str) or not isinstance(result["version"], str) or type(count) is not int or not _sha_text(result["scenario_fixture_sha256"]):
        raise SoundBankBusinessPlanError("archive validator requires an independent scenario identity")
    return result


def _validate_archive_inputs(static: Mapping[str, Any], live: Mapping[str, Any]) -> None:
    count = static["expected_primary_dispatch_count"]
    requests = static["operation_requests"]
    if type(count) is not int or count < 0 or not isinstance(requests, list):
        raise SoundBankBusinessPlanError("archived SoundBank dispatch/request shape is invalid")
    (
        io_root,
        _io_root_flavor,
        _dynamic_roots,
        _managed_side_effects,
    ) = _archive_output_policy(static)
    topic = live["topic"]
    if static["api"] == SOUNDBANK_TOPIC:
        expected_topic_keys = {
            "topic",
            "event_count",
            "match",
            "options",
            "expected_events",
            "publisher_requests",
            "publisher_steps",
            "reject_n_plus_one",
            "subscription_ack_requirement",
        }
        if (
            requests
            or not isinstance(topic, Mapping)
            or set(topic) != expected_topic_keys
            or topic.get("event_count") != count
        ):
            raise SoundBankBusinessPlanError("archived SoundBank topic dispatch shape is invalid")
        ack_requirement = topic.get("subscription_ack_requirement")
        if ack_requirement != {
            "contract": TOPIC_ACK_REQUIREMENT_CONTRACT,
            "ack_contract": TOPIC_ACK_CONTRACT,
            "step_name": "soundbank.generated.wait",
            "topic": SOUNDBANK_TOPIC,
            "fresh_exclusive_path_required": True,
            "publisher_requires_valid_ack": True,
        }:
            raise SoundBankBusinessPlanError(
                "archived SoundBank topic subscription ACK requirement drifted"
            )
    elif count == 0:
        if static["zero_dispatch_error_code"] != PROCESS_REFUSAL_ERROR_CODE or len(requests) != 1:
            raise SoundBankBusinessPlanError("archived SoundBank refusal is not closed")
    elif static["zero_dispatch_error_code"] is not None or len(requests) != count or topic is not None:
        raise SoundBankBusinessPlanError("archived SoundBank function dispatch shape is invalid")
    scoped_requests = topic["publisher_requests"] if static["api"] == SOUNDBANK_TOPIC else requests
    for request in scoped_requests:
        arguments = request.get("arguments") if isinstance(request, Mapping) else None
        if not isinstance(arguments, Mapping):
            raise SoundBankBusinessPlanError(
                "archived SoundBank operation request arguments are invalid"
            )
        request_io_root = arguments.get("io_root")
        if (
            request.get("operation") == "soundbank.generate"
            and request_io_root != str(io_root)
        ) or (
            request_io_root is not None and request_io_root != str(io_root)
        ):
            raise SoundBankBusinessPlanError(
                "archived SoundBank request io_root differs from output authority"
            )
    for field in ("object_ids", "platform_ids", "language_ids"):
        if not isinstance(live[field], Mapping) or any(not isinstance(key, str) or not _GUID.fullmatch(value) for key, value in live[field].items()):
            raise SoundBankBusinessPlanError("archived SoundBank GUID bindings are invalid")
    for field in ("short_ids", "media_ids"):
        if not isinstance(live[field], Mapping) or any(not isinstance(key, str) or type(value) is not int or value < 0 for key, value in live[field].items()):
            raise SoundBankBusinessPlanError("archived SoundBank numeric ID bindings are invalid")
    if not isinstance(live["input_files"], list):
        raise SoundBankBusinessPlanError("archived SoundBank input files lack path-size-sha proofs")
    input_relative_paths: set[str] = set()
    for item in live["input_files"]:
        if (
            not isinstance(item, Mapping)
            or set(item)
            != {"path", "relative_path", "size", "sha256", "mtime_ns"}
            or not isinstance(item["path"], str)
            or not isinstance(item["relative_path"], str)
            or type(item["size"]) is not int
            or not 0 < item["size"] <= MAX_FILE_BYTES
            or not _sha_text(item["sha256"])
        ):
            raise SoundBankBusinessPlanError(
                "archived SoundBank input files lack path-size-sha proofs"
            )
        try:
            parse_archive_absolute_path(item["path"])
            relative = parse_archive_relative_path(item["relative_path"]).canonical
        except ArchiveRelativePathError as exc:
            raise SoundBankBusinessPlanError(
                "archived SoundBank input file path is invalid"
            ) from exc
        if relative in input_relative_paths:
            raise SoundBankBusinessPlanError(
                "archived SoundBank input file relative paths are duplicated"
            )
        input_relative_paths.add(relative)
    if live["input_files"] != live["before_snapshot"].get("input_files"):
        raise SoundBankBusinessPlanError("archived SoundBank live input manifest differs from the sealed before snapshot")
    reviewed_documents = {
        document.get("path")
        for collection in (static["definitions"], static["external_documents"])
        for document in collection
        if isinstance(document, Mapping) and isinstance(document.get("path"), str)
    }
    if not reviewed_documents.issubset({item["path"] for item in live["input_files"]}):
        raise SoundBankBusinessPlanError("archived SoundBank reviewed definition/external files are absent from the input manifest")
    if topic is not None:
        events = topic.get("expected_events") if isinstance(topic, Mapping) else None
        if not isinstance(events, list) or len(events) != topic.get("event_count") or any(
            not isinstance(item, Mapping) or not all(_GUID.fullmatch(item.get(field, "")) for field in ("soundbank_id", "platform_id"))
            or item.get("language_id") is not None and not _GUID.fullmatch(item["language_id"])
            for item in events
        ):
            raise SoundBankBusinessPlanError("archived SoundBank topic identities are invalid")


def _set_inclusion_after(case: MaterializedSoundBankCase) -> dict[str, Any] | None:
    if case.blueprint.api != "ak.wwise.core.soundbank.setInclusions":
        return None
    spec = case.blueprint.asset_spec
    name = str(spec["soundbank"])
    expected = []
    by_name = {item.name: item for item in case.blueprint.object_fixtures}
    for row in spec["expected_after"]:
        fixture = by_name.get(str(row["object"]))
        if fixture is None or fixture.key not in case.object_ids:
            raise SoundBankBusinessPlanError("setInclusions expected row lacks sealed object identity")
        expected.append([case.object_ids[fixture.key].casefold(), sorted(row["filters"])])
    return {"bank_name": name, "bank_id": case.object_ids.get(f"bank:{name}"), "inclusions": sorted(expected)}


def _validate_runtime_result(value: Any, scenario_id: str, phase: str, before: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise SoundBankBusinessPlanError("archived SoundBank runtime verification is invalid")
    required = {"scenario_id", "phase", "passed", "failures", "before", "after"}
    if not required.issubset(value) or value.get("scenario_id") != scenario_id or value.get("phase") != phase:
        raise SoundBankBusinessPlanError("archived SoundBank verification identity/phase drifted")
    if value.get("passed") is not True or value.get("failures") not in ([], ()) or value.get("before") != before:
        raise SoundBankBusinessPlanError("archived SoundBank verification baseline is not a passed result")
    if not isinstance(value.get("after"), Mapping):
        raise SoundBankBusinessPlanError("archived SoundBank verification lacks an after snapshot")


def _validate_topic_result(value: Any, scenario_id: str, topic: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != {"scenario_id", "passed", "failures", "observed_keys", "expected_keys"} or value.get("scenario_id") != scenario_id or value.get("passed") is not True or value.get("failures") not in ([], ()):
        raise SoundBankBusinessPlanError("archived SoundBank topic result is not a passed result")
    expected = [_event_key(item) for item in topic["expected_events"]]
    observed = value.get("observed_keys")
    if value.get("expected_keys") != expected or not isinstance(observed, list):
        raise SoundBankBusinessPlanError("archived SoundBank topic identities drifted")

    normalized_observed: list[tuple[str, str, str | None]] = []
    for row in observed:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[0], str)
            or _GUID.fullmatch(row[0]) is None
            or not isinstance(row[1], str)
            or _GUID.fullmatch(row[1]) is None
            or (
                row[2] is not None
                and (
                    not isinstance(row[2], str)
                    or _GUID.fullmatch(row[2]) is None
                )
            )
        ):
            raise SoundBankBusinessPlanError(
                "archived SoundBank topic identities drifted"
            )
        normalized_observed.append(
            (
                row[0].casefold(),
                row[1].casefold(),
                row[2].casefold() if row[2] is not None else None,
            )
        )

    expected_counts: dict[tuple[str, str, str | None], int] = {}
    observed_counts: dict[tuple[str, str, str | None], int] = {}
    for row in expected:
        key = (row[0], row[1], row[2])
        expected_counts[key] = expected_counts.get(key, 0) + 1
    for key in normalized_observed:
        observed_counts[key] = observed_counts.get(key, 0) + 1
    if observed_counts != expected_counts:
        raise SoundBankBusinessPlanError("archived SoundBank topic identities drifted")


def _validate_after_delta(static: Mapping[str, Any], live: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if set(after) != {"scenario_id", "objects", "banks", "project_files", "input_files", "output_files"} or after.get("scenario_id") != static["scenario_id"]:
        raise SoundBankBusinessPlanError("archived SoundBank after snapshot schema is not closed")
    before = live["before_snapshot"]
    if after["input_files"] != before["input_files"]:
        raise SoundBankBusinessPlanError("archived SoundBank input file proof changed")
    (
        io_root,
        io_root_flavor,
        dynamic_roots,
        managed_side_effects,
    ) = _archive_output_policy(static)
    before_project_files = _tree_by_relative(
        before["project_files"],
        label="project tree",
        source_flavor=io_root_flavor,
    )
    after_project_files = _tree_by_relative(
        after["project_files"],
        label="project tree",
        source_flavor=io_root_flavor,
    )
    before_outputs = _tree_by_relative(
        before["output_files"], source_flavor=io_root_flavor
    )
    after_outputs = _tree_by_relative(
        after["output_files"], source_flavor=io_root_flavor
    )
    expected = static["expected_artifacts"]
    if not isinstance(expected, list):
        raise SoundBankBusinessPlanError("archived SoundBank expected artifacts are invalid")
    allowed = set()
    for artifact in expected:
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("path"), str):
            raise SoundBankBusinessPlanError("archived SoundBank artifact record is invalid")
        candidate = _artifact_relative(
            artifact["path"],
            io_root,
            {**before_outputs, **after_outputs},
        )
        if candidate is None:
            # Function cases prove an out-of-scope control Bank by equality:
            # absent before and absent after is a valid unchanged state.  Topic
            # fixtures, by contrast, require their control artifacts to exist
            # before subscription, so absence remains invalid there.
            optional_absence = (
                artifact.get("kind") in {"control", "init"}
                and static["api"] != SOUNDBANK_TOPIC
            )
            if not optional_absence:
                raise SoundBankBusinessPlanError("archived SoundBank expected artifact is absent")
            continue
        allowed.add(candidate)
        current, previous = after_outputs.get(candidate), before_outputs.get(candidate)
        if artifact.get("kind") == "control" or (
            artifact.get("kind") == "init" and static["api"] == SOUNDBANK_TOPIC
        ):
            if not _tree_rows_equal(
                current, previous, source_flavor=io_root_flavor
            ):
                raise SoundBankBusinessPlanError("archived SoundBank control artifact changed")
        elif artifact.get("kind") == "init":
            if current is not None and current.get("size", 0) <= 0:
                raise SoundBankBusinessPlanError("archived SoundBank automatic Init artifact is empty")
        else:
            if current is None or current.get("size", 0) <= 0 or artifact.get("required_change") is True and _tree_rows_equal(current, previous, source_flavor=io_root_flavor):
                raise SoundBankBusinessPlanError("archived SoundBank expected artifact delta drifted")
    for path in managed_side_effects:
        try:
            relative = _relative_identity(
                archive_relative_from_absolute(path, io_root).canonical,
                source_flavor=io_root_flavor,
            )
        except ArchiveRelativePathError as exc:  # defensive; policy proved this
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect authority is invalid"
            ) from exc
        allowed.add(relative)
        current = after_outputs.get(relative)
        if current is None:
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect is absent"
            )
        if current.get("size", 0) <= 0:
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect is empty"
            )
        if before_outputs.get(relative) is not None:
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect was not newly created"
            )
    for relative in set(before_outputs) | set(after_outputs):
        if relative in allowed or _tree_rows_equal(
            after_outputs.get(relative),
            before_outputs.get(relative),
            source_flavor=io_root_flavor,
        ):
            continue
        display_row = after_outputs.get(relative) or before_outputs.get(relative)
        assert display_row is not None
        parsed_relative = PurePosixPath(str(display_row["relative_path"]))
        if (
            parsed_relative.suffix.casefold() not in {".bnk", ".wem"}
            and parsed_relative.name != "Wwise.dat"
        ):
            raise SoundBankBusinessPlanError(
                "archived SoundBank output tree contains an unrecognized changed row"
            )
        dynamically_allowed = any(
            _relative_is_within(relative, root, flavor=io_root_flavor)
            for root in dynamic_roots
        )
        current = after_outputs.get(relative)
        if dynamically_allowed:
            if (
                parsed_relative.suffix.casefold() != ".wem"
                and parsed_relative.name != "Wwise.dat"
            ):
                raise SoundBankBusinessPlanError(
                    "archived SoundBank dynamic cache artifact type is not allowed"
                )
            if current is None or current.get("size", 0) <= 0:
                raise SoundBankBusinessPlanError(
                    "archived SoundBank dynamic cache artifact is absent or empty"
                )
            if before_outputs.get(relative) is not None:
                raise SoundBankBusinessPlanError(
                    "archived SoundBank preexisting dynamic cache artifact changed"
                )
            continue
        if parsed_relative.name == "Wwise.dat":
            raise SoundBankBusinessPlanError(
                "archived SoundBank cache index changed outside sealed authority"
            )
        raise SoundBankBusinessPlanError(
            "archived SoundBank output changed outside sealed artifacts"
        )
    inclusion = live["set_inclusion_after"]
    if inclusion is not None:
        if after["objects"] != before["objects"]:
            raise SoundBankBusinessPlanError("archived setInclusions changed fixture objects")
        after_banks = {item.get("name"): item for item in after["banks"] if isinstance(item, Mapping)}
        before_banks = {item.get("name"): item for item in before["banks"] if isinstance(item, Mapping)}
        target = after_banks.get(inclusion["bank_name"])
        if target is None or target.get("id") != inclusion["bank_id"] or target.get("inclusions") != inclusion["inclusions"]:
            raise SoundBankBusinessPlanError("archived setInclusions expected set algebra drifted")
        if any(after_banks.get(name) != row for name, row in before_banks.items() if name != inclusion["bank_name"]):
            raise SoundBankBusinessPlanError("archived setInclusions changed a control Bank")
    elif static["api"] == "ak.wwise.core.soundbank.processDefinitionFiles":
        if after["objects"] != before["objects"]:
            raise SoundBankBusinessPlanError("archived definition processing changed fixture objects")
        _validate_definition_inclusions(static, live, after)
    else:
        if after["objects"] != before["objects"] or after["banks"] != before["banks"] or not _tree_maps_equal(after_project_files, before_project_files, source_flavor=io_root_flavor):
            raise SoundBankBusinessPlanError("archived artifact operation changed sealed project state")


def _validate_definition_inclusions(static: Mapping[str, Any], live: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    before_banks = {item.get("name"): item for item in live["before_snapshot"]["banks"] if isinstance(item, Mapping)}
    after_banks = {item.get("name"): item for item in after["banks"] if isinstance(item, Mapping)}
    expected: dict[str, dict[str, list[str]]] = {}
    for document in static["definitions"]:
        for row in document.get("rows", []):
            if row.get("resolution") == "unique":
                object_id = live["object_ids"].get(row.get("object_key"))
                if object_id is None:
                    raise SoundBankBusinessPlanError("archived definition row lacks a sealed object ID")
                bank_name = row["soundbank"]
                previous = before_banks.get(bank_name)
                if previous is None:
                    raise SoundBankBusinessPlanError("archived definition target lacks a before Bank")
                inclusions = expected.setdefault(
                    bank_name,
                    {
                        str(item[0]).casefold(): list(item[1])
                        for item in previous.get("inclusions", [])
                    },
                )
                inclusions[object_id.casefold()] = _definition_inclusion_filters(
                    row.get("filters")
                )
    for name, inclusion_map in expected.items():
        current, previous = after_banks.get(name), before_banks.get(name)
        inclusions = sorted(
            [[object_id, filters] for object_id, filters in inclusion_map.items()]
        )
        if current is None or previous is None or current.get("id") != previous.get("id") or current.get("inclusions") != sorted(inclusions):
            raise SoundBankBusinessPlanError("archived definition inclusion result drifted")
    if any(after_banks.get(name) != row for name, row in before_banks.items() if name not in expected):
        raise SoundBankBusinessPlanError("archived definition processing changed a control Bank")


def _definition_inclusion_filters(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SoundBankBusinessPlanError(
            "archived definition filters must be a nonempty closed list"
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or item not in _DEFINITION_FILTER_TO_INCLUSION:
            raise SoundBankBusinessPlanError(
                "archived definition filters contain an unsupported value"
            )
        if item in seen:
            raise SoundBankBusinessPlanError(
                "archived definition filters contain a duplicate value"
            )
        seen.add(item)
        normalized.append(_DEFINITION_FILTER_TO_INCLUSION[item])
    return sorted(normalized)


def _tree_by_relative(
    rows: Any,
    *,
    source_flavor: str,
    label: str = "output tree",
) -> dict[str, Mapping[str, Any]]:
    if source_flavor not in {"posix", "windows"} or not isinstance(rows, list):
        raise SoundBankBusinessPlanError(
            f"archived SoundBank {label} is invalid"
        )
    result: dict[str, Mapping[str, Any]] = {}
    for item in rows:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"relative_path", "size", "sha256", "mtime_ns"}
            or not isinstance(item.get("relative_path"), str)
            or type(item.get("size")) is not int
            or item["size"] < 0
            or not _sha_text(item.get("sha256"))
            or type(item.get("mtime_ns")) is not int
            or item["mtime_ns"] < 0
        ):
            raise SoundBankBusinessPlanError(
                f"archived SoundBank {label} is invalid"
            )
        raw_relative = item["relative_path"]
        try:
            parsed = parse_archive_relative_path(raw_relative)
        except ArchiveRelativePathError as exc:
            raise SoundBankBusinessPlanError(
                f"archived SoundBank {label} is invalid"
            ) from exc
        relative = parsed.canonical
        identity = _relative_identity(
            relative,
            source_flavor=source_flavor,
        )
        if identity in result:
            raise SoundBankBusinessPlanError(
                f"archived SoundBank {label} is invalid"
            )
        normalized = dict(item)
        normalized["relative_path"] = relative
        result[identity] = normalized
    if len(result) != len(rows):
        raise SoundBankBusinessPlanError(
            f"archived SoundBank {label} is invalid"
        )
    return result


def _validate_snapshot_path_sets(
    value: Any,
    *,
    source_flavor: str,
) -> None:
    if not isinstance(value, Mapping):
        raise SoundBankBusinessPlanError(
            "archived SoundBank snapshot path sets are invalid"
        )
    _tree_by_relative(
        value.get("project_files"),
        label="project tree",
        source_flavor=source_flavor,
    )
    _tree_by_relative(
        value.get("output_files"),
        source_flavor=source_flavor,
    )


def _relative_identity(value: str, *, source_flavor: str) -> str:
    parts = PurePosixPath(value).parts
    if source_flavor == "windows":
        parts = tuple(part.casefold() for part in parts)
    return PurePosixPath(*parts).as_posix()


def _tree_rows_equal(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
    *,
    source_flavor: str,
) -> bool:
    if left is None or right is None:
        return left is right
    left_value = dict(left)
    right_value = dict(right)
    left_value["relative_path"] = _relative_identity(
        str(left_value["relative_path"]),
        source_flavor=source_flavor,
    )
    right_value["relative_path"] = _relative_identity(
        str(right_value["relative_path"]),
        source_flavor=source_flavor,
    )
    return left_value == right_value


def _tree_maps_equal(
    left: Mapping[str, Mapping[str, Any]],
    right: Mapping[str, Mapping[str, Any]],
    *,
    source_flavor: str,
) -> bool:
    return set(left) == set(right) and all(
        _tree_rows_equal(
            left[identity],
            right[identity],
            source_flavor=source_flavor,
        )
        for identity in left
    )


def _relative_is_within(
    candidate: str,
    root: str,
    *,
    flavor: str,
) -> bool:
    candidate_parts = PurePosixPath(candidate).parts
    root_parts = PurePosixPath(root).parts
    if flavor == "windows":
        candidate_parts = tuple(part.casefold() for part in candidate_parts)
        root_parts = tuple(part.casefold() for part in root_parts)
    return (
        len(candidate_parts) >= len(root_parts)
        and candidate_parts[: len(root_parts)] == root_parts
    )


def _archive_output_policy(
    static: Mapping[str, Any],
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    io_root_value = static.get("io_root")
    policy = static.get("dynamic_output_policy")
    if not isinstance(io_root_value, str) or not isinstance(policy, Mapping):
        raise SoundBankBusinessPlanError(
            "archived SoundBank output authority is invalid"
        )
    try:
        parsed_io_root = parse_archive_absolute_path(io_root_value)
    except ArchiveRelativePathError as exc:
        raise SoundBankBusinessPlanError(
            "archived SoundBank output authority is invalid"
        ) from exc
    io_root = io_root_value
    enabled = static.get("api") in {
        "ak.wwise.core.soundbank.generate",
        SOUNDBANK_TOPIC,
    }
    expected_policy = {
        "enum": "soundbank_generation_cache_v1" if enabled else "none",
        "roots": ["io/cache"] if enabled else [],
        "allowed_suffixes": [".wem"] if enabled else [],
        "allowed_exact_names": ["Wwise.dat"] if enabled else [],
        "require_nonempty": enabled,
        "creation_only": enabled,
    }
    if dict(policy) != expected_policy:
        raise SoundBankBusinessPlanError(
            "archived SoundBank dynamic output policy drifted"
        )
    roots_value = policy.get("roots")
    if not isinstance(roots_value, list):
        raise SoundBankBusinessPlanError(
            "archived SoundBank dynamic artifact roots are invalid"
        )
    roots: list[str] = []
    for value in roots_value:
        if not isinstance(value, str):
            raise SoundBankBusinessPlanError(
                "archived SoundBank dynamic artifact root is invalid"
            )
        try:
            relative = parse_archive_relative_path(value)
        except ArchiveRelativePathError as exc:
            raise SoundBankBusinessPlanError(
                "archived SoundBank dynamic artifact root exceeds case authority"
            ) from exc
        roots.append(relative.canonical)
    if len(set(roots)) != len(roots):
        raise SoundBankBusinessPlanError(
            "archived SoundBank dynamic artifact roots are duplicated"
        )
    expected_root_count = (
        1 if enabled else 0
    )
    if len(roots) != expected_root_count:
        raise SoundBankBusinessPlanError(
            "archived SoundBank dynamic artifact root count drifted"
        )
    artifacts = static.get("expected_artifacts")
    if not isinstance(artifacts, list):
        raise SoundBankBusinessPlanError(
            "archived SoundBank expected artifacts are invalid"
        )
    for artifact in artifacts:
        path_value = artifact.get("path") if isinstance(artifact, Mapping) else None
        if not isinstance(path_value, str):
            raise SoundBankBusinessPlanError(
                "archived SoundBank expected artifact authority is invalid"
            )
        try:
            artifact_relative = archive_relative_from_absolute(
                path_value, io_root
            ).canonical
        except ArchiveRelativePathError as exc:
            raise SoundBankBusinessPlanError(
                "archived SoundBank expected artifact exceeds case authority"
            ) from exc
        if any(
            _relative_is_within(
                artifact_relative,
                root,
                flavor=parsed_io_root.source_flavor,
            )
            or _relative_is_within(
                root,
                artifact_relative,
                flavor=parsed_io_root.source_flavor,
            )
            for root in roots
        ):
            raise SoundBankBusinessPlanError(
                "archived SoundBank dynamic root overlaps a sealed artifact"
            )
    expected_managed: set[ArchiveAbsolutePath] = set()
    if static.get("api") == "ak.wwise.core.soundbank.convertExternalSources":
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or artifact.get("kind") != "external":
                continue
            parsed_artifact = parse_archive_absolute_path(artifact["path"])
            expected_managed.add(
                ArchiveAbsolutePath(
                    source_flavor=parsed_artifact.source_flavor,
                    pure_path=parsed_artifact.pure_path.parent / "Wwise.dat",
                )
            )
    managed_value = static.get("managed_side_effects")
    if (
        not isinstance(managed_value, list)
        or any(not isinstance(value, str) for value in managed_value)
        or managed_value != sorted(managed_value)
    ):
        raise SoundBankBusinessPlanError(
            "archived SoundBank managed side effects drifted"
        )
    managed: list[str] = []
    managed_identities: set[ArchiveAbsolutePath] = set()
    for value in managed_value:
        if not isinstance(value, str):
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect authority is invalid"
            )
        try:
            parsed_path = parse_archive_absolute_path(value)
            relative = archive_relative_from_absolute(value, io_root).canonical
        except ArchiveRelativePathError as exc:
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect authority is invalid"
            ) from exc
        if (
            parsed_path.pure_path.name != "Wwise.dat"
            or any(
                _relative_is_within(
                    relative,
                    root,
                    flavor=parsed_io_root.source_flavor,
                )
                for root in roots
            )
            or parsed_path in managed_identities
        ):
            raise SoundBankBusinessPlanError(
                "archived SoundBank managed side effect authority is invalid"
            )
        managed_identities.add(parsed_path)
        managed.append(value)
    if managed_identities != expected_managed:
        raise SoundBankBusinessPlanError(
            "archived SoundBank managed side effects drifted"
        )
    return (
        io_root,
        parsed_io_root.source_flavor,
        tuple(roots),
        tuple(managed),
    )


def _dynamic_output_policy(case: MaterializedSoundBankCase) -> dict[str, Any]:
    io_root = case.blueprint.io_root.resolve(strict=False)
    enabled = case.blueprint.api in {
        "ak.wwise.core.soundbank.generate",
        SOUNDBANK_TOPIC,
    }
    roots: list[str] = []
    for raw_root in case.allowed_dynamic_artifact_roots:
        root = raw_root.resolve(strict=False)
        try:
            relative = root.relative_to(io_root)
        except ValueError as exc:
            raise SoundBankBusinessPlanError(
                "SoundBank dynamic output root exceeds case authority"
            ) from exc
        value = relative.as_posix()
        if not value or value == "." or ".." in relative.parts:
            raise SoundBankBusinessPlanError(
                "SoundBank dynamic output root is not a strict descendant"
            )
        roots.append(value)
    expected_roots = ["io/cache"] if enabled else []
    if (
        len(set(roots)) != len(roots)
        or sorted(roots) != expected_roots
    ):
        raise SoundBankBusinessPlanError(
            "SoundBank dynamic output root count is not closed"
        )
    return {
        "enum": "soundbank_generation_cache_v1" if enabled else "none",
        "roots": sorted(roots),
        "allowed_suffixes": [".wem"] if enabled else [],
        "allowed_exact_names": ["Wwise.dat"] if enabled else [],
        "require_nonempty": enabled,
        "creation_only": enabled,
    }


def _managed_side_effects(case: MaterializedSoundBankCase) -> list[str]:
    if (
        case.blueprint.api
        != "ak.wwise.core.soundbank.convertExternalSources"
    ):
        return []
    return sorted(
        {
            str(
                (artifact.path.resolve(strict=False).parent / "Wwise.dat").resolve(
                    strict=False
                )
            )
            for artifact in case.expected_artifacts
            if artifact.kind == "external"
        }
    )


def _artifact_relative(
    path: str,
    io_root: str | Path,
    outputs: Mapping[str, Any],
) -> str | None:
    try:
        parsed_root = parse_archive_absolute_path(io_root)
        relative = _relative_identity(
            archive_relative_from_absolute(path, io_root).canonical,
            source_flavor=parsed_root.source_flavor,
        )
    except ArchiveRelativePathError as exc:
        raise SoundBankBusinessPlanError(
            "archived SoundBank artifact path is outside output authority"
        ) from exc
    return relative if relative in outputs else None


def _sha_text(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.casefold())


def _verify_files(values: Sequence[Any]) -> None:
    for item in values:
        path = Path(item.path)
        try:
            snapshot = read_bounded_exclusive_regular_file(
                path,
                max_bytes=item.size,
                require_private_posix_mode=False,
            )
        except CodexFileSecurityError as exc:
            raise SoundBankBusinessPlanError(
                "sealed SoundBank input file drifted"
            ) from exc
        if (
            snapshot.metadata.st_size != item.size
            or hashlib.sha256(snapshot.raw).hexdigest() != item.sha256
        ):
            raise SoundBankBusinessPlanError("sealed SoundBank input file drifted")


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json(value: Any) -> Any:
    if value is None or type(value) in {str, int, float, bool}: return value
    if isinstance(value, Path): return str(value)
    if is_dataclass(value) and not isinstance(value, type): return {item.name: _json(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping): return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_json(item) for item in value]
    if isinstance(value, (set, frozenset)): return sorted((_json(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    raise SoundBankBusinessPlanError(f"unserializable SoundBank value: {type(value).__name__}")


def _plain(value: Any) -> Any: return _json(value)


__all__ = ["SoundBankBusinessPlanError", "SoundBankBusinessPlanSections", "TOPIC_ACK_CONTRACT", "TOPIC_ACK_PROOF_CONTRACT", "TOPIC_ACK_REQUIREMENT_CONTRACT", "compile_soundbank_business_plan", "validate_soundbank_business_plan", "soundbank_archive_identity", "parse_soundbank_business_plan_sections", "validate_soundbank_business_plan_archive", "validate_soundbank_archived_verification"]

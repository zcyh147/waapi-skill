"""Closed pre-Codex business-plan sections for audio.convert and Media Pool.

This is deliberately a compiler over runner-owned dataclasses, not a second
scenario definition format.  It turns materialized fixture state into the six
family sections accepted by ``write_business_oracle_plan`` and later verifies
those sections by recomputing them from the same independently-owned inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_audio_conversion_runtime_v3 import (
    AUDIO_CONVERT_URI,
    SUPPORTED_VERSION as AUDIO_VERSION,
    AudioConversionPlan,
    AudioConversionSnapshot,
    AudioConversionRuntimeError,
    audio_conversion_volatile_cache_paths,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_direct_protocol,
    build_transaction_protocol,
    call_step,
    query_object_step,
    typed_read_draft_steps,
)
from tests.semantic.support.codex_media_pool_runtime_v3 import (
    MEDIA_POOL_GET_FIELDS_URI,
    MEDIA_POOL_GET_URI,
    VERSION as MEDIA_VERSION,
    MaterializedMediaPoolCase,
    SealedMediaPoolOracle,
    StagedMediaPoolCase,
    bind_media_pool_request,
    build_reference_match_gateway_argv,
    build_semantic_answer,
    fingerprint_staged_media_assets,
    fingerprint_tree,
    reference_match_paths,
    verify_reference_match_agent_result,
)
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol


class AudioMediaBusinessPlanError(ValueError):
    """Typed business-plan inputs or a persisted section drifted."""


AUDIO_SCHEMA = "waapi-skill.audio-conversion-business-plan/v4"
MEDIA_SCHEMA = "waapi-skill.media-pool-business-plan/v1"
_MAX_VOLATILE_CACHE_FILE_BYTES = 16 * 1024 * 1024 * 1024
_AUDIO_ASSERTIONS = (
    "audio.request.exact", "audio.fixture.source_files", "audio.live.before_snapshot",
    "audio.delta.target_slots", "audio.delta.controls_unchanged",
)
_MEDIA_ASSERTIONS = (
    "media.request.exact", "media.fixture.fingerprints", "media.live.field_binding",
    "media.live.index_rows", "media.delta.read_only",
)


@dataclass(frozen=True, slots=True)
class AudioMediaBusinessPlanSections:
    """The six exact fields consumed by the common business-plan writer."""

    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]

    def writer_kwargs(self) -> dict[str, Any]:
        """Return only the common-writer family keyword arguments."""

        return {
            "fixture_spec": _plain(self.fixture_spec),
            "payload_bindings": _plain(self.payload_bindings),
            "assertion_ids": list(self.assertion_ids),
            "static_expectation": _plain(self.static_expectation),
            "live_binding": _plain(self.live_binding),
            "delta_rules": [_plain(item) for item in self.delta_rules],
        }


def compile_audio_conversion_business_plan(
    plan: AudioConversionPlan,
    before: AudioConversionSnapshot,
    protocol: V3GatewayProtocol,
    *,
    reviewed_scenario_fixture: Mapping[str, Any],
) -> AudioMediaBusinessPlanSections:
    """Compile the sealed conversion fixture, request, and before state."""

    _validate_audio_inputs(plan, before, protocol)
    static = _audio_static(
        plan,
        scenario_fixture_sha256=_reviewed_scenario_fixture_sha256(
            reviewed_scenario_fixture
        ),
    )
    live = _audio_live(plan, before)
    return _sections(
        fixture_kind="audio_conversion_materialized_v1",
        fixture_value={"static": static, "live": live},
        primary_steps=("tx01.execute",),
        verification_steps=("tx01.operation-schema", "tx01.preview", "tx01.transaction-show", "tx01.confirm", "tx01.verify"),
        assertion_ids=_AUDIO_ASSERTIONS,
        static=static,
        live=live,
        rules=(
            _audio_delta_rules(plan, before),
        ),
    )


def validate_audio_conversion_business_plan(
    sections: AudioMediaBusinessPlanSections,
    plan: AudioConversionPlan,
    before: AudioConversionSnapshot,
    protocol: V3GatewayProtocol,
    *,
    reviewed_scenario_fixture: Mapping[str, Any],
    verify_files: bool = False,
) -> None:
    """Independently recompute every conversion section and reject drift."""

    expected = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_scenario_fixture,
    )
    _assert_same_sections(sections, expected, family="audio_conversion")
    if verify_files:
        _verify_file_records(expected.live_binding["source_files"], field="source_files")


def compile_media_pool_business_plan(
    case: MaterializedMediaPoolCase,
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
    protocol: V3GatewayProtocol,
    *,
    project_digest: str,
    reviewed_scenario_fixture: Mapping[str, Any],
) -> AudioMediaBusinessPlanSections:
    """Compile a read-only Media Pool request from its sealed live index."""

    _validate_media_inputs(case, staged, oracle, protocol, project_digest=project_digest)
    static = _media_static(
        case,
        scenario_fixture_sha256=_reviewed_scenario_fixture_sha256(
            reviewed_scenario_fixture
        ),
    )
    live = _media_live(case, staged, oracle, project_digest=project_digest)
    verification_steps = ["media.get-fields"]
    if case.association_expectations is not None:
        verification_steps.append("media.audio-sources")
    return _sections(
        fixture_kind="media_pool_materialized_v1",
        fixture_value={
            "static": static,
            "live": live,
        },
        primary_steps=("media.get",),
        verification_steps=tuple(verification_steps),
        assertion_ids=_MEDIA_ASSERTIONS,
        static=static,
        live=live,
        rules=(_media_delta_rule(case, staged, oracle, project_digest=project_digest),),
    )


def validate_media_pool_business_plan(
    sections: AudioMediaBusinessPlanSections,
    case: MaterializedMediaPoolCase,
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
    protocol: V3GatewayProtocol,
    *,
    project_digest: str,
    reviewed_scenario_fixture: Mapping[str, Any],
    verify_files: bool = False,
) -> None:
    """Independently recompute exact Media Pool sections and reject drift."""

    expected = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest=project_digest,
        reviewed_scenario_fixture=reviewed_scenario_fixture,
    )
    _assert_same_sections(sections, expected, family="media_pool")
    if verify_files:
        _verify_media_files(case, staged)


def parse_audio_media_business_plan_sections(payload: Mapping[str, Any]) -> AudioMediaBusinessPlanSections:
    """Parse the six persisted sections and reject non-closed archive shapes."""

    required = {"fixture_spec", "payload_bindings", "assertion_ids", "static_expectation", "live_binding", "delta_rules"}
    if not isinstance(payload, Mapping) or not required.issubset(payload):
        raise AudioMediaBusinessPlanError("persisted business plan lacks required typed sections")
    values = {name: payload[name] for name in required}
    if not all(isinstance(values[name], Mapping) for name in ("fixture_spec", "payload_bindings", "static_expectation", "live_binding")):
        raise AudioMediaBusinessPlanError("persisted typed mapping section is invalid")
    if not isinstance(values["assertion_ids"], (list, tuple)) or not isinstance(values["delta_rules"], (list, tuple)):
        raise AudioMediaBusinessPlanError("persisted typed sequence section is invalid")
    sections = AudioMediaBusinessPlanSections(
        fixture_spec=MappingProxyType(_json_value(values["fixture_spec"])),
        payload_bindings=MappingProxyType(_json_value(values["payload_bindings"])),
        assertion_ids=tuple(_json_value(values["assertion_ids"])),
        static_expectation=MappingProxyType(_json_value(values["static_expectation"])),
        live_binding=MappingProxyType(_json_value(values["live_binding"])),
        delta_rules=tuple(MappingProxyType(_json_value(item)) for item in values["delta_rules"]),
    )
    _validate_archive_shape(sections)
    return sections


def validate_audio_media_business_plan_archive(
    sections: AudioMediaBusinessPlanSections,
    protocol: V3GatewayProtocol,
    *,
    scenario_id: str,
    api: str,
    version: str,
    reviewed_scenario_fixture: Mapping[str, Any],
) -> None:
    """Validate an archive against independently reviewed scenario truth."""

    _validate_archive_shape(sections)
    static = sections.static_expectation
    live = sections.live_binding
    family = static["family_schema_version"]
    expected_identity = {
        "scenario_id": scenario_id,
        "api": api,
        "version": version,
        "scenario_fixture_sha256": _reviewed_scenario_fixture_sha256(
            reviewed_scenario_fixture
        ),
    }
    if any(type(value) is not str or not value for value in (scenario_id, api, version)):
        raise AudioMediaBusinessPlanError(
            "archive validator requires an independent scenario identity"
        )
    if expected_identity != {
        "scenario_id": static["scenario_id"],
        "api": static["api"],
        "version": static["version"],
        "scenario_fixture_sha256": static["scenario_fixture_sha256"],
    }:
        raise AudioMediaBusinessPlanError(
            "archived audio/media scenario identity is not independently bound"
        )
    if family == AUDIO_SCHEMA:
        if sections.fixture_spec.get("kind") != "audio_conversion_materialized_v1" or sections.assertion_ids != _AUDIO_ASSERTIONS:
            raise AudioMediaBusinessPlanError("archived audio fixture kind or assertions drifted")
        expected_protocol = build_transaction_protocol([static["operation_request"]])
        expected_primary = ["tx01.execute"]
        expected_verification = ["tx01.operation-schema", "tx01.preview", "tx01.transaction-show", "tx01.confirm", "tx01.verify"]
        if live["before_snapshot_sha256"] != _archived_audio_snapshot_digest(
            live["before_snapshot"]
        ):
            raise AudioMediaBusinessPlanError("archived audio before digest is invalid")
        _validate_archived_audio_static_and_live(
            static,
            live,
            reviewed_scenario_fixture=reviewed_scenario_fixture,
        )
        expected_delta = _audio_archive_delta(static, live)
    elif family == MEDIA_SCHEMA:
        if sections.fixture_spec.get("kind") != "media_pool_materialized_v1" or sections.assertion_ids != _MEDIA_ASSERTIONS:
            raise AudioMediaBusinessPlanError("archived media fixture kind or assertions drifted")
        request = live["request"]
        if set(request) != {"args", "options", "binding", "post_filter"}:
            raise AudioMediaBusinessPlanError(
                "archived media request shape is not closed"
            )
        steps = [call_step("media.get-fields", MEDIA_POOL_GET_FIELDS_URI, version=MEDIA_VERSION)]
        steps.extend(
            typed_read_draft_steps(
                "media",
                MEDIA_POOL_GET_URI,
                version=MEDIA_VERSION,
                args=request["args"],
                options=request["options"],
                post_filter=request["post_filter"],
            )
        )
        expected_verification = ["media.get-fields"]
        if static["association_expectations"] is not None:
            steps.append(
                query_object_step(
                    "media.audio-sources",
                    build_reference_match_gateway_argv(
                        _archived_reference_match_paths(live)
                    ),
                )
            )
            expected_verification.append("media.audio-sources")
        expected_protocol = build_direct_protocol(steps)
        expected_primary = ["media.get"]
        if live["request_sha256"] != _sha256(
            {
                "args": request["args"],
                "options": request["options"],
                "post_filter": request["post_filter"],
            }
        ):
            raise AudioMediaBusinessPlanError("archived media request digest is invalid")
        _validate_archived_media_static_and_live(
            static,
            live,
            reviewed_scenario_fixture=reviewed_scenario_fixture,
        )
        expected_delta = _media_archive_delta(live)
    else:  # _validate_archive_shape already rejects this, retained for type narrowing.
        raise AudioMediaBusinessPlanError("archived family schema is unknown")
    if _protocol_value(protocol) != _protocol_value(expected_protocol):
        raise AudioMediaBusinessPlanError("archived typed plan protocol drifted")
    if sections.payload_bindings != {"primary_steps": expected_primary, "verification_steps": expected_verification}:
        raise AudioMediaBusinessPlanError("archived primary/verification partition drifted")
    if sections.delta_rules != (expected_delta,):
        raise AudioMediaBusinessPlanError("archived typed delta subjects drifted")
    if sections.fixture_spec.get("sha256") != _sha256({"static": static, "live": live}):
        raise AudioMediaBusinessPlanError("archived fixture digest is not bound to static and live fixture state")


def _validate_archived_media_static_and_live(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
    *,
    reviewed_scenario_fixture: Mapping[str, Any],
) -> None:
    """Rejoin candidate/business layers to reviewed fixture and bound fields."""

    if not isinstance(reviewed_scenario_fixture.get("asset_spec"), Mapping):
        raise AudioMediaBusinessPlanError(
            "reviewed Media Pool fixture has no asset specification"
        )
    request = live.get("request")
    binding = request.get("binding") if isinstance(request, Mapping) else None
    by_concept = binding.get("by_concept") if isinstance(binding, Mapping) else None
    if not isinstance(by_concept, Mapping):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool request lacks a field binding"
        )

    def bind_tokens(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): bind_tokens(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [bind_tokens(item) for item in value]
        if isinstance(value, str):
            match = re.fullmatch(r"\{media_pool_fields\.([a-z_]+)\}", value)
            if match:
                concept = match.group(1)
                bound = by_concept.get(concept)
                if not isinstance(bound, str) or not bound:
                    raise AudioMediaBusinessPlanError(
                        "archived Media Pool template uses an unbound field concept"
                    )
                return bound
        return value

    request_template = static["request_template"]
    bound_args = bind_tokens(request_template["args"])
    bound_post_filter = (
        bind_tokens(request_template["post_filter"])
        if "post_filter" in request_template
        else None
    )
    candidate_keys = live.get("candidate_keys")
    business_keys = live.get("expected_keys")
    row_keys = [
        row.get("key")
        for row in live.get("sealed_rows", [])
        if isinstance(row, Mapping)
    ]
    if (
        request.get("args") != bound_args
        or request.get("post_filter") != bound_post_filter
        or candidate_keys != static["expected_candidate_file_keys"]
        or business_keys != static["expected_file_keys"]
        or not isinstance(candidate_keys, list)
        or not isinstance(business_keys, list)
        or len(candidate_keys) != len(set(candidate_keys))
        or len(business_keys) != len(set(business_keys))
        or len(row_keys) != len(set(row_keys))
        or not set(business_keys).issubset(candidate_keys)
        or not set(candidate_keys).issubset(row_keys)
        or (bound_post_filter is None and candidate_keys != business_keys)
    ):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool candidate/business request binding drifted"
        )


def _archived_reference_match_paths(live: Mapping[str, Any]) -> tuple[str, ...]:
    """Recover the exact compact-query paths from the sealed archived rows."""

    rows = live.get("sealed_rows")
    expected_keys = live.get("expected_keys")
    if not isinstance(rows, list) or not isinstance(expected_keys, list):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool reference match inputs are invalid"
        )
    row_by_key: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise AudioMediaBusinessPlanError(
                "archived Media Pool reference match row is invalid"
            )
        key = row.get("key")
        if not isinstance(key, str) or not key or key in row_by_key:
            raise AudioMediaBusinessPlanError(
                "archived Media Pool reference match row key is invalid"
            )
        row_by_key[key] = row
    paths: list[str] = []
    for key in expected_keys:
        row = row_by_key.get(key) if isinstance(key, str) else None
        path = row.get("path") if isinstance(row, Mapping) else None
        if not isinstance(path, str) or not path:
            raise AudioMediaBusinessPlanError(
                "archived Media Pool reference match path is missing"
            )
        paths.append(path)
    return tuple(paths)


def _archived_reference_match_expectations(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Bind compact result rows to reviewed reference classifications."""

    association = static.get("association_expectations")
    assets = static.get("assets")
    expected_keys = live.get("expected_keys")
    rows = live.get("sealed_rows")
    if (
        not isinstance(association, Mapping)
        or not isinstance(assets, list)
        or not isinstance(expected_keys, list)
        or not isinstance(rows, list)
    ):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool reference expectations are invalid"
        )
    referenced = association.get("referenced")
    unreferenced = association.get("unreferenced")
    if not isinstance(referenced, list) or not isinstance(unreferenced, list):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool reference classifications are invalid"
        )
    classified = [*referenced, *unreferenced]
    if (
        any(not isinstance(key, str) or not key for key in classified)
        or len(classified) != len(set(classified))
        or set(classified) != set(expected_keys)
    ):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool reference classifications do not close business keys"
        )
    asset_by_key = {
        asset.get("key"): asset
        for asset in assets
        if isinstance(asset, Mapping) and isinstance(asset.get("key"), str)
    }
    row_by_key = {
        row.get("key"): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("key"), str)
    }
    if len(asset_by_key) != len(assets) or len(row_by_key) != len(rows):
        raise AudioMediaBusinessPlanError(
            "archived Media Pool reference assets or rows contain duplicate keys"
        )
    result: list[tuple[str, tuple[str, ...]]] = []
    referenced_keys = set(referenced)
    for key in expected_keys:
        asset = asset_by_key.get(key)
        row = row_by_key.get(key)
        raw_parents = asset.get("referenced_by") if isinstance(asset, Mapping) else None
        path = row.get("path") if isinstance(row, Mapping) else None
        if (
            not isinstance(raw_parents, list)
            or any(not isinstance(parent, str) or not parent for parent in raw_parents)
            or not isinstance(path, str)
            or not path
            or ((key in referenced_keys) != bool(raw_parents))
        ):
            raise AudioMediaBusinessPlanError(
                "archived Media Pool reference asset classification is invalid"
            )
        result.append((path, tuple(raw_parents)))
    return tuple(result)


def validate_audio_archived_verification(sections: AudioMediaBusinessPlanSections, verification: Mapping[str, Any]) -> None:
    """Bind archived conversion-oracle evidence to the sealed pre-Codex plan."""

    _validate_archive_shape(sections)
    if sections.static_expectation["family_schema_version"] != AUDIO_SCHEMA:
        raise AudioMediaBusinessPlanError("audio verification was paired with another family")
    evidence = _verification_evidence(verification)
    live = sections.live_binding
    static = sections.static_expectation
    if evidence.get("before") != live["before_snapshot"]:
        raise AudioMediaBusinessPlanError("archived conversion verification before snapshot drifted")
    if evidence.get("operation_request") != static["operation_request"]:
        raise AudioMediaBusinessPlanError("archived conversion verification request drifted")
    if evidence.get("operation_request_sha256") != static["operation_request_sha256"]:
        raise AudioMediaBusinessPlanError("archived conversion verification request digest drifted")
    if evidence.get("target_slots") != static["expected_output_count"]:
        raise AudioMediaBusinessPlanError("archived conversion verification target count drifted")
    after = evidence.get("after")
    if not isinstance(after, Mapping):
        raise AudioMediaBusinessPlanError("archived conversion verification lacks after snapshot")
    if after.get("digest") != _archived_audio_snapshot_digest(after):
        raise AudioMediaBusinessPlanError("archived conversion after digest is invalid")
    before_by_slot = _archived_audio_artifacts_by_slot(live["before_snapshot"])
    after_by_slot = _archived_audio_artifacts_by_slot(after)
    baseline_by_slot = _archived_audio_artifacts_by_slot(
        live["before_snapshot"],
        field="baseline_artifacts",
    )
    if (
        after.get("baseline_artifacts")
        != live["before_snapshot"].get("baseline_artifacts")
        or _archived_audio_artifacts_by_slot(
            after,
            field="baseline_artifacts",
        )
        != baseline_by_slot
    ):
        raise AudioMediaBusinessPlanError(
            "archived conversion baseline artifact evidence changed"
        )
    _validate_audio_artifact_files_against_tree(after_by_slot, after)
    _validate_archived_audio_volatile_cache_metadata(
        after.get("volatile_cache_files"),
        static=static,
        output_tree=after.get("output_tree"),
        artifacts_by_slot=after_by_slot,
    )
    _validate_archived_audio_converted_paths_owned(after_by_slot, static=static)
    _validate_archived_audio_baseline_paths(
        after.get("baseline_artifact_paths"),
        static=static,
        output_tree=after.get("output_tree"),
        artifact_count=len(after_by_slot),
        require_output_subset=False,
    )
    if set(after_by_slot) != set(before_by_slot):
        raise AudioMediaBusinessPlanError("archived conversion artifact slots drifted")
    preset_by_key, binding_by_path, profile_by_path = _audio_profile_maps(static)
    _reject_forbidden_audio_cache_aliases(
        after_by_slot,
        preset_by_key=preset_by_key,
        binding_by_path=binding_by_path,
        context="archived conversion output",
    )
    observed_reference_by_path: dict[str, tuple[str, str]] = {}
    observed_id_by_profile: dict[str, str] = {}
    observed_profile_by_id: dict[str, str] = {}
    for slot, current in after_by_slot.items():
        binding = binding_by_path.get(slot[0])
        profile = profile_by_path.get(slot[0])
        setting_key = (
            dict(binding["settings_by_platform"]).get(slot[1])
            if isinstance(binding, Mapping)
            else None
        )
        component = preset_by_key.get(setting_key or "")
        if (
            profile is None
            or component is None
            or current["conversion_name"] != profile["name"]
            or not isinstance(current["conversion_id"], str)
            or not current["conversion_id"]
        ):
            raise AudioMediaBusinessPlanError(
                "archived conversion output differs from its Conversion profile"
            )
        reference = (current["conversion_id"], current["conversion_name"])
        if observed_reference_by_path.setdefault(slot[0], reference) != reference:
            raise AudioMediaBusinessPlanError(
                "archived conversion Sound changed ShareSet across platforms"
            )
        profile_key = str(profile["key"])
        if (
            observed_id_by_profile.setdefault(profile_key, current["conversion_id"])
            != current["conversion_id"]
            or observed_profile_by_id.setdefault(current["conversion_id"], profile_key)
            != profile_key
        ):
            raise AudioMediaBusinessPlanError(
                "archived conversion profile identity is inconsistent"
            )
        if current["file"]["present"] and (
            current["codec"] != component["codec"]
            or current["sample_rate"] != component["sample_rate"]
        ):
            raise AudioMediaBusinessPlanError(
                "archived conversion output format differs from its platform component"
            )
    rule = sections.delta_rules[0]
    target_slots = {tuple(item) for item in rule["target_slots"]}
    for slot in target_slots:
        current = after_by_slot[slot]
        previous = before_by_slot[slot]
        if (
            current["object_id"],
            current["source_id"],
            current["source_key"],
            current["conversion_id"],
            current["conversion_name"],
            current["original_path"],
            current["original_file"],
        ) != (
            previous["object_id"],
            previous["source_id"],
            previous["source_key"],
            previous["conversion_id"],
            previous["conversion_name"],
            previous["original_path"],
            previous["original_file"],
        ):
            raise AudioMediaBusinessPlanError(
                "archived conversion target identity/profile/original binding drifted"
            )
        if not current["file"]["present"] or not current["file"]["size"]:
            raise AudioMediaBusinessPlanError("archived conversion target output is absent")
    if static["scenario_id"] == "VS24-F-AUDIO-CONVERT-05":
        target_hashes = [
            after_by_slot[slot]["file"].get("sha256") for slot in target_slots
        ]
        if len(target_hashes) != len(set(target_hashes)):
            raise AudioMediaBusinessPlanError(
                "archived same-basename conversion targets reused output bytes"
            )
    for slot in {tuple(item) for item in rule["control_slots_unchanged"]}:
        if after_by_slot[slot] != before_by_slot[slot]:
            raise AudioMediaBusinessPlanError("archived conversion control slot changed")
    for slot in {tuple(item) for item in rule["required_refresh_slots"]}:
        if not after_by_slot[slot]["file"]["present"]:
            raise AudioMediaBusinessPlanError("archived missing output was not refreshed")
    for slot in {tuple(item) for item in rule["required_sha_change_slots"]}:
        if after_by_slot[slot]["file"].get("sha256") == baseline_by_slot[slot][
            "file"
        ].get("sha256"):
            raise AudioMediaBusinessPlanError(
                "archived output bytes equal the sealed pre-delta baseline"
            )
    for slot in target_slots:
        current = after_by_slot[slot]
        baseline = baseline_by_slot[slot]
        if (
            current["file"].get("mtime_ns") is None
            or baseline["file"].get("mtime_ns") is None
            or current["file"]["mtime_ns"] <= baseline["file"]["mtime_ns"]
        ):
            raise AudioMediaBusinessPlanError(
                "archived conversion target was not refreshed after preview"
            )
    immutable = rule["immutable_subjects"]
    if (
        _sha256(after["input_files"]) != immutable["input_files_sha256"]
        or _sha256(after["originals_files"]) != immutable["originals_sha256"]
        or _sha256(after["authoring_files"]) != immutable["authoring_files_sha256"]
        or _sha256(after["conversion_xml"])
        != immutable["conversion_xml_sha256"]
        or _sha256(after["baseline_artifacts"])
        != immutable["baseline_artifacts_sha256"]
        or _sha256(after["baseline_artifact_paths"])
        != immutable["baseline_artifact_paths_sha256"]
    ):
        raise AudioMediaBusinessPlanError(
            "archived conversion immutable file subjects changed"
        )
    before_target_paths = {
        row["converted_path"] for slot, row in before_by_slot.items() if slot in target_slots
    }
    after_target_paths = {
        row["converted_path"] for slot, row in after_by_slot.items() if slot in target_slots
    }
    before_non_target_paths = {
        row["path"]
        for row in live["before_snapshot"]["output_tree"]
        if row["path"] not in before_target_paths
    }
    if (after_target_paths - before_target_paths) & before_non_target_paths:
        raise AudioMediaBusinessPlanError(
            "archived conversion target path collides with pre-existing non-target output"
        )
    target_paths = before_target_paths | after_target_paths
    non_target_output = [
        row for row in after["output_tree"] if row["path"] not in target_paths
    ]
    if _sha256(non_target_output) != immutable["non_target_output_sha256"]:
        raise AudioMediaBusinessPlanError(
            "archived conversion non-target output tree changed"
        )
    before_volatile = live["before_snapshot"]["volatile_cache_files"]
    after_volatile = after["volatile_cache_files"]
    changed_volatile_paths = [
        current["path"]
        for previous, current in zip(before_volatile, after_volatile, strict=True)
        if previous != current
    ]
    if (
        evidence.get("volatile_cache_files_before") != before_volatile
        or evidence.get("volatile_cache_files_after") != after_volatile
        or evidence.get("volatile_cache_changed_paths") != changed_volatile_paths
    ):
        raise AudioMediaBusinessPlanError(
            "archived conversion volatile cache evidence is not independently bound"
        )


def validate_media_archived_verification(sections: AudioMediaBusinessPlanSections, verification: Mapping[str, Any]) -> None:
    """Bind archived Media Pool evidence to the sealed read-only plan."""

    _validate_archive_shape(sections)
    if sections.static_expectation["family_schema_version"] != MEDIA_SCHEMA:
        raise AudioMediaBusinessPlanError("media verification was paired with another family")
    evidence = _verification_evidence(verification)
    live = sections.live_binding
    if evidence.get("project_digest_before") != live["project_digest_before"] or evidence.get("project_digest_after") != live["project_digest_before"]:
        raise AudioMediaBusinessPlanError("archived Media Pool verification project digest drifted")
    sealed = evidence.get("sealed_oracle")
    if not isinstance(sealed, Mapping):
        raise AudioMediaBusinessPlanError("archived Media Pool verification lacks its sealed oracle")
    if sealed.get("rows") != live["sealed_rows"]:
        raise AudioMediaBusinessPlanError("archived Media Pool verification sealed rows drifted")
    request = sealed.get("request")
    if (
        not isinstance(request, Mapping)
        or request.get("args") != live["request"]["args"]
        or request.get("options") != live["request"]["options"]
        or request.get("post_filter") != live["request"]["post_filter"]
    ):
        raise AudioMediaBusinessPlanError("archived Media Pool verification request drifted")
    if sealed.get("candidate_keys") != live["candidate_keys"]:
        raise AudioMediaBusinessPlanError(
            "archived Media Pool verification candidate keys drifted"
        )
    if sealed.get("expected_keys") != live["expected_keys"]:
        raise AudioMediaBusinessPlanError(
            "archived Media Pool verification business keys drifted"
        )
    if evidence.get("source_fingerprint_after") != live["source_fingerprint"]:
        raise AudioMediaBusinessPlanError("archived Media Pool verification source fingerprint drifted")
    static = sections.static_expectation
    if static["association_expectations"] is not None:
        model_reference_result = evidence.get("model_reference_result")
        if not isinstance(model_reference_result, Mapping):
            raise AudioMediaBusinessPlanError(
                "archived Media Pool verification lacks the compact reference match result"
            )
        if evidence.get("supporting_association_read") is not True:
            raise AudioMediaBusinessPlanError(
                "archived Media Pool verification omitted its trusted association baseline"
            )
        match_verification = verify_reference_match_agent_result(
            model_reference_result,
            expected_candidates=_archived_reference_match_expectations(
                static,
                live,
            ),
        )
        if not match_verification.ok:
            raise AudioMediaBusinessPlanError(
                "archived Media Pool compact reference match result drifted: "
                + str(match_verification.details.get("error", "unknown mismatch"))
            )


def _verification_evidence(verification: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(verification, Mapping):
        raise AudioMediaBusinessPlanError("archived verification is not an object")
    value = verification.get("evidence", verification)
    if not isinstance(value, Mapping):
        raise AudioMediaBusinessPlanError("archived verification evidence is not an object")
    return value


def _validate_archive_shape(sections: AudioMediaBusinessPlanSections) -> None:
    static = sections.static_expectation
    live = sections.live_binding
    family = static.get("family_schema_version")
    expected = AUDIO_SCHEMA if family == AUDIO_SCHEMA else MEDIA_SCHEMA if family == MEDIA_SCHEMA else None
    if expected is None:
        raise AudioMediaBusinessPlanError("typed plan has no supported family_schema_version")
    if set(sections.fixture_spec) != {"kind", "sha256"} or set(sections.payload_bindings) != {"primary_steps", "verification_steps"}:
        raise AudioMediaBusinessPlanError("typed plan common section shape is not closed")
    if expected == AUDIO_SCHEMA:
        static_keys = {"family", "family_schema_version", "api", "version", "scenario_id", "scenario_fixture_sha256", "operation_request", "operation_request_sha256", "objects", "platforms", "languages", "presets", "profiles", "bindings", "source_delta", "setting_delta", "missing_cache_paths", "expected_output_count"}
        live_keys = {"before_snapshot", "before_snapshot_sha256", "target_slots", "source_files", "artifact_fingerprints", "conversion_xml"}
    else:
        static_keys = {"family", "family_schema_version", "api", "version", "scenario_id", "scenario_fixture_sha256", "request_template", "expected_candidate_file_keys", "expected_file_keys", "expected_groups", "association_expectations", "assets", "databases"}
        live_keys = {"source_fingerprint", "staged_fingerprint", "project_digest_before", "staged_assets", "request", "request_sha256", "sealed_rows", "candidate_keys", "expected_keys", "semantic_answer"}
    if set(static) != static_keys or set(live) != live_keys:
        raise AudioMediaBusinessPlanError("typed plan family section has missing or extra fields")
    if family == AUDIO_SCHEMA:
        rule_keys = {"enum", "target_slots", "expected_output_count", "required_refresh_slots", "required_sha_change_slots", "control_slots_unchanged", "allowed_volatile_cache_paths", "immutable_subjects"}
        immutable_keys = {"input_files_sha256", "originals_sha256", "authoring_files_sha256", "conversion_xml_sha256", "baseline_artifacts_sha256", "baseline_artifact_paths_sha256", "non_target_output_sha256"}
        if len(sections.delta_rules) != 1 or set(sections.delta_rules[0]) != rule_keys or set(sections.delta_rules[0].get("immutable_subjects", {})) != immutable_keys:
            raise AudioMediaBusinessPlanError("audio typed delta rule is not closed")
    else:
        rule_keys = {"enum", "project_digest_before", "source_fingerprint", "staged_fingerprint", "sealed_row_ids", "request_sha256"}
        if len(sections.delta_rules) != 1 or set(sections.delta_rules[0]) != rule_keys:
            raise AudioMediaBusinessPlanError("media typed delta rule is not closed")


def _audio_profile_maps(
    static: Mapping[str, Any],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
]:
    """Rebuild deterministic ShareSet provenance from closed component maps."""

    scenario_id = static.get("scenario_id")
    platforms = static.get("platforms")
    presets = static.get("presets")
    profiles = static.get("profiles")
    bindings = static.get("bindings")
    if (
        not isinstance(scenario_id, str)
        or not scenario_id
        or not isinstance(platforms, list)
        or not platforms
        or any(not isinstance(item, str) or not item for item in platforms)
        or len(platforms) != len(set(platforms))
        or not isinstance(presets, list)
        or not presets
        or not isinstance(profiles, list)
        or not profiles
        or not isinstance(bindings, list)
        or not bindings
    ):
        raise AudioMediaBusinessPlanError(
            "archived audio Conversion profile inputs are invalid"
        )

    preset_keys = {"key", "name", "codec", "sample_rate", "channels"}
    preset_by_key: dict[str, Mapping[str, Any]] = {}
    preset_names: set[str] = set()
    for row in presets:
        if (
            not isinstance(row, Mapping)
            or set(row) != preset_keys
            or not isinstance(row.get("key"), str)
            or not row["key"]
            or not isinstance(row.get("name"), str)
            or not row["name"]
            or not isinstance(row.get("codec"), str)
            or not row["codec"]
            or type(row.get("sample_rate")) is not int
            or row["sample_rate"] <= 0
            or type(row.get("channels")) is not int
            or row["channels"] <= 0
            or row["key"] in preset_by_key
            or row["name"] in preset_names
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio Conversion component provenance is invalid"
            )
        preset_by_key[row["key"]] = row
        preset_names.add(row["name"])

    binding_keys = {
        "path",
        "source_keys_by_language",
        "settings_by_platform",
        "control",
    }
    binding_by_path: dict[str, Mapping[str, Any]] = {}
    settings_maps: list[list[list[str]]] = []
    for row in bindings:
        if (
            not isinstance(row, Mapping)
            or set(row) != binding_keys
            or not isinstance(row.get("path"), str)
            or not row["path"]
            or type(row.get("control")) is not bool
            or row["path"] in binding_by_path
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio Conversion binding provenance is invalid"
            )
        sources = row.get("source_keys_by_language")
        settings = row.get("settings_by_platform")
        if not _closed_string_pairs(sources) or not _closed_string_pairs(settings):
            raise AudioMediaBusinessPlanError(
                "archived audio Conversion binding maps are invalid"
            )
        if [item[0] for item in settings] != platforms or not {
            item[1] for item in settings
        } <= set(preset_by_key):
            raise AudioMediaBusinessPlanError(
                "archived audio Conversion component map is not platform-closed"
            )
        binding_by_path[row["path"]] = row
        settings_maps.append([list(item) for item in settings])

    setting_delta = static.get("setting_delta")
    if setting_delta is not None:
        if not isinstance(setting_delta, Mapping) or set(setting_delta) != {
            "path",
            "before_by_platform",
            "after_by_platform",
        }:
            raise AudioMediaBusinessPlanError(
                "archived audio setting delta profile provenance is invalid"
            )
        binding = binding_by_path.get(setting_delta.get("path"))
        before_settings = setting_delta.get("before_by_platform")
        after_settings = setting_delta.get("after_by_platform")
        if (
            binding is None
            or not _closed_string_pairs(before_settings)
            or not _closed_string_pairs(after_settings)
            or [item[0] for item in before_settings] != platforms
            or [item[0] for item in after_settings] != platforms
            or not {item[1] for item in before_settings} <= set(preset_by_key)
            or list(after_settings) != list(binding["settings_by_platform"])
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio setting delta is not bound to its profiles"
            )
        if list(before_settings) != list(after_settings):
            settings_maps.append([list(item) for item in before_settings])

    unique_settings: list[list[list[str]]] = []
    for settings in settings_maps:
        if settings not in unique_settings:
            unique_settings.append(settings)

    safe_identity = re.sub(r"[^A-Za-z0-9_]+", "_", scenario_id).strip("_")
    expected_profiles: list[dict[str, Any]] = []
    for settings in unique_settings:
        digest = _sha256(
            {
                "scenario_id": scenario_id,
                "components_by_platform": [
                    {
                        "platform": platform,
                        "component": dict(preset_by_key[key]),
                    }
                    for platform, key in settings
                ],
            }
        )
        expected_profiles.append(
            {
                "key": f"profile-{digest[:16]}",
                "name": f"SemanticLab_{safe_identity}_ShareSet_{digest[:12]}",
                "components_by_platform": settings,
            }
        )
    if profiles != expected_profiles:
        raise AudioMediaBusinessPlanError(
            "archived audio Conversion profile provenance drifted"
        )

    profile_by_signature = {
        tuple(tuple(item) for item in row["components_by_platform"]): row
        for row in profiles
    }
    if len(profile_by_signature) != len(profiles):
        raise AudioMediaBusinessPlanError(
            "archived audio Conversion profile signatures are duplicated"
        )
    profile_by_path: dict[str, Mapping[str, Any]] = {}
    for path, binding in binding_by_path.items():
        signature = tuple(
            tuple(item) for item in binding["settings_by_platform"]
        )
        profile = profile_by_signature.get(signature)
        if profile is None:
            raise AudioMediaBusinessPlanError(
                "archived audio Sound binding has no derived Conversion profile"
            )
        profile_by_path[path] = profile
    return preset_by_key, binding_by_path, profile_by_path


def _closed_string_pairs(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(part, str) and part for part in item)
            for item in value
        )
        and len({item[0] for item in value}) == len(value)
    )


def _reject_forbidden_audio_cache_aliases(
    artifacts_by_slot: Mapping[tuple[str, str, str], Mapping[str, Any]],
    *,
    preset_by_key: Mapping[str, Mapping[str, Any]],
    binding_by_path: Mapping[str, Mapping[str, Any]],
    context: str,
) -> None:
    """Allow only same-Sound aliases whose platform formats are equivalent."""

    observed: dict[str, tuple[str, str, str]] = {}
    for slot, artifact in artifacts_by_slot.items():
        converted_path = artifact.get("converted_path")
        if not isinstance(converted_path, str) or not converted_path:
            raise AudioMediaBusinessPlanError(
                f"{context} has an invalid converted cache path"
            )
        previous = observed.get(converted_path)
        if previous is not None and _audio_cache_alias_is_forbidden(
            previous,
            slot,
            preset_by_key=preset_by_key,
            binding_by_path=binding_by_path,
        ):
            raise AudioMediaBusinessPlanError(
                f"{context} reuses a converted cache alias across source slots "
                "or platform slots whose reviewed effective formats differ"
            )
        observed.setdefault(converted_path, slot)


def _audio_cache_alias_is_forbidden(
    left: tuple[str, str, str],
    right: tuple[str, str, str],
    *,
    preset_by_key: Mapping[str, Mapping[str, Any]],
    binding_by_path: Mapping[str, Mapping[str, Any]],
) -> bool:
    if (left[0], left[2]) != (right[0], right[2]):
        return True
    if left[1] == right[1]:
        return False
    binding = binding_by_path.get(left[0])
    if binding is None:
        return True
    settings = dict(binding["settings_by_platform"])
    left_component = preset_by_key.get(settings.get(left[1], ""))
    right_component = preset_by_key.get(settings.get(right[1], ""))
    if left_component is None or right_component is None:
        return True
    return (
        left_component["codec"],
        left_component["sample_rate"],
        left_component["channels"],
    ) != (
        right_component["codec"],
        right_component["sample_rate"],
        right_component["channels"],
    )


def _validate_archived_audio_static_and_live(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
    *,
    reviewed_scenario_fixture: Mapping[str, Any],
) -> None:
    if (
        static.get("family") != "audio_conversion"
        or static.get("family_schema_version") != AUDIO_SCHEMA
        or static.get("api") != AUDIO_CONVERT_URI
        or static.get("version") != AUDIO_VERSION
        or not isinstance(static.get("scenario_id"), str)
        or not static["scenario_id"]
        or not _is_sha256(static.get("scenario_fixture_sha256"))
    ):
        raise AudioMediaBusinessPlanError("archived audio static identity is invalid")
    request = static.get("operation_request")
    if (
        not isinstance(request, Mapping)
        or request.get("contract") != "waapi-skill.operation-request/v1"
        or request.get("version") != AUDIO_VERSION
        or request.get("operation") != "waapi.call"
        or not isinstance(request.get("arguments"), Mapping)
        or request["arguments"].get("api") != AUDIO_CONVERT_URI
        or static.get("operation_request_sha256") != _sha256(request)
    ):
        raise AudioMediaBusinessPlanError("archived audio operation request is invalid")
    dimensions: list[list[str]] = []
    for name in ("objects", "platforms", "languages"):
        values = static.get(name)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(item, str) or not item for item in values)
            or len(values) != len(set(values))
        ):
            raise AudioMediaBusinessPlanError(
                f"archived audio {name} dimension is invalid"
            )
        dimensions.append(values)
    expected_slots = [
        [object_path, platform, language]
        for object_path in dimensions[0]
        for platform in dimensions[1]
        for language in dimensions[2]
    ]
    if (
        live.get("target_slots") != expected_slots
        or static.get("expected_output_count") != len(expected_slots)
    ):
        raise AudioMediaBusinessPlanError("archived audio target slots are misbound")
    preset_by_key, binding_by_path, profile_by_path = _audio_profile_maps(static)
    before = live.get("before_snapshot")
    if not isinstance(before, Mapping) or set(before) != {
        "artifacts",
        "baseline_artifacts",
        "input_files",
        "originals_files",
        "authoring_files",
        "conversion_xml",
        "output_tree",
        "baseline_artifact_paths",
        "volatile_cache_files",
        "digest",
    }:
        raise AudioMediaBusinessPlanError("archived audio before snapshot is not closed")
    if before.get("digest") != live.get("before_snapshot_sha256"):
        raise AudioMediaBusinessPlanError("archived audio before digest fields disagree")
    before_by_slot = _archived_audio_artifacts_by_slot(before)
    _validate_audio_artifact_files_against_tree(before_by_slot, before)
    _validate_archived_audio_baseline_evidence(
        before,
        static=static,
        current_by_slot=before_by_slot,
    )
    _validate_archived_audio_volatile_cache_metadata(
        before.get("volatile_cache_files"),
        static=static,
        output_tree=before.get("output_tree"),
        artifacts_by_slot=before_by_slot,
    )
    _validate_archived_audio_converted_paths_owned(before_by_slot, static=static)
    _validate_archived_audio_baseline_paths(
        before.get("baseline_artifact_paths"),
        static=static,
        output_tree=before.get("output_tree"),
        artifact_count=len(before_by_slot),
    )
    _reject_forbidden_audio_cache_aliases(
        before_by_slot,
        preset_by_key=preset_by_key,
        binding_by_path=binding_by_path,
        context="archived audio",
    )
    if not set(map(tuple, expected_slots)).issubset(before_by_slot):
        raise AudioMediaBusinessPlanError("archived audio before omits target slots")
    observed_reference_by_path: dict[str, tuple[str, str]] = {}
    observed_id_by_profile: dict[str, str] = {}
    observed_profile_by_id: dict[str, str] = {}
    stale_format_path = (
        static["setting_delta"].get("path")
        if isinstance(static.get("setting_delta"), Mapping)
        else None
    )
    for slot, artifact in before_by_slot.items():
        binding = binding_by_path.get(slot[0])
        profile = profile_by_path.get(slot[0])
        setting_key = (
            dict(binding["settings_by_platform"]).get(slot[1])
            if isinstance(binding, Mapping)
            else None
        )
        preset = preset_by_key.get(setting_key)
        if (
            not isinstance(profile, Mapping)
            or not isinstance(preset, Mapping)
            or artifact["conversion_name"] != profile.get("name")
            or not isinstance(artifact["conversion_id"], str)
            or not artifact["conversion_id"]
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio artifact differs from its effective Conversion profile"
            )
        reference = (artifact["conversion_id"], artifact["conversion_name"])
        previous_reference = observed_reference_by_path.setdefault(slot[0], reference)
        if reference != previous_reference:
            raise AudioMediaBusinessPlanError(
                "archived audio Sound does not keep one global Conversion ShareSet "
                "across platform/language slots"
            )
        profile_key = str(profile["key"])
        previous_id = observed_id_by_profile.setdefault(
            profile_key, artifact["conversion_id"]
        )
        previous_profile = observed_profile_by_id.setdefault(
            artifact["conversion_id"], profile_key
        )
        if previous_id != artifact["conversion_id"] or previous_profile != profile_key:
            raise AudioMediaBusinessPlanError(
                "archived audio Conversion profile identity is inconsistent"
            )
        if (
            artifact["file"]["present"]
            and slot[0] != stale_format_path
            and (
                artifact["codec"] != preset["codec"]
                or artifact["sample_rate"] != preset["sample_rate"]
            )
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio artifact format differs from its platform component"
            )
    expected_artifacts = [
        {**row, "slot": list(slot)} for slot, row in before_by_slot.items()
    ]
    if live.get("artifact_fingerprints") != expected_artifacts:
        raise AudioMediaBusinessPlanError(
            "archived audio artifact fingerprints differ from before snapshot"
        )
    if (
        live.get("source_files") != before.get("input_files")
        or live.get("conversion_xml") != before.get("conversion_xml")
    ):
        raise AudioMediaBusinessPlanError(
            "archived audio source/XML bindings differ from before snapshot"
        )
    for name in ("input_files", "originals_files", "authoring_files", "output_tree"):
        rows = before.get(name)
        if not isinstance(rows, list):
            raise AudioMediaBusinessPlanError(
                f"archived audio {name} file list is invalid"
            )
        for row in rows:
            _validate_archived_file_state(row, label=f"audio.{name}")
    _validate_archived_file_state(before.get("conversion_xml"), label="audio.conversion_xml")


def _archived_audio_snapshot_digest(snapshot: Any) -> str:
    if not isinstance(snapshot, Mapping):
        raise AudioMediaBusinessPlanError("archived audio snapshot is not an object")
    required = {
        "artifacts",
        "baseline_artifacts",
        "input_files",
        "originals_files",
        "authoring_files",
        "conversion_xml",
        "output_tree",
        "baseline_artifact_paths",
        "volatile_cache_files",
        "digest",
    }
    if set(snapshot) != required:
        raise AudioMediaBusinessPlanError("archived audio snapshot schema is not closed")
    return _sha256(
        {
            "artifacts": snapshot["artifacts"],
            "baseline_artifacts": snapshot["baseline_artifacts"],
            "inputs": snapshot["input_files"],
            "originals": snapshot["originals_files"],
            "authoring_files": snapshot["authoring_files"],
            "conversion_xml": snapshot["conversion_xml"],
            "output_tree": snapshot["output_tree"],
            "baseline_artifact_paths": snapshot["baseline_artifact_paths"],
        }
    )


def _archived_audio_artifacts_by_slot(
    snapshot: Mapping[str, Any],
    *,
    field: str = "artifacts",
) -> dict[tuple[str, str, str], dict[str, Any]]:
    artifacts = snapshot.get(field)
    if not isinstance(artifacts, list):
        raise AudioMediaBusinessPlanError(f"archived audio {field} are invalid")
    keys = {
        "object_path",
        "object_id",
        "source_id",
        "source_key",
        "platform",
        "language",
        "conversion_id",
        "conversion_name",
        "original_path",
        "original_file",
        "converted_path",
        "file",
        "codec",
        "sample_rate",
    }
    values: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != keys:
            raise AudioMediaBusinessPlanError(
                f"archived audio {field} schema is not closed"
            )
        row = _json_value(raw)
        slot = (row["object_path"], row["platform"], row["language"])
        if (
            any(not isinstance(item, str) or not item for item in slot)
            or slot in values
        ):
            raise AudioMediaBusinessPlanError(
                f"archived audio {field} slot is invalid"
            )
        _validate_archived_file_state(row["original_file"], label="audio.original")
        _validate_archived_file_state(row["file"], label="audio.converted")
        values[slot] = row
    return values


def _validate_archived_file_state(value: Any, *, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "path",
        "present",
        "size",
        "sha256",
        "mtime_ns",
    }:
        raise AudioMediaBusinessPlanError(f"{label} file state is not closed")
    if (
        not isinstance(value.get("path"), str)
        or type(value.get("present")) is not bool
        or (
            value["present"]
            and (
                type(value.get("size")) is not int
                or value["size"] < 0
                or not _is_sha256(value.get("sha256"))
                or type(value.get("mtime_ns")) is not int
            )
        )
        or (
            not value["present"]
            and any(value.get(name) is not None for name in ("size", "sha256", "mtime_ns"))
        )
    ):
        raise AudioMediaBusinessPlanError(f"{label} file state values are invalid")


def _audio_io_root_from_static(static: Mapping[str, Any]) -> str:
    request = static.get("operation_request")
    arguments = request.get("arguments") if isinstance(request, Mapping) else None
    io_root = arguments.get("io_root") if isinstance(arguments, Mapping) else None
    if not isinstance(io_root, str) or not io_root or not Path(io_root).is_absolute():
        raise AudioMediaBusinessPlanError(
            "archived audio operation request has no absolute I/O root"
        )
    try:
        return str(Path(io_root).expanduser().resolve(strict=False))
    except OSError as exc:
        raise AudioMediaBusinessPlanError(
            "archived audio I/O root cannot be normalized"
        ) from exc


def _allowed_audio_volatile_cache_paths(static: Mapping[str, Any]) -> tuple[str, ...]:
    try:
        return audio_conversion_volatile_cache_paths(
            _audio_io_root_from_static(static)
        )
    except AudioConversionRuntimeError as exc:
        raise AudioMediaBusinessPlanError(
            "archived audio volatile cache allowlist cannot be derived"
        ) from exc


def _validate_archived_audio_volatile_cache_metadata(
    value: Any,
    *,
    static: Mapping[str, Any],
    output_tree: Any,
    artifacts_by_slot: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> None:
    expected_paths = _allowed_audio_volatile_cache_paths(static)
    if not isinstance(value, list) or len(value) != len(expected_paths):
        raise AudioMediaBusinessPlanError(
            "archived audio volatile cache metadata is not closed"
        )
    observed_paths: list[str] = []
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"path", "present", "size"}:
            raise AudioMediaBusinessPlanError(
                "archived audio volatile cache file state is not closed"
            )
        path = row.get("path")
        present = row.get("present")
        size = row.get("size")
        if (
            not isinstance(path, str)
            or type(present) is not bool
            or (
                present
                and (
                    type(size) is not int
                    or not 0 <= size <= _MAX_VOLATILE_CACHE_FILE_BYTES
                )
            )
            or (not present and size is not None)
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio volatile cache metadata is malformed or unbounded"
            )
        observed_paths.append(path)
    if tuple(observed_paths) != expected_paths:
        raise AudioMediaBusinessPlanError(
            "archived audio volatile cache paths differ from the exact allowlist"
        )
    if not isinstance(output_tree, list):
        raise AudioMediaBusinessPlanError("archived audio output tree is invalid")
    stable_paths = {
        row.get("path") for row in output_tree if isinstance(row, Mapping)
    }
    artifact_paths = {
        row.get("converted_path") for row in artifacts_by_slot.values()
    }
    if stable_paths & set(expected_paths) or artifact_paths & set(expected_paths):
        raise AudioMediaBusinessPlanError(
            "archived audio volatile cache paths overlap business output"
        )


def _validate_archived_audio_converted_paths_owned(
    artifacts_by_slot: Mapping[tuple[str, str, str], Mapping[str, Any]],
    *,
    static: Mapping[str, Any],
) -> None:
    owner = Path(_audio_io_root_from_static(static))
    for slot, artifact in artifacts_by_slot.items():
        raw_value = artifact.get("converted_path")
        file_state = artifact.get("file")
        if not isinstance(raw_value, str) or not isinstance(file_state, Mapping):
            raise AudioMediaBusinessPlanError(
                "archived audio converted path binding is malformed"
            )
        raw = Path(raw_value)
        if not raw.is_absolute():
            raise AudioMediaBusinessPlanError(
                f"archived audio converted path is not absolute: {slot}"
            )
        normalized = raw.expanduser().resolve(strict=False)
        if (
            normalized == owner
            or owner not in normalized.parents
            or str(normalized) != raw_value
            or file_state.get("path") != raw_value
        ):
            raise AudioMediaBusinessPlanError(
                f"archived audio converted path escapes or disagrees with its I/O root: {slot}"
            )


def _validate_archived_audio_baseline_paths(
    value: Any,
    *,
    static: Mapping[str, Any],
    output_tree: Any,
    artifact_count: int,
    require_output_subset: bool = True,
) -> None:
    owner = Path(_audio_io_root_from_static(static))
    if (
        not isinstance(value, list)
        or not value
        or len(value) > artifact_count
        or any(not isinstance(path, str) or not path for path in value)
        or value != sorted(set(value))
    ):
        raise AudioMediaBusinessPlanError(
            "archived audio baseline artifact path seal is invalid"
        )
    for raw_value in value:
        raw = Path(raw_value)
        normalized = raw.expanduser().resolve(strict=False)
        if (
            not raw.is_absolute()
            or normalized == owner
            or owner not in normalized.parents
            or str(normalized) != raw_value
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio baseline artifact path escapes its I/O root"
            )
    if not isinstance(output_tree, list) or any(
        not isinstance(row, Mapping) for row in output_tree
    ):
        raise AudioMediaBusinessPlanError(
            "archived audio baseline output tree is invalid"
        )
    stable_paths = {row.get("path") for row in output_tree}
    if require_output_subset and not stable_paths <= set(value):
        raise AudioMediaBusinessPlanError(
            "archived audio before stable output is not explained by baseline artifact readback"
        )


def _validate_archived_audio_baseline_evidence(
    snapshot: Mapping[str, Any],
    *,
    static: Mapping[str, Any],
    current_by_slot: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Validate the full pre-delta slot proof retained inside every snapshot."""

    baseline_by_slot = _archived_audio_artifacts_by_slot(
        snapshot,
        field="baseline_artifacts",
    )
    if set(baseline_by_slot) != set(current_by_slot):
        raise AudioMediaBusinessPlanError(
            "archived audio baseline slot matrix differs from current slots"
        )
    _validate_archived_audio_converted_paths_owned(baseline_by_slot, static=static)
    expected_paths = sorted(
        {row["converted_path"] for row in baseline_by_slot.values()}
    )
    if snapshot.get("baseline_artifact_paths") != expected_paths:
        raise AudioMediaBusinessPlanError(
            "archived audio baseline paths are not derived from slot evidence"
        )

    object_ids: dict[str, str] = {}
    source_ids: dict[tuple[str, str], str] = {}
    presets = static.get("presets")
    bindings = static.get("bindings")
    if not isinstance(presets, list) or not isinstance(bindings, list):
        raise AudioMediaBusinessPlanError(
            "archived audio baseline profile inputs are unavailable"
        )
    preset_by_key = {
        row.get("key"): row for row in presets if isinstance(row, Mapping)
    }
    binding_by_path = {
        row.get("path"): row for row in bindings if isinstance(row, Mapping)
    }
    setting_delta = static.get("setting_delta")
    source_delta_path = (
        static.get("source_delta", {}).get("path")
        if isinstance(static.get("source_delta"), Mapping)
        else None
    )
    for slot, baseline in baseline_by_slot.items():
        current = current_by_slot[slot]
        converted = baseline["file"]
        original = baseline["original_file"]
        binding = binding_by_path.get(slot[0])
        settings = (
            setting_delta.get("before_by_platform")
            if isinstance(setting_delta, Mapping)
            and setting_delta.get("path") == slot[0]
            else binding.get("settings_by_platform")
            if isinstance(binding, Mapping)
            else None
        )
        component = (
            preset_by_key.get(dict(settings).get(slot[1]))
            if isinstance(settings, list)
            else None
        )
        if (
            any(
                not isinstance(baseline.get(field), str) or not baseline[field]
                for field in (
                    "object_path",
                    "object_id",
                    "source_id",
                    "source_key",
                    "platform",
                    "language",
                    "conversion_id",
                    "conversion_name",
                    "original_path",
                    "converted_path",
                )
            )
            or baseline["object_id"] != current["object_id"]
            or (
                slot[0] != source_delta_path
                and baseline["source_id"] != current["source_id"]
            )
            or baseline["source_key"] != current["source_key"]
            or baseline["object_path"] != current["object_path"]
            or baseline["platform"] != current["platform"]
            or baseline["language"] != current["language"]
            or (
                slot[0] != source_delta_path
                and baseline["original_path"] != current["original_path"]
            )
            or converted.get("path") != baseline["converted_path"]
            or converted.get("present") is not True
            or type(converted.get("size")) is not int
            or converted["size"] <= 0
            or not _is_sha256(converted.get("sha256"))
            or type(converted.get("mtime_ns")) is not int
            or converted["mtime_ns"] <= 0
            or original.get("path") != baseline["original_path"]
            or original.get("present") is not True
            or type(original.get("size")) is not int
            or original["size"] <= 0
            or not _is_sha256(original.get("sha256"))
            or type(original.get("mtime_ns")) is not int
            or original["mtime_ns"] <= 0
            or not isinstance(baseline.get("codec"), str)
            or not baseline["codec"]
            or type(baseline.get("sample_rate")) is not int
            or baseline["sample_rate"] <= 0
            or not isinstance(component, Mapping)
            or baseline["codec"] != component.get("codec")
            or baseline["sample_rate"] != component.get("sample_rate")
        ):
            raise AudioMediaBusinessPlanError(
                "archived audio baseline artifact proof is malformed"
            )
        if object_ids.setdefault(slot[0], baseline["object_id"]) != baseline["object_id"]:
            raise AudioMediaBusinessPlanError(
                "archived audio baseline object identity varies across slots"
            )
        source_slot = (slot[0], slot[2])
        if source_ids.setdefault(source_slot, baseline["source_id"]) != baseline["source_id"]:
            raise AudioMediaBusinessPlanError(
                "archived audio baseline source identity varies across platforms"
            )
    if len(set(object_ids.values())) != len(object_ids) or len(
        set(source_ids.values())
    ) != len(source_ids):
        raise AudioMediaBusinessPlanError(
            "archived audio baseline identities alias distinct source slots"
        )

    controls = {
        row.get("path")
        for row in bindings
        if isinstance(row, Mapping) and row.get("control") is True
    }
    replacement_paths = {
        row.get("path")
        for row in (static.get("source_delta"), static.get("setting_delta"))
        if isinstance(row, Mapping)
    }
    retained_objects = controls | replacement_paths
    expected_retained = {
        row["converted_path"]: row["file"]
        for row in baseline_by_slot.values()
        if row["object_path"] in retained_objects
    }
    output_tree = snapshot.get("output_tree")
    if not isinstance(output_tree, list) or any(
        not isinstance(row, Mapping) for row in output_tree
    ):
        raise AudioMediaBusinessPlanError(
            "archived audio baseline output tree is invalid"
        )
    observed_retained = {row.get("path"): dict(row) for row in output_tree}
    if len(observed_retained) != len(output_tree) or observed_retained != expected_retained:
        raise AudioMediaBusinessPlanError(
            "archived audio retained baseline tree differs from its reviewed delta"
        )

    target_paths = set(static.get("objects", []))
    for slot, current in current_by_slot.items():
        baseline = baseline_by_slot[slot]
        if slot[0] in target_paths:
            if current["file"].get("present") is not False:
                raise AudioMediaBusinessPlanError(
                    "archived audio target must be absent before preview"
                )
            if (
                slot[0] in replacement_paths
                and current["converted_path"] == baseline["converted_path"]
            ):
                raise AudioMediaBusinessPlanError(
                    "archived audio changed target did not receive a new cache identity"
                )
        elif current != baseline:
            raise AudioMediaBusinessPlanError(
                "archived audio control differs from its sealed baseline"
            )
    return baseline_by_slot


def _validate_audio_artifact_files_against_tree(
    artifacts: Mapping[tuple[str, str, str], Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> None:
    output_rows = snapshot.get("output_tree")
    originals_rows = snapshot.get("originals_files")
    if not isinstance(output_rows, list) or not isinstance(originals_rows, list):
        raise AudioMediaBusinessPlanError("archived audio file trees are invalid")
    output_by_path = {
        row.get("path"): row for row in output_rows if isinstance(row, Mapping)
    }
    originals_by_path = {
        row.get("path"): row for row in originals_rows if isinstance(row, Mapping)
    }
    if len(output_by_path) != len(output_rows) or len(originals_by_path) != len(
        originals_rows
    ):
        raise AudioMediaBusinessPlanError("archived audio file tree paths are duplicated")
    for artifact in artifacts.values():
        converted = artifact["file"]
        converted_path = artifact["converted_path"]
        if converted["path"] != converted_path:
            raise AudioMediaBusinessPlanError(
                "archived converted artifact path fields disagree"
            )
        if converted["present"]:
            if output_by_path.get(converted_path) != converted:
                raise AudioMediaBusinessPlanError(
                    "archived converted artifact differs from output tree"
                )
        elif converted_path in output_by_path:
            raise AudioMediaBusinessPlanError(
                "archived absent converted artifact exists in output tree"
            )
        original = artifact["original_file"]
        if original["present"]:
            if originals_by_path.get(original["path"]) != original:
                raise AudioMediaBusinessPlanError(
                    "archived original artifact differs from Originals tree"
                )
        elif original["path"] in originals_by_path:
            raise AudioMediaBusinessPlanError(
                "archived absent original artifact exists in Originals tree"
            )


def _validate_audio_inputs(
    plan: AudioConversionPlan,
    before: AudioConversionSnapshot,
    protocol: V3GatewayProtocol,
) -> None:
    if not isinstance(plan, AudioConversionPlan) or not isinstance(before, AudioConversionSnapshot):
        raise AudioMediaBusinessPlanError("audio compiler requires AudioConversionPlan and AudioConversionSnapshot")
    if plan.operation_request.get("arguments", {}).get("api") != AUDIO_CONVERT_URI:
        raise AudioMediaBusinessPlanError("audio operation request is not ak.wwise.core.audio.convert")
    if plan.expected_output_count != len(_audio_target_slots(plan)):
        raise AudioMediaBusinessPlanError("audio expected output count does not close target slots")
    if before.digest != _audio_snapshot_digest(before):
        raise AudioMediaBusinessPlanError("audio before snapshot digest cannot be independently recomputed")
    expected_protocol = build_transaction_protocol([plan.operation_request])
    if _protocol_value(protocol) != _protocol_value(expected_protocol):
        raise AudioMediaBusinessPlanError("audio protocol does not exactly bind the sealed operation request")
    slots = {(item.object_path, item.platform, item.language) for item in before.artifacts}
    expected_slots = set(_audio_target_slots(plan))
    if not expected_slots.issubset(slots):
        raise AudioMediaBusinessPlanError("audio before snapshot omits a reviewed target slot")
    preset_by_key, archived_binding_by_path, profile_by_path = _audio_profile_maps(
        {
            "scenario_id": plan.scenario_id,
            "platforms": list(plan.platforms),
            "presets": _json_value(plan.presets),
            "profiles": _json_value(plan.profiles),
            "bindings": _json_value(plan.bindings),
            "setting_delta": _json_value(plan.setting_delta),
        }
    )
    _reject_forbidden_audio_cache_aliases(
        {
            item.slot: {"converted_path": item.converted_path}
            for item in before.artifacts
        },
        preset_by_key=preset_by_key,
        binding_by_path=archived_binding_by_path,
        context="audio before snapshot",
    )
    output_by_path = {item.path: item for item in before.output_tree}
    if len(output_by_path) != len(before.output_tree):
        raise AudioMediaBusinessPlanError(
            "audio before output tree contains duplicate paths"
        )
    typed_before_artifacts = {
        item.slot: _json_value(item) for item in before.artifacts
    }
    _validate_archived_audio_baseline_evidence(
        _json_value(before),
        static={
            "operation_request": _json_value(plan.operation_request),
            "presets": _json_value(plan.presets),
            "bindings": _json_value(plan.bindings),
            "source_delta": _json_value(plan.source_delta),
            "setting_delta": _json_value(plan.setting_delta),
            "objects": list(plan.objects),
        },
        current_by_slot=typed_before_artifacts,
    )
    _validate_archived_audio_volatile_cache_metadata(
        _json_value(before.volatile_cache_files),
        static={"operation_request": _json_value(plan.operation_request)},
        output_tree=_json_value(before.output_tree),
        artifacts_by_slot=typed_before_artifacts,
    )
    _validate_archived_audio_converted_paths_owned(
        typed_before_artifacts,
        static={"operation_request": _json_value(plan.operation_request)},
    )
    _validate_archived_audio_baseline_paths(
        _json_value(before.baseline_artifact_paths),
        static={"operation_request": _json_value(plan.operation_request)},
        output_tree=_json_value(before.output_tree),
        artifact_count=len(before.artifacts),
    )
    observed_reference_by_path: dict[str, tuple[str, str]] = {}
    observed_id_by_profile: dict[str, str] = {}
    observed_profile_by_id: dict[str, str] = {}
    stale_format_path = plan.setting_delta.path if plan.setting_delta is not None else None
    for artifact in before.artifacts:
        binding = archived_binding_by_path.get(artifact.object_path)
        if binding is None:
            raise AudioMediaBusinessPlanError(
                "audio before artifact references an unplanned object"
            )
        setting_key = dict(binding["settings_by_platform"]).get(artifact.platform)
        preset = preset_by_key.get(setting_key or "")
        profile = profile_by_path.get(artifact.object_path)
        if (
            preset is None
            or profile is None
            or artifact.conversion_name != profile["name"]
            or not artifact.conversion_id
        ):
            raise AudioMediaBusinessPlanError(
                "audio before artifact differs from its effective Conversion profile"
            )
        reference = (artifact.conversion_id, artifact.conversion_name)
        if observed_reference_by_path.setdefault(artifact.object_path, reference) != reference:
            raise AudioMediaBusinessPlanError(
                "audio before Sound does not keep one global Conversion ShareSet"
            )
        profile_key = str(profile["key"])
        if (
            observed_id_by_profile.setdefault(profile_key, artifact.conversion_id)
            != artifact.conversion_id
            or observed_profile_by_id.setdefault(artifact.conversion_id, profile_key)
            != profile_key
        ):
            raise AudioMediaBusinessPlanError(
                "audio before Conversion profile identity is inconsistent"
            )
        if (
            artifact.file.present
            and artifact.object_path != stale_format_path
            and (
                artifact.codec != preset["codec"]
                or artifact.sample_rate != preset["sample_rate"]
            )
        ):
            raise AudioMediaBusinessPlanError(
                "audio before artifact format differs from its platform component"
            )
        if artifact.file.path != artifact.converted_path:
            raise AudioMediaBusinessPlanError(
                "audio before artifact file/path fields disagree"
            )
        if (
            artifact.file.present
            and output_by_path.get(artifact.converted_path) != artifact.file
        ):
            raise AudioMediaBusinessPlanError(
                "audio before artifact is not bound to the output tree"
            )


def _validate_media_inputs(
    case: MaterializedMediaPoolCase,
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
    protocol: V3GatewayProtocol,
    *,
    project_digest: str,
) -> None:
    if not all(isinstance(value, expected) for value, expected in ((case, MaterializedMediaPoolCase), (staged, StagedMediaPoolCase), (oracle, SealedMediaPoolOracle))):
        raise AudioMediaBusinessPlanError("media compiler requires materialized, staged, and sealed dataclasses")
    if staged.materialized != case or oracle.scenario_id != case.scenario_id:
        raise AudioMediaBusinessPlanError("media case/stage/oracle identity is misbound")
    if oracle.source_fingerprint != case.source_fingerprint:
        raise AudioMediaBusinessPlanError("media oracle source fingerprint is not the materialized case fingerprint")
    if oracle.staged_fingerprint != staged.staged_fingerprint:
        raise AudioMediaBusinessPlanError("media oracle staged fingerprint is not the staged case fingerprint")
    if case.version != MEDIA_VERSION:
        raise AudioMediaBusinessPlanError("media business plan has an unsupported version")
    if not _is_sha256(project_digest):
        raise AudioMediaBusinessPlanError("media pre-Codex project digest is invalid")
    rows = tuple(oracle.rows)
    if tuple(oracle.candidate_keys) != tuple(case.expected_candidate_file_keys):
        raise AudioMediaBusinessPlanError(
            "media oracle candidate keys do not preserve the reviewed order"
        )
    if tuple(oracle.expected_keys) != tuple(case.expected_file_keys):
        raise AudioMediaBusinessPlanError("media oracle expected keys do not preserve the reviewed order")
    asset_keys = tuple(asset.key for asset in case.assets)
    staged_keys = tuple(item.asset.key for item in staged.assets)
    row_keys = tuple(row.key for row in rows)
    if staged_keys != asset_keys or row_keys != asset_keys:
        raise AudioMediaBusinessPlanError(
            "media sealed rows do not exactly close all fixture asset keys"
        )
    if not set(case.expected_file_keys).issubset(row_keys):
        raise AudioMediaBusinessPlanError(
            "media expected file keys are not contained in the sealed fixture rows"
        )
    if any(not row.file_id or not row.path or not row.db for row in rows):
        raise AudioMediaBusinessPlanError("media sealed row is missing live identity")
    binding = oracle.request.binding
    if not binding.available_fields or not binding.by_concept:
        raise AudioMediaBusinessPlanError("media field binding is empty")
    if case.association_expectations is not None and not case.association_expectations:
        raise AudioMediaBusinessPlanError("media association oracle may not be empty when association readback is required")
    answer = oracle.semantic_answer
    if answer != build_semantic_answer(case):
        raise AudioMediaBusinessPlanError(
            "media semantic answer differs from the canonical fixture plan"
        )
    rebound = bind_media_pool_request(case, binding)
    if (rebound.args, rebound.options, rebound.post_filter) != (
        oracle.request.args,
        oracle.request.options,
        oracle.request.post_filter,
    ):
        raise AudioMediaBusinessPlanError("media sealed request is not independently reproducible from its field binding")
    expected_protocol = _expected_media_protocol(case, oracle)
    if _protocol_value(protocol) != _protocol_value(expected_protocol):
        raise AudioMediaBusinessPlanError("media protocol does not exactly bind fields, request, and association readback")


def _expected_media_protocol(case: MaterializedMediaPoolCase, oracle: SealedMediaPoolOracle) -> V3GatewayProtocol:
    steps = [call_step("media.get-fields", MEDIA_POOL_GET_FIELDS_URI, version=MEDIA_VERSION)]
    steps.extend(
        typed_read_draft_steps(
            "media",
            MEDIA_POOL_GET_URI,
            version=MEDIA_VERSION,
            args=oracle.request.args,
            options=oracle.request.options,
            post_filter=oracle.request.post_filter,
        )
    )
    if case.association_expectations is not None:
        steps.append(
            query_object_step(
                "media.audio-sources",
                build_reference_match_gateway_argv(reference_match_paths(oracle)),
            )
        )
    return build_direct_protocol(steps)


def _audio_static(
    plan: AudioConversionPlan,
    *,
    scenario_fixture_sha256: str,
) -> dict[str, Any]:
    return _json_value({
        "family": "audio_conversion",
        "family_schema_version": AUDIO_SCHEMA,
        "api": AUDIO_CONVERT_URI,
        "version": AUDIO_VERSION,
        "scenario_id": plan.scenario_id,
        "scenario_fixture_sha256": scenario_fixture_sha256,
        "operation_request": plan.operation_request,
        "operation_request_sha256": _sha256(plan.operation_request),
        "objects": list(plan.objects), "platforms": list(plan.platforms), "languages": list(plan.languages),
        "presets": plan.presets, "profiles": plan.profiles,
        "bindings": plan.bindings,
        "source_delta": plan.source_delta, "setting_delta": plan.setting_delta,
        "missing_cache_paths": list(plan.missing_cache_paths),
        "expected_output_count": plan.expected_output_count,
    })


def _audio_live(plan: AudioConversionPlan, before: AudioConversionSnapshot) -> dict[str, Any]:
    artifacts = _audio_artifacts(before)
    return _json_value({
        "before_snapshot": _json_value(before),
        "before_snapshot_sha256": before.digest,
        "target_slots": [list(slot) for slot in _audio_target_slots(plan)],
        "source_files": _json_value(before.input_files),
        "artifact_fingerprints": artifacts,
        "conversion_xml": before.conversion_xml,
    })


def _audio_delta_rules(plan: AudioConversionPlan, before: AudioConversionSnapshot) -> dict[str, Any]:
    target_slots = set(_audio_target_slots(plan))
    replacement_paths = {
        item.path for item in (plan.source_delta, plan.setting_delta) if item is not None
    }
    artifacts = _audio_artifacts(before)
    refresh_slots = [
        item["slot"] for item in artifacts
        if tuple(item["slot"]) in target_slots and (
            not item["file"]["present"]
            or not item["file"]["size"]
        )
    ]
    baseline = [
        {**_json_value(item), "slot": list(item.slot)}
        for item in before.baseline_artifacts
    ]
    sha_change_slots = [
        item["slot"]
        for item in baseline
        if tuple(item["slot"]) in target_slots
        and item["object_path"] in replacement_paths
        and item["file"]["present"]
        and item["file"]["size"]
    ]
    controls = [item["slot"] for item in artifacts if tuple(item["slot"]) not in target_slots]
    return _json_value({
        "enum": "audio.conversion_delta_v1",
        "target_slots": [list(slot) for slot in sorted(target_slots)],
        "expected_output_count": plan.expected_output_count,
        "required_refresh_slots": refresh_slots,
        "required_sha_change_slots": sha_change_slots,
        "control_slots_unchanged": controls,
        "allowed_volatile_cache_paths": list(
            audio_conversion_volatile_cache_paths(plan.io_root)
        ),
        "immutable_subjects": {
            "input_files_sha256": _sha256(before.input_files),
            "originals_sha256": _sha256(before.originals_files),
            "authoring_files_sha256": _sha256(before.authoring_files),
            "conversion_xml_sha256": _sha256(before.conversion_xml),
            "baseline_artifacts_sha256": _sha256(
                before.baseline_artifacts
            ),
            "baseline_artifact_paths_sha256": _sha256(
                before.baseline_artifact_paths
            ),
            "non_target_output_sha256": _sha256([item for item in before.output_tree if item.path not in {artifact["converted_path"] for artifact in artifacts if tuple(artifact["slot"]) in target_slots}]),
        },
    })


def _audio_archive_delta(static: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    target_slots = {tuple(item) for item in live["target_slots"]}
    artifacts = live["artifact_fingerprints"]
    replacement_paths = {
        item["path"] for item in (static["source_delta"], static["setting_delta"])
        if isinstance(item, Mapping)
    }
    baseline = live["before_snapshot"]["baseline_artifacts"]
    refresh_slots = [item["slot"] for item in artifacts if tuple(item["slot"]) in target_slots and (not item["file"]["present"] or not item["file"]["size"])]
    sha_change_slots = [item["slot"] for item in ({**row, "slot": [row["object_path"], row["platform"], row["language"]]} for row in baseline) if tuple(item["slot"]) in target_slots and item["object_path"] in replacement_paths and item["file"]["present"] and item["file"]["size"]]
    controls = [item["slot"] for item in artifacts if tuple(item["slot"]) not in target_slots]
    before = live["before_snapshot"]
    target_paths = {item["converted_path"] for item in artifacts if tuple(item["slot"]) in target_slots}
    return {
        "enum": "audio.conversion_delta_v1",
        "target_slots": [list(slot) for slot in sorted(target_slots)],
        "expected_output_count": static["expected_output_count"],
        "required_refresh_slots": refresh_slots,
        "required_sha_change_slots": sha_change_slots,
        "control_slots_unchanged": controls,
        "allowed_volatile_cache_paths": list(
            _allowed_audio_volatile_cache_paths(static)
        ),
        "immutable_subjects": {
            "input_files_sha256": _sha256(before["input_files"]),
            "originals_sha256": _sha256(before["originals_files"]),
            "authoring_files_sha256": _sha256(before["authoring_files"]),
            "conversion_xml_sha256": _sha256(before["conversion_xml"]),
            "baseline_artifacts_sha256": _sha256(
                before["baseline_artifacts"]
            ),
            "baseline_artifact_paths_sha256": _sha256(
                before["baseline_artifact_paths"]
            ),
            "non_target_output_sha256": _sha256([item for item in before["output_tree"] if item["path"] not in target_paths]),
        },
    }


def _media_archive_delta(live: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "enum": "media.read_only_no_project_or_index_delta_v1",
        "project_digest_before": live["project_digest_before"],
        "source_fingerprint": live["source_fingerprint"],
        "staged_fingerprint": live["staged_fingerprint"],
        "sealed_row_ids": [
            {"key": row["key"], "file_id": row["file_id"], "path": row["path"], "db": row["db"]}
            for row in live["sealed_rows"]
        ],
        "request_sha256": live["request_sha256"],
    }


def _media_static(
    case: MaterializedMediaPoolCase,
    *,
    scenario_fixture_sha256: str,
) -> dict[str, Any]:
    return _json_value({
        "family": "media_pool", "family_schema_version": MEDIA_SCHEMA, "api": MEDIA_POOL_GET_URI, "version": MEDIA_VERSION,
        "scenario_id": case.scenario_id,
        "scenario_fixture_sha256": scenario_fixture_sha256,
        "request_template": case.request_template,
        "expected_candidate_file_keys": list(case.expected_candidate_file_keys),
        "expected_file_keys": list(case.expected_file_keys), "expected_groups": case.expected_groups,
        "association_expectations": case.association_expectations,
        "assets": case.assets, "databases": case.databases,
    })


def _media_live(case: MaterializedMediaPoolCase, staged: StagedMediaPoolCase, oracle: SealedMediaPoolOracle, *, project_digest: str) -> dict[str, Any]:
    return _json_value({
        "source_fingerprint": case.source_fingerprint,
        "staged_fingerprint": staged.staged_fingerprint,
        "project_digest_before": project_digest,
        "staged_assets": staged.assets,
        "request": {
            "args": oracle.request.args,
            "options": oracle.request.options,
            "binding": oracle.request.binding,
            "post_filter": oracle.request.post_filter,
        },
        "request_sha256": _sha256(
            {
                "args": oracle.request.args,
                "options": oracle.request.options,
                "post_filter": oracle.request.post_filter,
            }
        ),
        "sealed_rows": oracle.rows,
        "candidate_keys": list(oracle.candidate_keys),
        "expected_keys": list(oracle.expected_keys),
        "semantic_answer": oracle.semantic_answer,
    })


def _media_delta_rule(case: MaterializedMediaPoolCase, staged: StagedMediaPoolCase, oracle: SealedMediaPoolOracle, *, project_digest: str) -> dict[str, Any]:
    return _json_value({
        "enum": "media.read_only_no_project_or_index_delta_v1",
        "project_digest_before": project_digest,
        "source_fingerprint": case.source_fingerprint,
        "staged_fingerprint": staged.staged_fingerprint,
        "sealed_row_ids": [{"key": row.key, "file_id": row.file_id, "path": row.path, "db": row.db} for row in oracle.rows],
        "request_sha256": _sha256(
            {
                "args": oracle.request.args,
                "options": oracle.request.options,
                "post_filter": oracle.request.post_filter,
            }
        ),
    })


def _sections(*, fixture_kind: str, fixture_value: Mapping[str, Any], primary_steps: Sequence[str], verification_steps: Sequence[str], assertion_ids: Sequence[str], static: Mapping[str, Any], live: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]) -> AudioMediaBusinessPlanSections:
    fixture = _json_value(fixture_value)
    return AudioMediaBusinessPlanSections(
        fixture_spec=MappingProxyType({"kind": fixture_kind, "sha256": _sha256(fixture)}),
        payload_bindings=MappingProxyType({"primary_steps": list(primary_steps), "verification_steps": list(verification_steps)}),
        assertion_ids=tuple(assertion_ids), static_expectation=MappingProxyType(_json_value(static)),
        live_binding=MappingProxyType(_json_value(live)),
        delta_rules=tuple(MappingProxyType(_json_value(item)) for item in rules),
    )


def _rule(name: str) -> dict[str, str]:
    return {"enum": name}


def _audio_target_slots(plan: AudioConversionPlan) -> tuple[tuple[str, str, str], ...]:
    return tuple((path, platform, language) for path in plan.objects for platform in plan.platforms for language in plan.languages)


def _audio_snapshot_value(snapshot: AudioConversionSnapshot) -> dict[str, Any]:
    return _json_value({"artifacts": snapshot.artifacts, "baseline_artifacts": snapshot.baseline_artifacts, "inputs": snapshot.input_files, "originals": snapshot.originals_files, "authoring_files": snapshot.authoring_files, "conversion_xml": snapshot.conversion_xml, "output_tree": snapshot.output_tree, "baseline_artifact_paths": snapshot.baseline_artifact_paths})


def _audio_snapshot_digest(snapshot: AudioConversionSnapshot) -> str:
    return _sha256(_audio_snapshot_value(snapshot))


def _reviewed_scenario_fixture_sha256(
    reviewed_scenario_fixture: Mapping[str, Any],
) -> str:
    """Hash the immutable suite fixture, never an archive-derived projection."""

    if not isinstance(reviewed_scenario_fixture, Mapping):
        raise AudioMediaBusinessPlanError(
            "reviewed scenario fixture must be an independently supplied object"
        )
    return _sha256(_json_value(reviewed_scenario_fixture))


def _audio_artifacts(snapshot: AudioConversionSnapshot) -> list[dict[str, Any]]:
    return [
        {**_json_value(item), "slot": [item.object_path, item.platform, item.language]}
        for item in snapshot.artifacts
    ]


def _protocol_value(protocol: V3GatewayProtocol) -> dict[str, Any]:
    if not isinstance(protocol, V3GatewayProtocol):
        raise AudioMediaBusinessPlanError("protocol must be V3GatewayProtocol")
    return _json_value(serialize_protocol(protocol))


def _assert_same_sections(actual: AudioMediaBusinessPlanSections, expected: AudioMediaBusinessPlanSections, *, family: str) -> None:
    if not isinstance(actual, AudioMediaBusinessPlanSections):
        raise AudioMediaBusinessPlanError(f"{family} plan sections have the wrong type")
    if actual.writer_kwargs() != expected.writer_kwargs():
        raise AudioMediaBusinessPlanError(f"{family} plan sections differ from independently recomputed inputs")


def _verify_file_records(records: Any, *, field: str) -> None:
    if not isinstance(records, list):
        raise AudioMediaBusinessPlanError(f"{field} is not a closed file list")
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise AudioMediaBusinessPlanError(f"{field}[{index}] is not a file record")
        path = Path(str(row.get("path") or ""))
        present = row.get("present")
        if present is not True or not path.is_file() or path.stat().st_size != row.get("size") or _sha256_file(path) != row.get("sha256"):
            raise AudioMediaBusinessPlanError(f"{field}[{index}] no longer matches its sealed fingerprint")


def _verify_media_files(case: MaterializedMediaPoolCase, staged: StagedMediaPoolCase) -> None:
    if case.source_fingerprint != fingerprint_tree(case.source_fingerprint.root):
        raise AudioMediaBusinessPlanError("media source tree no longer matches its sealed fingerprint")
    if staged.staged_fingerprint != fingerprint_staged_media_assets(staged.assets):
        raise AudioMediaBusinessPlanError("media staged tree no longer matches its sealed fingerprint")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(item in "0123456789abcdef" for item in value)


def _canonical(value: Any) -> bytes:
    return json.dumps(_json_value(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_value(value: Any) -> Any:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, PurePath):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=lambda item: _canonical(item))
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise AudioMediaBusinessPlanError(f"unserializable typed business-plan value: {type(value).__name__}")


def _plain(value: Any) -> Any:
    return _json_value(value)


__all__ = [
    "AudioMediaBusinessPlanError", "AudioMediaBusinessPlanSections",
    "compile_audio_conversion_business_plan", "validate_audio_conversion_business_plan",
    "compile_media_pool_business_plan", "validate_media_pool_business_plan",
    "parse_audio_media_business_plan_sections", "validate_audio_media_business_plan_archive",
    "validate_audio_archived_verification", "validate_media_archived_verification",
]

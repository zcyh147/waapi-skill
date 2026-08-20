"""Typed pre-Codex business-oracle plans for object.get/create/set.

The reviewed recipe remains the static trust root.  A trusted project runner
adds the materialized Wwise identities, the complete before snapshot, and any
fixture WAV fingerprints before Codex is constructed.  Archived validation
recomputes the recipe/protocol projection and validates the sealed live state;
it never treats a field copied from the plan as its own expected value.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_archive_paths import (
    ArchiveAbsolutePath,
    ArchiveRelativePathError,
    parse_archive_absolute_path,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_direct_protocol,
    build_metadata_transaction_protocol,
    build_modification_policy_protocol,
    build_schema_query_transaction_protocol,
    build_transaction_protocol,
    query_object_step,
)
from tests.semantic.support.codex_filesystem_security import (
    CodexFileSecurityError,
    read_bounded_exclusive_regular_file,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftActionMetadataBinding,
    DraftTypedActionBatchArgument,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS,
    ObjectHeavyRecipe,
    OperationRequestSpec,
    QueryObjectRequestSpec,
)
from tests.semantic.support.codex_object_runtime_v3 import ObjectRuntimeSnapshot
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol
from tests.semantic.support.codex_version_layout_v3 import (
    get_codex_version_layout_v3,
)


OBJECT_BUSINESS_PLAN_SCHEMA = "waapi-skill.object-business-plan/v1"
OBJECT_FIXTURE_KIND = "object_materialized_v1"
OBJECT_APIS = frozenset(
    {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }
)
TYPED_PROFILE_SET03_UNIT_ID = "TYP22-METADATA-OBJECT-SET"
TYPED_PROFILE_OBJECT_METADATA_UNITS = MappingProxyType(
    {
        TYPED_PROFILE_SET03_UNIT_ID: (
            "OBJ22-F-SET-03",
            "ak.wwise.core.object.set",
            "2022.1",
            ("volume", "pitch", "notes", "output bus"),
            ("Volume", "Pitch", "OutputBus"),
        ),
        "TYP23-DEDICATED-OBJECT-CREATE": (
            "OBJ22-F-CREATE-03",
            "ak.wwise.core.object.create",
            "2023.1",
            ("volume",),
            ("Volume",),
        ),
        "TYP24-METADATA-OBJECT-SET": (
            "OBJ22-F-SET-01",
            "ak.wwise.core.object.set",
            "2024.1",
            ("volume",),
            ("Volume",),
        ),
        "TYP25-METADATA-OBJECT-SET": (
            "OBJ22-F-SET-02",
            "ak.wwise.core.object.set",
            "2025.1",
            ("volume",),
            ("Volume",),
        ),
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_OBJECT_INPUT_FILE_BYTES = 256 * 1024 * 1024
_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_OUTPUT_BUS_OVERRIDE_TYPES = frozenset(
    {"ActorMixer", "PropertyContainer", "RandomSequenceContainer", "Sound"}
)


class ObjectBusinessPlanError(ValueError):
    """An object family plan is incomplete, cross-bound, or mutable."""


@dataclass(frozen=True, slots=True)
class ObjectBusinessPlanSections:
    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]

    def writer_kwargs(self) -> dict[str, Any]:
        return {
            "fixture_spec": _json_value(self.fixture_spec),
            "payload_bindings": _json_value(self.payload_bindings),
            "assertion_ids": list(self.assertion_ids),
            "static_expectation": _json_value(self.static_expectation),
            "live_binding": _json_value(self.live_binding),
            "delta_rules": [_json_value(item) for item in self.delta_rules],
        }


def seal_object_input_file_manifest(
    files: Mapping[str, Path],
) -> tuple[Mapping[str, Any], ...]:
    """Fingerprint the exact fixture inputs without following symlinks."""

    if not isinstance(files, Mapping):
        raise ObjectBusinessPlanError("object input files must be a key/path mapping")
    rows: list[Mapping[str, Any]] = []
    seen_paths: set[ArchiveAbsolutePath] = set()
    for key in sorted(files):
        if not isinstance(key, str) or not key:
            raise ObjectBusinessPlanError("object input file key is invalid")
        path = Path(files[key]).expanduser()
        absolute = Path(os.path.abspath(os.fspath(path)))
        try:
            snapshot = read_bounded_exclusive_regular_file(
                absolute,
                max_bytes=_MAX_OBJECT_INPUT_FILE_BYTES,
                require_private_posix_mode=False,
            )
        except CodexFileSecurityError as exc:
            raise ObjectBusinessPlanError(
                "object input file must be one bounded, exclusive, "
                f"non-reparse regular file: {absolute}"
            ) from exc
        text = str(absolute)
        try:
            path_identity = parse_archive_absolute_path(text)
        except ArchiveRelativePathError as exc:  # pragma: no cover - host invariant
            raise ObjectBusinessPlanError(
                f"object input file path is not a valid absolute host path: {text}"
            ) from exc
        if path_identity in seen_paths:
            raise ObjectBusinessPlanError("object input file paths must be unique")
        seen_paths.add(path_identity)
        rows.append(
            MappingProxyType(
                {
                    "key": key,
                    "path": text,
                    "size": snapshot.metadata.st_size,
                    "sha256": hashlib.sha256(snapshot.raw).hexdigest(),
                }
            )
        )
    return tuple(rows)


def compile_object_business_plan(
    scenario: Any,
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
    before: ObjectRuntimeSnapshot,
    input_file_manifest: Sequence[Mapping[str, Any]] = (),
    *,
    profile_unit_id: str | None = None,
) -> ObjectBusinessPlanSections:
    """Compile one exact object plan from reviewed and live runner inputs."""

    _validate_identity(scenario, recipe)
    _validate_protocol(
        recipe,
        protocol,
        scenario=scenario,
        profile_unit_id=profile_unit_id,
    )
    before_value = _validate_before_snapshot(recipe, before)
    file_rows = _validate_input_manifest(
        input_file_manifest,
        required_keys={
            item.key
            for item in recipe.fixture.objects
            if item.object_type == "Sound" and item.source_language is not None
        },
        verify_files=True,
    )
    static = _static_expectation(
        recipe,
        protocol,
        profile_unit_id=profile_unit_id,
    )
    live = _live_binding(before_value, file_rows)
    rules = _delta_rules(recipe, before_value)
    primary_steps, verification_steps = _step_partition(recipe, protocol)
    return _build_sections(
        recipe=recipe,
        static=static,
        live=live,
        rules=rules,
        primary_steps=primary_steps,
        verification_steps=verification_steps,
    )


def parse_object_business_plan_sections(
    plan_payload: Mapping[str, Any],
) -> ObjectBusinessPlanSections:
    """Parse only the six family sections from a closed common plan payload."""

    if not isinstance(plan_payload, Mapping):
        raise ObjectBusinessPlanError("object business plan payload is not an object")
    required = {
        "fixture_spec",
        "payload_bindings",
        "assertion_ids",
        "static_expectation",
        "live_binding",
        "delta_rules",
    }
    if not required.issubset(plan_payload):
        raise ObjectBusinessPlanError("object business plan omits family sections")
    fixture = plan_payload["fixture_spec"]
    bindings = plan_payload["payload_bindings"]
    assertions = plan_payload["assertion_ids"]
    static_value = plan_payload["static_expectation"]
    live_value = plan_payload["live_binding"]
    rules = plan_payload["delta_rules"]
    if not isinstance(fixture, Mapping) or set(fixture) != {"kind", "sha256"}:
        raise ObjectBusinessPlanError("object fixture_spec schema is not closed")
    if fixture.get("kind") != OBJECT_FIXTURE_KIND or not _is_sha256(
        fixture.get("sha256")
    ):
        raise ObjectBusinessPlanError("object fixture_spec identity is invalid")
    if not isinstance(bindings, Mapping) or set(bindings) != {
        "primary_steps",
        "verification_steps",
    }:
        raise ObjectBusinessPlanError("object payload_bindings schema is not closed")
    if not isinstance(assertions, list) or any(
        not isinstance(item, str) or not item for item in assertions
    ):
        raise ObjectBusinessPlanError("object assertion_ids are invalid")
    if not isinstance(static_value, Mapping) or not isinstance(live_value, Mapping):
        raise ObjectBusinessPlanError("object static/live sections must be objects")
    if not isinstance(rules, list) or any(not isinstance(item, Mapping) for item in rules):
        raise ObjectBusinessPlanError("object delta_rules must be object rows")
    return ObjectBusinessPlanSections(
        fixture_spec=MappingProxyType(_json_value(fixture)),
        payload_bindings=MappingProxyType(_json_value(bindings)),
        assertion_ids=tuple(assertions),
        static_expectation=MappingProxyType(_json_value(static_value)),
        live_binding=MappingProxyType(_json_value(live_value)),
        delta_rules=tuple(MappingProxyType(_json_value(item)) for item in rules),
    )


def validate_object_business_plan(
    sections: ObjectBusinessPlanSections,
    *,
    scenario: Any,
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
    before: ObjectRuntimeSnapshot,
    input_file_manifest: Sequence[Mapping[str, Any]] = (),
    verify_files: bool = False,
    profile_unit_id: str | None = None,
) -> None:
    """Recompile from live dataclasses and compare every persisted section."""

    expected = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        input_file_manifest,
        profile_unit_id=profile_unit_id,
    )
    if sections.writer_kwargs() != expected.writer_kwargs():
        raise ObjectBusinessPlanError(
            "object plan differs from independently recomputed runner inputs"
        )
    if verify_files:
        _validate_input_manifest(
            sections.live_binding["input_files"],
            required_keys={row["key"] for row in sections.live_binding["input_files"]},
            verify_files=True,
        )


def validate_archived_object_business_plan(
    plan_payload: Mapping[str, Any],
    *,
    scenario: Any,
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
    verify_files: bool = False,
    profile_unit_id: str | None = None,
) -> ObjectBusinessPlanSections:
    """Validate an archived plan after scenario-owned state may be removed."""

    _validate_identity(scenario, recipe)
    _validate_protocol(
        recipe,
        protocol,
        scenario=scenario,
        profile_unit_id=profile_unit_id,
    )
    sections = parse_object_business_plan_sections(plan_payload)
    static = _static_expectation(
        recipe,
        protocol,
        profile_unit_id=profile_unit_id,
    )
    if sections.static_expectation != static:
        raise ObjectBusinessPlanError(
            "object static expectation differs from reviewed recipe/protocol"
        )
    live = sections.live_binding
    if set(live) != {
        "family_schema_version",
        "before_snapshot",
        "before_snapshot_sha256",
        "key_bindings",
        "input_files",
    } or live.get("family_schema_version") != OBJECT_BUSINESS_PLAN_SCHEMA:
        raise ObjectBusinessPlanError("object live binding schema is not closed")
    before_value = _validate_archived_before(recipe, live.get("before_snapshot"))
    if live.get("before_snapshot_sha256") != before_value["digest"]:
        raise ObjectBusinessPlanError("object archived before digest is misbound")
    if live.get("key_bindings") != before_value["objects"]:
        raise ObjectBusinessPlanError("object key bindings differ from before snapshot")
    file_rows = _validate_input_manifest(
        live.get("input_files"),
        required_keys={
            item.key
            for item in recipe.fixture.objects
            if item.object_type == "Sound" and item.source_language is not None
        },
        verify_files=verify_files,
    )
    expected_rules = _delta_rules(recipe, before_value)
    if tuple(_json_value(item) for item in sections.delta_rules) != expected_rules:
        raise ObjectBusinessPlanError("object delta rules differ from reviewed oracle")
    primary_steps, verification_steps = _step_partition(recipe, protocol)
    expected = _build_sections(
        recipe=recipe,
        static=static,
        live=_live_binding(before_value, file_rows),
        rules=expected_rules,
        primary_steps=primary_steps,
        verification_steps=verification_steps,
    )
    if sections.writer_kwargs() != expected.writer_kwargs():
        raise ObjectBusinessPlanError(
            "object archived plan differs from independently recomputed values"
        )
    return sections


def validate_object_archived_verification(
    sections: ObjectBusinessPlanSections,
    verification: Mapping[str, Any],
) -> None:
    """Join the post-run oracle evidence to the exact pre-Codex plan."""

    if not isinstance(sections, ObjectBusinessPlanSections):
        raise ObjectBusinessPlanError("object verification requires parsed plan sections")
    if not isinstance(verification, Mapping) or set(verification) != {
        "phase",
        "passed",
        "failures",
        "evidence",
    }:
        raise ObjectBusinessPlanError("object archived verification schema is not closed")
    if verification.get("passed") is not True or verification.get("failures") != []:
        raise ObjectBusinessPlanError("object archived verification is not a clean pass")
    evidence = verification.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ObjectBusinessPlanError("object archived verification evidence is invalid")
    before = sections.live_binding["before_snapshot"]
    if evidence.get("before") != before:
        raise ObjectBusinessPlanError(
            "object oracle before snapshot differs from the pre-Codex plan"
        )
    api = sections.static_expectation["api"]
    if verification.get("phase") == "policy_read_only":
        if (
            api not in {
                "ak.wwise.core.object.create",
                "ak.wwise.core.object.set",
            }
            or sections.payload_bindings.get("primary_steps") != []
            or set(evidence) != {"before", "after"}
            or evidence.get("after") != before
        ):
            raise ObjectBusinessPlanError(
                "object read-only policy oracle differs from its sealed baseline"
            )
        return
    if api == "ak.wwise.core.object.get":
        if verification.get("phase") != "query" or len(sections.delta_rules) != 1:
            raise ObjectBusinessPlanError("object.get verification phase/rules are invalid")
        rule = sections.delta_rules[0]
        request = sections.static_expectation["request"]["value"]
        expected_payload = (
            rule["bounded_superset_keys"]
            if request.get("result_strategy")
            == "bounded_superset_final_answer_filter"
            else rule["exact_expected_keys"]
        )
        if (
            set(evidence) != {
                "before",
                "after",
                "observed_keys",
                "expected_payload_keys",
                "primary_row_policy",
                "raw_row_count",
                "query_bound",
                "bound_reached",
                "derived_row_policy",
                "derived_rows",
                "required_keys",
                "excluded_keys",
                "final_answer_policy",
                "required_identity_tokens",
                "excluded_identity_tokens",
                "paired_rows",
                "deduplicated_parent_rows",
                "coverage_summary",
                "observed_answer_order",
                "final_response_sha256",
            }
            or rule.get("primary_row_policy") != request.get("primary_row_policy")
            or rule.get("derived_row_policy") != request.get("derived_row_policy")
            or rule.get("final_answer_policy") != request.get("final_answer_policy")
            or evidence.get("primary_row_policy") != rule.get("primary_row_policy")
            or evidence.get("derived_row_policy") != rule.get("derived_row_policy")
            or evidence.get("final_answer_policy") != rule.get("final_answer_policy")
            or evidence.get("expected_payload_keys") != expected_payload
            or not isinstance(evidence.get("observed_keys"), list)
            or not isinstance(evidence.get("raw_row_count"), int)
            or isinstance(evidence.get("raw_row_count"), bool)
            or evidence.get("query_bound")
            != {"mode": "take", "value": request.get("take")}
            or evidence.get("bound_reached")
            is not (evidence.get("raw_row_count") == request.get("take"))
            or evidence.get("required_keys") != rule["exact_expected_keys"]
            or evidence.get("excluded_keys") != rule["excluded_keys"]
            or not isinstance(evidence.get("after"), Mapping)
            or evidence["after"].get("digest") != before["digest"]
            or not _is_sha256(evidence.get("final_response_sha256"))
        ):
            raise ObjectBusinessPlanError(
                "object.get oracle keys or read-only snapshot differ from plan"
            )
        _validate_archived_query_primary_rows(
            before,
            rule,
            request,
            evidence,
        )
        _validate_archived_query_derived_rows(
            before,
            expected_payload,
            policy=str(rule["derived_row_policy"]),
            observed=evidence.get("derived_rows"),
        )
        if evidence["raw_row_count"] != len(evidence["observed_keys"]) + len(
            evidence["derived_rows"]
        ):
            raise ObjectBusinessPlanError(
                "object.get raw row count differs from primary/derived evidence"
            )
        _validate_archived_query_answer(
            before,
            rule,
            evidence,
        )
        return
    if verification.get("phase") != "after" or len(sections.delta_rules) != 3:
        raise ObjectBusinessPlanError("object mutation verification phase/rules are invalid")
    expected_rule, identity_rule, _oracle_rule = sections.delta_rules
    expected_keys = [item["key"] for item in expected_rule["expected_objects"]]
    resolved = evidence.get("resolved")
    if (
        not isinstance(resolved, Mapping)
        or evidence.get("expected_resolved_keys") != expected_keys
        or set(resolved) != set(expected_keys)
        or evidence.get("removed_keys") != identity_rule["removed_keys"]
        or evidence.get("protected_keys") != identity_rule["protected_snapshot_keys"]
    ):
        raise ObjectBusinessPlanError(
            "object mutation oracle identity sets differ from the pre-Codex plan"
        )
    before_by_key = {row["key"]: row for row in before["objects"]}
    expected_protected = {
        key: before_by_key[key]
        for key in identity_rule["protected_snapshot_keys"]
    }
    if evidence.get("protected_before") != expected_protected:
        raise ObjectBusinessPlanError(
            "object mutation protected snapshot differs from the pre-Codex plan"
        )
    before_ids = {row["id"] for row in before["objects"]}
    resolved_rows: dict[str, Mapping[str, Any]] = {}
    for expected in expected_rule["expected_objects"]:
        key = expected["key"]
        row = resolved[key]
        _validate_resolved_object_row(row, label=f"resolved.{key}")
        if row["key"] != key:
            raise ObjectBusinessPlanError("object resolved symbolic key differs from plan")
        resolved_rows[key] = row
        if row["type"] != expected["object_type"]:
            raise ObjectBusinessPlanError("object resolved type differs from plan")
        if expected["identity_policy"] == "new_renamed":
            if not row["name"].startswith(expected["requested_name"]):
                raise ObjectBusinessPlanError("object renamed result differs from plan")
        elif row["name"] != expected["requested_name"]:
            raise ObjectBusinessPlanError("object resolved name differs from plan")
        if expected["path"] is not None and row["path"] != expected["path"]:
            raise ObjectBusinessPlanError("object resolved path differs from plan")
        previous = before_by_key.get(key)
        if expected["identity_policy"] in {"preserve", "borrowed_snapshot"}:
            if previous is None or row["id"] != previous["id"]:
                raise ObjectBusinessPlanError(
                    "object resolved preserve identity differs from plan"
                )
        elif expected["identity_policy"] in {
            "new",
            "new_renamed",
            "replace_with_new",
        } and row["id"] in before_ids:
            raise ObjectBusinessPlanError("object resolved new identity reused before GUID")
    resolved_ids = [row["id"] for row in resolved_rows.values()]
    if len(resolved_ids) != len(set(resolved_ids)):
        raise ObjectBusinessPlanError("object resolved identities are not unique")
    for expected in expected_rule["expected_objects"]:
        key = expected["key"]
        row = resolved_rows[key]
        previous = before_by_key.get(key)
        parent = resolved_rows.get(expected["parent_key"]) or before_by_key.get(
            expected["parent_key"]
        )
        if expected["parent_key"] is not None and parent is None:
            raise ObjectBusinessPlanError(
                "object resolved parent is absent from resolved and before state"
            )
        if parent is not None and row["parent_id"] != parent["id"]:
            raise ObjectBusinessPlanError("object resolved parent GUID differs from plan")
        if expected["parent_path"] is not None and row["path"].rsplit("\\", 1)[0] != expected[
            "parent_path"
        ]:
            raise ObjectBusinessPlanError("object resolved parent path differs from plan")
        for field in expected["fields"]:
            actual = _resolved_field(row, field["name"])
            mode = field["mode"]
            if mode == "literal" and actual != field["value"]:
                raise ObjectBusinessPlanError("object resolved literal field differs")
            if mode == "object_key_id":
                target = resolved_rows.get(str(field["value"])) or before_by_key.get(
                    str(field["value"])
                )
                if target is None or actual != target["id"]:
                    raise ObjectBusinessPlanError("object resolved reference differs")
            if mode == "derived_children_count" and actual != len(expected["children"]):
                raise ObjectBusinessPlanError("object resolved children count differs")
            if mode == "sealed_fixture_snapshot":
                if previous is None or actual != _resolved_field(previous, field["name"]):
                    raise ObjectBusinessPlanError("object resolved sealed field differs")
        child_rows: list[Mapping[str, Any]] = []
        for child_key in expected["children"]:
            child = resolved_rows.get(child_key) or before_by_key.get(child_key)
            if child is None:
                raise ObjectBusinessPlanError(
                    "object expected child is absent from resolved and before state"
                )
            child_rows.append(child)
        if any(child["parent_id"] != row["id"] for child in child_rows):
            raise ObjectBusinessPlanError("object resolved child parent differs from plan")
        if expected["children"] and row["children_count"] != len(expected["children"]):
            raise ObjectBusinessPlanError("object resolved topology differs from plan")
    removed_readback = evidence.get("removed_readback")
    if not isinstance(removed_readback, Mapping) or any(
        value not in ([], {}) for value in removed_readback.values()
    ):
        raise ObjectBusinessPlanError("object removed identity still has archived readback")
    _validate_archived_protected_comparisons(
        expected_protected,
        evidence.get("protected_after"),
        evidence.get("protected_comparisons"),
        before_snapshot=before,
        after_snapshot=evidence.get("after"),
        expected_objects=expected_rule["expected_objects"],
        resolved_rows=resolved_rows,
        recipe=sections.static_expectation["recipe"],
    )


def _validate_archived_protected_comparisons(
    expected_before: Mapping[str, Mapping[str, Any]],
    observed_after: Any,
    comparisons: Any,
    *,
    before_snapshot: Mapping[str, Any],
    after_snapshot: Any,
    expected_objects: Sequence[Mapping[str, Any]],
    resolved_rows: Mapping[str, Mapping[str, Any]],
    recipe: Mapping[str, Any],
) -> None:
    # Older sealed campaigns predate intrinsic-state projections.  Their
    # protected evidence is still valid only when the complete after snapshot
    # is byte-for-byte equivalent to the sealed before snapshot.
    if comparisons is None:
        if observed_after != expected_before:
            raise ObjectBusinessPlanError(
                "object protected after snapshot differs from plan"
            )
        return
    if (
        not isinstance(observed_after, Mapping)
        or not isinstance(comparisons, Mapping)
        or set(observed_after) != set(expected_before)
        or set(comparisons) != set(expected_before)
    ):
        raise ObjectBusinessPlanError(
            "object protected intrinsic comparison keys differ from plan"
        )
    if not isinstance(after_snapshot, Mapping):
        raise ObjectBusinessPlanError("object protected after snapshot is invalid")
    before_overrides = _archived_override_output_map(
        before_snapshot.get("override_output_rows"),
        required_keys=set(expected_before),
        label="object protected before",
    )
    after_overrides = _archived_override_output_map(
        after_snapshot.get("override_output_rows"),
        required_keys=set(expected_before),
        label="object protected after",
    )
    before_by_key = {
        row["key"]: row
        for row in before_snapshot.get("objects", [])
        if isinstance(row, Mapping) and isinstance(row.get("key"), str)
    }
    comparison_keys = {
        "override_output_before",
        "override_output_after",
        "ignored_derived_fields",
        "before_projection",
        "after_projection",
        "passed",
    }
    for key, before in expected_before.items():
        after = observed_after[key]
        comparison = comparisons[key]
        _validate_resolved_object_row(after, label=f"protected_after.{key}")
        if not isinstance(comparison, Mapping) or set(comparison) != comparison_keys:
            raise ObjectBusinessPlanError(
                "object protected intrinsic comparison schema is invalid"
            )
        before_override = comparison.get("override_output_before")
        after_override = comparison.get("override_output_after")
        override_required = before.get("type") in _OUTPUT_BUS_OVERRIDE_TYPES
        if (
            before_overrides.get(key) != before_override
            or after_overrides.get(key) != after_override
        ):
            raise ObjectBusinessPlanError(
                "object protected OverrideOutput differs from sealed snapshots"
            )
        if override_required and (
            type(before_override) is not bool or type(after_override) is not bool
        ):
            raise ObjectBusinessPlanError(
                "object protected OverrideOutput evidence is not explicit"
            )
        if before_override != after_override:
            raise ObjectBusinessPlanError(
                "object protected OverrideOutput changed"
            )
        ignored_fields, inherited_mismatches = (
            _archived_inherited_effective_fields(
                key,
                before=before,
                current=after,
                before_by_key=before_by_key,
                resolved_rows=resolved_rows,
                expected_objects=expected_objects,
                recipe=recipe,
                before_override=before_override,
                after_override=after_override,
            )
        )
        if inherited_mismatches:
            raise ObjectBusinessPlanError(
                "object protected inherited effective fields differ from "
                f"reviewed parent: {', '.join(inherited_mismatches)}"
            )
        before_projection = _archived_intrinsic_projection(
            before,
            ignored_derived_fields=ignored_fields,
        )
        after_projection = _archived_intrinsic_projection(
            after,
            ignored_derived_fields=ignored_fields,
        )
        if (
            comparison.get("ignored_derived_fields") != list(ignored_fields)
            or comparison.get("before_projection") != before_projection
            or comparison.get("after_projection") != after_projection
            or comparison.get("passed") is not True
            or before_projection != after_projection
        ):
            raise ObjectBusinessPlanError(
                "object protected intrinsic projection differs from plan"
            )


def _archived_override_output_map(
    value: Any,
    *,
    required_keys: set[str],
    label: str,
) -> dict[str, bool | None]:
    if not isinstance(value, list):
        raise ObjectBusinessPlanError(f"{label} OverrideOutput rows are missing")
    result: dict[str, bool | None] = {}
    for row in value:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or row[0] in result
            or row[1] is not None
            and type(row[1]) is not bool
        ):
            raise ObjectBusinessPlanError(f"{label} OverrideOutput row is invalid")
        result[row[0]] = row[1]
    if not required_keys.issubset(result):
        raise ObjectBusinessPlanError(f"{label} OverrideOutput keys are incomplete")
    return result


def _archived_inherited_effective_fields(
    key: str,
    *,
    before: Mapping[str, Any],
    current: Mapping[str, Any],
    before_by_key: Mapping[str, Mapping[str, Any]],
    resolved_rows: Mapping[str, Mapping[str, Any]],
    expected_objects: Sequence[Mapping[str, Any]],
    recipe: Mapping[str, Any],
    before_override: bool | None,
    after_override: bool | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        recipe.get("scenario_id") != "OBJ22-F-SET-03"
        or current.get("key") != key
        or before.get("key") != key
    ):
        return (), ()
    fixture = recipe.get("fixture")
    fixture_objects = fixture.get("objects") if isinstance(fixture, Mapping) else None
    fixture_rows = (
        [
            row
            for row in fixture_objects
            if isinstance(row, Mapping) and row.get("key") == key
        ]
        if isinstance(fixture_objects, list)
        else []
    )
    if len(fixture_rows) != 1:
        raise ObjectBusinessPlanError(
            "object protected fixture identity is not unique"
        )
    fixture_row = fixture_rows[0]
    expected_by_key = {str(row["key"]): row for row in expected_objects}
    graph_by_id = {str(row["id"]): row for row in before_by_key.values()}
    graph_by_id.update({str(row["id"]): row for row in resolved_rows.values()})
    parent = graph_by_id.get(str(current.get("parent_id") or ""))
    fixture_path = fixture_row.get("path")
    if (
        parent is None
        or before.get("parent_id") != parent.get("id")
        or not isinstance(fixture_path, str)
        or fixture_path.rsplit("\\", 1)[0] != parent.get("path")
    ):
        return (), ()
    expected = expected_by_key.get(str(parent.get("key")))
    before_parent = before_by_key.get(str(parent.get("key")))
    if (
        expected is None
        or before_parent is None
        or before_parent.get("id") != parent.get("id")
    ):
        return (), ()

    properties = fixture_row.get("properties")
    references = fixture_row.get("references")
    if not isinstance(properties, list) or not isinstance(references, list):
        raise ObjectBusinessPlanError(
            "object protected fixture local fields are invalid"
        )
    local_properties = {
        str(row.get("name"))
        for row in properties
        if isinstance(row, Mapping)
    }
    local_references = {
        str(row.get("name"))
        for row in references
        if isinstance(row, Mapping)
    }
    expected_fields = expected.get("fields")
    if not isinstance(expected_fields, list):
        raise ObjectBusinessPlanError(
            "object reviewed parent fields are invalid"
        )

    ignored: list[str] = []
    mismatches: list[str] = []
    for field_name, local_name in (
        ("@Volume", "Volume"),
        ("@Pitch", "Pitch"),
    ):
        fields = [
            field
            for field in expected_fields
            if isinstance(field, Mapping)
            and field.get("name") == field_name
            and field.get("mode") == "literal"
        ]
        if len(fields) > 1:
            raise ObjectBusinessPlanError(
                f"object reviewed parent has duplicate {field_name} fields"
            )
        if not fields or local_name in local_properties:
            continue
        if (
            _resolved_field(before, field_name)
            == _resolved_field(before_parent, field_name)
            and _resolved_field(current, field_name) == fields[0].get("value")
        ):
            ignored.append(field_name)
        # Only an exact reviewed parent transition is safe to erase from the
        # archived projection.  Otherwise retain the field and compare the
        # protected child's before/after value strictly.

    output_fields = [
        field
        for field in expected_fields
        if isinstance(field, Mapping)
        and field.get("name") == "OutputBus"
        and field.get("mode") == "object_key_id"
    ]
    if len(output_fields) > 1:
        raise ObjectBusinessPlanError(
            "object reviewed parent has duplicate OutputBus fields"
        )
    # Archived Wwise 2022 rows can expose an effective true flag even though
    # the sealed child fixture contains no local OutputBus authoring.  The
    # explicit flag must remain stable and both bus identities must still
    # equal the exact reviewed parent transition.
    if (
        output_fields
        and "OutputBus" not in local_references
        and type(before_override) is bool
        and after_override == before_override
    ):
        target_key = str(output_fields[0].get("value"))
        target = resolved_rows.get(target_key) or before_by_key.get(target_key)
        if target is None:
            raise ObjectBusinessPlanError(
                "object reviewed inherited OutputBus target is unresolved"
            )
        if (
            _resolved_field(before, "OutputBus")
            != _resolved_field(before_parent, "OutputBus")
            or _resolved_field(current, "OutputBus") != target.get("id")
        ):
            mismatches.append("OutputBus")
        else:
            ignored.append("OutputBus")
    return tuple(ignored), tuple(mismatches)


def _archived_intrinsic_projection(
    value: Mapping[str, Any],
    *,
    ignored_derived_fields: Sequence[str],
) -> dict[str, Any]:
    result = _json_value(value)
    if not isinstance(result, dict):  # pragma: no cover - guarded by row validator
        raise ObjectBusinessPlanError(
            "object protected projection source is invalid"
        )
    ignored = set(ignored_derived_fields)
    if ignored.intersection({"@Volume", "@Pitch"}):
        result["properties"] = [
            row
            for row in result["properties"]
            if f"@{row.get('name')}" not in ignored
        ]
    if "OutputBus" in ignored:
        result["references"] = [
            row
            for row in result["references"]
            if row.get("name") != "OutputBus"
        ]
    return result


def _validate_archived_query_primary_rows(
    before: Mapping[str, Any],
    rule: Mapping[str, Any],
    request: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    observed = evidence["observed_keys"]
    expected = evidence["expected_payload_keys"]
    policy = rule.get("primary_row_policy")
    expected_bound = rule.get("expected_bound")
    if expected_bound is not None and expected_bound != {
        "take": request.get("take"),
        "reached": evidence.get("bound_reached"),
    }:
        raise ObjectBusinessPlanError(
            "object.get bound-reached evidence differs from reviewed oracle"
        )
    if policy == "unique_identity_rows":
        if (
            len(observed) != len(expected)
            or len(observed) != len(set(observed))
            or set(observed) != set(expected)
        ):
            raise ObjectBusinessPlanError(
                "object.get unique primary identities differ from plan"
            )
        return
    if policy == "ancestor_identity_rows":
        before_by_key = {row["key"]: row for row in before["objects"]}
        chain = [before_by_key[key] for key in rule["expected_order_keys"]]
        target = before_by_key.get("q5_target")
        if (
            len(observed) != len(expected)
            or len(observed) != len(set(observed))
            or set(observed) != set(expected)
            or evidence.get("raw_row_count") != len(expected)
            or evidence.get("bound_reached") is not False
            or target is None
            or not chain
            or target["parent_id"] != chain[0]["id"]
            or any(
                child["parent_id"] != parent["id"]
                for child, parent in zip(chain, chain[1:])
            )
            or any(row["type"] == "Project" for row in chain)
        ):
            raise ObjectBusinessPlanError(
                "object.get ordered ancestor rows differ from plan"
            )
        expected_counts = {
            "RandomSequenceContainer": sum(
                before_by_key[key]["type"] == "RandomSequenceContainer"
                for key in expected
            ),
            "ActorMixer": sum(
                before_by_key[key]["type"] == "ActorMixer"
                for key in expected
            ),
            "WorkUnit": sum(
                before_by_key[key]["type"] == "WorkUnit"
                for key in expected
            ),
            "Default Work Unit": sum(
                before_by_key[key]["name"] == "Default Work Unit"
                for key in expected
            ),
        }
        if rule.get("expected_answer_counts") != expected_counts:
            raise ObjectBusinessPlanError(
                "object.get ordered ancestor counts differ from sealed chain"
            )
        return
    if policy != "parent_projection_per_source_row":
        raise ObjectBusinessPlanError("object.get primary-row policy is unknown")
    if rule.get("final_answer_policy") != "deduplicated_parent_summary":
        raise ObjectBusinessPlanError(
            "object.get duplicate parent policy lacks its final-answer boundary"
        )
    if (
        set(observed) != set(expected)
        or len(observed) == len(set(observed))
        or len(observed) != request.get("take")
        or evidence.get("raw_row_count") != request.get("take")
        or evidence.get("bound_reached") is not True
    ):
        raise ObjectBusinessPlanError(
            "object.get parent-projection row stream is not the reached bound"
        )
    before_by_key = {row["key"]: row for row in before["objects"]}
    counts = Counter(observed)
    capacities = {
        key: sum(
            row["type"] == "Sound"
            and row["parent_id"] == before_by_key[key]["id"]
            for row in before["objects"]
        )
        for key in expected
    }
    if any(not 1 <= counts[key] <= capacities[key] for key in expected):
        raise ObjectBusinessPlanError(
            "object.get parent-projection multiplicity exceeds sealed Sound edges"
        )
    direct_child_objects = sum(
        before_by_key[key]["children_count"] for key in expected
    )
    expected_counts = {
        "unique_parents": len(expected),
        "returned_sound_edges": len(observed),
        "direct_child_objects": direct_child_objects,
        "fixture_eligible_sound_edges": sum(capacities.values()),
    }
    if (
        rule.get("expected_answer_counts") != expected_counts
        or sum(capacities.values()) <= request.get("take")
    ):
        raise ObjectBusinessPlanError(
            "object.get parent-projection counts differ from sealed topology"
        )


def _validate_archived_query_derived_rows(
    before: Mapping[str, Any],
    expected_payload: Sequence[str],
    *,
    policy: str,
    observed: Any,
) -> None:
    if not isinstance(observed, list):
        raise ObjectBusinessPlanError("object.get derived rows are not an array")
    if policy == "none":
        if observed:
            raise ObjectBusinessPlanError(
                "object.get unapproved derived rows were archived"
            )
        return
    if policy != "active_audio_sources_for_sound_rows":
        raise ObjectBusinessPlanError("object.get derived-row policy is unknown")
    before_by_key = {row["key"]: row for row in before["objects"]}
    expected: list[dict[str, Any]] = []
    for key in expected_payload:
        sound = before_by_key[key]
        if sound["type"] != "Sound" or sound["source_language"] is None:
            continue
        _validate_active_source_fields(
            sound,
            label=f"object.get derived source {key}",
            require=True,
        )
        expected.append(
            {
                "sound_key": key,
                "sound_id": sound["id"],
                "id": sound["active_source_id"],
                "name": sound["active_source_name"],
                "type": "AudioFileSource",
                "path": sound["active_source_path"],
                "parent_id": sound["id"],
                "language": sound["source_language"],
            }
        )
    row_keys = {
        "sound_key",
        "sound_id",
        "id",
        "name",
        "type",
        "path",
        "parent_id",
        "language",
    }
    if any(not isinstance(row, Mapping) or set(row) != row_keys for row in observed):
        raise ObjectBusinessPlanError("object.get derived row schema is not closed")
    if observed != expected:
        raise ObjectBusinessPlanError(
            "object.get derived rows differ from sealed activeSource bindings"
        )


def _validate_archived_query_answer(
    before: Mapping[str, Any],
    rule: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    before_by_key = {row["key"]: row for row in before["objects"]}
    required_keys = list(rule["exact_expected_keys"])
    excluded_keys = list(rule["excluded_keys"])
    policy = rule["final_answer_policy"]
    required = evidence.get("required_identity_tokens")
    excluded = evidence.get("excluded_identity_tokens")
    paired = evidence.get("paired_rows")
    deduplicated = evidence.get("deduplicated_parent_rows")
    coverage = evidence.get("coverage_summary")
    answer_order = evidence.get("observed_answer_order")
    if not all(
        isinstance(value, list)
        for value in (required, excluded, paired, deduplicated, answer_order)
    ):
        raise ObjectBusinessPlanError("object.get final-answer proof arrays are invalid")
    if policy == "name_and_id":
        expected_required = [
            {
                "key": key,
                "name": before_by_key[key]["name"],
                "id": before_by_key[key]["id"],
                "name_present": True,
                "id_present": True,
            }
            for key in required_keys
        ]
        expected_excluded = [
            {
                "key": key,
                "id": before_by_key[key]["id"],
                "id_present": False,
            }
            for key in excluded_keys
        ]
        if (
            required != expected_required
            or excluded != expected_excluded
            or paired != []
            or deduplicated != []
            or coverage is not None
            or answer_order != []
        ):
            raise ObjectBusinessPlanError(
                "object.get name/GUID answer proof differs from sealed identities"
            )
        return
    if policy == "deduplicated_parent_summary":
        expected_required = [
            {
                "key": key,
                "name": before_by_key[key]["name"],
                "id": before_by_key[key]["id"],
                "name_present": True,
                "id_present": True,
            }
            for key in required_keys
        ]
        expected_excluded = [
            {
                "key": key,
                "id": before_by_key[key]["id"],
                "id_present": False,
            }
            for key in excluded_keys
        ]
        if (
            required != expected_required
            or excluded != expected_excluded
            or paired != []
            or answer_order != list(rule["expected_order_keys"])
            or len(deduplicated) != len(required_keys)
        ):
            raise ObjectBusinessPlanError(
                "object.get deduplicated parent identity proof differs from plan"
            )
        before_by_id = {row["id"]: row for row in before["objects"]}
        previous_line = -1
        row_keys = {
            "key",
            "name",
            "id",
            "path",
            "children_count",
            "notes",
            "output_bus_id",
            "output_bus_name",
            "line_index",
            "line_sha256",
        }
        for row, key in zip(deduplicated, required_keys, strict=True):
            parent = before_by_key[key]
            bus_ids = [
                value["target_id"]
                for value in parent["references"]
                if value["name"] == "OutputBus"
            ]
            bus = before_by_id.get(bus_ids[0]) if len(bus_ids) == 1 else None
            if (
                not isinstance(row, Mapping)
                or set(row) != row_keys
                or bus is None
                or row.get("key") != key
                or row.get("name") != parent["name"]
                or row.get("id") != parent["id"]
                or row.get("path") != parent["path"]
                or row.get("children_count") != parent["children_count"]
                or row.get("notes") != parent["notes"]
                or row.get("output_bus_id") != bus["id"]
                or row.get("output_bus_name") != bus["name"]
                or type(row.get("line_index")) is not int
                or row["line_index"] <= previous_line
                or not _is_sha256(row.get("line_sha256"))
            ):
                raise ObjectBusinessPlanError(
                    "object.get deduplicated parent row differs from sealed fields"
                )
            previous_line = row["line_index"]
        direct_child_objects = sum(
            before_by_key[key]["children_count"] for key in required_keys
        )
        if (
            not isinstance(coverage, Mapping)
            or set(coverage)
            != {
                "unique_parent_count",
                "confirmed_sound_count",
                "direct_child_object_count",
                "summary_line_index",
                "bound_disclosed",
                "incomplete_disclosed",
                "claims_twelve_sounds",
            }
            or coverage.get("unique_parent_count") != len(required_keys)
            or coverage.get("confirmed_sound_count")
            != evidence.get("raw_row_count")
            or coverage.get("direct_child_object_count") != direct_child_objects
            or type(coverage.get("summary_line_index")) is not int
            or coverage["summary_line_index"] < 0
            or coverage.get("bound_disclosed") is not True
            or coverage.get("incomplete_disclosed") is not True
            or coverage.get("claims_twelve_sounds") is not False
        ):
            raise ObjectBusinessPlanError(
                "object.get parent coverage summary differs from sealed evidence"
            )
        return
    if policy == "ordered_ancestor_summary":
        expected_required = [
            {
                "key": key,
                "name": before_by_key[key]["name"],
                "id": before_by_key[key]["id"],
                "name_present": True,
                "id_present": True,
            }
            for key in required_keys
        ]
        expected_excluded = [
            {
                "key": key,
                "id": before_by_key[key]["id"],
                "id_present": False,
            }
            for key in excluded_keys
        ]
        if (
            required != expected_required
            or excluded != expected_excluded
            or paired != []
            or answer_order != list(rule["expected_order_keys"])
            or len(deduplicated) != len(required_keys)
        ):
            raise ObjectBusinessPlanError(
                "object.get ordered ancestor identity proof differs from plan"
            )
        previous_line = -1
        row_keys = {
            "key",
            "name",
            "id",
            "type",
            "path",
            "children_count",
            "notes",
            "notes_present",
            "ordinal",
            "ordinal_present",
            "numeric_values",
            "line_index",
            "line_sha256",
        }
        for ordinal, (row, key) in enumerate(
            zip(deduplicated, required_keys, strict=True),
            start=1,
        ):
            ancestor = before_by_key[key]
            allowed_numeric_values = (
                [float(ancestor["children_count"])],
                [float(ordinal), float(ancestor["children_count"])],
            )
            if (
                not isinstance(row, Mapping)
                or set(row) != row_keys
                or row.get("key") != key
                or row.get("name") != ancestor["name"]
                or row.get("id") != ancestor["id"]
                or row.get("type") != ancestor["type"]
                or row.get("path") != ancestor["path"]
                or row.get("children_count") != ancestor["children_count"]
                or row.get("notes") != ancestor["notes"]
                or row.get("notes_present") is not True
                or row.get("ordinal") != ordinal
                or not isinstance(row.get("ordinal_present"), bool)
                or row.get("numeric_values") not in allowed_numeric_values
                or row.get("ordinal_present")
                is not (
                    row.get("numeric_values") == allowed_numeric_values[1]
                )
                or type(row.get("line_index")) is not int
                or row["line_index"] <= previous_line
                or not _is_sha256(row.get("line_sha256"))
            ):
                raise ObjectBusinessPlanError(
                    "object.get ordered ancestor row differs from sealed fields"
                )
            previous_line = row["line_index"]
        type_counts = {
            "random_sequence_container_count": sum(
                before_by_key[key]["type"] == "RandomSequenceContainer"
                for key in required_keys
            ),
            "actor_mixer_count": sum(
                before_by_key[key]["type"] == "ActorMixer"
                for key in required_keys
            ),
            "work_unit_count": sum(
                before_by_key[key]["type"] == "WorkUnit"
                for key in required_keys
            ),
            "default_work_unit_count": sum(
                before_by_key[key]["name"] == "Default Work Unit"
                for key in required_keys
            ),
        }
        if (
            not isinstance(coverage, Mapping)
            or set(coverage)
            != {
                *type_counts,
                "raw_row_count",
                "take",
                "bound_reached",
                "summary_line_indexes",
                "truncation_claimed",
            }
            or any(coverage.get(key) != value for key, value in type_counts.items())
            or coverage.get("raw_row_count") != evidence.get("raw_row_count")
            or coverage.get("take") != evidence.get("query_bound", {}).get("value")
            or coverage.get("bound_reached") is not False
            or coverage.get("truncation_claimed") is not False
            or not isinstance(coverage.get("summary_line_indexes"), list)
            or not coverage["summary_line_indexes"]
            or any(
                type(index) is not int or index < 0
                for index in coverage["summary_line_indexes"]
            )
        ):
            raise ObjectBusinessPlanError(
                "object.get ordered ancestor summary differs from sealed chain"
            )
        return
    if policy != "paired_path_rows":
        raise ObjectBusinessPlanError("object.get final-answer policy is unknown")
    if deduplicated != [] or coverage is not None:
        raise ObjectBusinessPlanError(
            "object.get paired answer contains deduplicated-parent evidence"
        )
    if [row.get("key") for row in required if isinstance(row, Mapping)] != required_keys:
        raise ObjectBusinessPlanError("object.get required path keys differ from plan")
    for row, key in zip(required, required_keys, strict=True):
        if (
            not isinstance(row, Mapping)
            or set(row) != {"key", "path", "occurrence_count", "first_line"}
            or row.get("path") != before_by_key[key]["path"]
            or type(row.get("occurrence_count")) is not int
            or row["occurrence_count"] < 1
            or type(row.get("first_line")) is not int
            or row["first_line"] < 0
        ):
            raise ObjectBusinessPlanError(
                "object.get required standalone path proof is invalid"
            )
    expected_excluded = [
        {"key": key, "path": before_by_key[key]["path"], "occurrence_count": 0}
        for key in excluded_keys
    ]
    if excluded != expected_excluded:
        raise ObjectBusinessPlanError(
            "object.get excluded standalone path proof differs from plan"
        )
    id_to_key = {row["id"]: row["key"] for row in before["objects"]}
    expected_children = [
        key
        for key in rule["expected_order_keys"]
        if before_by_key[key]["type"] == "Sound"
        and id_to_key.get(before_by_key[key]["parent_id"]) in required_keys
    ]
    if answer_order != expected_children or len(paired) != len(expected_children):
        raise ObjectBusinessPlanError("object.get paired answer order differs from plan")
    previous_line = -1
    pair_keys = {
        "child_key",
        "parent_key",
        "parent_path",
        "child_path",
        "language",
        "volume",
        "notes",
        "line_index",
        "line_sha256",
        "parent_path_count",
        "child_path_count",
        "language_present",
        "volume_values",
        "notes_present",
        "unexpected_languages",
        "unexpected_notes",
    }
    for row, child_key in zip(paired, expected_children, strict=True):
        if not isinstance(row, Mapping) or set(row) != pair_keys:
            raise ObjectBusinessPlanError("object.get paired row schema is not closed")
        child = before_by_key[child_key]
        parent_key = id_to_key.get(child["parent_id"])
        parent = before_by_key.get(parent_key)
        volume_rows = [
            value["value"]
            for value in child["properties"]
            if value["name"] == "Volume"
        ]
        if (
            parent is None
            or len(volume_rows) != 1
            or row.get("child_key") != child_key
            or row.get("parent_key") != parent_key
            or row.get("parent_path") != parent["path"]
            or row.get("child_path") != child["path"]
            or row.get("language") != child["source_language"]
            or row.get("volume") != float(volume_rows[0])
            or row.get("notes") != child["notes"]
            or type(row.get("line_index")) is not int
            or row["line_index"] <= previous_line
            or not _is_sha256(row.get("line_sha256"))
            or row.get("parent_path_count") != 1
            or row.get("child_path_count") != 1
            or row.get("language_present") is not True
            or row.get("volume_values") != [float(volume_rows[0])]
            or row.get("notes_present") is not True
            or row.get("unexpected_languages") != []
            or row.get("unexpected_notes") != []
        ):
            raise ObjectBusinessPlanError(
                "object.get paired row differs from sealed parent/child fields"
            )
        previous_line = row["line_index"]


def _validate_resolved_object_row(value: Any, *, label: str) -> None:
    keys = {
        "key",
        "id",
        "name",
        "type",
        "path",
        "parent_id",
        "notes",
        "properties",
        "references",
        "source_language",
        "is_included",
        "children_count",
        "active_source_id",
        "active_source_name",
        "active_source_path",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or not _GUID_RE.fullmatch(str(value.get("id") or ""))
        or not isinstance(value.get("name"), str)
        or not isinstance(value.get("type"), str)
        or not isinstance(value.get("path"), str)
        or not isinstance(value.get("properties"), list)
        or not isinstance(value.get("references"), list)
        or type(value.get("children_count")) is not int
    ):
        raise ObjectBusinessPlanError(f"{label} is not a closed materialized object")
    _validate_active_source_fields(value, label=label, require=False)
    for row in value["properties"]:
        if not isinstance(row, Mapping) or set(row) != {"name", "value"}:
            raise ObjectBusinessPlanError(f"{label} has an invalid property row")
    for row in value["references"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"name", "target_id"}
            or not _GUID_RE.fullmatch(str(row.get("target_id") or ""))
        ):
            raise ObjectBusinessPlanError(f"{label} has an invalid reference row")


def _validate_active_source_fields(
    value: Mapping[str, Any],
    *,
    label: str,
    require: bool,
) -> None:
    source_id = value.get("active_source_id")
    source_name = value.get("active_source_name")
    source_path = value.get("active_source_path")
    present = tuple(item is not None for item in (source_id, source_name, source_path))
    if any(present) and not all(present):
        raise ObjectBusinessPlanError(f"{label} has a partial activeSource binding")
    if require and not all(present):
        raise ObjectBusinessPlanError(f"{label} omits its activeSource binding")
    if not any(present):
        return
    if (
        not _GUID_RE.fullmatch(str(source_id or ""))
        or not isinstance(source_name, str)
        or not source_name
        or not isinstance(source_path, str)
        or not source_path.startswith("\\")
        or "\\\\" in source_path
        or source_path != f"{value.get('path')}\\{source_name}"
        or value.get("type") != "Sound"
        or not isinstance(value.get("source_language"), str)
        or not value.get("source_language")
    ):
        raise ObjectBusinessPlanError(f"{label} has an invalid activeSource binding")


def _resolved_field(value: Mapping[str, Any], name: str) -> Any:
    if name in {"id", "name", "type", "path", "notes"}:
        return value.get(name)
    if name == "parent":
        return value.get("parent_id")
    if name == "childrenCount":
        return value.get("children_count")
    if name == "audioSource:language":
        return value.get("source_language")
    if name == "isIncluded":
        return value.get("is_included")
    if name.startswith("@"):
        return {
            row.get("name"): row.get("value")
            for row in value.get("properties", [])
            if isinstance(row, Mapping)
        }.get(name[1:])
    return {
        row.get("name"): row.get("target_id")
        for row in value.get("references", [])
        if isinstance(row, Mapping)
    }.get(name)


def _validate_identity(scenario: Any, recipe: ObjectHeavyRecipe) -> None:
    if not isinstance(recipe, ObjectHeavyRecipe):
        raise ObjectBusinessPlanError("object plan requires ObjectHeavyRecipe")
    if (
        recipe.api not in OBJECT_APIS
        or getattr(scenario, "id", None) != recipe.scenario_id
        or getattr(scenario, "api", None) != recipe.api
        or recipe.version not in tuple(getattr(scenario, "versions", ()))
    ):
        raise ObjectBusinessPlanError("object scenario and reviewed recipe are misbound")


def _compound_metadata_protocol(
    scenario: Any,
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
    *,
    profile_unit_id: str | None,
) -> V3GatewayProtocol | None:
    if profile_unit_id is not None:
        reviewed = TYPED_PROFILE_OBJECT_METADATA_UNITS.get(profile_unit_id)
        if reviewed is None or (
            recipe.scenario_id,
            recipe.api,
            recipe.version,
        ) != reviewed[:3]:
            raise ObjectBusinessPlanError(
                "object metadata profile unit is outside its reviewed lane"
            )
        metadata_queries = reviewed[3]
        required_tokens = reviewed[4]
    else:
        metadata_queries = ()
        required_tokens = ()

    fixture = getattr(scenario, "fixture", {})
    asset_spec = fixture.get("asset_spec") if isinstance(fixture, Mapping) else None
    value = (
        asset_spec.get("metadata_binding")
        if isinstance(asset_spec, Mapping)
        else None
    )
    if profile_unit_id is None and value is None:
        return None
    if profile_unit_id is None:
        if (
            recipe.scenario_id
            not in {
                "OBJ22-F-CREATE-03",
                "OBJ22-F-SET-01",
                "OBJ22-F-SET-02",
            }
            or not isinstance(value, Mapping)
            or set(value) != {"contract", "queries", "required_tokens"}
            or value.get("contract") != "waapi-skill.compound-object-metadata/v1"
            or value.get("queries") != ["volume"]
            or value.get("required_tokens") != ["Volume"]
        ):
            raise ObjectBusinessPlanError(
                "compound object metadata binding differs from the reviewed profile"
            )
        metadata_queries = ("volume",)
        required_tokens = ("Volume",)
    metadata_bindings: list[DraftActionMetadataBinding] = []
    for step in protocol.steps:
        candidates: list[object] = [step.metadata_binding]
        for argument in step.arguments:
            candidates.append(getattr(argument, "metadata_binding", None))
            if isinstance(argument, DraftTypedActionBatchArgument):
                candidates.extend(action.metadata_binding for action in argument.actions)
        metadata_bindings.extend(
            binding
            for binding in candidates
            if isinstance(binding, DraftActionMetadataBinding)
        )
    metadata_arguments = tuple(dict.fromkeys(metadata_bindings))
    if (
        len(metadata_arguments) != 1
        or metadata_arguments[0].expected_projection is None
    ):
        raise ObjectBusinessPlanError(
            "compound object protocol omits its trusted live metadata projection"
        )
    object_type = get_codex_version_layout_v3(recipe.version).reflected_type(
        "ActorMixer"
    )
    return build_metadata_transaction_protocol(
        (recipe.request.as_dict(version=recipe.version),),
        object_type=object_type,
        metadata_queries=metadata_queries,
        required_tokens=required_tokens,
        expected_required_token_projection=(
            metadata_arguments[0].expected_projection
        ),
        equivalence=(
            "object_set_v1"
            if recipe.request.operation == "object.set"
            else "wire_exact"
        ),
        schema_first=True,
    )


def build_object_merge_query_protocol(
    scenario: Any,
    recipe: ObjectHeavyRecipe,
) -> V3GatewayProtocol | None:
    """Require exact live type evidence for the compound same-name merge."""

    fixture = getattr(scenario, "fixture", {})
    asset_spec = fixture.get("asset_spec") if isinstance(fixture, Mapping) else None
    binding = (
        asset_spec.get("identity_binding")
        if isinstance(asset_spec, Mapping)
        else None
    )
    if recipe.scenario_id != "OBJ22-F-CREATE-02":
        if binding is not None:
            raise ObjectBusinessPlanError(
                "compound object merge identity binding differs from the reviewed profile"
            )
        return None
    if binding is None and recipe.version != "2021.1":
        return None
    if (
        getattr(scenario, "id", None) != recipe.scenario_id
        or getattr(scenario, "api", None) != recipe.api
        or recipe.version not in tuple(getattr(scenario, "versions", ()))
        or (
            binding is None
            and recipe.version
            not in OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS[
                recipe.scenario_id
            ]
        )
        or (
            binding is not None
            and (
                not isinstance(binding, Mapping)
                or dict(binding)
                != {
                    "contract": "waapi-skill.compound-object-identity/v1",
                    "fixture_key": "robot",
                }
            )
        )
        or not isinstance(recipe.request, OperationRequestSpec)
    ):
        raise ObjectBusinessPlanError(
            "compound object merge identity binding differs from the reviewed profile"
        )
    roots = tuple(
        item
        for item in recipe.fixture.objects
        if item.key == "robot"
    )
    if len(roots) != 1:
        raise ObjectBusinessPlanError(
            "compound object merge must identify one existing request root"
        )
    root = roots[0]
    return build_schema_query_transaction_protocol(
        (recipe.request.as_dict(version=recipe.version),),
        query_step=query_object_step(
            "object.merge-root",
            (
                "query-object",
                "--path",
                root.path,
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "type",
                "--return-field",
                "path",
            ),
        ),
    )


def _validate_protocol(
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
    *,
    scenario: Any,
    profile_unit_id: str | None,
) -> None:
    if not isinstance(protocol, V3GatewayProtocol):
        raise ObjectBusinessPlanError("object protocol must be V3GatewayProtocol")
    request = recipe.request
    if isinstance(request, OperationRequestSpec):
        metadata_protocol = _compound_metadata_protocol(
            scenario,
            recipe,
            protocol,
            profile_unit_id=profile_unit_id,
        )
        if metadata_protocol is not None:
            expected_protocols = (metadata_protocol,)
        else:
            base = build_transaction_protocol(
                [request.as_dict(version=recipe.version)]
            )
            merge_protocol = build_object_merge_query_protocol(
                scenario,
                recipe,
            )
            expected_protocols = (
                (merge_protocol,)
                if merge_protocol is not None
                else (
                    base,
                    *(
                        build_modification_policy_protocol(base, policy=policy)
                        for policy in (
                            "read_only",
                            "ask_before_changes",
                            "allow_changes",
                        )
                    ),
                )
            )
    elif isinstance(request, QueryObjectRequestSpec):
        expected_protocols = (
            build_direct_protocol(
                [
                    query_object_step("query-object", request.argv[3:]),
                ]
            ),
        )
    else:  # pragma: no cover - recipe union is closed
        raise ObjectBusinessPlanError("object recipe request type is unsupported")
    if serialize_protocol(protocol) not in tuple(
        serialize_protocol(expected) for expected in expected_protocols
    ):
        raise ObjectBusinessPlanError(
            "object protocol differs from the exact reviewed request"
        )


def _validate_before_snapshot(
    recipe: ObjectHeavyRecipe,
    before: ObjectRuntimeSnapshot,
) -> dict[str, Any]:
    if not isinstance(before, ObjectRuntimeSnapshot):
        raise ObjectBusinessPlanError("object before must be ObjectRuntimeSnapshot")
    value = _json_value(asdict(before))
    return _validate_archived_before(recipe, value)


def _validate_archived_before(
    recipe: ObjectHeavyRecipe,
    value: Any,
) -> dict[str, Any]:
    base_keys = {
        "objects",
        "absent_paths",
        "sibling_prefix_rows",
        "digest",
    }
    value_keys = frozenset(value) if isinstance(value, Mapping) else frozenset()
    if not isinstance(value, Mapping) or value_keys not in {
        frozenset(base_keys),
        frozenset((*base_keys, "override_output_rows")),
    }:
        raise ObjectBusinessPlanError("object before snapshot schema is not closed")
    has_override_rows = "override_output_rows" in value
    objects = value.get("objects")
    absent = value.get("absent_paths")
    prefixes = value.get("sibling_prefix_rows")
    if (
        not isinstance(objects, list)
        or not isinstance(absent, list)
        or not isinstance(prefixes, list)
    ):
        raise ObjectBusinessPlanError("object before snapshot arrays are invalid")
    expected_rows = {item.key: item for item in recipe.fixture.objects}
    observed: dict[str, Mapping[str, Any]] = {}
    object_keys = {
        "key",
        "id",
        "name",
        "type",
        "path",
        "parent_id",
        "notes",
        "properties",
        "references",
        "source_language",
        "is_included",
        "children_count",
        "active_source_id",
        "active_source_name",
        "active_source_path",
    }
    for row in objects:
        if not isinstance(row, Mapping) or set(row) != object_keys:
            raise ObjectBusinessPlanError("object before row schema is not closed")
        key = row.get("key")
        if not isinstance(key, str) or key in observed or key not in expected_rows:
            raise ObjectBusinessPlanError("object before row key is invalid")
        if not _GUID_RE.fullmatch(str(row.get("id") or "")):
            raise ObjectBusinessPlanError("object before row GUID is invalid")
        expected = expected_rows[key]
        if row.get("path") != expected.path or row.get("type") != expected.object_type:
            raise ObjectBusinessPlanError(
                "object before row path/type differs from recipe: "
                f"key={key!r}, observed_path={row.get('path')!r}, "
                f"expected_path={expected.path!r}, observed_type={row.get('type')!r}, "
                f"expected_type={expected.object_type!r}"
            )
        if row.get("name") != expected.name:
            raise ObjectBusinessPlanError("object before row name differs from recipe")
        if not isinstance(row.get("children_count"), int) or row["children_count"] < 0:
            raise ObjectBusinessPlanError("object before children_count is invalid")
        if not isinstance(row.get("properties"), list) or not isinstance(
            row.get("references"), list
        ):
            raise ObjectBusinessPlanError("object before properties/references are invalid")
        observed[key] = row
    if set(observed) != set(expected_rows):
        raise ObjectBusinessPlanError("object before snapshot omits fixture keys")
    override_output_rows: list[list[Any]] | None = None
    if has_override_rows:
        raw_override_rows = value.get("override_output_rows")
        if not isinstance(raw_override_rows, list):
            raise ObjectBusinessPlanError(
                "object before OverrideOutput rows are invalid"
            )
        override_output_rows = []
        override_keys: set[str] = set()
        for row in raw_override_rows:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or not isinstance(row[0], str)
                or row[0] in override_keys
                or row[0] not in observed
                or (row[1] is not None and type(row[1]) is not bool)
            ):
                raise ObjectBusinessPlanError(
                    "object before OverrideOutput row is invalid"
                )
            override_keys.add(row[0])
            override_output_rows.append([row[0], row[1]])
        if override_keys != set(observed):
            raise ObjectBusinessPlanError(
                "object before OverrideOutput keys differ from object keys"
            )
    ids_by_key = {key: str(row["id"]) for key, row in observed.items()}
    active_source_ids: set[str] = set()
    ids_by_path = {
        expected_rows[key].path: ids_by_key[key]
        for key in observed
    }
    for key, row in observed.items():
        expected = expected_rows[key]
        if expected.parent_path in ids_by_path and row.get("parent_id") != ids_by_path[
            expected.parent_path
        ]:
            raise ObjectBusinessPlanError("object before parent GUID differs from fixture")
        if expected.notes is not None and row.get("notes") != expected.notes:
            raise ObjectBusinessPlanError("object before notes differ from fixture")
        if row.get("source_language") != expected.source_language:
            raise ObjectBusinessPlanError("object before source language differs")
        _validate_active_source_fields(
            row,
            label=f"object before {key}",
            require=expected.source_language is not None,
        )
        active_source_id = row.get("active_source_id")
        if expected.source_language is not None:
            if (
                row.get("active_source_name") != key
                or row.get("active_source_path") != f"{expected.path}\\{key}"
            ):
                raise ObjectBusinessPlanError(
                    "object before activeSource name/path differs from fixture input"
                )
            if active_source_id in active_source_ids:
                raise ObjectBusinessPlanError(
                    "object before activeSource GUIDs are duplicated"
                )
            active_source_ids.add(str(active_source_id))
        elif any(
            row.get(field) is not None
            for field in (
                "active_source_id",
                "active_source_name",
                "active_source_path",
            )
        ):
            raise ObjectBusinessPlanError(
                "object before has an activeSource outside a language-bound Sound"
            )
        if (
            expected.is_included is not None
            and row.get("is_included") != expected.is_included
        ):
            raise ObjectBusinessPlanError("object before inclusion differs")
        observed_properties: dict[str, Any] = {}
        for property_row in row["properties"]:
            if not isinstance(property_row, Mapping) or set(property_row) != {
                "name",
                "value",
            } or not isinstance(property_row.get("name"), str):
                raise ObjectBusinessPlanError("object before property row is invalid")
            observed_properties[property_row["name"]] = property_row.get("value")
        for expected_property in expected.properties:
            if observed_properties.get(expected_property.name) != expected_property.value:
                raise ObjectBusinessPlanError("object before property differs from fixture")
        observed_references: dict[str, str] = {}
        for reference_row in row["references"]:
            if not isinstance(reference_row, Mapping) or set(reference_row) != {
                "name",
                "target_id",
            } or not isinstance(reference_row.get("name"), str):
                raise ObjectBusinessPlanError("object before reference row is invalid")
            target_id = reference_row.get("target_id")
            if not _GUID_RE.fullmatch(str(target_id or "")):
                raise ObjectBusinessPlanError("object before reference GUID is invalid")
            observed_references[reference_row["name"]] = str(target_id)
        for expected_reference in expected.references:
            if (
                observed_references.get(expected_reference.name)
                != ids_by_key[expected_reference.target_key]
            ):
                raise ObjectBusinessPlanError("object before reference differs from fixture")
    if active_source_ids & set(ids_by_key.values()):
        raise ObjectBusinessPlanError(
            "object before activeSource GUID overlaps a fixture object GUID"
        )
    if absent != list(recipe.fixture.absent_paths):
        raise ObjectBusinessPlanError("object before absence proof differs from recipe")
    if len(prefixes) != len(recipe.fixture.absent_sibling_prefixes):
        raise ObjectBusinessPlanError("object sibling-prefix proof count differs")
    expected_prefix_labels = {
        f"{parent}|{prefix}" for parent, prefix in recipe.fixture.absent_sibling_prefixes
    }
    labels: set[str] = set()
    for row in prefixes:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or row[0] in labels
            or row[1] != []
        ):
            raise ObjectBusinessPlanError("object sibling-prefix row is invalid")
        labels.add(row[0])
    if labels != expected_prefix_labels:
        raise ObjectBusinessPlanError("object sibling-prefix labels differ from recipe")
    digest = _snapshot_digest(
        objects,
        absent,
        prefixes,
        override_output_rows=override_output_rows,
    )
    if value.get("digest") != digest:
        raise ObjectBusinessPlanError("object before snapshot digest cannot be recomputed")
    result = {
        "objects": _json_value(objects),
        "absent_paths": _json_value(absent),
        "sibling_prefix_rows": _json_value(prefixes),
        "digest": digest,
    }
    if override_output_rows is not None:
        result["override_output_rows"] = _json_value(override_output_rows)
    return result


def _validate_input_manifest(
    value: Any,
    *,
    required_keys: set[str],
    verify_files: bool,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ObjectBusinessPlanError("object input manifest must be an array")
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    paths: set[ArchiveAbsolutePath] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {
            "key",
            "path",
            "size",
            "sha256",
        }:
            raise ObjectBusinessPlanError("object input manifest row is not closed")
        key = row.get("key")
        path_text = row.get("path")
        size = row.get("size")
        digest = row.get("sha256")
        try:
            path_identity = parse_archive_absolute_path(path_text)
        except (ArchiveRelativePathError, TypeError):
            path_identity = None
        if (
            not isinstance(key, str)
            or not key
            or key in keys
            or not isinstance(path_text, str)
            or path_identity is None
            or path_identity in paths
            or type(size) is not int
            or not 0 < size <= _MAX_OBJECT_INPUT_FILE_BYTES
            or not _is_sha256(digest)
        ):
            raise ObjectBusinessPlanError("object input manifest values are invalid")
        keys.add(key)
        paths.add(path_identity)
        normalized = {
            "key": key,
            "path": path_text,
            "size": size,
            "sha256": digest,
        }
        if verify_files:
            path = Path(path_text)
            if not path.is_absolute():
                raise ObjectBusinessPlanError(
                    "object input manifest path does not belong to the current host"
                )
            try:
                snapshot = read_bounded_exclusive_regular_file(
                    path,
                    max_bytes=size,
                    require_private_posix_mode=False,
                )
            except CodexFileSecurityError as exc:
                raise ObjectBusinessPlanError(
                    "object input manifest differs from the current fixture file"
                ) from exc
            if (
                snapshot.metadata.st_size != size
                or hashlib.sha256(snapshot.raw).hexdigest() != digest
            ):
                raise ObjectBusinessPlanError(
                    "object input manifest differs from the current fixture file"
                )
        rows.append(normalized)
    if keys != required_keys:
        raise ObjectBusinessPlanError(
            "object input manifest keys differ from language-bound Sound fixtures"
        )
    return tuple(sorted(rows, key=lambda item: item["key"]))


def _static_expectation(
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
    *,
    profile_unit_id: str | None,
) -> dict[str, Any]:
    recipe_value = _json_value(recipe)
    request_value = _request_value(recipe)
    result = {
        "family_schema_version": OBJECT_BUSINESS_PLAN_SCHEMA,
        "family": "object",
        "api": recipe.api,
        "version": recipe.version,
        "scenario_id": recipe.scenario_id,
        "recipe_digest": recipe.digest,
        "recipe": recipe_value,
        "request": request_value,
        "request_sha256": _sha256_json(request_value),
        "protocol_projection_sha256": _sha256_json(serialize_protocol(protocol)),
    }
    if profile_unit_id is not None:
        result["profile_unit_id"] = profile_unit_id
    return result


def _request_value(recipe: ObjectHeavyRecipe) -> dict[str, Any]:
    request = recipe.request
    if isinstance(request, OperationRequestSpec):
        return {
            "kind": "operation_request",
            "value": _json_value(request.as_dict(version=recipe.version)),
        }
    if isinstance(request, QueryObjectRequestSpec):
        return {"kind": "query_object", "value": _json_value(request)}
    raise ObjectBusinessPlanError("object recipe request type is unsupported")


def _live_binding(
    before_value: Mapping[str, Any],
    file_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "family_schema_version": OBJECT_BUSINESS_PLAN_SCHEMA,
        "before_snapshot": _json_value(before_value),
        "before_snapshot_sha256": before_value["digest"],
        "key_bindings": _json_value(before_value["objects"]),
        "input_files": _json_value(file_rows),
    }


def _delta_rules(
    recipe: ObjectHeavyRecipe,
    before_value: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    oracle = recipe.oracle
    if recipe.api == "ak.wwise.core.object.get":
        request = recipe.request
        if not isinstance(request, QueryObjectRequestSpec):
            raise ObjectBusinessPlanError("object.get recipe lacks query request")
        bound_rules = tuple(
            rule
            for rule in oracle.rules
            if rule.kind == "bound_reached_equal"
        )
        count_rules = tuple(
            rule
            for rule in oracle.rules
            if rule.kind == "answer_counts_equal"
        )
        if len(bound_rules) > 1 or len(count_rules) > 1:
            raise ObjectBusinessPlanError("object.get query oracle rules are ambiguous")
        return (
            {
                "kind": "object_query_read_only_v1",
                "before_snapshot_sha256": before_value["digest"],
                "exact_expected_keys": list(request.exact_expected_keys),
                "bounded_superset_keys": list(request.bounded_superset_keys),
                "expected_order_keys": list(oracle.expected_order_keys),
                "excluded_keys": list(oracle.excluded_keys),
                "final_filter": _json_value(request.final_filter),
                "primary_row_policy": request.primary_row_policy,
                "derived_row_policy": request.derived_row_policy,
                "final_answer_policy": request.final_answer_policy,
                "expected_bound": (
                    dict(bound_rules[0].expected) if bound_rules else None
                ),
                "expected_answer_counts": (
                    dict(count_rules[0].expected) if count_rules else None
                ),
            },
        )
    return (
        {
            "kind": "object_expected_objects_v1",
            "expected_objects": _json_value(oracle.expected_objects),
        },
        {
            "kind": "object_identity_delta_v1",
            "preserved_keys": list(oracle.preserved_keys),
            "new_keys": list(oracle.new_keys),
            "removed_keys": list(oracle.removed_keys),
            "protected_snapshot_keys": list(oracle.protected_snapshot_keys),
            "before_snapshot_sha256": before_value["digest"],
        },
        {
            "kind": "object_oracle_rules_v1",
            "rules": _json_value(oracle.rules),
        },
    )


def _step_partition(
    recipe: ObjectHeavyRecipe,
    protocol: V3GatewayProtocol,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if isinstance(recipe.request, QueryObjectRequestSpec):
        return ("query-object",), ()
    execute_steps = tuple(
        step.name for step in protocol.steps if step.subcommand == "execute"
    )
    verification_steps = tuple(
        step.name for step in protocol.steps if step.subcommand != "execute"
    )
    return execute_steps, verification_steps


def _assertion_ids(recipe: ObjectHeavyRecipe) -> tuple[str, ...]:
    base = (
        "object.request.exact",
        "object.fixture.materialized",
        "object.live.before_snapshot",
        "object.delta.closed",
    )
    return (*base, "object.query.answer_exact") if recipe.api.endswith(".get") else base


def _build_sections(
    *,
    recipe: ObjectHeavyRecipe,
    static: Mapping[str, Any],
    live: Mapping[str, Any],
    rules: Sequence[Mapping[str, Any]],
    primary_steps: Sequence[str],
    verification_steps: Sequence[str],
) -> ObjectBusinessPlanSections:
    fixture_value = {"static": _json_value(static), "live": _json_value(live)}
    return ObjectBusinessPlanSections(
        fixture_spec=MappingProxyType(
            {"kind": OBJECT_FIXTURE_KIND, "sha256": _sha256_json(fixture_value)}
        ),
        payload_bindings=MappingProxyType(
            {
                "primary_steps": list(primary_steps),
                "verification_steps": list(verification_steps),
            }
        ),
        assertion_ids=_assertion_ids(recipe),
        static_expectation=MappingProxyType(_json_value(static)),
        live_binding=MappingProxyType(_json_value(live)),
        delta_rules=tuple(MappingProxyType(_json_value(item)) for item in rules),
    )


def _snapshot_digest(
    objects: Any,
    absent: Any,
    prefixes: Any,
    *,
    override_output_rows: Any | None = None,
) -> str:
    payload = {
        "objects": objects,
        "absent_paths": absent,
        "sibling_prefix_rows": prefixes,
    }
    if override_output_rows is not None:
        payload["override_output_rows"] = override_output_rows
    return _sha256_json(payload)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _json_value(value: Any) -> Any:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_json_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    raise ObjectBusinessPlanError(
        f"object plan value is not JSON serializable: {type(value).__name__}"
    )


__all__ = [
    "OBJECT_BUSINESS_PLAN_SCHEMA",
    "OBJECT_FIXTURE_KIND",
    "ObjectBusinessPlanError",
    "ObjectBusinessPlanSections",
    "build_object_merge_query_protocol",
    "compile_object_business_plan",
    "parse_object_business_plan_sections",
    "seal_object_input_file_manifest",
    "validate_archived_object_business_plan",
    "validate_object_archived_verification",
    "validate_object_business_plan",
]

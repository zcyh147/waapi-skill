"""Trusted runtime for the committed-baseline Weapons audit workflow.

The model receives only two reviewed object paths.  The runtime seals the
copied SampleProject against the version manifest, requires one bounded audit
query, one exact-ID hop per distinct returned OutputBus, and one exact-ID
readback per selected Sound.  It builds one metadata-bound ``object.set`` batch
from those revalidated GUIDs and independently reads back all selected and
protected state.

Direct WAAPI access is runner-owned and read-only.  The model can mutate only
through the ordinary immutable Gateway transaction protocol.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from tests.semantic.support.codex_campaign import canonical_json_bytes
from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_object_set_composer_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    gateway_step_prefix_matches,
    gateway_step_sequence_matches,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    BaselineManifest,
)
from tests.semantic.support.codex_integration_fixture_tree_v2 import (
    wwise_fixture_tree_sha256,
)
from tests.semantic.support.codex_integration_paths_v2 import (
    IntegrationOriginalPathError,
    localize_copied_original_path,
)


WEAPONS_WORKFLOW_ID = "weapons_query_guided_batch_cleanup"
WEAPONS_FIXTURE_ADAPTER = "weapons_audit_committed_baseline_fixture_v2"
SUPPORTED_VERSIONS = frozenset({"2022.1", "2025.1"})

OBJECT_GET_API = "ak.wwise.core.object.get"
OBJECT_SET_API = "ak.wwise.core.object.set"
_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_OBJECT_ROWS = 64
_MAX_RTPC_ROWS = 32
_AUDIT_TAKE = 32

_RTPC_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "notes",
    "@PropertyName",
    "@ControlInput",
    "@Curve",
)
_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "notes",
    "originalFilePath",
    "audioSource:language",
)
_CHILD_FIELDS = ("id", "name", "type", "path", "parent")
_SOUND_STATE_FIELDS = (
    "parent",
    "notes",
    "@Volume",
    "@Pitch",
    "@IsLoopingEnabled",
    "@UseMaxSoundPerInstance",
    "@MaxSoundPerInstance",
    "OutputBus",
    "activeSource",
    "rtpc_rows",
)
WEAPONS_CANONICAL_STATE_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "audit_root": ("parent", "children"),
        "audit_close": _SOUND_STATE_FIELDS,
        "audit_tail": _SOUND_STATE_FIELDS,
        "audit_mechanical": _SOUND_STATE_FIELDS,
        "audit_exception_legacy": _SOUND_STATE_FIELDS,
        "audit_exception_hot": _SOUND_STATE_FIELDS,
        "audit_compliant": _SOUND_STATE_FIELDS,
        "audit_out_of_scope": _SOUND_STATE_FIELDS,
        "audit_close_event": ("parent", "children"),
        "audit_close_action": ("parent", "ActionType", "Target"),
        "weapons_bus": ("parent", "@Volume"),
        "footsteps_bus": ("parent", "@Volume"),
        "rifle_distance_parameter": ("parent",),
    }
)

_IN_SCOPE_SOUND_ROLES = (
    "audit_close",
    "audit_tail",
    "audit_mechanical",
    "audit_exception_legacy",
    "audit_exception_hot",
    "audit_compliant",
)
_EXPECTED_CANDIDATE_ROLES = (
    "audit_close",
    "audit_tail",
    "audit_mechanical",
    "audit_exception_legacy",
    "audit_exception_hot",
)
_SELECTED_ROLES = ("audit_close", "audit_tail", "audit_mechanical")
_ACTION_EVENT_ROLE = "audit_close_event"
_ACTION_ROLE = "audit_close_action"
_PROTECTED_ROLES = (
    "audit_exception_legacy",
    "audit_exception_hot",
    "audit_compliant",
    "audit_out_of_scope",
)
_EXPECTED_ASSERTION_IDS = (
    "audit_candidates_exact",
    "excluded_scope_absent",
    "selected_ids_revalidated",
    "selected_guids_and_parents_preserved",
    "selected_corrections_exact",
    "single_object_set_batch",
    "event_action_links_unchanged",
    "rtpc_and_audio_sources_unchanged",
    "exceptions_and_controls_unchanged",
    "source_project_unchanged",
)
_AUDIT_RETURN_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "OutputBus",
    "@Volume",
    "notes",
)
_IDENTITY_RETURN_FIELDS = ("id", "name", "type", "path")
_OUTPUT_BUS_STEP_PREFIX = "relationship.output_bus."
_EXPECTED_AUDIT_VIOLATIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "audit_close": ("name_prefix", "output_bus_path", "volume", "notes"),
        "audit_tail": ("volume",),
        "audit_mechanical": ("output_bus_path", "notes"),
        "audit_exception_legacy": (
            "name_prefix",
            "output_bus_path",
            "notes",
        ),
        "audit_exception_hot": ("volume",),
        "audit_compliant": (),
    }
)
class WeaponsIntegrationRuntimeError(RuntimeError):
    """The Weapons committed fixture, protocol, or oracle failed closed."""


DirectWaapiCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


class WeaponsRuntimePaths(Protocol):
    scenario_root: Path
    asset_root: Path
    io_root: Path
    sandbox: Any


@dataclass(frozen=True, slots=True)
class WeaponsFileProof:
    path: str
    relative_path: str | None
    size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "relative_path": self.relative_path,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class WeaponsObjectState:
    role: str
    object_id: str
    name: str
    object_type: str
    path: str
    state: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "id": self.object_id,
            "name": self.name,
            "type": self.object_type,
            "path": self.path,
            "state": _plain(self.state),
        }


@dataclass(frozen=True, slots=True)
class WeaponsMediaState:
    role: str
    sound_id: str
    active_source_id: str
    source_parent_id: str
    language: str
    original: WeaponsFileProof

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "sound_id": self.sound_id,
            "active_source_id": self.active_source_id,
            "source_parent_id": self.source_parent_id,
            "language": self.language,
            "original": self.original.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class WeaponsSourceProjectProof:
    project_sha256: str
    tree_sha256: str
    project_mtime_ns: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_sha256": self.project_sha256,
            "tree_sha256": self.tree_sha256,
            "project_mtime_ns": self.project_mtime_ns,
        }


@dataclass(frozen=True, slots=True)
class WeaponsSnapshot:
    workflow_id: str
    version: str
    objects: tuple[WeaponsObjectState, ...]
    media: tuple[WeaponsMediaState, ...]
    source_project: WeaponsSourceProjectProof
    digest: str

    def objects_by_role(self) -> dict[str, WeaponsObjectState]:
        return {row.role: row for row in self.objects}

    def media_by_role(self) -> dict[str, WeaponsMediaState]:
        return {row.role: row for row in self.media}

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "objects": [row.as_dict() for row in self.objects],
            "media": [row.as_dict() for row in self.media],
            "source_project": self.source_project.as_dict(),
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class WeaponsVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    assertions: Mapping[str, bool]
    before: WeaponsSnapshot
    after: WeaponsSnapshot | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "passed": self.passed,
            "failures": list(self.failures),
            "assertions": dict(self.assertions),
            "before": self.before.as_dict(),
            "after": None if self.after is None else self.after.as_dict(),
        }

    def assert_passed(self) -> None:
        if not self.passed:
            raise WeaponsIntegrationRuntimeError(
                f"{self.phase} failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class WeaponsCleanupProof:
    passed: bool
    already_clean: bool
    sandbox_untouched: bool
    source_untouched: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "already_clean": self.already_clean,
            "sandbox_untouched": self.sandbox_untouched,
            "source_untouched": self.source_untouched,
            "failures": list(self.failures),
        }

    def assert_passed(self) -> None:
        if not self.passed:
            raise WeaponsIntegrationRuntimeError(
                "Weapons runtime cleanup failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class WeaponsExpectedDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class WeaponsOracleRequirement:
    phase: str
    subject: str
    expectation: str


@dataclass(frozen=True, slots=True)
class PreparedWeaponsIntegrationRuntime:
    workflow_id: str
    version: str
    visible_values: Mapping[str, str]
    protocol: V3GatewayProtocol
    snapshot: Callable[[], WeaponsSnapshot]
    before_snapshot: WeaponsSnapshot
    verify_turn: Callable[[int, Any | None], WeaponsVerification]
    verify_final: Callable[
        [Mapping[str, Any] | None, Any | None], WeaponsVerification
    ]
    cleanup: Callable[[], WeaponsCleanupProof]
    observe_payload: Callable[[ExpectedGatewayStep, Mapping[str, Any]], None]
    expected_dispatches: tuple[WeaponsExpectedDispatch, ...]
    oracle_requirements: tuple[WeaponsOracleRequirement, ...]
    operation_request: Mapping[str, Any]
    prompt_sources: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _RuntimePaths:
    scenario_root: Path
    asset_root: Path
    io_root: Path
    sandbox_project: Path
    sandbox_root: Path
    source_project: Path
    source_root: Path


def prepare_weapons_integration_runtime(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    runtime: WeaponsRuntimePaths,
    baseline_manifest: BaselineManifest,
    direct_call: DirectWaapiCall,
) -> PreparedWeaponsIntegrationRuntime:
    """Seal one copied baseline and build the three-turn Weapons runtime."""

    _validate_reviewed_inputs(
        workflow,
        scenario,
        version=version,
        baseline_manifest=baseline_manifest,
        direct_call=direct_call,
    )
    paths = _validated_runtime_paths(runtime)
    backend = _ClosedWeaponsBackend(direct_call)
    session = _WeaponsSession(
        workflow=workflow,
        version=version,
        runtime_paths=paths,
        baseline_manifest=baseline_manifest,
        backend=backend,
    )
    try:
        before, visible_values, request = session.prepare()
        audit_step = _audit_query_step(visible_values["weapons_audit_root_path"])
        output_bus_steps = _output_bus_readback_steps(before)
        output_bus_states = _distinct_output_bus_states(before)
        reference_identity_sources = {
            state.path: step.name
            for state, step in zip(
                output_bus_states,
                output_bus_steps,
                strict=True,
            )
        }
        transaction_steps = build_object_set_composer_transaction_steps(
            request,
            label="tx01",
            reference_identity_sources=reference_identity_sources,
        )
        identity_steps = tuple(
            _identity_readback_step(role, before.objects_by_role()[role])
            for role in _SELECTED_ROLES
        )
        read_prefix = 1 + len(output_bus_steps)
        transaction_prefix = read_prefix + len(identity_steps)
        protocol = V3GatewayProtocol(
            (audit_step, *output_bus_steps, *identity_steps, *transaction_steps),
            (
                read_prefix,
                transaction_prefix
                + next(
                    index
                    for index, step in enumerate(transaction_steps, start=1)
                    if step.name == "tx01.preview"
                ),
                len(transaction_steps) + transaction_prefix,
            ),
            commutative_read_only_step_groups=(
                tuple(step.name for step in output_bus_steps),
            ),
        )
        session.bind_protocol(protocol)
    except BaseException:
        session.cleanup_failed_prepare()
        raise
    return PreparedWeaponsIntegrationRuntime(
        workflow_id=WEAPONS_WORKFLOW_ID,
        version=version,
        visible_values=MappingProxyType(dict(visible_values)),
        protocol=protocol,
        snapshot=session.snapshot,
        before_snapshot=before,
        verify_turn=session.verify_turn,
        verify_final=session.verify_final,
        cleanup=session.cleanup,
        observe_payload=session.observe_payload,
        expected_dispatches=(
            WeaponsExpectedDispatch(
                OBJECT_SET_API,
                1,
                "apply exactly the three reviewed Sound corrections in one batch",
            ),
        ),
        oracle_requirements=_oracle_requirements(),
        operation_request=_freeze_mapping(request),
        prompt_sources=MappingProxyType(
            {"baseline_manifest_digest": baseline_manifest.digest}
        ),
    )


class _ClosedWeaponsBackend:
    """Bounded runner-only object and metadata reads."""

    def __init__(self, call: DirectWaapiCall) -> None:
        if not callable(call):
            raise TypeError("direct_call must be callable")
        self.__call = call

    def read_path(
        self, path: str, *, fields: Sequence[str]
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"from": {"path": [_wwise_path(path, "object path")]}},
            fields,
            "object.get path",
        )

    def read_id(
        self, object_id: str, *, fields: Sequence[str]
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"from": {"id": [_guid(object_id, "object id")]}},
            fields,
            "object.get id",
        )

    def read_children(
        self, object_id: str
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {
                "from": {"id": [_guid(object_id, "parent id")]},
                "transform": [{"select": ["children"]}],
            },
            _CHILD_FIELDS,
            "object.get children",
        )

    def read_rtpcs(self, object_id: str) -> tuple[Mapping[str, Any], ...]:
        owner = _one_row(
            self.read_id(object_id, fields=("id", "@RTPC")),
            "RTPC owner",
        )
        raw_refs = owner.get("@RTPC")
        if raw_refs in (None, []):
            return ()
        if not isinstance(raw_refs, list) or len(raw_refs) > _MAX_RTPC_ROWS:
            raise WeaponsIntegrationRuntimeError("RTPC reference list is malformed")
        ids = tuple(_identity(row, "RTPC reference") for row in raw_refs)
        result = self.__call(
            OBJECT_GET_API,
            {"from": {"id": list(ids)}},
            {"return": list(_RTPC_FIELDS)},
        )
        rows = _bounded_rows(result, "RTPC detail", _MAX_RTPC_ROWS)
        by_id: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            object_id_value = _guid(row.get("id"), "RTPC id")
            key = object_id_value.casefold()
            if key in by_id:
                raise WeaponsIntegrationRuntimeError("RTPC detail repeats an id")
            by_id[key] = MappingProxyType(_normalize_rtpc_row(row))
        if set(by_id) != {value.casefold() for value in ids}:
            raise WeaponsIntegrationRuntimeError(
                "RTPC detail differs from the owner reference list"
            )
        return tuple(by_id[value.casefold()] for value in ids)

    def _read(
        self,
        args: Mapping[str, Any],
        fields: Sequence[str],
        label: str,
    ) -> tuple[Mapping[str, Any], ...]:
        result = self.__call(
            OBJECT_GET_API,
            dict(args),
            {"return": list(_return_fields(fields))},
        )
        rows = _bounded_rows(result, label, _MAX_OBJECT_ROWS)
        return tuple(MappingProxyType(dict(row)) for row in rows)


class _WeaponsSession:
    def __init__(
        self,
        *,
        workflow: Any,
        version: str,
        runtime_paths: _RuntimePaths,
        baseline_manifest: BaselineManifest,
        backend: _ClosedWeaponsBackend,
    ) -> None:
        self.workflow = workflow
        self.version = version
        self.paths = runtime_paths
        self.manifest = baseline_manifest
        self.backend = backend
        self.specs = {str(row.role): row for row in workflow.fixture.object_graph}
        self.manifest_objects = _weapons_manifest_objects(
            baseline_manifest, self.specs
        )
        self.manifest_media = _weapons_manifest_media(
            baseline_manifest, self.specs
        )
        self.before: WeaponsSnapshot | None = None
        self.protocol: V3GatewayProtocol | None = None
        self.observed_steps: list[str] = []
        self.audit_rows_by_role: Mapping[str, Mapping[str, Any]] | None = None
        self.audit_output_bus_ids: tuple[str, ...] | None = None
        self.output_bus_paths: dict[str, str] = {}
        self.audit_violation_rules: Mapping[str, tuple[str, ...]] | None = None
        self.audit_candidate_ids: frozenset[str] | None = None
        self.audit_exclusions_valid = False
        self.identity_readback_ids: dict[str, str] = {}
        self.selected_revalidated = False
        self._cleaned = False
        self._finalized = False

    def prepare(
        self,
    ) -> tuple[
        WeaponsSnapshot,
        Mapping[str, str],
        Mapping[str, Any],
    ]:
        if self.before is not None or self._cleaned:
            raise WeaponsIntegrationRuntimeError("Weapons runtime is single-use")
        before = self._capture_snapshot(validate_manifest=True)
        self._validate_baseline(before)
        visible = self._visible_values()
        request = self._operation_request(before, visible)
        self.before = before
        return before, visible, request

    def bind_protocol(self, protocol: V3GatewayProtocol) -> None:
        if self.protocol is not None or self.before is None:
            raise WeaponsIntegrationRuntimeError(
                "Weapons protocol binding is late or duplicated"
            )
        output_bus_steps = _output_bus_readback_steps(self.before)
        output_bus_names = tuple(step.name for step in output_bus_steps)
        names = tuple(step.name for step in protocol.steps)
        transaction_names = names[6:]
        if (
            names[:6]
            != (
                "audit.scope",
                *output_bus_names,
                "identity.audit_close",
                "identity.audit_tail",
                "identity.audit_mechanical",
            )
            or transaction_names[:2]
            != ("tx01.operation-schema", "tx01.draft-start")
            or tuple(
                step.subcommand for step in protocol.steps[6:]
            ).count("draft-apply")
            != 1
            or transaction_names[-6:]
            != (
                "tx01.check",
                "tx01.preview",
                "tx01.transaction-show",
                "tx01.confirm",
                "tx01.execute",
                "tx01.verify",
            )
            or tuple(protocol.steps[1 : 1 + len(output_bus_steps)])
            != output_bus_steps
            or protocol.turn_prefix_counts != (3, 11, 15)
            or protocol.commutative_read_only_step_groups
            != (output_bus_names,)
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons protocol is not the reviewed audit, distinct OutputBus "
                "hops, exact-ID readbacks, and one transaction"
            )
        self.protocol = protocol

    def snapshot(self) -> WeaponsSnapshot:
        self._require_active()
        return self._capture_snapshot(validate_manifest=False)

    def verify_turn(
        self, turn_index: int, _result: Any | None = None
    ) -> WeaponsVerification:
        if type(turn_index) is not int or turn_index not in {1, 2}:
            raise WeaponsIntegrationRuntimeError(
                "Weapons intermediate verification supports turns 1 and 2"
            )
        before = self._require_active()
        try:
            after = self._capture_snapshot(validate_manifest=False)
        except WeaponsIntegrationRuntimeError as exc:
            return WeaponsVerification(
                f"turn_{turn_index}_no_change",
                False,
                (str(exc),),
                MappingProxyType({"snapshot_unchanged": False}),
                before,
                None,
            )
        unchanged = after == before
        audit_ok = (
            self.audit_rows_by_role is not None
            and self.audit_output_bus_ids is not None
            and set(self.output_bus_paths) == set(self.audit_output_bus_ids)
            and self.audit_violation_rules == _EXPECTED_AUDIT_VIOLATIONS
            and self.audit_candidate_ids
            == frozenset(
                before.objects_by_role()[role].object_id.casefold()
                for role in _EXPECTED_CANDIDATE_ROLES
            )
            and self.audit_exclusions_valid
        )
        checks = {
            "snapshot_unchanged": unchanged,
            "audit_query_valid": audit_ok,
        }
        if turn_index == 2:
            checks["selected_ids_revalidated"] = self.selected_revalidated
        failures = tuple(name for name, passed in checks.items() if not passed)
        return WeaponsVerification(
            f"turn_{turn_index}_no_change",
            not failures,
            failures,
            MappingProxyType(checks),
            before,
            after,
        )

    def observe_payload(
        self, step: ExpectedGatewayStep, payload: Mapping[str, Any]
    ) -> None:
        self._require_active()
        protocol = self.protocol
        if protocol is None:
            raise WeaponsIntegrationRuntimeError(
                "Weapons observer ran before protocol binding"
            )
        if not isinstance(step, ExpectedGatewayStep) or not isinstance(
            payload, Mapping
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons observer received an invalid step or payload"
            )
        expected_names = tuple(row.name for row in protocol.steps)
        observed_prefix = (*self.observed_steps, step.name)
        if not gateway_step_prefix_matches(
            expected_names,
            observed_prefix,
            protocol.commutative_read_only_step_groups,
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons gateway steps were duplicated or observed out of order"
            )
        command = payload.get("command")
        if command is not None and command != step.subcommand:
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} returned a different gateway command"
            )
        if payload.get("ok") is not True:
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} did not return a successful gateway payload"
            )
        if step.name == "audit.scope":
            self._observe_audit_payload(payload)
        elif step.name.startswith(_OUTPUT_BUS_STEP_PREFIX):
            self._observe_output_bus_payload(step, payload)
        elif step.name.startswith("identity."):
            self._observe_identity_payload(step, payload)
        elif step.name == "tx01.preview":
            before = self._require_active().objects_by_role()
            selected = {
                before[role].object_id.casefold() for role in _SELECTED_ROLES
            }
            readback = {
                object_id.casefold()
                for object_id in self.identity_readback_ids.values()
            }
            self.selected_revalidated = (
                self.audit_candidate_ids is not None
                and selected <= self.audit_candidate_ids
                and set(self.identity_readback_ids) == set(_SELECTED_ROLES)
                and readback == selected
                and _request_object_ids(self._operation_request(
                    self._require_active(), self._visible_values()
                ))
                == readback
            )
        self.observed_steps.append(step.name)
        if (
            len(self.observed_steps) == protocol.turn_prefix_counts[0]
            and set(self.output_bus_paths) == set(self.audit_output_bus_ids or ())
        ):
            self.verify_turn(1).assert_passed()
        elif step.name == "tx01.preview":
            self.verify_turn(2).assert_passed()

    def verify_final(
        self,
        _gateway_payload: Mapping[str, Any] | None = None,
        _result: Any | None = None,
    ) -> WeaponsVerification:
        if self._finalized:
            raise WeaponsIntegrationRuntimeError(
                "Weapons final verification is single-use"
            )
        before = self._require_active()
        try:
            after = self._capture_snapshot(validate_manifest=False)
        except WeaponsIntegrationRuntimeError as exc:
            self._finalized = True
            return WeaponsVerification(
                "after_batch",
                False,
                (str(exc),),
                MappingProxyType(
                    {name: False for name in _EXPECTED_ASSERTION_IDS}
                ),
                before,
                None,
            )
        assertions, details = self._final_assertions(before, after)
        failures = tuple(
            f"{name}: {details[name]}"
            for name in _EXPECTED_ASSERTION_IDS
            if not assertions[name]
        )
        self._finalized = True
        return WeaponsVerification(
            "after_batch",
            not failures,
            failures,
            MappingProxyType(assertions),
            before,
            after,
        )

    def cleanup(self) -> WeaponsCleanupProof:
        if self._cleaned:
            return WeaponsCleanupProof(True, True, True, True, ())
        self._require_active()
        sandbox_before = _file_identity(self.paths.sandbox_project)
        source_before = _source_project_proof(
            self.paths.source_project, self.paths.source_root
        )
        # This workflow owns no external inputs.  The shared lifecycle removes
        # the copied project after the oracle has sealed it.
        sandbox_after = _file_identity(self.paths.sandbox_project)
        source_after = _source_project_proof(
            self.paths.source_project, self.paths.source_root
        )
        sandbox_ok = sandbox_before == sandbox_after
        source_ok = source_before == source_after
        failures = tuple(
            message
            for passed, message in (
                (sandbox_ok, "cleanup changed the copied .wproj file"),
                (source_ok, "cleanup changed the source project"),
            )
            if not passed
        )
        self._cleaned = not failures
        return WeaponsCleanupProof(
            self._cleaned, False, sandbox_ok, source_ok, failures
        )

    def cleanup_failed_prepare(self) -> None:
        # No scenario-owned external files are created by this adapter.
        self._cleaned = True

    def _visible_values(self) -> Mapping[str, str]:
        bindings = self.workflow.fixture.visible_bindings
        values = {
            "weapons_audit_root_path": _binding_object_path(
                bindings["weapons_audit_root_path"], self.version
            ),
            "weapons_bus_path": _binding_object_path(
                bindings["weapons_bus_path"], self.version
            ),
        }
        return MappingProxyType(values)

    def _operation_request(
        self,
        snapshot: WeaponsSnapshot,
        visible: Mapping[str, str],
    ) -> Mapping[str, Any]:
        objects = snapshot.objects_by_role()
        return MappingProxyType(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": self.version,
                "operation": "object.set",
                "arguments": {
                    "objects": [
                        {
                            "object": {
                                "kind": "id",
                                "value": objects["audit_close"].object_id,
                            },
                            "name": "RFL_Close",
                            "notes": "release-ready | close",
                            "references": [
                                {
                                    "name": "OutputBus",
                                    "target": {
                                        "kind": "path",
                                        "value": visible["weapons_bus_path"],
                                    },
                                }
                            ],
                        },
                        {
                            "object": {
                                "kind": "id",
                                "value": objects["audit_tail"].object_id,
                            },
                            "properties": [{"name": "Volume", "value": -3.0}],
                        },
                        {
                            "object": {
                                "kind": "id",
                                "value": objects["audit_mechanical"].object_id,
                            },
                            "notes": "release-ready | mechanical",
                            "references": [
                                {
                                    "name": "OutputBus",
                                    "target": {
                                        "kind": "path",
                                        "value": visible["weapons_bus_path"],
                                    },
                                }
                            ],
                        },
                    ],
                    "on_name_conflict": "fail",
                },
            }
        )

    def _capture_snapshot(self, *, validate_manifest: bool) -> WeaponsSnapshot:
        objects: list[WeaponsObjectState] = []
        media: list[WeaponsMediaState] = []
        children_by_role: dict[str, tuple[Mapping[str, str], ...]] = {}
        for role, spec in self.specs.items():
            manifest_row = self.manifest_objects.get(role)
            if manifest_row is None:
                raise WeaponsIntegrationRuntimeError(
                    f"manifest omitted Weapons role {role}"
                )
            state = manifest_row.get("state")
            expected_fields = WEAPONS_CANONICAL_STATE_FIELDS.get(role)
            if (
                not isinstance(state, Mapping)
                or expected_fields is None
                or tuple(state) != expected_fields
            ):
                raise WeaponsIntegrationRuntimeError(
                    f"manifest role {role} does not use the canonical state shape"
                )
            live_state_fields = tuple(
                field
                for field in expected_fields
                if field not in {"children", "rtpc_rows"}
            )
            fields = _return_fields(
                (
                    "id",
                    "name",
                    "type",
                    "path",
                    *live_state_fields,
                )
            )
            spec_path = spec.path_for(self.version)
            lookup_label = spec_path
            if role == _ACTION_ROLE:
                rows = self.backend.read_id(
                    str(manifest_row["id"]), fields=fields
                )
                lookup_label = f"{role} manifest id"
            elif validate_manifest:
                rows = self.backend.read_path(spec_path, fields=fields)
            else:
                rows = self.backend.read_id(
                    str(manifest_row["id"]), fields=fields
                )
                lookup_label = f"{role} manifest id"
            row = _one_row(rows, lookup_label)
            object_id = _guid(row.get("id"), f"{role} id")
            object_type = _text(row.get("type"), f"{role} type")
            path = _wwise_path(row.get("path"), f"{role} path")
            allowed_paths = {spec_path}
            if not validate_manifest and role == "audit_close":
                allowed_paths.add(
                    spec_path.rsplit("\\", 1)[0] + "\\RFL_Close"
                )
            path_is_allowed = path in allowed_paths
            if not validate_manifest and role == _ACTION_ROLE:
                # An Action's displayed leaf follows its target name.  Its
                # immutable GUID and its parent Event's live child row prove
                # identity below; do not derive or query that display path.
                path_is_allowed = True
            if not path_is_allowed or not _reviewed_type_match(
                version=self.version,
                role=role,
                live_type=object_type,
                declared_type=spec.type,
            ):
                raise WeaponsIntegrationRuntimeError(
                    f"{role} path or type differs from the reviewed workflow"
                )
            state_value: dict[str, Any] = {}
            for field in expected_fields:
                if field == "children":
                    children = self._capture_children(role, object_id)
                    children_by_role[role] = children
                    state_value[field] = [
                        {"id": child["id"]} for child in children
                    ]
                elif field == "rtpc_rows":
                    state_value[field] = [
                        _plain(value)
                        for value in self.backend.read_rtpcs(object_id)
                    ]
                else:
                    if field not in row:
                        raise WeaponsIntegrationRuntimeError(
                            f"{role} omitted manifest state field {field}"
                        )
                    state_value[field] = _normalize_state_field(
                        field, row[field]
                    )
            object_state = WeaponsObjectState(
                role,
                object_id,
                _text(row.get("name"), f"{role} name"),
                object_type,
                path,
                _freeze_mapping(state_value),
            )
            if validate_manifest:
                _validate_manifest_object_state(
                    object_state,
                    manifest_row,
                    version=self.version,
                )
            objects.append(object_state)
            if _type_token(spec.type) == "sound":
                media_state = self._capture_media(
                    object_state, enforce_parent=validate_manifest
                )
                if validate_manifest:
                    _validate_manifest_media(
                        media_state, self.manifest_media[role]
                    )
                media.append(media_state)
        self._validate_action_oracle(
            {row.role: row for row in objects},
            children_by_role.get(_ACTION_EVENT_ROLE),
        )
        source = _source_project_proof(
            self.paths.source_project, self.paths.source_root
        )
        serial = {
            "workflow_id": WEAPONS_WORKFLOW_ID,
            "version": self.version,
            "objects": [row.as_dict() for row in objects],
            "media": [row.as_dict() for row in media],
            "source_project": source.as_dict(),
        }
        return WeaponsSnapshot(
            WEAPONS_WORKFLOW_ID,
            self.version,
            tuple(objects),
            tuple(media),
            source,
            _json_sha256(serial),
        )

    def _capture_children(
        self,
        owner_role: str,
        owner_id: str,
    ) -> tuple[Mapping[str, str], ...]:
        """Capture canonical child IDs without using a return accessor.

        Wwise 2022.1 rejects ``children`` in ``options.return``.  The
        ``from.id`` plus ``transform.select children`` form is reflected and
        executable in both supported representative versions.
        """

        children: list[Mapping[str, str]] = []
        for raw in self.backend.read_children(owner_id):
            child_id = _guid(raw.get("id"), f"{owner_role} child id")
            parent_id = _identity(
                raw.get("parent"), f"{owner_role} child parent"
            )
            if parent_id.casefold() != owner_id.casefold():
                raise WeaponsIntegrationRuntimeError(
                    f"{owner_role} direct child has another parent"
                )
            children.append(
                MappingProxyType(
                    {
                        "id": child_id,
                        "name": _text(raw.get("name"), f"{owner_role} child name"),
                        "type": _text(raw.get("type"), f"{owner_role} child type"),
                        "path": _wwise_path(raw.get("path"), f"{owner_role} child path"),
                        "parent": parent_id,
                    }
                )
            )
        if len({row["id"].casefold() for row in children}) != len(children):
            raise WeaponsIntegrationRuntimeError(
                f"{owner_role} children contain duplicate GUIDs"
            )
        return tuple(children)

    def _validate_action_oracle(
        self,
        objects: Mapping[str, WeaponsObjectState],
        event_children: tuple[Mapping[str, str], ...] | None,
    ) -> None:
        """Prove the dynamic Action through its sealed GUID and parent Event."""

        event = objects.get(_ACTION_EVENT_ROLE)
        action = objects.get(_ACTION_ROLE)
        if event is None or action is None or event_children is None:
            raise WeaponsIntegrationRuntimeError(
                "Weapons Event/Action oracle is incomplete"
            )
        if len(event_children) != 1:
            raise WeaponsIntegrationRuntimeError(
                "Weapons Event must expose exactly one direct Action"
            )
        child = event_children[0]
        if (
            child["id"].casefold() != action.object_id.casefold()
            or child["parent"].casefold() != event.object_id.casefold()
            or child["name"] != action.name
            or _type_token(child["type"]) != "action"
            or child["path"] != action.path
            or _identity(action.state.get("parent"), "Action parent").casefold()
            != event.object_id.casefold()
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons Event child and sealed Action detail disagree"
            )

    def _capture_media(
        self, sound: WeaponsObjectState, *, enforce_parent: bool
    ) -> WeaponsMediaState:
        active_source = _identity(
            sound.state.get("activeSource"), f"{sound.role} activeSource"
        )
        row = _one_row(
            self.backend.read_id(active_source, fields=_SOURCE_FIELDS),
            f"{sound.role} activeSource",
        )
        source_id = _guid(row.get("id"), f"{sound.role} source id")
        if (
            source_id.casefold() != active_source.casefold()
            or _type_token(row.get("type"))
            not in {"audiofilesource", "audiosource"}
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{sound.role} activeSource identity or type drifted"
            )
        parent_id = _identity(row.get("parent"), f"{sound.role} source parent")
        if enforce_parent and parent_id.casefold() != sound.object_id.casefold():
            raise WeaponsIntegrationRuntimeError(
                f"{sound.role} activeSource has another parent"
            )
        return WeaponsMediaState(
            sound.role,
            sound.object_id,
            source_id,
            parent_id,
            _name_value(
                row.get("audioSource:language"), f"{sound.role} language"
            ),
            _copied_original_proof(
                row.get("originalFilePath"), sandbox_root=self.paths.sandbox_root
            ),
        )

    def _validate_baseline(self, snapshot: WeaponsSnapshot) -> None:
        objects = snapshot.objects_by_role()
        if set(objects) != set(WEAPONS_CANONICAL_STATE_FIELDS):
            raise WeaponsIntegrationRuntimeError(
                "Weapons baseline object coverage drifted"
            )
        root_id = objects["audit_root"].object_id.casefold()
        root_children = {
            _identity(row, "audit root child").casefold()
            for row in _list_value(
                objects["audit_root"].state.get("children"),
                "audit root children",
            )
        }
        expected_children = {
            objects[role].object_id.casefold() for role in _IN_SCOPE_SOUND_ROLES
        }
        if root_children != expected_children or any(
            _identity(objects[role].state.get("parent"), f"{role} parent")
            .casefold()
            != root_id
            for role in _IN_SCOPE_SOUND_ROLES
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit root does not contain exactly the reviewed Sounds"
            )
        candidates = self._candidate_roles(objects)
        if tuple(candidates) != _EXPECTED_CANDIDATE_ROLES:
            raise WeaponsIntegrationRuntimeError(
                "Weapons baseline audit candidate set drifted"
            )
        event = objects["audit_close_event"]
        action = objects["audit_close_action"]
        event_children = {
            _identity(row, "audit Event child").casefold()
            for row in _list_value(event.state.get("children"), "Event children")
        }
        if (
            event_children != {action.object_id.casefold()}
            or _identity(action.state.get("parent"), "Action parent").casefold()
            != event.object_id.casefold()
            or _integer(action.state.get("ActionType"), "ActionType") != 1
            or _identity(action.state.get("Target"), "Action Target").casefold()
            != objects["audit_close"].object_id.casefold()
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons Event/Action baseline chain drifted"
            )
        parameter_id = objects["rifle_distance_parameter"].object_id.casefold()
        mechanical_rtpcs = objects["audit_mechanical"].state.get("rtpc_rows")
        matches = [
            row
            for row in mechanical_rtpcs
            if isinstance(row, Mapping)
            and row.get("@PropertyName") == "Volume"
            and _optional_identity(row.get("@ControlInput")) == parameter_id
        ] if isinstance(mechanical_rtpcs, list | tuple) else []
        if len(matches) != 1:
            raise WeaponsIntegrationRuntimeError(
                "RFL_Mechanical lacks one exact Rifle_Distance Volume RTPC"
            )
        source = snapshot.source_project
        if (
            source.project_sha256 != self.manifest.project_file_sha256
            or source.tree_sha256 != self.manifest.full_tree_sha256
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons source project differs from the baseline manifest"
            )

    def _candidate_roles(
        self, objects: Mapping[str, WeaponsObjectState]
    ) -> tuple[str, ...]:
        bus_id = objects["weapons_bus"].object_id.casefold()
        result: list[str] = []
        for role in _IN_SCOPE_SOUND_ROLES:
            row = objects[role]
            if (
                not row.name.startswith("RFL_")
                or _identity(row.state.get("OutputBus"), f"{role} OutputBus")
                .casefold()
                != bus_id
                or _number(row.state.get("@Volume"), f"{role} Volume") > 0.0
                or "release-ready"
                not in _text(row.state.get("notes"), f"{role} notes")
            ):
                result.append(role)
        return tuple(result)

    def _observe_audit_payload(self, payload: Mapping[str, Any]) -> None:
        rows = payload.get("objects")
        if (
            not isinstance(rows, list)
            or len(rows) > _AUDIT_TAKE
            or any(not isinstance(row, Mapping) for row in rows)
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit query returned malformed or unbounded rows"
            )
        before = self._require_active().objects_by_role()
        expected_ids = {
            before[role].object_id.casefold(): role
            for role in _IN_SCOPE_SOUND_ROLES
        }
        seen: dict[str, Mapping[str, Any]] = {}
        for index, row in enumerate(rows):
            for field in _AUDIT_RETURN_FIELDS:
                if field not in row:
                    raise WeaponsIntegrationRuntimeError(
                        f"Weapons audit row {index} omitted {field}"
                    )
            object_id = _guid(row.get("id"), f"audit row {index} id").casefold()
            if object_id in seen:
                raise WeaponsIntegrationRuntimeError(
                    "Weapons audit query repeated an object"
                )
            if object_id not in expected_ids:
                raise WeaponsIntegrationRuntimeError(
                    "Weapons audit query escaped the reviewed Rifle scope"
                )
            seen[object_id] = row
        if set(seen) != set(expected_ids):
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit query did not return the exact in-scope Sound set"
            )

        rows_by_role: dict[str, Mapping[str, Any]] = {}
        ordered_bus_ids: list[str] = []
        for object_id, row in seen.items():
            role = expected_ids[object_id]
            if _text(row.get("type"), f"{role} type") != "Sound":
                raise WeaponsIntegrationRuntimeError(
                    f"Weapons audit row {role} is not a Sound"
                )
            _wwise_path(row.get("path"), f"{role} path")
            _text(row.get("name"), f"{role} name")
            _number(row.get("@Volume"), f"{role} Volume")
            _text(row.get("notes"), f"{role} notes")
            bus_id = _identity(row.get("OutputBus"), f"{role} OutputBus").casefold()
            if bus_id not in ordered_bus_ids:
                ordered_bus_ids.append(bus_id)
            rows_by_role[role] = MappingProxyType(dict(row))

        expected_bus_ids = tuple(
            state.object_id.casefold()
            for state in _distinct_output_bus_states(self._require_active())
        )
        if (
            len(ordered_bus_ids) != len(expected_bus_ids)
            or set(ordered_bus_ids) != set(expected_bus_ids)
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit query returned a different distinct OutputBus set"
            )
        self.audit_rows_by_role = MappingProxyType(rows_by_role)
        self.audit_output_bus_ids = tuple(ordered_bus_ids)

    def _observe_output_bus_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        if self.audit_rows_by_role is None or self.audit_output_bus_ids is None:
            raise WeaponsIntegrationRuntimeError(
                "Weapons OutputBus hop ran before the scoped audit"
            )
        if (
            len(step.arguments) < 2
            or step.arguments[0] != "--object-id"
            or not isinstance(step.arguments[1], str)
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} does not contain one exact OutputBus GUID"
            )
        expected_id = _guid(
            step.arguments[1], f"{step.name} expected OutputBus id"
        ).casefold()
        if (
            expected_id not in self.audit_output_bus_ids
            or expected_id in self.output_bus_paths
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} is an unexpected or duplicate OutputBus hop"
            )
        objects = payload.get("objects")
        if (
            payload.get("count") != 1
            or not isinstance(objects, list)
            or len(objects) != 1
            or not isinstance(objects[0], Mapping)
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} did not return exactly one OutputBus"
            )
        row = objects[0]
        if set(row) != set(_IDENTITY_RETURN_FIELDS):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} OutputBus identity shape is not closed"
            )
        returned_id = _guid(row.get("id"), f"{step.name} returned id").casefold()
        if returned_id != expected_id:
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} returned a different OutputBus GUID"
            )
        _text(row.get("name"), f"{step.name} name")
        if _text(row.get("type"), f"{step.name} type") != "Bus":
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} did not resolve to a Bus"
            )
        path = _wwise_path(row.get("path"), f"{step.name} path")
        before_matches = tuple(
            state
            for state in self._require_active().objects
            if state.object_id.casefold() == expected_id
        )
        if (
            len(before_matches) != 1
            or before_matches[0].object_type != "Bus"
            or before_matches[0].path != path
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} differs from the sealed OutputBus identity"
            )
        self.output_bus_paths[expected_id] = path
        if set(self.output_bus_paths) == set(self.audit_output_bus_ids):
            self._finalize_audit_candidates()

    def _finalize_audit_candidates(self) -> None:
        rows = self.audit_rows_by_role
        bus_ids = self.audit_output_bus_ids
        if (
            rows is None
            or bus_ids is None
            or set(self.output_bus_paths) != set(bus_ids)
        ):
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit cannot finish before every OutputBus path is resolved"
            )
        target_path = self._visible_values()["weapons_bus_path"]
        target_ids = tuple(
            object_id
            for object_id, path in self.output_bus_paths.items()
            if path == target_path
        )
        if len(target_ids) != 1:
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit did not resolve one unique target Bus path"
            )

        violations: dict[str, tuple[str, ...]] = {}
        for role in _IN_SCOPE_SOUND_ROLES:
            row = rows[role]
            rules: list[str] = []
            if not _text(row.get("name"), f"{role} name").startswith("RFL_"):
                rules.append("name_prefix")
            output_bus_id = _identity(
                row.get("OutputBus"), f"{role} OutputBus"
            ).casefold()
            output_bus_path = self.output_bus_paths.get(output_bus_id)
            if output_bus_path is None:
                raise WeaponsIntegrationRuntimeError(
                    f"Weapons audit lacks the resolved OutputBus path for {role}"
                )
            if output_bus_path != target_path:
                rules.append("output_bus_path")
            if _number(row.get("@Volume"), f"{role} Volume") > 0.0:
                rules.append("volume")
            if "release-ready" not in _text(row.get("notes"), f"{role} notes"):
                rules.append("notes")
            violations[role] = tuple(rules)

        if violations != _EXPECTED_AUDIT_VIOLATIONS:
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit produced the wrong per-object violation map"
            )
        candidate_roles = tuple(role for role, rules in violations.items() if rules)
        if set(candidate_roles) != set(_EXPECTED_CANDIDATE_ROLES):
            raise WeaponsIntegrationRuntimeError(
                "Weapons audit produced the wrong candidate set"
            )
        self.audit_violation_rules = MappingProxyType(violations)
        before = self._require_active().objects_by_role()
        self.audit_candidate_ids = frozenset(
            before[role].object_id.casefold() for role in candidate_roles
        )
        self.audit_exclusions_valid = (
            not violations["audit_compliant"]
            and "audit_out_of_scope" not in rows
        )

    def _observe_identity_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        role = step.name.removeprefix("identity.")
        if role not in _SELECTED_ROLES or role in self.identity_readback_ids:
            raise WeaponsIntegrationRuntimeError(
                f"unexpected or duplicate Weapons identity readback: {step.name}"
            )
        before = self._require_active().objects_by_role()[role]
        objects = payload.get("objects")
        if (
            payload.get("count") != 1
            or not isinstance(objects, list)
            or len(objects) != 1
            or not isinstance(objects[0], Mapping)
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} did not return exactly one object"
            )
        row = objects[0]
        expected = {
            "id": before.object_id,
            "name": before.name,
            "type": before.object_type,
            "path": before.path,
        }
        if set(row) != set(_IDENTITY_RETURN_FIELDS) or any(
            row.get(field) != value for field, value in expected.items()
        ):
            raise WeaponsIntegrationRuntimeError(
                f"{step.name} differs from the sealed selected object identity"
            )
        self.identity_readback_ids[role] = before.object_id

    def _final_assertions(
        self, before: WeaponsSnapshot, after: WeaponsSnapshot
    ) -> tuple[dict[str, bool], dict[str, str]]:
        old = before.objects_by_role()
        new = after.objects_by_role()
        old_media = before.media_by_role()
        new_media = after.media_by_role()
        assertions: dict[str, bool] = {}
        details: dict[str, str] = {}

        def record(name: str, passed: bool, failure: str) -> None:
            assertions[name] = bool(passed)
            details[name] = "ok" if passed else failure

        record(
            "audit_candidates_exact",
            self.audit_candidate_ids
            == frozenset(
                old[role].object_id.casefold()
                for role in _EXPECTED_CANDIDATE_ROLES
            ),
            "the observed read-only audit candidate set was not exact",
        )
        record(
            "excluded_scope_absent",
            self.audit_exclusions_valid,
            "the audit included its compliant control or an out-of-scope object",
        )
        record(
            "selected_ids_revalidated",
            self.selected_revalidated,
            "the preview did not bind the three selected queried GUIDs",
        )
        record(
            "selected_guids_and_parents_preserved",
            all(
                role in new
                and new[role].object_id.casefold() == old[role].object_id.casefold()
                and _identity(new[role].state.get("parent"), f"{role} parent")
                .casefold()
                == _identity(old[role].state.get("parent"), f"{role} old parent")
                .casefold()
                for role in _SELECTED_ROLES
            ),
            "a selected Sound GUID or parent changed",
        )
        bus_id = old["weapons_bus"].object_id.casefold()
        close = new.get("audit_close")
        tail = new.get("audit_tail")
        mechanical = new.get("audit_mechanical")
        corrections_ok = (
            close is not None
            and close.name == "RFL_Close"
            and close.path == old["audit_close"].path.rsplit("\\", 1)[0] + "\\RFL_Close"
            and close.state.get("notes") == "release-ready | close"
            and _identity(close.state.get("OutputBus"), "close OutputBus").casefold()
            == bus_id
            and _number(close.state.get("@Volume"), "close Volume")
            == _number(old["audit_close"].state.get("@Volume"), "old close Volume")
            and _state_equal_except(
                close.state,
                old["audit_close"].state,
                excluded={"notes", "OutputBus"},
            )
            and tail is not None
            and _number(tail.state.get("@Volume"), "tail Volume") == -3.0
            and tail.name == old["audit_tail"].name
            and tail.path == old["audit_tail"].path
            and tail.state.get("notes") == old["audit_tail"].state.get("notes")
            and _identity(tail.state.get("OutputBus"), "tail OutputBus").casefold()
            == _identity(old["audit_tail"].state.get("OutputBus"), "old tail OutputBus").casefold()
            and _state_equal_except(
                tail.state,
                old["audit_tail"].state,
                excluded={"@Volume"},
            )
            and mechanical is not None
            and mechanical.name == old["audit_mechanical"].name
            and mechanical.path == old["audit_mechanical"].path
            and mechanical.state.get("notes") == "release-ready | mechanical"
            and _identity(mechanical.state.get("OutputBus"), "mechanical OutputBus").casefold()
            == bus_id
            and _number(mechanical.state.get("@Volume"), "mechanical Volume")
            == _number(old["audit_mechanical"].state.get("@Volume"), "old mechanical Volume")
            and _state_equal_except(
                mechanical.state,
                old["audit_mechanical"].state,
                excluded={"notes", "OutputBus"},
            )
        )
        record(
            "selected_corrections_exact",
            corrections_ok,
            "one selected field differs from the exact partial correction request",
        )
        expected_steps = (
            tuple(step.name for step in self.protocol.steps)
            if self.protocol is not None
            else ()
        )
        record(
            "single_object_set_batch",
            gateway_step_sequence_matches(
                expected_steps,
                tuple(self.observed_steps),
                (
                    self.protocol.commutative_read_only_step_groups
                    if self.protocol is not None
                    else ()
                ),
            )
            and self.observed_steps.count("tx01.execute") == 1
            and self.observed_steps.count("tx01.verify") == 1,
            "the audit, OutputBus hops, selected exact-ID readbacks, and "
            "one-batch broker protocol were not completed",
        )
        record(
            "event_action_links_unchanged",
            _event_action_contract_unchanged(old, new),
            "the Event or Action identity/reference state changed",
        )
        record(
            "rtpc_and_audio_sources_unchanged",
            all(
                role in new
                and new[role].state.get("activeSource")
                == old[role].state.get("activeSource")
                and new[role].state.get("rtpc_rows")
                == old[role].state.get("rtpc_rows")
                and role in new_media
                and new_media[role] == old_media[role]
                for role in _SELECTED_ROLES
            ),
            "a selected AudioSource, media proof, or RTPC row changed",
        )
        record(
            "exceptions_and_controls_unchanged",
            all(
                role in new
                and new[role] == old[role]
                and new_media.get(role) == old_media.get(role)
                for role in _PROTECTED_ROLES
            )
            and new.get("audit_root") == old.get("audit_root")
            and new.get("weapons_bus") == old.get("weapons_bus")
            and new.get("footsteps_bus") == old.get("footsteps_bus")
            and new.get("rifle_distance_parameter")
            == old.get("rifle_distance_parameter"),
            "an exception, control, root, bus, or parameter changed",
        )
        record(
            "source_project_unchanged",
            after.source_project == before.source_project
            and after.source_project.project_sha256
            == self.manifest.project_file_sha256
            and after.source_project.tree_sha256
            == self.manifest.full_tree_sha256,
            "the immutable source project hash or mtime changed",
        )
        if tuple(assertions) != _EXPECTED_ASSERTION_IDS:
            raise AssertionError("Weapons assertion order drifted")
        return assertions, details

    def _require_active(self) -> WeaponsSnapshot:
        if self.before is None:
            raise WeaponsIntegrationRuntimeError("Weapons runtime was not prepared")
        if self._cleaned:
            raise WeaponsIntegrationRuntimeError("Weapons runtime is already clean")
        return self.before


def _audit_query_step(root_path: str) -> ExpectedGatewayStep:
    # The natural prompt explicitly asks for every Sound below this sealed
    # fixture subtree, so the Skill correctly selects its explicit
    # ``--all-results`` route.  The runner independently rejects more than
    # ``_AUDIT_TAKE`` rows before granting any business-oracle credit.
    arguments: list[Any] = [
        "--path",
        root_path,
        "--select",
        "descendants",
        "--where",
        "type",
        "=",
        "string",
        "Sound",
        "--all-results",
    ]
    for field in _AUDIT_RETURN_FIELDS:
        arguments.extend(("--return-field", field))
    return ExpectedGatewayStep(
        name="audit.scope",
        subcommand="query-object",
        arguments=tuple(arguments),
    )


def _distinct_output_bus_states(
    snapshot: WeaponsSnapshot,
) -> tuple[WeaponsObjectState, ...]:
    """Return the reviewed first-occurrence OutputBus sequence for the audit."""

    objects = snapshot.objects_by_role()
    objects_by_id = {
        state.object_id.casefold(): state for state in snapshot.objects
    }
    seen: set[str] = set()
    result: list[WeaponsObjectState] = []
    for role in _IN_SCOPE_SOUND_ROLES:
        sound = objects.get(role)
        if sound is None:
            raise WeaponsIntegrationRuntimeError(
                f"Weapons snapshot omitted in-scope Sound role {role}"
            )
        output_bus_id = _identity(
            sound.state.get("OutputBus"), f"{role} OutputBus"
        ).casefold()
        if output_bus_id in seen:
            continue
        bus = objects_by_id.get(output_bus_id)
        if bus is None or bus.object_type != "Bus":
            raise WeaponsIntegrationRuntimeError(
                f"Weapons {role} OutputBus does not resolve to a sealed Bus"
            )
        seen.add(output_bus_id)
        result.append(bus)
    if len(result) != 2:
        raise WeaponsIntegrationRuntimeError(
            "Weapons fixture must expose exactly two distinct in-scope OutputBus GUIDs"
        )
    return tuple(result)


def _output_bus_readback_steps(
    snapshot: WeaponsSnapshot,
) -> tuple[ExpectedGatewayStep, ...]:
    steps: list[ExpectedGatewayStep] = []
    for index, state in enumerate(_distinct_output_bus_states(snapshot), start=1):
        arguments: list[str] = ["--object-id", state.object_id]
        for field in _IDENTITY_RETURN_FIELDS:
            arguments.extend(("--return-field", field))
        steps.append(
            ExpectedGatewayStep(
                name=f"{_OUTPUT_BUS_STEP_PREFIX}{index:02d}",
                subcommand="query-object",
                arguments=tuple(arguments),
            )
        )
    return tuple(steps)


def _identity_readback_step(
    role: str,
    state: WeaponsObjectState,
) -> ExpectedGatewayStep:
    if role not in _SELECTED_ROLES:
        raise WeaponsIntegrationRuntimeError(
            f"Weapons identity readback role is not selected: {role}"
        )
    arguments: list[str] = ["--object-id", state.object_id]
    for field in _IDENTITY_RETURN_FIELDS:
        arguments.extend(("--return-field", field))
    return ExpectedGatewayStep(
        name=f"identity.{role}",
        subcommand="query-object",
        arguments=tuple(arguments),
    )


def _validate_reviewed_inputs(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    baseline_manifest: BaselineManifest,
    direct_call: DirectWaapiCall,
) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise WeaponsIntegrationRuntimeError(
            f"Weapons integration version is unsupported: {version!r}"
        )
    if not callable(direct_call):
        raise TypeError("direct_call must be callable")
    if getattr(workflow, "id", None) != WEAPONS_WORKFLOW_ID:
        raise WeaponsIntegrationRuntimeError("wrong integration workflow for Weapons")
    fixture = getattr(workflow, "fixture", None)
    if (
        getattr(fixture, "adapter", None) != WEAPONS_FIXTURE_ADAPTER
        or getattr(fixture, "baseline_source", None)
        != "committed_sample_project"
    ):
        raise WeaponsIntegrationRuntimeError("Weapons fixture adapter drifted")
    if version not in tuple(getattr(workflow, "versions", ())):
        raise WeaponsIntegrationRuntimeError("Weapons workflow/version are misbound")
    transactions = tuple(getattr(workflow, "transactions", ()))
    if len(transactions) != 1:
        raise WeaponsIntegrationRuntimeError("Weapons requires one transaction")
    transaction = transactions[0]
    if (
        getattr(transaction, "index", None) != 1
        or getattr(transaction, "operation", None) != "object.set"
        or getattr(transaction, "api", None) != OBJECT_SET_API
        or getattr(transaction, "preview_turn", None) != 2
        or getattr(transaction, "confirmation_turn", None) != 3
    ):
        raise WeaponsIntegrationRuntimeError("Weapons transaction topology drifted")
    if tuple(getattr(turn, "kind", None) for turn in workflow.turns) != (
        "audit_request",
        "change_request",
        "confirmation",
    ):
        raise WeaponsIntegrationRuntimeError("Weapons turn topology drifted")
    if tuple(item.name for item in workflow.visible_inputs) != (
        "weapons_audit_root_path",
        "weapons_bus_path",
    ):
        raise WeaponsIntegrationRuntimeError("Weapons visible inputs drifted")
    if tuple(item.id for item in fixture.business_assertions) != _EXPECTED_ASSERTION_IDS:
        raise WeaponsIntegrationRuntimeError("Weapons business assertions drifted")
    if set(WEAPONS_CANONICAL_STATE_FIELDS) != {
        row.role for row in fixture.object_graph
    }:
        raise WeaponsIntegrationRuntimeError("Weapons object roles drifted")
    if (
        getattr(scenario, "scenario_family", None) != WEAPONS_WORKFLOW_ID
        or getattr(scenario, "api", None) != OBJECT_SET_API
        or tuple(getattr(scenario, "versions", ())) != (version,)
    ):
        raise WeaponsIntegrationRuntimeError("Weapons scenario proxy is misbound")
    if (
        not isinstance(baseline_manifest, BaselineManifest)
        or baseline_manifest.version != version
    ):
        raise WeaponsIntegrationRuntimeError(
            "Weapons baseline manifest/version are misbound"
        )


def _validated_runtime_paths(runtime: WeaponsRuntimePaths) -> _RuntimePaths:
    directories: dict[str, Path] = {}
    for name in ("scenario_root", "asset_root", "io_root"):
        raw = getattr(runtime, name, None)
        if raw is None:
            raise WeaponsIntegrationRuntimeError(f"Weapons runtime omits {name}")
        directories[name] = _real_directory(Path(raw), name)
    scenario_root = directories["scenario_root"]
    for name in ("asset_root", "io_root"):
        path = directories[name]
        if path == scenario_root or scenario_root not in path.parents:
            raise WeaponsIntegrationRuntimeError(
                f"{name} must be a strict descendant of scenario_root"
            )
    sandbox = getattr(runtime, "sandbox", None)
    if sandbox is None:
        raise WeaponsIntegrationRuntimeError("Weapons runtime omits its sandbox")
    sandbox_project = _real_file(
        Path(getattr(sandbox, "sandbox_project", "")), "sandbox_project"
    )
    source_project = _real_file(
        Path(getattr(sandbox, "source_project", "")), "source_project"
    )
    source_root = _real_directory(
        Path(getattr(sandbox, "source_root", "")), "source_root"
    )
    sandbox_root = _real_directory(
        Path(getattr(sandbox, "sandbox_path", sandbox_project.parent)),
        "sandbox project root",
    )
    if sandbox_project.suffix.casefold() != ".wproj" or source_project.suffix.casefold() != ".wproj":
        raise WeaponsIntegrationRuntimeError("source and sandbox projects must be .wproj files")
    if sandbox_root not in sandbox_project.parents or scenario_root not in sandbox_project.parents:
        raise WeaponsIntegrationRuntimeError("sandbox project escaped its owned root")
    if source_root not in source_project.parents:
        raise WeaponsIntegrationRuntimeError("source project escaped source_root")
    if source_project == sandbox_project or source_root == sandbox_root:
        raise WeaponsIntegrationRuntimeError("source and copied projects are not isolated")
    return _RuntimePaths(
        scenario_root,
        directories["asset_root"],
        directories["io_root"],
        sandbox_project,
        sandbox_root,
        source_project,
        source_root,
    )


def _weapons_manifest_objects(
    manifest: BaselineManifest, specs: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest.objects:
        if not isinstance(raw, Mapping) or raw.get("role") not in specs:
            continue
        role = str(raw["role"])
        expected_fields = WEAPONS_CANONICAL_STATE_FIELDS.get(role)
        state = raw.get("state")
        if (
            role in result
            or expected_fields is None
            or tuple(state) != expected_fields
            if isinstance(state, Mapping)
            else True
        ):
            raise WeaponsIntegrationRuntimeError(
                f"baseline manifest Weapons role {role} state shape drifted"
            )
        spec = specs[role]
        if (
            spec.baseline_state != "present"
            or raw.get("path") != spec.path_for(manifest.version)
            or _type_token(raw.get("type")) != _type_token(spec.type)
            or _GUID_RE.fullmatch(str(raw.get("id"))) is None
            or _SHA256_RE.fullmatch(str(raw.get("state_sha256"))) is None
            or hashlib.sha256(canonical_json_bytes(state)).hexdigest()
            != raw.get("state_sha256")
        ):
            raise WeaponsIntegrationRuntimeError(
                f"baseline manifest Weapons role {role} is malformed"
            )
        result[role] = MappingProxyType(dict(raw))
    if set(result) != set(specs):
        raise WeaponsIntegrationRuntimeError(
            "baseline manifest Weapons object coverage drifted"
        )
    return result


def _weapons_manifest_media(
    manifest: BaselineManifest, specs: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    sound_roles = {
        role for role, spec in specs.items() if _type_token(spec.type) == "sound"
    }
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest.media:
        if not isinstance(raw, Mapping) or raw.get("role") not in sound_roles:
            continue
        role = str(raw["role"])
        if (
            role in result
            or _GUID_RE.fullmatch(str(raw.get("active_source_id"))) is None
            or not isinstance(raw.get("relative_path"), str)
            or not str(raw["relative_path"]).startswith("Originals/")
            or _SHA256_RE.fullmatch(str(raw.get("sha256"))) is None
        ):
            raise WeaponsIntegrationRuntimeError(
                f"baseline manifest Weapons media role {role} is malformed"
            )
        result[role] = MappingProxyType(dict(raw))
    if set(result) != sound_roles:
        raise WeaponsIntegrationRuntimeError(
            "baseline manifest Weapons media coverage drifted"
        )
    return result


def _validate_manifest_object_state(
    state: WeaponsObjectState,
    manifest_row: Mapping[str, Any],
    *,
    version: str,
) -> None:
    if (
        state.object_id.casefold() != str(manifest_row["id"]).casefold()
        or state.path != manifest_row["path"]
        or not _reviewed_type_match(
            version=version,
            role=state.role,
            live_type=state.object_type,
            declared_type=manifest_row["type"],
        )
        or _plain(state.state) != _plain(manifest_row["state"])
        or _json_sha256(_plain(state.state)) != manifest_row["state_sha256"]
    ):
        raise WeaponsIntegrationRuntimeError(
            f"live copied Weapons object differs from manifest role {state.role}"
        )


def _validate_manifest_media(
    state: WeaponsMediaState, manifest_row: Mapping[str, Any]
) -> None:
    if (
        state.active_source_id.casefold()
        != str(manifest_row["active_source_id"]).casefold()
        or state.original.relative_path != manifest_row["relative_path"]
        or state.original.sha256 != manifest_row["sha256"]
        or state.language != "SFX"
    ):
        raise WeaponsIntegrationRuntimeError(
            f"live copied Weapons media differs from manifest role {state.role}"
        )


def _oracle_requirements() -> tuple[WeaponsOracleRequirement, ...]:
    return (
        WeaponsOracleRequirement(
            "before",
            "committed_baseline",
            "all thirteen exact objects, seven AudioSources/media hashes, and canonical state digests match the version manifest",
        ),
        WeaponsOracleRequirement(
            "audit",
            "bounded_scope",
            "one descendants query returns exactly six in-scope Sounds, two distinct OutputBus GUID hops resolve their real paths, and the four rules derive exactly five violations without the control or out-of-scope Sound",
        ),
        WeaponsOracleRequirement(
            "preview",
            "queried_id_batch",
            "one metadata-bound object.set preview uses only the three reviewed GUIDs and leaves the graph unchanged",
        ),
        WeaponsOracleRequirement(
            "after",
            "selected_and_protected_state",
            "the partial corrections are exact while GUIDs, parents, AudioSources, RTPC, Event/Action links, exceptions, controls, buses, and source project are preserved",
        ),
        WeaponsOracleRequirement(
            "cleanup",
            "existing_lifecycle",
            "this input-free adapter changes no file; the shared lifecycle owns copied-project cleanup",
        ),
    )


def _request_object_ids(request: Mapping[str, Any]) -> set[str]:
    try:
        rows = request["arguments"]["objects"]
    except (KeyError, TypeError) as exc:
        raise WeaponsIntegrationRuntimeError("Weapons operation request drifted") from exc
    if not isinstance(rows, list) or len(rows) != 3:
        raise WeaponsIntegrationRuntimeError("Weapons object.set batch is not three rows")
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("object"), Mapping):
            raise WeaponsIntegrationRuntimeError("Weapons object.set row is malformed")
        selector = row["object"]
        if set(selector) != {"kind", "value"} or selector.get("kind") != "id":
            raise WeaponsIntegrationRuntimeError("Weapons mutation selector is not an exact id")
        result.add(_guid(selector.get("value"), "mutation object id").casefold())
    if len(result) != 3:
        raise WeaponsIntegrationRuntimeError("Weapons mutation repeats a GUID")
    return result


def _state_equal_except(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
    *,
    excluded: set[str],
) -> bool:
    if set(current) != set(previous):
        return False
    return all(
        _plain(current[key]) == _plain(previous[key])
        for key in current
        if key not in excluded
    )


def _event_action_contract_unchanged(
    before: Mapping[str, WeaponsObjectState],
    after: Mapping[str, WeaponsObjectState],
) -> bool:
    for role in ("audit_close_event", "audit_close_action"):
        old = before.get(role)
        new = after.get(role)
        if (
            old is None
            or new is None
            or new.object_id.casefold() != old.object_id.casefold()
            or any(
                _plain(new.state.get(field)) != _plain(old.state.get(field))
                for field in ("parent", "ActionType", "Target")
            )
        ):
            return False
    return True


def _normalize_state_field(field: str, value: Any) -> Any:
    if field in {"parent", "OutputBus", "activeSource", "Target"}:
        return {"id": _identity(value, field)}
    if field == "children":
        return [
            {"id": _identity(row, "child reference")}
            for row in _list_value(value, "children")
        ]
    return _plain(value)


def _normalize_rtpc_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {field: _plain(row.get(field)) for field in _RTPC_FIELDS}
    if normalized.get("@ControlInput") not in (None, "", {}):
        normalized["@ControlInput"] = {
            "id": _identity(normalized["@ControlInput"], "RTPC ControlInput")
        }
    return normalized


def _binding_object_path(value: Any, version: str) -> str:
    if not isinstance(value, Mapping):
        raise WeaponsIntegrationRuntimeError("Weapons object-path binding is malformed")
    if value.get("source") == "literal" and set(value) == {"source", "value"}:
        return _wwise_path(value.get("value"), "literal binding")
    values = value.get("values")
    if (
        value.get("source") == "version_literal"
        and set(value) == {"source", "values"}
        and isinstance(values, Mapping)
        and version in values
    ):
        return _wwise_path(values[version], "version binding")
    raise WeaponsIntegrationRuntimeError(
        "Weapons object-path binding does not cover this version"
    )


def _source_project_proof(project: Path, root: Path) -> WeaponsSourceProjectProof:
    proof = _regular_file_proof(project, relative_to=root)
    return WeaponsSourceProjectProof(
        proof.sha256,
        wwise_fixture_tree_sha256(root),
        project.stat().st_mtime_ns,
    )


def _copied_original_proof(
    value: Any,
    *,
    sandbox_root: Path,
    account_home: Path | None = None,
) -> WeaponsFileProof:
    try:
        candidate = localize_copied_original_path(
            value,
            account_home=account_home,
        )
    except IntegrationOriginalPathError as exc:
        raise WeaponsIntegrationRuntimeError(str(exc)) from exc
    root = sandbox_root.resolve(strict=True)
    originals = root / "Originals"
    _real_directory(originals, "copied Originals root")
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise WeaponsIntegrationRuntimeError(
            "copied Original is outside the sandbox"
        ) from exc
    if (
        not lexical_relative.parts
        or Path(lexical_relative.parts[0]) != Path("Originals")
    ):
        raise WeaponsIntegrationRuntimeError(
            "copied Original is outside sandbox Originals"
        )
    current = root
    for part in lexical_relative.parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise WeaponsIntegrationRuntimeError(
                f"copied Original path is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise WeaponsIntegrationRuntimeError(
                f"copied Original path contains a symlink: {current}"
            )
    resolved = candidate.resolve(strict=True)
    try:
        resolved_relative = resolved.relative_to(root)
    except ValueError as exc:
        raise WeaponsIntegrationRuntimeError(
            "copied Original resolves outside the sandbox"
        ) from exc
    if Path(*resolved_relative.parts) != Path(*lexical_relative.parts):
        raise WeaponsIntegrationRuntimeError(
            "copied Original changed during containment proof"
        )
    return _regular_file_proof(resolved, relative_to=root)


def _regular_file_proof(path: Path, *, relative_to: Path | None) -> WeaponsFileProof:
    candidate = _real_file(path, "file proof")
    relative = None
    if relative_to is not None:
        root = relative_to.resolve(strict=True)
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError as exc:
            raise WeaponsIntegrationRuntimeError("file proof escaped its root") from exc
    payload = candidate.read_bytes()
    return WeaponsFileProof(
        str(candidate), relative, len(payload), hashlib.sha256(payload).hexdigest()
    )


def _file_identity(path: Path) -> tuple[str, int, int]:
    proof = _regular_file_proof(path, relative_to=None)
    return proof.sha256, proof.size, path.stat().st_mtime_ns


def _real_directory(path: Path, label: str) -> Path:
    try:
        lexical = Path(os.path.abspath(os.fspath(path.expanduser())))
        metadata = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WeaponsIntegrationRuntimeError(f"cannot resolve {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not resolved.is_dir():
        raise WeaponsIntegrationRuntimeError(f"{label} must be a real directory")
    return resolved


def _real_file(path: Path, label: str) -> Path:
    try:
        lexical = Path(os.path.abspath(os.fspath(path.expanduser())))
        metadata = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WeaponsIntegrationRuntimeError(f"cannot resolve {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not resolved.is_file():
        raise WeaponsIntegrationRuntimeError(f"{label} must be a real file")
    return resolved


def _bounded_rows(
    result: Any, label: str, maximum: int
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(result, Mapping):
        raise WeaponsIntegrationRuntimeError(f"{label} result is not an object")
    rows = result.get("return")
    if (
        not isinstance(rows, list)
        or len(rows) > maximum
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise WeaponsIntegrationRuntimeError(
            f"{label} rows are malformed or unbounded"
        )
    return tuple(rows)


def _one_row(rows: Sequence[Mapping[str, Any]], label: str) -> Mapping[str, Any]:
    if len(rows) != 1:
        raise WeaponsIntegrationRuntimeError(
            f"{label} must resolve to exactly one object"
        )
    return rows[0]


def _return_fields(fields: Sequence[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(field) for field in fields))
    if not result or any(not value or value != value.strip() for value in result):
        raise WeaponsIntegrationRuntimeError("object.get return fields are invalid")
    return result


def _identity(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    return _guid(value, label)


def _optional_identity(value: Any) -> str | None:
    if value in (None, "", {}):
        return None
    try:
        return _identity(value, "optional identity").casefold()
    except WeaponsIntegrationRuntimeError:
        return None


def _guid(value: Any, label: str) -> str:
    if not isinstance(value, str) or _GUID_RE.fullmatch(value) is None:
        raise WeaponsIntegrationRuntimeError(f"{label} is not a GUID")
    return value


def _wwise_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("\\")
        or value != value.strip()
        or "\x00" in value
    ):
        raise WeaponsIntegrationRuntimeError(
            f"{label} is not an absolute Wwise path"
        )
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise WeaponsIntegrationRuntimeError(f"{label} is not a string")
    return value


def _type_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _reviewed_type_match(
    *,
    version: str,
    role: str,
    live_type: Any,
    declared_type: Any,
) -> bool:
    live = _type_token(live_type)
    declared = _type_token(declared_type)
    if live == declared:
        return True
    return (
        version == "2025.1"
        and role == "audit_root"
        and declared == "actormixer"
        and live == "propertycontainer"
    )


def _name_value(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("name")
    if not isinstance(value, str) or not value:
        raise WeaponsIntegrationRuntimeError(f"{label} is not a name")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WeaponsIntegrationRuntimeError(f"{label} is not an integer")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise WeaponsIntegrationRuntimeError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise WeaponsIntegrationRuntimeError(f"{label} is not finite")
    return result


def _list_value(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, (tuple, list)):
        raise WeaponsIntegrationRuntimeError(f"{label} is not a list")
    return tuple(value)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "OBJECT_SET_API",
    "PreparedWeaponsIntegrationRuntime",
    "WEAPONS_CANONICAL_STATE_FIELDS",
    "WEAPONS_FIXTURE_ADAPTER",
    "WEAPONS_WORKFLOW_ID",
    "WeaponsCleanupProof",
    "WeaponsExpectedDispatch",
    "WeaponsFileProof",
    "WeaponsIntegrationRuntimeError",
    "WeaponsMediaState",
    "WeaponsObjectState",
    "WeaponsOracleRequirement",
    "WeaponsSnapshot",
    "WeaponsSourceProjectProof",
    "WeaponsVerification",
    "prepare_weapons_integration_runtime",
]

"""Trusted runtime for the committed-baseline Footsteps v2 workflow.

The copied SampleProject already contains the reviewed Switch Container,
Surface Switch Group, Metal/Wood/Mud content, Event/Action chain, and media.
This adapter never creates that baseline and never attempts to undo it.  It
only seals the copied live graph against the version manifest, creates four
scenario-owned Snow WAV inputs, exposes two immutable gateway transactions,
and performs runner-owned readback after each user turn.

Only ``visible_values`` and the broker protocol are model-facing.  Manifest
GUIDs, copied Originals, assignment tables, source-project proofs, and direct
WAAPI access remain runner-owned.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import struct
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from tests.semantic.support.codex_archive_paths import (
    ArchiveRelativePathError,
    parse_archive_relative_path,
)
from tests.semantic.support.codex_campaign import canonical_json_bytes
from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import (
    GATEWAY_RESULT_CONTRACT,
    ExpectedGatewayStep,
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


FOOTSTEPS_WORKFLOW_ID = "footsteps_snow_assignment_maintenance"
FOOTSTEPS_FIXTURE_ADAPTER = "footsteps_committed_baseline_fixture_v2"
SUPPORTED_VERSIONS = frozenset({"2022.1", "2025.1"})

OBJECT_GET_API = "ak.wwise.core.object.get"
GET_ASSIGNMENTS_API = "ak.wwise.core.switchContainer.getAssignments"
IMPORT_API = "ak.wwise.core.audio.import"
REMOVE_ASSIGNMENT_API = (
    "ak.wwise.core.switchContainer.removeAssignment"
)

_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_OBJECT_ROWS = 64
_MAX_ASSIGNMENT_ROWS = 32

_BASELINE_SOUND_ROLES = (
    "metal_sound",
    "wood_sound",
    "mud_sound",
)
_BASELINE_CONTAINER_ROLES = (
    "metal_container",
    "wood_container",
    "mud_container",
)
_SURFACE_VALUE_ROLES = (
    "surface_metal",
    "surface_wood",
    "surface_mud",
    "surface_snow",
)


def _is_terminal_indeterminate_execute(
    step: ExpectedGatewayStep,
    payload: Mapping[str, Any],
) -> bool:
    """Mirror the broker's exact accepted ordinary-execute terminal branch."""

    return (
        step.subcommand == "execute"
        and step.allowed_exit_codes == (0, 2)
        and payload.get("contract") == GATEWAY_RESULT_CONTRACT
        and payload.get("ok") is False
        and payload.get("command") == "execute"
        and payload.get("status") == "indeterminate"
        and payload.get("state") == "indeterminate"
        and payload.get("automatic_retry") is False
    )


_SNOW_SOUND_ROLES = (
    "snow_step_01",
    "snow_step_02",
    "snow_step_03",
    "snow_step_04",
)
_SNOW_ROLES = ("snow_container", *_SNOW_SOUND_ROLES)
_PROTECTED_ROLES = (
    *_BASELINE_CONTAINER_ROLES,
    *_BASELINE_SOUND_ROLES,
    "surface_group",
    *_SURFACE_VALUE_ROLES,
    "play_footsteps_event",
    "play_footsteps_action",
    "footsteps_bus",
)
_ACTION_EVENT_ROLE = "play_footsteps_event"
_ACTION_ROLE = "play_footsteps_action"

_EXPECTED_ASSERTION_IDS = (
    "snow_hierarchy_created_once",
    "snow_media_hashes_match_inputs",
    "snow_assignment_present",
    "mud_assignment_absent",
    "mud_objects_and_value_preserved",
    "metal_wood_assignments_unchanged",
    "footstep_event_chain_unchanged",
    "existing_footstep_content_unchanged",
    "footsteps_bus_unchanged",
    "two_transaction_sequence_exact",
    "source_project_unchanged",
)
_TX01_CHECKPOINT_ASSERTION_IDS = (
    "snow_hierarchy_created_once",
    "snow_media_hashes_match_inputs",
    "snow_assignment_present",
    "mud_objects_and_value_preserved",
    "metal_wood_assignments_unchanged",
    "footstep_event_chain_unchanged",
    "existing_footstep_content_unchanged",
    "footsteps_bus_unchanged",
    "source_project_unchanged",
)
_TX02_FINAL_ASSERTION_IDS = (
    "mud_assignment_absent",
    "two_transaction_sequence_exact",
)

# Unlike the generic v2 loader, this runtime does not accept an opaque state
# bag.  These are the complete, role-specific manifest keys it consumes.  The
# children and assignment rows are normalized runner-owned readbacks rather
# than untrusted cached prose.
FOOTSTEPS_CANONICAL_STATE_FIELDS: Mapping[str, tuple[str, ...]] = (
    MappingProxyType(
        {
            "player_footsteps": (
                "parent",
                "children",
                "SwitchGroupOrStateGroup",
                "OutputBus",
                "assignment_pairs",
            ),
            "metal_container": ("parent", "children", "OutputBus"),
            "wood_container": ("parent", "children", "OutputBus"),
            "mud_container": ("parent", "children", "OutputBus"),
            "metal_sound": ("parent", "activeSource", "OutputBus"),
            "wood_sound": ("parent", "activeSource", "OutputBus"),
            "mud_sound": ("parent", "activeSource", "OutputBus"),
            "surface_group": ("parent", "children"),
            "surface_metal": ("parent",),
            "surface_wood": ("parent",),
            "surface_mud": ("parent",),
            "surface_snow": ("parent",),
            "play_footsteps_event": ("parent", "children"),
            "play_footsteps_action": ("parent", "ActionType", "Target"),
            "footsteps_bus": ("parent", "@Volume"),
        }
    )
)

_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "originalFilePath",
    "audioSource:language",
)
_CHILD_FIELDS = ("id", "name", "type", "path", "parent")


class FootstepsIntegrationRuntimeError(RuntimeError):
    """The committed Footsteps baseline, protocol, or oracle failed closed."""


DirectWaapiCall = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Any
]


class FootstepsRuntimePaths(Protocol):
    """Scenario-lifecycle subset required by this adapter."""

    scenario_root: Path
    asset_root: Path
    io_root: Path
    sandbox: Any


@dataclass(frozen=True, slots=True)
class FootstepsFileProof:
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
class FootstepsObjectState:
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
class FootstepsMediaState:
    role: str
    sound_id: str
    active_source_id: str
    source_parent_id: str
    language: str
    original: FootstepsFileProof

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "sound_id": self.sound_id,
            "active_source_id": self.active_source_id,
            "source_parent_id": self.source_parent_id,
            "language": self.language,
            "original": self.original.as_dict(),
        }


@dataclass(frozen=True, slots=True, order=True)
class FootstepsAssignmentPair:
    child_id: str
    state_or_switch_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "child": self.child_id,
            "stateOrSwitch": self.state_or_switch_id,
        }


@dataclass(frozen=True, slots=True)
class FootstepsChildState:
    owner_role: str
    object_id: str
    name: str
    path: str
    object_type: str
    parent_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "owner_role": self.owner_role,
            "id": self.object_id,
            "name": self.name,
            "path": self.path,
            "type": self.object_type,
            "parent_id": self.parent_id,
        }


@dataclass(frozen=True, slots=True)
class FootstepsSourceProjectProof:
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
class FootstepsSnapshot:
    workflow_id: str
    version: str
    objects: tuple[FootstepsObjectState, ...]
    absent_roles: tuple[str, ...]
    media: tuple[FootstepsMediaState, ...]
    children: tuple[FootstepsChildState, ...]
    assignments: tuple[FootstepsAssignmentPair, ...]
    input_files: tuple[tuple[str, FootstepsFileProof], ...]
    source_project: FootstepsSourceProjectProof
    digest: str

    def objects_by_role(self) -> dict[str, FootstepsObjectState]:
        return {row.role: row for row in self.objects}

    def media_by_role(self) -> dict[str, FootstepsMediaState]:
        return {row.role: row for row in self.media}

    def children_by_owner(self, role: str) -> tuple[FootstepsChildState, ...]:
        return tuple(row for row in self.children if row.owner_role == role)

    def inputs_by_key(self) -> dict[str, FootstepsFileProof]:
        return dict(self.input_files)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "objects": [row.as_dict() for row in self.objects],
            "absent_roles": list(self.absent_roles),
            "media": [row.as_dict() for row in self.media],
            "children": [row.as_dict() for row in self.children],
            "assignments": [row.as_dict() for row in self.assignments],
            "input_files": [
                {"key": key, **proof.as_dict()}
                for key, proof in self.input_files
            ],
            "source_project": self.source_project.as_dict(),
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class FootstepsVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    assertions: Mapping[str, bool]
    before: FootstepsSnapshot
    after: FootstepsSnapshot | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "passed": self.passed,
            "failures": list(self.failures),
            "assertions": dict(self.assertions),
            "before": self.before.as_dict(),
            "after": self.after.as_dict() if self.after is not None else None,
        }

    def assert_passed(self) -> None:
        if not self.passed:
            raise FootstepsIntegrationRuntimeError(
                f"{self.phase} failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class FootstepsCleanupProof:
    passed: bool
    already_clean: bool
    removed_input_root: str | None
    sandbox_untouched: bool
    source_untouched: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "already_clean": self.already_clean,
            "removed_input_root": self.removed_input_root,
            "sandbox_untouched": self.sandbox_untouched,
            "source_untouched": self.source_untouched,
            "failures": list(self.failures),
        }

    def assert_passed(self) -> None:
        if not self.passed:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps input cleanup failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class FootstepsExpectedDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class FootstepsOracleRequirement:
    transaction_id: str
    expectation: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "expectation": _plain(self.expectation),
        }


@dataclass(frozen=True, slots=True)
class PreparedFootstepsIntegrationRuntime:
    """Frozen runner seam; callbacks and hidden evidence are not model input."""

    workflow_id: str
    version: str
    visible_values: Mapping[str, str]
    protocol: V3GatewayProtocol
    snapshot: Callable[[], FootstepsSnapshot]
    before_snapshot: FootstepsSnapshot
    verify_turn: Callable[[int, Any | None], FootstepsVerification]
    verify_final: Callable[
        [Mapping[str, Any] | None, Any | None], FootstepsVerification
    ]
    cleanup: Callable[[], FootstepsCleanupProof]
    observe_payload: Callable[
        [ExpectedGatewayStep, Mapping[str, Any]], None
    ]
    expected_dispatches: tuple[FootstepsExpectedDispatch, ...]
    oracle_requirements: tuple[FootstepsOracleRequirement, ...]
    operation_requests: tuple[Mapping[str, Any], ...]
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


def prepare_footsteps_integration_runtime(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    runtime: FootstepsRuntimePaths,
    baseline_manifest: BaselineManifest,
    direct_call: DirectWaapiCall,
) -> PreparedFootstepsIntegrationRuntime:
    """Seal one committed Footsteps copy and build its three-turn runtime."""

    _validate_reviewed_inputs(
        workflow,
        scenario,
        version=version,
        baseline_manifest=baseline_manifest,
        direct_call=direct_call,
    )
    paths = _validated_runtime_paths(runtime)
    session = _FootstepsSession(
        workflow=workflow,
        version=version,
        runtime_paths=paths,
        baseline_manifest=baseline_manifest,
        backend=_ClosedFootstepsBackend(direct_call),
    )
    try:
        before, visible_values, requests = session.prepare()
        protocol = build_transaction_protocol(
            requests,
            request_equivalences=(
                "audio_import_default_operation_v1",
                "switch_container_remove_assignment_v1",
            ),
        )
        session.bind_protocol(protocol)
    except BaseException:
        session.cleanup_failed_prepare()
        raise
    return PreparedFootstepsIntegrationRuntime(
        workflow_id=FOOTSTEPS_WORKFLOW_ID,
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
            FootstepsExpectedDispatch(
                IMPORT_API,
                1,
                "create one Snow Random Container, four SFX Sounds, and the "
                "Surface/Snow assignment in one import batch",
            ),
            FootstepsExpectedDispatch(
                REMOVE_ASSIGNMENT_API,
                1,
                "remove only the existing Mud-container/Surface-Mud pair",
            ),
        ),
        oracle_requirements=_oracle_requirements(),
        operation_requests=tuple(_freeze_mapping(row) for row in requests),
        prompt_sources=MappingProxyType(
            {
                "footsteps_input_files": {
                    key: proof.as_dict() for key, proof in before.input_files
                },
                "baseline_manifest_digest": baseline_manifest.digest,
            }
        ),
    )


class _ClosedFootstepsBackend:
    """Bounded runner-only reads with no mutation or generic public method."""

    def __init__(self, call: DirectWaapiCall) -> None:
        if not callable(call):
            raise TypeError("direct_call must be callable")
        self.__call = call

    def read_path(
        self,
        path: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"from": {"path": [_wwise_path(path, "object path")]}},
            fields,
            "object.get path",
        )

    def read_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"from": {"id": [_guid(object_id, "object id")]}},
            fields,
            "object.get id",
        )

    def read_children(
        self,
        object_id: str,
        *,
        fields: Sequence[str] = _CHILD_FIELDS,
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {
                "from": {"id": [_guid(object_id, "parent id")]},
                "transform": [{"select": ["children"]}],
            },
            fields,
            "object.get children",
        )

    def read_assignments(
        self,
        switch_container_id: str,
    ) -> tuple[FootstepsAssignmentPair, ...]:
        result = self.__call(
            GET_ASSIGNMENTS_API,
            {"id": _guid(switch_container_id, "Switch Container id")},
            {},
        )
        if not isinstance(result, Mapping):
            raise FootstepsIntegrationRuntimeError(
                "getAssignments result is not an object"
            )
        rows = result.get("return")
        if (
            not isinstance(rows, list)
            or len(rows) > _MAX_ASSIGNMENT_ROWS
            or any(not isinstance(row, Mapping) for row in rows)
        ):
            raise FootstepsIntegrationRuntimeError(
                "getAssignments rows are malformed or unbounded"
            )
        pairs: list[FootstepsAssignmentPair] = []
        for index, row in enumerate(rows):
            pairs.append(
                FootstepsAssignmentPair(
                    child_id=_identity(
                        row.get("child"), f"assignment {index} child"
                    ),
                    state_or_switch_id=_identity(
                        row.get("stateOrSwitch"),
                        f"assignment {index} stateOrSwitch",
                    ),
                )
            )
        normalized = tuple(
            sorted(
                pairs,
                key=lambda row: (
                    row.child_id.casefold(),
                    row.state_or_switch_id.casefold(),
                ),
            )
        )
        if len(
            {
                (row.child_id.casefold(), row.state_or_switch_id.casefold())
                for row in normalized
            }
        ) != len(normalized):
            raise FootstepsIntegrationRuntimeError(
                "getAssignments returned a duplicate pair"
            )
        return normalized

    def _read(
        self,
        args: Mapping[str, Any],
        fields: Sequence[str],
        label: str,
    ) -> tuple[Mapping[str, Any], ...]:
        values = _return_fields(fields)
        result = self.__call(
            OBJECT_GET_API,
            dict(args),
            {"return": list(values)},
        )
        if not isinstance(result, Mapping):
            raise FootstepsIntegrationRuntimeError(
                f"{label} result is not an object"
            )
        rows = result.get("return")
        if (
            not isinstance(rows, list)
            or len(rows) > _MAX_OBJECT_ROWS
            or any(not isinstance(row, Mapping) for row in rows)
        ):
            raise FootstepsIntegrationRuntimeError(
                f"{label} rows are malformed or unbounded"
            )
        return tuple(MappingProxyType(dict(row)) for row in rows)


class _FootstepsSession:
    def __init__(
        self,
        *,
        workflow: Any,
        version: str,
        runtime_paths: _RuntimePaths,
        baseline_manifest: BaselineManifest,
        backend: _ClosedFootstepsBackend,
    ) -> None:
        self.workflow = workflow
        self.version = version
        self.paths = runtime_paths
        self.manifest = baseline_manifest
        self.backend = backend
        self.specs = {
            str(row.role): row for row in workflow.fixture.object_graph
        }
        self.manifest_objects = _footsteps_manifest_objects(
            baseline_manifest,
            self.specs,
        )
        self.manifest_media = _footsteps_manifest_media(
            baseline_manifest,
            self.specs,
        )
        self.input_root: Path | None = None
        self.input_paths: dict[str, Path] = {}
        self.before: FootstepsSnapshot | None = None
        self.protocol: V3GatewayProtocol | None = None
        self.observed_steps: list[str] = []
        self._cleaned = False
        self._finalized = False
        self._checkpoint_verified = False

    def prepare(
        self,
    ) -> tuple[
        FootstepsSnapshot,
        Mapping[str, str],
        tuple[Mapping[str, Any], Mapping[str, Any]],
    ]:
        if self.before is not None or self._cleaned:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps runtime is single-use"
            )
        input_root = self._create_inputs()
        self.input_root = input_root
        before = self._capture_snapshot(validate_manifest=True)
        self._validate_baseline(before)
        visible_values = self._visible_values(input_root)
        requests = self._operation_requests(visible_values)
        self.before = before
        return before, visible_values, requests

    def bind_protocol(self, protocol: V3GatewayProtocol) -> None:
        if self.protocol is not None or self.before is None:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps protocol binding is late or duplicated"
            )
        names = tuple(step.name for step in protocol.steps)
        if (
            len(names) != 12
            or protocol.turn_prefix_counts != (2, 8, 12)
            or names.count("tx01.execute") != 1
            or names.count("tx02.execute") != 1
            or names[0] != "tx01.operation-schema"
            or names[-1] != "tx02.verify"
        ):
            raise FootstepsIntegrationRuntimeError(
                "Footsteps protocol is not exactly two separately confirmed transactions"
            )
        self.protocol = protocol

    def snapshot(self) -> FootstepsSnapshot:
        self._require_active()
        return self._capture_snapshot(validate_manifest=False)

    def verify_turn(
        self,
        turn_index: int,
        _result: Any | None = None,
    ) -> FootstepsVerification:
        if type(turn_index) is not int or turn_index not in {1, 2}:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps turn verification supports only turns 1 and 2"
            )
        before = self._require_active()
        phase = (
            "preview_one_no_change"
            if turn_index == 1
            else "after_snow_before_mud_removal"
        )
        try:
            after = self._capture_snapshot(validate_manifest=False)
        except FootstepsIntegrationRuntimeError as exc:
            return FootstepsVerification(
                phase=phase,
                passed=False,
                failures=(str(exc),),
                assertions=MappingProxyType(
                    {
                        (
                            "preview_unchanged"
                            if turn_index == 1
                            else "snow_checkpoint_exact"
                        ): False
                    }
                ),
                before=before,
                after=None,
            )
        if turn_index == 1:
            passed = after == before
            assertions = {"preview_unchanged": passed}
            failures = (
                ()
                if passed
                else ("first preview changed the sealed Footsteps snapshot",)
            )
        else:
            assertions, details = self._business_assertions(
                before,
                after,
                final=False,
            )
            passed = all(
                assertions[name]
                for name in _TX01_CHECKPOINT_ASSERTION_IDS
            )
            failures = tuple(
                f"{name}: {details[name]}"
                for name in _TX01_CHECKPOINT_ASSERTION_IDS
                if not assertions[name]
            )
            assertions = {
                name: assertions[name]
                for name in _TX01_CHECKPOINT_ASSERTION_IDS
            }
            if passed:
                self._checkpoint_verified = True
        return FootstepsVerification(
            phase=phase,
            passed=passed,
            failures=failures,
            assertions=MappingProxyType(assertions),
            before=before,
            after=after,
        )

    def observe_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        self._require_active()
        protocol = self.protocol
        if protocol is None:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps observer ran before protocol binding"
            )
        if not isinstance(step, ExpectedGatewayStep) or not isinstance(
            payload, Mapping
        ):
            raise FootstepsIntegrationRuntimeError(
                "Footsteps observer received an invalid step or payload"
            )
        expected_names = tuple(row.name for row in protocol.steps)
        position = len(self.observed_steps)
        if position >= len(expected_names) or step.name != expected_names[position]:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps gateway steps were duplicated or observed out of order"
            )
        command = payload.get("command")
        if command is not None and command != step.subcommand:
            raise FootstepsIntegrationRuntimeError(
                f"{step.name} returned a different gateway command"
            )
        terminal_indeterminate = _is_terminal_indeterminate_execute(
            step,
            payload,
        )
        if (
            step.subcommand in {"preview", "verify"}
            and payload.get("ok") is not True
        ):
            raise FootstepsIntegrationRuntimeError(
                f"{step.name} did not return a successful gateway payload"
            )
        if (
            step.subcommand == "execute"
            and payload.get("ok") is not True
            and not terminal_indeterminate
        ):
            raise FootstepsIntegrationRuntimeError(
                f"{step.name} did not return a successful gateway payload"
            )
        self.observed_steps.append(step.name)
        if terminal_indeterminate:
            return
        if step.name == "tx01.preview":
            self.verify_turn(1).assert_passed()
        elif step.name == "tx01.verify":
            self.verify_turn(2).assert_passed()

    def verify_final(
        self,
        _gateway_payload: Mapping[str, Any] | None = None,
        _result: Any | None = None,
    ) -> FootstepsVerification:
        if self._finalized:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps final verification is single-use"
            )
        before = self._require_active()
        try:
            after = self._capture_snapshot(validate_manifest=False)
        except FootstepsIntegrationRuntimeError as exc:
            self._finalized = True
            return FootstepsVerification(
                phase="after_mud_assignment_removal",
                passed=False,
                failures=(str(exc),),
                assertions=MappingProxyType(
                    {name: False for name in _EXPECTED_ASSERTION_IDS}
                ),
                before=before,
                after=None,
            )
        assertions, details = self._business_assertions(
            before,
            after,
            final=True,
        )
        failures = tuple(
            f"{name}: {details[name]}"
            for name in _EXPECTED_ASSERTION_IDS
            if not assertions[name]
        )
        self._finalized = True
        return FootstepsVerification(
            phase="after_mud_assignment_removal",
            passed=not failures,
            failures=failures,
            assertions=MappingProxyType(assertions),
            before=before,
            after=after,
        )

    def cleanup(self) -> FootstepsCleanupProof:
        if self._cleaned:
            return FootstepsCleanupProof(True, True, None, True, True, ())
        if self.input_root is None:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps cleanup cannot run before preparation"
            )
        failures: list[str] = []
        input_root = self.input_root
        sandbox_before = _file_identity(self.paths.sandbox_project)
        source_before = _source_project_proof(
            self.paths.source_project,
            self.paths.source_root,
        )
        try:
            _remove_owned_input_tree(
                input_root,
                stop=self.paths.asset_root,
                expected_names={path.name for path in self.input_paths.values()},
            )
        except BaseException as exc:
            failures.append(f"inputs: {type(exc).__name__}: {exc}")
        sandbox_after = _file_identity(self.paths.sandbox_project)
        source_after = _source_project_proof(
            self.paths.source_project,
            self.paths.source_root,
        )
        sandbox_untouched = sandbox_before == sandbox_after
        source_untouched = source_before == source_after
        if not sandbox_untouched:
            failures.append("input cleanup changed the copied .wproj file")
        if not source_untouched:
            failures.append("input cleanup changed the source project")
        if input_root.exists() or input_root.is_symlink():
            failures.append("Footsteps input root remains after cleanup")
        self._cleaned = not failures
        return FootstepsCleanupProof(
            passed=self._cleaned,
            already_clean=False,
            removed_input_root=str(input_root) if self._cleaned else None,
            sandbox_untouched=sandbox_untouched,
            source_untouched=source_untouched,
            failures=tuple(failures),
        )

    def cleanup_failed_prepare(self) -> None:
        """Best-effort removal of inputs when no prepared seam can be returned."""

        root = self.input_root
        if root is None or not (root.exists() or root.is_symlink()):
            return
        try:
            _remove_owned_input_tree(
                root,
                stop=self.paths.asset_root,
                expected_names={path.name for path in self.input_paths.values()},
            )
        except BaseException:
            # Preserve the preparation exception.  The outer scenario lifecycle
            # owns and quarantines any residual scenario directory.
            return

    def _create_inputs(self) -> Path:
        binding = self.workflow.fixture.visible_bindings[
            "snow_source_directory"
        ]
        relative = binding.get("relative_path")
        if relative != "integration-v2/footsteps/incoming":
            raise FootstepsIntegrationRuntimeError(
                "Footsteps source binding differs from the reviewed owned path"
            )
        root = _fresh_owned_directory(self.paths.asset_root, str(relative))
        self.input_root = root
        for spec in self.workflow.fixture.source_files:
            path = root / _safe_file_name(spec.file_name)
            _write_deterministic_wav(
                path,
                duration_ms=spec.duration_ms,
                frequency_hz=spec.frequency_hz,
            )
            self.input_paths[str(spec.key)] = path
        if tuple(self.input_paths) != _SNOW_SOUND_ROLES:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps input identity or order drifted"
            )
        return root

    def _visible_values(self, input_root: Path) -> Mapping[str, str]:
        bindings = self.workflow.fixture.visible_bindings
        values = {
            "snow_source_directory": str(input_root),
            "footsteps_container_path": _binding_object_path(
                bindings["footsteps_container_path"], self.version
            ),
            "surface_group_path": _binding_object_path(
                bindings["surface_group_path"], self.version
            ),
            "footsteps_event_path": _binding_object_path(
                bindings["footsteps_event_path"], self.version
            ),
        }
        if tuple(values) != (
            "snow_source_directory",
            "footsteps_container_path",
            "surface_group_path",
            "footsteps_event_path",
        ):
            raise AssertionError("Footsteps visible value order drifted")
        return MappingProxyType(values)

    def _operation_requests(
        self,
        visible_values: Mapping[str, str],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        parameters = self.workflow.fixture.parameters
        structure = parameters["structure_row"]
        imports: list[dict[str, Any]] = [
            {
                "object_path": self.specs[str(structure["role"])].path_for(
                    self.version
                ),
                "object_type": str(structure["object_type"]),
                "switch_assignment": str(structure["switch_assignment"]),
            }
        ]
        for row in parameters["sound_rows"]:
            role = str(row["role"])
            source_key = str(row["source_key"])
            imports.append(
                {
                    "object_path": self.specs[role].path_for(self.version),
                    "object_type": "Sound SFX",
                    "audio_file": str(self.input_paths[source_key]),
                    "import_language": "SFX",
                }
            )
        import_request: Mapping[str, Any] = MappingProxyType(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": self.version,
                "operation": "audio.import",
                "arguments": {
                    "import_operation": "createNew",
                    "imports": imports,
                },
            }
        )
        pairs = parameters["assignment_pairs"]
        remove = pairs["remove"]
        remove_child = self.specs[str(remove["child_role"])]
        remove_value = self.specs[str(remove["value_role"])]
        remove_child_path = remove_child.path_for(self.version)
        remove_value_path = remove_value.path_for(self.version)
        if (
            remove_child_path.rsplit("\\", 1)[0]
            != visible_values["footsteps_container_path"]
            or remove_value_path.rsplit("\\", 1)[0]
            != visible_values["surface_group_path"]
        ):
            raise FootstepsIntegrationRuntimeError(
                "Footsteps scoped remove selectors do not match their sealed parents"
            )
        remove_request: Mapping[str, Any] = MappingProxyType(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": self.version,
                "operation": "switchContainer.removeAssignment",
                "arguments": {
                    "switch_container": {
                        "kind": "path",
                        "value": visible_values["footsteps_container_path"],
                    },
                    "child": {
                        "kind": "scoped-name",
                        "name": remove_child_path.rsplit("\\", 1)[-1],
                        "type": str(remove_child.type),
                        "parent": {
                            "kind": "path",
                            "value": visible_values["footsteps_container_path"],
                        },
                    },
                    "state_or_switch": {
                        "kind": "scoped-name",
                        "name": remove_value_path.rsplit("\\", 1)[-1],
                        "type": str(remove_value.type),
                        "parent": {
                            "kind": "path",
                            "value": visible_values["surface_group_path"],
                        },
                    },
                },
            }
        )
        if (
            len(imports) != 5
            or sum("switch_assignment" in row for row in imports) != 1
            or imports[0].get("object_type") != "RandomSequenceContainer"
        ):
            raise FootstepsIntegrationRuntimeError(
                "Footsteps import request is not the reviewed five-row batch"
            )
        return import_request, remove_request

    def _capture_snapshot(
        self,
        *,
        validate_manifest: bool,
    ) -> FootstepsSnapshot:
        objects: list[FootstepsObjectState] = []
        absent: list[str] = []
        media: list[FootstepsMediaState] = []
        child_rows: list[FootstepsChildState] = []
        assignments: tuple[FootstepsAssignmentPair, ...] | None = None

        for role, spec in self.specs.items():
            manifest_row = self.manifest_objects.get(role)
            fields = FOOTSTEPS_CANONICAL_STATE_FIELDS.get(role)
            if fields is None:
                if role == "snow_container":
                    fields = ("parent", "children", "OutputBus")
                elif role in _SNOW_SOUND_ROLES:
                    fields = ("parent", "activeSource", "OutputBus")
                else:
                    raise FootstepsIntegrationRuntimeError(
                        f"Footsteps role has no closed runtime state: {role}"
                    )
            live_fields = tuple(
                field
                for field in fields
                if field not in {"children", "assignment_pairs"}
            )
            query_fields = _return_fields(
                ("id", "name", "type", "path", *live_fields)
            )
            spec_path = spec.path_for(self.version)
            lookup_label = spec_path
            if role == _ACTION_ROLE:
                if manifest_row is None:
                    raise FootstepsIntegrationRuntimeError(
                        "manifest omitted the sealed Play_Footsteps Action"
                    )
                rows = self.backend.read_id(
                    str(manifest_row["id"]),
                    fields=query_fields,
                )
                lookup_label = f"{role} manifest id"
            else:
                rows = self.backend.read_path(spec_path, fields=query_fields)
            if not rows:
                absent.append(role)
                if manifest_row is not None:
                    raise FootstepsIntegrationRuntimeError(
                        f"committed Footsteps object is absent: {role}"
                    )
                continue
            raw = _one_row(rows, lookup_label)
            object_id = _guid(raw.get("id"), f"{role} id")
            path = _wwise_path(raw.get("path"), f"{role} path")
            object_type = _text(raw.get("type"), f"{role} type")
            if path != spec_path or _type_token(object_type) != _type_token(
                spec.type
            ):
                raise FootstepsIntegrationRuntimeError(
                    f"{role} path or type differs from the reviewed workflow"
                )
            state, owned_children, owned_assignments = self._capture_role_state(
                role,
                object_id,
                raw,
                fields,
            )
            child_rows.extend(owned_children)
            if owned_assignments is not None:
                if assignments is not None:
                    raise FootstepsIntegrationRuntimeError(
                        "Footsteps assignments were captured more than once"
                    )
                assignments = owned_assignments
            object_state = FootstepsObjectState(
                role=role,
                object_id=object_id,
                name=_name_value(raw.get("name"), f"{role} name"),
                object_type=object_type,
                path=path,
                state=state,
            )
            if manifest_row is not None and (
                validate_manifest or role in {_ACTION_EVENT_ROLE, _ACTION_ROLE}
            ):
                _validate_manifest_object_state(object_state, manifest_row)
            objects.append(object_state)
            if _type_token(spec.type) == "sound":
                media_state = self._capture_media(object_state)
                if validate_manifest:
                    manifest_media = self.manifest_media.get(role)
                    if manifest_media is None:
                        raise FootstepsIntegrationRuntimeError(
                            f"manifest omitted Footsteps media role {role}"
                        )
                    _validate_manifest_media(media_state, manifest_media)
                media.append(media_state)

        self._validate_action_oracle(objects, child_rows)
        present_snow = set(_SNOW_ROLES) - set(absent)
        if present_snow and present_snow != set(_SNOW_ROLES):
            raise FootstepsIntegrationRuntimeError(
                "Snow hierarchy is partially present"
            )
        if assignments is None:
            raise FootstepsIntegrationRuntimeError(
                "Player_Footsteps assignment table was not captured"
            )
        input_files = tuple(
            (
                key,
                _regular_file_proof(path, relative_to=self.paths.asset_root),
            )
            for key, path in self.input_paths.items()
        )
        source_proof = _source_project_proof(
            self.paths.source_project,
            self.paths.source_root,
        )
        serial = {
            "workflow_id": FOOTSTEPS_WORKFLOW_ID,
            "version": self.version,
            "objects": [row.as_dict() for row in objects],
            "absent_roles": absent,
            "media": [row.as_dict() for row in media],
            "children": [row.as_dict() for row in child_rows],
            "assignments": [row.as_dict() for row in assignments],
            "input_files": [
                {"key": key, **proof.as_dict()}
                for key, proof in input_files
            ],
            "source_project": source_proof.as_dict(),
        }
        return FootstepsSnapshot(
            workflow_id=FOOTSTEPS_WORKFLOW_ID,
            version=self.version,
            objects=tuple(objects),
            absent_roles=tuple(absent),
            media=tuple(media),
            children=tuple(child_rows),
            assignments=assignments,
            input_files=input_files,
            source_project=source_proof,
            digest=_json_sha256(serial),
        )

    def _validate_action_oracle(
        self,
        objects: Sequence[FootstepsObjectState],
        children: Sequence[FootstepsChildState],
    ) -> None:
        """Prove the nameless Action through its sealed GUID and parent Event."""

        by_role = {row.role: row for row in objects}
        event = by_role.get(_ACTION_EVENT_ROLE)
        action = by_role.get(_ACTION_ROLE)
        event_children = tuple(
            row for row in children if row.owner_role == _ACTION_EVENT_ROLE
        )
        if event is None or action is None:
            raise FootstepsIntegrationRuntimeError(
                "Play_Footsteps Event/Action oracle is incomplete"
            )
        if len(event_children) != 1:
            raise FootstepsIntegrationRuntimeError(
                "Play_Footsteps Event must expose exactly one direct Action"
            )
        child = event_children[0]
        if (
            child.object_id.casefold() != action.object_id.casefold()
            or child.parent_id.casefold() != event.object_id.casefold()
            or child.name != action.name
            or _type_token(child.object_type) != "action"
            or child.path != action.path
            or _identity(
                action.state.get("parent"), "Play_Footsteps Action parent"
            ).casefold()
            != event.object_id.casefold()
        ):
            raise FootstepsIntegrationRuntimeError(
                "Play_Footsteps Event child and sealed Action detail disagree"
            )

    def _capture_role_state(
        self,
        role: str,
        object_id: str,
        raw: Mapping[str, Any],
        fields: Sequence[str],
    ) -> tuple[
        Mapping[str, Any],
        tuple[FootstepsChildState, ...],
        tuple[FootstepsAssignmentPair, ...] | None,
    ]:
        children: tuple[FootstepsChildState, ...] = ()
        assignments: tuple[FootstepsAssignmentPair, ...] | None = None
        state: dict[str, Any] = {}
        for field in fields:
            if field == "parent":
                state[field] = _reference(
                    raw.get(field), f"{role} parent"
                )
            elif field == "children":
                children = self._capture_children(role, object_id)
                state[field] = [
                    {"id": row.object_id}
                    for row in sorted(
                        children, key=lambda item: item.object_id.casefold()
                    )
                ]
            elif field == "assignment_pairs":
                assignments = self.backend.read_assignments(object_id)
                state[field] = [row.as_dict() for row in assignments]
            elif field in {
                "SwitchGroupOrStateGroup",
                "activeSource",
                "Target",
            }:
                state[field] = _reference(
                    raw.get(field), f"{role} {field}"
                )
            elif field == "OutputBus":
                state[field] = _optional_reference(raw.get(field))
            elif field == "ActionType":
                state[field] = _integer(raw.get(field), f"{role} ActionType")
            elif field == "@Volume":
                state[field] = _number(raw.get(field), f"{role} Volume")
            else:  # pragma: no cover - field map is closed above
                raise FootstepsIntegrationRuntimeError(
                    f"unsupported Footsteps state field: {role}.{field}"
                )
        return _freeze_mapping(state), children, assignments

    def _capture_children(
        self,
        owner_role: str,
        owner_id: str,
    ) -> tuple[FootstepsChildState, ...]:
        result: list[FootstepsChildState] = []
        for raw in self.backend.read_children(owner_id):
            parent_id = _identity(
                raw.get("parent"), f"{owner_role} child parent"
            )
            if parent_id.casefold() != owner_id.casefold():
                raise FootstepsIntegrationRuntimeError(
                    f"{owner_role} direct child has another parent"
                )
            result.append(
                FootstepsChildState(
                    owner_role=owner_role,
                    object_id=_guid(
                        raw.get("id"), f"{owner_role} child id"
                    ),
                    name=_name_value(
                        raw.get("name"), f"{owner_role} child name"
                    ),
                    path=_wwise_path(
                        raw.get("path"), f"{owner_role} child path"
                    ),
                    object_type=_text(
                        raw.get("type"), f"{owner_role} child type"
                    ),
                    parent_id=parent_id,
                )
            )
        normalized = tuple(
            sorted(
                result,
                key=lambda row: (row.path.casefold(), row.object_id.casefold()),
            )
        )
        if len({row.object_id.casefold() for row in normalized}) != len(
            normalized
        ):
            raise FootstepsIntegrationRuntimeError(
                f"{owner_role} returned duplicate direct children"
            )
        return normalized

    def _capture_media(
        self,
        sound: FootstepsObjectState,
    ) -> FootstepsMediaState:
        active_source_id = _identity(
            sound.state.get("activeSource"),
            f"{sound.role} activeSource",
        )
        source = _one_row(
            self.backend.read_id(active_source_id, fields=_SOURCE_FIELDS),
            f"{sound.role} activeSource",
        )
        source_id = _guid(source.get("id"), f"{sound.role} source id")
        if (
            source_id.casefold() != active_source_id.casefold()
            or _type_token(source.get("type"))
            not in {"audiofilesource", "audiosource"}
        ):
            raise FootstepsIntegrationRuntimeError(
                f"{sound.role} activeSource identity or type drifted"
            )
        source_parent_id = _identity(
            source.get("parent"), f"{sound.role} source parent"
        )
        if source_parent_id.casefold() != sound.object_id.casefold():
            raise FootstepsIntegrationRuntimeError(
                f"{sound.role} activeSource has another parent"
            )
        language = _name_value(
            source.get("audioSource:language"),
            f"{sound.role} source language",
        )
        original = _copied_original_proof(
            source.get("originalFilePath"),
            sandbox_root=self.paths.sandbox_root,
        )
        return FootstepsMediaState(
            role=sound.role,
            sound_id=sound.object_id,
            active_source_id=source_id,
            source_parent_id=source_parent_id,
            language=language,
            original=original,
        )

    def _validate_baseline(self, snapshot: FootstepsSnapshot) -> None:
        objects = snapshot.objects_by_role()
        media = snapshot.media_by_role()
        if snapshot.absent_roles != _SNOW_ROLES:
            raise FootstepsIntegrationRuntimeError(
                "Snow is not the exact absent baseline hierarchy"
            )
        expected_present = {
            role
            for role, spec in self.specs.items()
            if spec.baseline_state == "present"
        }
        if set(objects) != expected_present:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps baseline object coverage differs from the workflow"
            )

        player = objects["player_footsteps"]
        group = objects["surface_group"]
        bus = objects["footsteps_bus"]
        if (
            _identity(
                player.state.get("SwitchGroupOrStateGroup"),
                "Player_Footsteps SwitchGroupOrStateGroup",
            ).casefold()
            != group.object_id.casefold()
            or _identity(
                player.state.get("OutputBus"),
                "Player_Footsteps OutputBus",
            ).casefold()
            != bus.object_id.casefold()
        ):
            raise FootstepsIntegrationRuntimeError(
                "Player_Footsteps group reference or OutputBus drifted"
            )
        expected_player_children = {
            objects[role].object_id.casefold()
            for role in _BASELINE_CONTAINER_ROLES
        }
        if self._child_id_set(snapshot, "player_footsteps") != (
            expected_player_children
        ):
            raise FootstepsIntegrationRuntimeError(
                "Player_Footsteps baseline children are not exactly Metal/Wood/Mud"
            )

        expected_group_children = {
            objects[role].object_id.casefold()
            for role in _SURFACE_VALUE_ROLES
        }
        if self._child_id_set(snapshot, "surface_group") != (
            expected_group_children
        ):
            raise FootstepsIntegrationRuntimeError(
                "Surface group children are not exactly Metal/Wood/Mud/Snow"
            )
        for role in _SURFACE_VALUE_ROLES:
            if _identity(
                objects[role].state.get("parent"), f"{role} parent"
            ).casefold() != group.object_id.casefold():
                raise FootstepsIntegrationRuntimeError(
                    f"{role} is not parented by the Surface group"
                )

        for container_role, sound_role in zip(
            _BASELINE_CONTAINER_ROLES,
            _BASELINE_SOUND_ROLES,
            strict=True,
        ):
            container = objects[container_role]
            sound = objects[sound_role]
            if (
                _identity(
                    container.state.get("parent"),
                    f"{container_role} parent",
                ).casefold()
                != player.object_id.casefold()
                or _identity(
                    sound.state.get("parent"), f"{sound_role} parent"
                ).casefold()
                != container.object_id.casefold()
                or self._child_id_set(snapshot, container_role)
                != {sound.object_id.casefold()}
            ):
                raise FootstepsIntegrationRuntimeError(
                    f"{container_role}/{sound_role} hierarchy drifted"
                )

        event = objects["play_footsteps_event"]
        action = objects["play_footsteps_action"]
        if (
            self._child_id_set(snapshot, "play_footsteps_event")
            != {action.object_id.casefold()}
            or _identity(
                action.state.get("parent"), "Play_Footsteps Action parent"
            ).casefold()
            != event.object_id.casefold()
            or _integer(
                action.state.get("ActionType"), "Play_Footsteps ActionType"
            )
            != 1
            or _identity(
                action.state.get("Target"), "Play_Footsteps Target"
            ).casefold()
            != player.object_id.casefold()
        ):
            raise FootstepsIntegrationRuntimeError(
                "Play_Footsteps Event/Action chain drifted"
            )

        expected_assignments = self._named_pairs(
            objects,
            (
                ("metal_container", "surface_metal"),
                ("wood_container", "surface_wood"),
                ("mud_container", "surface_mud"),
            ),
        )
        if self._pair_key_set(snapshot.assignments) != expected_assignments:
            raise FootstepsIntegrationRuntimeError(
                "baseline assignments are not exactly Metal/Wood/Mud"
            )
        if set(media) != set(_BASELINE_SOUND_ROLES) or any(
            row.language != "SFX" for row in media.values()
        ):
            raise FootstepsIntegrationRuntimeError(
                "baseline Footsteps media coverage or language drifted"
            )
        media_ids = [row.active_source_id.casefold() for row in media.values()]
        if len(media_ids) != len(set(media_ids)):
            raise FootstepsIntegrationRuntimeError(
                "baseline Footsteps AudioSource GUIDs are not unique"
            )
        source = snapshot.source_project
        if (
            source.project_sha256 != self.manifest.project_file_sha256
            or source.tree_sha256 != self.manifest.full_tree_sha256
        ):
            raise FootstepsIntegrationRuntimeError(
                "Footsteps source project differs from the sealed baseline manifest"
            )

    @staticmethod
    def _pair_key_set(
        pairs: Sequence[FootstepsAssignmentPair],
    ) -> set[tuple[str, str]]:
        return {
            (row.child_id.casefold(), row.state_or_switch_id.casefold())
            for row in pairs
        }

    @staticmethod
    def _named_pairs(
        objects: Mapping[str, FootstepsObjectState],
        pairs: Sequence[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        return {
            (
                objects[child].object_id.casefold(),
                objects[value].object_id.casefold(),
            )
            for child, value in pairs
        }

    @staticmethod
    def _child_id_set(
        snapshot: FootstepsSnapshot,
        owner_role: str,
    ) -> set[str]:
        return {
            row.object_id.casefold()
            for row in snapshot.children_by_owner(owner_role)
        }

    def _business_assertions(
        self,
        before: FootstepsSnapshot,
        after: FootstepsSnapshot,
        *,
        final: bool,
    ) -> tuple[dict[str, bool], dict[str, str]]:
        old_objects = before.objects_by_role()
        new_objects = after.objects_by_role()
        old_media = before.media_by_role()
        new_media = after.media_by_role()
        inputs = before.inputs_by_key()
        assertions: dict[str, bool] = {}
        details: dict[str, str] = {}

        def record(name: str, passed: bool, failure: str) -> None:
            assertions[name] = bool(passed)
            details[name] = "ok" if passed else failure

        snow_objects = {
            role: new_objects.get(role) for role in _SNOW_ROLES
        }
        snow_media = {
            role: new_media.get(role) for role in _SNOW_SOUND_ROLES
        }
        old_ids = {
            row.object_id.casefold() for row in before.objects
        } | {
            row.active_source_id.casefold() for row in before.media
        }
        new_snow_ids = {
            row.object_id.casefold()
            for row in snow_objects.values()
            if row is not None
        } | {
            row.active_source_id.casefold()
            for row in snow_media.values()
            if row is not None
        }
        player = old_objects["player_footsteps"]
        snow_container = snow_objects["snow_container"]
        snow_hierarchy_ok = (
            all(row is not None for row in snow_objects.values())
            and all(role not in after.absent_roles for role in _SNOW_ROLES)
            and len(new_snow_ids) == 9
            and not (new_snow_ids & old_ids)
        )
        if snow_hierarchy_ok and snow_container is not None:
            snow_hierarchy_ok = (
                _identity(
                    snow_container.state.get("parent"),
                    "Snow container parent",
                ).casefold()
                == player.object_id.casefold()
                and self._child_id_set(after, "snow_container")
                == {
                    snow_objects[role].object_id.casefold()  # type: ignore[union-attr]
                    for role in _SNOW_SOUND_ROLES
                }
                and self._child_id_set(after, "player_footsteps")
                == {
                    old_objects[role].object_id.casefold()
                    for role in _BASELINE_CONTAINER_ROLES
                }
                | {snow_container.object_id.casefold()}
                and all(
                    _identity(
                        snow_objects[role].state.get("parent"),  # type: ignore[union-attr]
                        f"{role} parent",
                    ).casefold()
                    == snow_container.object_id.casefold()
                    for role in _SNOW_SOUND_ROLES
                )
            )
        record(
            "snow_hierarchy_created_once",
            snow_hierarchy_ok,
            "Snow hierarchy is absent, duplicated, reused an old GUID, or has the wrong parent/children",
        )

        media_ok = all(
            snow_media[role] is not None
            and snow_media[role].original.sha256 == inputs[role].sha256  # type: ignore[union-attr]
            and snow_media[role].language == "SFX"  # type: ignore[union-attr]
            and snow_objects[role] is not None
            and snow_media[role].sound_id.casefold()  # type: ignore[union-attr]
            == snow_objects[role].object_id.casefold()  # type: ignore[union-attr]
            for role in _SNOW_SOUND_ROLES
        )
        record(
            "snow_media_hashes_match_inputs",
            media_ok,
            "one or more Snow copied Originals or SFX languages differ from their inputs",
        )

        baseline_pairs = self._named_pairs(
            old_objects,
            (
                ("metal_container", "surface_metal"),
                ("wood_container", "surface_wood"),
                ("mud_container", "surface_mud"),
            ),
        )
        snow_pair: set[tuple[str, str]] = set()
        if snow_container is not None:
            snow_pair = {
                (
                    snow_container.object_id.casefold(),
                    old_objects["surface_snow"].object_id.casefold(),
                )
            }
        expected_pairs = (
            baseline_pairs
            - (
                self._named_pairs(
                    old_objects,
                    (("mud_container", "surface_mud"),),
                )
                if final
                else set()
            )
        ) | snow_pair
        actual_pairs = self._pair_key_set(after.assignments)
        record(
            "snow_assignment_present",
            bool(snow_pair)
            and snow_pair <= actual_pairs
            and actual_pairs == expected_pairs,
            "Snow pair is absent or the complete assignment table contains an unexpected delta",
        )
        mud_pair = self._named_pairs(
            old_objects,
            (("mud_container", "surface_mud"),),
        )
        record(
            "mud_assignment_absent",
            final and not (mud_pair & actual_pairs),
            "the exact Mud assignment remains after the removal transaction",
        )

        record(
            "mud_objects_and_value_preserved",
            all(
                role in new_objects and new_objects[role] == old_objects[role]
                for role in ("mud_container", "mud_sound", "surface_mud")
            )
            and new_media.get("mud_sound") == old_media["mud_sound"],
            "Mud container, Sound, media, or Switch value changed or disappeared",
        )
        metal_wood_pairs = self._named_pairs(
            old_objects,
            (
                ("metal_container", "surface_metal"),
                ("wood_container", "surface_wood"),
            ),
        )
        record(
            "metal_wood_assignments_unchanged",
            metal_wood_pairs <= actual_pairs
            and all(
                role in new_objects and new_objects[role] == old_objects[role]
                for role in (
                    "metal_container",
                    "metal_sound",
                    "surface_metal",
                    "wood_container",
                    "wood_sound",
                    "surface_wood",
                )
            ),
            "Metal or Wood assignment/object state changed",
        )
        record(
            "footstep_event_chain_unchanged",
            all(
                role in new_objects and new_objects[role] == old_objects[role]
                for role in (
                    "play_footsteps_event",
                    "play_footsteps_action",
                )
            ),
            "Play_Footsteps Event or Action identity/state changed",
        )
        record(
            "existing_footstep_content_unchanged",
            all(
                role in new_objects and new_objects[role] == old_objects[role]
                for role in (
                    *_BASELINE_CONTAINER_ROLES,
                    *_BASELINE_SOUND_ROLES,
                )
            )
            and all(
                new_media.get(role) == old_media[role]
                for role in _BASELINE_SOUND_ROLES
            )
            and all(
                role in new_objects and new_objects[role] == old_objects[role]
                for role in ("surface_group", *_SURFACE_VALUE_ROLES)
            )
            and _same_object_except_player_relationships(
                old_objects["player_footsteps"],
                new_objects.get("player_footsteps"),
            )
            and after.input_files == before.input_files,
            "existing containers, Sounds, media, Surface objects, inputs, or fixed Player fields changed",
        )
        record(
            "footsteps_bus_unchanged",
            new_objects.get("footsteps_bus") == old_objects["footsteps_bus"],
            "Footsteps Bus identity or state changed",
        )

        expected_steps = (
            tuple(step.name for step in self.protocol.steps)
            if self.protocol is not None
            else ()
        )
        record(
            "two_transaction_sequence_exact",
            final
            and self._checkpoint_verified
            and tuple(self.observed_steps) == expected_steps
            and self.observed_steps.count("tx01.execute") == 1
            and self.observed_steps.count("tx02.execute") == 1
            and self.observed_steps.count("tx01.verify") == 1
            and self.observed_steps.count("tx02.verify") == 1,
            "the intermediate oracle or exact two-transaction broker protocol was not fully observed",
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
            raise AssertionError("Footsteps assertion order drifted")
        return assertions, details

    def _require_active(self) -> FootstepsSnapshot:
        if self.before is None:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps runtime was not prepared"
            )
        if self._cleaned:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps inputs are already clean"
            )
        return self.before


def _validate_reviewed_inputs(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    baseline_manifest: BaselineManifest,
    direct_call: DirectWaapiCall,
) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise FootstepsIntegrationRuntimeError(
            f"Footsteps integration version is unsupported: {version!r}"
        )
    if not callable(direct_call):
        raise TypeError("direct_call must be callable")
    if (
        getattr(workflow, "id", None) != FOOTSTEPS_WORKFLOW_ID
        or getattr(scenario, "scenario_family", None)
        != FOOTSTEPS_WORKFLOW_ID
        or getattr(workflow.fixture, "adapter", None)
        != FOOTSTEPS_FIXTURE_ADAPTER
        or not isinstance(getattr(scenario, "fixture", None), Mapping)
        or scenario.fixture.get("adapter") != FOOTSTEPS_FIXTURE_ADAPTER
        or tuple(getattr(scenario, "versions", ())) != (version,)
    ):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps workflow, scenario, and adapter are not exactly bound"
        )
    if (
        not isinstance(baseline_manifest, BaselineManifest)
        or baseline_manifest.version != version
        or _SHA256_RE.fullmatch(str(baseline_manifest.digest)) is None
        or _SHA256_RE.fullmatch(
            str(baseline_manifest.project_file_sha256)
        )
        is None
        or _SHA256_RE.fullmatch(str(baseline_manifest.full_tree_sha256))
        is None
    ):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps baseline manifest/version are misbound"
        )
    if tuple(
        assertion.id for assertion in workflow.fixture.business_assertions
    ) != _EXPECTED_ASSERTION_IDS:
        raise FootstepsIntegrationRuntimeError(
            "Footsteps business assertion contract drifted"
        )
    if tuple(
        (row.operation, row.api, row.preview_turn, row.confirmation_turn)
        for row in workflow.transactions
    ) != (
        ("audio.import", IMPORT_API, 1, 2),
        (
            "switchContainer.removeAssignment",
            REMOVE_ASSIGNMENT_API,
            2,
            3,
        ),
    ):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps transaction topology drifted"
        )
    if tuple(
        (row.key, row.file_name, row.duration_ms, row.frequency_hz)
        for row in workflow.fixture.source_files
    ) != (
        ("snow_step_01", "snow_step_01.wav", 317, 293),
        ("snow_step_02", "snow_step_02.wav", 359, 367),
        ("snow_step_03", "snow_step_03.wav", 401, 439),
        ("snow_step_04", "snow_step_04.wav", 443, 521),
    ):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps source specification drifted"
        )
    specs = {str(row.role): row for row in workflow.fixture.object_graph}
    expected_roles = set(FOOTSTEPS_CANONICAL_STATE_FIELDS) | set(_SNOW_ROLES)
    if set(specs) != expected_roles:
        raise FootstepsIntegrationRuntimeError(
            "Footsteps object graph coverage drifted"
        )
    if {
        role for role, spec in specs.items() if spec.baseline_state == "absent"
    } != set(_SNOW_ROLES):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps baseline presence contract drifted"
        )


def _validated_runtime_paths(runtime: FootstepsRuntimePaths) -> _RuntimePaths:
    directories: dict[str, Path] = {}
    for name in ("scenario_root", "asset_root", "io_root"):
        raw = getattr(runtime, name, None)
        if raw is None:
            raise FootstepsIntegrationRuntimeError(
                f"Footsteps runtime paths omit {name}"
            )
        path = Path(os.path.abspath(os.fspath(Path(raw).expanduser())))
        _real_directory(path, name)
        directories[name] = path
    scenario_root = directories["scenario_root"]
    for name in ("asset_root", "io_root"):
        path = directories[name]
        if path == scenario_root or scenario_root not in path.parents:
            raise FootstepsIntegrationRuntimeError(
                f"{name} must be a strict descendant of scenario_root"
            )
    sandbox = getattr(runtime, "sandbox", None)
    if sandbox is None:
        raise FootstepsIntegrationRuntimeError(
            "Footsteps runtime omits its sandbox"
        )
    file_values: dict[str, Path] = {}
    for name in ("sandbox_project", "source_project"):
        value = getattr(sandbox, name, None)
        if value is None:
            raise FootstepsIntegrationRuntimeError(f"sandbox omits {name}")
        path = _real_file(Path(value), name)
        if path.suffix.casefold() != ".wproj":
            raise FootstepsIntegrationRuntimeError(
                f"{name} must be a .wproj file"
            )
        file_values[name] = path
    sandbox_project = file_values["sandbox_project"]
    source_project = file_values["source_project"]
    source_value = getattr(sandbox, "source_root", None)
    if source_value is None:
        raise FootstepsIntegrationRuntimeError("sandbox omits source_root")
    source_root = _real_directory(Path(source_value), "source_root")
    sandbox_value = getattr(sandbox, "sandbox_path", None)
    sandbox_root = _real_directory(
        (
            Path(sandbox_value)
            if sandbox_value is not None
            else sandbox_project.parent
        ),
        "sandbox project root",
    )
    if sandbox_root not in sandbox_project.parents:
        raise FootstepsIntegrationRuntimeError(
            "sandbox project is outside its copied project root"
        )
    if scenario_root not in sandbox_project.parents:
        raise FootstepsIntegrationRuntimeError(
            "sandbox project is outside the scenario-owned root"
        )
    if source_root not in source_project.parents:
        raise FootstepsIntegrationRuntimeError(
            "source project is outside its source root"
        )
    if source_project == sandbox_project or source_root == sandbox_root:
        raise FootstepsIntegrationRuntimeError(
            "source and copied Footsteps projects are not isolated"
        )
    return _RuntimePaths(
        scenario_root=scenario_root,
        asset_root=directories["asset_root"],
        io_root=directories["io_root"],
        sandbox_project=sandbox_project,
        sandbox_root=sandbox_root,
        source_project=source_project,
        source_root=source_root,
    )


def _footsteps_manifest_objects(
    manifest: BaselineManifest,
    specs: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest.objects:
        if not isinstance(raw, Mapping):
            raise FootstepsIntegrationRuntimeError(
                "baseline manifest contains a non-object row"
            )
        role = raw.get("role")
        if role not in specs:
            continue
        role = str(role)
        if role in result:
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest repeats Footsteps role {role}"
            )
        spec = specs[role]
        if spec.baseline_state != "present":
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest contains absent Footsteps role {role}"
            )
        state = raw.get("state")
        if (
            raw.get("path") != spec.path_for(manifest.version)
            or _type_token(raw.get("type")) != _type_token(spec.type)
            or _GUID_RE.fullmatch(str(raw.get("id"))) is None
            or not isinstance(state, Mapping)
            or _SHA256_RE.fullmatch(str(raw.get("state_sha256"))) is None
        ):
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest Footsteps role {role} is malformed"
            )
        if hashlib.sha256(canonical_json_bytes(state)).hexdigest() != raw.get(
            "state_sha256"
        ):
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest Footsteps role {role} state digest drifted"
            )
        canonical = _canonical_manifest_state(role, state)
        if _plain(state) != canonical:
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest Footsteps role {role} state is not canonical"
            )
        result[role] = MappingProxyType(dict(raw))
    expected = {
        role for role, spec in specs.items() if spec.baseline_state == "present"
    }
    if set(result) != expected:
        raise FootstepsIntegrationRuntimeError(
            "baseline manifest Footsteps object coverage drifted"
        )
    if len({str(row["id"]).casefold() for row in result.values()}) != len(
        result
    ):
        raise FootstepsIntegrationRuntimeError(
            "baseline manifest Footsteps GUIDs are not unique"
        )
    return result


def _footsteps_manifest_media(
    manifest: BaselineManifest,
    specs: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    sound_roles = {
        role
        for role, spec in specs.items()
        if spec.baseline_state == "present"
        and _type_token(spec.type) == "sound"
    }
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest.media:
        if not isinstance(raw, Mapping) or raw.get("role") not in sound_roles:
            continue
        role = str(raw["role"])
        if role in result:
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest repeats Footsteps media role {role}"
            )
        relative = raw.get("relative_path")
        if (
            _GUID_RE.fullmatch(str(raw.get("active_source_id"))) is None
            or not isinstance(relative, str)
            or not _safe_original_relative(relative)
            or _SHA256_RE.fullmatch(str(raw.get("sha256"))) is None
        ):
            raise FootstepsIntegrationRuntimeError(
                f"baseline manifest Footsteps media role {role} is malformed"
            )
        result[role] = MappingProxyType(dict(raw))
    if set(result) != sound_roles:
        raise FootstepsIntegrationRuntimeError(
            "baseline manifest Footsteps media coverage drifted"
        )
    if len(
        {
            str(row["active_source_id"]).casefold()
            for row in result.values()
        }
    ) != len(result):
        raise FootstepsIntegrationRuntimeError(
            "baseline manifest Footsteps AudioSource GUIDs are not unique"
        )
    return result


def _canonical_manifest_state(
    role: str,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        fields = FOOTSTEPS_CANONICAL_STATE_FIELDS[role]
    except KeyError as exc:
        raise FootstepsIntegrationRuntimeError(
            f"manifest role has no Footsteps state contract: {role}"
        ) from exc
    if set(state) != set(fields):
        raise FootstepsIntegrationRuntimeError(
            f"manifest role {role} state keys are not closed"
        )
    result: dict[str, Any] = {}
    for field in fields:
        value = state[field]
        if field in {
            "parent",
            "SwitchGroupOrStateGroup",
            "activeSource",
            "Target",
        }:
            result[field] = _reference(value, f"manifest {role} {field}")
        elif field == "OutputBus":
            result[field] = _optional_reference(value)
        elif field == "children":
            if (
                not isinstance(value, list)
                or len(value) > _MAX_OBJECT_ROWS
                or any(
                    not isinstance(row, Mapping) or set(row) != {"id"}
                    for row in value
                )
            ):
                raise FootstepsIntegrationRuntimeError(
                    f"manifest {role} children are malformed or unbounded"
                )
            ids = sorted(
                (_identity(row, f"manifest {role} child") for row in value),
                key=str.casefold,
            )
            if len({item.casefold() for item in ids}) != len(ids):
                raise FootstepsIntegrationRuntimeError(
                    f"manifest {role} children contain duplicates"
                )
            result[field] = [{"id": item} for item in ids]
        elif field == "assignment_pairs":
            if (
                not isinstance(value, list)
                or len(value) > _MAX_ASSIGNMENT_ROWS
                or any(
                    not isinstance(row, Mapping)
                    or set(row) != {"child", "stateOrSwitch"}
                    for row in value
                )
            ):
                raise FootstepsIntegrationRuntimeError(
                    "manifest Player_Footsteps assignments are malformed or unbounded"
                )
            pairs = sorted(
                (
                    {
                        "child": _guid(
                            row["child"], "manifest assignment child"
                        ),
                        "stateOrSwitch": _guid(
                            row["stateOrSwitch"],
                            "manifest assignment stateOrSwitch",
                        ),
                    }
                    for row in value
                ),
                key=lambda row: (
                    row["child"].casefold(),
                    row["stateOrSwitch"].casefold(),
                ),
            )
            if len(
                {
                    (row["child"].casefold(), row["stateOrSwitch"].casefold())
                    for row in pairs
                }
            ) != len(pairs):
                raise FootstepsIntegrationRuntimeError(
                    "manifest Player_Footsteps assignments contain duplicates"
                )
            result[field] = pairs
        elif field == "ActionType":
            result[field] = _integer(value, f"manifest {role} ActionType")
        elif field == "@Volume":
            result[field] = _number(value, f"manifest {role} Volume")
        else:  # pragma: no cover - field table is closed
            raise FootstepsIntegrationRuntimeError(
                f"unsupported manifest state field: {role}.{field}"
            )
    return result


def _validate_manifest_object_state(
    state: FootstepsObjectState,
    manifest_row: Mapping[str, Any],
) -> None:
    if (
        state.object_id.casefold() != str(manifest_row["id"]).casefold()
        or state.path != manifest_row["path"]
        or _type_token(state.object_type) != _type_token(manifest_row["type"])
        or _plain(state.state) != _plain(manifest_row["state"])
        or hashlib.sha256(
            canonical_json_bytes(_plain(state.state))
        ).hexdigest()
        != manifest_row["state_sha256"]
    ):
        raise FootstepsIntegrationRuntimeError(
            f"live copied Footsteps object differs from manifest role {state.role}"
        )


def _validate_manifest_media(
    state: FootstepsMediaState,
    manifest_row: Mapping[str, Any],
) -> None:
    if (
        state.active_source_id.casefold()
        != str(manifest_row["active_source_id"]).casefold()
        or state.original.relative_path != manifest_row["relative_path"]
        or state.original.sha256 != manifest_row["sha256"]
        or state.language != "SFX"
    ):
        raise FootstepsIntegrationRuntimeError(
            f"live copied Footsteps media differs from manifest role {state.role}"
        )


def _same_object_except_player_relationships(
    before: FootstepsObjectState,
    after: FootstepsObjectState | None,
) -> bool:
    if after is None:
        return False
    if (
        before.role != after.role
        or before.object_id.casefold() != after.object_id.casefold()
        or before.name != after.name
        or before.object_type != after.object_type
        or before.path != after.path
    ):
        return False
    mutable = {"children", "assignment_pairs"}
    return {
        key: _plain(value)
        for key, value in before.state.items()
        if key not in mutable
    } == {
        key: _plain(value)
        for key, value in after.state.items()
        if key not in mutable
    }


def _oracle_requirements() -> tuple[FootstepsOracleRequirement, ...]:
    return (
        FootstepsOracleRequirement(
            "tx01",
            _freeze_mapping(
                {
                    "kind": "footsteps.snow-import-delta/v1",
                    "operation": "audio.import",
                    "before": {
                        "baseline_manifest_bound": True,
                        "snow_roles_absent": _SNOW_ROLES,
                        "existing_graph_and_media_exact": True,
                    },
                    "preview": {"snapshot": "unchanged"},
                    "checkpoint": {
                        "assertion_ids": _TX01_CHECKPOINT_ASSERTION_IDS,
                        "snow_hierarchy": "one container and four SFX Sounds",
                        "snow_assignment": "present",
                        "mud_assignment": "still_present",
                    },
                }
            ),
        ),
        FootstepsOracleRequirement(
            "tx02",
            _freeze_mapping(
                {
                    "kind": "footsteps.mud-assignment-removal-delta/v1",
                    "operation": "switchContainer.removeAssignment",
                    "precondition": {
                        "transaction_id": "tx01",
                        "checkpoint": "verified",
                    },
                    "final": {
                        "assertion_ids": _TX02_FINAL_ASSERTION_IDS,
                        "removed_pair": {
                            "child_role": "mud_container",
                            "state_or_switch_role": "surface_mud",
                        },
                        "preserve": "the complete verified tx01 checkpoint",
                    },
                    "protocol": {
                        "ordered_transactions": ("tx01", "tx02"),
                        "broker_steps": 12,
                        "execute_count_per_transaction": 1,
                        "delete_dispatch_count": 0,
                    },
                    "cleanup": {
                        "owned_input_tree": "removed",
                        "sandbox_project": "lifecycle_owned",
                        "source_project": "unchanged",
                    },
                }
            ),
        ),
    )


def _fresh_owned_directory(root: Path, relative: str) -> Path:
    try:
        parsed_relative = parse_archive_relative_path(relative)
    except ArchiveRelativePathError as exc:
        raise FootstepsIntegrationRuntimeError(
            "Footsteps input relative path is unsafe"
        ) from exc
    candidate = root.joinpath(*parsed_relative.parts)
    if candidate.exists() or candidate.is_symlink():
        raise FootstepsIntegrationRuntimeError(
            f"Footsteps input root is not fresh: {candidate}"
        )
    current = root
    for part in parsed_relative.parts:
        current /= part
        current.mkdir(exist_ok=False)
        _real_directory(current, "Footsteps input directory")
    if root not in candidate.parents:
        raise FootstepsIntegrationRuntimeError(
            "Footsteps input root escaped asset_root"
        )
    return candidate


def _binding_object_path(value: Any, version: str) -> str:
    if not isinstance(value, Mapping):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps object-path binding is malformed"
        )
    if value.get("source") == "literal" and set(value) == {
        "source",
        "value",
    }:
        return _wwise_path(value.get("value"), "literal binding")
    values = value.get("values")
    if (
        value.get("source") == "version_literal"
        and set(value) == {"source", "values"}
        and isinstance(values, Mapping)
        and version in values
    ):
        return _wwise_path(values[version], "version binding")
    raise FootstepsIntegrationRuntimeError(
        "Footsteps object-path binding does not cover this version"
    )


def _remove_owned_input_tree(
    path: Path,
    *,
    stop: Path,
    expected_names: set[str],
) -> None:
    candidate = Path(path)
    if stop not in candidate.parents:
        raise FootstepsIntegrationRuntimeError(
            "Footsteps cleanup path escaped asset_root"
        )
    if candidate.is_symlink():
        raise FootstepsIntegrationRuntimeError(
            "Footsteps input root became a symlink"
        )
    if candidate.exists():
        _real_directory(candidate, "Footsteps input root")
        actual_names = {child.name for child in candidate.iterdir()}
        if actual_names != expected_names:
            raise FootstepsIntegrationRuntimeError(
                "Footsteps input root contains an unexpected entry"
            )
        for child in candidate.iterdir():
            metadata = os.lstat(child)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
                metadata.st_mode
            ):
                raise FootstepsIntegrationRuntimeError(
                    f"unexpected Footsteps input entry: {child}"
                )
            child.unlink()
        candidate.rmdir()
    parent = candidate.parent
    while parent != stop and stop in parent.parents:
        if parent.is_symlink():
            raise FootstepsIntegrationRuntimeError(
                "Footsteps input ancestor became a symlink"
            )
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _write_deterministic_wav(
    path: Path,
    *,
    duration_ms: int,
    frequency_hz: int,
) -> None:
    if (
        type(duration_ms) is not int
        or type(frequency_hz) is not int
        or not 1 <= duration_ms <= 10_000
        or not 20 <= frequency_hz <= 20_000
    ):
        raise FootstepsIntegrationRuntimeError(
            "Footsteps WAV specification is outside the closed bounds"
        )
    if path.exists() or path.is_symlink():
        raise FootstepsIntegrationRuntimeError(
            f"Footsteps WAV path is not fresh: {path}"
        )
    sample_rate = 48_000
    frame_count = max(1, sample_rate * duration_ms // 1000)
    frames = bytearray()
    for index in range(frame_count):
        value = int(
            math.sin(2.0 * math.pi * frequency_hz * index / sample_rate)
            * 8191
        )
        frames.extend(struct.pack("<h", value))
    with path.open("xb") as raw:
        with wave.open(raw, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(bytes(frames))
    _regular_file_proof(path, relative_to=path.parent)


def _copied_original_proof(
    value: Any,
    *,
    sandbox_root: Path,
    account_home: Path | None = None,
) -> FootstepsFileProof:
    try:
        candidate = localize_copied_original_path(
            value,
            account_home=account_home,
        )
    except IntegrationOriginalPathError as exc:
        raise FootstepsIntegrationRuntimeError(str(exc)) from exc
    root = sandbox_root.resolve(strict=True)
    originals = root / "Originals"
    _real_directory(originals, "copied Originals root")
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise FootstepsIntegrationRuntimeError(
            f"copied Original escapes the sandbox: {candidate}"
        ) from exc
    if (
        not lexical_relative.parts
        or Path(lexical_relative.parts[0]) != Path("Originals")
    ):
        raise FootstepsIntegrationRuntimeError(
            f"copied Original is outside sandbox Originals: {candidate}"
        )
    current = root
    for part in lexical_relative.parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise FootstepsIntegrationRuntimeError(
                f"copied Original path is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise FootstepsIntegrationRuntimeError(
                f"copied Original path contains a symlink: {current}"
            )
    resolved = candidate.resolve(strict=True)
    try:
        resolved_relative = resolved.relative_to(root)
    except ValueError as exc:
        raise FootstepsIntegrationRuntimeError(
            "copied Original resolves outside the sandbox"
        ) from exc
    if Path(*resolved_relative.parts) != Path(*lexical_relative.parts):
        raise FootstepsIntegrationRuntimeError(
            "copied Original changed during containment proof"
        )
    return _regular_file_proof(resolved, relative_to=root)


def _regular_file_proof(
    value: Path,
    *,
    relative_to: Path | None,
) -> FootstepsFileProof:
    path = _real_file(Path(value), "sealed file")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns"):
        if getattr(before, field) != getattr(after, field):
            raise FootstepsIntegrationRuntimeError(
                f"file changed while being sealed: {path}"
            )
    relative: str | None = None
    if relative_to is not None:
        root = Path(relative_to).resolve(strict=True)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise FootstepsIntegrationRuntimeError(
                f"sealed file escapes its root: {path}"
            ) from exc
    return FootstepsFileProof(
        path=str(path),
        relative_path=relative,
        size=before.st_size,
        sha256=digest.hexdigest(),
    )


def _source_project_proof(
    project: Path,
    root: Path,
) -> FootstepsSourceProjectProof:
    project_proof = _regular_file_proof(project, relative_to=root)
    return FootstepsSourceProjectProof(
        project_sha256=project_proof.sha256,
        tree_sha256=wwise_fixture_tree_sha256(root),
        project_mtime_ns=project.stat().st_mtime_ns,
    )


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    metadata = _real_file(path, "project file").stat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _real_directory(path: Path, label: str) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise FootstepsIntegrationRuntimeError(
            f"{label} cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise FootstepsIntegrationRuntimeError(
            f"{label} must be a real directory"
        )
    return candidate.resolve(strict=True)


def _real_file(path: Path, label: str) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise FootstepsIntegrationRuntimeError(
            f"{label} cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FootstepsIntegrationRuntimeError(f"{label} must be a real file")
    return candidate.resolve(strict=True)


def _safe_file_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != Path(value).name
        or not value.casefold().endswith(".wav")
    ):
        raise FootstepsIntegrationRuntimeError(
            f"unsafe Footsteps WAV file name: {value!r}"
        )
    return value


def _safe_original_relative(value: str) -> bool:
    try:
        path = parse_archive_relative_path(value)
    except ArchiveRelativePathError:
        return False
    return (
        len(path.parts) >= 2
        and path.parts[0] == "Originals"
    )


def _one_row(
    rows: Sequence[Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    if len(rows) != 1:
        raise FootstepsIntegrationRuntimeError(
            f"{label} did not resolve exactly once"
        )
    return rows[0]


def _return_fields(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or any(ord(character) < 32 for character in value)
        ):
            raise FootstepsIntegrationRuntimeError(
                f"invalid object.get return field: {value!r}"
            )
        if value not in result:
            result.append(value)
    if not result or len(result) > 64:
        raise FootstepsIntegrationRuntimeError(
            "object.get return projection is empty or unbounded"
        )
    return tuple(result)


def _guid(value: Any, label: str) -> str:
    if not isinstance(value, str) or _GUID_RE.fullmatch(value) is None:
        raise FootstepsIntegrationRuntimeError(
            f"{label} must be one canonical GUID"
        )
    return value.upper()


def _identity(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        for key in ("id", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and _GUID_RE.fullmatch(candidate):
                return _guid(candidate, label)
    return _guid(value, label)


def _reference(value: Any, label: str) -> dict[str, str]:
    return {"id": _identity(value, label)}


def _optional_reference(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    return {"id": _identity(value, "optional reference")}


def _wwise_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("\\")
        or value != value.strip()
        or "\x00" in value
        or len(value) > 4096
    ):
        raise FootstepsIntegrationRuntimeError(
            f"{label} must be one absolute Wwise path"
        )
    return value


def _text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise FootstepsIntegrationRuntimeError(
            f"{label} must be non-empty text"
        )
    return value


def _type_token(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise FootstepsIntegrationRuntimeError(
            "Wwise object type must be non-empty text"
        )
    return "".join(character for character in value.casefold() if character.isalnum())


def _name_value(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("name")
    if not isinstance(value, str) or "\x00" in value:
        raise FootstepsIntegrationRuntimeError(
            f"{label} must expose one text name"
        )
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FootstepsIntegrationRuntimeError(
            f"{label} must be one integer"
        )
    return value


def _number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
    ):
        raise FootstepsIntegrationRuntimeError(
            f"{label} must be one finite number"
        )
    return float(value)


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {str(key): _freeze(value[key]) for key in value}
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "FOOTSTEPS_CANONICAL_STATE_FIELDS",
    "FOOTSTEPS_FIXTURE_ADAPTER",
    "FOOTSTEPS_WORKFLOW_ID",
    "GET_ASSIGNMENTS_API",
    "IMPORT_API",
    "REMOVE_ASSIGNMENT_API",
    "FootstepsAssignmentPair",
    "FootstepsChildState",
    "FootstepsCleanupProof",
    "FootstepsExpectedDispatch",
    "FootstepsFileProof",
    "FootstepsIntegrationRuntimeError",
    "FootstepsMediaState",
    "FootstepsObjectState",
    "FootstepsOracleRequirement",
    "FootstepsRuntimePaths",
    "FootstepsSnapshot",
    "FootstepsSourceProjectProof",
    "FootstepsVerification",
    "PreparedFootstepsIntegrationRuntime",
    "prepare_footsteps_integration_runtime",
]

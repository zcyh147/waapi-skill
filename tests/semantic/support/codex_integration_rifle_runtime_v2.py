"""Trusted runtime adapter for the v2 committed-baseline Rifle workflow.

The workflow starts from a version-pinned SampleProject graph.  This adapter
therefore performs no project setup and owns no Wwise object cleanup.  It
validates the copied live graph against the sealed baseline manifest, writes
only the four case-owned incoming WAV files, builds one metadata-bound
``audio.import`` transaction, and evaluates the final business state through a
private direct-WAAPI readback.

Only ``visible_values`` and the broker protocol are model-facing.  Baseline
GUIDs, manifest state, copied Originals paths, media hashes, RTPC rows, source
project proofs, and direct WAAPI access remain runner-owned.
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
    build_audio_import_composer_transaction_steps,
    metadata_candidate_limit,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftActionMetadataBinding,
    ExpectedGatewayStep,
    MetadataQueryArgument,
    gateway_step_prefix_matches,
    gateway_step_sequence_matches,
    project_required_metadata_tokens,
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
from wwise_waapi.builders.metadata import (
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
)
from wwise_waapi.metadata_discovery import discover_metadata


RIFLE_WORKFLOW_ID = "rifle_safe_reimport"
RIFLE_FIXTURE_ADAPTER = "rifle_committed_baseline_fixture_v2"
SUPPORTED_VERSIONS = frozenset({"2022.1", "2025.1"})
OBJECT_GET_API = "ak.wwise.core.object.get"
IMPORT_API = "ak.wwise.core.audio.import"
METADATA_QUERIES = ("volume", "output bus")
METADATA_TOKENS = ("Volume", "OutputBus")
RIFLE_COMMUTATIVE_READ_ONLY_STEP_GROUPS = (
    ("tx01.operation-schema", "metadata.discover"),
)
RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS = (
    (
        "metadata.discover",
        "tx01.draft-start",
        "tx01.action.001",
    ),
)

_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_OBJECT_ROWS = 64
_MAX_RTPC_ROWS = 32
_RTPC_SNAPSHOT_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "notes",
    "@PropertyName",
    "@ControlInput",
    "@Curve",
)
_NEW_SOUND_STATE_FIELDS = (
    "parent",
    "notes",
    "@Volume",
    "@Pitch",
    "@IsLoopingEnabled",
    "@UseMaxSoundPerInstance",
    "@MaxSoundPerInstance",
    "OutputBus",
    "activeSource",
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
_EXPECTED_ASSERTION_IDS = (
    "existing_sound_guids_preserved",
    "existing_active_sources_bound_to_sounds",
    "updated_media_hashes_match_inputs",
    "distant_created_once_with_new_guid",
    "distant_media_hash_matches_input",
    "rifle_container_child_set_exact",
    "play_event_chain_unchanged",
    "sound_design_state_unchanged",
    "distractors_unchanged",
    "single_import_transaction",
    "source_project_unchanged",
)
_EXISTING_SOUND_ROLES = (
    "rifle_close",
    "rifle_tail",
    "rifle_mechanical",
)
_DISTRACTOR_ROLES = (
    "rifle_close_backup",
    "rifle_tails_distractor",
)
_PROTECTED_GRAPH_ROLES = (
    "play_rifle_event",
    "play_rifle_action",
)
_ACTION_EVENT_ROLE = "play_rifle_event"
_ACTION_ROLE = "play_rifle_action"
RIFLE_CANONICAL_STATE_FIELDS: Mapping[str, tuple[str, ...]] = (
    MappingProxyType(
        {
            "rifle_container": ("parent", "children"),
            "rifle_close": (
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
            ),
            "rifle_tail": (
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
            ),
            "rifle_mechanical": (
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
            ),
            "rifle_close_backup": (
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
            ),
            "rifle_tails_distractor": (
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
            ),
            "play_rifle_event": ("parent", "children"),
            "play_rifle_action": ("parent", "ActionType", "Target"),
            "weapons_bus": ("parent", "@Volume"),
            "rifle_distance_parameter": ("parent",),
        }
    )
)
_METADATA_URIS = frozenset(
    {
        GET_TYPES_URI,
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    }
)


class RifleIntegrationRuntimeError(RuntimeError):
    """The committed Rifle fixture, protocol, or oracle failed closed."""


DirectWaapiCall = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Any
]


class RifleRuntimePaths(Protocol):
    """Subset supplied by the existing per-scenario lifecycle."""

    scenario_root: Path
    asset_root: Path
    io_root: Path
    sandbox: Any


@dataclass(frozen=True, slots=True)
class RifleFileProof:
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
class RifleObjectState:
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
class RifleMediaState:
    role: str
    sound_id: str
    active_source_id: str
    source_parent_id: str
    language: str
    original: RifleFileProof

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
class RifleChildState:
    object_id: str
    name: str
    path: str
    object_type: str
    parent_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.object_id,
            "name": self.name,
            "path": self.path,
            "type": self.object_type,
            "parent_id": self.parent_id,
        }


@dataclass(frozen=True, slots=True)
class RifleSourceProjectProof:
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
class RifleSnapshot:
    workflow_id: str
    version: str
    objects: tuple[RifleObjectState, ...]
    absent_roles: tuple[str, ...]
    media: tuple[RifleMediaState, ...]
    container_children: tuple[RifleChildState, ...]
    input_files: tuple[tuple[str, RifleFileProof], ...]
    source_project: RifleSourceProjectProof
    digest: str

    def objects_by_role(self) -> dict[str, RifleObjectState]:
        return {row.role: row for row in self.objects}

    def media_by_role(self) -> dict[str, RifleMediaState]:
        return {row.role: row for row in self.media}

    def inputs_by_key(self) -> dict[str, RifleFileProof]:
        return dict(self.input_files)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "objects": [row.as_dict() for row in self.objects],
            "absent_roles": list(self.absent_roles),
            "media": [row.as_dict() for row in self.media],
            "container_children": [
                row.as_dict() for row in self.container_children
            ],
            "input_files": [
                {"key": key, **proof.as_dict()}
                for key, proof in self.input_files
            ],
            "source_project": self.source_project.as_dict(),
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class RifleVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    assertions: Mapping[str, bool]
    before: RifleSnapshot
    after: RifleSnapshot | None

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
            raise RifleIntegrationRuntimeError(
                f"{self.phase} failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class RifleCleanupProof:
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
            raise RifleIntegrationRuntimeError(
                "Rifle input cleanup failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class RifleExpectedDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class RifleOracleRequirement:
    phase: str
    subject: str
    expectation: str


@dataclass(frozen=True, slots=True)
class PreparedRifleIntegrationRuntime:
    """Frozen runner seam; callback fields must never enter model input."""

    workflow_id: str
    version: str
    visible_values: Mapping[str, str]
    protocol: V3GatewayProtocol
    snapshot: Callable[[], RifleSnapshot]
    before_snapshot: RifleSnapshot
    verify_turn: Callable[[int, Any | None], RifleVerification]
    verify_final: Callable[
        [Mapping[str, Any] | None, Any | None], RifleVerification
    ]
    cleanup: Callable[[], RifleCleanupProof]
    observe_payload: Callable[
        [ExpectedGatewayStep, Mapping[str, Any]], None
    ]
    expected_dispatches: tuple[RifleExpectedDispatch, ...]
    oracle_requirements: tuple[RifleOracleRequirement, ...]
    operation_request: Mapping[str, Any]
    prompt_sources: Mapping[str, Any]


def prepare_rifle_integration_runtime(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    runtime: RifleRuntimePaths,
    baseline_manifest: BaselineManifest,
    direct_call: DirectWaapiCall,
) -> PreparedRifleIntegrationRuntime:
    """Validate one committed Rifle copy and prepare its two-turn runtime."""

    _validate_reviewed_inputs(
        workflow,
        scenario,
        version=version,
        baseline_manifest=baseline_manifest,
        direct_call=direct_call,
    )
    paths = _validated_runtime_paths(runtime)
    backend = _ClosedRifleBackend(direct_call)
    session = _RifleSession(
        workflow=workflow,
        version=version,
        runtime_paths=paths,
        baseline_manifest=baseline_manifest,
        backend=backend,
    )
    try:
        before, visible_values, operation_request, metadata_result = (
            session.prepare()
        )
        projection = project_required_metadata_tokens(
            metadata_result,
            object_type="Sound",
            required_tokens=METADATA_TOKENS,
        )
        metadata_arguments: list[Any] = [
            "discover",
            "--object-type",
            "Sound",
        ]
        for query in METADATA_QUERIES:
            metadata_arguments.extend(("--query", MetadataQueryArgument(query)))
        metadata_arguments.extend(
            ("--limit", str(metadata_candidate_limit(METADATA_QUERIES)))
        )
        metadata_step = ExpectedGatewayStep(
            name="metadata.discover",
            subcommand="metadata",
            arguments=tuple(metadata_arguments),
        )
        composer_steps = build_audio_import_composer_transaction_steps(
            operation_request,
            label="tx01",
            metadata_binding=DraftActionMetadataBinding(
                step=metadata_step.name,
                object_type="Sound",
                required_tokens=METADATA_TOKENS,
                expected_projection=projection,
            ),
        )
        steps = (
            composer_steps[0],
            metadata_step,
            *composer_steps[1:],
        )
        protocol = V3GatewayProtocol(
            steps=steps,
            turn_prefix_counts=(
                next(
                    index
                    for index, step in enumerate(steps, start=1)
                    if step.name == "tx01.preview"
                ),
                len(steps),
            ),
            commutative_read_only_step_groups=(
                RIFLE_COMMUTATIVE_READ_ONLY_STEP_GROUPS
            ),
            commutative_composer_setup_step_groups=(
                RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS
            ),
        )
        session.bind_protocol(protocol)
    except BaseException:
        session.cleanup_failed_prepare()
        raise
    return PreparedRifleIntegrationRuntime(
        workflow_id=RIFLE_WORKFLOW_ID,
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
            RifleExpectedDispatch(
                IMPORT_API,
                1,
                "reuse three exact Rifle Sounds and create only Rifle_Distant "
                "in one useExisting import batch",
            ),
        ),
        oracle_requirements=_oracle_requirements(),
        operation_request=_freeze_mapping(operation_request),
        prompt_sources=MappingProxyType(
            {
                "rifle_input_files": {
                    key: proof.as_dict()
                    for key, proof in before.input_files
                }
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class _RuntimePaths:
    scenario_root: Path
    asset_root: Path
    io_root: Path
    sandbox_project: Path
    sandbox_root: Path
    source_project: Path
    source_root: Path


class _ClosedRifleBackend:
    """Bounded runner-only reads; no mutation or generic public method."""

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

    def read_ids(
        self,
        object_ids: Sequence[str],
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        values = tuple(_guid(value, "object id") for value in object_ids)
        if not values or len(values) > _MAX_RTPC_ROWS:
            raise RifleIntegrationRuntimeError(
                "RTPC identity batch is empty or unbounded"
            )
        return self._read(
            {"from": {"id": list(values)}},
            fields,
            "object.get ids",
        )

    def read_children(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {
                "from": {"id": [_guid(object_id, "parent id")]},
                "transform": [{"select": ["children"]}],
            },
            fields,
            "object.get children",
        )

    def read_metadata(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if uri not in _METADATA_URIS:
            raise RifleIntegrationRuntimeError(
                f"unapproved Rifle metadata URI: {uri}"
            )
        result = self.__call(uri, dict(args), dict(options))
        if not isinstance(result, Mapping):
            raise RifleIntegrationRuntimeError(
                f"{uri} returned no metadata object"
            )
        return dict(result)

    def read_rtpcs(self, object_id: str) -> tuple[Mapping[str, Any], ...]:
        owner = _one_row(
            self.read_id(object_id, fields=("id", "@RTPC")),
            "RTPC owner",
        )
        raw_references = owner.get("@RTPC", [])
        if raw_references is None:
            raw_references = []
        if (
            not isinstance(raw_references, list)
            or len(raw_references) > _MAX_RTPC_ROWS
        ):
            raise RifleIntegrationRuntimeError(
                "RTPC owner returned malformed or unbounded references"
            )
        ids: list[str] = []
        for index, value in enumerate(raw_references):
            try:
                ids.append(_identity(value, f"RTPC reference {index}"))
            except RifleIntegrationRuntimeError as exc:
                raise RifleIntegrationRuntimeError(
                    "RTPC owner returned an invalid reference"
                ) from exc
        if len({value.casefold() for value in ids}) != len(ids):
            raise RifleIntegrationRuntimeError(
                "RTPC owner returned duplicate references"
            )
        if not ids:
            return ()
        rows = self.read_ids(ids, fields=_RTPC_SNAPSHOT_FIELDS)
        by_id: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            row_id = _guid(row.get("id"), "RTPC detail id")
            key = row_id.casefold()
            if key in by_id or _type_token(row.get("type")) != "rtpc":
                raise RifleIntegrationRuntimeError(
                    "RTPC detail rows are duplicated or have the wrong type"
                )
            if any(field not in row for field in _RTPC_SNAPSHOT_FIELDS):
                raise RifleIntegrationRuntimeError(
                    "RTPC detail row omitted a sealed field"
                )
            by_id[key] = MappingProxyType(
                _normalize_rtpc_row(row)
            )
        if set(by_id) != {value.casefold() for value in ids}:
            raise RifleIntegrationRuntimeError(
                "RTPC detail readback differs from the owner reference list"
            )
        return tuple(by_id[value.casefold()] for value in ids)

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
            raise RifleIntegrationRuntimeError(f"{label} result is not an object")
        rows = result.get("return")
        if (
            not isinstance(rows, list)
            or len(rows) > _MAX_OBJECT_ROWS
            or any(not isinstance(row, Mapping) for row in rows)
        ):
            raise RifleIntegrationRuntimeError(
                f"{label} rows are malformed or unbounded"
            )
        return tuple(MappingProxyType(dict(row)) for row in rows)


class _RifleSession:
    def __init__(
        self,
        *,
        workflow: Any,
        version: str,
        runtime_paths: _RuntimePaths,
        baseline_manifest: BaselineManifest,
        backend: _ClosedRifleBackend,
    ) -> None:
        self.workflow = workflow
        self.version = version
        self.paths = runtime_paths
        self.manifest = baseline_manifest
        self.backend = backend
        self.specs = {
            str(row.role): row for row in workflow.fixture.object_graph
        }
        self.manifest_objects = _rifle_manifest_objects(
            baseline_manifest,
            self.specs,
        )
        self.manifest_media = _rifle_manifest_media(
            baseline_manifest,
            self.specs,
        )
        self.input_root: Path | None = None
        self.input_paths: dict[str, Path] = {}
        self.before: RifleSnapshot | None = None
        self.protocol: V3GatewayProtocol | None = None
        self.observed_steps: list[str] = []
        self._cleaned = False
        self._finalized = False

    def prepare(
        self,
    ) -> tuple[
        RifleSnapshot,
        Mapping[str, str],
        Mapping[str, Any],
        Mapping[str, Any],
    ]:
        if self.before is not None or self._cleaned:
            raise RifleIntegrationRuntimeError("Rifle runtime is single-use")
        input_root = self._create_inputs()
        self.input_root = input_root
        before = self._capture_snapshot(validate_manifest=True)
        self._validate_baseline(before)
        visible_values = self._visible_values(input_root)
        request = self._operation_request(visible_values)
        metadata = discover_metadata(
            read_call=self.backend.read_metadata,
            queries=METADATA_QUERIES,
            object_type="Sound",
            limit=8,
        ).as_dict()
        if (
            metadata.get("scope", {}).get("resolved", {}).get("name")
            != "Sound"
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle metadata did not resolve the exact live Sound type"
            )
        self.before = before
        return before, visible_values, request, MappingProxyType(metadata)

    def bind_protocol(self, protocol: V3GatewayProtocol) -> None:
        if self.protocol is not None or self.before is None:
            raise RifleIntegrationRuntimeError(
                "Rifle protocol binding is late or duplicated"
            )
        if (
            tuple(step.name for step in protocol.steps).count("tx01.execute")
            != 1
            or len(protocol.turn_prefix_counts) != 2
            or protocol.turn_prefix_counts[-1] != len(protocol.steps)
            or protocol.steps[protocol.turn_prefix_counts[0] - 1].name
            != "tx01.preview"
            or protocol.commutative_read_only_step_groups
            != RIFLE_COMMUTATIVE_READ_ONLY_STEP_GROUPS
            or protocol.commutative_composer_setup_step_groups
            != RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle protocol is not one metadata-bound transaction"
            )
        self.protocol = protocol

    def snapshot(self) -> RifleSnapshot:
        self._require_active()
        return self._capture_snapshot(validate_manifest=False)

    def verify_turn(
        self,
        turn_index: int,
        _result: Any | None = None,
    ) -> RifleVerification:
        if type(turn_index) is not int or turn_index != 1:
            raise RifleIntegrationRuntimeError(
                "Rifle preview verification supports only turn 1"
            )
        before = self._require_active()
        try:
            after = self._capture_snapshot(validate_manifest=False)
        except RifleIntegrationRuntimeError as exc:
            return RifleVerification(
                "preview_no_change",
                False,
                (str(exc),),
                MappingProxyType({"preview_unchanged": False}),
                before,
                None,
            )
        passed = after == before
        return RifleVerification(
            "preview_no_change",
            passed,
            () if passed else ("preview changed the sealed Rifle snapshot",),
            MappingProxyType({"preview_unchanged": passed}),
            before,
            after,
        )

    def observe_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        self._require_active()
        protocol = self.protocol
        if protocol is None:
            raise RifleIntegrationRuntimeError(
                "Rifle observer ran before protocol binding"
            )
        if not isinstance(step, ExpectedGatewayStep) or not isinstance(
            payload, Mapping
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle observer received an invalid step or payload"
            )
        expected_names = tuple(row.name for row in protocol.steps)
        candidate = (*self.observed_steps, step.name)
        if not gateway_step_prefix_matches(
            expected_names,
            candidate,
            protocol.commutative_read_only_step_groups,
            protocol.commutative_composer_setup_step_groups,
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle gateway steps were duplicated or observed out of order"
            )
        command = payload.get("command")
        if command is not None and command != step.subcommand:
            raise RifleIntegrationRuntimeError(
                f"{step.name} returned a different gateway command"
            )
        if step.name in {"tx01.preview", "tx01.execute", "tx01.verify"}:
            if payload.get("ok") is not True:
                raise RifleIntegrationRuntimeError(
                    f"{step.name} did not return a successful gateway payload"
                )
        self.observed_steps.append(step.name)
        if step.name == "tx01.preview":
            verification = self.verify_turn(1)
            verification.assert_passed()

    def verify_final(
        self,
        _gateway_payload: Mapping[str, Any] | None = None,
        _result: Any | None = None,
    ) -> RifleVerification:
        if self._finalized:
            raise RifleIntegrationRuntimeError(
                "Rifle final verification is single-use"
            )
        before = self._require_active()
        try:
            after = self._capture_snapshot(validate_manifest=False)
        except RifleIntegrationRuntimeError as exc:
            self._finalized = True
            return RifleVerification(
                "after_import",
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
        return RifleVerification(
            "after_import",
            not failures,
            failures,
            MappingProxyType(assertions),
            before,
            after,
        )

    def cleanup(self) -> RifleCleanupProof:
        if self._cleaned:
            return RifleCleanupProof(True, True, None, True, True, ())
        before = self.before
        input_root = self.input_root
        if before is None or input_root is None:
            raise RifleIntegrationRuntimeError(
                "Rifle cleanup cannot run before preparation"
            )
        failures: list[str] = []
        sandbox_project = self.paths.sandbox_project
        source_project = self.paths.source_project
        sandbox_before = _file_identity(sandbox_project)
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
        except BaseException as exc:  # cleanup must retain exact failure text
            failures.append(f"inputs: {type(exc).__name__}: {exc}")
        sandbox_after = _file_identity(sandbox_project)
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
            failures.append("Rifle input root remains after cleanup")
        self._cleaned = not failures
        return RifleCleanupProof(
            passed=self._cleaned,
            already_clean=False,
            removed_input_root=str(input_root) if self._cleaned else None,
            sandbox_untouched=sandbox_untouched,
            source_untouched=source_untouched,
            failures=tuple(failures),
        )

    def cleanup_failed_prepare(self) -> None:
        """Best-effort input cleanup when no prepared seam can be returned."""

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
            # Keep the preparation exception.  The outer lifecycle owns and
            # quarantines any scenario directory that cannot be cleaned here.
            return

    def _create_inputs(self) -> Path:
        binding = self.workflow.fixture.visible_bindings[
            "rifle_source_directory"
        ]
        relative = binding.get("relative_path")
        if not isinstance(relative, str):
            raise RifleIntegrationRuntimeError(
                "Rifle source binding lacks its reviewed relative path"
            )
        root = _fresh_owned_directory(self.paths.asset_root, relative)
        self.input_root = root
        for spec in self.workflow.fixture.source_files:
            file_name = _safe_file_name(spec.file_name)
            path = root / file_name
            _write_deterministic_wav(
                path,
                duration_ms=spec.duration_ms,
                frequency_hz=spec.frequency_hz,
            )
            self.input_paths[spec.key] = path
        if tuple(self.input_paths) != (
            "rifle_close_v2",
            "rifle_tail_v2",
            "rifle_mechanical_v2",
            "rifle_distant",
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle source file order or identity drifted"
            )
        return root

    def _visible_values(self, input_root: Path) -> Mapping[str, str]:
        bindings = self.workflow.fixture.visible_bindings
        values = {
            "rifle_source_directory": str(input_root),
            "rifle_container_path": _binding_object_path(
                bindings["rifle_container_path"], self.version
            ),
            "rifle_event_path": _binding_object_path(
                bindings["rifle_event_path"], self.version
            ),
            "rifle_bus_path": _binding_object_path(
                bindings["rifle_bus_path"], self.version
            ),
        }
        if tuple(values) != (
            "rifle_source_directory",
            "rifle_container_path",
            "rifle_event_path",
            "rifle_bus_path",
        ):
            raise AssertionError("Rifle visible value order drifted")
        return MappingProxyType(values)

    def _operation_request(
        self,
        visible_values: Mapping[str, str],
    ) -> Mapping[str, Any]:
        parameters = self.workflow.fixture.parameters
        source_by_key = self.input_paths
        imports: list[dict[str, Any]] = []
        for row in parameters["existing_rows"]:
            role = str(row["role"])
            source_key = str(row["source_key"])
            imports.append(
                {
                    "object_path": self.specs[role].path_for(self.version),
                    "audio_file": str(source_by_key[source_key]),
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                }
            )
        new_row = parameters["new_row"]
        imports.append(
            {
                "object_path": self.specs[str(new_row["role"])].path_for(
                    self.version
                ),
                "audio_file": str(
                    source_by_key[str(new_row["source_key"])]
                ),
                "object_type": "Sound SFX",
                "import_language": "SFX",
                "properties": [{"name": "Volume", "value": -12.0}],
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {
                            "kind": "path",
                            "value": visible_values["rifle_bus_path"],
                        },
                    }
                ],
            }
        )
        return MappingProxyType(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": self.version,
                "operation": "audio.import",
                "arguments": {
                    "import_operation": "useExisting",
                    "imports": imports,
                },
            }
        )

    def _capture_snapshot(self, *, validate_manifest: bool) -> RifleSnapshot:
        objects: list[RifleObjectState] = []
        absent: list[str] = []
        media: list[RifleMediaState] = []
        children_by_role: dict[str, tuple[RifleChildState, ...]] = {}
        for role, spec in self.specs.items():
            manifest_row = self.manifest_objects.get(role)
            state_fields: tuple[str, ...]
            if manifest_row is None:
                if role != "rifle_distant":
                    raise RifleIntegrationRuntimeError(
                        f"manifest omitted present Rifle role {role}"
                    )
                state_fields = _NEW_SOUND_STATE_FIELDS
            else:
                state = manifest_row.get("state")
                if not isinstance(state, Mapping) or not state:
                    raise RifleIntegrationRuntimeError(
                        f"manifest role {role} lacks state evidence"
                    )
                state_fields = RIFLE_CANONICAL_STATE_FIELDS[role]
            live_state_fields = tuple(
                field
                for field in state_fields
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
                if manifest_row is None:
                    raise RifleIntegrationRuntimeError(
                        "manifest omitted the sealed Play_Rifle Action"
                    )
                rows = self.backend.read_id(
                    str(manifest_row["id"]),
                    fields=fields,
                )
                lookup_label = f"{role} manifest id"
            else:
                rows = self.backend.read_path(spec_path, fields=fields)
            if not rows:
                absent.append(role)
                if manifest_row is not None:
                    raise RifleIntegrationRuntimeError(
                        f"committed Rifle object is absent: {role}"
                    )
                continue
            raw = _one_row(rows, lookup_label)
            object_id = _guid(raw.get("id"), f"{role} id")
            path = _wwise_path(raw.get("path"), f"{role} path")
            object_type = _text(raw.get("type"), f"{role} type")
            if path != spec_path or _type_token(object_type) != _type_token(
                spec.type
            ):
                raise RifleIntegrationRuntimeError(
                    f"{role} path or type differs from the reviewed workflow"
                )
            state_value: dict[str, Any] = {}
            for field in state_fields:
                if field == "children":
                    child_state = self._capture_children(role, object_id)
                    children_by_role[role] = child_state
                    state_value[field] = [
                        {"id": row.object_id}
                        for row in sorted(
                            child_state,
                            key=lambda item: item.object_id.casefold(),
                        )
                    ]
                elif field == "rtpc_rows":
                    state_value[field] = [
                        _plain(row)
                        for row in self.backend.read_rtpcs(object_id)
                    ]
                else:
                    if field not in raw:
                        raise RifleIntegrationRuntimeError(
                            f"{role} omitted manifest state field {field}"
                        )
                    state_value[field] = _normalize_state_field(
                        field,
                        raw[field],
                        label=f"{role} {field}",
                    )
            object_state = RifleObjectState(
                role=role,
                object_id=object_id,
                name=_text(raw.get("name"), f"{role} name"),
                object_type=object_type,
                path=path,
                state=_freeze_mapping(state_value),
            )
            if manifest_row is not None and (
                validate_manifest or role in {_ACTION_EVENT_ROLE, _ACTION_ROLE}
            ):
                _validate_manifest_object_state(object_state, manifest_row)
            objects.append(object_state)
            if _type_token(spec.type) == "sound":
                media_state = self._capture_media(
                    object_state,
                    enforce_parent=validate_manifest,
                )
                if validate_manifest:
                    manifest_media = self.manifest_media.get(role)
                    if manifest_media is None:
                        raise RifleIntegrationRuntimeError(
                            f"manifest omitted Rifle media role {role}"
                        )
                    _validate_manifest_media(media_state, manifest_media)
                media.append(media_state)

        by_role = {row.role: row for row in objects}
        self._validate_action_oracle(
            by_role,
            children_by_role.get(_ACTION_EVENT_ROLE),
        )
        container = by_role.get("rifle_container")
        if container is None:
            raise RifleIntegrationRuntimeError("Rifle container is absent")
        children = children_by_role.get("rifle_container")
        if children is None:
            raise RifleIntegrationRuntimeError(
                "Rifle container children were not captured"
            )
        input_files = tuple(
            (
                key,
                _regular_file_proof(
                    path,
                    relative_to=self.paths.asset_root,
                ),
            )
            for key, path in self.input_paths.items()
        )
        source_proof = _source_project_proof(
            self.paths.source_project,
            self.paths.source_root,
        )
        serial = {
            "workflow_id": RIFLE_WORKFLOW_ID,
            "version": self.version,
            "objects": [row.as_dict() for row in objects],
            "absent_roles": absent,
            "media": [row.as_dict() for row in media],
            "container_children": [row.as_dict() for row in children],
            "input_files": [
                {"key": key, **proof.as_dict()}
                for key, proof in input_files
            ],
            "source_project": source_proof.as_dict(),
        }
        return RifleSnapshot(
            workflow_id=RIFLE_WORKFLOW_ID,
            version=self.version,
            objects=tuple(objects),
            absent_roles=tuple(absent),
            media=tuple(media),
            container_children=children,
            input_files=input_files,
            source_project=source_proof,
            digest=_json_sha256(serial),
        )

    def _validate_action_oracle(
        self,
        objects: Mapping[str, RifleObjectState],
        event_children: tuple[RifleChildState, ...] | None,
    ) -> None:
        """Prove the nameless Action through its sealed GUID and parent Event."""

        event = objects.get(_ACTION_EVENT_ROLE)
        action = objects.get(_ACTION_ROLE)
        if event is None or action is None or event_children is None:
            raise RifleIntegrationRuntimeError(
                "Play_Rifle Event/Action oracle is incomplete"
            )
        if len(event_children) != 1:
            raise RifleIntegrationRuntimeError(
                "Play_Rifle Event must expose exactly one direct Action"
            )
        child = event_children[0]
        if (
            child.object_id.casefold() != action.object_id.casefold()
            or child.parent_id.casefold() != event.object_id.casefold()
            or child.name != action.name
            or _type_token(child.object_type) != "action"
            or child.path != action.path
            or _identity(action.state.get("parent"), "Play_Rifle Action parent")
            .casefold()
            != event.object_id.casefold()
        ):
            raise RifleIntegrationRuntimeError(
                "Play_Rifle Event child and sealed Action detail disagree"
            )

    def _capture_children(
        self,
        owner_role: str,
        owner_id: str,
    ) -> tuple[RifleChildState, ...]:
        """Read direct children through the cross-version select transform.

        ``children`` is canonical snapshot state, but it is not a portable
        ``options.return`` accessor: Wwise 2022.1 rejects that shape.  Both
        supported versions expose direct children through the reviewed
        ``from.id`` plus ``transform.select`` query instead.
        """

        result: list[RifleChildState] = []
        for raw in self.backend.read_children(owner_id, fields=_CHILD_FIELDS):
            parent_id = _identity(
                raw.get("parent"), f"{owner_role} child parent"
            )
            if parent_id.casefold() != owner_id.casefold():
                raise RifleIntegrationRuntimeError(
                    f"{owner_role} direct child has another parent"
                )
            result.append(
                RifleChildState(
                    object_id=_guid(
                        raw.get("id"), f"{owner_role} child id"
                    ),
                    name=_text(
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
        ids = [row.object_id.casefold() for row in result]
        if len(set(ids)) != len(ids):
            raise RifleIntegrationRuntimeError(
                f"{owner_role} children contain duplicate GUIDs"
            )
        return tuple(
            sorted(
                result,
                key=lambda row: (row.path.casefold(), row.object_id.casefold()),
            )
        )

    def _capture_media(
        self,
        sound: RifleObjectState,
        *,
        enforce_parent: bool,
    ) -> RifleMediaState:
        active_source_id = _identity(
            sound.state.get("activeSource"),
            f"{sound.role} activeSource",
        )
        source = _one_row(
            self.backend.read_id(active_source_id, fields=_SOURCE_FIELDS),
            f"{sound.role} activeSource",
        )
        source_id = _guid(source.get("id"), f"{sound.role} source id")
        source_type = _type_token(source.get("type"))
        if source_id.casefold() != active_source_id.casefold() or source_type not in {
            "audiofilesource",
            "audiosource",
        }:
            raise RifleIntegrationRuntimeError(
                f"{sound.role} activeSource identity or type drifted"
            )
        source_parent = _identity(
            source.get("parent"), f"{sound.role} source parent"
        )
        if (
            enforce_parent
            and source_parent.casefold() != sound.object_id.casefold()
        ):
            raise RifleIntegrationRuntimeError(
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
        return RifleMediaState(
            role=sound.role,
            sound_id=sound.object_id,
            active_source_id=source_id,
            source_parent_id=source_parent,
            language=language,
            original=original,
        )

    def _validate_baseline(self, snapshot: RifleSnapshot) -> None:
        objects = snapshot.objects_by_role()
        media = snapshot.media_by_role()
        if snapshot.absent_roles != ("rifle_distant",):
            raise RifleIntegrationRuntimeError(
                "Rifle_Distant is not the sole absent baseline role"
            )
        expected_present = {
            role
            for role, spec in self.specs.items()
            if spec.baseline_state == "present"
        }
        if set(objects) != expected_present:
            raise RifleIntegrationRuntimeError(
                "Rifle baseline object coverage differs from the workflow"
            )
        container_id = objects["rifle_container"].object_id
        for role in _EXISTING_SOUND_ROLES:
            if _identity(
                objects[role].state.get("parent"), f"{role} parent"
            ).casefold() != container_id.casefold():
                raise RifleIntegrationRuntimeError(
                    f"{role} is not parented by the Rifle container"
                )
        expected_child_ids = {
            objects[role].object_id.casefold()
            for role in _EXISTING_SOUND_ROLES
        }
        actual_child_ids = {
            child.object_id.casefold() for child in snapshot.container_children
        }
        state_child_ids = {
            _identity(row, "Rifle container state child").casefold()
            for row in objects["rifle_container"].state["children"]
        }
        if (
            actual_child_ids != expected_child_ids
            or state_child_ids != expected_child_ids
            or any(
                child.parent_id.casefold() != container_id.casefold()
                for child in snapshot.container_children
            )
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle container baseline children are not exactly the three Sounds"
            )
        event = objects["play_rifle_event"]
        action = objects["play_rifle_action"]
        event_child_ids = {
            _identity(row, "Play_Rifle Event child").casefold()
            for row in event.state["children"]
        }
        if (
            event_child_ids != {action.object_id.casefold()}
            or _identity(action.state.get("parent"), "Play_Rifle Action parent")
            .casefold()
            != event.object_id.casefold()
            or _integer(action.state.get("ActionType"), "ActionType") != 1
            or _identity(action.state.get("Target"), "Play_Rifle Target")
            .casefold()
            != objects["rifle_container"].object_id.casefold()
        ):
            raise RifleIntegrationRuntimeError(
                "Play_Rifle baseline Action chain drifted"
            )
        parameter_id = objects["rifle_distance_parameter"].object_id
        close_rtpcs = objects["rifle_close"].state.get("rtpc_rows")
        matching_rtpcs = [
            row
            for row in close_rtpcs
            if isinstance(row, Mapping)
            and row.get("@PropertyName") == "Volume"
            and _optional_identity(row.get("@ControlInput"))
            == parameter_id.casefold()
        ] if isinstance(close_rtpcs, list | tuple) else []
        if len(matching_rtpcs) != 1:
            raise RifleIntegrationRuntimeError(
                "Rifle_Close lacks one exact Rifle_Distance Volume RTPC"
            )
        media_ids = [row.active_source_id.casefold() for row in media.values()]
        if len(media_ids) != len(set(media_ids)):
            raise RifleIntegrationRuntimeError(
                "Rifle baseline AudioSource GUIDs are not unique"
            )
        inputs = snapshot.inputs_by_key()
        source_keys = {
            "rifle_close": "rifle_close_v2",
            "rifle_tail": "rifle_tail_v2",
            "rifle_mechanical": "rifle_mechanical_v2",
        }
        for role, key in source_keys.items():
            if media[role].original.sha256 == inputs[key].sha256:
                raise RifleIntegrationRuntimeError(
                    f"{role} baseline media already equals its incoming revision"
                )
        source = snapshot.source_project
        if (
            source.project_sha256 != self.manifest.project_file_sha256
            or source.tree_sha256 != self.manifest.full_tree_sha256
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle source project differs from the sealed baseline manifest"
            )

    def _final_assertions(
        self,
        before: RifleSnapshot,
        after: RifleSnapshot,
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

        record(
            "existing_sound_guids_preserved",
            all(
                role in new_objects
                and new_objects[role].object_id.casefold()
                == old_objects[role].object_id.casefold()
                for role in _EXISTING_SOUND_ROLES
            ),
            "one or more existing Sound GUIDs changed",
        )
        record(
            "existing_active_sources_bound_to_sounds",
            all(
                role in new_objects
                and role in new_media
                and new_media[role].sound_id.casefold()
                == old_objects[role].object_id.casefold()
                and new_media[role].source_parent_id.casefold()
                == old_objects[role].object_id.casefold()
                for role in _EXISTING_SOUND_ROLES
            )
            and len(
                {
                    new_media[role].active_source_id.casefold()
                    for role in _EXISTING_SOUND_ROLES
                    if role in new_media
                }
            )
            == len(_EXISTING_SOUND_ROLES),
            "an existing Sound has a missing, shared, or incorrectly parented activeSource",
        )
        source_keys = {
            "rifle_close": "rifle_close_v2",
            "rifle_tail": "rifle_tail_v2",
            "rifle_mechanical": "rifle_mechanical_v2",
        }
        record(
            "updated_media_hashes_match_inputs",
            all(
                role in new_media
                and new_media[role].original.sha256 == inputs[key].sha256
                and new_media[role].language == "SFX"
                for role, key in source_keys.items()
            ),
            "an updated Sound media hash or language differs from its input",
        )
        distant = new_objects.get("rifle_distant")
        distant_media = new_media.get("rifle_distant")
        all_old_ids = {
            row.object_id.casefold() for row in before.objects
        } | {
            row.active_source_id.casefold() for row in before.media
        }
        record(
            "distant_created_once_with_new_guid",
            distant is not None
            and "rifle_distant" not in after.absent_roles
            and distant.object_id.casefold() not in all_old_ids
            and _identity(distant.state.get("parent"), "Distant parent")
            .casefold()
            == old_objects["rifle_container"].object_id.casefold()
            and distant_media is not None
            and distant_media.active_source_id.casefold() not in all_old_ids
            and distant_media.source_parent_id.casefold()
            == distant.object_id.casefold(),
            "Rifle_Distant is absent, reused an old GUID, or has the wrong parent",
        )
        record(
            "distant_media_hash_matches_input",
            distant_media is not None
            and distant_media.original.sha256
            == inputs["rifle_distant"].sha256
            and distant_media.language == "SFX",
            "Rifle_Distant media hash or language differs from its input",
        )
        expected_children = {
            new_objects[role].object_id.casefold()
            for role in (*_EXISTING_SOUND_ROLES, "rifle_distant")
            if role in new_objects
        }
        record(
            "rifle_container_child_set_exact",
            len(expected_children) == 4
            and {row.object_id.casefold() for row in after.container_children}
            == expected_children
            and all(
                row.parent_id.casefold()
                == old_objects["rifle_container"].object_id.casefold()
                for row in after.container_children
            ),
            "Rifle container direct children differ from the exact four-Sound set",
        )
        record(
            "play_event_chain_unchanged",
            all(
                role in new_objects
                and new_objects[role] == old_objects[role]
                for role in _PROTECTED_GRAPH_ROLES
            ),
            "Play_Rifle Event or Action identity/state changed",
        )
        record(
            "sound_design_state_unchanged",
            all(
                role in new_objects
                and _sound_design_projection(new_objects[role])
                == _sound_design_projection(old_objects[role])
                for role in _EXISTING_SOUND_ROLES
            ),
            "an existing Sound identity, parent, property, OutputBus, or RTPC changed",
        )
        record(
            "distractors_unchanged",
            all(
                role in new_objects
                and new_objects[role] == old_objects[role]
                and role in new_media
                and new_media[role] == old_media[role]
                for role in _DISTRACTOR_ROLES
            ),
            "a similarly named distractor object or media source changed",
        )
        expected_steps = (
            tuple(step.name for step in self.protocol.steps)
            if self.protocol is not None
            else ()
        )
        record(
            "single_import_transaction",
            gateway_step_sequence_matches(
                expected_steps,
                tuple(self.observed_steps),
                (
                    self.protocol.commutative_read_only_step_groups
                    if self.protocol is not None
                    else ()
                ),
                (
                    self.protocol.commutative_composer_setup_step_groups
                    if self.protocol is not None
                    else ()
                ),
            )
            and self.observed_steps.count("tx01.execute") == 1
            and self.observed_steps.count("tx01.verify") == 1,
            "the exact one-transaction broker protocol was not fully observed",
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
        if distant is not None:
            bus_id = old_objects["weapons_bus"].object_id.casefold()
            distant_fields_ok = (
                _number(distant.state.get("@Volume"), "Distant Volume")
                == -12.0
                and _identity(distant.state.get("OutputBus"), "Distant OutputBus")
                .casefold()
                == bus_id
            )
            if not distant_fields_ok:
                assertions["distant_created_once_with_new_guid"] = False
                details["distant_created_once_with_new_guid"] = (
                    "Rifle_Distant Volume or OutputBus differs from the request"
                )
        if tuple(assertions) != _EXPECTED_ASSERTION_IDS:
            raise AssertionError("Rifle assertion order drifted")
        return assertions, details

    def _require_active(self) -> RifleSnapshot:
        if self.before is None:
            raise RifleIntegrationRuntimeError("Rifle runtime was not prepared")
        if self._cleaned:
            raise RifleIntegrationRuntimeError("Rifle inputs are already clean")
        return self.before


def _sound_design_projection(value: RifleObjectState) -> dict[str, Any]:
    """Compare the Sound contract while allowing native media-source churn."""

    return {
        "role": value.role,
        "id": value.object_id,
        "name": value.name,
        "type": value.object_type,
        "path": value.path,
        "state": {
            key: _plain(item)
            for key, item in value.state.items()
            if key != "activeSource"
        },
    }


def _validate_reviewed_inputs(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    baseline_manifest: BaselineManifest,
    direct_call: DirectWaapiCall,
) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise RifleIntegrationRuntimeError(
            f"Rifle integration version is unsupported: {version!r}"
        )
    if not callable(direct_call):
        raise TypeError("direct_call must be callable")
    if getattr(workflow, "id", None) != RIFLE_WORKFLOW_ID:
        raise RifleIntegrationRuntimeError("wrong integration workflow for Rifle")
    if version not in tuple(getattr(workflow, "versions", ())):
        raise RifleIntegrationRuntimeError("Rifle workflow/version are misbound")
    fixture = getattr(workflow, "fixture", None)
    if (
        getattr(fixture, "adapter", None) != RIFLE_FIXTURE_ADAPTER
        or getattr(fixture, "baseline_source", None)
        != "committed_sample_project"
    ):
        raise RifleIntegrationRuntimeError("Rifle fixture adapter drifted")
    transactions = tuple(getattr(workflow, "transactions", ()))
    if len(transactions) != 1:
        raise RifleIntegrationRuntimeError("Rifle requires one transaction")
    transaction = transactions[0]
    if (
        getattr(transaction, "index", None) != 1
        or getattr(transaction, "operation", None) != "audio.import"
        or getattr(transaction, "api", None) != IMPORT_API
        or getattr(transaction, "preview_turn", None) != 1
        or getattr(transaction, "confirmation_turn", None) != 2
    ):
        raise RifleIntegrationRuntimeError("Rifle transaction topology drifted")
    if tuple(getattr(turn, "kind", None) for turn in workflow.turns) != (
        "request",
        "confirmation",
    ):
        raise RifleIntegrationRuntimeError("Rifle turn topology drifted")
    if tuple(item.name for item in workflow.visible_inputs) != (
        "rifle_source_directory",
        "rifle_container_path",
        "rifle_event_path",
        "rifle_bus_path",
    ):
        raise RifleIntegrationRuntimeError("Rifle visible inputs drifted")
    if tuple(item.id for item in fixture.business_assertions) != (
        _EXPECTED_ASSERTION_IDS
    ):
        raise RifleIntegrationRuntimeError("Rifle business assertions drifted")
    if (
        getattr(scenario, "scenario_family", None) != RIFLE_WORKFLOW_ID
        or getattr(scenario, "api", None) != IMPORT_API
        or tuple(getattr(scenario, "versions", ())) != (version,)
    ):
        raise RifleIntegrationRuntimeError("Rifle scenario proxy is misbound")
    if (
        not isinstance(baseline_manifest, BaselineManifest)
        or baseline_manifest.version != version
    ):
        raise RifleIntegrationRuntimeError(
            "Rifle baseline manifest/version are misbound"
        )


def _validated_runtime_paths(runtime: RifleRuntimePaths) -> _RuntimePaths:
    directories: dict[str, Path] = {}
    for name in ("scenario_root", "asset_root", "io_root"):
        raw = getattr(runtime, name, None)
        if raw is None:
            raise RifleIntegrationRuntimeError(
                f"Rifle runtime paths omit {name}"
            )
        path = Path(os.path.abspath(os.fspath(Path(raw).expanduser())))
        _real_directory(path, name)
        directories[name] = path
    scenario_root = directories["scenario_root"]
    for name in ("asset_root", "io_root"):
        path = directories[name]
        if path == scenario_root or scenario_root not in path.parents:
            raise RifleIntegrationRuntimeError(
                f"{name} must be a strict descendant of scenario_root"
            )
    sandbox = getattr(runtime, "sandbox", None)
    if sandbox is None:
        raise RifleIntegrationRuntimeError("Rifle runtime omits its sandbox")
    file_values: dict[str, Path] = {}
    for name in ("sandbox_project", "source_project"):
        value = getattr(sandbox, name, None)
        if value is None:
            raise RifleIntegrationRuntimeError(f"sandbox omits {name}")
        path = _real_file(Path(value), name)
        if path.suffix.casefold() != ".wproj":
            raise RifleIntegrationRuntimeError(f"{name} must be a .wproj file")
        file_values[name] = path
    sandbox_project = file_values["sandbox_project"]
    source_project = file_values["source_project"]
    source_value = getattr(sandbox, "source_root", None)
    if source_value is None:
        raise RifleIntegrationRuntimeError("sandbox omits source_root")
    source_root = _real_directory(Path(source_value), "source_root")
    sandbox_value = getattr(sandbox, "sandbox_path", None)
    sandbox_root = _real_directory(
        Path(sandbox_value) if sandbox_value is not None else sandbox_project.parent,
        "sandbox project root",
    )
    if sandbox_root not in sandbox_project.parents:
        raise RifleIntegrationRuntimeError(
            "sandbox project is outside its copied project root"
        )
    if scenario_root not in sandbox_project.parents:
        raise RifleIntegrationRuntimeError(
            "sandbox project is outside the scenario-owned root"
        )
    if source_root not in source_project.parents:
        raise RifleIntegrationRuntimeError(
            "source project is outside its source root"
        )
    if source_project == sandbox_project or source_root == sandbox_root:
        raise RifleIntegrationRuntimeError(
            "source and copied Rifle projects are not isolated"
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


def _rifle_manifest_objects(
    manifest: BaselineManifest,
    specs: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest.objects:
        if not isinstance(raw, Mapping):
            raise RifleIntegrationRuntimeError(
                "baseline manifest contains a non-object row"
            )
        role = raw.get("role")
        if role not in specs:
            continue
        if role in result:
            raise RifleIntegrationRuntimeError(
                f"baseline manifest repeats Rifle role {role}"
            )
        spec = specs[str(role)]
        state = raw.get("state")
        if spec.baseline_state != "present":
            raise RifleIntegrationRuntimeError(
                f"baseline manifest contains absent Rifle role {role}"
            )
        if (
            raw.get("path") != spec.path_for(manifest.version)
            or _type_token(raw.get("type")) != _type_token(spec.type)
            or _GUID_RE.fullmatch(str(raw.get("id"))) is None
            or not isinstance(state, Mapping)
            or _SHA256_RE.fullmatch(str(raw.get("state_sha256"))) is None
        ):
            raise RifleIntegrationRuntimeError(
                f"baseline manifest Rifle role {role} is malformed"
            )
        state_digest = hashlib.sha256(
            canonical_json_bytes(state)
        ).hexdigest()
        if state_digest != raw["state_sha256"]:
            raise RifleIntegrationRuntimeError(
                f"baseline manifest Rifle role {role} state digest drifted"
            )
        canonical = _canonical_manifest_state(str(role), state)
        if _plain(state) != canonical:
            raise RifleIntegrationRuntimeError(
                f"baseline manifest Rifle role {role} state is not canonical"
            )
        result[str(role)] = MappingProxyType(dict(raw))
    expected = {
        role
        for role, spec in specs.items()
        if spec.baseline_state == "present"
    }
    if set(result) != expected:
        raise RifleIntegrationRuntimeError(
            "baseline manifest Rifle object coverage drifted"
        )
    return result


def _canonical_manifest_state(
    role: str,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        fields = RIFLE_CANONICAL_STATE_FIELDS[role]
    except KeyError as exc:
        raise RifleIntegrationRuntimeError(
            f"manifest role has no Rifle state contract: {role}"
        ) from exc
    if set(state) != set(fields):
        raise RifleIntegrationRuntimeError(
            f"manifest role {role} state keys are not closed"
        )
    result: dict[str, Any] = {}
    for field in fields:
        value = state[field]
        if field == "rtpc_rows":
            if (
                not isinstance(value, list)
                or len(value) > _MAX_RTPC_ROWS
                or any(
                    not isinstance(row, Mapping)
                    or set(row) != set(_RTPC_SNAPSHOT_FIELDS)
                    for row in value
                )
            ):
                raise RifleIntegrationRuntimeError(
                    f"manifest {role} RTPC rows are malformed or unbounded"
                )
            rows = [_normalize_rtpc_row(row) for row in value]
            ids = [_guid(row["id"], f"manifest {role} RTPC id") for row in rows]
            if len({item.casefold() for item in ids}) != len(ids):
                raise RifleIntegrationRuntimeError(
                    f"manifest {role} RTPC rows contain duplicate GUIDs"
                )
            result[field] = rows
        else:
            result[field] = _normalize_state_field(
                field,
                value,
                label=f"manifest {role} {field}",
                require_canonical_children=True,
            )
    return result


def _rifle_manifest_media(
    manifest: BaselineManifest,
    specs: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    sound_roles = {
        role
        for role, spec in specs.items()
        if spec.baseline_state == "present" and _type_token(spec.type) == "sound"
    }
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest.media:
        if not isinstance(raw, Mapping) or raw.get("role") not in sound_roles:
            continue
        role = str(raw["role"])
        if role in result:
            raise RifleIntegrationRuntimeError(
                f"baseline manifest repeats Rifle media role {role}"
            )
        if (
            _GUID_RE.fullmatch(str(raw.get("active_source_id"))) is None
            or not isinstance(raw.get("relative_path"), str)
            or not str(raw["relative_path"]).startswith("Originals/")
            or _SHA256_RE.fullmatch(str(raw.get("sha256"))) is None
        ):
            raise RifleIntegrationRuntimeError(
                f"baseline manifest Rifle media role {role} is malformed"
            )
        result[role] = MappingProxyType(dict(raw))
    if set(result) != sound_roles:
        raise RifleIntegrationRuntimeError(
            "baseline manifest Rifle media coverage drifted"
        )
    return result


def _validate_manifest_object_state(
    state: RifleObjectState,
    manifest_row: Mapping[str, Any],
) -> None:
    if (
        state.object_id.casefold() != str(manifest_row["id"]).casefold()
        or state.path != manifest_row["path"]
        or _type_token(state.object_type) != _type_token(manifest_row["type"])
        or _plain(state.state) != _plain(manifest_row["state"])
        or hashlib.sha256(canonical_json_bytes(_plain(state.state))).hexdigest()
        != manifest_row["state_sha256"]
    ):
        raise RifleIntegrationRuntimeError(
            f"live copied Rifle object differs from manifest role {state.role}"
        )


def _validate_manifest_media(
    state: RifleMediaState,
    manifest_row: Mapping[str, Any],
) -> None:
    if (
        state.active_source_id.casefold()
        != str(manifest_row["active_source_id"]).casefold()
        or state.original.relative_path != manifest_row["relative_path"]
        or state.original.sha256 != manifest_row["sha256"]
        or state.language != "SFX"
    ):
        raise RifleIntegrationRuntimeError(
            f"live copied Rifle media differs from manifest role {state.role}"
        )


def _oracle_requirements() -> tuple[RifleOracleRequirement, ...]:
    return (
        RifleOracleRequirement(
            "before",
            "committed_baseline",
            "every exact GUID, state digest, activeSource, and old media hash matches the version manifest",
        ),
        RifleOracleRequirement(
            "preview",
            "immutable_snapshot",
            "metadata discovery, operation-schema, and preview leave the copied graph and inputs unchanged",
        ),
        RifleOracleRequirement(
            "after",
            "existing_sounds",
            "three Sound GUIDs and their design state are preserved; each unique activeSource remains parented to its Sound and its copied media hash matches the incoming WAV",
        ),
        RifleOracleRequirement(
            "after",
            "new_distant",
            "one new Rifle_Distant has a fresh GUID, -12 dB Volume, Weapons OutputBus, and matching media",
        ),
        RifleOracleRequirement(
            "after",
            "protected_graph",
            "container cardinality, Event/Action chain, properties, references, RTPC rows, and distractors satisfy all eleven business assertions",
        ),
        RifleOracleRequirement(
            "cleanup",
            "existing_lifecycle",
            "the runtime removes only its incoming input tree; the lifecycle owns copied-project cleanup and source proof",
        ),
    )


def _normalize_state_field(
    field: str,
    value: Any,
    *,
    label: str,
    require_canonical_children: bool = False,
) -> Any:
    if field in {"parent", "OutputBus", "activeSource", "Target"}:
        return {"id": _identity(value, label)}
    if field == "children":
        if (
            not isinstance(value, list)
            or len(value) > _MAX_OBJECT_ROWS
        ):
            raise RifleIntegrationRuntimeError(
                f"{label} are malformed or unbounded"
            )
        if require_canonical_children and any(
            not isinstance(row, Mapping) or set(row) != {"id"}
            for row in value
        ):
            raise RifleIntegrationRuntimeError(
                f"{label} are not canonical id references"
            )
        ids = sorted(
            (_identity(row, f"{label} reference") for row in value),
            key=str.casefold,
        )
        if len({item.casefold() for item in ids}) != len(ids):
            raise RifleIntegrationRuntimeError(
                f"{label} contain duplicate GUIDs"
            )
        return [{"id": item} for item in ids]
    return _plain(value)


def _normalize_rtpc_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        field: _plain(row[field]) for field in _RTPC_SNAPSHOT_FIELDS
    }
    normalized["id"] = _guid(normalized["id"], "RTPC id")
    control_input = normalized.get("@ControlInput")
    if control_input not in (None, "", {}):
        normalized["@ControlInput"] = {
            "id": _identity(control_input, "RTPC ControlInput")
        }
    return normalized


def _fresh_owned_directory(root: Path, relative: str) -> Path:
    try:
        parsed_relative = parse_archive_relative_path(relative)
    except ArchiveRelativePathError as exc:
        raise RifleIntegrationRuntimeError(
            "Rifle input relative path is unsafe"
        ) from exc
    candidate = root.joinpath(*parsed_relative.parts)
    if candidate.exists() or candidate.is_symlink():
        raise RifleIntegrationRuntimeError(
            f"Rifle input root is not fresh: {candidate}"
        )
    current = root
    for part in parsed_relative.parts:
        current /= part
        current.mkdir(exist_ok=False)
        _real_directory(current, "Rifle input directory")
    if root not in candidate.parents:
        raise RifleIntegrationRuntimeError("Rifle input root escaped asset_root")
    return candidate


def _binding_object_path(value: Any, version: str) -> str:
    if not isinstance(value, Mapping):
        raise RifleIntegrationRuntimeError(
            "Rifle object-path binding is malformed"
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
    raise RifleIntegrationRuntimeError(
        "Rifle object-path binding does not cover this version"
    )


def _remove_owned_input_tree(
    path: Path,
    *,
    stop: Path,
    expected_names: set[str],
) -> None:
    candidate = Path(path)
    if stop not in candidate.parents:
        raise RifleIntegrationRuntimeError(
            "Rifle cleanup path escaped asset_root"
        )
    if candidate.is_symlink():
        raise RifleIntegrationRuntimeError(
            "Rifle input root became a symlink"
        )
    if candidate.exists():
        _real_directory(candidate, "Rifle input root")
        children = tuple(candidate.iterdir())
        if (
            {child.name for child in children} != expected_names
            or len(children) != len(expected_names)
        ):
            raise RifleIntegrationRuntimeError(
                "Rifle input root contains entries outside the owned set"
            )
        for child in children:
            metadata = os.lstat(child)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
                metadata.st_mode
            ):
                raise RifleIntegrationRuntimeError(
                    f"unexpected Rifle input entry: {child}"
                )
            child.unlink()
        candidate.rmdir()
    parent = candidate.parent
    while parent != stop and stop in parent.parents:
        if parent.is_symlink():
            raise RifleIntegrationRuntimeError(
                "Rifle input ancestor became a symlink"
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
        raise RifleIntegrationRuntimeError(
            "Rifle WAV specification is outside the closed bounds"
        )
    if path.exists() or path.is_symlink():
        raise RifleIntegrationRuntimeError(
            f"Rifle WAV path is not fresh: {path}"
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
    with wave.open(str(path), "wb") as handle:
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
) -> RifleFileProof:
    try:
        candidate = localize_copied_original_path(
            value,
            account_home=account_home,
        )
    except IntegrationOriginalPathError as exc:
        raise RifleIntegrationRuntimeError(str(exc)) from exc
    root = sandbox_root.resolve(strict=True)
    originals = root / "Originals"
    _real_directory(originals, "copied Originals root")
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise RifleIntegrationRuntimeError(
            f"copied Original escapes the sandbox: {candidate}"
        ) from exc
    if (
        not lexical_relative.parts
        or Path(lexical_relative.parts[0]) != Path("Originals")
    ):
        raise RifleIntegrationRuntimeError(
            f"copied Original is outside sandbox Originals: {candidate}"
        )
    current = root
    for part in lexical_relative.parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise RifleIntegrationRuntimeError(
                f"copied Original path is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RifleIntegrationRuntimeError(
                f"copied Original path contains a symlink: {current}"
            )
    resolved = candidate.resolve(strict=True)
    try:
        resolved_relative = resolved.relative_to(root)
    except ValueError as exc:
        raise RifleIntegrationRuntimeError(
            "copied Original resolves outside the sandbox"
        ) from exc
    if Path(*resolved_relative.parts) != Path(*lexical_relative.parts):
        raise RifleIntegrationRuntimeError(
            "copied Original changed during containment proof"
        )
    return _regular_file_proof(resolved, relative_to=root)


def _regular_file_proof(
    value: Path,
    *,
    relative_to: Path | None,
) -> RifleFileProof:
    path = _real_file(Path(value), "sealed file")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns"):
        if getattr(before, field) != getattr(after, field):
            raise RifleIntegrationRuntimeError(
                f"file changed while being sealed: {path}"
            )
    relative: str | None = None
    if relative_to is not None:
        root = Path(relative_to).resolve(strict=True)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise RifleIntegrationRuntimeError(
                f"sealed file escapes its root: {path}"
            ) from exc
    return RifleFileProof(
        path=str(path),
        relative_path=relative,
        size=before.st_size,
        sha256=digest.hexdigest(),
    )


def _source_project_proof(
    project: Path,
    root: Path,
) -> RifleSourceProjectProof:
    project_proof = _regular_file_proof(project, relative_to=root)
    return RifleSourceProjectProof(
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
        raise RifleIntegrationRuntimeError(
            f"{label} cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RifleIntegrationRuntimeError(
            f"{label} must be a real directory"
        )
    return candidate.resolve(strict=True)


def _real_file(path: Path, label: str) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise RifleIntegrationRuntimeError(
            f"{label} cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RifleIntegrationRuntimeError(f"{label} must be a real file")
    return candidate.resolve(strict=True)


def _safe_file_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != Path(value).name
        or not value.casefold().endswith(".wav")
    ):
        raise RifleIntegrationRuntimeError(
            f"unsafe Rifle WAV file name: {value!r}"
        )
    return value


def _one_row(
    rows: Sequence[Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    if len(rows) != 1:
        raise RifleIntegrationRuntimeError(
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
            raise RifleIntegrationRuntimeError(
                f"invalid object.get return field: {value!r}"
            )
        if value not in result:
            result.append(value)
    if not result or len(result) > 64:
        raise RifleIntegrationRuntimeError(
            "object.get return field list is empty or unbounded"
        )
    return tuple(result)


def _guid(value: Any, label: str) -> str:
    if not isinstance(value, str) or _GUID_RE.fullmatch(value) is None:
        raise RifleIntegrationRuntimeError(f"{label} is not a GUID")
    return value.upper()


def _identity(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    return _guid(value, label)


def _optional_identity(value: Any) -> str | None:
    try:
        return _identity(value, "identity").casefold()
    except RifleIntegrationRuntimeError:
        return None


def _wwise_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("\\")
        or value != value.strip()
        or "\x00" in value
    ):
        raise RifleIntegrationRuntimeError(
            f"{label} is not an absolute Wwise path"
        )
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise RifleIntegrationRuntimeError(f"{label} is not a string")
    return value


def _type_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _name_value(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("name")
    if not isinstance(value, str) or not value:
        raise RifleIntegrationRuntimeError(f"{label} is not a name")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RifleIntegrationRuntimeError(f"{label} is not an integer")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RifleIntegrationRuntimeError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RifleIntegrationRuntimeError(f"{label} is not finite")
    return result


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(_plain(value))).hexdigest()


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[str(key)] = _freeze_mapping(item)
        elif isinstance(item, list | tuple):
            frozen[str(key)] = tuple(
                _freeze_mapping(row) if isinstance(row, Mapping) else _plain(row)
                for row in item
            )
        else:
            frozen[str(key)] = item
    return MappingProxyType(frozen)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "IMPORT_API",
    "METADATA_QUERIES",
    "METADATA_TOKENS",
    "RIFLE_CANONICAL_STATE_FIELDS",
    "RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS",
    "RIFLE_COMMUTATIVE_READ_ONLY_STEP_GROUPS",
    "RIFLE_FIXTURE_ADAPTER",
    "RIFLE_WORKFLOW_ID",
    "SUPPORTED_VERSIONS",
    "PreparedRifleIntegrationRuntime",
    "RifleCleanupProof",
    "RifleExpectedDispatch",
    "RifleFileProof",
    "RifleIntegrationRuntimeError",
    "RifleMediaState",
    "RifleObjectState",
    "RifleOracleRequirement",
    "RifleSnapshot",
    "RifleSourceProjectProof",
    "RifleVerification",
    "prepare_rifle_integration_runtime",
]

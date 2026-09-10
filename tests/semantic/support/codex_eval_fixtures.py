"""Runner-owned live Wwise fixtures and direct semantic-eval oracles.

The evaluated model must never create its own fixtures or learn fixture GUIDs.
This module therefore has two deliberately separate surfaces:

* :func:`create_shared_fixture_bundle` uses the packaged gateway, outside the
  model sandbox, to create and later remove a small disposable object graph.
* :meth:`EvalFixtureBundle.prompt_values` returns a closed set of path/value
  strings, while :meth:`EvalFixtureBundle.snapshot` keeps direct WAAPI
  readback and hidden identities on the trusted runner side.

No destructive test module is imported here: several of those modules skip at
import time unless a live environment is active.  The transaction lifecycle is
implemented against the production packaged gateway contract instead.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
import sys
import uuid
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeAlias

from tests.semantic.support.codex_gateway_broker import (
    GatewayInvocationError,
    validate_transaction_show_confirmation_payload,
)
from tests.semantic.support.typed_gateway_input import (
    create_typed_transaction_preview,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"

GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")

ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
CONTAINERS_PARENT = r"\Containers\Default Work Unit"
SOUNDBANK_PARENT = r"\SoundBanks\Default Work Unit"
SWITCH_PARENT = r"\Switches\Default Work Unit"
SWITCH_GROUP_REFERENCE = "SwitchGroupOrStateGroup"
SOUND_SFX_QUERY_NAME = "Sound = SFX"
QUERY_RESULT_LIMIT = 10
_ACTOR_MIXER_REFLECTED_TYPE_BY_VERSION: Mapping[str, str] = MappingProxyType(
    {
        "2021.1": "ActorMixer",
        "2022.1": "ActorMixer",
        "2023.1": "ActorMixer",
        "2024.1": "ActorMixer",
        # Wwise 2025.1 creates this requested ActorMixer below the new
        # Containers hierarchy but reflects its canonical base type.
        "2025.1": "PropertyContainer",
    }
)
_QUERY_EDITOR_ORACLE_MODE_BY_VERSION: Mapping[
    str, Literal["live", "validated-baseline"]
] = MappingProxyType(
    {
        "2021.1": "live",
        "2022.1": "live",
        "2023.1": "live",
        # Wwise 2024.1 and 2025.1 persistent oracle connections deterministically
        # report "Recursive loop detected in query" when the factory Sound = SFX
        # Query is executed a second time.  Capture it live once during fixture
        # validation, then compare the model's independent live gateway result
        # against that immutable trusted baseline.
        "2024.1": "validated-baseline",
        "2025.1": "validated-baseline",
    }
)

CASE_IDS = (
    "Q1", "Q2", "Q3", "Q4", "Q5", "C1", "M1", "M2", "M3", "M4", "M5", "M6", "M7",
    "B1", "B2", "B3", "B4", "B5", "B6", "B7", "I1", "S1", "W1", "W2",
    "R1", "R2", "R3", "R4", "R5", "R6",
)
QUERY_CASE_IDS = frozenset({"Q1", "Q2", "Q3", "Q4", "Q5"})
FIXED_READ_CASE_IDS = frozenset({"R1", "R2", "R3", "R4", "R5", "R6"})
LIVE_CASE_IDS = frozenset(
    {*QUERY_CASE_IDS, "M1", "M2", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"}
)
CASE_ADAPTERS: Mapping[str, str] = MappingProxyType(
    {
        "Q1": "exact_path_query",
        "Q2": "direct_children_query",
        "Q3": "name_search_query",
        "Q4": "query_editor_query",
        "Q5": "exact_missing_path_query",
        "C1": "offline_catalog",
        "M1": "object_set_notes",
        "M2": "object_set_notes",
        "M3": "object_create",
        "M4": "object_delete",
        "M5": "object_set_name",
        "M6": "object_set_property",
        "M7": "object_set_reference",
        "B1": "operation_boundary",
        "B2": "operation_boundary",
        "B3": "operation_boundary",
        "B4": "operation_boundary",
        "B5": "operation_boundary",
        "B6": "operation_boundary",
        "B7": "operation_boundary",
        "I1": "audio_import",
        "S1": "soundbank_inclusions",
        "W1": "switch_assignment",
        "W2": "switch_assignment_remove",
        "R1": "status_read",
        "R2": "buses_read",
        "R3": "selected_read",
        "R4": "metadata_types_read",
        "R5": "object_created_topic_read",
        "R6": "reflection_functions_read",
    }
)
_EXPECTATIONS = frozenset({"unchanged", "applied"})
_GUID_KEY_RE = re.compile(r"(?:^|_)(?:id|guid)(?:$|_)", re.IGNORECASE)
_BROKER_ENV_PREFIX = "WAAPI_CODEX_GATEWAY_BROKER_"
_BROKER_ENV_NAMES = frozenset({"BASH_ENV", "WAAPI_CODEX_GATEWAY_REQUIRED"})


class FixtureContractError(RuntimeError):
    """A trusted fixture/gateway/readback contract failed closed."""


def _actor_mixer_reflected_type(version: str) -> str:
    reflected_type = _ACTOR_MIXER_REFLECTED_TYPE_BY_VERSION.get(version)
    if reflected_type is None:
        raise FixtureContractError(
            f"ActorMixer reflected-type contract is unavailable for Wwise {version}"
        )
    return reflected_type


def _query_editor_oracle_mode(version: str) -> Literal["live", "validated-baseline"]:
    mode = _QUERY_EDITOR_ORACLE_MODE_BY_VERSION.get(version)
    if mode is None:
        raise FixtureContractError(
            f"Query Editor oracle contract is unavailable for Wwise {version}"
        )
    return mode


class TrustedGateway(Protocol):
    """Callable form used for the packaged gateway and unit-test fakes."""

    def __call__(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
    ) -> Mapping[str, Any]: ...


TrustedPreview: TypeAlias = Callable[
    [Mapping[str, Any], Path, Path],
    Mapping[str, Any],
]
ReadCall: TypeAlias = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True, init=False)
class PackagedGatewayBinding:
    """Validated runner/cwd pair derived from one trusted Skill source.

    The runner path is intentionally not caller-selectable: it is always the
    regular file at ``<skill_source>/scripts/run.py`` and the resolved Skill
    root is always used as its working directory.
    """

    skill_root: Path
    runner_path: Path

    def __init__(self, skill_source: str | Path) -> None:
        try:
            skill_root = Path(skill_source).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise FixtureContractError(
                f"packaged gateway Skill source does not exist: {skill_source}"
            ) from exc
        if not skill_root.is_dir():
            raise FixtureContractError(
                f"packaged gateway Skill source must be a directory: {skill_root}"
            )

        runner_path = skill_root / "scripts" / "run.py"
        try:
            runner_mode = runner_path.lstat().st_mode
        except OSError as exc:
            raise FixtureContractError(
                f"packaged gateway runner does not exist: {runner_path}"
            ) from exc
        if not stat.S_ISREG(runner_mode):
            raise FixtureContractError(
                f"packaged gateway runner must be a regular file: {runner_path}"
            )

        object.__setattr__(self, "skill_root", skill_root)
        object.__setattr__(self, "runner_path", runner_path)


@dataclass(frozen=True, slots=True)
class ObjectOracle:
    id: str
    name: str
    type: str
    path: str
    notes: str | None
    parent_id: str | None = None


@dataclass(frozen=True, slots=True, order=True)
class InclusionOracle:
    object_id: str
    filters: tuple[str, ...]


@dataclass(frozen=True, slots=True, order=True)
class AssignmentOracle:
    child_id: str
    state_or_switch_id: str


@dataclass(frozen=True, slots=True)
class PathOracleSnapshot:
    object: ObjectOracle


@dataclass(frozen=True, slots=True)
class ObjectRowsOracleSnapshot:
    objects: tuple[ObjectOracle, ...]


@dataclass(frozen=True, slots=True)
class MissingPathOracleSnapshot:
    path: str


@dataclass(frozen=True, slots=True)
class ObjectPresenceOracleSnapshot:
    path: str
    expected_id: str | None
    by_path: ObjectOracle | None
    by_id: ObjectOracle | None


@dataclass(frozen=True, slots=True)
class RenameOracleSnapshot:
    object: ObjectOracle
    original_path_object: ObjectOracle | None


@dataclass(frozen=True, slots=True)
class FieldOracleSnapshot:
    object: ObjectOracle
    field: str
    value: Any


@dataclass(frozen=True, slots=True)
class ReferenceOracleSnapshot:
    source: ObjectOracle
    target: ObjectOracle
    reference: str
    target_id: str


@dataclass(frozen=True, slots=True)
class AudioOracleSnapshot:
    object: ObjectOracle | None
    wav_sha256: str


@dataclass(frozen=True, slots=True)
class SoundBankOracleSnapshot:
    soundbank: ObjectOracle
    included_object: ObjectOracle
    inclusions: tuple[InclusionOracle, ...]


@dataclass(frozen=True, slots=True)
class SwitchOracleSnapshot:
    switch_container: ObjectOracle
    switch_group: ObjectOracle
    state_or_switch: ObjectOracle
    direct_child: ObjectOracle
    reference_id: str
    assignments: tuple[AssignmentOracle, ...]


OraclePayload: TypeAlias = (
    PathOracleSnapshot
    | ObjectRowsOracleSnapshot
    | MissingPathOracleSnapshot
    | ObjectPresenceOracleSnapshot
    | RenameOracleSnapshot
    | FieldOracleSnapshot
    | ReferenceOracleSnapshot
    | AudioOracleSnapshot
    | SoundBankOracleSnapshot
    | SwitchOracleSnapshot
)


@dataclass(frozen=True, slots=True)
class OracleSnapshot:
    case_id: str
    payload: OraclePayload


@dataclass(frozen=True, slots=True)
class OracleComparison:
    case_id: str
    expectation: str
    passed: bool
    failures: tuple[str, ...]
    before: OracleSnapshot
    after: OracleSnapshot

    def assert_passed(self) -> None:
        if not self.passed:
            raise FixtureContractError(
                f"{self.case_id} oracle comparison failed for {self.expectation}: "
                + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class HiddenFixtureIdentities:
    """Runner-only fixture facts.  Never interpolate this object into prompts."""

    query_notes_id: str
    notes_target_id: str
    adversarial_target_id: str
    query_editor_id: str
    included_object_id: str
    soundbank_id: str
    switch_container_id: str
    switch_group_id: str
    state_or_switch_id: str
    direct_child_id: str
    delete_target_id: str
    rename_target_id: str
    property_target_id: str
    reference_source_id: str
    reference_target_id: str
    remove_switch_container_id: str
    remove_direct_child_id: str
    query_notes_path: str
    notes_target_path: str
    adversarial_target_path: str
    query_editor_path: str
    missing_query_path: str
    included_object_path: str
    soundbank_path: str
    switch_container_path: str
    switch_group_path: str
    state_or_switch_path: str
    direct_child_path: str
    create_parent_path: str
    create_name: str
    create_notes: str
    create_target_path: str
    delete_target_path: str
    rename_target_path: str
    rename_value: str
    rename_result_path: str
    property_target_path: str
    reference_source_path: str
    reference_target_path: str
    remove_switch_container_path: str
    remove_direct_child_path: str
    query_notes_baseline: str
    notes_target_baseline: str
    adversarial_target_baseline: str
    typed_import_path: str
    normalized_import_path: str
    audio_file: Path
    audio_file_sha256: str

    @property
    def setup_created_ids(self) -> tuple[str, ...]:
        return (
            self.query_notes_id,
            self.notes_target_id,
            self.adversarial_target_id,
            self.included_object_id,
            self.soundbank_id,
            self.switch_container_id,
            self.switch_group_id,
            self.state_or_switch_id,
            self.direct_child_id,
            self.delete_target_id,
            self.rename_target_id,
            self.property_target_id,
            self.reference_source_id,
            self.reference_target_id,
            self.remove_switch_container_id,
            self.remove_direct_child_id,
        )


@dataclass(frozen=True, slots=True)
class TrustedTransactionEvidence:
    lane: str
    purpose: str
    operation: str
    transaction_id: str
    artifact_hash: str
    state_dir: Path
    evidence_dir: Path


@dataclass(frozen=True, slots=True)
class _RuntimeConfig:
    version: str
    host: str
    port: int
    sandbox_path: Path
    private_root: Path
    runner_env: Mapping[str, str]
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class _CreateRecoveryCandidate:
    """Closed metadata used only to recover a verified create result."""

    role: str
    purpose: str
    path: str
    name: str
    object_type: str
    notes: str | None = None


class _PackagedGateway:
    """Run the production gateway through its packaged environment wrapper."""

    def __init__(
        self,
        *,
        binding: PackagedGatewayBinding,
        timeout_seconds: float,
    ) -> None:
        self.binding = binding
        self.timeout_seconds = timeout_seconds

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> Mapping[str, Any]:
        completed = subprocess.run(
            [sys.executable, str(self.binding.runner_path), "gateway.py", *tuple(argv)],
            cwd=self.binding.skill_root,
            env=dict(env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(60.0, self.timeout_seconds * 4),
            check=False,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise FixtureContractError(
                "packaged gateway did not emit exactly one JSON result: "
                f"exit={completed.returncode} stderr={completed.stderr[-2000:]!r}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise FixtureContractError("packaged gateway JSON result must be an object")
        if completed.returncode != 0:
            raise FixtureContractError(
                f"packaged gateway exited {completed.returncode}: {_safe_json(payload)}"
            )
        return dict(payload)


class _OwnedDirectReadCall:
    """Own one direct WaapiClient used only by the trusted oracle."""

    def __init__(self, *, host: str, port: int) -> None:
        try:
            from waapi import WaapiClient, WaapiRequestFailed  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - only a misconfigured real runner
            raise FixtureContractError("cannot import the packaged WAAPI client") from exc
        # The waapi-client default logs request failures and returns None.  A
        # trusted oracle must distinguish a proven exact-path absence from a
        # transport/query failure, so request exceptions are mandatory here.
        self._client = WaapiClient(url=f"ws://{host}:{port}/waapi", allow_exception=True)
        self._request_failed_type = WaapiRequestFailed
        self._closed = False

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        if self._closed:
            raise FixtureContractError("direct oracle read client is closed")
        try:
            return self._client.call(uri, dict(args), options=dict(options))
        except Exception as exc:
            if (
                isinstance(exc, self._request_failed_type)
                and _single_exact_object_lookup(uri, args)
                and _known_exact_object_absence(exc)
            ):
                return {"return": []}
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        disconnect = getattr(self._client, "disconnect", None)
        if callable(disconnect):
            disconnect()


class _TransactionRunner:
    def __init__(
        self,
        config: _RuntimeConfig,
        gateway: TrustedGateway,
        *,
        namespace: str,
        trusted_preview: TrustedPreview | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.namespace = namespace
        self._trusted_preview = trusted_preview
        self.records: list[TrustedTransactionEvidence] = []
        self._executed_setup_creates: set[str] = set()
        self._sequence = 0

    @property
    def executed_setup_create_purposes(self) -> frozenset[str]:
        """Creates whose trusted execute payload proves the mutation ran."""

        return frozenset(self._executed_setup_creates)

    def complete(
        self,
        *,
        lane: Literal["setup", "cleanup"],
        purpose: str,
        operation: str,
        arguments: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._sequence += 1
        slug = re.sub(r"[^a-z0-9]+", "-", purpose.casefold()).strip("-") or "transaction"
        transaction_root = (
            self.config.private_root
            / "trusted-fixture-transactions"
            / self.namespace
            / lane
            / f"{self._sequence:03d}-{slug}"
        )
        state_dir = transaction_root / "state"
        evidence_dir = transaction_root / "evidence"
        state_dir.mkdir(parents=True, exist_ok=False)
        evidence_dir.mkdir(parents=True, exist_ok=False)

        request = {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": self.config.version,
            "operation": operation,
            "arguments": copy.deepcopy(dict(arguments)),
        }
        preview = (
            self._trusted_preview(request, state_dir, evidence_dir)
            if self._trusted_preview is not None
            else create_typed_transaction_preview(
                lambda argv: self._call(
                    command=argv[0],
                    state_dir=state_dir,
                    evidence_dir=evidence_dir,
                    command_args=tuple(argv),
                ),
                request,
            )
        )
        if preview.get("state") != "awaiting_confirmation" or preview.get("executed") is not False:
            raise FixtureContractError(f"fixture preview did not await confirmation: {_safe_json(preview)}")
        transaction_id = _required_string(preview, "transaction_id", context="preview")
        artifact_hash = _required_sha256(preview, "artifact_hash", context="preview")
        summary = preview.get("preview_summary")
        if not isinstance(summary, Mapping) or summary.get("request") != request:
            raise FixtureContractError("fixture preview did not preserve the exact closed request")

        shown = self._call(
            command="transaction-show",
            state_dir=state_dir,
            evidence_dir=evidence_dir,
            command_args=("transaction-show", transaction_id, "--summary-only"),
        )
        shown_transaction_id = _required_string(
            shown,
            "transaction_id",
            context="transaction-show",
        )
        if (
            shown_transaction_id != transaction_id
            or shown.get("state") != "awaiting_confirmation"
            or shown.get("artifact_hash") != artifact_hash
        ):
            raise FixtureContractError(
                f"fixture transaction-show mismatch: {_safe_json(shown)}"
            )
        try:
            confirmation = validate_transaction_show_confirmation_payload(shown)
        except GatewayInvocationError as exc:
            raise FixtureContractError(
                f"fixture transaction-show has an invalid confirmation binding: {exc}"
            ) from exc
        confirmation_token = _required_string(
            confirmation,
            "token",
            context="transaction-show confirmation",
        )

        confirmed = self._call(
            command="confirm",
            state_dir=state_dir,
            evidence_dir=evidence_dir,
            command_args=(
                "confirm",
                shown_transaction_id,
                "--confirmation-token",
                confirmation_token,
            ),
        )
        confirmed_transaction_id = _required_string(
            confirmed,
            "transaction_id",
            context="confirm",
        )
        if (
            confirmed_transaction_id != shown_transaction_id
            or confirmed.get("state") != "confirmed"
            or confirmed.get("artifact_hash") != artifact_hash
        ):
            raise FixtureContractError(f"fixture confirmation mismatch: {_safe_json(confirmed)}")

        executed = self._call(
            command="execute",
            state_dir=state_dir,
            evidence_dir=evidence_dir,
            command_args=("execute", confirmed_transaction_id),
        )
        executed_transaction_id = _required_string(
            executed,
            "transaction_id",
            context="execute",
        )
        if (
            executed_transaction_id != confirmed_transaction_id
            or executed.get("state") != "executed_unverified"
            or executed.get("artifact_hash") != artifact_hash
            or executed.get("executed") is not True
        ):
            raise FixtureContractError(f"fixture execution mismatch: {_safe_json(executed)}")
        if lane == "setup" and operation == "object.create":
            # Preserve this narrow recovery proof before verify/result parsing:
            # a later failure must not lose an object WAAPI already created.
            self._executed_setup_creates.add(purpose)

        verified = self._call(
            command="verify",
            state_dir=state_dir,
            evidence_dir=evidence_dir,
            command_args=("verify", executed_transaction_id),
        )
        verified_transaction_id = _required_string(
            verified,
            "transaction_id",
            context="verify",
        )
        verification = verified.get("verification")
        assertions = verification.get("assertions") if isinstance(verification, Mapping) else None
        if (
            verified_transaction_id != executed_transaction_id
            or verified.get("state") != "verified"
            or verified.get("artifact_hash") != artifact_hash
            or verified.get("verified") is not True
            or not isinstance(assertions, list)
            or not assertions
            or not all(isinstance(item, Mapping) and item.get("passed") is True for item in assertions)
        ):
            raise FixtureContractError(f"fixture verification mismatch: {_safe_json(verified)}")

        self.records.append(
            TrustedTransactionEvidence(
                lane=lane,
                purpose=purpose,
                operation=operation,
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
                state_dir=state_dir,
                evidence_dir=evidence_dir,
            )
        )
        return executed

    def _call(
        self,
        *,
        command: str,
        state_dir: Path,
        evidence_dir: Path,
        command_args: Sequence[str],
    ) -> Mapping[str, Any]:
        argv = (
            "--host",
            self.config.host,
            "--port",
            str(self.config.port),
            "--version",
            self.config.version,
            "--timeout",
            str(self.config.timeout_seconds),
            "--state-dir",
            str(state_dir),
            "--evidence-dir",
            str(evidence_dir),
            *tuple(command_args),
        )
        try:
            payload = self.gateway(argv, self.config.runner_env)
        except FixtureContractError:
            raise
        except BaseException as exc:  # noqa: BLE001 - trusted adapter errors are contract failures
            raise FixtureContractError(
                f"trusted gateway adapter failed during {command}: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise FixtureContractError(f"trusted gateway {command} result must be a mapping")
        if payload.get("contract") != GATEWAY_RESULT_CONTRACT:
            raise FixtureContractError(f"trusted gateway {command} returned the wrong contract")
        if payload.get("ok") is not True:
            raise FixtureContractError(f"trusted gateway {command} failed: {_safe_json(payload)}")
        if payload.get("command") != command:
            raise FixtureContractError(
                f"trusted gateway command mismatch: expected {command!r}, got {payload.get('command')!r}"
            )
        return dict(payload)


class _OracleReader:
    def __init__(self, read_call: ReadCall, hidden: HiddenFixtureIdentities) -> None:
        self.read_call = read_call
        self.hidden = hidden

    def snapshot(self, case_id: str) -> OracleSnapshot:
        if case_id not in CASE_IDS:
            raise FixtureContractError(f"unknown semantic fixture case: {case_id!r}")
        if case_id == "C1":
            raise FixtureContractError("C1 is an offline catalog case and has no live Wwise oracle")
        if case_id == "Q1":
            payload: OraclePayload = PathOracleSnapshot(
                self._read_exact_id(self.hidden.query_notes_id)
            )
        elif case_id == "M1":
            payload = PathOracleSnapshot(self._read_exact_id(self.hidden.notes_target_id))
        elif case_id == "M2":
            payload = PathOracleSnapshot(self._read_exact_id(self.hidden.adversarial_target_id))
        elif case_id == "Q2":
            payload = ObjectRowsOracleSnapshot(
                (self._read_exact_id(self.hidden.direct_child_id),)
            )
        elif case_id == "Q3":
            payload = ObjectRowsOracleSnapshot(
                (self._read_exact_id(self.hidden.query_notes_id),)
            )
        elif case_id == "Q4":
            payload = ObjectRowsOracleSnapshot(self._read_query_editor_results())
        elif case_id == "Q5":
            rows = self._read_rows(
                {"from": {"path": [self.hidden.missing_query_path]}},
                fields=("id", "name", "type", "path"),
            )
            if rows:
                raise FixtureContractError("reserved Q5 exact path unexpectedly resolved")
            payload = MissingPathOracleSnapshot(self.hidden.missing_query_path)
        elif case_id == "M3":
            payload = ObjectPresenceOracleSnapshot(
                path=self.hidden.create_target_path,
                expected_id=None,
                by_path=self._read_optional_path(self.hidden.create_target_path),
                by_id=None,
            )
        elif case_id == "M4":
            payload = ObjectPresenceOracleSnapshot(
                path=self.hidden.delete_target_path,
                expected_id=self.hidden.delete_target_id,
                by_path=self._read_optional_path(self.hidden.delete_target_path),
                by_id=self.object_if_present(self.hidden.delete_target_id),
            )
        elif case_id == "M5":
            payload = RenameOracleSnapshot(
                object=self._read_exact_id(self.hidden.rename_target_id),
                original_path_object=self._read_optional_path(self.hidden.rename_target_path),
            )
        elif case_id == "M6":
            row = self._read_exact_row(
                self.hidden.property_target_id,
                extra_fields=("Volume",),
            )
            payload = FieldOracleSnapshot(
                object=self._object(row),
                field="Volume",
                value=_field_value(row, "Volume"),
            )
        elif case_id == "M7":
            row = self._read_exact_row(
                self.hidden.reference_source_id,
                extra_fields=(SWITCH_GROUP_REFERENCE,),
            )
            reference = _identity_value(_field_value(row, SWITCH_GROUP_REFERENCE))
            if reference is None:
                raise FixtureContractError("M7 reference oracle returned no target identity")
            payload = ReferenceOracleSnapshot(
                source=self._object(row),
                target=self._read_exact_id(self.hidden.reference_target_id),
                reference=SWITCH_GROUP_REFERENCE,
                target_id=reference,
            )
        elif case_id == "I1":
            rows = self._read_rows(
                {"from": {"path": [self.hidden.normalized_import_path]}},
                fields=("id", "name", "type", "path", "parent", "notes"),
            )
            if len(rows) > 1:
                raise FixtureContractError("audio oracle path resolved more than once")
            payload = AudioOracleSnapshot(
                object=self._object(rows[0]) if rows else None,
                wav_sha256=_sha256_file(self.hidden.audio_file),
            )
        elif case_id == "S1":
            payload = SoundBankOracleSnapshot(
                soundbank=self._read_exact_id(self.hidden.soundbank_id),
                included_object=self._read_exact_id(self.hidden.included_object_id),
                inclusions=self._read_inclusions(self.hidden.soundbank_id),
            )
        elif case_id == "W1":
            payload = self._read_switch_snapshot(
                container_id=self.hidden.switch_container_id,
                child_id=self.hidden.direct_child_id,
            )
        elif case_id == "W2":
            payload = self._read_switch_snapshot(
                container_id=self.hidden.remove_switch_container_id,
                child_id=self.hidden.remove_direct_child_id,
            )
        else:  # pragma: no cover - closed CASE_IDS above makes this unreachable
            raise FixtureContractError(f"no oracle adapter for case {case_id!r}")
        return OracleSnapshot(case_id=case_id, payload=payload)

    def object_if_present(self, object_id: str) -> ObjectOracle | None:
        rows = self._read_rows(
            {"from": {"id": [object_id]}},
            fields=("id", "name", "type", "path", "parent", "notes"),
        )
        if len(rows) > 1:
            raise FixtureContractError(f"cleanup identity {object_id!r} resolved more than once")
        return self._object(rows[0]) if rows else None

    def audio_object_if_present(self) -> ObjectOracle | None:
        rows = self._read_rows(
            {"from": {"path": [self.hidden.normalized_import_path]}},
            fields=("id", "name", "type", "path", "parent", "notes"),
        )
        if len(rows) > 1:
            raise FixtureContractError("cleanup audio path resolved more than once")
        return self._object(rows[0]) if rows else None

    def object_at_path_if_present(self, path: str) -> ObjectOracle | None:
        return self._read_optional_path(path)

    def _read_exact_id(
        self,
        object_id: str,
        *,
        extra_fields: Sequence[str] = (),
    ) -> ObjectOracle:
        row = self._read_exact_row(object_id, extra_fields=extra_fields)
        value = self._object(row)
        if not _same_identity(value.id, object_id):
            raise FixtureContractError(f"oracle identity changed for {object_id!r}: {value.id!r}")
        return value

    def _read_exact_row(
        self,
        object_id: str,
        *,
        extra_fields: Sequence[str] = (),
    ) -> Mapping[str, Any]:
        fields = ("id", "name", "type", "path", "parent", "notes", *tuple(extra_fields))
        rows = self._read_rows({"from": {"id": [object_id]}}, fields=fields)
        if len(rows) != 1:
            raise FixtureContractError(f"oracle identity {object_id!r} did not resolve exactly once")
        return rows[0]

    def _read_optional_path(self, path: str) -> ObjectOracle | None:
        rows = self._read_rows(
            {"from": {"path": [path]}},
            fields=("id", "name", "type", "path", "parent", "notes"),
        )
        if len(rows) > 1:
            raise FixtureContractError(f"oracle path {path!r} resolved more than once")
        return self._object(rows[0]) if rows else None

    def _read_switch_snapshot(self, *, container_id: str, child_id: str) -> SwitchOracleSnapshot:
        row = self._read_exact_row(container_id, extra_fields=(SWITCH_GROUP_REFERENCE,))
        reference = _identity_value(_field_value(row, SWITCH_GROUP_REFERENCE))
        if reference is None:
            raise FixtureContractError("SwitchContainer reference oracle returned no identity")
        return SwitchOracleSnapshot(
            switch_container=self._object(row),
            switch_group=self._read_exact_id(self.hidden.switch_group_id),
            state_or_switch=self._read_exact_id(self.hidden.state_or_switch_id),
            direct_child=self._read_exact_id(child_id),
            reference_id=reference,
            assignments=self._read_assignments(container_id),
        )

    def _read_rows(
        self,
        args: Mapping[str, Any],
        *,
        fields: Sequence[str],
    ) -> list[Mapping[str, Any]]:
        result = self._call_read(
            "ak.wwise.core.object.get",
            args,
            {"return": list(fields)},
        )
        rows = result.get("return")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise FixtureContractError("object.get oracle result must contain a mapping array in 'return'")
        return [dict(row) for row in rows]

    def _read_query_editor_results(self) -> tuple[ObjectOracle, ...]:
        rows = self._read_rows(
            {
                "waql": (
                    f'from query "{self.hidden.query_editor_id}" '
                    f"take {QUERY_RESULT_LIMIT}"
                )
            },
            fields=("id", "name", "type", "path"),
        )
        if len(rows) > QUERY_RESULT_LIMIT:
            raise FixtureContractError("Query Editor oracle exceeded its closed take limit")
        return tuple(self._object(row) for row in rows)

    def _read_inclusions(self, soundbank_id: str) -> tuple[InclusionOracle, ...]:
        result = self._call_read(
            "ak.wwise.core.soundbank.getInclusions",
            {"soundbank": soundbank_id},
            {},
        )
        rows = result.get("inclusions")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise FixtureContractError("getInclusions oracle result must contain an inclusion array")
        normalized: list[InclusionOracle] = []
        for row in rows:
            object_id = _identity_value(row.get("object"))
            if object_id is None:
                raise FixtureContractError(f"inclusion has no object identity: {_safe_json(row)}")
            raw_filters = row.get("filter", row.get("filters"))
            if not isinstance(raw_filters, list) or not all(
                isinstance(item, str) and item for item in raw_filters
            ):
                raise FixtureContractError(f"inclusion has invalid filters: {_safe_json(row)}")
            normalized.append(
                InclusionOracle(
                    object_id=object_id.casefold(),
                    filters=tuple(sorted({item.casefold() for item in raw_filters})),
                )
            )
        return tuple(sorted(normalized))

    def _read_assignments(self, switch_container_id: str) -> tuple[AssignmentOracle, ...]:
        result = self._call_read(
            "ak.wwise.core.switchContainer.getAssignments",
            {"id": switch_container_id},
            {},
        )
        rows = result.get("return")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise FixtureContractError("getAssignments oracle result must contain a mapping array")
        normalized: list[AssignmentOracle] = []
        for row in rows:
            child_id = _identity_value(row.get("child"))
            state_id = _identity_value(row.get("stateOrSwitch"))
            if child_id is None or state_id is None:
                raise FixtureContractError(f"assignment has incomplete identities: {_safe_json(row)}")
            normalized.append(
                AssignmentOracle(
                    child_id=child_id.casefold(),
                    state_or_switch_id=state_id.casefold(),
                )
            )
        return tuple(sorted(normalized))

    def _call_read(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            result = self.read_call(uri, dict(args), dict(options))
        except FixtureContractError:
            raise
        except BaseException as exc:  # noqa: BLE001 - adapter failure is a closed oracle failure
            raise FixtureContractError(
                f"direct read adapter failed for {uri}: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(result, Mapping):
            raise FixtureContractError(f"direct read adapter for {uri} must return a mapping")
        return dict(result)

    @staticmethod
    def _object(row: Mapping[str, Any]) -> ObjectOracle:
        object_id = _required_string(row, "id", context="object readback")
        name = _required_string(row, "name", context="object readback")
        object_type = _required_string(row, "type", context="object readback")
        path = _required_string(row, "path", context="object readback")
        notes = row.get("notes", row.get("@Notes"))
        if notes is not None and not isinstance(notes, str):
            raise FixtureContractError("object notes readback must be a string or null")
        parent = _identity_value(row.get("parent"))
        return ObjectOracle(object_id, name, object_type, path, notes, parent)


class EvalFixtureBundle:
    """One runner-owned fixture graph shared by sessions for one Wwise version."""

    def __init__(
        self,
        *,
        config: _RuntimeConfig,
        prompt_values: Mapping[str, Mapping[str, str]],
        hidden: HiddenFixtureIdentities,
        transaction_runner: _TransactionRunner,
        oracle: _OracleReader,
        owned_reader: _OwnedDirectReadCall | None,
        fixture_root: Path,
    ) -> None:
        self.version = config.version
        self.host = config.host
        self.port = config.port
        self.sandbox_path = config.sandbox_path
        self.private_root = config.private_root
        self.hidden = hidden
        self._config = config
        self._prompt_values = MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in prompt_values.items()}
        )
        self._transaction_runner = transaction_runner
        self._oracle = oracle
        self._owned_reader = owned_reader
        self._fixture_root = fixture_root
        self._baselines: dict[str, OracleSnapshot] = {}
        self._topic_probe_ids: dict[str, str] = {}
        self._closed = False

    @property
    def transactions(self) -> tuple[TrustedTransactionEvidence, ...]:
        return tuple(self._transaction_runner.records)

    def prompt_values(self, case_id: str, *, adapter: str | None = None) -> dict[str, str]:
        if case_id not in CASE_IDS:
            raise FixtureContractError(f"unknown semantic fixture case: {case_id!r}")
        if adapter is not None:
            expected_adapter = CASE_ADAPTERS[case_id]
            if adapter != expected_adapter:
                raise FixtureContractError(
                    f"case {case_id} requires fixture adapter {expected_adapter!r}, got {adapter!r}"
                )
        values = dict(self._prompt_values[case_id])
        forbidden = sorted(key for key in values if _GUID_KEY_RE.search(key))
        if forbidden:
            raise FixtureContractError(f"prompt fixture unexpectedly exposes identity fields: {forbidden}")
        if not all(isinstance(key, str) and isinstance(value, str) and value for key, value in values.items()):
            raise FixtureContractError(f"prompt fixture {case_id} contains invalid values")
        return values

    def snapshot(self, case_id: str) -> OracleSnapshot:
        self._require_open()
        if (
            case_id == "Q4"
            and _query_editor_oracle_mode(self.version) == "validated-baseline"
        ):
            baseline = self._baselines.get(case_id)
            if baseline is None:
                raise FixtureContractError(
                    f"Wwise {self.version} Q4 snapshot requires a live, validated baseline"
                )
            return baseline
        return self._oracle.snapshot(case_id)

    def baseline(self, case_id: str) -> OracleSnapshot:
        if case_id not in LIVE_CASE_IDS:
            if case_id in CASE_IDS:
                raise FixtureContractError(f"{case_id} has no live baseline")
            raise FixtureContractError(f"unknown semantic fixture case: {case_id!r}")
        baseline = self._baselines.get(case_id)
        if baseline is None:
            raise FixtureContractError(f"baseline for {case_id} has not been captured")
        return baseline

    def capture_baselines(self) -> None:
        self._require_open()
        representatives = (
            "Q1", "Q2", "Q3", "Q4", "Q5", "M1", "M2", "M3", "M4", "M5", "M6", "M7",
            "I1", "S1", "W1", "W2",
        )
        q4_mode = _query_editor_oracle_mode(self.version)
        if q4_mode == "validated-baseline" and "Q4" in self._baselines:
            raise FixtureContractError(
                f"Wwise {self.version} Q4 baseline may only be captured once"
            )
        captured = {
            case_id: (
                self._oracle.snapshot(case_id)
                if case_id == "Q4" and q4_mode == "validated-baseline"
                else self.snapshot(case_id)
            )
            for case_id in representatives
        }
        self._validate_initial_graph(captured)
        self._baselines = {
            "Q1": captured["Q1"],
            "Q2": captured["Q2"],
            "Q3": captured["Q3"],
            "Q4": captured["Q4"],
            "Q5": captured["Q5"],
            "M1": captured["M1"],
            "M2": captured["M2"],
            "M3": captured["M3"],
            "M4": captured["M4"],
            "M5": captured["M5"],
            "M6": captured["M6"],
            "M7": captured["M7"],
            "I1": captured["I1"],
            "S1": captured["S1"],
            "W1": captured["W1"],
            "W2": captured["W2"],
        }

    def compare(
        self,
        case_id: str,
        before: OracleSnapshot,
        after: OracleSnapshot,
        *,
        expectation: Literal["unchanged", "applied"],
    ) -> OracleComparison:
        if case_id not in LIVE_CASE_IDS:
            if case_id in CASE_IDS:
                raise FixtureContractError(f"{case_id} has no live oracle comparison")
            raise FixtureContractError(f"unknown semantic fixture case: {case_id!r}")
        if expectation not in _EXPECTATIONS:
            raise FixtureContractError(f"unknown oracle expectation: {expectation!r}")
        if before.case_id != case_id or after.case_id != case_id:
            raise FixtureContractError("oracle snapshots must belong to the compared case")
        if type(before.payload) is not type(after.payload):
            raise FixtureContractError("oracle snapshot payload types changed")

        failures: list[str] = []
        if expectation == "unchanged":
            if before.payload != after.payload:
                failures.append("target snapshot changed")
        else:
            self._compare_applied(case_id, before.payload, after.payload, failures)
        return OracleComparison(
            case_id=case_id,
            expectation=expectation,
            passed=not failures,
            failures=tuple(failures),
            before=before,
            after=after,
        )

    def assert_comparison(
        self,
        case_id: str,
        before: OracleSnapshot,
        after: OracleSnapshot,
        *,
        expectation: Literal["unchanged", "applied"],
    ) -> None:
        self.compare(case_id, before, after, expectation=expectation).assert_passed()

    def publish_object_created_probe(self, name: str) -> dict[str, Any]:
        """Create and remove one runner-owned object through packaged transactions.

        The semantic runner starts this method only after the broker accepts the
        model's exact ``wait-topic`` argv.  The object name is prompt-visible,
        while its identity remains private to this trusted fixture bundle.
        """

        self._require_open()
        if not isinstance(name, str) or not re.fullmatch(r"WAAPI_SEM_TOPIC_[A-Za-z0-9_-]{8,80}", name):
            raise FixtureContractError("topic probe name violates the runner-owned namespace")
        target_path = f"{self.hidden.create_parent_path}\\{name}"
        if self._oracle.object_at_path_if_present(target_path) is not None:
            raise FixtureContractError("topic probe path was not empty before publication")

        executed = self._transaction_runner.complete(
            lane="setup",
            purpose=f"publish-object-created-{name}",
            operation="object.create",
            arguments={
                "parent": {"kind": "path", "value": self.hidden.create_parent_path},
                "type": "ActorMixer",
                "name": name,
                "notes": "runner-owned semantic topic probe",
            },
        )
        dispatch_result = executed.get("dispatch_result")
        result = dispatch_result.get("result") if isinstance(dispatch_result, Mapping) else None
        if not isinstance(result, Mapping):
            raise FixtureContractError("topic probe create returned no result object")
        object_id = _required_string(result, "id", context="topic probe create result")
        self._topic_probe_ids[name] = object_id

        current = self._oracle.object_if_present(object_id)
        if (
            current is None
            or current.name != name
            or current.path != target_path
            or current.type != _actor_mixer_reflected_type(self.version)
        ):
            raise FixtureContractError("topic probe create readback did not match the closed request")

        self._delete_object(f"topic-probe-{name}", object_id)
        if self._oracle.object_if_present(object_id) is not None:
            raise FixtureContractError("topic probe remained after verified cleanup")
        self._topic_probe_ids.pop(name, None)
        return {
            "name": name,
            "path": target_path,
            "object_id": object_id,
            "created": True,
            "deleted": True,
        }

    def cleanup(self) -> None:
        if self._closed:
            return
        failures: list[str] = []
        for probe_name, object_id in tuple(self._topic_probe_ids.items()):
            try:
                self._delete_object(f"pending-topic-probe-{probe_name}", object_id)
                self._topic_probe_ids.pop(probe_name, None)
            except BaseException as exc:  # noqa: BLE001 - continue with all fixture cleanup
                failures.append(f"topic-probe-{probe_name}: {type(exc).__name__}: {exc}")
        try:
            audio = self._oracle.audio_object_if_present()
            if audio is not None:
                if audio.path != self.hidden.normalized_import_path or audio.type != "Sound":
                    raise FixtureContractError("refusing to delete an unexpected object at the reserved audio path")
                self._delete_object("audio-target", audio.id)
        except BaseException as exc:  # noqa: BLE001 - reader and file cleanup must still close
            failures.append(f"audio-target: {type(exc).__name__}: {exc}")

        try:
            created = self._oracle.object_at_path_if_present(self.hidden.create_target_path)
            if created is not None:
                if (
                    created.path != self.hidden.create_target_path
                    or created.name != self.hidden.create_name
                    or created.type != _actor_mixer_reflected_type(self.version)
                    or created.notes != self.hidden.create_notes
                ):
                    raise FixtureContractError("refusing to delete unexpected object at M3 reserved path")
                self._delete_object("M3-created-target", created.id)
        except BaseException as exc:  # noqa: BLE001
            failures.append(f"M3-created-target: {type(exc).__name__}: {exc}")

        try:
            switch_snapshot = self._oracle.snapshot("W1").payload
            if not isinstance(switch_snapshot, SwitchOracleSnapshot):
                raise FixtureContractError("cleanup Switch oracle returned the wrong payload")
            expected_assignment = AssignmentOracle(
                self.hidden.direct_child_id.casefold(),
                self.hidden.state_or_switch_id.casefold(),
            )
            if switch_snapshot.assignments:
                if switch_snapshot.assignments != (expected_assignment,):
                    raise FixtureContractError("refusing cleanup with unexpected SwitchContainer assignments")
                self._transaction_runner.complete(
                    lane="cleanup",
                    purpose="remove-switch-assignment",
                    operation="switchContainer.removeAssignment",
                    arguments={
                        "switch_container": {
                            "kind": "id",
                            "value": self.hidden.switch_container_id,
                        },
                        "child": {"kind": "id", "value": self.hidden.direct_child_id},
                        "state_or_switch": {
                            "kind": "id",
                            "value": self.hidden.state_or_switch_id,
                        },
                    },
                )
        except BaseException as exc:  # noqa: BLE001 - object deletions must still be attempted
            failures.append(f"switch-assignment: {type(exc).__name__}: {exc}")

        try:
            remove_snapshot = self._oracle.snapshot("W2").payload
            if not isinstance(remove_snapshot, SwitchOracleSnapshot):
                raise FixtureContractError("cleanup W2 oracle returned the wrong payload")
            expected_remove_assignment = AssignmentOracle(
                self.hidden.remove_direct_child_id.casefold(),
                self.hidden.state_or_switch_id.casefold(),
            )
            if remove_snapshot.assignments:
                if remove_snapshot.assignments != (expected_remove_assignment,):
                    raise FixtureContractError("refusing cleanup with unexpected W2 assignments")
                self._transaction_runner.complete(
                    lane="cleanup",
                    purpose="remove-preexisting-switch-assignment",
                    operation="switchContainer.removeAssignment",
                    arguments={
                        "switch_container": {
                            "kind": "id",
                            "value": self.hidden.remove_switch_container_id,
                        },
                        "child": {"kind": "id", "value": self.hidden.remove_direct_child_id},
                        "state_or_switch": {
                            "kind": "id",
                            "value": self.hidden.state_or_switch_id,
                        },
                    },
                )
        except BaseException as exc:  # noqa: BLE001
            failures.append(f"remove-switch-assignment: {type(exc).__name__}: {exc}")

        # Every deletion is by a hidden GUID returned by this runner's own setup.
        # Leaves precede their parents; referenced containers precede their groups.
        cleanup_order = (
            ("remove-direct-child", self.hidden.remove_direct_child_id),
            ("remove-switch-container", self.hidden.remove_switch_container_id),
            ("reference-source", self.hidden.reference_source_id),
            ("reference-target", self.hidden.reference_target_id),
            ("property-target", self.hidden.property_target_id),
            ("rename-target", self.hidden.rename_target_id),
            ("delete-target", self.hidden.delete_target_id),
            ("switch-direct-child", self.hidden.direct_child_id),
            ("switch-container", self.hidden.switch_container_id),
            ("state-or-switch", self.hidden.state_or_switch_id),
            ("switch-group", self.hidden.switch_group_id),
            ("soundbank", self.hidden.soundbank_id),
            ("included-object", self.hidden.included_object_id),
            ("M2-adversarial-target", self.hidden.adversarial_target_id),
            ("M1-notes-target", self.hidden.notes_target_id),
            ("query-notes-target", self.hidden.query_notes_id),
        )
        for purpose, object_id in cleanup_order:
            try:
                self._delete_object(purpose, object_id)
            except BaseException as exc:  # noqa: BLE001 - attempt every disposable object
                failures.append(f"{purpose}: {type(exc).__name__}: {exc}")
        # Local files and the owned read client are released even when one or
        # more live cleanup steps failed; the accumulated error is raised last.
        try:
            if self.hidden.audio_file.exists():
                if self.hidden.audio_file.is_symlink() or not self.hidden.audio_file.is_file():
                    raise FixtureContractError("refusing to remove a non-regular fixture WAV")
                self.hidden.audio_file.unlink()
            if self._fixture_root.exists():
                shutil.rmtree(self._fixture_root)
        except BaseException as exc:  # noqa: BLE001
            failures.append(f"fixture-files: {type(exc).__name__}: {exc}")
        try:
            if self._owned_reader is not None:
                self._owned_reader.close()
        except BaseException as exc:  # noqa: BLE001
            failures.append(f"read-client: {type(exc).__name__}: {exc}")
        self._closed = True
        if failures:
            raise FixtureContractError("fixture cleanup failed: " + "; ".join(failures))

    close = cleanup

    def __enter__(self) -> "EvalFixtureBundle":
        self._require_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.cleanup()
        except BaseException as cleanup_exc:  # noqa: BLE001
            if exc is not None:
                exc.add_note(str(cleanup_exc))
                return
            raise

    def _delete_object(self, purpose: str, object_id: str) -> None:
        current = self._oracle.object_if_present(object_id)
        if current is None:
            return
        self._transaction_runner.complete(
            lane="cleanup",
            purpose=f"delete-{purpose}",
            operation="object.delete",
            arguments={"object": {"kind": "id", "value": object_id}},
        )
        if self._oracle.object_if_present(object_id) is not None:
            raise FixtureContractError(f"cleanup object {object_id!r} still resolves after verified delete")

    def _validate_initial_graph(self, snapshots: Mapping[str, OracleSnapshot]) -> None:
        query = snapshots["Q1"].payload
        notes_target = snapshots["M1"].payload
        adversarial_target = snapshots["M2"].payload
        children = snapshots["Q2"].payload
        search = snapshots["Q3"].payload
        query_editor = snapshots["Q4"].payload
        missing = snapshots["Q5"].payload
        audio = snapshots["I1"].payload
        soundbank = snapshots["S1"].payload
        switch = snapshots["W1"].payload
        create = snapshots["M3"].payload
        delete = snapshots["M4"].payload
        rename = snapshots["M5"].payload
        property_snapshot = snapshots["M6"].payload
        reference = snapshots["M7"].payload
        remove = snapshots["W2"].payload
        if not isinstance(query, PathOracleSnapshot):
            raise FixtureContractError("Q1 baseline returned the wrong oracle payload")
        expected_query = {
            "id": self.hidden.query_notes_id,
            "path": self.hidden.query_notes_path,
            "type": _actor_mixer_reflected_type(self.version),
        }
        if (
            not _same_identity(query.object.id, expected_query["id"])
            or query.object.path != expected_query["path"]
            or query.object.type != expected_query["type"]
            or query.object.notes != self.hidden.query_notes_baseline
        ):
            raise FixtureContractError("query/notes fixture readback does not match setup evidence")
        if (
            not isinstance(notes_target, PathOracleSnapshot)
            or not _same_identity(notes_target.object.id, self.hidden.notes_target_id)
            or notes_target.object.path != self.hidden.notes_target_path
            or notes_target.object.notes != self.hidden.notes_target_baseline
        ):
            raise FixtureContractError("M1 dedicated Notes target does not match setup evidence")
        if (
            not isinstance(adversarial_target, PathOracleSnapshot)
            or not _same_identity(adversarial_target.object.id, self.hidden.adversarial_target_id)
            or adversarial_target.object.path != self.hidden.adversarial_target_path
            or adversarial_target.object.notes != self.hidden.adversarial_target_baseline
        ):
            raise FixtureContractError("M2 dedicated adversarial target does not match setup evidence")
        if (
            not isinstance(children, ObjectRowsOracleSnapshot)
            or len(children.objects) != 1
            or not _same_identity(children.objects[0].id, self.hidden.direct_child_id)
            or not _same_identity(children.objects[0].parent_id or "", self.hidden.switch_container_id)
        ):
            raise FixtureContractError("Q2 direct-children fixture does not match the closed parent")
        if (
            not isinstance(search, ObjectRowsOracleSnapshot)
            or len(search.objects) != 1
            or not _same_identity(search.objects[0].id, self.hidden.query_notes_id)
        ):
            raise FixtureContractError("Q3 name-search fixture does not match the unique target")
        if (
            not isinstance(query_editor, ObjectRowsOracleSnapshot)
            or not query_editor.objects
            or len(query_editor.objects) > QUERY_RESULT_LIMIT
            or any(item.type != "Sound" for item in query_editor.objects)
        ):
            raise FixtureContractError("Q4 Sound = SFX Query returned an invalid bounded result set")
        if (
            not isinstance(missing, MissingPathOracleSnapshot)
            or missing.path != self.hidden.missing_query_path
        ):
            raise FixtureContractError("Q5 missing-path fixture was not proven absent")
        if not isinstance(audio, AudioOracleSnapshot) or audio.object is not None:
            raise FixtureContractError("reserved audio target must be absent before semantic evaluation")
        if audio.wav_sha256 != self.hidden.audio_file_sha256:
            raise FixtureContractError("fixture WAV changed before semantic evaluation")
        if not isinstance(soundbank, SoundBankOracleSnapshot):
            raise FixtureContractError("S1 baseline returned the wrong oracle payload")
        if not _same_identity(soundbank.soundbank.id, self.hidden.soundbank_id):
            raise FixtureContractError("SoundBank fixture identity changed")
        if not _same_identity(soundbank.included_object.id, self.hidden.included_object_id):
            raise FixtureContractError("included object fixture identity changed")
        if soundbank.inclusions:
            raise FixtureContractError("new semantic-eval SoundBank must start with no inclusions")
        if not isinstance(switch, SwitchOracleSnapshot):
            raise FixtureContractError("W1 baseline returned the wrong oracle payload")
        self._validate_switch_graph(
            switch,
            expected_container_id=self.hidden.switch_container_id,
            expected_child_id=self.hidden.direct_child_id,
            require_assignment=False,
        )
        if not isinstance(create, ObjectPresenceOracleSnapshot) or create.by_path is not None:
            raise FixtureContractError("M3 reserved create target must be absent initially")
        if (
            not isinstance(delete, ObjectPresenceOracleSnapshot)
            or delete.by_path is None
            or delete.by_id is None
            or not _same_identity(delete.by_path.id, self.hidden.delete_target_id)
            or delete.by_path != delete.by_id
        ):
            raise FixtureContractError("M4 disposable delete target is invalid")
        if (
            not isinstance(rename, RenameOracleSnapshot)
            or not _same_identity(rename.object.id, self.hidden.rename_target_id)
            or rename.object.path != self.hidden.rename_target_path
            or rename.original_path_object != rename.object
        ):
            raise FixtureContractError("M5 dedicated rename target is invalid")
        if (
            not isinstance(property_snapshot, FieldOracleSnapshot)
            or not _same_identity(property_snapshot.object.id, self.hidden.property_target_id)
            or property_snapshot.field != "Volume"
            or isinstance(property_snapshot.value, bool)
            or not isinstance(property_snapshot.value, (int, float))
            or float(property_snapshot.value) == -3.0
        ):
            raise FixtureContractError("M6 Volume baseline must be numeric and differ from -3.0")
        if (
            not isinstance(reference, ReferenceOracleSnapshot)
            or not _same_identity(reference.source.id, self.hidden.reference_source_id)
            or not _same_identity(reference.target.id, self.hidden.reference_target_id)
            or not _same_identity(reference.target_id, self.hidden.switch_group_id)
        ):
            raise FixtureContractError("M7 reference baseline is invalid")
        if not isinstance(remove, SwitchOracleSnapshot):
            raise FixtureContractError("W2 baseline returned the wrong oracle payload")
        self._validate_switch_graph(
            remove,
            expected_container_id=self.hidden.remove_switch_container_id,
            expected_child_id=self.hidden.remove_direct_child_id,
            require_assignment=True,
        )

    def _compare_applied(
        self,
        case_id: str,
        before: OraclePayload,
        after: OraclePayload,
        failures: list[str],
    ) -> None:
        if case_id in QUERY_CASE_IDS or case_id == "M2":
            raise FixtureContractError(f"case {case_id} does not define an applied transition")
        if case_id == "M1":
            if not isinstance(before, PathOracleSnapshot) or not isinstance(after, PathOracleSnapshot):
                raise FixtureContractError("M1 requires path snapshots")
            expected_notes = self.prompt_values("M1")["notes_value"]
            if _object_without_notes(before.object) != _object_without_notes(after.object):
                failures.append("notes mutation changed object identity or hierarchy")
            if before.object.notes == expected_notes:
                failures.append("notes already matched the requested value before execution")
            if after.object.notes != expected_notes:
                failures.append("notes value does not match the closed M1 fixture")
            return
        if case_id == "M3":
            if not isinstance(before, ObjectPresenceOracleSnapshot) or not isinstance(after, ObjectPresenceOracleSnapshot):
                raise FixtureContractError("M3 requires object-presence snapshots")
            if before.by_path is not None or before.by_id is not None:
                failures.append("reserved create path was occupied before execution")
            created = after.by_path
            if created is None:
                failures.append("created object is absent at the reserved path")
            elif (
                created.path != self.hidden.create_target_path
                or created.name != self.hidden.create_name
                or created.type != _actor_mixer_reflected_type(self.version)
                or created.notes != self.hidden.create_notes
            ):
                failures.append("created object metadata does not match the closed M3 request")
            return
        if case_id == "M4":
            if not isinstance(before, ObjectPresenceOracleSnapshot) or not isinstance(after, ObjectPresenceOracleSnapshot):
                raise FixtureContractError("M4 requires object-presence snapshots")
            if before.by_path is None or before.by_id is None:
                failures.append("delete target was absent before execution")
            if after.by_path is not None or after.by_id is not None:
                failures.append("deleted GUID or reserved path still resolves")
            return
        if case_id == "M5":
            if not isinstance(before, RenameOracleSnapshot) or not isinstance(after, RenameOracleSnapshot):
                raise FixtureContractError("M5 requires rename snapshots")
            if not _same_identity(before.object.id, after.object.id):
                failures.append("rename changed the object GUID")
            if before.object.path != self.hidden.rename_target_path:
                failures.append("rename target did not start at its closed original path")
            if after.object.path != self.hidden.rename_result_path or after.object.name != self.hidden.rename_value:
                failures.append("renamed object did not reach the exact requested name/path")
            if after.original_path_object is not None:
                failures.append("old rename path still resolves after execution")
            return
        if case_id == "M6":
            if not isinstance(before, FieldOracleSnapshot) or not isinstance(after, FieldOracleSnapshot):
                raise FixtureContractError("M6 requires typed field snapshots")
            if _object_without_notes(before.object) != _object_without_notes(after.object):
                failures.append("property mutation changed object identity or hierarchy")
            if isinstance(after.value, bool) or not isinstance(after.value, (int, float)):
                failures.append("Volume readback is not numeric")
            elif float(after.value) != -3.0:
                failures.append("Volume readback does not equal numeric -3.0")
            return
        if case_id == "M7":
            if not isinstance(before, ReferenceOracleSnapshot) or not isinstance(after, ReferenceOracleSnapshot):
                raise FixtureContractError("M7 requires reference snapshots")
            if before.source != after.source or before.target != after.target:
                failures.append("reference mutation changed source/target object identity")
            if not _same_identity(before.target_id, self.hidden.switch_group_id):
                failures.append("reference source did not start at the independent baseline group")
            if not _same_identity(after.target_id, self.hidden.reference_target_id):
                failures.append("reference readback does not target the exact M7 group")
            return
        if case_id == "I1":
            if not isinstance(before, AudioOracleSnapshot) or not isinstance(after, AudioOracleSnapshot):
                raise FixtureContractError("I1 requires audio snapshots")
            if before.object is not None:
                failures.append("audio target was present before import")
            if after.object is None:
                failures.append("audio target is absent after import")
            else:
                expected_name = self.hidden.normalized_import_path.rsplit("\\", 1)[-1]
                if after.object.path != self.hidden.normalized_import_path:
                    failures.append("imported object path does not match typed-path normalization")
                if after.object.name != expected_name or after.object.type != "Sound":
                    failures.append("imported object identity fields are incorrect")
                if after.object.notes != self.prompt_values("I1")["import_notes"]:
                    failures.append("imported notes do not match the closed I1 fixture")
            if before.wav_sha256 != self.hidden.audio_file_sha256:
                failures.append("fixture WAV was already changed before import")
            if after.wav_sha256 != self.hidden.audio_file_sha256:
                failures.append("fixture WAV changed during import")
            return
        if case_id == "S1":
            if not isinstance(before, SoundBankOracleSnapshot) or not isinstance(after, SoundBankOracleSnapshot):
                raise FixtureContractError("S1 requires SoundBank snapshots")
            if before.soundbank != after.soundbank or before.included_object != after.included_object:
                failures.append("SoundBank workflow changed fixture object identity")
            expected = (
                InclusionOracle(
                    self.hidden.included_object_id.casefold(),
                    ("media", "structures"),
                ),
            )
            if before.inclusions:
                failures.append("SoundBank inclusions were not empty before execution")
            if after.inclusions != expected:
                failures.append("complete normalized SoundBank inclusions do not match the closed S1 request")
            return
        if case_id == "W1":
            if not isinstance(before, SwitchOracleSnapshot) or not isinstance(after, SwitchOracleSnapshot):
                raise FixtureContractError("W1 requires Switch snapshots")
            if (
                before.switch_container != after.switch_container
                or before.switch_group != after.switch_group
                or before.state_or_switch != after.state_or_switch
                or before.direct_child != after.direct_child
                or not _same_identity(before.reference_id, after.reference_id)
            ):
                failures.append("Switch workflow changed fixture identities or relationships")
            if before.assignments:
                failures.append("SwitchContainer assignment already existed before execution")
            try:
                self._validate_switch_graph(
                    after,
                    expected_container_id=self.hidden.switch_container_id,
                    expected_child_id=self.hidden.direct_child_id,
                    require_assignment=True,
                )
            except FixtureContractError as exc:
                failures.append(str(exc))
            return
        if case_id == "W2":
            if not isinstance(before, SwitchOracleSnapshot) or not isinstance(after, SwitchOracleSnapshot):
                raise FixtureContractError("W2 requires Switch snapshots")
            if (
                before.switch_container != after.switch_container
                or before.switch_group != after.switch_group
                or before.state_or_switch != after.state_or_switch
                or before.direct_child != after.direct_child
                or not _same_identity(before.reference_id, after.reference_id)
            ):
                failures.append("removeAssignment changed fixture identities or relationships")
            try:
                self._validate_switch_graph(
                    before,
                    expected_container_id=self.hidden.remove_switch_container_id,
                    expected_child_id=self.hidden.remove_direct_child_id,
                    require_assignment=True,
                )
                self._validate_switch_graph(
                    after,
                    expected_container_id=self.hidden.remove_switch_container_id,
                    expected_child_id=self.hidden.remove_direct_child_id,
                    require_assignment=False,
                )
            except FixtureContractError as exc:
                failures.append(str(exc))
            return
        raise FixtureContractError(f"no applied oracle adapter for case {case_id!r}")

    def _validate_switch_graph(
        self,
        snapshot: SwitchOracleSnapshot,
        *,
        expected_container_id: str,
        expected_child_id: str,
        require_assignment: bool,
    ) -> None:
        failures: list[str] = []
        if snapshot.switch_container.type != "SwitchContainer":
            failures.append("fixture container is not a SwitchContainer")
        if snapshot.switch_group.type != "SwitchGroup":
            failures.append("fixture group is not a SwitchGroup")
        if snapshot.state_or_switch.type != "Switch":
            failures.append("fixture state_or_switch is not a Switch")
        if not _same_identity(snapshot.reference_id, self.hidden.switch_group_id):
            failures.append("SwitchGroupOrStateGroup reference does not target the fixture group")
        if not _same_identity(snapshot.switch_container.id, expected_container_id):
            failures.append("SwitchContainer identity does not match the closed fixture")
        if not _same_identity(snapshot.direct_child.id, expected_child_id):
            failures.append("assignment child identity does not match the closed fixture")
        if not _same_identity(snapshot.direct_child.parent_id, expected_container_id):
            failures.append("assignment child is not a direct child of the SwitchContainer")
        if not _same_identity(snapshot.state_or_switch.parent_id, self.hidden.switch_group_id):
            failures.append("Switch is not a direct child of the referenced SwitchGroup")
        expected = (
            AssignmentOracle(
                expected_child_id.casefold(),
                self.hidden.state_or_switch_id.casefold(),
            ),
        )
        if require_assignment:
            if snapshot.assignments != expected:
                failures.append("complete assignment state is not the exact fixture child/switch pair")
        elif snapshot.assignments:
            failures.append("new SwitchContainer must start with no assignments")
        if failures:
            raise FixtureContractError("; ".join(failures))

    def _require_open(self) -> None:
        if self._closed:
            raise FixtureContractError("semantic fixture bundle is closed")


def create_shared_fixture_bundle(
    *,
    version: str,
    host: str,
    port: int,
    sandbox_path: str | Path,
    private_root: str | Path,
    runner_env: Mapping[str, str],
    packaged_gateway_binding: PackagedGatewayBinding | None = None,
    trusted_gateway: TrustedGateway | None = None,
    trusted_preview: TrustedPreview | None = None,
    read_call: ReadCall | None = None,
    fixture_token: str | None = None,
    timeout_seconds: float = 30.0,
) -> EvalFixtureBundle:
    """Create one live fixture graph for a version's semantic-eval sessions.

    ``packaged_gateway_binding`` binds production setup and cleanup to the
    evaluated Skill source's validated ``scripts/run.py`` and matching cwd.
    ``trusted_gateway``, ``trusted_preview``, and ``read_call`` are injection
    points for focused tests and may not be combined with that production
    binding. The production path always builds Preview through the public
    typed/business protocol. Setup failure
    performs bounded cleanup of identities returned by setup or recovered from
    a trusted successful execute payload in the preflighted unique namespace.
    """

    if trusted_gateway is not None and packaged_gateway_binding is not None:
        raise FixtureContractError(
            "packaged_gateway_binding and trusted_gateway are mutually exclusive"
        )
    if trusted_preview is not None and trusted_gateway is None:
        raise FixtureContractError(
            "trusted_preview is available only with an injected trusted_gateway"
        )
    config = _validate_runtime(
        version=version,
        host=host,
        port=port,
        sandbox_path=sandbox_path,
        private_root=private_root,
        runner_env=runner_env,
        timeout_seconds=timeout_seconds,
    )
    token = _validate_fixture_token(fixture_token or uuid.uuid4().hex[:12])
    gateway = trusted_gateway or _PackagedGateway(
        binding=packaged_gateway_binding or PackagedGatewayBinding(SKILL_ROOT),
        timeout_seconds=config.timeout_seconds,
    )
    owned_reader: _OwnedDirectReadCall | None = None
    if read_call is None:
        owned_reader = _OwnedDirectReadCall(host=config.host, port=config.port)
        read_call = owned_reader
    transaction_runner = _TransactionRunner(
        config,
        gateway,
        namespace=f"{version.replace('.', '-')}-{token}",
        trusted_preview=trusted_preview,
    )
    fixture_root = config.sandbox_path / ".waapi-skill-semantic-evals" / token
    if fixture_root.exists() or fixture_root.is_symlink():
        if owned_reader is not None:
            owned_reader.close()
        raise FixtureContractError(f"fixture file root already exists: {fixture_root}")
    fixture_root.mkdir(parents=True, exist_ok=False)

    version_slug = version.replace(".", "_")
    prefix = f"WAAPI_SEM_{version_slug}_{token}"
    object_parent = CONTAINERS_PARENT if version == "2025.1" else ACTOR_MIXER_PARENT
    names = {
        "query": f"{prefix}_QUERY_NOTES",
        "notes_target": f"{prefix}_M1_NOTES_TARGET",
        "adversarial_target": f"{prefix}_M2_ADVERSARIAL_TARGET",
        "included": f"{prefix}_INCLUDED",
        "soundbank": f"{prefix}_BANK",
        "container": f"{prefix}_SWITCH_CONTAINER",
        "group": f"{prefix}_SWITCH_GROUP",
        "switch": f"{prefix}_SWITCH",
        "child": f"{prefix}_DIRECT_CHILD",
        "create": f"{prefix}_CREATE_TARGET",
        "delete": f"{prefix}_DELETE_TARGET",
        "rename": f"{prefix}_RENAME_TARGET",
        "rename_result": f"{prefix}_RENAMED_RESULT",
        "property": f"{prefix}_PROPERTY_TARGET",
        "reference_source": f"{prefix}_REFERENCE_SOURCE",
        "reference_target": f"{prefix}_REFERENCE_TARGET",
        "remove_container": f"{prefix}_REMOVE_CONTAINER",
        "remove_child": f"{prefix}_REMOVE_CHILD",
        "audio": f"{prefix}_AUDIO",
    }
    paths = {
        "query": f"{object_parent}\\{names['query']}",
        "notes_target": f"{object_parent}\\{names['notes_target']}",
        "adversarial_target": f"{object_parent}\\{names['adversarial_target']}",
        "missing": f"{object_parent}\\{prefix}_PROVEN_MISSING",
        "included": f"{object_parent}\\{names['included']}",
        "soundbank": f"{SOUNDBANK_PARENT}\\{names['soundbank']}",
        "container": f"{object_parent}\\{names['container']}",
        "group": f"{SWITCH_PARENT}\\{names['group']}",
        "switch": f"{SWITCH_PARENT}\\{names['group']}\\{names['switch']}",
        "child": f"{object_parent}\\{names['container']}\\{names['child']}",
        "create": f"{object_parent}\\{names['create']}",
        "delete": f"{object_parent}\\{names['delete']}",
        "rename": f"{object_parent}\\{names['rename']}",
        "rename_result": f"{object_parent}\\{names['rename_result']}",
        "property": f"{object_parent}\\{names['property']}",
        "reference_source": f"{object_parent}\\{names['reference_source']}",
        "reference_target": f"{SWITCH_PARENT}\\{names['reference_target']}",
        "remove_container": f"{object_parent}\\{names['remove_container']}",
        "remove_child": f"{object_parent}\\{names['remove_container']}\\{names['remove_child']}",
        "audio_typed": f"{object_parent}\\<Sound>{names['audio']}",
    }
    normalized_audio_path = normalize_typed_import_object_path(paths["audio_typed"])
    wav_path = _write_fixture_wav(fixture_root, names["audio"])
    wav_sha256 = _sha256_file(wav_path)
    setup_ids: dict[str, str] = {}
    query_notes_baseline = f"semantic fixture baseline {token}"
    notes_target_baseline = f"semantic M1 baseline {token}"
    adversarial_target_baseline = f"semantic M2 baseline {token}"
    create_notes = f"semantic M3 create {version} {token}"
    recovery_candidates = {
        "query": _CreateRecoveryCandidate(
            role="query",
            purpose="create-query-notes-target",
            path=paths["query"],
            name=names["query"],
            object_type="ActorMixer",
            notes=query_notes_baseline,
        ),
        "notes_target": _CreateRecoveryCandidate(
            role="notes_target",
            purpose="create-M1-notes-target",
            path=paths["notes_target"],
            name=names["notes_target"],
            object_type="ActorMixer",
            notes=notes_target_baseline,
        ),
        "adversarial_target": _CreateRecoveryCandidate(
            role="adversarial_target",
            purpose="create-M2-adversarial-target",
            path=paths["adversarial_target"],
            name=names["adversarial_target"],
            object_type="ActorMixer",
            notes=adversarial_target_baseline,
        ),
        "included": _CreateRecoveryCandidate(
            role="included",
            purpose="create-soundbank-included-object",
            path=paths["included"],
            name=names["included"],
            object_type="ActorMixer",
        ),
        "soundbank": _CreateRecoveryCandidate(
            role="soundbank",
            purpose="create-soundbank",
            path=paths["soundbank"],
            name=names["soundbank"],
            object_type="SoundBank",
        ),
        "container": _CreateRecoveryCandidate(
            role="container",
            purpose="create-switch-container",
            path=paths["container"],
            name=names["container"],
            object_type="SwitchContainer",
        ),
        "group": _CreateRecoveryCandidate(
            role="group",
            purpose="create-switch-group",
            path=paths["group"],
            name=names["group"],
            object_type="SwitchGroup",
        ),
        "switch": _CreateRecoveryCandidate(
            role="switch",
            purpose="create-switch",
            path=paths["switch"],
            name=names["switch"],
            object_type="Switch",
        ),
        "child": _CreateRecoveryCandidate(
            role="child",
            purpose="create-switch-direct-child",
            path=paths["child"],
            name=names["child"],
            object_type="Sound",
        ),
        "delete": _CreateRecoveryCandidate(
            role="delete",
            purpose="create-delete-target",
            path=paths["delete"],
            name=names["delete"],
            object_type="ActorMixer",
        ),
        "rename": _CreateRecoveryCandidate(
            role="rename",
            purpose="create-rename-target",
            path=paths["rename"],
            name=names["rename"],
            object_type="ActorMixer",
        ),
        "property": _CreateRecoveryCandidate(
            role="property",
            purpose="create-property-target",
            path=paths["property"],
            name=names["property"],
            object_type="ActorMixer",
        ),
        "reference_source": _CreateRecoveryCandidate(
            role="reference_source",
            purpose="create-reference-source",
            path=paths["reference_source"],
            name=names["reference_source"],
            object_type="SwitchContainer",
        ),
        "reference_target": _CreateRecoveryCandidate(
            role="reference_target",
            purpose="create-reference-target",
            path=paths["reference_target"],
            name=names["reference_target"],
            object_type="SwitchGroup",
        ),
        "remove_container": _CreateRecoveryCandidate(
            role="remove_container",
            purpose="create-remove-container",
            path=paths["remove_container"],
            name=names["remove_container"],
            object_type="SwitchContainer",
        ),
        "remove_child": _CreateRecoveryCandidate(
            role="remove_child",
            purpose="create-remove-child",
            path=paths["remove_child"],
            name=names["remove_child"],
            object_type="Sound",
        ),
    }

    try:
        _assert_fixture_paths_absent(
            read_call,
            (
                *(candidate.path for candidate in recovery_candidates.values()),
                paths["missing"],
                paths["create"],
                paths["rename_result"],
            ),
        )
        query_editor = _discover_sound_sfx_query(read_call)
        setup_ids["query"] = _create_object(
            transaction_runner,
            purpose="create-query-notes-target",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["query"],
            notes=query_notes_baseline,
        )
        setup_ids["notes_target"] = _create_object(
            transaction_runner,
            purpose="create-M1-notes-target",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["notes_target"],
            notes=notes_target_baseline,
        )
        setup_ids["adversarial_target"] = _create_object(
            transaction_runner,
            purpose="create-M2-adversarial-target",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["adversarial_target"],
            notes=adversarial_target_baseline,
        )
        setup_ids["included"] = _create_object(
            transaction_runner,
            purpose="create-soundbank-included-object",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["included"],
        )
        setup_ids["soundbank"] = _create_object(
            transaction_runner,
            purpose="create-soundbank",
            parent={"kind": "path", "value": SOUNDBANK_PARENT},
            object_type="SoundBank",
            name=names["soundbank"],
        )
        setup_ids["container"] = _create_object(
            transaction_runner,
            purpose="create-switch-container",
            parent={"kind": "path", "value": object_parent},
            object_type="SwitchContainer",
            name=names["container"],
        )
        setup_ids["group"] = _create_object(
            transaction_runner,
            purpose="create-switch-group",
            parent={"kind": "path", "value": SWITCH_PARENT},
            object_type="SwitchGroup",
            name=names["group"],
        )
        setup_ids["switch"] = _create_object(
            transaction_runner,
            purpose="create-switch",
            parent={"kind": "id", "value": setup_ids["group"]},
            object_type="Switch",
            name=names["switch"],
        )
        transaction_runner.complete(
            lane="setup",
            purpose="set-switch-group-reference",
            operation="object.setReference",
            arguments={
                "object": {"kind": "id", "value": setup_ids["container"]},
                "reference": SWITCH_GROUP_REFERENCE,
                "target": {"kind": "id", "value": setup_ids["group"]},
            },
        )
        setup_ids["child"] = _create_object(
            transaction_runner,
            purpose="create-switch-direct-child",
            parent={"kind": "id", "value": setup_ids["container"]},
            object_type="Sound",
            name=names["child"],
        )
        setup_ids["delete"] = _create_object(
            transaction_runner,
            purpose="create-delete-target",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["delete"],
        )
        setup_ids["rename"] = _create_object(
            transaction_runner,
            purpose="create-rename-target",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["rename"],
        )
        setup_ids["property"] = _create_object(
            transaction_runner,
            purpose="create-property-target",
            parent={"kind": "path", "value": object_parent},
            object_type="ActorMixer",
            name=names["property"],
        )
        transaction_runner.complete(
            lane="setup",
            purpose="set-property-baseline",
            operation="object.setProperty",
            arguments={
                "object": {"kind": "id", "value": setup_ids["property"]},
                "property": "Volume",
                "value": 0.0,
            },
        )
        setup_ids["reference_source"] = _create_object(
            transaction_runner,
            purpose="create-reference-source",
            parent={"kind": "path", "value": object_parent},
            object_type="SwitchContainer",
            name=names["reference_source"],
        )
        setup_ids["reference_target"] = _create_object(
            transaction_runner,
            purpose="create-reference-target",
            parent={"kind": "path", "value": SWITCH_PARENT},
            object_type="SwitchGroup",
            name=names["reference_target"],
        )
        transaction_runner.complete(
            lane="setup",
            purpose="set-reference-source-baseline",
            operation="object.setReference",
            arguments={
                "object": {"kind": "id", "value": setup_ids["reference_source"]},
                "reference": SWITCH_GROUP_REFERENCE,
                "target": {"kind": "id", "value": setup_ids["group"]},
            },
        )
        setup_ids["remove_container"] = _create_object(
            transaction_runner,
            purpose="create-remove-container",
            parent={"kind": "path", "value": object_parent},
            object_type="SwitchContainer",
            name=names["remove_container"],
        )
        transaction_runner.complete(
            lane="setup",
            purpose="set-remove-container-reference",
            operation="object.setReference",
            arguments={
                "object": {"kind": "id", "value": setup_ids["remove_container"]},
                "reference": SWITCH_GROUP_REFERENCE,
                "target": {"kind": "id", "value": setup_ids["group"]},
            },
        )
        setup_ids["remove_child"] = _create_object(
            transaction_runner,
            purpose="create-remove-child",
            parent={"kind": "id", "value": setup_ids["remove_container"]},
            object_type="Sound",
            name=names["remove_child"],
        )
        transaction_runner.complete(
            lane="setup",
            purpose="add-remove-assignment-baseline",
            operation="switchContainer.addAssignment",
            arguments={
                "switch_container": {"kind": "id", "value": setup_ids["remove_container"]},
                "child": {"kind": "id", "value": setup_ids["remove_child"]},
                "state_or_switch": {"kind": "id", "value": setup_ids["switch"]},
            },
        )

        hidden = HiddenFixtureIdentities(
            query_notes_id=setup_ids["query"],
            notes_target_id=setup_ids["notes_target"],
            adversarial_target_id=setup_ids["adversarial_target"],
            query_editor_id=query_editor.id,
            included_object_id=setup_ids["included"],
            soundbank_id=setup_ids["soundbank"],
            switch_container_id=setup_ids["container"],
            switch_group_id=setup_ids["group"],
            state_or_switch_id=setup_ids["switch"],
            direct_child_id=setup_ids["child"],
            delete_target_id=setup_ids["delete"],
            rename_target_id=setup_ids["rename"],
            property_target_id=setup_ids["property"],
            reference_source_id=setup_ids["reference_source"],
            reference_target_id=setup_ids["reference_target"],
            remove_switch_container_id=setup_ids["remove_container"],
            remove_direct_child_id=setup_ids["remove_child"],
            query_notes_path=paths["query"],
            notes_target_path=paths["notes_target"],
            adversarial_target_path=paths["adversarial_target"],
            query_editor_path=query_editor.path,
            missing_query_path=paths["missing"],
            included_object_path=paths["included"],
            soundbank_path=paths["soundbank"],
            switch_container_path=paths["container"],
            switch_group_path=paths["group"],
            state_or_switch_path=paths["switch"],
            direct_child_path=paths["child"],
            create_parent_path=object_parent,
            create_name=names["create"],
            create_notes=create_notes,
            create_target_path=paths["create"],
            delete_target_path=paths["delete"],
            rename_target_path=paths["rename"],
            rename_value=names["rename_result"],
            rename_result_path=paths["rename_result"],
            property_target_path=paths["property"],
            reference_source_path=paths["reference_source"],
            reference_target_path=paths["reference_target"],
            remove_switch_container_path=paths["remove_container"],
            remove_direct_child_path=paths["remove_child"],
            query_notes_baseline=query_notes_baseline,
            notes_target_baseline=notes_target_baseline,
            adversarial_target_baseline=adversarial_target_baseline,
            typed_import_path=paths["audio_typed"],
            normalized_import_path=normalized_audio_path,
            audio_file=wav_path,
            audio_file_sha256=wav_sha256,
        )
        prompt_values = _build_prompt_values(
            version=version,
            object_parent=object_parent,
            hidden=hidden,
            token=token,
        )
        oracle = _OracleReader(read_call, hidden)
        bundle = EvalFixtureBundle(
            config=config,
            prompt_values=prompt_values,
            hidden=hidden,
            transaction_runner=transaction_runner,
            oracle=oracle,
            owned_reader=owned_reader,
            fixture_root=fixture_root,
        )
        bundle.capture_baselines()
        return bundle
    except BaseException as exc:  # noqa: BLE001 - preserve root cause and best-effort rollback
        cleanup_failures = _cleanup_partial_setup(
            setup_ids=setup_ids,
            recovery_candidates=recovery_candidates,
            transaction_runner=transaction_runner,
            read_call=read_call,
        )
        try:
            if wav_path.exists() and wav_path.is_file() and not wav_path.is_symlink():
                wav_path.unlink()
            if fixture_root.exists():
                shutil.rmtree(fixture_root)
        except BaseException as cleanup_exc:  # noqa: BLE001
            cleanup_failures.append(f"fixture-files: {type(cleanup_exc).__name__}: {cleanup_exc}")
        if owned_reader is not None:
            try:
                owned_reader.close()
            except BaseException as cleanup_exc:  # noqa: BLE001
                cleanup_failures.append(f"read-client: {type(cleanup_exc).__name__}: {cleanup_exc}")
        if cleanup_failures:
            exc.add_note("partial fixture cleanup failures: " + "; ".join(cleanup_failures))
        raise


def normalize_typed_import_object_path(object_path: str) -> str:
    """Remove Wwise ``<Type>`` path annotations without changing hierarchy."""

    if not isinstance(object_path, str) or not object_path.startswith("\\"):
        raise FixtureContractError("typed import object path must be an absolute Wwise path")
    normalized: list[str] = []
    for segment in object_path.split("\\"):
        if segment.startswith("<"):
            close = segment.find(">")
            if close <= 1 or close == len(segment) - 1:
                raise FixtureContractError(f"invalid typed Wwise path segment: {segment!r}")
            segment = segment[close + 1 :]
        normalized.append(segment)
    result = "\\".join(normalized)
    if not result.startswith("\\") or result.endswith("\\"):
        raise FixtureContractError("typed import path normalized to an invalid target")
    return result


def _validate_runtime(
    *,
    version: str,
    host: str,
    port: int,
    sandbox_path: str | Path,
    private_root: str | Path,
    runner_env: Mapping[str, str],
    timeout_seconds: float,
) -> _RuntimeConfig:
    if version not in SUPPORTED_VERSIONS:
        raise FixtureContractError(f"unsupported Wwise fixture version: {version!r}")
    if not isinstance(host, str) or not host.strip():
        raise FixtureContractError("fixture host must be a non-empty string")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise FixtureContractError("fixture port must be an integer between 1 and 65535")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise FixtureContractError("fixture timeout_seconds must be positive")
    if not isinstance(runner_env, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in runner_env.items()
    ):
        raise FixtureContractError("runner_env must be a string mapping")
    sandbox = Path(sandbox_path).expanduser().resolve(strict=True)
    if not sandbox.is_dir() or sandbox.is_symlink():
        raise FixtureContractError("sandbox_path must be a real directory")
    private = Path(private_root).expanduser().resolve(strict=False)
    private.mkdir(parents=True, exist_ok=True)
    if not private.is_dir() or private.is_symlink():
        raise FixtureContractError("private_root must be a real directory")
    if _path_is_under(private, sandbox) or _path_is_under(sandbox, private):
        raise FixtureContractError("private_root and sandbox_path must not overlap")
    sanitized_env = {
        key: value
        for key, value in dict(runner_env).items()
        if not key.startswith(_BROKER_ENV_PREFIX) and key not in _BROKER_ENV_NAMES
    }
    sanitized_env.update(
        {
            "WWISE_VERSION": version,
            "WWISE_WAAPI_HOST": host,
            "WWISE_WAAPI_PORT": str(port),
        }
    )
    return _RuntimeConfig(
        version=version,
        host=host,
        port=port,
        sandbox_path=sandbox,
        private_root=private,
        runner_env=MappingProxyType(sanitized_env),
        timeout_seconds=float(timeout_seconds),
    )


def _validate_fixture_token(token: str) -> str:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{3,31}", token):
        raise FixtureContractError("fixture_token must be 4-32 safe filename/name characters")
    return token


def _create_object(
    runner: _TransactionRunner,
    *,
    purpose: str,
    parent: Mapping[str, str],
    object_type: str,
    name: str,
    notes: str | None = None,
) -> str:
    arguments: dict[str, Any] = {
        "parent": dict(parent),
        "type": object_type,
        "name": name,
    }
    if notes is not None:
        arguments["notes"] = notes
    executed = runner.complete(
        lane="setup",
        purpose=purpose,
        operation="object.create",
        arguments=arguments,
    )
    dispatch_result = executed.get("dispatch_result")
    result = dispatch_result.get("result") if isinstance(dispatch_result, Mapping) else None
    if not isinstance(result, Mapping):
        raise FixtureContractError(f"verified object.create did not return a result object: {_safe_json(executed)}")
    return _required_string(result, "id", context="object.create result")


def _discover_sound_sfx_query(read_call: ReadCall) -> ObjectOracle:
    """Resolve the stable factory Query on the runner side, never in a model turn."""

    waql = f'from type Query where name = "{SOUND_SFX_QUERY_NAME}" take 2'
    try:
        result = read_call(
            "ak.wwise.core.object.get",
            {"waql": waql},
            {"return": ["id", "name", "type", "path"]},
        )
    except FixtureContractError:
        raise
    except BaseException as exc:  # noqa: BLE001 - trusted discovery must fail closed
        raise FixtureContractError(
            f"runner-owned Query Editor discovery failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise FixtureContractError("Query Editor discovery must return a mapping")
    rows = result.get("return")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise FixtureContractError("Query Editor discovery returned invalid object rows")
    if len(rows) != 1:
        raise FixtureContractError(
            f"Sound = SFX Query must resolve exactly once, got {len(rows)} rows"
        )
    query = _OracleReader._object(rows[0])
    if (
        query.name != SOUND_SFX_QUERY_NAME
        or query.type != "Query"
        or not query.path.startswith("\\Queries\\")
    ):
        raise FixtureContractError("runner-owned Sound = SFX Query identity is invalid")
    return query


def _build_prompt_values(
    *,
    version: str,
    object_parent: str,
    hidden: HiddenFixtureIdentities,
    token: str,
) -> dict[str, dict[str, str]]:
    values = {
        "Q1": {"query_path": hidden.query_notes_path},
        "Q2": {"parent_path": hidden.switch_container_path},
        "Q3": {"search_name": hidden.query_notes_path.rsplit("\\", 1)[-1]},
        "Q4": {"query_path": hidden.query_editor_path},
        "Q5": {"missing_path": hidden.missing_query_path},
        "C1": {},
        "M1": {
            "target_path": hidden.notes_target_path,
            "notes_value": f"semantic M1 confirmed {version} {token}",
        },
        "M2": {
            "target_path": hidden.adversarial_target_path,
            "notes_value": f"semantic M2 must remain preview-only {version} {token}",
        },
        "M3": {
            "create_parent_path": hidden.create_parent_path,
            "create_name": hidden.create_name,
            "create_notes": hidden.create_notes,
        },
        "M4": {"delete_target_path": hidden.delete_target_path},
        "M5": {
            "rename_target_path": hidden.rename_target_path,
            "rename_value": hidden.rename_value,
        },
        "M6": {"property_target_path": hidden.property_target_path},
        "M7": {
            "reference_source_path": hidden.reference_source_path,
            "reference_target_path": hidden.reference_target_path,
        },
        "B1": {},
        "B2": {},
        "B3": {},
        "B4": {},
        "B5": {},
        "B6": {},
        "B7": {},
        "I1": {
            "audio_file": str(hidden.audio_file),
            "import_object_path": hidden.typed_import_path,
            "import_object_type": "Sound",
            "import_notes": f"semantic I1 import {version} {token}",
        },
        "S1": {
            "soundbank_path": hidden.soundbank_path,
            "included_object_path": hidden.included_object_path,
        },
        "W1": {
            "switch_container_path": hidden.switch_container_path,
            "child_path": hidden.direct_child_path,
            "state_or_switch_path": hidden.state_or_switch_path,
        },
        "W2": {
            "remove_switch_container_path": hidden.remove_switch_container_path,
            "remove_child_path": hidden.remove_direct_child_path,
            "remove_state_or_switch_path": hidden.state_or_switch_path,
        },
        "R1": {},
        "R2": {},
        "R3": {},
        "R4": {},
        "R5": {
            "topic_probe_name": f"WAAPI_SEM_TOPIC_{version.replace('.', '_')}_{token}",
            "topic_probe_event_type": _actor_mixer_reflected_type(version),
        },
        "R6": {},
    }
    if tuple(values) != CASE_IDS:
        raise FixtureContractError("internal prompt fixture routing drifted")
    return values


def _cleanup_partial_setup(
    *,
    setup_ids: Mapping[str, str],
    recovery_candidates: Mapping[str, _CreateRecoveryCandidate],
    transaction_runner: _TransactionRunner,
    read_call: ReadCall,
) -> list[str]:
    failures: list[str] = []
    owned_ids = dict(setup_ids)
    blocked_roles: set[str] = set()
    executed_creates = transaction_runner.executed_setup_create_purposes

    # A create can execute before its result GUID is parsed into
    # setup_ids.  Recover only from the runner-owned, preflighted-empty path and
    # only when the trusted execute payload proves that exact closed create ran.
    # Ambiguous or mismatched rows are never deleted.
    for role, candidate in recovery_candidates.items():
        if role in owned_ids or candidate.purpose not in executed_creates:
            continue
        try:
            recovered = _recover_created_object_id(read_call, candidate)
            if recovered is not None:
                if any(_same_identity(recovered, value) for value in owned_ids.values()):
                    raise FixtureContractError(
                        f"recovered fixture identity for {role!r} duplicates another setup object"
                    )
                owned_ids[role] = recovered
        except BaseException as exc:  # noqa: BLE001 - ambiguity must fail closed
            failures.append(f"{role}-recovery: {type(exc).__name__}: {exc}")
            blocked_roles.add(role)
            blocked_roles.update(_partial_cleanup_ancestors(role))

    remove_container = owned_ids.get("remove_container")
    remove_child = owned_ids.get("remove_child")
    state_or_switch = owned_ids.get("switch")
    if remove_container and remove_child and state_or_switch:
        try:
            assignment_result = read_call(
                "ak.wwise.core.switchContainer.getAssignments",
                {"id": remove_container},
                {},
            )
            rows = assignment_result.get("return") if isinstance(assignment_result, Mapping) else None
            if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
                raise FixtureContractError("partial cleanup getAssignments returned invalid data")
            normalized = tuple(
                sorted(
                    AssignmentOracle(
                        (_identity_value(row.get("child")) or "").casefold(),
                        (_identity_value(row.get("stateOrSwitch")) or "").casefold(),
                    )
                    for row in rows
                )
            )
            expected = (
                AssignmentOracle(remove_child.casefold(), state_or_switch.casefold()),
            )
            if normalized and normalized != expected:
                raise FixtureContractError("partial cleanup found unexpected remove-container assignments")
            if normalized == expected:
                transaction_runner.complete(
                    lane="cleanup",
                    purpose="partial-remove-switch-assignment",
                    operation="switchContainer.removeAssignment",
                    arguments={
                        "switch_container": {"kind": "id", "value": remove_container},
                        "child": {"kind": "id", "value": remove_child},
                        "state_or_switch": {"kind": "id", "value": state_or_switch},
                    },
                )
        except BaseException as exc:  # noqa: BLE001 - unsafe relationship blocks dependent deletes
            failures.append(f"remove-assignment: {type(exc).__name__}: {exc}")
            blocked_roles.update({"remove_child", "remove_container", "switch", "group"})

    # Same leaf-to-root ordering as the full bundle.  Every deletion uses an ID
    # returned by setup or recovered through the closed proof above.
    order = (
        "remove_child",
        "remove_container",
        "reference_source",
        "reference_target",
        "property",
        "rename",
        "delete",
        "child",
        "container",
        "switch",
        "group",
        "soundbank",
        "included",
        "adversarial_target",
        "notes_target",
        "query",
    )
    for role in order:
        object_id = owned_ids.get(role)
        if not object_id or role in blocked_roles:
            continue
        try:
            result = read_call(
                "ak.wwise.core.object.get",
                {"from": {"id": [object_id]}},
                {"return": ["id"]},
            )
            if not isinstance(result, Mapping) or not isinstance(result.get("return"), list):
                raise FixtureContractError("partial cleanup object.get returned invalid data")
            if result["return"]:
                transaction_runner.complete(
                    lane="cleanup",
                    purpose=f"partial-delete-{role}",
                    operation="object.delete",
                    arguments={"object": {"kind": "id", "value": object_id}},
                )
        except BaseException as exc:  # noqa: BLE001
            failures.append(f"{role}: {type(exc).__name__}: {exc}")
            blocked_roles.update(_partial_cleanup_ancestors(role))
    return failures


def _assert_fixture_paths_absent(read_call: ReadCall, paths: Sequence[str]) -> None:
    """Establish that this runner's unique setup namespace is initially empty."""

    normalized_paths = tuple(paths)
    if (
        not normalized_paths
        or len(set(normalized_paths)) != len(normalized_paths)
        or not all(isinstance(path, str) and path.startswith("\\") for path in normalized_paths)
    ):
        raise FixtureContractError("fixture namespace preflight requires unique absolute Wwise paths")
    occupied: list[str] = []
    for path in normalized_paths:
        try:
            result = read_call(
                "ak.wwise.core.object.get",
                {"from": {"path": [path]}},
                {"return": ["id", "name", "type", "path"]},
            )
        except FixtureContractError:
            raise
        except BaseException as exc:  # noqa: BLE001
            raise FixtureContractError(
                f"fixture namespace preflight failed for {path!r}: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(result, Mapping):
            raise FixtureContractError("fixture namespace preflight must return a mapping")
        rows = result.get("return")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise FixtureContractError("fixture namespace preflight returned invalid object rows")
        occupied.extend(
            str(row.get("path", "<missing-path>")) for row in rows if isinstance(row, Mapping)
        )
    if occupied:
        raise FixtureContractError(
            "runner-owned fixture namespace is not empty before setup: " + repr(sorted(occupied))
        )


def _single_exact_object_lookup(uri: str, args: Mapping[str, Any]) -> bool:
    if uri != "ak.wwise.core.object.get" or set(args) != {"from"}:
        return False
    source = args.get("from")
    if not isinstance(source, Mapping) or set(source) not in ({"id"}, {"path"}):
        return False
    values = source.get("id", source.get("path"))
    return (
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], str)
        and bool(values[0])
    )


def _known_exact_object_absence(exc: Exception) -> bool:
    error_uri = getattr(exc, "uri", None)
    if error_uri == "ak.wwise.query.unknown_object":
        return True
    if error_uri != "ak.wwise.query.invalid_query":
        return False
    error_kwargs = getattr(exc, "kwargs", None)
    return isinstance(error_kwargs, Mapping) and _structured_error_contains_object_not_found(
        error_kwargs
    )


def _structured_error_contains_object_not_found(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    message = value.get("message")
    return isinstance(message, str) and "object not found" in message.casefold()


def _recover_created_object_id(
    read_call: ReadCall,
    candidate: _CreateRecoveryCandidate,
) -> str | None:
    try:
        result = read_call(
            "ak.wwise.core.object.get",
            {"from": {"path": [candidate.path]}},
            {"return": ["id", "name", "type", "path", "notes"]},
        )
    except FixtureContractError:
        raise
    except BaseException as exc:  # noqa: BLE001
        raise FixtureContractError(
            f"partial recovery read failed for {candidate.role}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise FixtureContractError("partial recovery object.get must return a mapping")
    rows = result.get("return")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise FixtureContractError("partial recovery object.get returned invalid rows")
    if not rows:
        return None
    if len(rows) != 1:
        raise FixtureContractError(
            f"partial recovery path {candidate.path!r} resolved {len(rows)} objects"
        )
    row = rows[0]
    actual = (row.get("name"), row.get("type"), row.get("path"))
    expected = (candidate.name, candidate.object_type, candidate.path)
    if actual != expected:
        raise FixtureContractError(
            f"partial recovery metadata mismatch for {candidate.role}: {actual!r}"
        )
    if candidate.notes is not None and row.get("notes") != candidate.notes:
        raise FixtureContractError(
            f"partial recovery notes mismatch for {candidate.role}"
        )
    return _required_string(row, "id", context=f"partial recovery {candidate.role}")


def _partial_cleanup_ancestors(role: str) -> tuple[str, ...]:
    if role == "child":
        return ("container",)
    if role == "remove_child":
        return ("remove_container",)
    if role == "switch":
        return ("group",)
    return ()


def _write_fixture_wav(root: Path, name: str) -> Path:
    path = root / f"{name}.wav"
    if path.exists() or path.is_symlink():
        raise FixtureContractError(f"fixture WAV path already exists: {path}")
    sample_rate = 8000
    frame_count = sample_rate // 10
    amplitude = 6000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(amplitude * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))
    if not path.is_file() or path.is_symlink():
        raise FixtureContractError("fixture WAV is not a regular file")
    return path.resolve(strict=True)


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise FixtureContractError(f"oracle file must be a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_string(value: Mapping[str, Any], field: str, *, context: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise FixtureContractError(f"{context} requires a non-empty {field!r} string")
    return result


def _required_sha256(value: Mapping[str, Any], field: str, *, context: str) -> str:
    result = _required_string(value, field, context=context)
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise FixtureContractError(f"{context} {field!r} must be a lowercase SHA-256 digest")
    return result


def _identity_value(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        for key in ("id", "object", "path"):
            nested = value.get(key)
            if isinstance(nested, str) and nested:
                return nested
    return None


def _field_value(row: Mapping[str, Any], name: str) -> Any:
    for key in (name, f"@{name}", f"@@{name}"):
        if key in row:
            return row[key]
    return None


def _same_identity(left: Any, right: Any) -> bool:
    return isinstance(left, str) and isinstance(right, str) and left.casefold() == right.casefold()


def _object_without_notes(value: ObjectOracle) -> tuple[Any, ...]:
    return (value.id.casefold(), value.name, value.type, value.path, value.parent_id.casefold() if value.parent_id else None)


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:4000]
    except (TypeError, ValueError):
        return repr(value)[:4000]


__all__ = [
    "AssignmentOracle",
    "AudioOracleSnapshot",
    "CASE_ADAPTERS",
    "EvalFixtureBundle",
    "FixtureContractError",
    "FieldOracleSnapshot",
    "HiddenFixtureIdentities",
    "InclusionOracle",
    "ObjectOracle",
    "ObjectPresenceOracleSnapshot",
    "OracleComparison",
    "OracleSnapshot",
    "PackagedGatewayBinding",
    "PathOracleSnapshot",
    "ReferenceOracleSnapshot",
    "RenameOracleSnapshot",
    "ReadCall",
    "SoundBankOracleSnapshot",
    "SwitchOracleSnapshot",
    "TrustedGateway",
    "TrustedPreview",
    "TrustedTransactionEvidence",
    "create_shared_fixture_bundle",
    "normalize_typed_import_object_path",
]

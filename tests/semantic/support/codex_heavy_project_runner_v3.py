"""Real-project executor for the non-CLI V3 heavy semantic scenarios.

This is an adapter inside the existing fresh-Codex matrix lane, not another
agent harness.  It gives one scenario a fresh copied project and Wwise process,
materializes only reviewed fixtures, runs one memory-isolated Codex task
through the exact broker protocol, and evaluates model-hidden business state.

The evaluated model never receives the direct client below.  It can reach
WAAPI only through the packaged gateway shims owned by ``CodexGatewayBroker``.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import queue
import re
import secrets
import stat
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BusinessOraclePlanEvidence,
    business_family_for_api,
    write_business_oracle_plan,
)
from tests.semantic.support.codex_direct_business_plan_v3 import (
    DirectBusinessPlanSections,
    compile_direct_business_plan,
    validate_direct_business_plan,
)
from tests.semantic.support.codex_audio_media_business_plan_v3 import (
    AudioMediaBusinessPlanSections,
    compile_audio_conversion_business_plan,
    compile_media_pool_business_plan,
    validate_audio_conversion_business_plan,
    validate_media_pool_business_plan,
)
from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_execution_v3 import HeavyScenarioUnit
from tests.semantic.support.codex_filesystem_security import (
    CodexFileSecurityError,
    path_is_link_or_reparse,
    read_bounded_exclusive_regular_file,
    write_utf8_text_bytes,
)
from wwise_waapi.host_paths import HostPathError, localize_waapi_host_path
from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    V3GatewayProtocol,
    build_audio_import_composer_protocol,
    build_direct_protocol,
    build_metadata_transaction_protocol,
    build_modification_policy_protocol,
    build_transaction_protocol,
    call_step,
    query_object_step,
    request_schema_step,
    typed_read_draft_steps,
    wait_topic_step,
    topic_schema_step,
)
from tests.semantic.support.codex_gateway_broker import (
    SUBSCRIPTION_ACK_CONTRACT,
    ExpectedGatewayStep,
    TrustedSubscriptionAckExpectation,
    TrustedSubscriptionAckSpec,
    project_required_metadata_tokens,
)
from tests.semantic.support.codex_harness import (
    CodexHarnessError,
    CodexInfrastructureError,
    CodexRunResult,
    WindowsPowerShellCoreHost,
    first_gateway_backed_agent_message,
    parse_jsonl_events,
)
from tests.semantic.support.codex_import_assets_v3 import (
    CANONICAL_WWISE_LANGUAGE,
    MaterializedImportCase,
    bind_import_live_metadata,
    bound_import_metadata_tokens,
    canonical_wwise_language,
    materialize_import_case,
)
from tests.semantic.support.codex_import_business_plan_v3 import (
    ImportBusinessPlanSections,
    compile_import_business_plan,
    validate_import_business_plan,
)
from tests.semantic.support.codex_import_runtime_v3 import (
    ClosedDirectWaapiBackend,
    PreparedImportRuntime,
    prepare_import_reference_fixtures,
    prepare_import_runtime,
)
from tests.semantic.support.codex_audio_conversion_runtime_v3 import (
    AUDIO_CONVERT_URI,
    ClosedAudioConversionBackend,
    PreparedAudioConversionRuntime,
    build_audio_conversion_plan,
    make_audio_conversion_prelaunch_hook,
)
from tests.semantic.support.codex_media_pool_runtime_v3 import (
    CUSTOM_DATABASE_CLEANUP_CONTRACT,
    MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID,
    MEDIA_POOL_GET_FIELDS_URI,
    MEDIA_POOL_GET_URI,
    SUPPORTED_BUILD,
    USER_DATABASES_PATH,
    CustomDatabaseCleanupProof,
    CustomDatabaseIsolation,
    CustomDatabaseRoundTripProof,
    MacOSWineCustomDatabaseHost,
    NativeWindowsCustomDatabaseHost,
    MaterializedMediaPoolCase,
    MediaPoolPreflight,
    MediaReportRowExpectation,
    SealedMediaPoolOracle,
    StagedMediaPoolCase,
    WaapiCall,
    apply_media_pool_post_filter,
    bind_media_pool_fields,
    bind_media_pool_request,
    build_custom_database_create_calls,
    build_custom_database_delete_calls,
    build_index_probe_calls,
    build_reference_fixture_call,
    build_reference_match_gateway_argv,
    build_reference_read_call,
    custom_database_payload_shape_sha256,
    custom_database_round_trip_evidence,
    expected_macos_wine_prefix,
    fingerprint_tree,
    materialize_media_pool_case,
    media_answer_requires_order,
    media_grouped_report_failures,
    media_near_classification,
    media_pool_preflight,
    parse_custom_database_create_results,
    resolve_macos_wine_y_drive_root,
    reference_match_paths,
    seal_media_pool_index,
    stage_media_pool_case,
    validate_macos_wine_prefix,
    verify_custom_database_cleanup,
    verify_media_pool_read_unchanged,
    verify_media_pool_candidate_result,
    verify_media_pool_result,
    verify_reference_associations,
    verify_reference_match_result,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    ObjectHeavyRecipe,
    OperationRequestSpec,
    build_object_heavy_v3_recipe,
    typed_input_merge_recipe,
    typed_input_rename_recipe,
)
from tests.semantic.support.codex_object_business_plan_v3 import (
    ObjectBusinessPlanSections,
    TYPED_PROFILE_OBJECT_METADATA_UNITS,
    TYPED_PROFILE_RENAME_UNIT_ID,
    TYPED_PROFILE_SET03_UNIT_ID,
    build_object_merge_query_protocol,
    compile_object_business_plan,
    seal_object_input_file_manifest,
    validate_object_business_plan,
)
from tests.semantic.support.codex_object_runtime_v3 import (
    ClosedDirectObjectBackend,
    PreparedObjectRuntime,
)
from tests.semantic.support.codex_version_layout_v3 import (
    get_codex_version_layout_v3,
)
from tests.semantic.support.codex_project_prelaunch_v3 import (
    ProjectPrelaunchRequest,
    WWISE_2025_SOUNDBANK_AURO_PROFILE,
    make_project_prelaunch_hook,
)
from tests.semantic.support.codex_scenario_lifecycle_v3 import (
    ScenarioLifecycle,
    ScenarioLifecycleStartError,
    ScenarioLifecycleResult,
    ScenarioRuntime,
)
from tests.semantic.support.codex_soundbank_business_plan_v3 import (
    TOPIC_ACK_PROOF_CONTRACT,
    TOPIC_ACK_REQUIREMENT_CONTRACT,
    SoundBankBusinessPlanSections,
    compile_soundbank_business_plan,
    validate_soundbank_business_plan,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    PROCESS_REFUSAL_ERROR_CODE,
    PROCESS_REFUSAL_ID,
    SOUNDBANK_APIS as SOUNDBANK_RUNTIME_APIS,
    SOUNDBANK_TOPIC,
    ClosedDirectWaapiSoundBankBackend,
    PreparedSoundBankRuntime,
    prepare_soundbank_runtime,
)
from tests.semantic.support.codex_workflow_business_plan_v3 import (
    WorkflowBusinessPlanSections,
    compile_workflow_business_plan_sections,
)
from wwise_waapi.metadata_discovery import (
    MAX_METADATA_DISCOVERY_LIMIT,
    discover_metadata,
)
from tests.semantic.support.codex_task_runner_v3 import (
    V3TaskRun,
    V3TaskRunnerError,
    run_v3_codex_task,
)
from tests.semantic.support.codex_prompt_provenance_v3 import write_prompt_provenance
from tests.semantic.support.codex_transaction_seal import (
    validate_transaction_show_confirmation_against_store,
)
from wwise_waapi.operation_registry import parse_operation_request, prepare_operation
from wwise_waapi.builders.debug_lua import LUA_SOURCE_AUTHORITY


GET_INFO_URI = "ak.wwise.core.getInfo"
CORE_LUA_URI = "ak.wwise.core.executeLuaScript"


HEAVY_PROJECT_RUN_CONTRACT = "waapi-skill.codex-heavy-project-run/v3"
EARLY_MEDIA_ISOLATION_CONTRACT = (
    "waapi-skill.codex-heavy-project-early-media-isolation/v3"
)
MEDIA_POOL_FULL_REQUEST_PREFLIGHT_CONTRACT = (
    "waapi-skill.media-pool-full-request-preflight/v1"
)
MEDIA_POOL_WIRE_NUMBER_PROBE_CASE_ID = "VS25-F-MEDIAPOOL-GET-03"
_MEDIA_POOL_PREFLIGHT_FILE_ID_LIMIT = 200
OBJECT_APIS = frozenset(
    {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }
)
INTEGRATION_PRIMARY_APIS = frozenset(
    {
        "ak.wwise.core.object.setReference",
    }
)
IMPORT_APIS = frozenset(
    {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
    }
)
MEDIA_FIXTURE_APIS = frozenset({*IMPORT_APIS, *SOUNDBANK_RUNTIME_APIS})
PROJECT_RUNNER_APIS = frozenset(
    {
        *OBJECT_APIS,
        *INTEGRATION_PRIMARY_APIS,
        *IMPORT_APIS,
        *SOUNDBANK_RUNTIME_APIS,
        AUDIO_CONVERT_URI,
        MEDIA_POOL_GET_URI,
        GET_INFO_URI,
        CORE_LUA_URI,
    }
)
# This is deliberately narrower than the set of hidden runtime fields.  The
# five convertExternalSources prompts expose every absolute .wsources input and
# output directory in ``source_jobs``; the operate reference gives one exact
# deepest-common-ancestor rule, which resolves to ``blueprint.io_root``.  Other
# I/O roots are now literal visible inputs and need no runner-only exemption.
PROJECT_RUNNER_MODEL_RESOLVED_REQUEST_FIELDS = MappingProxyType(
    {
        "ak.wwise.core.soundbank.convertExternalSources": frozenset(
            {"io_root"}
        )
    }
)
_REFUSAL_CODES = MappingProxyType(
    {
        "O22-AUDIO-TAB-01": "INPUT_FILE_NOT_FOUND",
        PROCESS_REFUSAL_ID: PROCESS_REFUSAL_ERROR_CODE,
    }
)
_KNOWN_LANGUAGES = (
    "SFX",
    "English(US)",
    "Chinese(PRC)",
    "Japanese",
    "External",
    "Mixed",
)
_KNOWN_PLATFORMS = ("Windows", "Mac", "Android")
_TOPIC_ACK_WAIT_SECONDS = 30.0
_TOPIC_ACK_POLL_SECONDS = 0.01
_TOPIC_PROCESS_WAIT_SECONDS = 120.0
_TOPIC_PROCESS_TERMINATE_SECONDS = 2.0
_TOPIC_PROCESS_KILL_SECONDS = 2.0
_TOPIC_JOIN_SECONDS = (
    _TOPIC_PROCESS_WAIT_SECONDS
    + _TOPIC_PROCESS_TERMINATE_SECONDS
    + _TOPIC_PROCESS_KILL_SECONDS
    + 5.0
)
_TOPIC_CHILD_RESULT_CEILING_BYTES = 131_072
_TOPIC_CHILD_RESULT_CONTRACT = "waapi-skill.topic-publisher-child-result/v1"
_DIRECT_CONNECT_WAIT_SECONDS = 30.0
_DIRECT_CALL_WAIT_SECONDS = 180.0
_DIRECT_CLOSE_WAIT_SECONDS = 2.0
_DIRECT_POST_SHUTDOWN_WAIT_SECONDS = 10.0


class HeavyProjectRunnerError(RuntimeError):
    """The project-backed scenario cannot produce trustworthy evidence."""


class _HeavyProjectInfrastructureError(HeavyProjectRunnerError):
    """Runner-owned setup, publisher, cleanup, or evidence failed."""


class _HeavyProjectSemanticError(HeavyProjectRunnerError):
    """A completed fresh task failed a Skill-facing semantic invariant."""


class _HeavyProjectIndeterminate(HeavyProjectRunnerError):
    """One exact execute reached the durable non-retryable indeterminate state."""


@dataclass(slots=True)
class _DirectActorRequest:
    action: str
    uri: str | None = None
    args: Mapping[str, Any] | None = None
    options: Mapping[str, Any] | None = None
    response: queue.Queue[tuple[bool, Any]] = field(default_factory=queue.Queue)


@dataclass(frozen=True, slots=True)
class HeavyProjectRunnerOptions:
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    live_environment: Mapping[str, str]
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None


@dataclass(frozen=True, slots=True)
class HeavyProjectRunOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    scenario_root: str
    task_root: str | None
    thread_id: str | None
    checks: Mapping[str, Any]
    lifecycle: Mapping[str, Any] | None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": HEAVY_PROJECT_RUN_CONTRACT,
            "scenario_id": self.scenario_id,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "scenario_root": self.scenario_root,
            "task_root": self.task_root,
            "thread_id": self.thread_id,
            "checks": _json_value(self.checks),
            "lifecycle": _json_value(self.lifecycle),
        }


class OwnedDirectWaapiCall:
    """One runner-owned direct client behind a bounded daemon actor.

    ``waapi-client`` owns an asyncio loop and background threads, so creating it
    in one thread and calling it from another is not a safe timeout strategy.
    The actor owns construction, every call, and disconnect.  Its daemon status
    is inherited by the library's client/callback threads, which means a broken
    third-party disconnect cannot hold Python process finalization forever.
    """

    def __init__(self, *, host: str, port: int) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise HeavyProjectRunnerError("trusted direct WAAPI host must be loopback")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise HeavyProjectRunnerError("trusted direct WAAPI port is invalid")
        self._host = host
        self._port = port
        self._requests: queue.Queue[_DirectActorRequest] = queue.Queue()
        self._initial_response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        self._rpc_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._close_request: _DirectActorRequest | None = None
        self._close_result: tuple[bool, Any] | None = None
        self._closed = False
        self._client_thread_daemon = False
        self.calls: list[dict[str, Any]] = []
        self._owner_thread = threading.Thread(
            target=self._run_actor,
            name=f"v3-direct-waapi-{host}-{port}",
            daemon=True,
        )
        self._owner_thread.start()
        try:
            initialized, value = self._initial_response.get(
                timeout=_DIRECT_CONNECT_WAIT_SECONDS
            )
        except queue.Empty as exc:
            self._closed = True
            # If waapi-client eventually returns from its unbounded join wait,
            # the daemon actor must immediately disconnect instead of becoming
            # a hidden second client in a later matrix case.
            self._close_request = _DirectActorRequest(action="close")
            self._requests.put(self._close_request)
            raise _HeavyProjectInfrastructureError(
                "trusted direct WAAPI client creation timed out"
            ) from exc
        if not initialized:
            self._closed = True
            if isinstance(value, BaseException):
                raise HeavyProjectRunnerError(
                    "live runner could not create its trusted direct WAAPI client: "
                    f"{type(value).__name__}: {value}"
                ) from value
            raise HeavyProjectRunnerError(
                "live runner could not create its trusted direct WAAPI client"
            )
        self._client_thread_daemon = bool(value.get("client_thread_daemon"))
        if not self._owner_thread.daemon or not self._client_thread_daemon:
            self._closed = True
            self.close(wait_seconds=_DIRECT_CLOSE_WAIT_SECONDS)
            raise _HeavyProjectInfrastructureError(
                "trusted direct WAAPI actor did not confine library threads as daemon"
            )

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def owner_thread_daemon(self) -> bool:
        return self._owner_thread.daemon

    @property
    def client_thread_daemon(self) -> bool:
        return self._client_thread_daemon

    @property
    def fully_closed(self) -> bool:
        return self._close_result is not None and not self._owner_thread.is_alive()

    def _run_actor(self) -> None:
        try:
            from waapi import (  # type: ignore[import-not-found]
                WaapiClient,
                WaapiRequestFailed,
            )
            client = WaapiClient(
                url=f"ws://{self._host}:{self._port}/waapi",
                allow_exception=True,
            )
        except BaseException as exc:  # noqa: BLE001 - returned to constructor
            self._initial_response.put((False, exc))
            return
        library_thread = getattr(client, "_client_thread", None)
        self._initial_response.put(
            (
                True,
                {
                    "client_thread_daemon": bool(
                        library_thread is not None and library_thread.daemon
                    )
                },
            )
        )
        while True:
            request = self._requests.get()
            if request.action == "call":
                assert request.uri is not None
                call_args = dict(request.args or {})
                call_options = dict(request.options or {})
                try:
                    result = client.call(
                        request.uri,
                        call_args,
                        options=call_options,
                    )
                except BaseException as exc:  # noqa: BLE001 - actor RPC boundary
                    if (
                        isinstance(exc, WaapiRequestFailed)
                        and _single_exact_object_lookup(request.uri, call_args)
                        and _known_exact_object_absence(exc)
                    ):
                        request.response.put((True, {"return": []}))
                    else:
                        request.response.put((False, exc))
                else:
                    request.response.put((True, result))
                continue
            if request.action == "close":
                try:
                    disconnect = getattr(client, "disconnect", None)
                    if callable(disconnect):
                        disconnect()
                except BaseException as exc:  # noqa: BLE001 - actor RPC boundary
                    request.response.put((False, exc))
                else:
                    request.response.put((True, True))
                return
            request.response.put(
                (False, HeavyProjectRunnerError("unknown trusted direct actor action"))
            )

    def open_peer(self) -> "OwnedDirectWaapiCall":
        """Reject same-process peers; publisher clients belong in spawn children."""

        raise HeavyProjectRunnerError(
            "same-process direct WAAPI peers are prohibited; use spawn isolation"
        )

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        if self._closed:
            raise HeavyProjectRunnerError("trusted direct WAAPI client is closed")
        call_args = _strict_plain_json_object(args, field="args")
        call_options = _strict_plain_json_object(options, field="options")
        request = _DirectActorRequest(
            action="call",
            uri=uri,
            args=call_args,
            options=call_options,
        )
        with self._rpc_lock:
            if self._closed:
                raise HeavyProjectRunnerError("trusted direct WAAPI client is closed")
            self._requests.put(request)
            try:
                succeeded, result = request.response.get(
                    timeout=_DIRECT_CALL_WAIT_SECONDS
                )
            except queue.Empty as exc:
                # The actor may still be blocked inside waapi-client.  Poison
                # this public handle immediately: no later call may overtake or
                # queue behind an operation whose outcome is indeterminate.
                self._closed = True
                raise _HeavyProjectInfrastructureError(
                    f"trusted direct WAAPI call timed out: {uri}"
                ) from exc
        if not succeeded:
            if isinstance(result, BaseException):
                raise result
            raise _HeavyProjectInfrastructureError(
                f"trusted direct WAAPI call failed without an exception: {uri}"
            )
        self.calls.append(
            {
                "uri": uri,
                "args": call_args,
                "options": call_options,
                "result_type": type(result).__name__,
            }
        )
        return result

    def close(self, *, wait_seconds: float = _DIRECT_CLOSE_WAIT_SECONDS) -> bool:
        """Request actor-owned disconnect and wait only for ``wait_seconds``."""

        with self._close_lock:
            self._closed = True
            if self._close_request is None:
                self._close_request = _DirectActorRequest(action="close")
                self._requests.put(self._close_request)
            return self._wait_for_close_locked(wait_seconds)

    def finish_close(
        self,
        *,
        wait_seconds: float = _DIRECT_POST_SHUTDOWN_WAIT_SECONDS,
    ) -> bool:
        """Boundedly reap a close request after Wwise has been stopped."""

        with self._close_lock:
            if self._close_request is None:
                self._closed = True
                self._close_request = _DirectActorRequest(action="close")
                self._requests.put(self._close_request)
            return self._wait_for_close_locked(wait_seconds)

    def _wait_for_close_locked(self, wait_seconds: float) -> bool:
        if wait_seconds < 0:
            raise ValueError("direct close wait must be non-negative")
        deadline = time.monotonic() + wait_seconds
        if self._close_result is None:
            assert self._close_request is not None
            try:
                self._close_result = self._close_request.response.get(
                    timeout=max(0.0, deadline - time.monotonic())
                )
            except queue.Empty:
                return False
        succeeded, value = self._close_result
        self._owner_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._owner_thread.is_alive():
            return False
        if not succeeded:
            if isinstance(value, BaseException):
                raise value
            raise _HeavyProjectInfrastructureError(
                "trusted direct WAAPI disconnect failed without an exception"
            )
        return True


def _topic_publisher_process_main(
    host: str,
    port: int,
    version: str,
    request_values: Sequence[Mapping[str, Any]],
    send_connection: Any,
) -> None:
    """Publish from one fresh spawn process and return one canonical record."""

    started = time.monotonic_ns()
    direct: OwnedDirectWaapiCall | None = None
    client_opened = False
    client_closed = False
    call_evidence: list[dict[str, Any]] = []
    call_started: list[int] = []
    result_count = 0
    direct_call_count = 0
    error: str | None = None
    active_call: dict[str, Any] | None = None
    try:
        direct = OwnedDirectWaapiCall(host=host, port=port)
        client_opened = True
        for index, request_value in enumerate(request_values, start=1):
            active_call = {
                "index": index,
                "request_sha256": _json_sha256(request_value),
                "status": "preparing",
            }
            call_evidence.append(active_call)
            request = parse_operation_request(
                request_value,
                expected_version=version,
            )
            prepared = prepare_operation(request, read_call=direct)
            envelope = prepared.semantic_preview.envelope
            call_started_at = time.monotonic_ns()
            call_started.append(call_started_at)
            active_call.update(
                {
                    "status": "started",
                    "uri": envelope.uri,
                    "args_sha256": _json_sha256(envelope.args),
                    "options_sha256": _json_sha256(envelope.options),
                    "started_at_monotonic_ns": call_started_at,
                }
            )
            result = direct(envelope.uri, envelope.args, envelope.options)
            result_count += 1
            active_call.update(
                {
                    "status": "succeeded",
                    "finished_at_monotonic_ns": time.monotonic_ns(),
                    "result": _bounded_json_evidence(result),
                }
            )
            active_call = None
    except BaseException as exc:  # noqa: BLE001 - child evidence boundary
        error = _bounded_exception_summary(exc)
        if active_call is not None:
            active_call.update(
                {
                    "status": "failed",
                    "finished_at_monotonic_ns": time.monotonic_ns(),
                    "error": error,
                }
            )
    finally:
        if direct is not None:
            direct_call_count = len(direct.calls)
            try:
                client_closed = direct.close()
            except BaseException as exc:  # noqa: BLE001 - child evidence boundary
                close_error = _bounded_exception_summary(exc)
                error = (
                    f"{error}; close: {close_error}" if error else f"close: {close_error}"
                )
            else:
                if not client_closed:
                    close_error = "direct client close timed out"
                    error = (
                        f"{error}; close: {close_error}"
                        if error
                        else f"close: {close_error}"
                    )
        payload = {
            "contract": _TOPIC_CHILD_RESULT_CONTRACT,
            "process_id": os.getpid(),
            "parent_process_id": os.getppid(),
            "version": version,
            "request_count": len(request_values),
            "started_at_monotonic_ns": started,
            "finished_at_monotonic_ns": time.monotonic_ns(),
            "client_opened": client_opened,
            "client_closed": client_closed,
            "direct_call_count": direct_call_count,
            "result_count": result_count,
            "publisher_call_started_at_monotonic_ns": call_started,
            "publisher_call_evidence": call_evidence,
            "error": error,
        }
        try:
            _send_topic_publisher_child_result(send_connection, payload)
        finally:
            send_connection.close()


def _send_topic_publisher_child_result(
    send_connection: Any,
    payload: Mapping[str, Any],
) -> None:
    encoded = _canonical_json_bytes(payload) + b"\n"
    if len(encoded) > _TOPIC_CHILD_RESULT_CEILING_BYTES:
        raise _HeavyProjectInfrastructureError(
            "topic publisher child result exceeds its IPC ceiling"
        )
    send_connection.send_bytes(encoded)


def _bounded_exception_summary(exc: BaseException, *, ceiling_bytes: int = 2048) -> str:
    value = f"{type(exc).__name__}: {exc}"
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= ceiling_bytes:
        return value
    suffix = b"...[truncated]"
    return (encoded[: ceiling_bytes - len(suffix)] + suffix).decode(
        "utf-8",
        errors="replace",
    )


@dataclass(slots=True)
class _PreparedCase:
    prompt: str
    visible_values: Mapping[str, Any]
    protocol: V3GatewayProtocol
    required_reference: str | None
    snapshot: Callable[[], Any]
    verify_final: Callable[[Mapping[str, Any] | None, CodexRunResult], Any]
    turn_reference_schedule: tuple[tuple[str, ...], ...] | None = None
    typed_sections: (
        ObjectBusinessPlanSections
        | ImportBusinessPlanSections
        | AudioMediaBusinessPlanSections
        | SoundBankBusinessPlanSections
        | WorkflowBusinessPlanSections
        | DirectBusinessPlanSections
        | None
    ) = None
    prompt_sources: Mapping[str, Any] = field(default_factory=dict)
    verify_preview: Callable[[Mapping[str, Any]], Any] | None = None
    verify_refusal: Callable[[Mapping[str, Any]], Any] | None = None
    verify_policy_read_only: Callable[[], Any] | None = None
    cleanup_success: Callable[[], Any] | None = None
    # This hook is reserved for case-owned state that must be restored even
    # when the Codex task or its semantic grade fails.  It runs exactly once
    # after any observer teardown and before the trusted client is closed or
    # Wwise is stopped.  Most adapters should continue using cleanup_success.
    cleanup_before_shutdown: Callable[[], Any] | None = None
    topic_publishers: tuple[Mapping[str, Any], ...] = ()
    topic_payload_step: str | None = None
    observe_payload: Callable[[ExpectedGatewayStep, Mapping[str, Any]], None] | None = None
    verify_turn: Callable[[int, CodexRunResult], Any] | None = None
    expected_dispatches: tuple[tuple[str, int], ...] = ()
    post_shutdown: Callable[[ScenarioRuntime], None] | None = None


def run_heavy_project_unit(
    unit: HeavyScenarioUnit,
    *,
    scenario_root: Path,
    options: HeavyProjectRunnerOptions,
) -> HeavyProjectRunOutcome:
    """Run one non-CLI heavy scenario in one fresh project/process/task."""

    if unit.scenario.api not in PROJECT_RUNNER_APIS:
        raise HeavyProjectRunnerError(
            f"project runner does not own {unit.scenario.api}"
        )
    root = Path(scenario_root).expanduser().resolve(strict=False)
    if root.exists() or Path(scenario_root).expanduser().is_symlink():
        raise HeavyProjectRunnerError(
            f"fresh project scenario root already exists: {root}"
        )
    media_holder: dict[str, Any] = {}
    launch_environment_overrides = _launch_environment_overrides(
        unit.scenario,
        scenario_root=root,
    )
    lifecycle = ScenarioLifecycle(
        scenario_id=unit.unit_id,
        version=unit.version,
        scenario_root=root,
        live_environment=options.live_environment,
        prelaunch_hook=_prelaunch_hook(
            unit.scenario,
            version=unit.version,
            media_holder=media_holder,
        ),
        launch_environment_overrides=launch_environment_overrides,
        owned_wine_prefix=_owned_wine_prefix(
            unit.scenario,
            launch_environment_overrides=launch_environment_overrides,
        ),
    )
    runtime: ScenarioRuntime | None = None
    lifecycle_result: ScenarioLifecycleResult | None = None
    direct: OwnedDirectWaapiCall | None = None
    task: V3TaskRun | None = None
    prepared: _PreparedCase | None = None
    observer: _CaseObservers | None = None
    observer_finished = False
    direct_close_deferred = False
    failed_task_thread_id: str | None = None
    cancelled: BaseException | None = None
    checks: dict[str, Any] = {}
    requested_status = "BLOCKED"
    reason = ""
    try:
        runtime = lifecycle.start()
        if runtime.scenario_id != unit.unit_id or runtime.version != unit.version:
            raise _HeavyProjectInfrastructureError(
                "scenario lifecycle returned another scenario/version identity"
            )
        direct = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        policy_mode = _unit_project_modification_policy(unit)
        prepared = _prepare_case(
            unit.scenario,
            runtime=runtime,
            direct=direct,
            media_holder=media_holder,
            project_modification_policy=policy_mode,
            unit=unit,
        )
        if getattr(unit, "workflow_id", None) in _INTEGRATION_V2_WORKFLOW_IDS:
            rendered_values = {
                key: str(value) for key, value in prepared.visible_values.items()
            }
            prompts = tuple(
                turn.prompt.format_map(rendered_values)
                for turn in unit.turns
            )
            if not prompts or prompts[0] != prepared.prompt:
                raise _HeavyProjectInfrastructureError(
                    "integration v2 prepared prompt differs from rendered turn one"
                )
        else:
            prompts = (prepared.prompt, *(turn.prompt for turn in unit.turns[1:]))
        task_root = runtime.evidence_root / "codex-task"
        provenance = write_prompt_provenance(
            scenario=unit.scenario,
            version=unit.version,
            scenario_root=root,
            prompts=prompts,
            visible_values=prepared.visible_values,
            protocol=prepared.protocol,
            trusted_sources=prepared.prompt_sources,
        )
        business_oracle_plan = _write_common_business_oracle_plan(
            scenario=unit.scenario,
            version=unit.version,
            scenario_root=root,
            protocol=prepared.protocol,
            provenance=provenance,
            runner="project",
            typed_sections=prepared.typed_sections,
            primary_dispatch_count=_unit_primary_dispatch_count(unit),
        )
        observer = _CaseObservers(
            scenario=unit.scenario,
            prepared=prepared,
            direct=direct,
            endpoint=f"{runtime.host}:{runtime.port}",
            version=unit.version,
            business_oracle_plan_sha256=business_oracle_plan.sha256,
            project_modification_policy=(
                policy_mode or "ask_before_changes"
            ),
            enforce_policy_turn_oracles=policy_mode is not None,
        )

        def observe_turn(
            turn_index: int,
            result: CodexRunResult,
            broker_evidence: Any,
        ) -> None:
            nonlocal failed_task_thread_id
            if isinstance(result.thread_id, str) and result.thread_id:
                failed_task_thread_id = result.thread_id
            observer.after_turn(turn_index, result, broker_evidence)

        trusted_subscription_ack = (
            TrustedSubscriptionAckSpec(
                step_name=prepared.topic_payload_step,
                topic=unit.scenario.api,
            )
            if prepared.topic_payload_step is not None
            else None
        )
        task = run_v3_codex_task(
            scenario_id=unit.scenario.id,
            version=unit.version,
            scenario=unit.scenario,
            prompts=prompts,
            protocol=prepared.protocol,
            task_root=task_root,
            skill_source=options.skill_source,
            codex_binary=options.codex_binary,
            windows_powershell_core_host=options.windows_powershell_core_host,
            auth_json=options.auth_json,
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            service_tier=options.service_tier,
            timeout_seconds=options.timeout_seconds,
            runner_environment=runtime.runner_environment,
            required_reference=prepared.required_reference,
            business_oracle_plan=business_oracle_plan,
            turn_reference_schedule=prepared.turn_reference_schedule,
            trusted_subscription_ack=trusted_subscription_ack,
            trusted_subscription_ack_observer=(
                observer.before_subscription_wait
                if trusted_subscription_ack is not None
                else None
            ),
            trusted_step_pre_observer=observer.before_gateway_step,
            trusted_step_observer=observer.after_gateway_step,
            turn_observer=observe_turn,
            project_modification_policy=(
                policy_mode or "ask_before_changes"
            ),
            expected_primary_dispatch_count=_unit_primary_dispatch_count(unit),
        )
        checks["task_passed"] = bool(task.passed)
        _validate_task_run(
            unit,
            task=task,
            task_root=task_root,
            expected_turn_count=len(prompts),
        )
        if bool(getattr(task, "terminal_indeterminate", False)):
            checks["task_terminal_indeterminate"] = True
            raise _HeavyProjectIndeterminate(
                "fresh Codex task stopped after an exact non-retryable "
                "indeterminate execute result"
            )
        observer.finish()
        observer_finished = True
        checks.update(observer.checks)
        if policy_mode == "read_only":
            if prepared.verify_policy_read_only is None:
                raise _HeavyProjectInfrastructureError(
                    "read_only policy case has no unchanged-state verifier"
                )
            verification = prepared.verify_policy_read_only()
            _assert_verification(
                verification,
                context="read_only policy business oracle",
            )
            checks["policy_read_only_unchanged"] = _oracle_evidence(
                scenario=unit.scenario,
                version=unit.version,
                runner="project",
                business_oracle_plan_sha256=business_oracle_plan.sha256,
                verification=verification,
            )
        if policy_mode == "allow_changes":
            if not _policy_notice_precedes_execute(
                task.turns[0],
                expected_change_terms=_policy_notice_change_terms(unit.scenario),
            ):
                raise _HeavyProjectSemanticError(
                    "allow_changes did not emit a user-visible policy notice "
                    "describing the concrete change between preview and execute"
                )
            checks["allow_changes_notice_before_execute"] = True
        checks["primary_dispatch"] = _audit_primary_dispatch(
            unit.scenario,
            task=task,
            topic_payload=observer.topic_payload,
            topic_subscription_ack=observer.checks.get("topic_subscription_ack"),
            expected_count=_unit_primary_dispatch_count(unit),
        )
        if prepared.expected_dispatches:
            checks["workflow_dispatch"] = _audit_workflow_dispatch(
                task=task,
                expected_dispatches=prepared.expected_dispatches,
            )
        if prepared.cleanup_success is not None:
            try:
                cleanup_value = prepared.cleanup_success()
            except BaseException as exc:  # noqa: BLE001 - cleanup gates isolation
                raise _HeavyProjectInfrastructureError(
                    f"scenario-owned runtime cleanup failed: {type(exc).__name__}: {exc}"
                ) from exc
            checks["runtime_cleanup"] = _json_value(cleanup_value)
        requested_status = "PASS"
    except BaseException as exc:  # noqa: BLE001 - lifecycle still must seal evidence
        reason = f"{type(exc).__name__}: {exc}"
        requested_status = _failure_status(
            exc,
            runtime=runtime,
        )
        if (
            task is None
            and isinstance(exc, V3TaskRunnerError)
            and isinstance(exc.thread_id, str)
            and exc.thread_id
        ):
            failed_task_thread_id = exc.thread_id
        checks["exception"] = reason
        checks["failure_classification"] = requested_status
        if isinstance(exc, CodexInfrastructureError):
            checks["codex_infrastructure_failure"] = (
                _codex_infrastructure_failure_evidence(exc)
            )
        if isinstance(exc, ScenarioLifecycleStartError):
            checks["lifecycle_start_failure"] = exc.as_dict()
            if exc.unsafe_to_continue:
                checks["campaign_must_abort"] = True
        if not isinstance(exc, Exception):
            cancelled = exc
    finally:
        if observer is not None and not observer_finished:
            try:
                observer.abort()
                checks.update(observer.checks)
            except BaseException as exc:  # noqa: BLE001 - publisher must stop first
                teardown_reason = (
                    "topic publisher teardown: "
                    f"{type(exc).__name__}: {exc}"
                )
                checks["topic_publisher_teardown_error"] = teardown_reason
                reason = _append_reason(reason, teardown_reason)
                requested_status = "BLOCKED"
        if (
            prepared is not None
            and prepared.cleanup_before_shutdown is not None
        ):
            try:
                cleanup_value = prepared.cleanup_before_shutdown()
                cleanup_evidence = _json_value(cleanup_value)
            except BaseException as exc:  # noqa: BLE001 - cleanup gates isolation
                cleanup_reason = (
                    "scenario-owned pre-shutdown cleanup failed: "
                    f"{_bounded_exception_summary(exc)}"
                )
                checks["pre_shutdown_cleanup_error"] = cleanup_reason
                reason = _append_reason(reason, cleanup_reason)
                requested_status = "BLOCKED"
            else:
                checks["pre_shutdown_cleanup"] = cleanup_evidence
        if direct is not None:
            try:
                close_complete = direct.close()
                checks["trusted_direct_call_count"] = len(direct.calls)
                if close_complete is False:
                    direct_close_deferred = True
                    checks["direct_client_closed"] = False
                    checks["direct_client_close_deferred"] = True
                else:
                    checks["direct_client_closed"] = True
            except BaseException as exc:  # noqa: BLE001
                checks["direct_client_closed"] = False
                close_reason = f"direct client close: {type(exc).__name__}: {exc}"
                checks["direct_client_close_error"] = close_reason
                reason = _append_reason(reason, close_reason)
                requested_status = "BLOCKED"
        if runtime is not None:
            def finish_post_shutdown(runtime_value: ScenarioRuntime) -> None:
                post_shutdown_errors: list[str] = []
                if direct_close_deferred:
                    assert direct is not None
                    finish_close = getattr(direct, "finish_close", None)
                    if not callable(finish_close):
                        checks["direct_client_close_error"] = (
                            "direct client has no post-shutdown close boundary"
                        )
                        post_shutdown_errors.append(
                            checks["direct_client_close_error"]
                        )
                    else:
                        try:
                            fully_closed = finish_close()
                        except BaseException as exc:  # noqa: BLE001
                            checks["direct_client_close_error"] = (
                                "direct client post-shutdown close: "
                                f"{type(exc).__name__}: {exc}"
                            )
                            post_shutdown_errors.append(
                                checks["direct_client_close_error"]
                            )
                        else:
                            if fully_closed is not True:
                                checks["direct_client_close_error"] = (
                                    "direct client remained alive after Wwise shutdown"
                                )
                                post_shutdown_errors.append(
                                    checks["direct_client_close_error"]
                                )
                            else:
                                checks["direct_client_closed"] = True
                                checks[
                                    "direct_client_close_reaped_after_shutdown"
                                ] = True
                if prepared is not None and prepared.post_shutdown is not None:
                    try:
                        prepared.post_shutdown(runtime_value)
                    except BaseException as exc:  # noqa: BLE001
                        post_shutdown_errors.append(
                            "scenario post-shutdown hook: "
                            f"{type(exc).__name__}: {exc}"
                        )
                elif prepared is None:
                    fallback = _media_post_shutdown_fallback(
                        unit.scenario,
                        media_holder,
                    )
                    if fallback is not None:
                        try:
                            fallback(runtime_value)
                        except BaseException as exc:  # noqa: BLE001
                            post_shutdown_errors.append(
                                "fallback post-shutdown hook: "
                                f"{type(exc).__name__}: {exc}"
                            )
                if post_shutdown_errors:
                    raise _HeavyProjectInfrastructureError(
                        "; ".join(post_shutdown_errors)
                    )

            try:
                lifecycle_result = lifecycle.finish(
                    requested_status,
                    reason=reason,
                    post_shutdown_hook=finish_post_shutdown,
                )
            except BaseException as exc:  # noqa: BLE001
                requested_status = "BLOCKED"
                reason = _append_reason(reason, f"lifecycle finish: {type(exc).__name__}: {exc}")
            else:
                requested_status = lifecycle_result.final_status
                if lifecycle_result.errors:
                    lifecycle_errors = tuple(
                        row
                        for row in lifecycle_result.errors
                        if not row.startswith("scenario:")
                    )
                    if lifecycle_errors:
                        reason = _append_reason(reason, "; ".join(lifecycle_errors))
        elif "global_user_state_before" in media_holder:
            try:
                isolation_evidence = _archive_early_media_isolation_proof(
                    unit.scenario,
                    media_holder,
                    scenario_root=root,
                )
            except BaseException as exc:  # noqa: BLE001 - protect the real account
                isolation_reason = (
                    "early Media Pool isolation proof: "
                    f"{type(exc).__name__}: {exc}"
                )
                checks["early_media_isolation_error"] = isolation_reason
                reason = _append_reason(reason, isolation_reason)
                requested_status = "BLOCKED"
            else:
                checks["early_media_isolation"] = isolation_evidence

    outcome = HeavyProjectRunOutcome(
        scenario_id=unit.unit_id,
        version=unit.version,
        status=requested_status,
        reason=reason,
        scenario_root=str(root),
        task_root=(
            str(runtime.evidence_root / "codex-task")
            if runtime is not None
            and (runtime.evidence_root / "codex-task").is_dir()
            else None
        ),
        thread_id=(
            task.thread_id
            if task is not None
            else failed_task_thread_id
        ),
        checks=MappingProxyType(dict(checks)),
        lifecycle=lifecycle_result.as_dict() if lifecycle_result is not None else None,
    )
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "outcome.json", outcome.as_dict())
    if cancelled is not None:
        raise cancelled
    return outcome


def _codex_infrastructure_failure_evidence(
    exc: CodexInfrastructureError,
) -> dict[str, Any]:
    """Archive the closed pre-agent facts without parsing exception prose."""

    failure = exc.failure
    return {
        "category": failure.category,
        "turn_failed": failure.turn_failed,
        "timed_out": failure.timed_out,
        "agent_item_event_count": failure.agent_item_event_count,
    }


class _CaseObservers:
    def __init__(
        self,
        *,
        scenario: OnlineScenario,
        prepared: _PreparedCase,
        direct: OwnedDirectWaapiCall,
        endpoint: str,
        version: str,
        business_oracle_plan_sha256: str,
        project_modification_policy: str = "ask_before_changes",
        enforce_policy_turn_oracles: bool = False,
        publisher_client_factory: Callable[[], OwnedDirectWaapiCall] | None = None,
        publisher_process_target: Callable[..., None] | None = None,
    ) -> None:
        self.scenario = scenario
        self.prepared = prepared
        self.direct = direct
        self.endpoint = endpoint
        self.version = version
        self.business_oracle_plan_sha256 = business_oracle_plan_sha256
        self.project_modification_policy = project_modification_policy
        self.policy_baseline = (
            prepared.snapshot()
            if enforce_policy_turn_oracles
            and project_modification_policy
            in {"read_only", "ask_before_changes", "allow_changes"}
            else None
        )
        # An explicit factory keeps the cheap in-process fake lane available to
        # unit tests.  Production leaves it unset and always uses spawn.
        self._publisher_client_factory = publisher_client_factory
        self._publisher_process_target = (
            publisher_process_target or _topic_publisher_process_main
        )
        self.preview_snapshots: dict[str, Any] = {}
        self.payloads: dict[str, Mapping[str, Any]] = {}
        self.checks: dict[str, Any] = {}
        self.topic_payload: Mapping[str, Any] | None = None
        self._publisher_thread: threading.Thread | None = None
        self._publisher_abort = threading.Event()
        self._publisher_error: BaseException | None = None
        self._publisher_results: list[Any] = []
        self._publisher_direct_call_count = 0
        self._publisher_client_opened = False
        self._publisher_client_closed = False
        self._subscription_ack_expectation: TrustedSubscriptionAckExpectation | None = None
        self._subscription_ack_payload: Mapping[str, Any] | None = None
        self._subscription_ack_file_sha256 = ""
        self._subscription_ack_observed_at_monotonic_ns = 0
        self._publisher_started_at_monotonic_ns = 0
        self._publisher_finished_at_monotonic_ns = 0
        self._publisher_call_started_at_monotonic_ns: list[int] = []
        self._publisher_call_evidence: list[dict[str, Any]] = []
        self._publisher_error_summary: str | None = None
        self._publisher_execution_mode = (
            "injected_thread"
            if publisher_client_factory is not None
            else "spawn_process"
        )
        self._publisher_process_pid: int | None = None
        self._publisher_process_exit_code: int | None = None
        self._publisher_process_reaped = False
        self._publisher_process_terminate_requested = False
        self._publisher_process_kill_requested = False
        self._publisher_child_result_received = False
        self._publisher_child_parent_process_id: int | None = None
        self._publisher_child_started_at_monotonic_ns: int | None = None
        self._publisher_child_finished_at_monotonic_ns: int | None = None
        self._publisher_process_cleanup_error: str | None = None

    def before_gateway_step(
        self,
        step: ExpectedGatewayStep,
        _state_directory: Path,
        _evidence_directory: Path,
    ) -> None:
        if step.name.endswith(".preview"):
            self.preview_snapshots[step.name] = self.prepared.snapshot()

    def before_subscription_wait(
        self,
        expectation: TrustedSubscriptionAckExpectation,
    ) -> None:
        """Start the runner publisher only as an ACK-gated waiter."""

        if self.prepared.topic_payload_step is None:
            raise _HeavyProjectInfrastructureError(
                "broker supplied a subscription ACK for a non-topic case"
            )
        if (
            not isinstance(expectation, TrustedSubscriptionAckExpectation)
            or expectation.contract != SUBSCRIPTION_ACK_CONTRACT
            or expectation.step_name != self.prepared.topic_payload_step
            or expectation.topic != self.scenario.api
            or expectation.path.parent.name != "evidence"
            or expectation.path.parent.parent.name != "broker"
            or not expectation.path.is_absolute()
            or expectation.path.exists()
            or expectation.path.is_symlink()
        ):
            raise _HeavyProjectInfrastructureError(
                "broker subscription ACK expectation is misbound or not fresh"
            )
        self._validate_subscription_ack_plan(expectation)
        self._subscription_ack_expectation = expectation
        self._start_topic_publishers()

    def _validate_subscription_ack_plan(
        self,
        expectation: TrustedSubscriptionAckExpectation,
    ) -> None:
        sections = self.prepared.typed_sections
        topic = (
            sections.live_binding.get("topic")
            if isinstance(sections, SoundBankBusinessPlanSections)
            else None
        )
        requirement = (
            topic.get("subscription_ack_requirement")
            if isinstance(topic, Mapping)
            else None
        )
        if requirement != {
            "contract": TOPIC_ACK_REQUIREMENT_CONTRACT,
            "ack_contract": SUBSCRIPTION_ACK_CONTRACT,
            "step_name": expectation.step_name,
            "topic": expectation.topic,
            "fresh_exclusive_path_required": True,
            "publisher_requires_valid_ack": True,
        }:
            raise _HeavyProjectInfrastructureError(
                "SoundBank business plan does not bind the subscription ACK gate"
            )

    def after_gateway_step(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
        _state_directory: Path,
        _evidence_directory: Path,
    ) -> None:
        self.payloads[step.name] = payload
        if self.prepared.observe_payload is not None:
            self.prepared.observe_payload(step, payload)
        if step.name.endswith(".transaction-show"):
            self.checks[f"{step.name}.confirmation_binding"] = (
                validate_transaction_show_confirmation_against_store(
                    payload,
                    _state_directory,
                )
            )
        if step.name.endswith(".preview"):
            before = self.preview_snapshots.get(step.name)
            after = self.prepared.snapshot()
            if before != after:
                raise HeavyProjectRunnerError(
                    f"{self.scenario.id} preview changed the hidden business snapshot"
                )
            self.checks[f"{step.name}.unchanged"] = True
            if self.prepared.verify_preview is not None:
                verification = self.prepared.verify_preview(payload)
                _assert_verification(
                    verification,
                    context=f"{step.name} business preview",
                )
                self.checks[f"{step.name}.business_preview"] = _json_value(
                    verification
                )
            if self.prepared.verify_refusal is not None:
                verification = self.prepared.verify_refusal(payload)
                _assert_verification(verification, context=f"{step.name} refusal")
                self.checks[f"{step.name}.refusal"] = _oracle_evidence(
                    scenario=self.scenario,
                    version=self.version,
                    runner="project",
                    business_oracle_plan_sha256=self.business_oracle_plan_sha256,
                    verification=verification,
                )
        if step.name == self.prepared.topic_payload_step:
            self.topic_payload = payload
        if step.name.endswith(".verify") and step.name == _last_verify_step(self.prepared.protocol):
            verification = self.prepared.verify_final(payload, _EMPTY_CODEX_RESULT)
            _assert_verification(verification, context=f"{step.name} business oracle")
            self.checks["business_verification"] = _oracle_evidence(
                scenario=self.scenario,
                version=self.version,
                runner="project",
                business_oracle_plan_sha256=self.business_oracle_plan_sha256,
                verification=verification,
            )

    def after_turn(
        self,
        turn_index: int,
        result: CodexRunResult,
        _broker_evidence: Any,
    ) -> None:
        if turn_index == 1:
            intro_response = first_gateway_backed_agent_message(
                result.stdout,
                validated_gateway_commands=result.command_facts.gateway_commands,
            )
            if intro_response is None:
                raise HeavyProjectRunnerError(
                    "first Skill-backed response has no visible agent message "
                    "after the first validated gateway command"
                )
            _require_natural_intro(
                intro_response,
                endpoint=self.endpoint,
                version=self.version,
                policy=self.project_modification_policy,
            )
            self.checks["first_use_intro"] = True
        if self.policy_baseline is not None and (
            self.project_modification_policy == "read_only"
            or (
                self.project_modification_policy == "ask_before_changes"
                and turn_index == 1
            )
        ):
            if self.policy_baseline is None or (
                self.prepared.snapshot() != self.policy_baseline
            ):
                raise HeavyProjectRunnerError(
                    f"{self.project_modification_policy} changed the project "
                    f"during turn {turn_index}"
                )
            self.checks[
                f"policy_turn_{turn_index:02d}_project_unchanged"
            ] = True
            _require_policy_turn_response(
                result,
                policy=self.project_modification_policy,
                turn_index=turn_index,
                expected_change_terms=_policy_notice_change_terms(self.scenario),
            )
            self.checks[
                f"policy_turn_{turn_index:02d}_response"
            ] = True
        if self.prepared.verify_turn is not None:
            verification = self.prepared.verify_turn(turn_index, result)
            if verification is not None:
                _assert_verification(
                    verification,
                    context=f"turn {turn_index} workflow oracle",
                )
                self.checks[f"turn_{turn_index:02d}_workflow"] = _oracle_evidence(
                    scenario=self.scenario,
                    version=self.version,
                    runner="project",
                    business_oracle_plan_sha256=self.business_oracle_plan_sha256,
                    verification=verification,
                )
        if turn_index == len(self.prepared.protocol.turn_prefix_counts):
            if self.scenario.protocol == "single" and self.prepared.topic_payload_step is None:
                payload = self.payloads[self.prepared.protocol.steps[-1].name]
                verification = self.prepared.verify_final(payload, result)
                _assert_verification(verification, context="direct semantic oracle")
                self.checks["business_verification"] = _oracle_evidence(
                    scenario=self.scenario,
                    version=self.version,
                    runner="project",
                    business_oracle_plan_sha256=self.business_oracle_plan_sha256,
                    verification=verification,
                )
            self.checks["final_response_nonempty"] = bool(result.final_response.strip())
            if not result.final_response.strip():
                raise HeavyProjectRunnerError("final Codex response is empty")

    def finish(self) -> None:
        self._drain_topic_publishers(abort=False)
        if self.prepared.topic_payload_step is not None:
            if self.topic_payload is None:
                raise _HeavyProjectInfrastructureError(
                    "topic gateway step completed without a payload for final verification"
                )
            verification = self.prepared.verify_final(
                self.topic_payload,
                _EMPTY_CODEX_RESULT,
            )
            _assert_verification(verification, context="topic verification")
            self.checks["topic_verification"] = _oracle_evidence(
                scenario=self.scenario,
                version=self.version,
                runner="project",
                business_oracle_plan_sha256=self.business_oracle_plan_sha256,
                verification=verification,
            )

    def abort(self) -> None:
        """Stop and join any runner-owned publisher before main-client teardown."""

        self._drain_topic_publishers(abort=True)

    def _start_topic_publishers(self) -> None:
        if self._publisher_thread is not None:
            raise HeavyProjectRunnerError("topic publisher started more than once")
        if not self.prepared.topic_publishers:
            raise HeavyProjectRunnerError("topic wait has no runner-owned publisher")

        def publish() -> None:
            publish_error: BaseException | None = None
            try:
                ack_payload = self._wait_for_subscription_ack()
                if ack_payload is None:
                    return
                if self._publisher_abort.is_set():
                    return
                self._publisher_started_at_monotonic_ns = time.monotonic_ns()
                if self._publisher_client_factory is not None:
                    self._run_injected_topic_publishers()
                else:
                    self._run_spawned_topic_publishers()
            except BaseException as exc:  # noqa: BLE001
                publish_error = exc
            finally:
                # This timestamp proves the client/process teardown has already
                # completed, rather than merely proving the last WAAPI call did.
                self._publisher_finished_at_monotonic_ns = time.monotonic_ns()
                if publish_error is not None:
                    self._publisher_error_summary = _bounded_exception_summary(
                        publish_error
                    )
                    self._publisher_error = _HeavyProjectInfrastructureError(
                        "runner-owned topic publisher failed: "
                        f"{self._publisher_error_summary}"
                    )

        self._publisher_thread = threading.Thread(
            target=publish,
            name=f"v3-topic-publisher-{self.scenario.id}",
            daemon=True,
        )
        self._publisher_thread.start()

    def _run_injected_topic_publishers(self) -> None:
        if self._publisher_abort.is_set():
            return
        factory = self._publisher_client_factory
        assert factory is not None
        publisher_direct: OwnedDirectWaapiCall | None = None
        publish_error: BaseException | None = None
        active_call: dict[str, Any] | None = None
        try:
            publisher_direct = factory()
            if publisher_direct is self.direct:
                raise _HeavyProjectInfrastructureError(
                    "topic publisher must use an injected peer client"
                )
            self._publisher_client_opened = True
            for index, request_value in enumerate(
                self.prepared.topic_publishers,
                start=1,
            ):
                active_call = {
                    "index": index,
                    "request_sha256": _json_sha256(request_value),
                    "status": "preparing",
                }
                self._publisher_call_evidence.append(active_call)
                request = parse_operation_request(
                    request_value,
                    expected_version=self.version,
                )
                prepared = prepare_operation(request, read_call=publisher_direct)
                envelope = prepared.semantic_preview.envelope
                started = time.monotonic_ns()
                self._publisher_call_started_at_monotonic_ns.append(started)
                active_call.update(
                    {
                        "status": "started",
                        "uri": envelope.uri,
                        "args_sha256": _json_sha256(envelope.args),
                        "options_sha256": _json_sha256(envelope.options),
                        "started_at_monotonic_ns": started,
                    }
                )
                result = publisher_direct(
                    envelope.uri,
                    envelope.args,
                    envelope.options,
                )
                self._publisher_results.append(result)
                active_call.update(
                    {
                        "status": "succeeded",
                        "finished_at_monotonic_ns": time.monotonic_ns(),
                        "result": _bounded_json_evidence(result),
                    }
                )
                active_call = None
        except BaseException as exc:  # noqa: BLE001 - injected test boundary
            publish_error = exc
            if active_call is not None:
                active_call.update(
                    {
                        "status": "failed",
                        "finished_at_monotonic_ns": time.monotonic_ns(),
                        "error": _bounded_exception_summary(exc),
                    }
                )
        finally:
            if publisher_direct is not None:
                self._publisher_direct_call_count = len(publisher_direct.calls)
                try:
                    close_complete = publisher_direct.close()
                except BaseException as exc:  # noqa: BLE001
                    close_error = _HeavyProjectInfrastructureError(
                        "topic publisher injected client close failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    publish_error = close_error if publish_error is None else (
                        _HeavyProjectInfrastructureError(
                            "topic publisher failed and its injected client did not close: "
                            f"{type(publish_error).__name__}: {publish_error}; "
                            f"{type(exc).__name__}: {exc}"
                        )
                    )
                else:
                    self._publisher_client_closed = close_complete is not False
                    if not self._publisher_client_closed:
                        publish_error = _HeavyProjectInfrastructureError(
                            "topic publisher injected client close timed out"
                        )
            if publish_error is not None:
                raise publish_error

    def _run_spawned_topic_publishers(self) -> None:
        if self._publisher_abort.is_set():
            return
        context = multiprocessing.get_context("spawn")
        receive_connection, send_connection = context.Pipe(duplex=False)
        request_values = tuple(
            _json_value(value) for value in self.prepared.topic_publishers
        )
        process = context.Process(
            target=self._publisher_process_target,
            args=(
                self.direct.host,
                self.direct.port,
                self.version,
                request_values,
                send_connection,
            ),
            name=f"v3-topic-publisher-child-{self.scenario.id}",
            daemon=True,
        )
        raw_result: bytes | None = None
        timed_out = False
        process_started = False
        primary_error: BaseException | None = None
        try:
            if self._publisher_abort.is_set():
                return
            process.start()
            process_started = True
            self._publisher_process_pid = process.pid
            send_connection.close()
            deadline = time.monotonic() + _TOPIC_PROCESS_WAIT_SECONDS
            while process.is_alive():
                if raw_result is None and receive_connection.poll(
                    _TOPIC_ACK_POLL_SECONDS
                ):
                    raw_result = receive_connection.recv_bytes(
                        maxlength=_TOPIC_CHILD_RESULT_CEILING_BYTES
                    )
                process.join(timeout=0)
                if not process.is_alive():
                    break
                if self._publisher_abort.is_set():
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
            if process.is_alive():
                self._terminate_and_reap_topic_process(process)
            self._capture_topic_process_exit(process)
            if not self._publisher_process_reaped:
                raise _HeavyProjectInfrastructureError(
                    "topic publisher child remained alive after TERM and KILL"
                )
            if raw_result is None and receive_connection.poll(0):
                raw_result = receive_connection.recv_bytes(
                    maxlength=_TOPIC_CHILD_RESULT_CEILING_BYTES
                )
            if self._publisher_abort.is_set():
                return
            if timed_out:
                raise _HeavyProjectInfrastructureError(
                    "topic publisher child exceeded its bounded runtime"
                )
            if self._publisher_process_exit_code != 0:
                raise _HeavyProjectInfrastructureError(
                    "topic publisher child exited unsuccessfully: "
                    f"{self._publisher_process_exit_code}"
                )
            if raw_result is None:
                raise _HeavyProjectInfrastructureError(
                    "topic publisher child exited without canonical evidence"
                )
            self._consume_topic_publisher_child_result(raw_result)
        except BaseException as exc:  # noqa: BLE001 - cleanup must still reap child
            primary_error = exc
        finally:
            if process_started and self._topic_process_is_alive(process):
                self._terminate_and_reap_topic_process(process)
            if process_started:
                self._capture_topic_process_exit(process)
            for label, connection in (
                ("send-pipe-close", send_connection),
                ("receive-pipe-close", receive_connection),
            ):
                try:
                    connection.close()
                except BaseException as exc:  # noqa: BLE001
                    self._record_topic_process_cleanup_error(label, exc)
            if self._publisher_process_reaped:
                try:
                    process.close()
                except BaseException as exc:  # noqa: BLE001
                    self._record_topic_process_cleanup_error(
                        "process-handle-close",
                        exc,
                    )
            elif not process_started:
                try:
                    process.close()
                except BaseException as exc:  # noqa: BLE001
                    self._record_topic_process_cleanup_error(
                        "unstarted-process-handle-close",
                        exc,
                    )
        if self._publisher_process_cleanup_error is not None:
            cleanup_error = _HeavyProjectInfrastructureError(
                "topic publisher child cleanup failed: "
                f"{self._publisher_process_cleanup_error}"
            )
            if primary_error is not None:
                raise cleanup_error from primary_error
            raise cleanup_error
        if primary_error is not None:
            raise primary_error

    def _terminate_and_reap_topic_process(self, process: Any) -> None:
        if self._topic_process_is_alive(process):
            self._publisher_process_terminate_requested = True
            try:
                process.terminate()
                process.join(timeout=_TOPIC_PROCESS_TERMINATE_SECONDS)
            except BaseException as exc:  # noqa: BLE001
                self._record_topic_process_cleanup_error("terminate", exc)
        if self._topic_process_is_alive(process):
            self._publisher_process_kill_requested = True
            try:
                process.kill()
                process.join(timeout=_TOPIC_PROCESS_KILL_SECONDS)
            except BaseException as exc:  # noqa: BLE001
                self._record_topic_process_cleanup_error("kill", exc)

    def _capture_topic_process_exit(self, process: Any) -> None:
        try:
            alive = process.is_alive()
            exit_code = process.exitcode
        except BaseException as exc:  # noqa: BLE001
            self._record_topic_process_cleanup_error("capture-exit", exc)
            return
        self._publisher_process_reaped = not alive and exit_code is not None
        self._publisher_process_exit_code = exit_code

    def _topic_process_is_alive(self, process: Any) -> bool:
        try:
            return bool(process.is_alive())
        except BaseException as exc:  # noqa: BLE001
            self._record_topic_process_cleanup_error("is-alive", exc)
            return False

    def _record_topic_process_cleanup_error(
        self,
        label: str,
        exc: BaseException,
    ) -> None:
        value = f"{label}: {_bounded_exception_summary(exc)}"
        self._publisher_process_cleanup_error = (
            value
            if self._publisher_process_cleanup_error is None
            else f"{self._publisher_process_cleanup_error}; {value}"
        )

    def _consume_topic_publisher_child_result(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _HeavyProjectInfrastructureError(
                f"topic publisher child evidence is unreadable: {exc}"
            ) from exc
        canonical = _canonical_json_bytes(payload) + b"\n"
        expected_keys = {
            "contract",
            "process_id",
            "parent_process_id",
            "version",
            "request_count",
            "started_at_monotonic_ns",
            "finished_at_monotonic_ns",
            "client_opened",
            "client_closed",
            "direct_call_count",
            "result_count",
            "publisher_call_started_at_monotonic_ns",
            "publisher_call_evidence",
            "error",
        }
        if (
            raw != canonical
            or not isinstance(payload, Mapping)
            or set(payload) != expected_keys
            or payload.get("contract") != _TOPIC_CHILD_RESULT_CONTRACT
            or payload.get("process_id") != self._publisher_process_pid
            or payload.get("parent_process_id") != os.getpid()
            or payload.get("version") != self.version
            or payload.get("request_count") != len(self.prepared.topic_publishers)
            or type(payload.get("started_at_monotonic_ns")) is not int
            or type(payload.get("finished_at_monotonic_ns")) is not int
            or payload.get("started_at_monotonic_ns", 0) <= 0
            or payload.get("finished_at_monotonic_ns", 0)
            < payload.get("started_at_monotonic_ns", 0)
            or type(payload.get("client_opened")) is not bool
            or type(payload.get("client_closed")) is not bool
            or type(payload.get("direct_call_count")) is not int
            or payload.get("direct_call_count", -1) < 0
            or type(payload.get("result_count")) is not int
            or not 0 <= payload.get("result_count", -1) <= len(
                self.prepared.topic_publishers
            )
            or not isinstance(
                payload.get("publisher_call_started_at_monotonic_ns"),
                list,
            )
            or not isinstance(payload.get("publisher_call_evidence"), list)
            or payload.get("error") is not None
            and not isinstance(payload.get("error"), str)
        ):
            raise _HeavyProjectInfrastructureError(
                "topic publisher child evidence has an invalid contract"
            )
        started_values = payload["publisher_call_started_at_monotonic_ns"]
        call_evidence = payload["publisher_call_evidence"]
        succeeded_rows = [
            value
            for value in call_evidence
            if isinstance(value, Mapping) and value.get("status") == "succeeded"
        ]
        evidence_started_values = [
            value.get("started_at_monotonic_ns")
            for value in call_evidence
            if isinstance(value, Mapping)
            and "started_at_monotonic_ns" in value
        ]
        if (
            not payload["result_count"] <= len(started_values) <= len(call_evidence)
            or len(call_evidence) > len(self.prepared.topic_publishers)
            or any(type(value) is not int or value <= 0 for value in started_values)
            or any(not isinstance(value, Mapping) for value in call_evidence)
            or len(succeeded_rows) != payload["result_count"]
            or evidence_started_values != started_values
        ):
            raise _HeavyProjectInfrastructureError(
                "topic publisher child call evidence is malformed"
            )
        self._publisher_child_result_received = True
        self._publisher_child_parent_process_id = payload["parent_process_id"]
        self._publisher_child_started_at_monotonic_ns = payload[
            "started_at_monotonic_ns"
        ]
        self._publisher_child_finished_at_monotonic_ns = payload[
            "finished_at_monotonic_ns"
        ]
        self._publisher_client_opened = payload["client_opened"]
        self._publisher_client_closed = payload["client_closed"]
        self._publisher_direct_call_count = payload["direct_call_count"]
        self._publisher_results = [None] * payload["result_count"]
        self._publisher_call_started_at_monotonic_ns = list(started_values)
        self._publisher_call_evidence = [dict(value) for value in call_evidence]
        child_error = payload["error"]
        if child_error is not None:
            raise _HeavyProjectInfrastructureError(
                f"topic publisher child reported failure: {child_error}"
            )
        expected_count = len(self.prepared.topic_publishers)
        if (
            not self._publisher_client_opened
            or not self._publisher_client_closed
            or payload["request_count"] != expected_count
            or payload["result_count"] != expected_count
            or len(started_values) != expected_count
            or len(call_evidence) != expected_count
            or payload["direct_call_count"] < expected_count
        ):
            raise _HeavyProjectInfrastructureError(
                "topic publisher child did not complete every call and close its client"
            )
        for index, (request_value, evidence) in enumerate(
            zip(self.prepared.topic_publishers, call_evidence, strict=True),
            start=1,
        ):
            expected_uri: str | None = None
            arguments = (
                request_value.get("arguments")
                if isinstance(request_value, Mapping)
                else None
            )
            if isinstance(arguments, Mapping) and isinstance(
                arguments.get("api"),
                str,
            ):
                expected_uri = arguments["api"]
            started_at = evidence.get("started_at_monotonic_ns")
            finished_at = evidence.get("finished_at_monotonic_ns")
            if (
                set(evidence)
                != {
                    "index",
                    "request_sha256",
                    "status",
                    "uri",
                    "args_sha256",
                    "options_sha256",
                    "started_at_monotonic_ns",
                    "finished_at_monotonic_ns",
                    "result",
                }
                or evidence.get("index") != index
                or evidence.get("request_sha256") != _json_sha256(request_value)
                or evidence.get("status") != "succeeded"
                or not isinstance(evidence.get("uri"), str)
                or not evidence.get("uri")
                or expected_uri is not None
                and evidence.get("uri") != expected_uri
                or not _valid_sha256_text(evidence.get("args_sha256"))
                or not _valid_sha256_text(evidence.get("options_sha256"))
                or type(started_at) is not int
                or started_at != started_values[index - 1]
                or started_at < payload["started_at_monotonic_ns"]
                or type(finished_at) is not int
                or finished_at < started_at
                or finished_at > payload["finished_at_monotonic_ns"]
                or not _valid_bounded_json_evidence(evidence.get("result"))
            ):
                raise _HeavyProjectInfrastructureError(
                    "topic publisher child success evidence is not closed"
                )

    def _wait_for_subscription_ack(self) -> Mapping[str, Any] | None:
        expectation = self._subscription_ack_expectation
        if expectation is None:
            raise _HeavyProjectInfrastructureError(
                "topic publisher has no broker subscription ACK expectation"
            )
        deadline = time.monotonic() + _TOPIC_ACK_WAIT_SECONDS
        while True:
            if self._publisher_abort.is_set():
                return None
            try:
                candidate_metadata = expectation.path.lstat()
            except FileNotFoundError:
                candidate_metadata = None
            except OSError as exc:
                raise _HeavyProjectInfrastructureError(
                    f"topic subscription ACK is unavailable: {exc}"
                ) from exc
            if candidate_metadata is not None:
                if path_is_link_or_reparse(
                    expectation.path,
                    metadata=candidate_metadata,
                ):
                    raise _HeavyProjectInfrastructureError(
                        "topic subscription ACK target became a link or reparse point"
                    )
                if (
                    stat.S_ISREG(candidate_metadata.st_mode)
                    and candidate_metadata.st_nlink == 1
                ):
                    break
                if (
                    not stat.S_ISREG(candidate_metadata.st_mode)
                    or candidate_metadata.st_nlink != 2
                ):
                    raise _HeavyProjectInfrastructureError(
                        "topic subscription ACK is not an exclusive regular file"
                    )
                # The atomic no-overwrite writer publishes by linking its
                # complete temp inode, then immediately unlinks the temp
                # name.  During that tiny interval the target legitimately
                # has nlink==2.  Retry only this exact transitional state;
                # final evidence must still reach nlink==1.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _HeavyProjectInfrastructureError(
                    "timed out waiting for one exclusive packaged gateway subscription ACK"
                )
            self._publisher_abort.wait(min(_TOPIC_ACK_POLL_SECONDS, remaining))

        try:
            snapshot = read_bounded_exclusive_regular_file(
                expectation.path,
                max_bytes=4096,
            )
            raw = snapshot.raw
        except CodexFileSecurityError as exc:
            raise _HeavyProjectInfrastructureError(
                f"topic subscription ACK failed its file-integrity boundary: {exc}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _HeavyProjectInfrastructureError(
                f"topic subscription ACK is unreadable: {exc}"
            ) from exc
        expected_keys = {
            "contract",
            "step_name",
            "topic",
            "nonce",
            "runner_parent_process_id",
            "gateway_process_id",
            "subscribed_at_unix_ns",
            "subscribed_at_monotonic_ns",
        }
        nonce = payload.get("nonce") if isinstance(payload, Mapping) else None
        nonce_sha256 = (
            hashlib.sha256(nonce.encode("utf-8")).hexdigest()
            if isinstance(nonce, str)
            else ""
        )
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected_keys
            or payload.get("contract") != expectation.contract
            or payload.get("step_name") != expectation.step_name
            or payload.get("topic") != expectation.topic
            or not isinstance(nonce, str)
            or not secrets.compare_digest(
                nonce_sha256,
                expectation.nonce_sha256,
            )
            or type(payload.get("runner_parent_process_id")) is not int
            or payload.get("runner_parent_process_id", 0) <= 0
            or type(payload.get("gateway_process_id")) is not int
            or payload.get("gateway_process_id", 0) <= 0
            or payload.get("gateway_process_id")
            == payload.get("runner_parent_process_id")
            or type(payload.get("subscribed_at_unix_ns")) is not int
            or type(payload.get("subscribed_at_monotonic_ns")) is not int
            or payload.get("subscribed_at_monotonic_ns", 0) <= 0
        ):
            raise _HeavyProjectInfrastructureError(
                "topic subscription ACK identity or timestamps are invalid"
            )
        canonical = (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if raw != canonical:
            raise _HeavyProjectInfrastructureError(
                "topic subscription ACK is not canonical JSON"
            )
        observed = time.monotonic_ns()
        if int(payload["subscribed_at_monotonic_ns"]) > observed:
            raise _HeavyProjectInfrastructureError(
                "topic subscription ACK monotonic timestamp is in the future"
            )
        self._subscription_ack_payload = MappingProxyType(dict(payload))
        self._subscription_ack_file_sha256 = hashlib.sha256(raw).hexdigest()
        self._subscription_ack_observed_at_monotonic_ns = observed
        return self._subscription_ack_payload

    def _drain_topic_publishers(self, *, abort: bool) -> None:
        if abort:
            self._publisher_abort.set()
        thread = self._publisher_thread
        if thread is None:
            return
        thread.join(timeout=_TOPIC_JOIN_SECONDS)
        self.checks["topic_publisher_call_count"] = len(self._publisher_results)
        self.checks["topic_publisher_direct_call_count"] = (
            self._publisher_direct_call_count
        )
        self.checks["topic_publisher_client_opened"] = self._publisher_client_opened
        self.checks["topic_publisher_client_closed"] = self._publisher_client_closed
        self.checks["topic_publisher_diagnostics"] = self._publisher_diagnostics(
            abort=abort,
        )
        if thread.is_alive():
            raise _HeavyProjectInfrastructureError(
                "topic publisher coordinator did not finish before teardown"
            )
        if self._publisher_error is not None:
            raise _HeavyProjectInfrastructureError(
                "topic publisher failed: "
                f"{type(self._publisher_error).__name__}: {self._publisher_error}"
            )
        if not abort and self.prepared.topic_payload_step is not None:
            self.checks["topic_subscription_ack"] = self._subscription_ack_proof()

    def _publisher_diagnostics(self, *, abort: bool) -> Mapping[str, Any]:
        """Return bounded runner evidence even when the Codex task aborts.

        This record is diagnostic rather than functional coverage.  In
        particular, observing the private ACK file does not replace the
        broker-owned terminal ACK join required by the passing validator.
        """

        expectation = self._subscription_ack_expectation
        payload = self._subscription_ack_payload
        ack: dict[str, Any] | None = None
        if expectation is not None:
            ack = {
                "contract": expectation.contract,
                "step_name": expectation.step_name,
                "topic": expectation.topic,
                "path": str(expectation.path),
                "nonce_sha256": expectation.nonce_sha256,
                "observed": payload is not None,
                "file_sha256": self._subscription_ack_file_sha256 or None,
                "observed_at_monotonic_ns": (
                    self._subscription_ack_observed_at_monotonic_ns or None
                ),
            }
            if payload is not None:
                ack["payload"] = {
                    key: value
                    for key, value in payload.items()
                    if key != "nonce"
                }
        return MappingProxyType(
            {
                "contract": "waapi-skill.topic-publisher-diagnostics/v1",
                "diagnostic_only": True,
                "abort_requested": abort,
                "execution_mode": self._publisher_execution_mode,
                "ack": ack,
                "publisher_started_at_monotonic_ns": (
                    self._publisher_started_at_monotonic_ns or None
                ),
                "publisher_finished_at_monotonic_ns": (
                    self._publisher_finished_at_monotonic_ns or None
                ),
                "publisher_call_evidence": tuple(
                    dict(value) for value in self._publisher_call_evidence
                ),
                "result_count": len(self._publisher_results),
                "direct_call_count": self._publisher_direct_call_count,
                "client_opened": self._publisher_client_opened,
                "client_closed": self._publisher_client_closed,
                "child_process": {
                    "start_method": (
                        "spawn"
                        if self._publisher_execution_mode == "spawn_process"
                        else None
                    ),
                    "coordinator_process_id": os.getpid(),
                    "pid": self._publisher_process_pid,
                    "parent_pid": self._publisher_child_parent_process_id,
                    "exit_code": self._publisher_process_exit_code,
                    "reaped": self._publisher_process_reaped,
                    "terminate_requested": (
                        self._publisher_process_terminate_requested
                    ),
                    "kill_requested": self._publisher_process_kill_requested,
                    "canonical_result_received": (
                        self._publisher_child_result_received
                    ),
                    "child_started_at_monotonic_ns": (
                        self._publisher_child_started_at_monotonic_ns
                    ),
                    "child_finished_at_monotonic_ns": (
                        self._publisher_child_finished_at_monotonic_ns
                    ),
                    "cleanup_error": self._publisher_process_cleanup_error,
                },
                "error": self._publisher_error_summary,
            }
        )

    def _subscription_ack_proof(self) -> Mapping[str, Any]:
        expectation = self._subscription_ack_expectation
        payload = self._subscription_ack_payload
        if (
            expectation is None
            or payload is None
            or not self._subscription_ack_file_sha256
            or self._subscription_ack_observed_at_monotonic_ns <= 0
            or self._publisher_started_at_monotonic_ns <= 0
            or not self._publisher_call_started_at_monotonic_ns
        ):
            raise _HeavyProjectInfrastructureError(
                "topic publisher lacks complete subscription ACK-before-publish evidence"
            )
        subscribed = int(payload["subscribed_at_monotonic_ns"])
        observed = self._subscription_ack_observed_at_monotonic_ns
        started = self._publisher_started_at_monotonic_ns
        calls = tuple(self._publisher_call_started_at_monotonic_ns)
        if not subscribed <= observed <= started <= min(calls):
            raise _HeavyProjectInfrastructureError(
                "topic publisher began before its validated subscription ACK"
            )
        requirement = {
            "contract": TOPIC_ACK_REQUIREMENT_CONTRACT,
            "ack_contract": SUBSCRIPTION_ACK_CONTRACT,
            "step_name": expectation.step_name,
            "topic": expectation.topic,
            "fresh_exclusive_path_required": True,
            "publisher_requires_valid_ack": True,
        }
        return MappingProxyType(
            {
                "contract": TOPIC_ACK_PROOF_CONTRACT,
                "business_oracle_plan_sha256": self.business_oracle_plan_sha256,
                "requirement": requirement,
                "ack_path": str(expectation.path),
                "ack_file_sha256": self._subscription_ack_file_sha256,
                "ack_payload": dict(payload),
                "ack_observed_at_monotonic_ns": observed,
                "publisher_started_at_monotonic_ns": started,
                "publisher_call_started_at_monotonic_ns": list(calls),
                "ack_before_publish": True,
            }
        )


@dataclass(frozen=True, slots=True)
class _MediaSemanticVerification:
    passed: bool
    failures: tuple[str, ...]
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _DirectSemanticVerification:
    passed: bool
    failures: tuple[str, ...]
    evidence: Mapping[str, Any]


class _PreparedMediaPoolAdapter:
    def __init__(
        self,
        *,
        scenario: OnlineScenario,
        runtime: ScenarioRuntime,
        direct: OwnedDirectWaapiCall,
        staged: StagedMediaPoolCase,
        preflight: MediaPoolPreflight,
        oracle: SealedMediaPoolOracle,
        fields: tuple[str, ...],
        protocol: V3GatewayProtocol,
        reference_baseline: Mapping[str, Any] | None,
        project_digest: str,
        custom_baseline_ids: tuple[str, ...],
        custom_created_ids: Mapping[str, str],
        waapi_y_drive_root: Path | None,
    ) -> None:
        self.scenario = scenario
        self.runtime = runtime
        self.direct = direct
        self.staged = staged
        self.preflight = preflight
        self.oracle = oracle
        self.fields = fields
        self.protocol = protocol
        self.reference_baseline = reference_baseline
        self.project_digest = project_digest
        self.custom_baseline_ids = custom_baseline_ids
        self.custom_created_ids = custom_created_ids
        self.waapi_y_drive_root = waapi_y_drive_root
        self.model_get_fields: Mapping[str, Any] | None = None
        self.model_media_result: Mapping[str, Any] | None = None
        self.model_reference_result: Mapping[str, Any] | None = None
        self.cleanup_final_ids: tuple[str, ...] | None = None

    def snapshot(self) -> tuple[Any, ...]:
        return (
            fingerprint_tree(
                self.staged.materialized.asset_root / "database-inputs"
            ),
            tuple(
                (
                    str(item.indexed_host_path),
                    item.indexed_host_path.stat().st_size,
                    _sha256_file(item.indexed_host_path),
                )
                for item in self.staged.assets
            ),
            _project_document_digest(self.runtime.sandbox.sandbox_path),
        )

    def observe_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        if step.name == "media.get-fields":
            raw = _agent_result_mapping(payload, context=step.name)
            returned = raw.get("return")
            if not isinstance(returned, list) or tuple(returned) != self.fields:
                raise HeavyProjectRunnerError(
                    "model getFields result differs from the sealed live field inventory"
                )
            self.model_get_fields = raw
            return
        if step.name == "media.check":
            raw = _agent_result_mapping(payload, context=step.name)
            verification = verify_media_pool_result(self.oracle, raw)
            _assert_verification(verification, context="Media Pool business result")
            unchanged = verify_media_pool_read_unchanged(self.staged, self.oracle)
            _assert_verification(unchanged, context="Media Pool read-only state")
            self.model_media_result = raw
            return
        if step.name == "media.audio-sources":
            raw = _agent_result_mapping(payload, context=step.name)
            verification = verify_reference_match_result(
                self.staged,
                self.oracle,
                raw,
            )
            _assert_verification(
                verification,
                context="model compact Audio Source association query",
            )
            self.model_reference_result = raw

    def _restore_model_reads_from_gateway_results(
        self,
        result: CodexRunResult,
    ) -> None:
        """Restore exact reads from the already reconciled command evidence."""

        requirements = (
            ("media.get-fields", MEDIA_POOL_GET_FIELDS_URI),
            ("media.check", MEDIA_POOL_GET_URI),
        )
        results = result.command_facts.gateway_results
        for step_name, api in requirements:
            steps = tuple(
                step for step in self.protocol.steps if step.name == step_name
            )
            if len(steps) != 1:
                raise HeavyProjectRunnerError(
                    f"media protocol requires exactly one {step_name} step"
                )
            step = steps[0]
            matches = tuple(
                payload
                for payload in results
                if isinstance(payload, Mapping)
                and payload.get("command") == step.subcommand
                and payload.get("api_attempted") == api
                and payload.get("ok") is True
                and payload.get("status") == "ok"
            )
            if len(matches) != 1:
                raise HeavyProjectRunnerError(
                    f"expected exactly one reconciled {step_name} gateway result"
                )
            self.observe_payload(step, matches[0])

    def verify_final(
        self,
        _payload: Mapping[str, Any] | None,
        result: CodexRunResult,
    ) -> _MediaSemanticVerification:
        if self.model_get_fields is None or self.model_media_result is None:
            self._restore_model_reads_from_gateway_results(result)
        failures: list[str] = []
        if self.model_get_fields is None or self.model_media_result is None:
            failures.append("model did not complete both Media Pool reads")
        if self.reference_baseline is not None and self.model_reference_result is None:
            failures.append("model omitted the required Audio Source association read")
        current_project_digest = _project_document_digest(
            self.runtime.sandbox.sandbox_path
        )
        if current_project_digest != self.project_digest:
            failures.append("read-only Media Pool task changed project documents")
        failures.extend(
            _media_final_response_failures(
                self.oracle,
                self.staged,
                result.final_response,
            )
        )
        return _MediaSemanticVerification(
            passed=not failures,
            failures=tuple(failures),
            evidence=MappingProxyType(
                {
                    "sealed_oracle": _json_value(self.oracle),
                    "source_fingerprint_after": _json_value(
                        fingerprint_tree(
                            self.staged.materialized.asset_root / "database-inputs"
                        )
                    ),
                    "staged_assets_after": [
                        {
                            "key": item.asset.key,
                            "path": str(item.indexed_host_path),
                            "size": item.indexed_host_path.stat().st_size,
                            "sha256": _sha256_file(item.indexed_host_path),
                        }
                        for item in self.staged.assets
                    ],
                    "model_get_fields": _json_value(self.model_get_fields),
                    "model_media_result": _json_value(self.model_media_result),
                    "model_reference_result": _json_value(
                        self.model_reference_result
                    ),
                    "reference_baseline": _json_value(self.reference_baseline),
                    "project_digest_before": self.project_digest,
                    "project_digest_after": current_project_digest,
                    "supporting_association_read": self.reference_baseline is not None,
                    "custom_baseline_ids": self.custom_baseline_ids,
                    "custom_created_ids": self.custom_created_ids,
                    "final_response_sha256": hashlib.sha256(
                        result.final_response.encode("utf-8")
                    ).hexdigest(),
                    "cleanup_evidence_path": str(
                        self.runtime.evidence_root / "media-pool-cleanup.json"
                    ),
                }
            ),
        )

    def cleanup_before_shutdown(self) -> Mapping[str, Any]:
        if not self.custom_created_ids:
            self.cleanup_final_ids = self.custom_baseline_ids
            return MappingProxyType({"custom_databases": 0})
        for call in build_custom_database_delete_calls(
            self.staged.materialized,
            self.custom_created_ids,
        ):
            _execute_closed_call(self.direct, call)
        final_ids = _read_user_database_ids(self.direct)
        if final_ids != self.custom_baseline_ids:
            raise HeavyProjectRunnerError(
                "case-owned Media Pool databases did not restore the baseline"
            )
        self.cleanup_final_ids = final_ids
        return MappingProxyType(
            {
                "custom_databases": len(self.custom_created_ids),
                "baseline_restored": True,
            }
        )

    def post_shutdown(self, _runtime: ScenarioRuntime) -> None:
        if self.cleanup_final_ids is None:
            raise HeavyProjectRunnerError(
                "Media Pool cleanup did not seal final database identities"
            )
        if self.custom_created_ids and self.preflight.isolation is None:
            raise HeavyProjectRunnerError(
                "custom database isolation proof is missing after Wwise stopped"
            )
        isolation = self.preflight.isolation
        global_state_before = (
            isolation.global_user_state_before if isolation is not None else None
        )
        global_state_after = (
            fingerprint_tree(global_state_before.root)
            if global_state_before is not None
            else None
        )
        if self.custom_created_ids:
            if global_state_after is None:
                raise HeavyProjectRunnerError(
                    "custom database cleanup lacks global state after-snapshot"
                )
            proof = CustomDatabaseCleanupProof(
                contract=CUSTOM_DATABASE_CLEANUP_CONTRACT,
                scenario_id=self.scenario.id,
                baseline_user_database_ids=self.custom_baseline_ids,
                created_database_ids=self.custom_created_ids,
                final_user_database_ids=self.cleanup_final_ids,
                global_user_state_after=global_state_after,
                wwise_process_stopped=True,
            )
            verification = verify_custom_database_cleanup(
                self.staged.materialized,
                self.preflight,
                proof,
            )
            _assert_verification(
                verification,
                context="post-shutdown custom database cleanup",
            )
        else:
            verification = {"ok": True, "code": "NO_CUSTOM_DATABASES", "details": {}}
        _write_json(
            self.runtime.evidence_root / "media-pool-cleanup.json",
            {
                "contract": "waapi-skill.media-pool-cleanup-evidence/v1",
                "scenario_id": self.scenario.id,
                "baseline_user_database_ids": self.custom_baseline_ids,
                "created_database_ids": self.custom_created_ids,
                "final_user_database_ids": self.cleanup_final_ids,
                "global_user_state_before": _json_value(global_state_before),
                "global_user_state_after": _json_value(global_state_after),
                "wwise_process_stopped": True,
                "verification": _json_value(verification),
                "passed": True,
            },
        )


def _prepare_media_pool_case(
    scenario: OnlineScenario,
    *,
    runtime: ScenarioRuntime,
    direct: OwnedDirectWaapiCall,
    staged: StagedMediaPoolCase,
    prelaunch_evidence: Mapping[str, Any],
) -> _PreparedCase:
    case = staged.materialized
    isolation: CustomDatabaseIsolation | None = None
    custom_baseline_ids: tuple[str, ...] = ()
    if case.requires_custom_database:
        isolation, custom_baseline_ids = _establish_custom_database_roundtrip(
            case,
            runtime=runtime,
            direct=direct,
            real_account_state_root=prelaunch_evidence.get(
                "real_account_state_root"
            ),
            global_before=prelaunch_evidence.get("global_user_state_before"),
        )
    preflight = media_pool_preflight(case, isolation=isolation)
    if not preflight.ready:
        raise HeavyProjectRunnerError(
            f"Media Pool preflight blocked: {preflight.code}: {preflight.reason}"
        )
    custom_created_ids: Mapping[str, str] = MappingProxyType({})
    if preflight.create_calls:
        results = tuple(
            _execute_closed_call(direct, call) for call in preflight.create_calls
        )
        custom_created_ids = parse_custom_database_create_results(case, results)
        observed_ids = set(_read_user_database_ids(direct))
        if not set(custom_created_ids.values()).issubset(observed_ids):
            raise HeavyProjectRunnerError(
                "created Media Pool database IDs are absent from User Databases"
            )

    waapi_y_drive_root: Path | None = None
    if os.name != "nt":
        launch_home_value: Any = runtime.runner_environment.get("HOME")
        if isinstance(
            isolation.host if isolation is not None else None,
            MacOSWineCustomDatabaseHost,
        ):
            launch_home_value = isolation.host.launch_home
        if not isinstance(launch_home_value, (str, Path)) or not str(
            launch_home_value
        ):
            raise HeavyProjectRunnerError(
                "Media Pool Wwise launch did not expose its HOME for Wine Y: binding"
            )
        waapi_y_drive_root = resolve_macos_wine_y_drive_root(
            Path(launch_home_value)
        )

    reference_call = build_reference_fixture_call(staged)
    if reference_call is not None:
        _execute_closed_call(direct, reference_call)
        direct("ak.wwise.core.project.save", {}, {})
    reference_read = build_reference_read_call(staged)
    reference_baseline = (
        _execute_closed_call(direct, reference_read)
        if reference_read is not None
        else None
    )
    if reference_baseline is not None:
        verification = verify_reference_associations(
            staged,
            reference_baseline,
            waapi_y_drive_root=waapi_y_drive_root,
        )
        _assert_verification(
            verification,
            context="trusted Audio Source association baseline",
        )

    fields = _wait_for_media_pool_fields(case, direct=direct)
    binding = bind_media_pool_fields(case, fields)
    request = bind_media_pool_request(case, binding)
    observed_rows = _wait_for_media_pool_index(
        staged,
        binding=binding,
        direct=direct,
    )
    oracle = seal_media_pool_index(
        staged,
        request,
        observed_rows,
        waapi_y_drive_root=waapi_y_drive_root,
    )
    _run_media_pool_full_request_preflight(
        runtime=runtime,
        direct=direct,
        staged=staged,
        oracle=oracle,
    )
    steps: list[ExpectedGatewayStep] = [
        request_schema_step(
            "media.get-fields.schema",
            MEDIA_POOL_GET_FIELDS_URI,
        ),
        call_step("media.get-fields", MEDIA_POOL_GET_FIELDS_URI, version=runtime.version),
    ]
    steps.extend(
        typed_read_draft_steps(
            "media",
            MEDIA_POOL_GET_URI,
            version=runtime.version,
            args=request.args,
            options=request.options,
            post_filter=request.post_filter,
        )
    )
    if reference_read is not None:
        steps.append(
            query_object_step(
                "media.audio-sources",
                build_reference_match_gateway_argv(reference_match_paths(oracle)),
            )
        )
    protocol = build_direct_protocol(steps)
    project_digest = _project_document_digest(runtime.sandbox.sandbox_path)
    typed_sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest=project_digest,
        reviewed_scenario_fixture=scenario.fixture,
    )
    validate_media_pool_business_plan(
        typed_sections,
        case,
        staged,
        oracle,
        protocol,
        project_digest=project_digest,
        reviewed_scenario_fixture=scenario.fixture,
        verify_files=True,
    )
    adapter = _PreparedMediaPoolAdapter(
        scenario=scenario,
        runtime=runtime,
        direct=direct,
        staged=staged,
        preflight=preflight,
        oracle=oracle,
        fields=fields,
        protocol=protocol,
        reference_baseline=reference_baseline,
        project_digest=project_digest,
        custom_baseline_ids=custom_baseline_ids,
        custom_created_ids=custom_created_ids,
        waapi_y_drive_root=waapi_y_drive_root,
    )
    return _PreparedCase(
        prompt=scenario.render_prompt({}),
        protocol=protocol,
        required_reference="references/waapi-query.md",
        snapshot=adapter.snapshot,
        verify_final=adapter.verify_final,
        typed_sections=typed_sections,
        cleanup_before_shutdown=adapter.cleanup_before_shutdown,
        observe_payload=adapter.observe_payload,
        post_shutdown=adapter.post_shutdown,
        visible_values=MappingProxyType({}),
    )


def _custom_database_host_from_runtime(
    runtime: ScenarioRuntime,
) -> MacOSWineCustomDatabaseHost | NativeWindowsCustomDatabaseHost:
    """Derive the host variant only from the runner's current process."""

    if os.name == "nt":
        roots: dict[str, Path] = {}
        for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            value = runtime.runner_environment.get(key)
            if not isinstance(value, str) or not value:
                raise HeavyProjectRunnerError(
                    f"native Windows custom database launch has no isolated {key}"
                )
            roots[key] = Path(value).resolve(strict=True)
        if runtime.sandbox.metadata.wine_prefix_path not in {None, ""}:
            raise HeavyProjectRunnerError(
                "native Windows custom database launch unexpectedly owns a Wine prefix"
            )
        return NativeWindowsCustomDatabaseHost(
            user_profile=roots["USERPROFILE"],
            appdata=roots["APPDATA"],
            local_appdata=roots["LOCALAPPDATA"],
        )

    launch_home_value = runtime.runner_environment.get("HOME")
    if not isinstance(launch_home_value, str) or not launch_home_value:
        raise HeavyProjectRunnerError(
            "custom database Wwise launch has no isolated HOME"
        )
    launch_home = Path(launch_home_value).resolve(strict=True)
    wine_prefix_value = runtime.runner_environment.get("WINEPREFIX")
    if not isinstance(wine_prefix_value, str) or not wine_prefix_value:
        raise HeavyProjectRunnerError(
            "custom database Wwise launch has no effective WINEPREFIX"
        )
    wine_prefix = validate_macos_wine_prefix(
        owned_root=runtime.owned_root,
        launch_home=launch_home,
        wine_prefix=Path(wine_prefix_value),
    )
    if runtime.sandbox.metadata.wine_prefix_path != str(wine_prefix):
        raise HeavyProjectRunnerError(
            "sandbox cleanup metadata is not bound to the effective WINEPREFIX"
        )
    return MacOSWineCustomDatabaseHost(
        launch_home=launch_home,
        wine_prefix=wine_prefix,
    )


def _establish_custom_database_roundtrip(
    case: MaterializedMediaPoolCase,
    *,
    runtime: ScenarioRuntime,
    direct: OwnedDirectWaapiCall,
    real_account_state_root: Any,
    global_before: Any,
) -> tuple[CustomDatabaseIsolation, tuple[str, ...]]:
    if not case.requires_custom_database:
        raise HeavyProjectRunnerError(
            "custom database round trip used for a Project Originals-only case"
        )
    build = _exact_wwise_build(runtime.lifecycle.ready_result)
    if build != SUPPORTED_BUILD:
        raise HeavyProjectRunnerError(
            f"custom database payload is proven only for {SUPPORTED_BUILD}; got {build}"
        )
    host = _custom_database_host_from_runtime(runtime)
    if not isinstance(real_account_state_root, Path):
        raise HeavyProjectRunnerError(
            "prelaunch real-account Wwise state root evidence is missing"
        )
    real_account_state_root = real_account_state_root.expanduser().resolve(
        strict=False
    )
    if real_account_state_root.is_relative_to(runtime.owned_root):
        raise HeavyProjectRunnerError(
            "real-account Wwise state unexpectedly overlaps case state"
        )
    if not hasattr(global_before, "root"):
        raise HeavyProjectRunnerError(
            "prelaunch real-account Wwise state fingerprint is missing"
        )
    global_state_root = global_before.root
    if global_state_root != real_account_state_root:
        raise HeavyProjectRunnerError(
            "prelaunch Wwise state fingerprint belongs to an unexpected root"
        )
    baseline_ids = _read_user_database_ids(direct)

    create_calls = build_custom_database_create_calls(
        case,
        owned_root=runtime.owned_root,
        host=host,
    )
    create_results = tuple(_execute_closed_call(direct, call) for call in create_calls)
    created = parse_custom_database_create_results(case, create_results)
    created_ids = set(created.values())
    if not created_ids.issubset(set(_read_user_database_ids(direct))):
        raise HeavyProjectRunnerError(
            "custom database round-trip create was not visible under User Databases"
        )
    for call in build_custom_database_delete_calls(case, created):
        _execute_closed_call(direct, call)
    if _read_user_database_ids(direct) != baseline_ids:
        raise HeavyProjectRunnerError(
            "custom database round-trip delete did not restore the baseline"
        )
    if fingerprint_tree(global_state_root) != global_before:
        raise HeavyProjectRunnerError(
            "real-account Wwise user state changed during isolated round trip"
        )

    evidence_path = runtime.owned_root / "evidence" / "custom-db-roundtrip.json"
    payload = custom_database_round_trip_evidence(host)
    _write_json(evidence_path, payload)
    proof = CustomDatabaseRoundTripProof(
        wwise_build=build,
        evidence_path=evidence_path,
        evidence_sha256=_sha256_file(evidence_path),
        payload_shape_sha256=custom_database_payload_shape_sha256(),
        host_mode=(
            "macos_wine"
            if isinstance(host, MacOSWineCustomDatabaseHost)
            else "native_windows"
        ),
    )
    isolation = CustomDatabaseIsolation(
        owned_root=runtime.owned_root,
        host=host,
        real_account_state_root=real_account_state_root,
        global_user_state_before=global_before,
        round_trip_proof=proof,
    )
    return isolation, baseline_ids


def _wait_for_media_pool_fields(
    case: MaterializedMediaPoolCase,
    *,
    direct: OwnedDirectWaapiCall,
    timeout_seconds: float = 30.0,
) -> tuple[str, ...]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    last_fields: tuple[Any, ...] = ()
    while True:
        raw = direct(MEDIA_POOL_GET_FIELDS_URI, {}, {})
        try:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("return"), list):
                raise HeavyProjectRunnerError(
                    "mediaPool.getFields direct result.return is not an array"
                )
            fields = tuple(raw["return"])
            last_fields = fields
            bind_media_pool_fields(case, fields)
            return fields
        except (ValueError, HeavyProjectRunnerError) as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise HeavyProjectRunnerError(
                "Media Pool field discovery did not converge: "
                f"{last_error}; field_count={len(last_fields)}; "
                f"fields={list(last_fields[:64])!r}"
            )
        time.sleep(0.25)


def _wait_for_media_pool_index(
    staged: StagedMediaPoolCase,
    *,
    binding: Any,
    direct: OwnedDirectWaapiCall,
    timeout_seconds: float = 45.0,
) -> tuple[Mapping[str, Any], ...]:
    calls = build_index_probe_calls(staged, binding)
    deadline = time.monotonic() + timeout_seconds
    last_counts: tuple[int, ...] = ()
    while True:
        observed: list[Mapping[str, Any]] = []
        counts: list[int] = []
        for call in calls:
            raw = _execute_closed_call(direct, call)
            rows = raw.get("return")
            if not isinstance(rows, list) or any(
                not isinstance(row, Mapping) for row in rows
            ):
                raise HeavyProjectRunnerError(
                    "Media Pool index probe returned malformed rows"
                )
            counts.append(len(rows))
            if len(rows) == 1:
                observed.append(rows[0])
        if len(observed) == len(calls) and all(count == 1 for count in counts):
            return tuple(observed)
        last_counts = tuple(counts)
        if time.monotonic() >= deadline:
            raise HeavyProjectRunnerError(
                "Media Pool index did not expose every case asset exactly once; "
                f"probe counts={last_counts}"
            )
        time.sleep(0.4)


def _execute_closed_call(
    direct: OwnedDirectWaapiCall,
    call: WaapiCall,
) -> Mapping[str, Any]:
    result = direct(call.uri, call.args, call.options)
    if not isinstance(result, Mapping):
        raise HeavyProjectRunnerError(
            f"trusted {call.uri} result must be a JSON object"
        )
    return MappingProxyType(dict(result))


def _run_media_pool_full_request_preflight(
    *,
    runtime: ScenarioRuntime,
    direct: OwnedDirectWaapiCall,
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
) -> Mapping[str, Any]:
    """Reproduce the sealed business query before starting a Codex process.

    Per-file Filename probes prove that every fixture asset was indexed, but do
    not prove that Wwise evaluates the complete combined filter as the fixture
    oracle does.  This preflight executes the exact bound request through the
    same live endpoint.  Case 03 also records one diagnostic request that
    differs only by the JSON number representation of its whole-second upper
    duration bound.  The diagnostic result is evidence, not a cross-build
    expectation: either an exact match or a mismatch is allowed.
    """

    evidence_path = runtime.evidence_root / "media-pool-full-request-preflight.json"
    project_digest_before = _project_document_digest(runtime.sandbox.sandbox_path)
    canonical_identity = _media_pool_request_identity(
        oracle.request.args,
        oracle.request.options,
        post_filter=oracle.request.post_filter,
        duration_field=oracle.request.binding.exact("duration"),
    )
    payload: dict[str, Any] = {
        "contract": MEDIA_POOL_FULL_REQUEST_PREFLIGHT_CONTRACT,
        "scenario_id": oracle.scenario_id,
        "api": MEDIA_POOL_GET_URI,
        "canonical_request": {
            **canonical_identity,
            "status": "pending",
            "result": None,
            "candidate_verification": None,
            "raw_count_below_max_results": None,
            "business_result": None,
            "verification": None,
            "post_filter_error": None,
        },
        "integer_wire_probe": {
            "performed": False,
            "reason": (
                "canonical_request_not_verified"
                if oracle.scenario_id == MEDIA_POOL_WIRE_NUMBER_PROBE_CASE_ID
                else "not_selected_for_this_scenario"
            ),
            "diagnostic_only": True,
        },
        "project_digest_before": project_digest_before,
        "project_digest_after": None,
        "read_state_verification": None,
        "passed": False,
    }

    try:
        canonical_result = _execute_closed_call(
            direct,
            WaapiCall(
                uri=MEDIA_POOL_GET_URI,
                args=oracle.request.args,
                options=oracle.request.options,
            ),
        )
    except BaseException as exc:  # noqa: BLE001 - archive the pre-agent blocker
        payload["canonical_request"]["status"] = "call_failed"
        payload["canonical_request"]["error"] = _bounded_exception_summary(exc)
        _finish_media_pool_full_request_preflight_evidence(
            payload,
            evidence_path=evidence_path,
            runtime=runtime,
            staged=staged,
            oracle=oracle,
        )
        raise _HeavyProjectInfrastructureError(
            "canonical Media Pool full-request preflight call failed"
        ) from exc

    candidate_verification = verify_media_pool_candidate_result(
        oracle,
        canonical_result,
    )
    raw_rows = canonical_result.get("return")
    raw_count = len(raw_rows) if isinstance(raw_rows, (list, tuple)) else None
    raw_count_below_max_results = (
        raw_count is not None
        and raw_count < int(oracle.request.args["maxResults"])
    )
    business_result: Mapping[str, Any] | None = None
    if candidate_verification.ok and raw_count_below_max_results:
        try:
            business_result = apply_media_pool_post_filter(
                oracle.request,
                canonical_result,
            )
        except Exception as exc:
            canonical_verification = None
            post_filter_error = _bounded_exception_summary(exc)
        else:
            canonical_verification = verify_media_pool_result(
                oracle,
                business_result,
            )
            post_filter_error = None
    else:
        canonical_verification = None
        post_filter_error = None
    payload["canonical_request"].update(
        {
            "status": (
                "verified_exact"
                if (
                    candidate_verification.ok
                    and raw_count_below_max_results
                    and canonical_verification is not None
                    and canonical_verification.ok
                )
                else "verification_failed"
            ),
            "result": _media_pool_result_identity(canonical_result),
            "candidate_verification": _json_value(candidate_verification),
            "raw_count_below_max_results": raw_count_below_max_results,
            "business_result": (
                None
                if business_result is None
                else _media_pool_result_identity(business_result)
            ),
            "verification": _json_value(canonical_verification),
            "post_filter_error": post_filter_error,
        }
    )
    if (
        not candidate_verification.ok
        or not raw_count_below_max_results
        or canonical_verification is None
        or not canonical_verification.ok
    ):
        _finish_media_pool_full_request_preflight_evidence(
            payload,
            evidence_path=evidence_path,
            runtime=runtime,
            staged=staged,
            oracle=oracle,
        )
        raise _HeavyProjectInfrastructureError(
            "canonical Media Pool full-request preflight did not reproduce the sealed candidate and business oracles"
        )

    if oracle.scenario_id == MEDIA_POOL_WIRE_NUMBER_PROBE_CASE_ID:
        integer_args, filter_index = _media_pool_case03_integer_upper_args(oracle)
        integer_identity = _media_pool_request_identity(
            integer_args,
            oracle.request.options,
            post_filter=oracle.request.post_filter,
            duration_field=oracle.request.binding.exact("duration"),
        )
        probe_record: dict[str, Any] = {
            "performed": True,
            "diagnostic_only": True,
            "changed_filter_index": filter_index,
            "only_int_float_representation_changed": True,
            **integer_identity,
            "status": "pending",
            "result": None,
            "verification": None,
            "matches_canonical_result_sha256": None,
        }
        payload["integer_wire_probe"] = probe_record
        try:
            integer_result = _execute_closed_call(
                direct,
                WaapiCall(
                    uri=MEDIA_POOL_GET_URI,
                    args=integer_args,
                    options=oracle.request.options,
                ),
            )
        except Exception as exc:  # diagnostic only; canonical proof already passed
            probe_record["status"] = "call_failed"
            probe_record["error"] = _bounded_exception_summary(exc)
        else:
            integer_verification = verify_media_pool_result(oracle, integer_result)
            integer_result_identity = _media_pool_result_identity(integer_result)
            probe_record.update(
                {
                    "status": "observed",
                    "result": integer_result_identity,
                    "verification": _json_value(integer_verification),
                    "matches_canonical_result_sha256": (
                        integer_result_identity["result_sha256"]
                        == payload["canonical_request"]["result"]["result_sha256"]
                    ),
                }
            )

    _finish_media_pool_full_request_preflight_evidence(
        payload,
        evidence_path=evidence_path,
        runtime=runtime,
        staged=staged,
        oracle=oracle,
    )
    if payload["project_digest_after"] != project_digest_before:
        raise _HeavyProjectInfrastructureError(
            "Media Pool full-request preflight changed project documents"
        )
    read_state = payload["read_state_verification"]
    if not isinstance(read_state, Mapping) or read_state.get("ok") is not True:
        raise _HeavyProjectInfrastructureError(
            "Media Pool full-request preflight changed staged media state"
        )
    payload["passed"] = True
    _write_json(evidence_path, payload)
    return MappingProxyType(payload)


def _finish_media_pool_full_request_preflight_evidence(
    payload: dict[str, Any],
    *,
    evidence_path: Path,
    runtime: ScenarioRuntime,
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
) -> None:
    payload["project_digest_after"] = _project_document_digest(
        runtime.sandbox.sandbox_path
    )
    payload["read_state_verification"] = _json_value(
        verify_media_pool_read_unchanged(staged, oracle)
    )
    _write_json(evidence_path, payload)


def _media_pool_case03_integer_upper_args(
    oracle: SealedMediaPoolOracle,
) -> tuple[Mapping[str, Any], int]:
    args = _json_value(oracle.request.args)
    filters = args.get("filters") if isinstance(args, dict) else None
    if not isinstance(filters, list):
        raise _HeavyProjectInfrastructureError(
            "case 03 Media Pool request has no filter array"
        )
    duration_field = oracle.request.binding.exact("duration")
    candidates = [
        index
        for index, item in enumerate(filters)
        if isinstance(item, dict)
        and item.get("type") == "field"
        and item.get("field") == duration_field
        and item.get("operator") == "lessThanOrEqual"
    ]
    if len(candidates) != 1:
        raise _HeavyProjectInfrastructureError(
            "case 03 Media Pool request does not have one exact duration upper filter"
        )
    index = candidates[0]
    value = filters[index].get("value")
    if type(value) is not float or value != 8.0:
        raise _HeavyProjectInfrastructureError(
            "case 03 Media Pool duration upper filter drifted from canonical 8.0"
        )
    filters[index]["value"] = 8
    return MappingProxyType(args), index


def _media_pool_request_identity(
    args: Mapping[str, Any],
    options: Mapping[str, Any],
    *,
    post_filter: Mapping[str, Any] | None = None,
    duration_field: str,
) -> Mapping[str, Any]:
    plain_args = _json_value(args)
    plain_options = _json_value(options)
    duration_upper: dict[str, Any] | None = None
    filters = plain_args.get("filters") if isinstance(plain_args, dict) else None
    if isinstance(filters, list):
        for index, item in enumerate(filters):
            if (
                isinstance(item, dict)
                and item.get("type") == "field"
                and item.get("field") == duration_field
                and item.get("operator") == "lessThanOrEqual"
            ):
                value = item.get("value")
                duration_upper = {
                    "filter_index": index,
                    "value": value,
                    "json_number_kind": (
                        "integer"
                        if type(value) is int
                        else "number"
                        if type(value) is float
                        else type(value).__name__
                    ),
                }
                break
    return MappingProxyType(
        {
            "request_sha256": _json_sha256(
                {
                    "args": plain_args,
                    "options": plain_options,
                    "post_filter": _json_value(post_filter),
                }
            ),
            "args_sha256": _json_sha256(plain_args),
            "options_sha256": _json_sha256(plain_options),
            "post_filter": _json_value(post_filter),
            "duration_upper": duration_upper,
        }
    )


def _media_pool_result_identity(result: Mapping[str, Any]) -> Mapping[str, Any]:
    encoded = _canonical_json_bytes(result)
    raw_rows = result.get("return")
    rows = raw_rows if isinstance(raw_rows, (list, tuple)) else None
    file_ids: list[str] = []
    valid_file_id_count = 0
    if rows is not None:
        for row in rows:
            file_id = row.get("FileId") if isinstance(row, Mapping) else None
            if isinstance(file_id, str):
                valid_file_id_count += 1
                if len(file_ids) < _MEDIA_POOL_PREFLIGHT_FILE_ID_LIMIT:
                    file_ids.append(file_id)
    return MappingProxyType(
        {
            "result_sha256": hashlib.sha256(encoded).hexdigest(),
            "result_size_bytes": len(encoded),
            "return_is_array": rows is not None,
            "row_count": len(rows) if rows is not None else None,
            "file_ids": sorted(file_ids),
            "file_ids_complete": (
                rows is not None
                and valid_file_id_count == len(rows)
                and len(rows) <= _MEDIA_POOL_PREFLIGHT_FILE_ID_LIMIT
            ),
        }
    )


def _read_user_database_ids(direct: OwnedDirectWaapiCall) -> tuple[str, ...]:
    result = direct(
        "ak.wwise.core.object.get",
        {
            "from": {"path": [USER_DATABASES_PATH]},
            "transform": [{"select": ["children"]}],
        },
        {"return": ["id", "name", "type", "path"]},
    )
    if not isinstance(result, Mapping) or not isinstance(result.get("return"), list):
        raise HeavyProjectRunnerError("User Databases inventory is malformed")
    ids: list[str] = []
    for row in result["return"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
            raise HeavyProjectRunnerError("User Databases child has no GUID")
        ids.append(str(row["id"]).upper())
    if len(ids) != len(set(ids)):
        raise HeavyProjectRunnerError("User Databases inventory contains duplicate GUIDs")
    return tuple(sorted(ids))


def _exact_wwise_build(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise HeavyProjectRunnerError("Wwise readiness proof is not an object")
    version = value.get("version")
    if not isinstance(version, Mapping):
        raise HeavyProjectRunnerError("Wwise readiness proof has no version object")
    fields = tuple(version.get(key) for key in ("year", "major", "minor", "build"))
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in fields):
        raise HeavyProjectRunnerError("Wwise readiness version tuple is incomplete")
    return ".".join(str(item) for item in fields)


def _final_response_has_complete_build_identity(
    response: str,
    *,
    expected_build: str,
) -> bool:
    """Accept the exact build tuple either joined or explicitly split by label."""

    folded = response.casefold()
    expected = expected_build.casefold()
    if expected in folded:
        return True
    release, separator, build = expected.rpartition(".")
    if not separator or not release or not build.isdigit():
        return False
    line_pattern = re.compile(
        rf"(?im)^[^\n]*\bwwise\b[^\n]{{0,96}}"
        rf"(?<![0-9.])v?{re.escape(release)}(?![0-9.])"
        rf"[^\n]{{0,48}}(?:build|构建)\s*[:：#]?\s*"
        rf"{re.escape(build)}(?!\d)[^\n]*$"
    )
    return any(
        not any(token in match.group(0) for token in ("not ", "不是", "并非", "wrong"))
        for match in line_pattern.finditer(folded)
    )


def _status_project_identity(
    project_path: Path,
    *,
    version: str,
) -> dict[str, str]:
    path = Path(project_path).resolve(strict=True)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise HeavyProjectRunnerError(
            "sandbox project identity document is unreadable"
        ) from exc
    project = root.find("./ProjectInfo/Project")
    if project is None:
        raise HeavyProjectRunnerError("sandbox project identity is missing")
    name = project.get("Name")
    project_id = project.get("ID")
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(project_id, str)
        or re.fullmatch(
            r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}",
            project_id,
        )
        is None
    ):
        raise HeavyProjectRunnerError("sandbox project identity is invalid")
    return {
        "id": project_id.upper(),
        "name": name,
        "type": "Project",
        "path": "\\" if version == "2021.1" else path.name,
    }


def _agent_result_mapping(
    payload: Mapping[str, Any],
    *,
    context: str,
) -> Mapping[str, Any]:
    value = payload.get("agent_result")
    if not isinstance(value, Mapping):
        raise HeavyProjectRunnerError(f"{context} has no exact agent_result object")
    return MappingProxyType(dict(value))


def _project_document_digest(root: Path) -> str:
    directory = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    count = 0
    for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
        if path.is_symlink():
            raise HeavyProjectRunnerError(
                f"project document tree contains a symlink: {path}"
            )
        if not path.is_file() or path.suffix.casefold() not in {".wproj", ".wwu"}:
            continue
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(relative + b"\0" + hashlib.sha256(data).digest())
        count += 1
    if count == 0:
        raise HeavyProjectRunnerError("project document tree contains no Wwise documents")
    return digest.hexdigest()


def _media_final_response_failures(
    oracle: SealedMediaPoolOracle,
    staged: StagedMediaPoolCase,
    text: str,
) -> tuple[str, ...]:
    folded = text.casefold()
    failures: list[str] = []
    positions: dict[str, int] = {}
    for key in oracle.expected_keys:
        filenames = _media_response_filenames(oracle, staged, key)
        filename = filenames[-1]
        position = _first_media_filename_position(folded, filenames)
        if position < 0:
            failures.append(f"final response omits expected Media Pool file {filename}")
        else:
            positions[key] = position
    if (
        len(positions) == len(oracle.expected_keys)
        and media_answer_requires_order(oracle.scenario_id)
    ):
        observed_order = tuple(sorted(positions, key=positions.__getitem__))
        if observed_order != oracle.semantic_answer.ordered_keys:
            failures.append(
                "final response Media Pool order differs from the reviewed business order"
            )
    if oracle.scenario_id != MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID:
        for key in oracle.semantic_answer.excluded_keys:
            filenames = _media_response_filenames(oracle, staged, key)
            filename = filenames[-1]
            if _first_media_filename_position(folded, filenames) >= 0:
                failures.append(f"final response includes excluded {filename}")
    if oracle.scenario_id == MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID:
        report_rows = {
            row.key: MediaReportRowExpectation(
                key=row.key,
                filenames=_media_response_filenames(oracle, staged, row.key),
                database=str(row.db.get("name", "")),
                path=row.path,
            )
            for row in oracle.rows
        }
        failures.extend(
            media_grouped_report_failures(
                text,
                expected_groups=oracle.semantic_answer.expected_groups,
                rows=report_rows,
                excluded_keys=oracle.semantic_answer.excluded_keys,
            )
        )
    else:
        for group, keys in oracle.semantic_answer.expected_groups.items():
            if group.casefold() not in folded:
                failures.append(f"final response omits duplicate group {group}")
            for key in keys:
                filenames = _media_response_filenames(oracle, staged, key)
                filename = filenames[-1]
                if _first_media_filename_position(folded, filenames) < 0:
                    failures.append(f"duplicate group {group} omits {filename}")
    for key in oracle.semantic_answer.referenced_keys:
        filenames = _media_response_filenames(oracle, staged, key)
        filename = filenames[-1]
        if not _near_classification(folded, filenames, referenced=True):
            failures.append(f"final response does not classify {filename} as referenced")
    for key in oracle.semantic_answer.unreferenced_keys:
        filenames = _media_response_filenames(oracle, staged, key)
        filename = filenames[-1]
        if not _near_classification(folded, filenames, referenced=False):
            failures.append(f"final response does not classify {filename} as unreferenced")
    return tuple(failures)


def _media_response_filenames(
    oracle: SealedMediaPoolOracle,
    staged: StagedMediaPoolCase,
    key: str,
) -> tuple[str, ...]:
    field = oracle.request.binding.exact("name")
    live_filename = oracle.row(key).values[field]
    full_filename = staged.staged_asset(key).indexed_host_path.name
    if not isinstance(live_filename, str) or not live_filename:
        raise HeavyProjectRunnerError(
            f"sealed Media Pool row {key} has no live Filename value"
        )
    return tuple(
        dict.fromkeys((live_filename.casefold(), full_filename.casefold()))
    )


def _first_media_filename_position(text: str, filenames: Sequence[str]) -> int:
    positions = tuple(
        position
        for filename in filenames
        if (position := text.find(filename)) >= 0
    )
    return min(positions, default=-1)


def _near_classification(
    text: str,
    filenames: Sequence[str],
    *,
    referenced: bool,
) -> bool:
    return media_near_classification(
        text,
        filenames,
        referenced=referenced,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_requires_custom_database(scenario: OnlineScenario) -> bool:
    spec = scenario.fixture.get("asset_spec")
    if not isinstance(spec, Mapping):
        return False
    databases = spec.get("databases")
    return isinstance(databases, list) and any(
        isinstance(row, Mapping)
        and row.get("path") != r"\Databases\Project Originals"
        for row in databases
    )


def _bind_compound_import_metadata(
    materialized: MaterializedImportCase,
    *,
    version: str,
    direct: OwnedDirectWaapiCall,
    reference_targets: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[MaterializedImportCase, Mapping[str, Any] | None]:
    """Close one staged compound import with bounded live Sound metadata.

    This runner-owned read occurs before Codex starts so the broker can seal
    the exact request it will permit.  The evaluated agent must still perform
    its own single packaged ``metadata discover`` step; the compound protocol
    binds every dynamic request token to that visible result.
    """

    if not materialized.requires_metadata_binding:
        return materialized, None
    queries = tuple(materialized.metadata_queries)
    if not 1 <= len(queries) <= 8:
        raise HeavyProjectRunnerError(
            "compound import has no bounded metadata query set"
        )
    result = discover_metadata(
        read_call=direct,
        queries=queries,
        object_type="Sound",
        limit=MAX_METADATA_DISCOVERY_LIMIT,
    ).as_dict()
    if result.get("scope", {}).get("resolved", {}).get("name") != "Sound":
        raise HeavyProjectRunnerError(
            "compound import metadata did not resolve the exact live Sound type"
        )
    envelope = MappingProxyType({"agent_result": result})
    bound = bind_import_live_metadata(
        materialized,
        version=version,
        discovery_payload=envelope,
        reference_targets=reference_targets,
    )
    if (
        bound.requires_metadata_binding
        or len(bound.operation_requests)
        != bound.expected_primary_dispatch_count
    ):
        raise HeavyProjectRunnerError(
            "compound import metadata binding did not close one exact request"
        )
    return bound, MappingProxyType(result)


def _compound_object_metadata_binding(
    scenario: OnlineScenario,
    *,
    version: str,
    profile_unit_id: str | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """Parse the profile-owned live-metadata requirement for object mutation.

    Historical V3 object cases intentionally retain their original protocol.
    Compound cases carry a closed hidden marker; the typed-input profile adds
    a fixed exact unit/scenario/version map for its metadata tasks. Neither path
    can silently broaden another campaign or version.
    """

    if profile_unit_id is not None:
        reviewed = TYPED_PROFILE_OBJECT_METADATA_UNITS.get(profile_unit_id)
        if reviewed is None or (
            scenario.id,
            scenario.api,
            version,
        ) != reviewed[:3]:
            raise HeavyProjectRunnerError(
                "typed-input object metadata unit is outside its reviewed lane"
            )
        return (
            get_codex_version_layout_v3(version).reflected_type("ActorMixer"),
            reviewed[3],
            reviewed[4],
        )

    asset_spec = scenario.fixture.get("asset_spec")
    if not isinstance(asset_spec, Mapping):
        return None
    value = asset_spec.get("metadata_binding")
    if value is None:
        return None
    if (
        scenario.id
        not in {
            "OBJ22-F-CREATE-03",
            "OBJ22-F-SET-01",
            "OBJ22-F-SET-02",
        }
        or scenario.api
        not in {
            "ak.wwise.core.object.create",
            "ak.wwise.core.object.set",
        }
        or not isinstance(value, Mapping)
        or set(value) != {"contract", "queries", "required_tokens"}
        or value.get("contract") != "waapi-skill.compound-object-metadata/v1"
    ):
        raise HeavyProjectRunnerError(
            "compound object metadata binding is outside the reviewed profile"
        )
    queries_value = value.get("queries")
    tokens_value = value.get("required_tokens")
    queries = (
        tuple(queries_value)
        if isinstance(queries_value, list)
        else ()
    )
    tokens = (
        tuple(tokens_value)
        if isinstance(tokens_value, list)
        else ()
    )
    if (
        queries != ("volume",)
        or tokens != ("Volume",)
        or any(not isinstance(item, str) for item in (*queries, *tokens))
    ):
        raise HeavyProjectRunnerError(
            "compound object metadata binding differs from the reviewed Volume lookup"
        )
    object_type = get_codex_version_layout_v3(version).reflected_type(
        "ActorMixer"
    )
    return object_type, queries, tokens


def _build_compound_object_metadata_protocol(
    scenario: OnlineScenario,
    *,
    recipe: ObjectHeavyRecipe,
    direct: OwnedDirectWaapiCall,
    version: str,
    profile_unit_id: str | None = None,
) -> V3GatewayProtocol | None:
    """Seal one object mutation behind an agent-visible live metadata read."""

    binding = _compound_object_metadata_binding(
        scenario,
        version=version,
        profile_unit_id=profile_unit_id,
    )
    if binding is None:
        return None
    if not isinstance(recipe.request, OperationRequestSpec):
        raise HeavyProjectRunnerError(
            "compound object metadata binding requires one operation request"
        )
    object_type, queries, tokens = binding
    trusted_result = discover_metadata(
        read_call=direct,
        queries=queries,
        object_type=object_type,
        limit=MAX_METADATA_DISCOVERY_LIMIT,
    ).as_dict()
    projection = project_required_metadata_tokens(
        trusted_result,
        object_type=object_type,
        required_tokens=tokens,
    )
    return build_metadata_transaction_protocol(
        (recipe.request.as_dict(version=version),),
        object_type=object_type,
        metadata_queries=queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence=(
            "object_set_v1"
            if recipe.request.operation == "object.set"
            else "wire_exact"
        ),
        schema_first=True,
    )


_INTEGRATION_V1_WORKFLOW_IDS = frozenset(
    {
        "interactive_weather_build",
        "alarm_diagnose_and_repair",
        "harbor_soundbank_release",
    }
)
_INTEGRATION_V2_WORKFLOW_IDS = frozenset(
    {
        "rifle_safe_reimport",
        "footsteps_snow_assignment_maintenance",
        "weapons_query_guided_batch_cleanup",
    }
)
_INTEGRATION_WORKFLOW_IDS = frozenset(
    {*_INTEGRATION_V1_WORKFLOW_IDS, *_INTEGRATION_V2_WORKFLOW_IDS}
)
_INTEGRATION_QUERY_FIRST_WORKFLOW_IDS = frozenset(
    {"alarm_diagnose_and_repair", "weapons_query_guided_batch_cleanup"}
)
_ALARM_TURN_REFERENCE_SCHEDULE = (
    ("references/waapi-query.md",),
    ("references/waapi-operate.md",),
    (),
)


def _integration_workflow_id(scenario: Any) -> str | None:
    """Return a reviewed integration identity without matching legacy cases."""

    value = getattr(scenario, "scenario_family", None)
    if value in _INTEGRATION_WORKFLOW_IDS:
        return str(value)
    value = getattr(scenario, "workflow_id", None)
    if value in _INTEGRATION_WORKFLOW_IDS:
        return str(value)
    return None


def _prepare_integration_workflow_case(
    scenario: Any,
    *,
    runtime: ScenarioRuntime,
    direct: OwnedDirectWaapiCall,
    unit: Any | None,
) -> _PreparedCase:
    """Adapt one reviewed integration runtime to the existing project runner."""

    workflow_id = _integration_workflow_id(scenario)
    workflow = getattr(unit, "workflow", None)
    if (
        workflow_id is None
        or unit is None
        or getattr(workflow, "id", None) != workflow_id
        or getattr(unit, "scenario", None) is not scenario
        or getattr(unit, "version", None) != runtime.version
    ):
        raise HeavyProjectRunnerError(
            "integration workflow unit, scenario, and runtime are not exactly bound"
        )
    if workflow_id == "interactive_weather_build":
        from tests.semantic.support.codex_integration_weather_runtime_v1 import (
            prepare_weather_workflow,
        )

        prepared = prepare_weather_workflow(
            scenario,
            version=runtime.version,
            scenario_root=runtime.scenario_root,
            owned_root=runtime.owned_root,
            sandbox_project_root=runtime.sandbox.sandbox_path,
            direct=direct,
        )
        typed_sections = prepared.typed_sections
        prompt = prepared.prompt
        cleanup = prepared.cleanup_success
        verify_turn = prepared.verify_turn
    elif workflow_id == "alarm_diagnose_and_repair":
        from tests.semantic.support.codex_integration_alarm_runtime_v1 import (
            prepare_alarm_integration_runtime,
        )

        prepared = prepare_alarm_integration_runtime(
            workflow,
            scenario,
            version=runtime.version,
            paths=runtime,
            direct_call=direct,
        )
        prompt = scenario.render_prompt(prepared.visible_values)
        cleanup = prepared.cleanup
        def verify_alarm_turn(turn_index: int, result: CodexRunResult) -> Any:
            if turn_index in {1, 2}:
                return prepared.verify_turn(turn_index, result)
            if turn_index == 3:
                return prepared.verify_final(None, result)
            raise HeavyProjectRunnerError(
                f"Alarm workflow received unexpected turn {turn_index}"
            )

        verify_turn = verify_alarm_turn
        typed_sections = _compile_integration_workflow_plan(
            unit=unit,
            protocol=prepared.protocol,
            visible_values=prepared.visible_values,
            oracle_requirements=prepared.oracle_requirements,
        )
    elif workflow_id == "harbor_soundbank_release":
        from tests.semantic.support.codex_integration_soundbank_runtime_v1 import (
            prepare_harbor_integration_runtime,
        )

        prepared = prepare_harbor_integration_runtime(
            workflow,
            scenario,
            version=runtime.version,
            runtime=runtime,
            direct=direct,
        )
        prompt = prepared.prompt
        cleanup = prepared.cleanup
        verify_turn = None
        typed_sections = _compile_integration_workflow_plan(
            unit=unit,
            protocol=prepared.protocol,
            visible_values=prepared.visible_values,
            oracle_requirements=prepared.oracle_requirements,
        )
    elif workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
        baseline_manifest = _integration_v2_baseline_manifest(
            unit,
            version=runtime.version,
        )
        if workflow_id == "rifle_safe_reimport":
            from tests.semantic.support.codex_integration_rifle_runtime_v2 import (
                prepare_rifle_integration_runtime,
            )

            prepared = prepare_rifle_integration_runtime(
                workflow,
                scenario,
                version=runtime.version,
                runtime=runtime,
                baseline_manifest=baseline_manifest,
                direct_call=direct,
            )
        elif workflow_id == "footsteps_snow_assignment_maintenance":
            from tests.semantic.support.codex_integration_footsteps_runtime_v2 import (
                prepare_footsteps_integration_runtime,
            )

            prepared = prepare_footsteps_integration_runtime(
                workflow,
                scenario,
                version=runtime.version,
                runtime=runtime,
                baseline_manifest=baseline_manifest,
                direct_call=direct,
            )
        else:
            from tests.semantic.support.codex_integration_weapons_runtime_v2 import (
                prepare_weapons_integration_runtime,
            )

            prepared = prepare_weapons_integration_runtime(
                workflow,
                scenario,
                version=runtime.version,
                runtime=runtime,
                baseline_manifest=baseline_manifest,
                direct_call=direct,
            )
        if (
            prepared.workflow_id != workflow_id
            or prepared.version != runtime.version
        ):
            raise HeavyProjectRunnerError(
                "integration v2 runtime returned another workflow or version"
            )
        prompt = scenario.render_prompt(prepared.visible_values)

        def cleanup_v2() -> Mapping[str, Any]:
            proof = prepared.cleanup()
            as_dict = getattr(proof, "as_dict", None)
            if not callable(as_dict):
                raise HeavyProjectRunnerError(
                    "integration v2 cleanup omitted its closed as_dict projection"
                )
            value = as_dict()
            if not isinstance(value, Mapping):
                raise HeavyProjectRunnerError(
                    "integration v2 cleanup as_dict projection is not an object"
                )
            return value

        cleanup = cleanup_v2

        def verify_v2_intermediate_turn(
            turn_index: int,
            result: CodexRunResult,
        ) -> Any | None:
            if 1 <= turn_index < int(unit.user_turn_count):
                return prepared.verify_turn(turn_index, result)
            return None

        verify_turn = verify_v2_intermediate_turn
        typed_sections = _compile_integration_workflow_plan(
            unit=unit,
            protocol=prepared.protocol,
            visible_values=prepared.visible_values,
            oracle_requirements=prepared.oracle_requirements,
            baseline_manifest_digest=baseline_manifest.digest,
        )
    else:  # pragma: no cover - workflow identity is closed above
        raise HeavyProjectRunnerError(
            f"integration workflow has no runtime: {workflow_id}"
        )

    visible_values = MappingProxyType(dict(prepared.visible_values))
    expected_dispatches = _integration_expected_dispatches(
        prepared.expected_dispatches
    )
    if not expected_dispatches:
        raise HeavyProjectRunnerError(
            "integration runtime omitted its mutation dispatch vector"
        )
    return _PreparedCase(
        prompt=prompt,
        visible_values=visible_values,
        protocol=prepared.protocol,
        required_reference=(
            "references/waapi-query.md"
            if workflow_id in _INTEGRATION_QUERY_FIRST_WORKFLOW_IDS
            else getattr(
                prepared,
                "required_reference",
                "references/waapi-operate.md",
            )
        ),
        turn_reference_schedule=(
            _ALARM_TURN_REFERENCE_SCHEDULE
            if workflow_id in _INTEGRATION_QUERY_FIRST_WORKFLOW_IDS
            else None
        ),
        snapshot=prepared.snapshot,
        verify_final=prepared.verify_final,
        typed_sections=typed_sections,
        prompt_sources=MappingProxyType(
            {"integration_visible_inputs": dict(visible_values)}
        ),
        cleanup_success=cleanup,
        observe_payload=getattr(prepared, "observe_payload", None),
        verify_turn=verify_turn,
        expected_dispatches=expected_dispatches,
    )


def _integration_v2_baseline_manifest(
    unit: Any,
    *,
    version: str,
) -> Any:
    """Require the loader-sealed manifest on every executable V2 unit."""

    manifest = getattr(unit, "baseline_manifest", None)
    path = getattr(manifest, "path", None)
    digest = getattr(manifest, "digest", None)
    objects = getattr(manifest, "objects", None)
    media = getattr(manifest, "media", None)
    if (
        manifest is None
        or getattr(manifest, "version", None) != version
        or not isinstance(path, Path)
        or not path.is_absolute()
        or not path.is_file()
        or not isinstance(digest, str)
        or not _valid_sha256_text(digest)
        or not isinstance(objects, tuple)
        or not objects
        or not isinstance(media, tuple)
        or not media
    ):
        raise HeavyProjectRunnerError(
            "integration v2 unit lacks its exact sealed baseline manifest"
        )
    return manifest


def _integration_expected_dispatches(
    values: Sequence[Any],
) -> tuple[tuple[str, int], ...]:
    aggregated: dict[str, int] = {}
    order: list[str] = []
    for value in values:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
        ):
            api, count = value
        else:
            api = getattr(value, "api", None)
            count = getattr(value, "count", None)
        if (
            not isinstance(api, str)
            or not api.startswith(("ak.wwise.", "ak.soundengine."))
            or type(count) is not int
            or count < 1
        ):
            raise HeavyProjectRunnerError(
                "integration runtime has an invalid dispatch expectation"
            )
        if api not in aggregated:
            order.append(api)
            aggregated[api] = 0
        aggregated[api] += count
    return tuple((api, aggregated[api]) for api in order)


def _compile_integration_workflow_plan(
    *,
    unit: Any,
    protocol: V3GatewayProtocol,
    visible_values: Mapping[str, Any],
    oracle_requirements: Sequence[Any],
    baseline_manifest_digest: str | None = None,
) -> WorkflowBusinessPlanSections:
    transactions = tuple(getattr(unit, "transactions", ()))
    if not transactions:
        raise HeavyProjectRunnerError(
            "integration unit has no transaction topology"
        )
    weather_phases = (
        "import_weather_assets",
        "configure_event_actions",
        "bind_rain_intensity_rtpc",
    )
    if (
        unit.workflow_id == "interactive_weather_build"
        and len(transactions) != len(weather_phases)
    ):
        raise HeavyProjectRunnerError(
            "interactive weather transaction phases differ from the reviewed workflow"
        )
    transaction_rows = tuple(
        {
            "transaction_id": f"tx{index:02d}",
            "api": transaction.api,
            "operation": transaction.operation,
            "phase": (
                weather_phases[index - 1]
                if unit.workflow_id == "interactive_weather_build"
                else f"{unit.workflow_id}.transaction_{index:02d}"
            ),
            "primary_step": f"tx{index:02d}.execute",
        }
        for index, transaction in enumerate(transactions, start=1)
    )
    transaction_by_id = {
        row["transaction_id"]: row for row in transaction_rows
    }
    kind_by_subcommand = {
        "operation-schema": "operation_schema",
        "request-array-item": "operation_compose",
        "request-map-container": "operation_compose",
        "draft-start": "operation_compose",
        "draft-apply": "operation_compose",
        "draft-check": "operation_compose_check",
        "preview": "preview",
        "preview-from-draft": "preview",
        "typed-operation": "preview",
        "transaction-show": "transaction_show",
        "confirm": "confirm",
        "execute": "execute",
        "verify": "verify",
    }
    workflow_steps: list[Mapping[str, Any]] = []
    diagnostic_evidence: list[Mapping[str, Any]] = []
    for step in protocol.steps:
        transaction_id = (
            step.name.split(".", 1)[0]
            if step.name.startswith("tx")
            else None
        )
        transaction = transaction_by_id.get(transaction_id)
        if transaction is not None and step.subcommand in kind_by_subcommand:
            workflow_steps.append(
                {
                    "name": step.name,
                    "kind": kind_by_subcommand[step.subcommand],
                    "phase": transaction["phase"],
                    "transaction_id": transaction_id,
                    "api": transaction["api"],
                }
            )
            continue
        is_diagnostic = (
            step.subcommand == "query-object"
            and not any(
                row["name"].startswith(f"{transaction_id}.")
                for row in workflow_steps
                if transaction_id is not None
            )
        )
        kind = "diagnostic" if is_diagnostic else "checkpoint"
        phase = (
            f"{unit.workflow_id}.diagnosis"
            if is_diagnostic
            else f"{unit.workflow_id}.checkpoint"
        )
        workflow_steps.append(
            {
                "name": step.name,
                "kind": kind,
                "phase": phase,
                "transaction_id": None,
                "api": (
                    "ak.wwise.core.object.get"
                    if is_diagnostic
                    else None
                ),
            }
        )
        if is_diagnostic:
            diagnostic_evidence.append(
                {
                    "evidence_id": f"{step.name}.bounded-read",
                    "step": step.name,
                    "api": "ak.wwise.core.object.get",
                    "phase": phase,
                    "expectation": {
                        "gateway_step": step.name,
                        "bounded_live_read": True,
                    },
                }
            )
    workflow_steps.append(
        {
            "name": "cleanup.success",
            "kind": "cleanup",
            "phase": (
                "cleanup"
                if unit.workflow_id == "interactive_weather_build"
                else f"{unit.workflow_id}.cleanup"
            ),
            "transaction_id": None,
            "api": None,
        }
    )
    requirements: list[Mapping[str, Any]] = []
    requirement_rows = [
        value.as_dict() if hasattr(value, "as_dict") else value
        for value in oracle_requirements
    ]
    if requirement_rows and all(
        isinstance(row, Mapping)
        and set(row) == {"transaction_id", "expectation"}
        for row in requirement_rows
    ):
        for index, row in enumerate(requirement_rows, start=1):
            assert isinstance(row, Mapping)
            transaction_id = row.get("transaction_id")
            expectation = row.get("expectation")
            if (
                transaction_id != f"tx{index:02d}"
                or not isinstance(expectation, Mapping)
                or not expectation
            ):
                raise HeavyProjectRunnerError(
                    "integration oracle requirements differ from transactions"
                )
            requirements.append(
                {
                    "transaction_id": transaction_id,
                    "expectation": dict(expectation),
                }
            )
    elif requirement_rows:
        if len(transaction_rows) != 1:
            raise HeavyProjectRunnerError(
                "workflow-level oracle requirements are ambiguous across transactions"
            )
        normalized_rows: list[dict[str, str]] = []
        for value in oracle_requirements:
            phase = getattr(value, "phase", None)
            subject = getattr(value, "subject", None)
            expectation = getattr(value, "expectation", None)
            if not all(
                isinstance(item, str) and item
                for item in (phase, subject, expectation)
            ):
                raise HeavyProjectRunnerError(
                    "integration workflow oracle requirement is invalid"
                )
            normalized_rows.append(
                {
                    "phase": phase,
                    "subject": subject,
                    "expectation": expectation,
                }
            )
        requirements.append(
            {
                "transaction_id": "tx01",
                "expectation": {"workflow_requirements": normalized_rows},
            }
        )
    if not requirements:
        requirements = [
            {
                "transaction_id": row["transaction_id"],
                "expectation": {
                    "operation": row["operation"],
                    "reviewed_delta_required": True,
                },
            }
            for row in transaction_rows
        ]
    live_bindings: dict[str, Any] = {
        "version": unit.version,
        "visible_values": dict(visible_values),
    }
    if baseline_manifest_digest is not None:
        if (
            unit.workflow_id not in _INTEGRATION_V2_WORKFLOW_IDS
            or not _valid_sha256_text(baseline_manifest_digest)
        ):
            raise HeavyProjectRunnerError(
                "integration workflow baseline-manifest binding is invalid"
            )
        live_bindings["baseline_manifest_sha256"] = baseline_manifest_digest
    elif unit.workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
        raise HeavyProjectRunnerError(
            "integration v2 workflow plan lacks its baseline-manifest digest"
        )
    return compile_workflow_business_plan_sections(
        workflow_id=unit.workflow_id,
        transactions=transaction_rows,
        workflow_steps=tuple(workflow_steps),
        diagnostic_evidence=tuple(diagnostic_evidence),
        live_bindings=live_bindings,
        transaction_expectations=tuple(requirements),
    )


def _prepare_case(
    scenario: OnlineScenario,
    *,
    runtime: ScenarioRuntime,
    direct: OwnedDirectWaapiCall,
    media_holder: Mapping[str, Any],
    project_modification_policy: str | None = None,
    unit: Any | None = None,
) -> _PreparedCase:
    if _integration_workflow_id(scenario) is not None:
        if project_modification_policy is not None:
            raise HeavyProjectRunnerError(
                "integration workflows own their reviewed confirmation topology"
            )
        return _prepare_integration_workflow_case(
            scenario,
            runtime=runtime,
            direct=direct,
            unit=unit,
        )
    if scenario.api == GET_INFO_URI:
        baseline = direct(GET_INFO_URI, {}, {})
        if not isinstance(baseline, Mapping):
            raise HeavyProjectRunnerError("getInfo baseline is not an object")
        baseline_result = _strict_plain_json(
            baseline,
            field="getInfo baseline",
        )
        expected_build = _exact_wwise_build(baseline_result)
        if not expected_build.startswith(runtime.version + "."):
            raise HeavyProjectRunnerError(
                "getInfo baseline differs from the exact scenario version"
            )
        process_id = baseline_result.get("processId")
        ready_result = getattr(runtime.lifecycle, "ready_result", None)
        ready_process_id = (
            ready_result.get("processId")
            if isinstance(ready_result, Mapping)
            else None
        )
        launch_process_id = getattr(runtime.lifecycle.process, "pid", None)
        if (
            type(process_id) is not int
            or type(ready_process_id) is not int
            or type(launch_process_id) is not int
            or process_id != ready_process_id
        ):
            raise HeavyProjectRunnerError(
                "getInfo process identity differs from lifecycle readiness proof"
            )
        status_project = _status_project_identity(
            runtime.sandbox.sandbox_project,
            version=runtime.version,
        )
        status_binding = {
            "wwise_build": expected_build,
            "process_id": process_id,
            "project": status_project,
        }
        protocol = build_direct_protocol(
            [
                ExpectedGatewayStep(
                    "host.status",
                    "status",
                ),
                ExpectedGatewayStep(
                    "host.get-info.schema",
                    "request-schema",
                    (GET_INFO_URI,),
                ),
                call_step("host.get-info", GET_INFO_URI, version=runtime.version),
            ]
        )
        project_digest = _project_document_digest(runtime.sandbox.sandbox_path)
        typed_sections = compile_direct_business_plan(
            scenario_id=scenario.id,
            api=GET_INFO_URI,
            protocol_steps=tuple(
                {"name": step.name, "subcommand": step.subcommand}
                for step in protocol.steps
            ),
            live_bindings={
                "version": runtime.version,
                "build": expected_build,
                "process_id": process_id,
                "launch_process_id": launch_process_id,
                "session_id": baseline_result.get("sessionId"),
                "result_sha256": _json_sha256(baseline_result),
                "project_digest": project_digest,
                "status": status_binding,
            },
            verification_boundary="exact_host_identity",
        )
        validate_direct_business_plan(
            typed_sections,
            scenario_id=scenario.id,
            api=GET_INFO_URI,
            protocol_steps=tuple(
                {"name": step.name, "subcommand": step.subcommand}
                for step in protocol.steps
            ),
            live_bindings={
                "version": runtime.version,
                "build": expected_build,
                "process_id": process_id,
                "launch_process_id": launch_process_id,
                "session_id": baseline_result.get("sessionId"),
                "result_sha256": _json_sha256(baseline_result),
                "project_digest": project_digest,
                "status": status_binding,
            },
            verification_boundary="exact_host_identity",
        )

        status_observed = False

        def observe_get_info(
            step: ExpectedGatewayStep,
            payload: Mapping[str, Any],
        ) -> None:
            nonlocal status_observed
            if step.name != "host.status":
                return
            wwise = payload.get("wwise")
            project = payload.get("project")
            normalized_project: dict[str, Any] | None = None
            if isinstance(project, Mapping):
                normalized_project = {
                    key: project.get(key)
                    for key in ("id", "name", "type", "path")
                }
                if runtime.version != "2021.1":
                    if normalized_project["type"] is None:
                        normalized_project["type"] = "Project"
                    try:
                        localized = Path(
                            localize_waapi_host_path(project.get("path"))
                        ).resolve(strict=True)
                    except (HostPathError, OSError, RuntimeError, TypeError):
                        localized = None
                    if localized == runtime.sandbox.sandbox_project.resolve(strict=True):
                        normalized_project["path"] = status_project["path"]
            if (
                not isinstance(wwise, Mapping)
                or _exact_wwise_build(wwise) != expected_build
                or wwise.get("processId") != process_id
                or normalized_project != status_project
            ):
                raise HeavyProjectRunnerError(
                    "Gateway status differs from the sealed Wwise/project identity"
                )
            status_observed = True

        def snapshot_get_info() -> str:
            return _project_document_digest(runtime.sandbox.sandbox_path)

        def verify_get_info(
            payload: Mapping[str, Any] | None,
            result: CodexRunResult,
        ) -> _DirectSemanticVerification:
            failures: list[str] = []
            if not status_observed:
                failures.append("Gateway status identity was not observed")
            actual: Mapping[str, Any] | None = None
            if payload is None:
                failures.append("getInfo gateway payload is missing")
            else:
                try:
                    actual = _agent_result_mapping(payload, context="host.get-info")
                except HeavyProjectRunnerError as exc:
                    failures.append(str(exc))
            if actual is not None and dict(actual) != baseline_result:
                failures.append("model getInfo result differs from the sealed host identity")
            if snapshot_get_info() != project_digest:
                failures.append("read-only getInfo task changed project documents")
            folded = result.final_response.casefold()
            if str(process_id) not in folded or not (
                _final_response_has_complete_build_identity(
                    result.final_response,
                    expected_build=expected_build,
                )
            ):
                failures.append(
                    "final response omits the exact process or complete build identity"
                )
            return _DirectSemanticVerification(
                passed=not failures,
                failures=tuple(failures),
                evidence=MappingProxyType(
                    {
                        "expected_build": expected_build,
                        "expected_process_id": process_id,
                        "expected_result_sha256": _json_sha256(baseline_result),
                        "actual_result_sha256": (
                            _json_sha256(actual) if actual is not None else None
                        ),
                    }
                ),
            )

        return _PreparedCase(
            prompt=scenario.prompt,
            visible_values=MappingProxyType({}),
            protocol=protocol,
            required_reference=None,
            turn_reference_schedule=None,
            snapshot=snapshot_get_info,
            verify_final=verify_get_info,
            observe_payload=observe_get_info,
            typed_sections=typed_sections,
        )

    if scenario.api == CORE_LUA_URI:
        script_root = runtime.asset_root / "typed-input-lua"
        script_root.mkdir(parents=True, exist_ok=False)
        script_path = script_root / "user-script.lua"
        script_bytes = (
            b'return { profile = "typed_input", count = wa_args.count }\n'
        )
        write_utf8_text_bytes(script_path, script_bytes.decode("utf-8"))
        request_payload = {
            "contract": "waapi-skill.operation-request/v1",
            "version": runtime.version,
            "operation": "lua.executeCoreFile",
            "arguments": {
                "script_file": str(script_path),
                "io_root": str(script_root),
                "source_authority": LUA_SOURCE_AUTHORITY,
                "wa_args": {"count": 3},
            },
        }
        parsed = parse_operation_request(
            request_payload,
            expected_version=runtime.version,
        )
        prepared_lua = prepare_operation(parsed, read_call=direct).as_dict()
        protocol = build_transaction_protocol([request_payload])
        project_digest = _project_document_digest(runtime.sandbox.sandbox_path)
        script_sha256 = hashlib.sha256(script_bytes).hexdigest()
        live_bindings = {
            "version": runtime.version,
            "script_file": str(script_path.resolve()),
            "script_sha256": script_sha256,
            "dispatch": prepared_lua["dispatch"],
            "project_digest": project_digest,
            "expected_return": {"profile": "typed_input", "count": 3},
        }
        plan_steps = tuple(
            {"name": step.name, "subcommand": step.subcommand}
            for step in protocol.steps
        )
        typed_sections = compile_direct_business_plan(
            scenario_id=scenario.id,
            api=CORE_LUA_URI,
            protocol_steps=plan_steps,
            live_bindings=live_bindings,
            verification_boundary="result_schema_only",
        )
        validate_direct_business_plan(
            typed_sections,
            scenario_id=scenario.id,
            api=CORE_LUA_URI,
            protocol_steps=plan_steps,
            live_bindings=live_bindings,
            verification_boundary="result_schema_only",
        )
        execution_return: dict[str, Any] = {}

        def snapshot_lua() -> tuple[str, str]:
            return (
                _project_document_digest(runtime.sandbox.sandbox_path),
                hashlib.sha256(script_path.read_bytes()).hexdigest(),
            )

        def observe_lua(
            step: ExpectedGatewayStep,
            payload: Mapping[str, Any],
        ) -> None:
            if not step.name.endswith(".execute"):
                return
            dispatch_result = payload.get("dispatch_result")
            raw_result = (
                dispatch_result.get("result")
                if isinstance(dispatch_result, Mapping)
                else None
            )
            returned = raw_result.get("return") if isinstance(raw_result, Mapping) else None
            execution_return["value"] = _json_value(returned)

        def verify_lua(
            payload: Mapping[str, Any] | None,
            _result: CodexRunResult,
        ) -> _DirectSemanticVerification:
            failures: list[str] = []
            if payload is None:
                failures.append("Lua verification payload is missing")
            else:
                verification = payload.get("verification")
                if (
                    payload.get("status") != "result_schema_checked"
                    or payload.get("result_schema_checked") is not True
                    or payload.get("verified") is not False
                    or not isinstance(verification, Mapping)
                    or verification.get("business_state_verified") is not False
                    or payload.get("verification_strength")
                    not in {"complete_reflected_schema", "partial_reflected_schema"}
                ):
                    failures.append("Lua terminal boundary overstates business verification")
            expected_return = {"profile": "typed_input", "count": 3}
            if execution_return.get("value") != expected_return:
                failures.append("Lua execution result differs from the sealed return value")
            if snapshot_lua() != (project_digest, script_sha256):
                failures.append("Lua task changed the project or user-supplied source")
            return _DirectSemanticVerification(
                passed=not failures,
                failures=tuple(failures),
                evidence=MappingProxyType(
                    {
                        "expected_return": expected_return,
                        "actual_return": execution_return.get("value"),
                        "business_state_verified": False,
                        "script_sha256": script_sha256,
                    }
                ),
            )

        def verify_lua_turn(
            turn_index: int,
            result: CodexRunResult,
        ) -> _DirectSemanticVerification | None:
            if turn_index != 2:
                return None
            failures: list[str] = []
            folded = result.final_response.casefold()
            explicit_schema_limit = (
                "验证仅限返回结果结构" in folded
                or "verification is limited to the returned result schema" in folded
                or "verification is limited to the result schema" in folded
            )
            equivalent_schema_limit = (
                (
                    "验证仅确认返回结果符合预期结构" in folded
                    or "only confirms that the returned result matches the expected structure"
                    in folded
                    or (
                        "仅确认" in folded
                        and "返回结果" in folded
                        and "结构" in folded
                    )
                    or (
                        "验证仅限" in folded
                        and "返回" in folded
                        and "结构" in folded
                    )
                    or (
                        ("仅验证" in folded or "只验证" in folded)
                        and "返回结果" in folded
                        and "结构" in folded
                    )
                )
                and (
                    "未验证" in folded
                    or "不能声称已验证" in folded
                    or (
                        "不能" in folded
                        and "声称" in folded
                        and "已验证" in folded
                    )
                    or "not verified" in folded
                    or "does not verify" in folded
                )
                and (
                    "业务副作用" in folded
                    or "业务状态" in folded
                    or "business side effects" in folded
                    or "business state" in folded
                )
            )
            bounded_boundary = explicit_schema_limit or equivalent_schema_limit
            overclaim_markers = (
                "不仅限于结果结构",
                "不限于结果结构",
                "已验证全部业务副作用",
                "验证了全部业务副作用",
                "all business side effects were verified",
                "verified all business side effects",
                "business state verified",
                "所有业务状态正确",
                "全部业务状态正确",
                "确认所有业务状态",
                "all business state is correct",
                "all business states are correct",
                "confirmed all business state",
            )
            if (
                "typed_input" not in folded
                or "3" not in folded
                or not bounded_boundary
                or any(marker in folded for marker in overclaim_markers)
            ):
                failures.append("final response omits the weak-verifier boundary")
            return _DirectSemanticVerification(
                passed=not failures,
                failures=tuple(failures),
                evidence=MappingProxyType(
                    {
                        "turn_index": turn_index,
                        "weak_boundary_reported": not failures,
                    }
                ),
            )

        return _PreparedCase(
            prompt=scenario.prompt.format_map(
                {"script_file": str(script_path), "io_root": str(script_root)}
            ),
            visible_values=MappingProxyType(
                {"script_file": str(script_path), "io_root": str(script_root)}
            ),
            protocol=protocol,
            required_reference="references/waapi-operate.md",
            snapshot=snapshot_lua,
            verify_final=verify_lua,
            verify_turn=verify_lua_turn,
            observe_payload=observe_lua,
            typed_sections=typed_sections,
        )
    if scenario.api in OBJECT_APIS:
        unit_id = (
            unit.unit_id
            if isinstance(getattr(unit, "unit_id", None), str)
            else None
        )
        metadata_profile_unit_id = (
            unit_id
            if unit_id in TYPED_PROFILE_OBJECT_METADATA_UNITS
            else None
        )
        recipe = build_object_heavy_v3_recipe(
            scenario.id,
            version=runtime.version,
        )
        if unit_id == "TYP21-DEDICATED-OBJECT-CREATE":
            recipe = typed_input_merge_recipe(recipe, unit_id=unit_id)
        elif unit_id == TYPED_PROFILE_RENAME_UNIT_ID:
            recipe = typed_input_rename_recipe(recipe, unit_id=unit_id)
        if recipe.version != runtime.version:
            raise HeavyProjectRunnerError(
                "object recipe version differs from the active lifecycle"
            )
        object_runtime = PreparedObjectRuntime(
            scenario=scenario,
            recipe=recipe,
            backend=ClosedDirectObjectBackend(direct),
            asset_root=runtime.asset_root,
        ).prepare()
        before = object_runtime.before
        if before is None:
            raise HeavyProjectRunnerError(
                "object runtime did not retain its sealed before snapshot"
            )
        if unit_id == TYPED_PROFILE_RENAME_UNIT_ID:
            protocol = object_runtime.gateway_protocol()
            protocol = build_object_merge_query_protocol(
                scenario,
                recipe,
                base_protocol=protocol,
                profile_unit_id=unit_id,
            )
        else:
            protocol = _build_compound_object_metadata_protocol(
                scenario,
                recipe=recipe,
                direct=direct,
                version=runtime.version,
                profile_unit_id=metadata_profile_unit_id,
            )
            if protocol is None:
                protocol = build_object_merge_query_protocol(
                    scenario,
                    recipe,
                )
            if protocol is None:
                protocol = object_runtime.gateway_protocol()
        if project_modification_policy is not None:
            if _compound_object_metadata_binding(
                scenario,
                version=runtime.version,
                profile_unit_id=metadata_profile_unit_id,
            ) is not None:
                raise HeavyProjectRunnerError(
                    "compound object metadata cases do not run policy probes"
                )
            protocol = build_modification_policy_protocol(
                protocol,
                policy=project_modification_policy,
            )
        object_input_files = {
            item.key: (
                runtime.asset_root / "object-query-audio" / f"{item.key}.wav"
            )
            for item in recipe.fixture.objects
            if item.object_type == "Sound" and item.source_language is not None
        }
        input_file_manifest = seal_object_input_file_manifest(object_input_files)
        business_plan_profile_unit_id = (
            unit_id
            if unit_id == TYPED_PROFILE_RENAME_UNIT_ID
            else metadata_profile_unit_id
        )
        typed_sections = compile_object_business_plan(
            scenario,
            recipe,
            protocol,
            before,
            input_file_manifest,
            profile_unit_id=business_plan_profile_unit_id,
        )
        validate_object_business_plan(
            typed_sections,
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
            before=before,
            input_file_manifest=input_file_manifest,
            verify_files=True,
            profile_unit_id=business_plan_profile_unit_id,
        )

        def verify(payload: Mapping[str, Any] | None, result: CodexRunResult) -> Any:
            if scenario.api == "ak.wwise.core.object.get":
                if payload is None:
                    raise HeavyProjectRunnerError("object query payload is missing")
                return object_runtime.verify_query_result(
                    payload,
                    final_response=result.final_response,
                )
            return object_runtime.verify_after_execution()

        return _PreparedCase(
            prompt=object_runtime.render_prompt(),
            protocol=protocol,
            required_reference=(
                "references/waapi-query.md"
                if scenario.api == "ak.wwise.core.object.get"
                else "references/waapi-operate.md"
            ),
            snapshot=object_runtime.snapshot,
            verify_final=verify,
            verify_policy_read_only=(
                object_runtime.verify_policy_read_only_unchanged
                if project_modification_policy == "read_only"
                else None
            ),
            typed_sections=typed_sections,
            visible_values=MappingProxyType({}),
        )

    if scenario.api in IMPORT_APIS:
        materialized = materialize_import_case(
            scenario,
            version=runtime.version,
            asset_root=runtime.asset_root / "import-case",
        )
        import_backend = ClosedDirectWaapiBackend(
            direct,
            version=runtime.version,
        )
        reference_fixtures = None
        metadata_discovery = None
        try:
            if materialized.requires_metadata_binding:
                reference_fixtures = prepare_import_reference_fixtures(
                    scenario,
                    materialized,
                    version=runtime.version,
                    backend=import_backend,
                )
            materialized, metadata_discovery = _bind_compound_import_metadata(
                materialized,
                version=runtime.version,
                direct=direct,
                reference_targets=(
                    reference_fixtures.request_reference_targets
                    if reference_fixtures is not None
                    else None
                ),
            )
        except Exception as setup_error:
            if reference_fixtures is not None and not reference_fixtures.adopted:
                try:
                    reference_fixtures.cleanup_emergency()
                except Exception as cleanup_error:
                    raise HeavyProjectRunnerError(
                        "compound import setup failed and reference-fixture "
                        f"cleanup also failed: {cleanup_error}"
                    ) from setup_error
            raise
        import_runtime = prepare_import_runtime(
            scenario,
            materialized,
            sandbox_project=runtime.sandbox.sandbox_project,
            backend=import_backend,
            reference_fixtures=reference_fixtures,
        )
        refusal_code = _REFUSAL_CODES.get(scenario.id)
        if metadata_discovery is not None:
            if refusal_code is not None:
                raise HeavyProjectRunnerError(
                    "compound import metadata cases cannot be preview refusals"
                )
            tokens = bound_import_metadata_tokens(materialized)
            projection = project_required_metadata_tokens(
                metadata_discovery,
                object_type="Sound",
                required_tokens=tokens,
            )
            protocol = build_metadata_transaction_protocol(
                materialized.operation_requests,
                object_type="Sound",
                metadata_queries=materialized.metadata_queries,
                required_tokens=tokens,
                expected_required_token_projection=projection,
                equivalence=(
                    "audio_import_v1"
                    if scenario.api == "ak.wwise.core.audio.import"
                    else "audio_import_tab_v1"
                ),
            )
        else:
            protocol = (
                build_audio_import_composer_protocol(
                    materialized.operation_requests[0]
                )
                if scenario.api == "ak.wwise.core.audio.import"
                else build_transaction_protocol(
                    materialized.operation_requests,
                    refusal=(
                        StructuredRefusal(refusal_code) if refusal_code else None
                    ),
                )
            )
        before = import_runtime.hidden_before
        if before is None:
            raise HeavyProjectRunnerError(
                "import runtime did not retain its sealed before snapshot"
            )
        typed_sections = compile_import_business_plan(
            scenario,
            materialized,
            import_runtime.plan,
            before,
            protocol,
        )
        validate_import_business_plan(
            typed_sections,
            scenario,
            materialized,
            import_runtime.plan,
            before,
            protocol,
            verify_files=True,
        )

        def verify(_payload: Mapping[str, Any] | None, _result: CodexRunResult) -> Any:
            return import_runtime.verify_after_execution()

        def verify_refusal(_payload: Mapping[str, Any]) -> Any:
            return import_runtime.verify_zero_dispatch_unchanged()

        import_prompt_sources: Mapping[str, Any] = MappingProxyType({})
        if (
            metadata_discovery is not None
            and scenario.api == "ak.wwise.core.audio.import"
        ):
            try:
                visible_rows = json.loads(
                    materialized.visible_values["import_rows"]
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise HeavyProjectRunnerError(
                    "compound import visible rows are not canonical JSON"
                ) from exc
            if not isinstance(visible_rows, list) or not visible_rows:
                raise HeavyProjectRunnerError(
                    "compound import visible rows must be a non-empty array"
                )
            import_prompt_sources = MappingProxyType(
                {
                    "compound_import_visible_rows": visible_rows,
                }
            )

        return _PreparedCase(
            prompt=import_runtime.render_prompt(),
            protocol=protocol,
            required_reference="references/waapi-operate.md",
            snapshot=import_runtime.snapshot,
            verify_final=verify,
            typed_sections=typed_sections,
            verify_refusal=verify_refusal if refusal_code else None,
            cleanup_success=import_runtime.cleanup_success,
            visible_values=materialized.visible_values,
            prompt_sources=import_prompt_sources,
        )

    if scenario.api == AUDIO_CONVERT_URI:
        plan = build_audio_conversion_plan(
            scenario,
            sandbox_project=runtime.sandbox.sandbox_project,
            sandbox_root=runtime.sandbox.sandbox_path,
            asset_root=runtime.asset_root,
            io_root=runtime.io_root,
        )
        audio_runtime = PreparedAudioConversionRuntime(
            scenario=scenario,
            plan=plan,
            backend=ClosedAudioConversionBackend(direct),
        ).prepare()
        before = audio_runtime.before
        if before is None:
            raise HeavyProjectRunnerError(
                "audio conversion runtime did not retain its sealed before snapshot"
            )
        protocol = audio_runtime.gateway_protocol()
        typed_sections = compile_audio_conversion_business_plan(
            plan,
            before,
            protocol,
            reviewed_scenario_fixture=scenario.fixture,
        )
        validate_audio_conversion_business_plan(
            typed_sections,
            plan,
            before,
            protocol,
            reviewed_scenario_fixture=scenario.fixture,
            verify_files=True,
        )

        def verify_audio_preview(_payload: Mapping[str, Any]) -> Any:
            return audio_runtime.verify_preview_unchanged()

        def verify_audio(
            payload: Mapping[str, Any] | None,
            _result: CodexRunResult,
        ) -> Any:
            if payload is None:
                raise HeavyProjectRunnerError(
                    "audio.convert gateway verify payload is missing"
                )
            return audio_runtime.verify_after_execution(verify_payload=payload)

        return _PreparedCase(
            prompt=audio_runtime.render_prompt(),
            protocol=protocol,
            required_reference="references/waapi-operate.md",
            snapshot=audio_runtime.snapshot,
            verify_preview=verify_audio_preview,
            verify_final=verify_audio,
            typed_sections=typed_sections,
            visible_values=MappingProxyType({"io_root": str(plan.io_root)}),
        )

    if scenario.api == MEDIA_POOL_GET_URI:
        staged = media_holder.get("staged")
        if not isinstance(staged, StagedMediaPoolCase):
            raise HeavyProjectRunnerError(
                "Media Pool prelaunch did not materialize the staged case"
            )
        return _prepare_media_pool_case(
            scenario,
            runtime=runtime,
            direct=direct,
            staged=staged,
            prelaunch_evidence=media_holder,
        )

    if scenario.api not in SOUNDBANK_RUNTIME_APIS:
        raise HeavyProjectRunnerError(
            f"project runner has no prepared-case branch for {scenario.api}"
        )

    soundbank_runtime = prepare_soundbank_runtime(
        scenario,
        version=runtime.version,
        sandbox_project=runtime.sandbox.sandbox_project,
        io_root=runtime.owned_root,
        asset_root=runtime.asset_root / "soundbank-case",
        backend=ClosedDirectWaapiSoundBankBackend(direct, version=runtime.version),
    )
    soundbank_materialized = soundbank_runtime.materialized
    if soundbank_materialized is None:
        raise HeavyProjectRunnerError(
            "SoundBank runtime did not retain its sealed prompt materialization"
        )
    before = soundbank_runtime.hidden_before
    if before is None:
        raise HeavyProjectRunnerError(
            "SoundBank runtime did not retain its sealed before snapshot"
        )
    if scenario.api == SOUNDBANK_TOPIC:
        topic = soundbank_runtime.topic_plan
        if topic is None:
            raise HeavyProjectRunnerError("SoundBank topic scenario has no topic plan")
        step_name = "soundbank.generated.wait"
        protocol = build_direct_protocol(
            [
                topic_schema_step("soundbank.generated.schema", topic.topic),
                wait_topic_step(
                    step_name,
                    topic.topic,
                    version=runtime.version,
                    event_count=topic.event_count,
                    match=topic.match,
                    options=topic.options,
                    timeout_seconds=120.0,
                    schema_step_name="soundbank.generated.schema",
                )
            ]
        )
        typed_sections = compile_soundbank_business_plan(
            soundbank_materialized,
            before,
            protocol,
        )
        validate_soundbank_business_plan(
            typed_sections,
            soundbank_materialized,
            before,
            protocol,
            verify_files=True,
        )

        def verify_topic(payload: Mapping[str, Any] | None, _result: CodexRunResult) -> Any:
            if payload is None:
                raise HeavyProjectRunnerError("SoundBank topic payload is missing")
            values = payload.get("events")
            if not isinstance(values, list):
                event = payload.get("event")
                values = [event] if isinstance(event, Mapping) else []
            topic_verification, artifacts = soundbank_runtime.verify_topic(values)
            return {"topic": topic_verification, "artifacts": artifacts}

        return _PreparedCase(
            prompt=soundbank_runtime.render_prompt(),
            protocol=protocol,
            required_reference="references/waapi-query.md",
            snapshot=soundbank_runtime.snapshot,
            verify_final=verify_topic,
            typed_sections=typed_sections,
            cleanup_success=soundbank_runtime.cleanup_success,
            topic_publishers=tuple(
                item.operation_request for item in topic.publishers
            ),
            topic_payload_step=step_name,
            visible_values=soundbank_materialized.visible_values,
            prompt_sources=soundbank_materialized.prompt_sources,
        )

    refusal_code = _REFUSAL_CODES.get(scenario.id)
    protocol = build_transaction_protocol(
        soundbank_runtime.operation_requests,
        refusal=StructuredRefusal(refusal_code) if refusal_code else None,
    )
    typed_sections = compile_soundbank_business_plan(
        soundbank_materialized,
        before,
        protocol,
    )
    validate_soundbank_business_plan(
        typed_sections,
        soundbank_materialized,
        before,
        protocol,
        verify_files=True,
    )

    def verify_soundbank(_payload: Mapping[str, Any] | None, _result: CodexRunResult) -> Any:
        return soundbank_runtime.verify_after_execution()

    def verify_soundbank_refusal(payload: Mapping[str, Any]) -> Any:
        return soundbank_runtime.verify_zero_dispatch(payload)

    return _PreparedCase(
        prompt=soundbank_runtime.render_prompt(),
        protocol=protocol,
        required_reference="references/waapi-operate.md",
        snapshot=soundbank_runtime.snapshot,
        verify_final=verify_soundbank,
        typed_sections=typed_sections,
        verify_refusal=verify_soundbank_refusal if refusal_code else None,
        cleanup_success=soundbank_runtime.cleanup_success,
        visible_values=soundbank_materialized.visible_values,
        prompt_sources=soundbank_materialized.prompt_sources,
    )


def _prelaunch_hook(
    scenario: OnlineScenario,
    *,
    media_holder: dict[str, Any],
    version: str = "2022.1",
):
    if scenario.api == AUDIO_CONVERT_URI:
        return make_audio_conversion_prelaunch_hook(scenario)

    values = tuple(_walk_scalars(scenario.fixture))
    integration_workflow_id = _integration_workflow_id(scenario)
    if integration_workflow_id is not None:
        languages = ("SFX",)
        platforms = (
            ("Windows", "Mac")
            if integration_workflow_id == "harbor_soundbank_release"
            else ("Windows",)
        )
        return make_project_prelaunch_hook(
            ProjectPrelaunchRequest(
                scenario_id=scenario.id,
                languages=languages,
                platforms=platforms,
                auro_isolation_profile=(
                    WWISE_2025_SOUNDBANK_AURO_PROFILE
                    if (
                        version == "2025.1"
                        and integration_workflow_id
                        == "harbor_soundbank_release"
                    )
                    else None
                ),
            )
        )
    if scenario.api in MEDIA_FIXTURE_APIS:
        asset_spec = scenario.fixture.get("asset_spec")
        if not isinstance(asset_spec, Mapping):
            raise HeavyProjectRunnerError(
                "media fixture has no reviewed asset specification"
            )
        # Import and SoundBank assets intentionally use short user-facing
        # aliases such as ``Chinese`` and ``English``.  Their materializers
        # map those aliases to Wwise's canonical project languages;
        # pre-launch normalization must use the same mapping or the trusted
        # media setup can fail before the scenario is evaluated.
        canonical_media_languages = tuple(
            canonical_wwise_language(value)
            for value in _walk_scalars(asset_spec)
            if value in CANONICAL_WWISE_LANGUAGE
        )
        values = (*values, *canonical_media_languages)
    if scenario.api in OBJECT_APIS:
        # Object fixtures are defined by the closed runner-owned recipe.  Public
        # fixture prose is intentionally natural and is not an executable
        # dependency manifest, so derive every required Wwise language from the
        # same immutable recipe that _prepare_case materializes after launch.
        recipe = build_object_heavy_v3_recipe(scenario.id, version=version)
        recipe_languages = tuple(
            item.source_language
            for item in recipe.fixture.objects
            if item.source_language is not None
        )
        unknown_recipe_languages = sorted(
            set(recipe_languages) - set(_KNOWN_LANGUAGES)
        )
        if unknown_recipe_languages:
            raise HeavyProjectRunnerError(
                "object fixture recipe requires unsupported prelaunch languages: "
                f"{unknown_recipe_languages}"
            )
        values = (*values, *recipe_languages)
    languages = tuple(value for value in _KNOWN_LANGUAGES if value in values)
    platforms = tuple(value for value in _KNOWN_PLATFORMS if value in values)
    if scenario.api in OBJECT_APIS | IMPORT_APIS and "SFX" not in languages:
        languages = ("SFX", *languages)
    if not platforms:
        platforms = ("Windows",)
    normalizer = make_project_prelaunch_hook(
        ProjectPrelaunchRequest(
            scenario_id=scenario.id,
            languages=languages,
            platforms=platforms,
            auro_isolation_profile=(
                WWISE_2025_SOUNDBANK_AURO_PROFILE
                if (
                    version == "2025.1"
                    and scenario.api == "ak.wwise.core.soundbank.generate"
                )
                else None
            ),
        )
    )
    if scenario.api != MEDIA_POOL_GET_URI:
        return normalizer

    def media_hook(sandbox: Any, asset_root: Path, io_root: Path) -> None:
        if _media_requires_custom_database(scenario):
            global_state_root = _real_account_wwise_state_root()
            media_holder["real_account_state_root"] = global_state_root
            media_holder["global_user_state_before"] = fingerprint_tree(
                global_state_root
            )
            if os.name == "nt":
                native_roots = _prove_fresh_native_windows_user_state(
                    _native_windows_launch_roots(asset_root.parent),
                    owned_root=asset_root.parent,
                )
                media_holder["host_mode"] = "native_windows"
                media_holder["native_windows_roots"] = native_roots
            else:
                launch_home, wine_prefix = _prove_fresh_media_launch_home(
                    asset_root.parent / "wwise-user-home",
                    owned_root=asset_root.parent,
                )
                media_holder["host_mode"] = "macos_wine"
                media_holder["launch_home"] = launch_home
                media_holder["owned_wine_prefix_expected"] = wine_prefix
        normalizer(sandbox, asset_root, io_root)
        case = materialize_media_pool_case(
            scenario,
            asset_root=asset_root / "media-pool-case",
        )
        staged = stage_media_pool_case(
            case,
            sandbox_project=sandbox.sandbox_project,
            immutable_source_root=sandbox.source_root,
            owned_root=asset_root.parent,
        )
        media_holder["case"] = case
        media_holder["staged"] = staged

    return media_hook


def _real_account_wwise_state_root() -> Path:
    if os.name == "nt":
        raw = os.environ.get("APPDATA")
        if not isinstance(raw, str) or not raw:
            raise HeavyProjectRunnerError(
                "native Windows account has no APPDATA for Wwise state proof"
            )
        appdata = Path(raw).expanduser().resolve(strict=True)
        return (appdata / "Audiokinetic" / "Wwise").resolve(strict=False)
    real_home = Path(
        os.environ.get("HOME", str(Path.home()))
    ).expanduser().resolve(strict=True)
    return (
        real_home
        / "Library"
        / "Application Support"
        / "Audiokinetic"
        / "Wwise"
    ).resolve(strict=False)


def _native_windows_launch_roots(owned_root: Path) -> Mapping[str, Path]:
    """Return the fixed case-owned roots used only on native Windows."""

    owned = Path(owned_root).resolve(strict=False)
    return MappingProxyType(
        {
            "USERPROFILE": owned / "wwise-user-profile",
            "APPDATA": owned / "wwise-appdata",
            "LOCALAPPDATA": owned / "wwise-localappdata",
        }
    )


def _prove_fresh_native_windows_user_state(
    roots: Mapping[str, Path],
    *,
    owned_root: Path,
) -> Mapping[str, Path]:
    if set(roots) != {"USERPROFILE", "APPDATA", "LOCALAPPDATA"}:
        raise HeavyProjectRunnerError(
            "native Windows custom database user-state roots are incomplete"
        )
    owned = Path(owned_root).resolve(strict=True)
    proven: dict[str, Path] = {}
    for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        path = Path(roots[key])
        if path_is_link_or_reparse(path) or not path.is_dir():
            raise HeavyProjectRunnerError(
                f"native Windows custom database {key} is not a fresh real directory"
            )
        path = path.resolve(strict=True)
        if not path.is_relative_to(owned) or path == owned:
            raise HeavyProjectRunnerError(
                f"native Windows custom database {key} is outside case ownership"
            )
        if any(path.iterdir()):
            raise HeavyProjectRunnerError(
                f"native Windows custom database {key} is not empty before Wwise startup"
            )
        proven[key] = path
    if len(set(proven.values())) != len(proven):
        raise HeavyProjectRunnerError(
            "native Windows custom database user-state roots overlap exactly"
        )
    return MappingProxyType(proven)


def _prove_fresh_media_launch_home(
    launch_home: Path,
    *,
    owned_root: Path,
) -> tuple[Path, Path]:
    """Prove the private HOME is empty before the Wwise launcher builds Wine."""

    owned = Path(owned_root).expanduser().resolve(strict=True)
    home = Path(launch_home).expanduser()
    if home.is_symlink() or not home.is_dir():
        raise HeavyProjectRunnerError(
            "custom Media Pool launch HOME is not a fresh real directory"
        )
    home = home.resolve(strict=True)
    if not home.is_relative_to(owned) or home == owned:
        raise HeavyProjectRunnerError(
            "custom Media Pool launch HOME is outside case ownership"
        )
    if any(home.iterdir()):
        raise HeavyProjectRunnerError(
            "custom Media Pool launch HOME is not empty before Wwise startup"
        )
    wine_prefix = expected_macos_wine_prefix(home)
    if wine_prefix.is_symlink() or wine_prefix.exists():
        raise HeavyProjectRunnerError(
            f"custom Media Pool effective WINEPREFIX is not fresh: {wine_prefix}"
        )
    return home, wine_prefix


def _prove_media_global_state_unchanged(
    media_holder: Mapping[str, Any],
) -> tuple[Any, Any]:
    baseline = media_holder.get("global_user_state_before")
    if not hasattr(baseline, "root"):
        raise HeavyProjectRunnerError(
            "custom Media Pool prelaunch user-state proof is missing"
        )
    observed = fingerprint_tree(baseline.root)
    if observed != baseline:
        raise HeavyProjectRunnerError(
            "real-account Wwise user state changed during failed Media Pool setup"
        )
    return baseline, observed


def _archive_early_media_isolation_proof(
    scenario: OnlineScenario,
    media_holder: Mapping[str, Any],
    *,
    scenario_root: Path,
) -> Mapping[str, Any]:
    if scenario.api != MEDIA_POOL_GET_URI or not _media_requires_custom_database(
        scenario
    ):
        raise HeavyProjectRunnerError(
            "early Media Pool isolation proof used for a non-custom scenario"
        )
    evidence_path = (
        Path(scenario_root).resolve(strict=True)
        / "evidence"
        / "early-media-isolation.json"
    )
    baseline = media_holder.get("global_user_state_before")
    host_binding = _early_media_host_binding(media_holder)
    try:
        baseline, observed = _prove_media_global_state_unchanged(media_holder)
    except BaseException as exc:  # noqa: BLE001 - archive the failed proof too
        _write_json(
            evidence_path,
            {
                "contract": EARLY_MEDIA_ISOLATION_CONTRACT,
                "scenario_id": scenario.id,
                "real_user_state_unchanged": False,
                "global_user_state_before": _json_value(baseline),
                "error": f"{type(exc).__name__}: {exc}",
                "host_binding": host_binding,
            },
        )
        raise
    payload = {
        "contract": EARLY_MEDIA_ISOLATION_CONTRACT,
        "scenario_id": scenario.id,
        "real_user_state_unchanged": True,
        "global_user_state_before": _json_value(baseline),
        "global_user_state_after": _json_value(observed),
        "host_binding": host_binding,
    }
    _write_json(evidence_path, payload)
    return MappingProxyType(
        {
            "contract": EARLY_MEDIA_ISOLATION_CONTRACT,
            "evidence_path": str(evidence_path),
            "evidence_sha256": _sha256_file(evidence_path),
            "real_user_state_unchanged": True,
        }
    )


def _early_media_host_binding(media_holder: Mapping[str, Any]) -> Mapping[str, Any]:
    mode = media_holder.get("host_mode")
    if mode == "macos_wine":
        return MappingProxyType(
            {
                "mode": mode,
                "launch_home": str(media_holder.get("launch_home", "")),
                "owned_wine_prefix_expected": str(
                    media_holder.get("owned_wine_prefix_expected", "")
                ),
            }
        )
    if mode == "native_windows":
        roots = media_holder.get("native_windows_roots")
        if not isinstance(roots, Mapping):
            raise HeavyProjectRunnerError(
                "native Windows early Media Pool isolation roots are missing"
            )
        return MappingProxyType(
            {
                "mode": mode,
                "roots": {
                    key: str(roots.get(key, ""))
                    for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA")
                },
            }
        )
    raise HeavyProjectRunnerError("early Media Pool host mode is missing")


def _media_post_shutdown_fallback(
    scenario: OnlineScenario,
    media_holder: Mapping[str, Any],
) -> Callable[[ScenarioRuntime], None] | None:
    """Protect the real user state when Media Pool setup fails early.

    A custom-database setup error can happen before the prepared adapter exists.
    The case HOME/WINEPREFIX is retained in that situation, while this fallback
    still proves that the actual account's Wwise state never changed.
    """

    if scenario.api != MEDIA_POOL_GET_URI or not _media_requires_custom_database(
        scenario
    ):
        return None
    def prove_real_user_state_unchanged(_runtime: ScenarioRuntime) -> None:
        _prove_media_global_state_unchanged(media_holder)

    return prove_real_user_state_unchanged


def _launch_environment_overrides(
    scenario: OnlineScenario,
    *,
    scenario_root: Path,
) -> Mapping[str, str]:
    if scenario.api != MEDIA_POOL_GET_URI or not _media_requires_custom_database(
        scenario
    ):
        return MappingProxyType({})
    owned = (scenario_root / "owned").resolve(strict=False)
    if os.name == "nt":
        return MappingProxyType(
            {
                key: str(path)
                for key, path in _native_windows_launch_roots(owned).items()
            }
        )
    return MappingProxyType(
        {"HOME": str((owned / "wwise-user-home").resolve(strict=False))}
    )


def _owned_wine_prefix(
    scenario: OnlineScenario,
    *,
    launch_environment_overrides: Mapping[str, str],
) -> Path | None:
    if scenario.api != MEDIA_POOL_GET_URI or not _media_requires_custom_database(
        scenario
    ):
        if launch_environment_overrides:
            raise HeavyProjectRunnerError(
                "non-custom scenario unexpectedly has launch environment overrides"
            )
        return None
    if os.name == "nt":
        if set(launch_environment_overrides) != {
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
        }:
            raise HeavyProjectRunnerError(
                "native Windows custom Media Pool isolation roots are incomplete"
            )
        return None
    home_value = launch_environment_overrides.get("HOME")
    if not isinstance(home_value, str) or not home_value:
        raise HeavyProjectRunnerError(
            "custom Media Pool scenario has no private HOME override"
        )
    return expected_macos_wine_prefix(Path(home_value))


def _walk_scalars(value: Any) -> Sequence[str]:
    result: list[str] = []
    if isinstance(value, Mapping):
        for nested in value.values():
            result.extend(_walk_scalars(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            result.extend(_walk_scalars(nested))
    elif isinstance(value, str):
        result.append(value)
    return tuple(result)


def _validate_task_run(
    unit: HeavyScenarioUnit,
    *,
    task: V3TaskRun,
    task_root: Path,
    expected_turn_count: int,
) -> None:
    if task.scenario_id != unit.scenario.id or task.version != unit.version:
        raise _HeavyProjectInfrastructureError(
            "fresh task returned another scenario/version identity"
        )
    if Path(task.task_root).resolve(strict=True) != Path(task_root).resolve(strict=True):
        raise _HeavyProjectInfrastructureError(
            "fresh task evidence root is not bound to the scenario lifecycle"
        )
    terminal_indeterminate = bool(
        getattr(task, "terminal_indeterminate", False)
    )
    if terminal_indeterminate:
        if (
            not 1 <= len(task.turns) <= expected_turn_count
            or len(task.turn_grades) != len(task.turns)
            or not all(grade.passed for grade in task.turn_grades)
        ):
            raise _HeavyProjectInfrastructureError(
                "terminal indeterminate task has invalid completed-turn evidence"
            )
    elif (
        len(task.turns) != expected_turn_count
        or len(task.turn_grades) != expected_turn_count
    ):
        raise _HeavyProjectInfrastructureError(
            "fresh task did not return the exact planned turn cardinality"
        )
    if not task.thread_id:
        raise _HeavyProjectInfrastructureError(
            "fresh task completed without one exact thread identity"
        )
    if not task.passed and not terminal_indeterminate:
        raise _HeavyProjectSemanticError(
            "fresh task returned a non-passing broker/turn grade"
        )


def _unit_project_modification_policy(unit: Any) -> str | None:
    value = getattr(unit, "project_modification_policy", None)
    if value is None:
        return None
    if value not in {"read_only", "ask_before_changes", "allow_changes"}:
        raise _HeavyProjectInfrastructureError(
            f"unit has invalid project modification policy {value!r}"
        )
    return str(value)


def _unit_primary_dispatch_count(unit: Any) -> int:
    declared = getattr(unit, "expected_primary_dispatch_count", None)
    if declared is None:
        declared = getattr(
            getattr(unit.scenario, "primary_dispatch", None),
            "count",
            None,
        )
    if type(declared) is not int or declared < 0:
        raise _HeavyProjectInfrastructureError(
            "unit has no closed expected primary-dispatch count"
        )
    return declared


def _policy_notice_change_terms(
    scenario: OnlineScenario,
) -> tuple[str, ...]:
    """Derive concrete object names the allow-changes notice must mention."""

    recipe = build_object_heavy_v3_recipe(scenario.id)
    request = recipe.request
    if not isinstance(request, OperationRequestSpec):
        raise _HeavyProjectInfrastructureError(
            "modification-policy notice requires an object operation recipe"
        )
    arguments = request.arguments
    root_name = arguments.get("name")
    children = arguments.get("children", ())
    child_names = tuple(
        child.get("name")
        for child in children
        if isinstance(child, Mapping) and isinstance(child.get("name"), str)
    )
    if (
        not isinstance(root_name, str)
        or not root_name
        or len(child_names) < 2
    ):
        raise _HeavyProjectInfrastructureError(
            "modification-policy notice terms are unavailable"
        )
    return (root_name, *child_names[:2])


def _policy_notice_precedes_execute(
    result: CodexRunResult,
    *,
    expected_change_terms: Sequence[str],
) -> bool:
    """Require a concrete allow-changes notice after preview, before execute."""

    facts = result.command_facts
    commands = tuple(facts.gateway_attempt_commands)
    subcommands = tuple(facts.gateway_subcommands)
    if len(commands) != len(subcommands):
        return False
    preview_commands = {
        command
        for command, subcommand in zip(commands, subcommands, strict=True)
        if subcommand == "preview"
    }
    execute_commands = {
        command
        for command, subcommand in zip(commands, subcommands, strict=True)
        if subcommand == "execute"
    }
    if len(preview_commands) != 1 or len(execute_commands) != 1:
        return False
    terms = tuple(
        str(value).casefold()
        for value in expected_change_terms
        if isinstance(value, str) and value
    )
    if not terms:
        return False
    preview_completed = False
    notice_seen = False
    for event in parse_jsonl_events(result.stdout):
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        if (
            event.get("type") == "item.completed"
            and item.get("type") == "command_execution"
            and item.get("command") in preview_commands
        ):
            preview_completed = True
            continue
        if (
            preview_completed
            and event.get("type") == "item.completed"
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            folded = item["text"].casefold()
            mode_notice = (
                "allow_changes" in folded
                or (
                    any(
                        marker in item["text"]
                        for marker in ("当前模式", "修改策略", "当前策略")
                    )
                    and any(
                        marker in item["text"]
                        for marker in (
                            "允许",
                            "可以直接",
                            "授权",
                            "按当前策略执行",
                        )
                    )
                )
            )
            affirmative_action = bool(
                re.search(
                    r"(?:将|会|接下来|现在|随后).{0,24}"
                    r"(?:创建|新建|建出|执行)",
                    item["text"],
                )
                or re.search(
                    r"(?:will|going to|proceed|now|next).{0,32}"
                    r"(?:create|build|execute)",
                    folded,
                )
            )
            negated_action = bool(
                re.search(
                    r"(?:不|不会|不能|不可|不要|暂不|先不|无法).{0,12}"
                    r"(?:创建|新建|建出|执行)",
                    item["text"],
                )
                or re.search(
                    r"(?:not|cannot|can't|won't|do not|unable to).{0,24}"
                    r"(?:create|execute|proceed)",
                    folded,
                )
            )
            concrete_change = (
                affirmative_action
                and all(term in folded for term in terms)
                and not negated_action
            )
            notice_seen = notice_seen or (mode_notice and concrete_change)
            continue
        if (
            item.get("type") == "command_execution"
            and item.get("command") in execute_commands
        ):
            return preview_completed and notice_seen
    return False


def _require_policy_turn_response(
    result: CodexRunResult,
    *,
    policy: str,
    turn_index: int,
    expected_change_terms: Sequence[str],
) -> None:
    """Require the user-facing response to explain the policy outcome."""

    text = result.final_response.strip()
    folded = text.casefold()
    root_term = (
        str(expected_change_terms[0]).casefold()
        if expected_change_terms
        else ""
    )
    unchanged = any(
        marker in folded
        for marker in (
            "没有修改",
            "没有改动",
            "未修改",
                "未改动",
                "未执行",
                "未写入",
                "尚未写入",
                "未发生任何更改",
                "保持原样",
                "不会创建",
            "no change",
            "not changed",
            "not executed",
        )
    ) or bool(
        re.search(
                r"(?:尚未|还未|未).{0,8}"
                r"(?:执行|创建|新建|修改|改动|更改|变更|变化|应用|写入)",
                text,
            )
        or re.search(
            r"(?:未发生(?:任何)?|没有(?:发生)?(?:任何)?).{0,8}"
            r"(?:修改|改动|更改|变更|变化)",
            text,
        )
    )
    completion_text = re.sub(
        r"预览(?:已经|已)?(?:生成|准备完成|创建完成|完成)"
        r"(?!了?(?:层级|对象|项目))",
        "PREVIEW_READY",
        text,
    )
    completion_text = re.sub(
        r"(?:已经|已)(?:生成|准备好|创建完成|完成).{0,8}预览",
        "PREVIEW_READY",
        completion_text,
    )
    completion_folded = re.sub(
        r"preview.{0,12}(?:(?:has been|is|was)\s+)?"
        r"(?:created|completed|prepared|ready)",
        "preview ready",
        completion_text.casefold(),
    )
    contradictory_completion = bool(
        re.search(
            r"(?:已经|已)(?!确认)(?:成功地?|完成)?(?:为你)?"
            r"(?:创建|新建|建好|建出)",
            completion_text,
        )
        or re.search(
            r"(?<!确认)(?:操作|创建|新建|建好|建出).{0,8}"
            r"(?:完成|好了)(?!后|时|再)",
            completion_text,
        )
        or re.search(
            r"(?:already|has been).{0,24}(?:created|built|completed)",
            completion_folded,
        )
        or any(
            marker in completion_folded
            for marker in ("created successfully", "operation completed")
        )
    )
    if policy == "read_only":
        policy_explained = (
            "read_only" in folded
            or "只读" in text
            or (turn_index > 1 and unchanged)
        )
        request_explained = (
            (bool(root_term) and root_term in folded)
            or turn_index > 1
            or any(
                marker in folded
                for marker in (
                    "创建",
                    "对象",
                    "修改",
                    "改动",
                    "create",
                    "object",
                    "change",
                )
            )
        )
        if (
            not text
            or not unchanged
            or contradictory_completion
            or not policy_explained
            or not request_explained
        ):
            raise HeavyProjectRunnerError(
                "read_only response did not explain that the requested project "
                "change was blocked and the project remained unchanged"
            )
        return
    if policy == "ask_before_changes" and turn_index == 1:
        preview_negated = bool(
            re.search(
                r"预览.{0,8}(?:尚未|还未|未|无法|不能).{0,8}"
                r"(?:完成|生成|准备|就绪)",
                text,
            )
            or re.search(
                r"preview.{0,16}(?:not|isn't|cannot|can't|unable).{0,16}"
                r"(?:ready|complete|generated|prepared)",
                folded,
            )
        )
        preview = not preview_negated and bool(
            re.search(
                r"预览.{0,16}(?:已|已经)?"
                r"(?:生成|准备完成|准备好|就绪|创建完成|完成)",
                text,
            )
            or re.search(
                r"(?:已|已经)(?:生成|准备好|创建完成|完成).{0,16}预览",
                text,
            )
            or re.search(
                r"preview.{0,16}(?:ready|complete|generated|prepared)",
                folded,
            )
        )
        confirmation_requested = any(
            marker in folded
            for marker in (
                "请确认",
                "是否继续",
                "要我执行吗",
                "等待你的确认",
                "等你确认",
                "please confirm",
                "would you like me to proceed",
            )
            ) or bool(
                re.search(
                    r"(?:请|可以)?(?:明确)?回复.{0,12}(?:确认|同意)",
                    text,
                )
                or re.search(
                    r"(?:确认|是否|要(?:不要|我)?|可以|需要我|你希望我).{0,12}"
                    r"(?:执行|创建|继续|进行).{0,6}(?:吗|么|？|\?)",
                    text,
                )
                or re.search(
                    r"(?:please\s+)?reply.{0,24}(?:confirm|yes|proceed)",
                    folded,
            )
        )
        concrete_terms = tuple(
            str(term).casefold()
            for term in expected_change_terms
            if isinstance(term, str) and term
        )
        target_explained = bool(concrete_terms) and all(
            term in folded for term in concrete_terms
        )
        if (
            not text
            or not preview
            or not confirmation_requested
            or not unchanged
            or contradictory_completion
            or not target_explained
        ):
            raise HeavyProjectRunnerError(
                "ask_before_changes first response did not explain the concrete "
                "preview, unchanged state, and later-confirmation requirement"
            )


def _failure_status(
    exc: BaseException,
    *,
    runtime: ScenarioRuntime | None,
) -> str:
    """Separate runner/infrastructure faults from completed semantic evidence."""

    if isinstance(exc, _HeavyProjectIndeterminate):
        return "INDETERMINATE"
    if isinstance(exc, _HeavyProjectSemanticError):
        return "FAIL"
    if isinstance(
        exc,
        (
            _HeavyProjectInfrastructureError,
            ScenarioLifecycleStartError,
            CodexInfrastructureError,
            CodexHarnessError,
        ),
    ):
        return "BLOCKED"
    if not isinstance(exc, Exception) or runtime is None:
        return "BLOCKED"
    turns_root = runtime.evidence_root / "codex-task" / "turns"
    # ``run_v3_codex_task`` archives a turn grade only after a real Codex turn
    # returned and was reconciled.  Merely creating codex-task happens before
    # broker/Codex startup and is not semantic evidence.
    if turns_root.is_dir() and any(turns_root.glob("turn-*/turn-grade.json")):
        return "FAIL"
    return "BLOCKED"


def _audit_primary_dispatch(
    scenario: OnlineScenario,
    *,
    task: V3TaskRun,
    topic_payload: Mapping[str, Any] | None,
    topic_subscription_ack: Mapping[str, Any] | None = None,
    expected_count: int | None = None,
) -> Mapping[str, Any]:
    try:
        evidence_root = Path(task.broker_evidence.evidence_directory).resolve(
            strict=True
        )
    except (OSError, RuntimeError) as exc:
        raise _HeavyProjectInfrastructureError(
            f"dispatcher evidence root is unavailable: {exc}"
        ) from exc
    rows = _read_dispatch_evidence(
        evidence_root,
        topic_subscription_ack=(
            topic_subscription_ack if scenario.item_type == "topic" else None
        ),
    )
    observed_calls = sum(row.get("api") == scenario.api for row in rows)
    if scenario.item_type == "topic":
        if topic_payload is None:
            raise HeavyProjectRunnerError("topic dispatch has no payload evidence")
        events = topic_payload.get("events")
        observed_events = len(events) if isinstance(events, list) else int(topic_payload.get("event") is not None)
        if observed_calls != 1 or observed_events != scenario.primary_dispatch.count:
            raise HeavyProjectRunnerError(
                f"topic evidence differs: calls={observed_calls}, events={observed_events}, "
                f"expected_events={scenario.primary_dispatch.count}"
            )
        return MappingProxyType(
            {
                "api": scenario.api,
                "gateway_dispatch_calls": observed_calls,
                "event_count": observed_events,
            }
        )
    primary_count = (
        scenario.primary_dispatch.count
        if expected_count is None
        else expected_count
    )
    if scenario.api == GET_INFO_URI:
        versions = tuple(scenario.versions)
        if versions == ("2021.1",):
            status_project_api = "ak.wwise.core.object.get"
        elif versions in {
            ("2022.1",),
            ("2023.1",),
            ("2024.1",),
            ("2025.1",),
        }:
            status_project_api = "ak.wwise.core.getProjectInfo"
        else:
            raise HeavyProjectRunnerError(
                "getInfo dispatch audit has no exact reviewed version"
            )
        return _audit_get_info_dispatch_partition(
            task=task,
            rows=rows,
            primary_count=primary_count,
            status_project_api=status_project_api,
        )
    if observed_calls != primary_count:
        raise HeavyProjectRunnerError(
            f"primary dispatch count differs for {scenario.api}: "
            f"expected={primary_count} observed={observed_calls}"
        )
    return MappingProxyType(
        {
            "api": scenario.api,
            "dispatch_count": observed_calls,
        }
    )


def _audit_get_info_dispatch_partition(
    *,
    task: V3TaskRun,
    rows: Sequence[Mapping[str, Any]],
    primary_count: int,
    status_project_api: str,
) -> Mapping[str, Any]:
    """Separate the required status preflight from the named API result."""

    records = tuple(task.broker_evidence.records)
    if tuple(record.step_name for record in records) != (
        "host.status",
        "host.get-info.schema",
        "host.get-info",
    ):
        raise HeavyProjectRunnerError(
            "getInfo dispatch audit differs from its exact public protocol"
        )
    status_payload = records[0].payload
    result_payload = records[2].payload
    status_calls = (
        status_payload.get("calls")
        if isinstance(status_payload, Mapping)
        else None
    )
    result_call = (
        result_payload.get("call")
        if isinstance(result_payload, Mapping)
        else None
    )
    if (
        primary_count != 1
        or not isinstance(status_calls, list)
        or len(status_calls) != 2
        or not all(isinstance(row, Mapping) for row in status_calls)
        or {row.get("api") for row in status_calls}
        != {GET_INFO_URI, status_project_api}
        or not isinstance(result_call, Mapping)
        or result_call.get("api") != GET_INFO_URI
    ):
        raise HeavyProjectRunnerError(
            "getInfo status/result dispatch partition is invalid"
        )
    status_get_info = next(
        row for row in status_calls if row.get("api") == GET_INFO_URI
    )
    status_project = next(
        row
        for row in status_calls
        if row.get("api") == status_project_api
    )
    expected_bindings = (
        (GET_INFO_URI, status_get_info.get("evidence_path")),
        (status_project_api, status_project.get("evidence_path")),
        (GET_INFO_URI, result_call.get("evidence_path")),
    )
    expected_paths = tuple(path for _api, path in expected_bindings)
    if not all(isinstance(path, str) and path for path in expected_paths):
        raise HeavyProjectRunnerError(
            "getInfo dispatcher evidence paths are invalid"
        )
    observed_bindings = tuple(
        (row.get("api"), row.get("evidence_path")) for row in rows
    )
    if (
        len(set(expected_paths)) != 3
        or observed_bindings != expected_bindings
    ):
        raise HeavyProjectRunnerError(
            "getInfo dispatcher evidence is not bound to its ordered status and named result"
        )
    return MappingProxyType(
        {
            "api": GET_INFO_URI,
            "dispatch_count": 1,
            "status_preflight_dispatch_count": 1,
        }
    )


def _audit_workflow_dispatch(
    *,
    task: V3TaskRun,
    expected_dispatches: Sequence[tuple[str, int]],
) -> Mapping[str, Any]:
    """Require the exact reviewed mutation vector for one integration workflow."""

    if not expected_dispatches:
        raise _HeavyProjectInfrastructureError(
            "workflow dispatch audit has no reviewed expectations"
        )
    normalized: list[tuple[str, int]] = []
    seen: set[str] = set()
    for api, count in expected_dispatches:
        if (
            not isinstance(api, str)
            or not api.startswith(("ak.wwise.", "ak.soundengine."))
            or type(count) is not int
            or count < 1
            or api in seen
        ):
            raise _HeavyProjectInfrastructureError(
                "workflow dispatch expectations are invalid or duplicated"
            )
        seen.add(api)
        normalized.append((api, count))
    try:
        evidence_root = Path(task.broker_evidence.evidence_directory).resolve(
            strict=True
        )
    except (OSError, RuntimeError) as exc:
        raise _HeavyProjectInfrastructureError(
            f"workflow dispatcher evidence root is unavailable: {exc}"
        ) from exc
    rows = _read_dispatch_evidence(evidence_root)
    observed = {
        api: sum(row.get("api") == api for row in rows)
        for api, _count in normalized
    }
    expected = dict(normalized)
    if observed != expected:
        raise HeavyProjectRunnerError(
            "workflow mutation dispatch vector differs: "
            f"expected={expected} observed={observed}"
        )
    return MappingProxyType(
        {
            "expected": expected,
            "observed": observed,
            "total_expected_dispatches": sum(expected.values()),
        }
    )


def _read_dispatch_evidence(
    directory: Path,
    *,
    topic_subscription_ack: Mapping[str, Any] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    expected_ack_path: Path | None = None
    expected_ack_payload: Mapping[str, Any] | None = None
    expected_ack_sha256: str | None = None
    if topic_subscription_ack is not None:
        ack_path_value = topic_subscription_ack.get("ack_path")
        expected_ack_payload_value = topic_subscription_ack.get("ack_payload")
        expected_ack_sha256_value = topic_subscription_ack.get("ack_file_sha256")
        if (
            not isinstance(ack_path_value, str)
            or not isinstance(expected_ack_payload_value, Mapping)
            or not _valid_sha256_text(expected_ack_sha256_value)
        ):
            raise _HeavyProjectSemanticError(
                "topic dispatcher audit has no closed subscription ACK proof"
            )
        try:
            expected_ack_path = Path(ack_path_value).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _HeavyProjectInfrastructureError(
                f"topic subscription ACK proof path is unavailable: {exc}"
            ) from exc
        expected_ack_payload = expected_ack_payload_value
        expected_ack_sha256 = expected_ack_sha256_value
        if (
            expected_ack_path.parent != directory
            or not expected_ack_path.name.startswith("subscription-ack-")
            or not expected_ack_path.name.endswith(".json")
        ):
            raise _HeavyProjectSemanticError(
                "topic subscription ACK is outside the dispatcher evidence root"
            )

    rows: list[Mapping[str, Any]] = []
    ack_observed = False
    try:
        paths = sorted(directory.glob("*.json"))
    except (OSError, RuntimeError) as exc:
        raise _HeavyProjectInfrastructureError(
            f"dispatcher evidence directory is unreadable: {directory}: {exc}"
        ) from exc
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise _HeavyProjectInfrastructureError(
                f"dispatcher evidence must be a regular file: {path}"
            )
        try:
            raw = path.read_bytes()
        except (OSError, RuntimeError) as exc:
            raise _HeavyProjectInfrastructureError(
                f"dispatcher evidence is unreadable: {path}: {exc}"
            ) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _HeavyProjectSemanticError(
                f"dispatcher evidence is not strict UTF-8 JSON: {path}: {exc}"
            ) from exc
        try:
            resolved_path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _HeavyProjectInfrastructureError(
                f"dispatcher evidence path became unavailable: {path}: {exc}"
            ) from exc
        if expected_ack_path is not None and resolved_path == expected_ack_path:
            if (
                ack_observed
                or not isinstance(value, Mapping)
                or value != expected_ack_payload
                or value.get("contract") != SUBSCRIPTION_ACK_CONTRACT
                or hashlib.sha256(raw).hexdigest() != expected_ack_sha256
            ):
                raise _HeavyProjectSemanticError(
                    "topic subscription ACK differs from its sealed dispatcher proof"
                )
            ack_observed = True
            continue
        if (
            path.name.startswith("subscription-ack-")
            and path.name.endswith(".json")
        ) or (
            isinstance(value, Mapping)
            and value.get("contract") == SUBSCRIPTION_ACK_CONTRACT
        ):
            raise _HeavyProjectSemanticError(
                "unsealed topic subscription ACK is present in dispatcher evidence"
            )
        if not isinstance(value, Mapping) or value.get("evidence_path") != str(path):
            raise _HeavyProjectSemanticError(
                f"dispatcher evidence path binding is invalid: {path}"
            )
        if not isinstance(value.get("api"), str):
            raise _HeavyProjectSemanticError(
                f"dispatcher evidence has no API: {path}"
            )
        rows.append(MappingProxyType(dict(value)))
    if expected_ack_path is not None and not ack_observed:
        raise _HeavyProjectInfrastructureError(
            "topic subscription ACK is missing from the dispatcher evidence root"
        )
    return tuple(rows)


def _last_verify_step(protocol: V3GatewayProtocol) -> str | None:
    names = [step.name for step in protocol.steps if step.name.endswith(".verify")]
    return names[-1] if names else None


def _assert_verification(value: Any, *, context: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _assert_verification(nested, context=f"{context}.{key}")
        return
    passed = getattr(value, "passed", None)
    if passed is None:
        passed = getattr(value, "ok", None)
    if passed is not True:
        failures = getattr(value, "failures", None)
        details = getattr(value, "details", None)
        raise HeavyProjectRunnerError(
            f"{context} failed: {failures if failures is not None else details!r}"
        )


def _require_natural_intro(
    text: str,
    *,
    endpoint: str,
    version: str,
    policy: str,
) -> None:
    folded = text.casefold()
    required = {
        "skill": "waapi-skill" in folded,
        "endpoint": endpoint.casefold() in folded,
        "version": version.casefold() in folded,
        "policy": policy.casefold() in folded,
        "mode_read_only": "read_only" in folded,
        "mode_ask": "ask_before_changes" in folded,
        "mode_allow": "allow_changes" in folded,
    }
    missing = [key for key, ok in required.items() if not ok]
    if missing:
        raise HeavyProjectRunnerError(
            "first Skill-backed response lacks natural session context fields: "
            + ", ".join(missing)
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
    value = getattr(exc, "kwargs", None)
    if not isinstance(value, Mapping):
        return False
    message = value.get("message")
    return isinstance(message, str) and "object not found" in message.casefold()


def _strict_plain_json_object(
    value: Mapping[str, Any],
    *,
    field: str,
) -> dict[str, Any]:
    """Copy one trusted request into plain JSON containers before enqueueing it.

    Runtime builders deliberately freeze reviewed requests with mapping proxies
    and tuples.  ``waapi-client`` ultimately hands the request to a JSON
    serializer, so every nested container must cross this boundary as a plain
    ``dict`` or ``list``.  Unknown values are rejected here instead of being
    stringified or surfacing later as an indeterminate actor timeout.
    """

    converted = _strict_plain_json(value, field=field)
    if not isinstance(converted, dict):  # defensive: the public type is runtime data
        raise HeavyProjectRunnerError(f"trusted direct WAAPI {field} must be an object")
    return converted


def _strict_plain_json(value: Any, *, field: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HeavyProjectRunnerError(
                f"trusted direct WAAPI {field} contains a non-finite number"
            )
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise HeavyProjectRunnerError(
                    f"trusted direct WAAPI {field} contains a non-string object key"
                )
            result[key] = _strict_plain_json(nested, field=f"{field}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _strict_plain_json(nested, field=f"{field}[{index}]")
            for index, nested in enumerate(value)
        ]
    raise HeavyProjectRunnerError(
        f"trusted direct WAAPI {field} contains non-JSON value "
        f"{type(value).__name__}"
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return {
            item.name: _json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(nested) for nested in value]
    if isinstance(value, Path):
        return str(value)
    return repr(value)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _bounded_json_evidence(
    value: Any,
    *,
    ceiling_bytes: int = 65_536,
) -> Mapping[str, Any]:
    """Seal a publisher result without allowing unbounded outcome payloads."""

    normalized = _json_value(value)
    encoded = _canonical_json_bytes(normalized)
    included = len(encoded) <= ceiling_bytes
    return MappingProxyType(
        {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "included": included,
            "value": normalized if included else None,
        }
    )


def _valid_sha256_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_bounded_json_evidence(value: Any, *, ceiling_bytes: int = 65_536) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"sha256", "size_bytes", "included", "value"}
        or not _valid_sha256_text(value.get("sha256"))
        or type(value.get("size_bytes")) is not int
        or value.get("size_bytes", -1) < 0
        or type(value.get("included")) is not bool
    ):
        return False
    if value["included"]:
        encoded = _canonical_json_bytes(value["value"])
        return (
            len(encoded) == value["size_bytes"]
            and len(encoded) <= ceiling_bytes
            and hashlib.sha256(encoded).hexdigest() == value["sha256"]
        )
    return value["value"] is None and value["size_bytes"] > ceiling_bytes


def _oracle_evidence(
    *,
    scenario: OnlineScenario,
    version: str,
    runner: str,
    business_oracle_plan_sha256: str,
    verification: Any,
) -> dict[str, Any]:
    """Bind one bounded business oracle to the exact scenario/version lane."""

    workflow_id = _integration_workflow_id(scenario)
    if workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
        as_dict = getattr(verification, "as_dict", None)
        if not callable(as_dict):
            raise HeavyProjectRunnerError(
                "integration v2 verification omitted its closed as_dict projection"
            )
        verification_value = as_dict()
        if not isinstance(verification_value, Mapping):
            raise HeavyProjectRunnerError(
                "integration v2 verification as_dict projection is not an object"
            )
    else:
        verification_value = verification
    return {
        "contract": "waapi-skill.heavy-oracle/v2",
        "scenario_id": scenario.id,
        "version": version,
        "api": scenario.api,
        "runner": runner,
        "business_oracle_plan_sha256": business_oracle_plan_sha256,
        "verification": _json_value(verification_value),
    }


def _write_common_business_oracle_plan(
    *,
    scenario: OnlineScenario,
    version: str,
    scenario_root: Path,
    protocol: V3GatewayProtocol,
    provenance: Any,
    runner: str,
    typed_sections: (
        ObjectBusinessPlanSections
        | ImportBusinessPlanSections
        | AudioMediaBusinessPlanSections
        | SoundBankBusinessPlanSections
        | WorkflowBusinessPlanSections
        | DirectBusinessPlanSections
        | None
    ),
    primary_dispatch_count: int | None = None,
) -> BusinessOraclePlanEvidence:
    """Seal the common envelope with runner-compiled family sections.

    Every project-runner API must supply runner-compiled typed sections.
    """

    if typed_sections is None:
        raise HeavyProjectRunnerError(
            f"{scenario.api} reached plan writing without typed family sections"
        )
    family_kwargs = typed_sections.writer_kwargs()
    return write_business_oracle_plan(
        scenario_id=scenario.id,
        version=version,
        api=scenario.api,
        runner=runner,
        family=business_family_for_api(scenario.api),
        scenario_root=scenario_root,
        protocol_sha256=provenance.payload["protocol"]["sha256"],
        provenance_sha256=provenance.sha256,
        primary_dispatch_count=(
            scenario.primary_dispatch.count
            if primary_dispatch_count is None
            else primary_dispatch_count
        ),
        **family_kwargs,
    )


def _append_reason(current: str, extra: str) -> str:
    return extra if not current else f"{current}; {extra}"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(
        path,
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )


# Topic verification runs after the task/broker response path is clear, but the
# topic verifiers intentionally consume only the gateway payload/state.
_EMPTY_CODEX_RESULT = object()  # type: ignore[assignment]


__all__ = [
    "HEAVY_PROJECT_RUN_CONTRACT",
    "PROJECT_RUNNER_APIS",
    "PROJECT_RUNNER_MODEL_RESOLVED_REQUEST_FIELDS",
    "HeavyProjectRunOutcome",
    "HeavyProjectRunnerError",
    "HeavyProjectRunnerOptions",
    "OwnedDirectWaapiCall",
    "run_heavy_project_unit",
]

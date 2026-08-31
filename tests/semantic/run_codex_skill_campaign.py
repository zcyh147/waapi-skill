#!/usr/bin/env python3
"""Run or resume an immutable fresh-Codex WAAPI semantic campaign.

Each child process reuses the existing semantic matrix runner.  Frozen v2
profiles group pending pairs by live Wwise version; the reviewed V3 heavy
profile sends its pending scenarios to the matrix in suite order, where every
case owns a fresh lifecycle.  The campaign adds immutable fingerprints,
append-only attempts, strict resume compatibility, and evidence sealing.
"""

from __future__ import annotations

import argparse
from collections import Counter
import errno
import hashlib
import importlib.metadata
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

try:  # Native Windows has no fcntl module.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised by native Windows gates.
    _fcntl = None

try:  # POSIX hosts have no msvcrt module.
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised by POSIX gates.
    _msvcrt = None


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
WORKSPACE_ROOT = SKILL_ROOT.parent / "waapi-skill-workspace"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.semantic import run_codex_skill_matrix as matrix  # noqa: E402
from wwise_waapi.operation_composer import (  # noqa: E402
    OperationComposerError,
    parse_typed_action_cli_argument_sequence,
)
from tests.destructive.support.live_environment import (  # noqa: E402
    LiveEnvironmentError,
    require_live_environment,
)
from tests.destructive.support.sandbox_fixture import hash_project  # noqa: E402
from tests.semantic.support.codex_campaign import (  # noqa: E402
    ATTEMPT_MANIFEST_FILE,
    CampaignEvidenceError,
    atomic_write_json_with_digest,
    canonical_json_bytes,
    consolidate_units,
    create_attempt,
    create_immutable_campaign_config,
    list_campaign_attempts,
    load_immutable_campaign_config,
    seal_attempt,
    sha256_file,
    stable_tree_manifest,
    stable_tree_sha256,
    verify_attempt_seal,
)
from tests.semantic.support.codex_archive_paths import (  # noqa: E402
    ArchiveAbsolutePath,
    ArchiveRelativePathError,
    archive_absolute_has_relative_suffix,
    archive_absolute_names_equal,
    archive_relative_from_absolute,
    parse_archive_absolute_path,
    parse_archive_relative_path,
)
from tests.semantic.support.codex_campaign_runner import (  # noqa: E402
    AUTO_RETRY_CATEGORIES,
    BLOCKED_INFRASTRUCTURE_CATEGORIES,
    PAUSE_RETRY_CATEGORIES,
    ChildValidation,
    PhaseVerdict,
    load_strict_regular_json,
    replace_expected_skill_symlinks,
    validate_child_run,
)
from tests.semantic.support.codex_eval_suite import (  # noqa: E402
    CASE_IDS,
    PROFILE_IDS,
    SUPPORTED_VERSIONS,
    EvalSession,
    EvalSuiteError,
    load_eval_suite,
)
from tests.semantic.support.codex_business_oracle_plan_v3 import (  # noqa: E402
    BUSINESS_ORACLE_PLAN_FILE,
    BusinessOraclePlanError,
    BusinessOraclePlanEvidence,
    business_family_for_api,
    read_business_oracle_plan_envelope,
)
from tests.semantic.support.codex_audio_media_business_plan_v3 import (  # noqa: E402
    AudioMediaBusinessPlanError,
    AudioMediaBusinessPlanSections,
    parse_audio_media_business_plan_sections,
    validate_audio_archived_verification,
    validate_audio_media_business_plan_archive,
    validate_media_archived_verification,
)
from tests.semantic.support.codex_audio_conversion_runtime_v3 import (  # noqa: E402
    AudioConversionRuntimeError,
    audio_conversion_volatile_cache_paths,
)
from tests.semantic.support.codex_media_pool_runtime_v3 import (  # noqa: E402
    MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID,
    REFERENCE_MATCH_RESULT_CONTRACT,
    REFERENCE_MATCH_SCAN_LIMIT,
    MediaReportRowExpectation,
    media_answer_requires_order,
    media_grouped_report_failures,
    media_near_classification,
)
from tests.semantic.support.codex_import_business_plan_v3 import (  # noqa: E402
    COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA,
    COMPOUND_IMPORT_FIXTURE_KIND,
    IMPORT_BUSINESS_PLAN_SCHEMA,
    IMPORT_FIXTURE_KIND,
    ImportBusinessPlanError,
    ImportBusinessPlanSections,
    parse_import_business_plan_sections,
    validate_import_archived_verification,
    validate_import_business_plan_archive,
)
from tests.semantic.support.codex_cli_business_plan_v3 import (  # noqa: E402
    CliBusinessPlanError,
    CliBusinessPlanSections,
    parse_cli_business_plan_sections,
    validate_cli_archived_verification,
    validate_cli_business_plan_archive,
    validate_cli_convert_archived_side_effects,
)
from tests.semantic.support.codex_cli_runtime_v3 import (  # noqa: E402
    authored_project_archive_projection,
)
from tests.semantic.support.codex_object_business_plan_v3 import (  # noqa: E402
    ObjectBusinessPlanError,
    ObjectBusinessPlanSections,
    TYPED_PROFILE_OBJECT_METADATA_UNITS,
    TYPED_PROFILE_QUERY_REPAIR_UNIT_ID,
    TYPED_PROFILE_RENAME_UNIT_ID,
    TYPED_PROFILE_SET03_UNIT_ID,
    parse_object_business_plan_sections,
    validate_archived_object_business_plan,
    validate_object_archived_verification,
)
from tests.semantic.support.codex_direct_business_plan_v3 import (  # noqa: E402
    DIRECT_FIXTURE_KIND,
    DirectBusinessPlanError,
    DirectBusinessPlanSections,
    parse_direct_business_plan_sections,
    validate_direct_archived_verification,
    validate_direct_business_plan_archive,
    validate_direct_status_archive_binding,
)
from tests.semantic.support.codex_typed_draft_evidence_v3 import (  # noqa: E402
    BUSINESS_DRAFT_EVIDENCE_CONTRACT,
    TYPED_DRAFT_EVIDENCE_CONTRACT,
    TypedDraftEvidenceError,
    validate_typed_draft_evidence,
)
from tests.semantic.support.codex_soundbank_business_plan_v3 import (  # noqa: E402
    SoundBankBusinessPlanError,
    SoundBankBusinessPlanSections,
    TOPIC_ACK_CONTRACT,
    TOPIC_ACK_PROOF_CONTRACT,
    TOPIC_ACK_REQUIREMENT_CONTRACT,
    parse_soundbank_business_plan_sections,
    validate_soundbank_archived_verification,
    validate_soundbank_business_plan_archive,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (  # noqa: E402
    PROCESS_REFUSAL_ERROR_CODE,
    SOUNDBANK_TOPIC,
)
from tests.semantic.support.codex_workflow_business_plan_v3 import (  # noqa: E402
    WORKFLOW_FIXTURE_KIND,
    WorkflowBusinessPlanError,
    WorkflowBusinessPlanSections,
    parse_workflow_business_plan_sections,
)
from tests.semantic.support.codex_integration_workflows_v2 import (  # noqa: E402
    EXPECTED_ASSERTION_IDS as INTEGRATION_V2_ASSERTION_IDS,
)
from tests.semantic.support.codex_object_heavy_v3 import (  # noqa: E402
    ObjectHeavyRecipeError,
    build_object_heavy_v3_recipe,
    typed_input_business_query_recipe,
    typed_input_merge_recipe,
    typed_input_rename_recipe,
)
from tests.semantic.support.codex_object_runtime_v3 import (  # noqa: E402
    bounded_result_disclosure,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (  # noqa: E402
    AUDIO_IMPORT_DERIVED_SFX_PROTOCOL_REVISION,
    PROMPT_MATERIALIZATION_RECEIPT_CONTRACT,
    PROMPT_MATERIALIZATION_RECEIPT_FILE,
    PROMPT_PROVENANCE_FILE,
    PromptProvenanceError,
    PromptProvenanceEvidence,
    _canonicalize_legacy_protocol_manifest,
    deserialize_protocol,
    read_prompt_provenance,
    serialize_protocol,
)
from tests.semantic.support.codex_eval_protocol_v3 import (  # noqa: E402
    V3GatewayProtocol,
    V3ProtocolError,
    materialize_typed_transaction_protocol_requests,
    operation_request_equivalence,
)
from tests.semantic.support.codex_gateway_broker import (  # noqa: E402
    ExpectedGatewayStep,
    InlineTypedOperationArgument,
    TypedRequestFactsArgument,
)
from tests.semantic.support.codex_gateway_contracts import (  # noqa: E402
    GATEWAY_RESULT_CONTRACT,
    gateway_payload_contracts,
)
from tests.semantic.support.codex_filesystem_security import (  # noqa: E402
    CodexFileSecurityError,
    path_is_link_or_reparse,
    read_bounded_exclusive_regular_file,
    write_utf8_text_bytes,
)
from tests.semantic.support.codex_windows_path_budget import (  # noqa: E402
    WindowsCampaignPathBudget,
    WindowsCampaignPathBudgetError,
    require_windows_campaign_path_budget,
)
from tests.semantic.support.codex_prompt_asset_reads_v3 import (  # noqa: E402
    PromptAssetReadError,
    remove_validated_command_occurrences,
    validated_prompt_asset_cat_commands,
)
from tests.semantic.support.codex_task_runner_v3 import (  # noqa: E402
    _normalize_turn_reference_schedule,
)
from tests.semantic.support.codex_harness import (  # noqa: E402
    CodexGatewayErrorExpectation,
    CodexHarnessConfig,
    CodexHarnessError,
    WindowsPowerShellCoreHost,
    audit_session_events,
    build_task_exec_command,
    build_task_resume_command,
    classify_task_commands,
    classify_codex_infrastructure_failure,
    codex_process_environment,
    codex_runtime_files,
    completed_command_records,
    count_invalid_jsonl_lines,
    discover_windows_powershell_core,
    final_agent_message,
    gateway_continuation_binding_errors,
    is_evaluation_sensitive_environment_key,
    parse_jsonl_events,
    powershell_core_host_fingerprint,
    probe_windows_powershell_core,
    recoverable_preprocess_attempt_indexes,
    semantic_skill_bootstrap_developer_instructions,
    semantic_task_developer_instructions,
    turn_usage,
    validate_codex_version_output,
    workspace_skill_install_path,
)
from tests.semantic.support.codex_gateway_broker import (  # noqa: E402
    CodexGatewayBroker,
    DRAFT_REVISION_SUBCOMMANDS,
    GatewayInvocationError,
    ResponseBinding,
    SemanticJsonArgument,
    VALIDATED_SUBSCRIPTION_ACK_CONTRACT,
    _extract_topic_stream_records,
    resolve_gateway_invocation,
    gateway_step_sequence_matches,
    validate_transaction_show_confirmation_payload,
)
from tests.semantic.support.codex_transaction_seal import (  # noqa: E402
    TransactionSealError,
    validate_transaction_show_confirmation_against_store,
)


CAMPAIGN_MARKER_CONTRACT = "waapi-skill.codex-semantic-campaign-root/v1"
CAMPAIGN_MARKER_FILE = ".waapi-semantic-campaign-root.json"
CAMPAIGN_EFFECTIVE_CONTRACT = "waapi-skill.codex-semantic-campaign-effective/v1"
CHILD_EXECUTION_CONTRACT = "waapi-skill.codex-semantic-campaign-child/v1"
CHILD_CLASSIFICATION_CONTRACT = "waapi-skill.codex-semantic-child-classification/v1"
CONSOLIDATED_SUMMARY_FILE = "consolidated-summary.json"
LOCK_FILE = ".campaign.lock"
LOCK_OWNER_FILE = ".campaign-lock-owner.json"
_LOCK_REGION_BYTES = 1
_WINDOWS_LOCK_VIOLATION = 33
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
EXIT_BLOCKED = 3
EXIT_PENDING = 75
EXIT_INTERRUPTED = 130
HEAVY_V3_PROFILE_ID = matrix.HEAVY_V3_PROFILE_ID
MODIFICATION_POLICY_V3_PROFILE_ID = matrix.MODIFICATION_POLICY_V3_PROFILE_ID
COMPOUND_HEAVY_V1_PROFILE_ID = matrix.COMPOUND_HEAVY_V1_PROFILE_ID
TYPED_INPUT_PROFILE_ID = matrix.TYPED_INPUT_PROFILE_ID
DEEP_INTERFACE_MVP_PROFILE_ID = matrix.DEEP_INTERFACE_MVP_PROFILE_ID
AUDIO_IMPORT_BUSINESS_PROFILE_ID = matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID
OFFLINE_BUSINESS_AGENT_PROFILE_IDS = frozenset(
    matrix.OFFLINE_BUSINESS_AGENT_PROFILES
)
INTEGRATION_WORKFLOWS_V1_PROFILE_ID = (
    matrix.INTEGRATION_WORKFLOWS_V1_PROFILE_ID
)
INTEGRATION_WORKFLOWS_V2_PROFILE_ID = (
    matrix.INTEGRATION_WORKFLOWS_V2_PROFILE_ID
)
INTEGRATION_PROFILE_ID = matrix.INTEGRATION_PROFILE_ID
SEMANTIC_BOOTSTRAP_PROFILE_IDS = matrix.SEMANTIC_BOOTSTRAP_PROFILE_IDS
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
EXECUTABLE_V3_PROFILE_IDS = matrix.EXECUTABLE_V3_PROFILE_IDS
TERRA_LOCKED_V3_PROFILE_IDS = frozenset(
    {
        MODIFICATION_POLICY_V3_PROFILE_ID,
        COMPOUND_HEAVY_V1_PROFILE_ID,
        TYPED_INPUT_PROFILE_ID,
        DEEP_INTERFACE_MVP_PROFILE_ID,
        *OFFLINE_BUSINESS_AGENT_PROFILE_IDS,
        INTEGRATION_WORKFLOWS_V1_PROFILE_ID,
        INTEGRATION_WORKFLOWS_V2_PROFILE_ID,
        INTEGRATION_PROFILE_ID,
    }
)
HEAVY_V3_EFFECTIVE_CONTRACT = "waapi-skill.codex-semantic-campaign-effective/v3"
WINDOWS_SHELL_BACKEND = "pwsh-ps1-v1"
_WINDOWS_POWERSHELL_CORE_HOST_KEYS = frozenset(
    {
        "edition",
        "path",
        "version",
        "native_argument_passing",
        "sha256",
    }
)
HEAVY_V3_PHASE = "scenario"
HEAVY_V3_GROUP_ID = "heavy-v3"
HEAVY_V3_PROJECT_OUTCOME_CONTRACT = "waapi-skill.codex-heavy-project-run/v3"
HEAVY_V3_CLI_OUTCOME_CONTRACT = "waapi-skill.codex-heavy-cli-run/v3"
AUDIO_IMPORT_BUSINESS_OUTCOME_CONTRACT = (
    "waapi-skill.audio-import-business-agent-outcome/v1"
)
BUSINESS_AGENT_OUTCOME_CONTRACTS = {
    matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID: AUDIO_IMPORT_BUSINESS_OUTCOME_CONTRACT,
    matrix.OBJECT_LIFECYCLE_BUSINESS_PROFILE_ID: (
        "waapi-skill.object-lifecycle-business-agent-outcome/v1"
    ),
    matrix.OBJECT_METADATA_BUSINESS_PROFILE_ID: (
        "waapi-skill.object-metadata-business-agent-outcome/v1"
    ),
    matrix.OBJECT_GRAPH_BUSINESS_PROFILE_ID: (
        "waapi-skill.object-graph-business-agent-outcome/v1"
    ),
    matrix.SWITCH_ASSIGNMENT_BUSINESS_PROFILE_ID: (
        "waapi-skill.switch-assignment-business-agent-outcome/v1"
    ),
    matrix.CORE_BUSINESS_PROFILE_ID: (
        "waapi-skill.core-business-agent-outcome/v1"
    ),
    matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID: (
        "waapi-skill.project-setting-business-agent-outcome/v1"
    ),
    matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID: (
        "waapi-skill.runtime-control-business-agent-outcome/v1"
    ),
    matrix.SOUNDENGINE_BUSINESS_PROFILE_ID: (
        "waapi-skill.soundengine-business-agent-outcome/v1"
    ),
    matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID: (
        "waapi-skill.cli-console-business-agent-outcome/v1"
    ),
    matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID: (
        "waapi-skill.host-ui-debug-business-agent-outcome/v1"
    ),
    matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID: (
        "waapi-skill.compound-undo-business-agent-outcome/v1"
    ),
    matrix.AUTHORING_UI_BUSINESS_PROFILE_ID: (
        "waapi-skill.authoring-ui-business-agent-outcome/v1"
    ),
}
HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT = (
    "waapi-skill.codex-semantic-scenario-lifecycle/v3"
)
HEAVY_V3_CLI_LIFECYCLE_CONTRACT = "waapi-skill.codex-heavy-cli-lifecycle/v3"
HEAVY_V3_PROJECT_QUARANTINE_CONTRACT = (
    "waapi-skill.codex-semantic-scenario-quarantine/v3"
)
HEAVY_V3_TASK_INFRASTRUCTURE_FAILURE_CONTRACT = (
    "waapi-skill.codex-semantic-task-infrastructure-failure/v3"
)
HEAVY_V3_TASK_RESULT_CONTRACT = "waapi-skill.codex-semantic-task-result/v5"
HEAVY_V3_TOPIC_PUBLISHER_DIAGNOSTICS_CONTRACT = (
    "waapi-skill.topic-publisher-diagnostics/v1"
)
HEAVY_V3_PROMPT_MATERIALIZATION_CONTRACT = (
    PROMPT_MATERIALIZATION_RECEIPT_CONTRACT
)
HEAVY_V3_PROMPT_MATERIALIZATION_FILE = PROMPT_MATERIALIZATION_RECEIPT_FILE
HEAVY_V3_PROMPT_PROVENANCE_FILE = PROMPT_PROVENANCE_FILE
_DERIVED_SFX_PROTOCOL_HARNESS_SHA256 = frozenset(
    {
        "b152de8c55f8cb1085321da3ec877507627352acb10bed43e2ba7dbfae8b37df",
        "5100e2c672d2461fe0ce96dba4b0cf1536a43d48e100ad2ac3fc5dbc0203efdb",
    }
)
_CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION = (
    "audio-import-business-agent/current-v2-batch"
)
HEAVY_V3_ORACLE_CONTRACT = "waapi-skill.heavy-oracle/v2"
HEAVY_V3_LIVE_PREFLIGHT_CONTRACT = "waapi-skill.codex-semantic-live-preflight/v1"
HEAVY_V3_MIGRATION_API = "ak.wwise.cli.migrate"
HEAVY_V3_MIGRATION_SOURCE = REPO_ROOT / "tests" / "_org" / "2021.1" / "SampleProject.wproj"
_HEAVY_V3_REQUIRED_COMMON_GATES = frozenset(
    {
        "memory_isolated",
        "one_completed_turn",
        "one_target_skill",
        "no_collaboration",
        "skill_reads_exact",
        "read_prefix_exact",
        "gateway_count_exact",
        "no_other_commands",
        "no_discovery",
        "no_direct_waapi",
        "no_write_like",
        "no_unexpected_commands",
        "no_files_changed",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEAVY_V3_CODEX_INFRASTRUCTURE_CATEGORIES = frozenset(
    {
        "authentication",
        "quota_or_rate_limit",
        "service_unavailable",
        "timeout_before_agent_action",
        "turn_failed_before_agent_action",
    }
)


class CampaignConfigError(RuntimeError):
    """The requested invocation does not match a safe immutable campaign."""


class _HeavyV3UnitEvidenceError(CampaignEvidenceError):
    """One identified heavy scenario has untrusted child evidence."""

    def __init__(self, unit_id: str, reason: str) -> None:
        self.unit_id = unit_id
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class CampaignOptions:
    campaign_root: Path
    resume: bool
    verify_only: bool
    profile: str
    suite_path: Path
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    live_config: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    case_ids: tuple[str, ...]
    versions: tuple[str, ...]
    pair_ids: tuple[str, ...]
    offline_only: bool
    lock_timeout_seconds: float
    max_pre_action_retries: int
    wwise_readiness_timeout_seconds: float = 60.0
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None
    protocol_manifest_revision: str | None = None


@dataclass(frozen=True, slots=True)
class HeavyV3PromptEvidence:
    prompts: tuple[str, ...]
    provenance: PromptProvenanceEvidence
    business_oracle_plan: BusinessOraclePlanEvidence
    typed_sections: (
        ObjectBusinessPlanSections
        | ImportBusinessPlanSections
        | AudioMediaBusinessPlanSections
        | SoundBankBusinessPlanSections
        | CliBusinessPlanSections
        | WorkflowBusinessPlanSections
        | DirectBusinessPlanSections
        | None
    )


@dataclass(frozen=True, slots=True)
class ChildGroup:
    group_id: str
    version: str | None
    pair_ids: tuple[str, ...]
    sessions: tuple[EvalSession, ...]

    @property
    def offline_only(self) -> bool:
        return self.version is None


class _PosixCampaignLockBackend:
    def try_acquire(self, descriptor: int) -> bool:
        if _fcntl is None:
            raise CampaignConfigError(
                "campaign locking requires fcntl.flock on this POSIX host"
            )
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise CampaignConfigError(
                "campaign writer lock could not be acquired with fcntl.flock"
            ) from exc
        return True

    def release(self, descriptor: int) -> None:
        if _fcntl is None:  # pragma: no cover - guarded during acquisition.
            raise CampaignConfigError("campaign POSIX lock backend disappeared")
        _fcntl.flock(descriptor, _fcntl.LOCK_UN)

    @staticmethod
    def clear_owner(descriptor: int) -> None:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)


class _WindowsCampaignLockBackend:
    @staticmethod
    def _seek_region(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)

    @staticmethod
    def _ensure_region_exists(descriptor: int) -> None:
        if os.fstat(descriptor).st_size >= _LOCK_REGION_BYTES:
            return
        previous_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        finally:
            os.lseek(descriptor, previous_offset, os.SEEK_SET)

    def try_acquire(self, descriptor: int) -> bool:
        if _msvcrt is None:
            raise CampaignConfigError(
                "campaign locking requires msvcrt.locking on this Windows host"
            )
        self._ensure_region_exists(descriptor)
        self._seek_region(descriptor)
        try:
            _msvcrt.locking(
                descriptor,
                _msvcrt.LK_NBLCK,
                _LOCK_REGION_BYTES,
            )
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or (
                getattr(exc, "winerror", None) == _WINDOWS_LOCK_VIOLATION
            ):
                return False
            raise CampaignConfigError(
                "campaign writer lock could not be acquired with msvcrt.locking"
            ) from exc
        return True

    def release(self, descriptor: int) -> None:
        if _msvcrt is None:  # pragma: no cover - guarded during acquisition.
            raise CampaignConfigError("campaign Windows lock backend disappeared")
        self._seek_region(descriptor)
        _msvcrt.locking(
            descriptor,
            _msvcrt.LK_UNLCK,
            _LOCK_REGION_BYTES,
        )

    @classmethod
    def clear_owner(cls, descriptor: int) -> None:
        os.ftruncate(descriptor, _LOCK_REGION_BYTES)
        cls._seek_region(descriptor)
        os.write(descriptor, b"\0")
        os.fsync(descriptor)
        cls._seek_region(descriptor)


def _campaign_lock_platform_name() -> str:
    return os.name


def _campaign_lock_backend() -> Any:
    platform_name = _campaign_lock_platform_name()
    if platform_name == "posix":
        return _PosixCampaignLockBackend()
    if platform_name == "nt":
        return _WindowsCampaignLockBackend()
    raise CampaignConfigError(
        f"campaign locking has no supported backend for os.name={platform_name!r}"
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:  # pragma: no cover - defensive OS boundary.
            raise OSError("campaign lock owner write made no progress")
        view = view[written:]


class CampaignLock:
    def __init__(self, root: Path, *, timeout_seconds: float) -> None:
        self.root = Path(root)
        self.timeout_seconds = timeout_seconds
        self._descriptor: int | None = None
        self._backend: Any | None = None

    def __enter__(self) -> "CampaignLock":
        lock_path = self.root / LOCK_FILE
        backend = _campaign_lock_backend()
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        acquired = False
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise CampaignConfigError(
                    f"campaign lock is not a regular file: {lock_path}"
                )
            deadline = time.monotonic() + self.timeout_seconds
            while not backend.try_acquire(descriptor):
                if time.monotonic() >= deadline:
                    raise CampaignConfigError(
                        f"campaign writer lock remained busy for {self.timeout_seconds:.1f}s: {lock_path}"
                    )
                time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
            acquired = True
            self._descriptor = descriptor
            self._backend = backend
            owner_payload = (
                f"pid={os.getpid()} started={utc_now()}\n".encode("utf-8")
            )
            os.lseek(descriptor, 0, os.SEEK_SET)
            _write_all(descriptor, owner_payload)
            # Truncate only after replacing the owner record.  A Windows
            # msvcrt lock covers byte zero, so the locked region must never be
            # removed while the lock is held.
            os.ftruncate(descriptor, len(owner_payload))
            os.fsync(descriptor)
            atomic_write_json_with_digest(
                self.root / LOCK_OWNER_FILE,
                {
                    "pid": os.getpid(),
                    "started_at": utc_now(),
                    "campaign_root": str(self.root.resolve(strict=True)),
                },
            )
            return self
        except BaseException:
            if acquired:
                try:
                    backend.release(descriptor)
                except BaseException:
                    pass
            os.close(descriptor)
            self._descriptor = None
            self._backend = None
            raise

    def __exit__(self, exc_type: object, _value: object, _traceback: object) -> None:
        if self._descriptor is None or self._backend is None:
            return
        cleanup_error: BaseException | None = None
        try:
            try:
                self._backend.clear_owner(self._descriptor)
            except BaseException as error:
                cleanup_error = error
            try:
                self._backend.release(self._descriptor)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        finally:
            os.close(self._descriptor)
            self._descriptor = None
            self._backend = None
        if cleanup_error is not None and exc_type is None:
            raise cleanup_error


class InterruptLatch:
    """Defer SIGINT/SIGTERM until the active child reaches an evidence boundary."""

    def __init__(self) -> None:
        self.requested = False
        self.signal_number: int | None = None
        self._previous: dict[int, Any] = {}

    def __enter__(self) -> "InterruptLatch":
        for number in (signal.SIGINT, signal.SIGTERM):
            self._previous[number] = signal.getsignal(number)
            signal.signal(number, self._handle)
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        for number, previous in self._previous.items():
            signal.signal(number, previous)

    def _handle(self, number: int, _frame: object) -> None:
        self.requested = True
        self.signal_number = number
        print(
            f"[campaign] received signal {number}; deferring stop until the current child is sealed",
            flush=True,
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        options = parse_args(argv)
        return run_campaign(options)
    except (CampaignConfigError, EvalSuiteError) as exc:
        print(f"[campaign-config] {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except CampaignEvidenceError as exc:
        print(f"[campaign-blocked] {exc}", file=sys.stderr)
        return EXIT_BLOCKED


def require_skill_local_campaign_interpreter(
    skill_source: Path,
    *,
    interpreter: str | Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Fail before Codex if the candidate's packaged runtime is not active."""

    active_platform = os.name if platform_name is None else platform_name
    expected = (
        skill_source / ".venv" / "Scripts" / "python.exe"
        if active_platform == "nt" or active_platform.startswith("win")
        else skill_source / ".venv" / "bin" / "python"
    )
    expected_lexical = Path(os.path.abspath(os.fspath(expected)))
    if not expected_lexical.is_file():
        raise CampaignEvidenceError(
            "candidate Skill-local interpreter is missing; run this candidate's "
            f"scripts/setup_environment.py before the campaign: {expected_lexical}"
        )
    observed = Path(
        os.path.abspath(os.fspath(interpreter or sys.executable))
    )
    if os.path.normcase(str(observed)) != os.path.normcase(str(expected_lexical)):
        raise CampaignEvidenceError(
            "formal campaign must run with the exact candidate Skill-local "
            f"interpreter {expected_lexical}; received {observed}"
        )
    return expected_lexical


def run_campaign(options: CampaignOptions) -> int:
    if options.profile in EXECUTABLE_V3_PROFILE_IDS:
        return run_heavy_v3_campaign(options)
    try:
        suite = load_eval_suite(options.suite_path)
        sessions = matrix.select_sessions(
            suite.expand_profile(options.profile),
            case_ids=options.case_ids,
            versions=options.versions,
            pair_ids=options.pair_ids,
            offline_only=options.offline_only,
        )
    except SystemExit as exc:
        raise CampaignConfigError(str(exc)) from exc
    if not sessions:
        raise CampaignConfigError("no semantic sessions matched the requested filters")
    require_skill_local_campaign_interpreter(options.skill_source)
    required_units = required_unit_map(sessions)
    windows_path_budget = None
    if (
        not options.verify_only
        and options.profile not in OFFLINE_BUSINESS_AGENT_PROFILE_IDS
    ):
        try:
            windows_path_budget = _require_standard_windows_path_budget(
                options,
                sessions=sessions,
            )
        except (ValueError, WindowsCampaignPathBudgetError) as exc:
            raise CampaignConfigError(str(exc)) from exc
    _print_windows_path_budget(windows_path_budget)
    try:
        effective = build_effective_config(options, sessions=sessions, required_units=required_units)
    except (CampaignEvidenceError, OSError, subprocess.SubprocessError) as exc:
        raise CampaignConfigError(f"cannot fingerprint campaign inputs: {exc}") from exc
    sealed_windows_host = _sealed_windows_powershell_core_host(effective)

    root = prepare_campaign_root(options)
    with CampaignLock(root, timeout_seconds=options.lock_timeout_seconds):
        if options.resume:
            config = load_immutable_campaign_config(root)
            if config.get("effective") != effective:
                raise CampaignConfigError("resume invocation does not exactly match immutable campaign config")
            expected_effective_hash = hashlib.sha256(canonical_json_bytes(effective)).hexdigest()
            if config.get("effective_sha256") != expected_effective_hash:
                raise CampaignEvidenceError("campaign effective config digest is invalid")
            verify_campaign_marker(root, campaign_id=config.get("campaign_id"))
        else:
            config = create_immutable_campaign_config(
                root,
                {
                    "created_at": utc_now(),
                    "effective": effective,
                    "effective_sha256": hashlib.sha256(canonical_json_bytes(effective)).hexdigest(),
                },
            )
            write_campaign_marker(root, campaign_id=str(config["campaign_id"]))

        manifests = load_verified_attempts(root)
        consolidated = consolidate_units(required_units, manifests)
        write_consolidated(root, consolidated)
        terminal = consolidated_exit(consolidated)
        if terminal is not None:
            return terminal
        if options.verify_only:
            return EXIT_PENDING

        candidate_sha256 = str(effective["candidate"]["tree_sha256"])
        assert_effective_inputs_frozen(options, effective=effective)
        retry_round = 0
        with InterruptLatch() as interrupts:
            while True:
                scheduled = tuple(
                    consolidated["pending_unit_ids"] + consolidated["retryable_unit_ids"]
                )
                if not scheduled:
                    terminal = consolidated_exit(consolidated)
                    return terminal if terminal is not None else EXIT_PENDING
                attempt_id, attempt_root = create_attempt(root)
                print(
                    f"[campaign] {attempt_id} scheduled_units={len(scheduled)}",
                    flush=True,
                )
                observations: list[dict[str, Any]] = []
                current_retry_categories: list[str] = []
                attempt_blocked = False
                groups = build_child_groups(sessions, scheduled_unit_ids=scheduled)
                for group in groups:
                    if interrupts.requested:
                        break
                    try:
                        assert_effective_inputs_frozen(options, effective=effective)
                    except CampaignEvidenceError as exc:
                        attempt_blocked = True
                        validation = blocked_child_validation(group, reason=str(exc))
                        observations.extend(validation.observations)
                        atomic_write_json_with_digest(
                            attempt_root / "candidate-drift.json",
                            {"group_id": group.group_id, "error": str(exc), "recorded_at": utc_now()},
                        )
                        break
                    group_root = attempt_root / "runs" / group.group_id
                    matrix_root = group_root / "matrix"
                    group_root.mkdir(parents=True, exist_ok=False)
                    argv_child = build_child_argv(
                        options,
                        group=group,
                        matrix_root=matrix_root,
                        windows_powershell_core_host=sealed_windows_host,
                    )
                    atomic_write_json_with_digest(
                        group_root / "child-request.json",
                        {
                            "contract": CHILD_EXECUTION_CONTRACT,
                            "group_id": group.group_id,
                            "version": group.version,
                            "pair_ids": list(group.pair_ids),
                            "session_ids": [session.session_id for session in group.sessions],
                            "argv": argv_child,
                            "started_at": utc_now(),
                        },
                    )
                    print(
                        f"[campaign] start group={group.group_id} pairs={len(group.pair_ids)} "
                        f"sessions={len(group.sessions)}",
                        flush=True,
                    )
                    completed = run_child(argv_child, cwd=REPO_ROOT)
                    write_utf8_text_bytes(group_root / "stdout.txt", completed.stdout)
                    write_utf8_text_bytes(group_root / "stderr.txt", completed.stderr)
                    atomic_write_json_with_digest(
                        group_root / "child-result.json",
                        {
                            "contract": CHILD_EXECUTION_CONTRACT,
                            "group_id": group.group_id,
                            "returncode": completed.returncode,
                            "completed_at": utc_now(),
                        },
                    )
                    print(
                        f"[campaign] end group={group.group_id} returncode={completed.returncode}",
                        flush=True,
                    )
                    replaced_links: tuple[str, ...] = ()
                    try:
                        observed_candidate_sha256 = current_candidate_sha256(
                            options.skill_source,
                            effective=effective,
                        )
                        replaced_links = replace_expected_skill_symlinks(
                            group_root,
                            skill_source=options.skill_source,
                            candidate_sha256=observed_candidate_sha256,
                        )
                        if observed_candidate_sha256 != candidate_sha256:
                            raise CampaignEvidenceError(
                                "candidate Skill changed during child execution: "
                                f"expected={candidate_sha256} actual={observed_candidate_sha256}"
                            )
                        validation = validate_child_run(
                            matrix_root,
                            expected_sessions=group.sessions,
                            expected_pair_ids=group.pair_ids,
                            profile=options.profile,
                            skill_source=options.skill_source,
                            suite_path=options.suite_path,
                            live_config=options.live_config,
                            model=options.model,
                            reasoning_effort=options.reasoning_effort,
                            service_tier=options.service_tier,
                            version=group.version,
                            offline_only=group.offline_only,
                            returncode=completed.returncode,
                        )
                        assert_effective_inputs_frozen(options, effective=effective)
                    except (CampaignEvidenceError, OSError, TypeError, ValueError) as exc:
                        attempt_blocked = True
                        validation = blocked_child_validation(group, reason=str(exc))
                    observations.extend(validation.observations)
                    current_retry_categories.extend(validation.retry_categories)
                    atomic_write_json_with_digest(
                        group_root / "classification.json",
                        {
                            "contract": CHILD_CLASSIFICATION_CONTRACT,
                            "group_id": group.group_id,
                            "skill_link_attestations": list(replaced_links),
                            **validation.as_dict(),
                        },
                    )
                    if attempt_blocked or validation.has_blocked or validation.has_fail or validation.has_retryable:
                        break

                if interrupts.requested and not observations:
                    # No child began after the signal; an empty sealed attempt is
                    # still valid append-only evidence and leaves every unit pending.
                    atomic_write_json_with_digest(
                        attempt_root / "interrupted.json",
                        {"signal": interrupts.signal_number, "recorded_at": utc_now()},
                    )
                try:
                    assert_effective_inputs_frozen(options, effective=effective)
                except CampaignEvidenceError as exc:
                    atomic_write_json_with_digest(
                        attempt_root / "candidate-drift-before-seal.json",
                        {"error": str(exc), "recorded_at": utc_now()},
                    )
                    if observations:
                        observations[-1] = {**observations[-1], "status": "BLOCKED"}
                    else:
                        first = next(session for session in sessions if session.pair_id in scheduled)
                        observations.append(
                            {
                                "unit_id": first.pair_id,
                                "status": "BLOCKED",
                                "phases": [{"phase": first.phase, "status": "BLOCKED"}],
                            }
                        )
                manifest = seal_attempt(attempt_root, observations)
                verified = verify_attempt_seal(attempt_root)
                if verified != manifest:
                    raise CampaignEvidenceError(f"sealed attempt failed immediate verification: {attempt_id}")
                manifests.append(verified)
                consolidated = consolidate_units(required_units, manifests)
                write_consolidated(root, consolidated)
                print_status(consolidated)
                if interrupts.requested:
                    return EXIT_INTERRUPTED
                terminal = consolidated_exit(consolidated)
                if terminal is not None:
                    return terminal
                if not consolidated["retryable_unit_ids"]:
                    return EXIT_PENDING
                if any(category in PAUSE_RETRY_CATEGORIES for category in current_retry_categories):
                    return EXIT_PENDING
                auto_categories = AUTO_RETRY_CATEGORIES | {"prompt_audit_timeout_before_exec"}
                if not current_retry_categories or any(
                    category not in auto_categories for category in current_retry_categories
                ):
                    return EXIT_PENDING
                if retry_round >= options.max_pre_action_retries:
                    return EXIT_PENDING
                retry_round += 1
                print(
                    f"[campaign] retrying pre-action infrastructure units round={retry_round}",
                    flush=True,
                )


def run_heavy_v3_campaign(options: CampaignOptions) -> int:
    """Run or resume the reviewed V3 heavy units through the existing matrix."""

    if options.pair_ids:
        raise CampaignConfigError("heavy V3 campaigns do not accept pair filters")
    if (
        options.offline_only
        and options.profile not in OFFLINE_BUSINESS_AGENT_PROFILE_IDS
    ):
        raise CampaignConfigError("heavy V3 campaigns require real Wwise execution")
    if (
        options.profile == MODIFICATION_POLICY_V3_PROFILE_ID
        and (options.case_ids or options.versions)
    ):
        raise CampaignConfigError(
            "modification_policy_9 is one fixed nine-task campaign; "
            "case/version filters are reserved for its internal resume child"
        )
    try:
        units = load_heavy_v3_campaign_units(options)
    except (SystemExit, ValueError) as exc:
        raise CampaignConfigError(str(exc)) from exc
    required_units = {str(unit.unit_id): (HEAVY_V3_PHASE,) for unit in units}
    require_skill_local_campaign_interpreter(options.skill_source)
    windows_path_budget = None
    if not options.verify_only:
        try:
            windows_path_budget = _require_heavy_windows_path_budget(
                options,
                units=units,
            )
        except (ValueError, WindowsCampaignPathBudgetError) as exc:
            raise CampaignConfigError(str(exc)) from exc
    _print_windows_path_budget(windows_path_budget)
    try:
        effective = build_heavy_v3_effective_config(
            options,
            units=units,
            required_units=required_units,
        )
    except (CampaignEvidenceError, OSError, subprocess.SubprocessError) as exc:
        raise CampaignConfigError(f"cannot fingerprint heavy campaign inputs: {exc}") from exc
    sealed_windows_host = _sealed_windows_powershell_core_host(effective)
    validation_options = replace(
        options,
        windows_powershell_core_host=sealed_windows_host,
        protocol_manifest_revision=_sealed_protocol_manifest_revision(effective),
    )

    root = prepare_campaign_root(options)
    with CampaignLock(root, timeout_seconds=options.lock_timeout_seconds):
        if options.resume:
            config = load_immutable_campaign_config(root)
            if config.get("effective") != effective:
                raise CampaignConfigError(
                    "resume invocation does not exactly match immutable campaign config"
                )
            expected_effective_hash = hashlib.sha256(
                canonical_json_bytes(effective)
            ).hexdigest()
            if config.get("effective_sha256") != expected_effective_hash:
                raise CampaignEvidenceError("campaign effective config digest is invalid")
            verify_campaign_marker(root, campaign_id=config.get("campaign_id"))
        else:
            config = create_immutable_campaign_config(
                root,
                {
                    "created_at": utc_now(),
                    "effective": effective,
                    "effective_sha256": hashlib.sha256(
                        canonical_json_bytes(effective)
                    ).hexdigest(),
                },
            )
            write_campaign_marker(root, campaign_id=str(config["campaign_id"]))

        manifests = load_verified_attempts(root)
        if options.profile == MODIFICATION_POLICY_V3_PROFILE_ID:
            _validate_modification_policy_identity_history(
                root,
                manifests=manifests,
            )
        consolidated = consolidate_units(required_units, manifests)
        write_consolidated(root, consolidated)
        terminal = heavy_v3_consolidated_exit(
            consolidated,
            freeze_retryable=options.profile == TYPED_INPUT_PROFILE_ID,
        )
        if terminal is not None:
            return terminal
        if options.verify_only:
            return EXIT_PENDING

        scheduled_id_set = frozenset(
            consolidated["pending_unit_ids"]
            + consolidated["retryable_unit_ids"]
        )
        if not scheduled_id_set:
            return EXIT_PENDING
        # Preserve suite order across resume.  ``pending + retryable`` is a
        # status grouping, not an execution order; putting a formerly blocked
        # first unit at the end would disagree with the matrix's canonical
        # selection order and make a trustworthy resume impossible.
        scheduled_units = tuple(
            unit for unit in units if str(unit.unit_id) in scheduled_id_set
        )
        if {str(unit.unit_id) for unit in scheduled_units} != scheduled_id_set:
            raise CampaignEvidenceError(
                "heavy consolidated state references an unknown schedulable unit"
            )
        attempt_id, attempt_root = create_attempt(root)
        print(
            f"[campaign] {attempt_id} scheduled_units={len(scheduled_units)}",
            flush=True,
        )
        observations: list[dict[str, Any]] = []
        validation: ChildValidation | None = None
        group_root = attempt_root / "runs" / HEAVY_V3_GROUP_ID
        matrix_root = group_root / "matrix"
        group_root.mkdir(parents=True, exist_ok=False)

        with InterruptLatch() as interrupts:
            try:
                assert_heavy_v3_effective_inputs_frozen(
                    options,
                    effective=effective,
                )
            except CampaignEvidenceError as exc:
                validation = blocked_heavy_v3_validation(
                    scheduled_units,
                    reason=str(exc),
                )
                atomic_write_json_with_digest(
                    attempt_root / "candidate-drift.json",
                    {
                        "group_id": HEAVY_V3_GROUP_ID,
                        "error": str(exc),
                        "recorded_at": utc_now(),
                    },
                )
            else:
                argv_child = build_heavy_v3_child_argv(
                    options,
                    units=scheduled_units,
                    matrix_root=matrix_root,
                    windows_powershell_core_host=sealed_windows_host,
                )
                request_payload = heavy_v3_child_request(
                    options,
                    units=scheduled_units,
                    argv=argv_child,
                )
                atomic_write_json_with_digest(
                    group_root / "child-request.json",
                    request_payload,
                )
                print(
                    f"[campaign] start group={HEAVY_V3_GROUP_ID} "
                    f"scenarios={len(scheduled_units)}",
                    flush=True,
                )
                completed = run_child(argv_child, cwd=REPO_ROOT)
                write_utf8_text_bytes(group_root / "stdout.txt", completed.stdout)
                write_utf8_text_bytes(group_root / "stderr.txt", completed.stderr)
                atomic_write_json_with_digest(
                    group_root / "child-result.json",
                    {
                        "contract": CHILD_EXECUTION_CONTRACT,
                        "group_id": HEAVY_V3_GROUP_ID,
                        "returncode": completed.returncode,
                        "completed_at": utc_now(),
                    },
                )
                print(
                    f"[campaign] end group={HEAVY_V3_GROUP_ID} "
                    f"returncode={completed.returncode}",
                    flush=True,
                )
                replaced_links: tuple[str, ...] = ()
                try:
                    observed_candidate_sha256 = current_candidate_sha256(
                        options.skill_source,
                        effective=effective,
                    )
                    replaced_links = replace_expected_skill_symlinks(
                        group_root,
                        skill_source=options.skill_source,
                        candidate_sha256=observed_candidate_sha256,
                    )
                    if observed_candidate_sha256 != effective["candidate"]["tree_sha256"]:
                        raise CampaignEvidenceError(
                            "candidate Skill changed during child execution"
                        )
                    validate_heavy_v3_child_request(
                        group_root / "child-request.json",
                        expected=request_payload,
                    )
                    validation = validate_heavy_v3_child_run(
                        matrix_root,
                        expected_units=scheduled_units,
                        options=validation_options,
                        returncode=completed.returncode,
                    )
                    if options.profile == MODIFICATION_POLICY_V3_PROFILE_ID:
                        _validate_modification_policy_identity_history(
                            root,
                            manifests=manifests,
                            current_attempt_root=attempt_root,
                        )
                    assert_heavy_v3_effective_inputs_frozen(
                        options,
                        effective=effective,
                    )
                except (CampaignEvidenceError, OSError, TypeError, ValueError) as exc:
                    validation = blocked_heavy_v3_validation(
                        scheduled_units,
                        reason=str(exc),
                        blocked_unit_id=(
                            exc.unit_id
                            if isinstance(exc, _HeavyV3UnitEvidenceError)
                            else None
                        ),
                    )
                atomic_write_json_with_digest(
                    group_root / "classification.json",
                    {
                        "contract": CHILD_CLASSIFICATION_CONTRACT,
                        "group_id": HEAVY_V3_GROUP_ID,
                        "skill_link_attestations": list(replaced_links),
                        **validation.as_dict(),
                    },
                )

            if validation is None:
                raise CampaignEvidenceError("heavy child produced no classification")
            observations.extend(validation.observations)
            if interrupts.requested and not observations:
                atomic_write_json_with_digest(
                    attempt_root / "interrupted.json",
                    {
                        "signal": interrupts.signal_number,
                        "recorded_at": utc_now(),
                    },
                )
            try:
                assert_heavy_v3_effective_inputs_frozen(
                    options,
                    effective=effective,
                )
            except CampaignEvidenceError as exc:
                atomic_write_json_with_digest(
                    attempt_root / "candidate-drift-before-seal.json",
                    {"error": str(exc), "recorded_at": utc_now()},
                )
                observations = list(
                    blocked_heavy_v3_validation(
                        scheduled_units,
                        reason=str(exc),
                    ).observations
                )

            manifest = seal_attempt(attempt_root, observations)
            verified = verify_attempt_seal(attempt_root)
            if verified != manifest:
                raise CampaignEvidenceError(
                    f"sealed attempt failed immediate verification: {attempt_id}"
                )
            manifests.append(verified)
            if options.profile == MODIFICATION_POLICY_V3_PROFILE_ID:
                _validate_modification_policy_identity_history(
                    root,
                    manifests=manifests,
                )
            consolidated = consolidate_units(required_units, manifests)
            write_consolidated(root, consolidated)
            print_status(consolidated)
            if interrupts.requested:
                return EXIT_INTERRUPTED
            terminal = heavy_v3_consolidated_exit(
                consolidated,
                freeze_retryable=options.profile == TYPED_INPUT_PROFILE_ID,
            )
            return terminal if terminal is not None else EXIT_PENDING


def load_heavy_v3_campaign_units(options: CampaignOptions) -> tuple[Any, ...]:
    matrix_options = matrix.RunnerOptions(
        profile=options.profile,
        iteration_root=options.campaign_root / ".selection-only",
        suite_path=options.suite_path,
        skill_source=options.skill_source,
        codex_binary=options.codex_binary,
        windows_powershell_core_host=options.windows_powershell_core_host,
        auth_json=options.auth_json,
        live_config=options.live_config,
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier,
        timeout_seconds=options.timeout_seconds,
        case_ids=options.case_ids,
        versions=options.versions,
        pair_ids=(),
        offline_only=options.offline_only,
        overwrite=False,
        wwise_readiness_timeout_seconds=(
            options.wwise_readiness_timeout_seconds
        ),
    )
    return tuple(matrix.load_heavy_v3_units(matrix_options))


def build_heavy_v3_child_argv(
    options: CampaignOptions,
    *,
    units: Sequence[Any],
    matrix_root: Path,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> list[str]:
    if not units:
        raise CampaignEvidenceError("heavy child requires at least one scenario")
    argv = [
        sys.executable,
        str(REPO_ROOT / "tests" / "semantic" / "run_codex_skill_matrix.py"),
        "--profile",
        options.profile,
        "--suite",
        str(options.suite_path),
        "--iteration-root",
        str(matrix_root),
        "--skill-source",
        str(options.skill_source),
        "--codex-binary",
        str(options.codex_binary),
        "--auth-json",
        str(options.auth_json),
        "--live-config",
        str(options.live_config),
        "--model",
        options.model,
        "--reasoning-effort",
        options.reasoning_effort,
        "--service-tier",
        options.service_tier,
        "--timeout",
        str(options.timeout_seconds),
        "--wwise-readiness-timeout",
        str(options.wwise_readiness_timeout_seconds),
    ]
    if windows_powershell_core_host is not None:
        argv.extend(
            (
                "--sealed-windows-powershell-core-host-json",
                _windows_powershell_core_host_cli_json(
                    windows_powershell_core_host
                ),
            )
        )
    if options.offline_only:
        argv.append("--offline-only")
    for unit in units:
        argv.extend(("--case-id", str(unit.unit_id)))
    return argv


def heavy_v3_child_request(
    options: CampaignOptions,
    *,
    units: Sequence[Any],
    argv: Sequence[str],
) -> dict[str, Any]:
    return {
        "contract": CHILD_EXECUTION_CONTRACT,
        "group_id": HEAVY_V3_GROUP_ID,
        "scenario_ids": [str(unit.unit_id) for unit in units],
        "units": [
            {
                **heavy_v3_unit_row(unit, sequence=index),
                **_policy_unit_metadata(unit),
            }
            for index, unit in enumerate(units, start=1)
        ],
        "request": {
            "profile": options.profile,
            "suite_path": str(options.suite_path),
            "skill_source": str(options.skill_source),
            "codex_binary": str(options.codex_binary),
            "auth_json": str(options.auth_json),
            "live_config": str(options.live_config),
            "model": options.model,
            "reasoning_effort": options.reasoning_effort,
            "service_tier": options.service_tier,
            "timeout_seconds": options.timeout_seconds,
            "wwise_readiness_timeout_seconds": (
                options.wwise_readiness_timeout_seconds
            ),
            "memory": "disabled",
            **(
                {"approval_policy": "never"}
                if options.profile in TERRA_LOCKED_V3_PROFILE_IDS
                else {}
            ),
            "sequential": True,
            "offline_only": options.offline_only,
        },
        "argv": list(argv),
        "started_at": utc_now(),
    }


def validate_heavy_v3_child_request(
    path: Path,
    *,
    expected: Mapping[str, Any],
) -> None:
    from tests.semantic.support.codex_campaign import load_verified_json

    observed = load_verified_json(path)
    if observed != expected:
        raise CampaignEvidenceError("heavy child request differs from its sealed request")


def blocked_heavy_v3_validation(
    units: Sequence[Any],
    *,
    reason: str,
    blocked_unit_id: str | None = None,
) -> ChildValidation:
    if not units:
        raise CampaignEvidenceError("cannot block an empty heavy child selection")
    unit_ids = tuple(str(unit.unit_id) for unit in units)
    scenario_id = blocked_unit_id or unit_ids[0]
    if scenario_id not in unit_ids:
        raise CampaignEvidenceError(
            "heavy evidence error identifies a unit outside the scheduled selection"
        )
    verdict = PhaseVerdict(
        session_id=scenario_id,
        phase=HEAVY_V3_PHASE,
        status="BLOCKED",
        reason=reason,
    )
    return ChildValidation(
        observations=(
            {
                "unit_id": scenario_id,
                "status": "BLOCKED",
                "phases": [verdict.phase_row()],
            },
        ),
        phase_verdicts=(verdict,),
        executed_session_ids=(),
        pending_session_ids=tuple(
            unit_id for unit_id in unit_ids if unit_id != scenario_id
        ),
        retry_categories=(),
        summary={"validation_error": reason},
    )


def heavy_v3_consolidated_exit(
    consolidated: Mapping[str, Any],
    *,
    freeze_retryable: bool = False,
) -> int | None:
    if consolidated.get("blocked_unit_ids"):
        return EXIT_BLOCKED
    if freeze_retryable and consolidated.get("retryable_unit_ids"):
        # This release profile freezes every non-PASS root. Even a proven
        # pre-action service failure may only be retried under a new candidate
        # and campaign root; verify-only remains available after 25/25 PASS.
        return EXIT_PENDING
    if consolidated.get("pending_unit_ids") or consolidated.get("retryable_unit_ids"):
        return None
    if consolidated.get("failed_unit_ids"):
        return EXIT_FAIL
    if consolidated.get("all_selected_passed") is True:
        return EXIT_PASS
    return None


def _require_real_directory(
    path: Path,
    *,
    label: str,
    error_type: type[Exception] = CampaignEvidenceError,
) -> Path:
    """Validate a directory's lexical entry before resolving it.

    ``Path.is_symlink`` alone does not cover Windows junctions or other
    reparse points.  The shared filesystem-security primitive inspects the
    no-follow metadata first; resolution is only allowed after that boundary
    passes.
    """

    candidate = Path(path)
    try:
        metadata = candidate.lstat()
        if (
            path_is_link_or_reparse(candidate, metadata=metadata)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise error_type(f"{label} is not a real directory: {candidate}")
        return candidate.resolve(strict=True)
    except error_type:
        raise
    except (OSError, RuntimeError) as exc:
        raise error_type(
            f"{label} is not a real directory: {candidate}: {exc}"
        ) from exc


def prepare_campaign_root(options: CampaignOptions) -> Path:
    root = Path(
        os.path.abspath(os.fspath(options.campaign_root.expanduser()))
    )
    allowed = WORKSPACE_ROOT.resolve(strict=False)
    if root == allowed:
        raise CampaignConfigError(f"campaign root must be a named child below {allowed}")
    try:
        relative = root.relative_to(allowed)
    except ValueError as exc:
        raise CampaignConfigError(f"campaign root must be below {allowed}: {root}") from exc
    if not relative.parts:
        raise CampaignConfigError("campaign root must be a named child directory")
    if options.resume:
        root = _require_real_directory(
            root,
            label="resume campaign root",
            error_type=CampaignConfigError,
        )
    else:
        if os.path.lexists(root):
            raise CampaignConfigError(f"new campaign root already exists; use --resume: {root}")
        root.mkdir(parents=True, exist_ok=False)
        root = _require_real_directory(
            root,
            label="new campaign root",
            error_type=CampaignConfigError,
        )
    try:
        root.relative_to(allowed)
    except ValueError as exc:
        raise CampaignConfigError(
            f"campaign root resolves outside {allowed}: {root}"
        ) from exc
    return root


def _codex_version_fingerprint(
    binary: Path,
    *,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> str:
    """Probe one exact Codex executable and retain its path in every failure."""

    candidate = Path(binary)
    try:
        completed = subprocess.run(
            [str(candidate), "--version"],
            cwd=REPO_ROOT,
            env=codex_process_environment(
                candidate,
                os.environ,
                powershell_core_host=windows_powershell_core_host,
            ),
            text=True,
            encoding="utf-8",
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (CodexHarnessError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CampaignConfigError(
            "Codex version fingerprint probe could not execute "
            f"{candidate}: {type(exc).__name__}: {exc}"
        ) from exc
    version = completed.stdout
    if completed.returncode != 0 or not version:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise CampaignConfigError(
            f"Codex version fingerprint probe failed for {candidate}: {detail}"
        )
    try:
        return validate_codex_version_output(version, binary=candidate)
    except CodexHarnessError as exc:
        raise CampaignConfigError(str(exc)) from exc


def _runtime_distribution_fingerprint() -> list[tuple[str, str]]:
    """Return the installed Python distribution inventory with stage diagnostics."""

    try:
        rows: set[tuple[str, str]] = set()
        for distribution in importlib.metadata.distributions():
            name = distribution.metadata.get("Name")
            if name:
                rows.add((str(name).casefold(), str(distribution.version)))
        return sorted(rows)
    except (OSError, UnicodeError) as exc:
        raise CampaignEvidenceError(
            "cannot fingerprint runtime distributions for interpreter "
            f"{sys.executable}: {type(exc).__name__}: {exc}"
        ) from exc


def _codex_runtime_fingerprints(binary: Path) -> list[dict[str, str]]:
    """Bind Windows standalone helpers to the same immutable CLI release."""

    try:
        return [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in codex_runtime_files(binary)
        ]
    except (CodexHarnessError, OSError, ValueError, TypeError) as exc:
        raise CampaignEvidenceError(
            f"cannot fingerprint Codex runtime files for {binary}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _windows_powershell_core_host_seal(
    *,
    platform_name: str | None = None,
    host: WindowsPowerShellCoreHost | None = None,
) -> dict[str, str] | None:
    """Seal the exact PowerShell Core host used by native Windows campaigns."""

    active_platform = os.name if platform_name is None else str(platform_name)
    if active_platform != "nt" and not active_platform.startswith("win"):
        if host is not None:
            raise CampaignConfigError(
                "Windows PowerShell Core host cannot be sealed on a non-Windows host"
            )
        return None
    try:
        selected = host or discover_windows_powershell_core(
            platform_name=active_platform
        )
        fingerprint = powershell_core_host_fingerprint(selected)
    except (CodexHarnessError, OSError, TypeError, ValueError) as exc:
        raise CampaignConfigError(
            "Windows PowerShell Core host fingerprint probe failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"edition": "Core", **fingerprint}


def _codex_shell_effective_config(
    host: WindowsPowerShellCoreHost | None = None,
) -> dict[str, Any]:
    host_fingerprint = _windows_powershell_core_host_seal(host=host)
    return {
        "windows_powershell_core_host": host_fingerprint,
        "windows_shell_backend": (
            WINDOWS_SHELL_BACKEND if host_fingerprint is not None else None
        ),
        "allow_login_shell": False,
    }


def _sealed_windows_powershell_core_host(
    effective: Mapping[str, Any],
) -> WindowsPowerShellCoreHost | None:
    codex = effective.get("codex")
    if not isinstance(codex, Mapping):
        raise CampaignEvidenceError("campaign Codex fingerprint is malformed")
    value = codex.get("windows_powershell_core_host")
    if value is None:
        return None
    if (
        not isinstance(value, Mapping)
        or set(value) != _WINDOWS_POWERSHELL_CORE_HOST_KEYS
        or value.get("edition") != "Core"
    ):
        raise CampaignEvidenceError(
            "Windows PowerShell Core host fingerprint is malformed"
        )
    try:
        return WindowsPowerShellCoreHost(
            executable=str(value["path"]),
            version=str(value["version"]),
            native_argument_passing=str(value["native_argument_passing"]),
            sha256=str(value["sha256"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CampaignEvidenceError(
            "Windows PowerShell Core host fingerprint is malformed"
        ) from exc


def _sealed_protocol_manifest_revision(
    effective: Mapping[str, Any],
) -> str | None:
    """Select only reviewed archive migrations from immutable campaign identity."""

    selection = effective.get("selection")
    harness = effective.get("harness")
    if (
        effective.get("synthetic") is True
        and selection is None
        and harness is None
    ):
        return None
    if not isinstance(selection, Mapping) or not isinstance(harness, Mapping):
        raise CampaignEvidenceError("campaign protocol revision identity is malformed")
    profile = selection.get("profile")
    semantic_sha256 = harness.get("semantic_tree_sha256")
    sealed_revision = harness.get("protocol_manifest_revision")
    if profile == AUDIO_IMPORT_BUSINESS_PROFILE_ID:
        if sealed_revision == _CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION:
            return _CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
        if sealed_revision is not None:
            raise CampaignEvidenceError(
                "audio import business protocol revision is unreviewed"
            )
        if semantic_sha256 in _DERIVED_SFX_PROTOCOL_HARNESS_SHA256:
            return AUDIO_IMPORT_DERIVED_SFX_PROTOCOL_REVISION
        raise CampaignEvidenceError(
            "audio import business historical harness hash is unreviewed"
        )
    if sealed_revision is not None:
        raise CampaignEvidenceError(
            "non-audio-import campaign declares a protocol revision"
        )
    return None


def _assert_codex_shell_frozen(
    codex: Mapping[str, Any],
    *,
    platform_name: str | None = None,
) -> None:
    """Re-probe the sealed shell executable instead of rediscovering ambient PATH."""

    if codex.get("allow_login_shell") is not False:
        raise CampaignEvidenceError(
            "campaign Codex login-shell policy drifted from the immutable fingerprint"
        )
    expected = codex.get("windows_powershell_core_host")
    backend = codex.get("windows_shell_backend")
    active_platform = os.name if platform_name is None else str(platform_name)
    if active_platform != "nt" and not active_platform.startswith("win"):
        if expected is not None or backend is not None:
            raise CampaignEvidenceError(
                "Windows PowerShell Core host fingerprint does not match this platform"
            )
        return
    if (
        not isinstance(expected, Mapping)
        or set(expected) != _WINDOWS_POWERSHELL_CORE_HOST_KEYS
        or expected.get("edition") != "Core"
        or backend != WINDOWS_SHELL_BACKEND
    ):
        raise CampaignEvidenceError(
            "Windows PowerShell Core host fingerprint is malformed"
        )
    executable = expected.get("path")
    if not isinstance(executable, str):
        raise CampaignEvidenceError(
            "Windows PowerShell Core host fingerprint is malformed"
        )
    try:
        current_host = probe_windows_powershell_core(executable)
        current = {
            "edition": "Core",
            **powershell_core_host_fingerprint(current_host),
        }
    except (CodexHarnessError, OSError, TypeError, ValueError) as exc:
        raise CampaignEvidenceError(
            "Windows PowerShell Core host drifted from the immutable fingerprint: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if dict(expected) != current:
        raise CampaignEvidenceError(
            "Windows PowerShell Core host drifted from the immutable fingerprint"
        )


def build_effective_config(
    options: CampaignOptions,
    *,
    sessions: Sequence[EvalSession],
    required_units: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    skill_excludes = (".venv", "__pycache__", ".pytest_cache", ".DS_Store", ".coverage")
    harness_excludes = ("__pycache__", ".pytest_cache", ".DS_Store", ".coverage")
    interpreter = Path(sys.executable).resolve(strict=True)
    codex_version = _codex_version_fingerprint(
        options.codex_binary,
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    distributions = _runtime_distribution_fingerprint()
    session_rows = [
        {
            "session_id": session.session_id,
            "pair_id": session.pair_id,
            "profile_id": session.profile_id,
            "case_id": session.case.id,
            "version": session.version,
            "phase": session.phase,
            "repetition": session.repetition,
            "gateway_steps": list(session.gateway_steps),
            "hard_gates": list(session.hard_gates),
        }
        for session in sessions
    ]
    return {
        "contract": CAMPAIGN_EFFECTIVE_CONTRACT,
        "selection": {
            "profile": options.profile,
            "case_ids": list(options.case_ids),
            "versions": list(options.versions),
            "pair_ids": list(options.pair_ids),
            "offline_only": options.offline_only,
            "sessions": session_rows,
            "required_units": {key: list(value) for key, value in required_units.items()},
        },
        "candidate": {
            "path": str(options.skill_source),
            "tree_sha256": stable_tree_sha256(options.skill_source, exclude_names=skill_excludes),
            "excluded_names": list(skill_excludes),
        },
        "suite": {"path": str(options.suite_path), "sha256": sha256_file(options.suite_path)},
        "harness": {
            "semantic_tree_sha256": stable_tree_sha256(
                REPO_ROOT / "tests" / "semantic", exclude_names=harness_excludes
            ),
            "destructive_support_tree_sha256": stable_tree_sha256(
                REPO_ROOT / "tests" / "destructive" / "support", exclude_names=harness_excludes
            ),
            "excluded_names": list(harness_excludes),
        },
        "live_config": {
            "path": str(options.live_config),
            "sha256": sha256_file(options.live_config),
            "readiness_timeout_seconds": (
                options.wwise_readiness_timeout_seconds
            ),
        },
        "codex": {
            "path": str(options.codex_binary),
            "sha256": sha256_file(options.codex_binary),
            "runtime_files": _codex_runtime_fingerprints(options.codex_binary),
            **_codex_shell_effective_config(options.windows_powershell_core_host),
            "version": codex_version,
            "model": options.model,
            "reasoning_effort": options.reasoning_effort,
            "service_tier": options.service_tier,
            "timeout_seconds": options.timeout_seconds,
            "memory": "disabled",
            "fresh_session_per_phase": True,
        },
        "auth": {
            "mode": "ephemeral-codex-home-auth-link",
            "path": str(options.auth_json),
            "content_hashed": False,
        },
        "runtime": {
            "interpreter": str(interpreter),
            "interpreter_sha256": sha256_file(interpreter),
            "python_version": sys.version,
            "platform": sys.platform,
            "distributions": [[name, version] for name, version in distributions],
        },
        "retry_policy": {
            "max_pre_action_retries_per_invocation": options.max_pre_action_retries,
            "auto_categories": sorted(AUTO_RETRY_CATEGORIES | {"prompt_audit_timeout_before_exec"}),
            "pause_categories": sorted(PAUSE_RETRY_CATEGORIES),
        },
    }


def _windows_powershell_core_host_cli_json(
    host: WindowsPowerShellCoreHost,
) -> str:
    return canonical_json_bytes(
        {"edition": "Core", **powershell_core_host_fingerprint(host)}
    ).decode("utf-8")


_SUITE_TREE_EXCLUDE_NAMES = (
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
)


def build_heavy_v3_suite_fingerprint(
    options: CampaignOptions,
) -> dict[str, Any]:
    """Build the immutable suite projection shared by creation and replay.

    Legacy profile projections intentionally retain their exact historical
    shape.  The public composed integration profile adds its ordered component
    definitions because its profile file contains references rather than the
    workflow and committed-baseline bytes themselves.
    """

    result: dict[str, Any] = {
        "path": str(options.suite_path),
        "sha256": sha256_file(options.suite_path),
    }
    if options.profile in TERRA_LOCKED_V3_PROFILE_IDS:
        dependency_root = options.suite_path.parent
        result.update(
            {
                "dependency_root": str(dependency_root),
                "dependency_tree_sha256": stable_tree_sha256(
                    dependency_root,
                    exclude_names=_SUITE_TREE_EXCLUDE_NAMES,
                ),
            }
        )
    if options.profile != INTEGRATION_PROFILE_ID:
        return result

    try:
        integration_module = importlib.import_module(
            "tests.semantic.support.codex_integration_workflows"
        )
        profile = integration_module.load_integration_profile(
            options.suite_path,
            repo_root=REPO_ROOT,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise CampaignEvidenceError(
            "cannot fingerprint composed integration suite: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    component_rows: list[dict[str, Any]] = []
    for component in profile.component_profiles:
        source_rows: list[dict[str, str]] = []
        committed_manifest_paths = {
            f"baseline-{version}.json": manifest.path
            for version, manifest in getattr(
                component,
                "baseline_manifests",
                {},
            ).items()
        }
        for relative_name, expected_digest in component.source_digests:
            unresolved_source = committed_manifest_paths.get(
                relative_name,
                component.path.parent / relative_name,
            )
            try:
                source_path = Path(unresolved_source).resolve(strict=True)
                observed_digest = sha256_file(source_path)
            except (OSError, RuntimeError) as exc:
                raise CampaignEvidenceError(
                    "cannot fingerprint composed integration source file: "
                    f"{unresolved_source}"
                ) from exc
            if observed_digest != expected_digest:
                raise CampaignEvidenceError(
                    "composed integration loader digest disagrees with source file: "
                    f"{source_path}"
                )
            source_rows.append(
                {
                    "relative_path": str(relative_name),
                    "path": str(source_path),
                    "sha256": str(expected_digest),
                }
            )
        component_rows.append(
            {
                "profile_path": str(component.path),
                "profile_sha256": sha256_file(component.path),
                "dependency_root": str(component.path.parent),
                "dependency_tree_sha256": stable_tree_sha256(
                    component.path.parent,
                    exclude_names=_SUITE_TREE_EXCLUDE_NAMES,
                ),
                "definition_sha256": str(component.definition_sha256),
                "source_digests": [
                    [str(name), str(digest)]
                    for name, digest in component.source_digests
                ],
                "files": source_rows,
            }
        )
    result["composition"] = {
        "definition_sha256": str(profile.definition_sha256),
        "source_digests": [
            [str(name), str(digest)]
            for name, digest in profile.source_digests
        ],
        "components": component_rows,
    }
    return result


def build_heavy_v3_effective_config(
    options: CampaignOptions,
    *,
    units: Sequence[Any],
    required_units: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Fingerprint every immutable input of the V3 matrix campaign."""

    if not units:
        raise CampaignEvidenceError("heavy campaign requires at least one unit")
    skill_excludes = (".venv", "__pycache__", ".pytest_cache", ".DS_Store", ".coverage")
    harness_excludes = ("__pycache__", ".pytest_cache", ".DS_Store", ".coverage")
    interpreter = Path(sys.executable).resolve(strict=True)
    matrix_runner = Path(matrix.__file__).resolve(strict=True)
    campaign_runner = Path(__file__).resolve(strict=True)
    codex_version = _codex_version_fingerprint(
        options.codex_binary,
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    distributions = _runtime_distribution_fingerprint()
    unit_rows = [
        {
            **heavy_v3_unit_row(unit, sequence=index),
            "prompt_sha256": str(unit.scenario.prompt_sha256),
            "user_turn_count": int(unit.user_turn_count),
            "transaction_count": int(unit.transaction_count),
            **_policy_unit_metadata(unit),
        }
        for index, unit in enumerate(units, start=1)
    ]
    live_inputs = _heavy_v3_live_input_fingerprints(
        options,
        unit_rows=unit_rows,
    )
    return {
        "contract": HEAVY_V3_EFFECTIVE_CONTRACT,
        "selection": {
            "profile": options.profile,
            "case_ids": list(options.case_ids),
            "versions": list(options.versions),
            "pair_ids": [],
            "offline_only": options.offline_only,
            "units": unit_rows,
            "required_units": {
                str(key): list(value) for key, value in required_units.items()
            },
        },
        "candidate": {
            "path": str(options.skill_source),
            "tree_sha256": stable_tree_sha256(
                options.skill_source,
                exclude_names=skill_excludes,
            ),
            "excluded_names": list(skill_excludes),
        },
        "suite": build_heavy_v3_suite_fingerprint(options),
        "runner": {
            "campaign_path": str(campaign_runner),
            "campaign_sha256": sha256_file(campaign_runner),
            "matrix_path": str(matrix_runner),
            "matrix_sha256": sha256_file(matrix_runner),
        },
        "harness": {
            "semantic_tree_sha256": stable_tree_sha256(
                REPO_ROOT / "tests" / "semantic",
                exclude_names=harness_excludes,
            ),
            "destructive_support_tree_sha256": stable_tree_sha256(
                REPO_ROOT / "tests" / "destructive" / "support",
                exclude_names=harness_excludes,
            ),
            "excluded_names": list(harness_excludes),
            **(
                {
                    "protocol_manifest_revision": (
                        _CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
                    )
                }
                if options.profile == AUDIO_IMPORT_BUSINESS_PROFILE_ID
                else {}
            ),
        },
        "live_config": (
            {
                "path": str(options.live_config),
                "sha256": None,
                "used": False,
            }
            if options.offline_only
            else {
                "path": str(options.live_config),
                "sha256": sha256_file(options.live_config),
                "used": True,
            }
        ),
        "live_inputs": live_inputs,
        "codex": {
            "path": str(options.codex_binary),
            "sha256": sha256_file(options.codex_binary),
            "runtime_files": _codex_runtime_fingerprints(options.codex_binary),
            **_codex_shell_effective_config(options.windows_powershell_core_host),
            "version": codex_version,
            "model": options.model,
            "reasoning_effort": options.reasoning_effort,
            "service_tier": options.service_tier,
            "timeout_seconds": options.timeout_seconds,
            "memory": "disabled",
            "fresh_process_thread_and_task_per_scenario": True,
            **(
                {"approval_policy": "never"}
                if options.profile in TERRA_LOCKED_V3_PROFILE_IDS
                else {}
            ),
        },
        "auth": {
            "mode": "ephemeral-codex-home-auth-link",
            "path": str(options.auth_json),
            "content_hashed": False,
        },
        "runtime": {
            "interpreter": str(interpreter),
            "interpreter_sha256": sha256_file(interpreter),
            "python_version": sys.version,
            "platform": sys.platform,
            "distributions": [[name, version] for name, version in distributions],
        },
        "options": heavy_v3_immutable_options(options),
        "execution_policy": {
            "matrix_reuse": True,
            "sequential_wwise_lifecycles": True,
            "semantic_fail": "continue_and_preserve_later_case_evidence",
            "blocked_or_indeterminate": "stop",
            "resume": "schedule_pending_and_proven_retryable_units_in_suite_order",
        },
    }


def heavy_v3_immutable_options(options: CampaignOptions) -> dict[str, Any]:
    return {
        "campaign_root": str(options.campaign_root),
        "profile": options.profile,
        "suite_path": str(options.suite_path),
        "skill_source": str(options.skill_source),
        "codex_binary": str(options.codex_binary),
        "auth_json": str(options.auth_json),
        "live_config": str(options.live_config),
        "model": options.model,
        "reasoning_effort": options.reasoning_effort,
        "service_tier": options.service_tier,
        "timeout_seconds": options.timeout_seconds,
        "wwise_readiness_timeout_seconds": (
            options.wwise_readiness_timeout_seconds
        ),
        "case_ids": list(options.case_ids),
        "versions": list(options.versions),
        "pair_ids": [],
        "offline_only": options.offline_only,
        "lock_timeout_seconds": options.lock_timeout_seconds,
        "max_pre_action_retries": options.max_pre_action_retries,
    }


def _heavy_v3_live_input_fingerprints(
    options: CampaignOptions,
    *,
    unit_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve and freeze every selected real-Wwise input, not only its config path."""

    if not unit_rows:
        raise CampaignEvidenceError("heavy live-input fingerprint requires selected units")
    if options.profile in OFFLINE_BUSINESS_AGENT_PROFILE_IDS:
        versions = sorted({str(row.get("version")) for row in unit_rows})
        supported = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[
            options.profile
        ].supported_versions
        if any(version not in supported for version in versions):
            raise CampaignEvidenceError(
                "business Agent profile has an invalid fixture version"
            )
        return {
            "mode": "deterministic-waapi-read-shim",
            "versions": versions,
            "wwise_started": False,
            "production_gateway": True,
        }
    versions: list[str] = []
    migration_selected = False
    for row in unit_rows:
        if not isinstance(row, Mapping):
            raise CampaignEvidenceError("heavy selected-unit fingerprint row is malformed")
        version = row.get("version")
        api = row.get("api")
        if not isinstance(version, str) or not version:
            raise CampaignEvidenceError("heavy selected unit has no fingerprintable version")
        if not isinstance(api, str) or not api:
            raise CampaignEvidenceError("heavy selected unit has no fingerprintable API")
        if version not in versions:
            versions.append(version)
        migration_selected = migration_selected or api == HEAVY_V3_MIGRATION_API

    resolved_versions: dict[str, Any] = {}
    for version in versions:
        environment = {
            "WWISE_LIVE": "1",
            "WWISE_DESTRUCTIVE": "1",
            "WWISE_VERSION": version,
            "WWISE_TEST_CONFIG": str(options.live_config),
        }
        try:
            contract = require_live_environment(environment)
        except (LiveEnvironmentError, OSError, ValueError, TypeError) as exc:
            raise CampaignEvidenceError(
                f"cannot resolve immutable live inputs for Wwise {version}: {exc}"
            ) from exc
        if (
            contract.version != version
            or contract.console_path is None
            or contract.sample_project_source is None
        ):
            raise CampaignEvidenceError(
                f"live config did not resolve exact launcher and SampleProject for {version}"
            )
        launcher_input = Path(contract.console_path).expanduser()
        project_input = Path(contract.sample_project_source).expanduser()
        try:
            launcher = launcher_input.resolve(strict=True)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot resolve Wwise {version} launcher {launcher_input}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            project = project_input.resolve(strict=True)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot resolve Wwise {version} SampleProject {project_input}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            launcher_fingerprint = _heavy_v3_launcher_fingerprint(launcher)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot fingerprint Wwise {version} launcher {launcher}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            project_fingerprint = _heavy_v3_project_fingerprint(project)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot fingerprint Wwise {version} SampleProject {project}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        resolved_versions[version] = {
            "version": version,
            "launcher": launcher_fingerprint,
            "sample_project": project_fingerprint,
        }

    migration_source = None
    if migration_selected:
        migration_input = HEAVY_V3_MIGRATION_SOURCE.expanduser()
        try:
            migration_project = migration_input.resolve(strict=True)
            migration_source = _heavy_v3_project_fingerprint(migration_project)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot fingerprint migration SampleProject {migration_input}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    return {
        "versions": resolved_versions,
        "migration_source": migration_source,
    }


def _heavy_v3_launcher_fingerprint(path: Path) -> dict[str, Any]:
    launcher = Path(path)
    info = launcher.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or launcher.is_symlink():
        raise CampaignEvidenceError(
            f"resolved Wwise launcher must be a real regular file: {launcher}"
        )
    return {
        "path": str(launcher),
        "sha256": sha256_file(launcher),
        "size": info.st_size,
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
    }


def _heavy_v3_project_fingerprint(path: Path) -> dict[str, Any]:
    project = Path(path)
    info = project.stat(follow_symlinks=False)
    if (
        project.suffix.casefold() != ".wproj"
        or project.is_symlink()
        or not stat.S_ISREG(info.st_mode)
    ):
        raise CampaignEvidenceError(
            f"immutable Wwise source must be a real .wproj file: {project}"
        )
    root = project.parent.resolve(strict=True)
    full_hash = hash_project(root, preferred_strategy="full")
    if full_hash.strategy != "full":
        raise CampaignEvidenceError(
            f"immutable Wwise source did not receive a full-tree hash: {root}"
        )
    return {
        "project_path": str(project),
        "source_root": str(root),
        "project_sha256": sha256_file(project),
        "project_mtime_ns": info.st_mtime_ns,
        "full_project_hash": asdict(full_hash),
        "tree_sha256": stable_tree_sha256(root),
        "tree_mtime_sha256": _heavy_v3_tree_mtime_sha256(root),
    }


def _heavy_v3_tree_mtime_sha256(root: Path) -> str:
    tree = Path(root).resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for manifest_row in stable_tree_manifest(tree):
        relative = str(manifest_row["path"])
        entry = tree / relative
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot stat immutable source-tree entry {entry}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        rows.append(
            {
                "path": relative,
                "type": manifest_row["type"],
                "mode": stat.S_IMODE(info.st_mode),
                "size": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
        )
    return hashlib.sha256(canonical_json_bytes(rows)).hexdigest()


def heavy_v3_unit_row(unit: Any, *, sequence: int) -> dict[str, Any]:
    scenario_id = getattr(unit, "unit_id", None)
    version = getattr(unit, "version", None)
    scenario = getattr(unit, "scenario", None)
    api = getattr(scenario, "api", None)
    if (
        type(sequence) is not int
        or sequence < 1
        or not isinstance(scenario_id, str)
        or not scenario_id
        or not isinstance(version, str)
        or not version
        or not isinstance(api, str)
        or not api
    ):
        raise CampaignEvidenceError("heavy unit has an invalid identity")
    runner_lane = getattr(unit, "runner_lane", None)
    if runner_lane is None:
        runner_lane = "cli" if api.startswith("ak.wwise.cli.") else "project"
    if runner_lane not in {"project", "cli", "agent"}:
        raise CampaignEvidenceError("heavy unit has an invalid runner lane")
    row = {
        "sequence": sequence,
        "scenario_id": scenario_id,
        "version": version,
        "api": api,
        "runner": runner_lane,
    }
    base_scenario_id = getattr(unit, "base_scenario_id", None)
    if base_scenario_id is not None:
        if not isinstance(base_scenario_id, str) or not base_scenario_id:
            raise CampaignEvidenceError(
                "heavy unit has an invalid base-scenario identity"
            )
        row["base_scenario_id"] = base_scenario_id
    policy_metadata = _policy_unit_metadata(unit)
    for key in (
        "base_scenario_id",
        "policy_mode",
        "project_modification_policy",
        "repetition",
        "expected_primary_dispatch_count",
    ):
        if key in policy_metadata:
            row[key] = policy_metadata[key]
    return row


def _policy_unit_metadata(unit: Any) -> dict[str, Any]:
    policy = getattr(unit, "project_modification_policy", None)
    if policy is None:
        return {}
    base_scenario_id = getattr(unit, "base_scenario_id", None)
    repetition = getattr(unit, "repetition", None)
    expected_dispatch = getattr(unit, "expected_primary_dispatch_count", None)
    turns = tuple(getattr(unit, "turns", ()))
    if (
        policy not in {"read_only", "ask_before_changes", "allow_changes"}
        or not isinstance(base_scenario_id, str)
        or not base_scenario_id
        or type(repetition) is not int
        or repetition not in {1, 2, 3}
        or type(expected_dispatch) is not int
        or expected_dispatch not in {0, 1}
        or not turns
    ):
        raise CampaignEvidenceError(
            "modification-policy unit metadata is incomplete"
        )
    return {
        "base_scenario_id": base_scenario_id,
        "policy_mode": policy,
        "project_modification_policy": policy,
        "repetition": repetition,
        "expected_primary_dispatch_count": expected_dispatch,
        "turns": [
            {
                "index": int(turn.index),
                "kind": str(turn.kind),
                "prompt_sha256": hashlib.sha256(
                    str(turn.prompt).encode("utf-8")
                ).hexdigest(),
            }
            for turn in turns
        ],
    }


def assert_heavy_v3_effective_inputs_frozen(
    options: CampaignOptions,
    *,
    effective: Mapping[str, Any],
) -> None:
    assert_effective_inputs_frozen(options, effective=effective)
    if effective.get("suite") != build_heavy_v3_suite_fingerprint(options):
        raise CampaignEvidenceError(
            f"{options.profile} transitive suite inputs drifted"
        )
    runner = effective.get("runner")
    if not isinstance(runner, Mapping):
        raise CampaignEvidenceError("heavy campaign runner fingerprint is malformed")
    campaign_path = Path(__file__).resolve(strict=True)
    matrix_path = Path(matrix.__file__).resolve(strict=True)
    expected_runner = {
        "campaign_path": str(campaign_path),
        "campaign_sha256": sha256_file(campaign_path),
        "matrix_path": str(matrix_path),
        "matrix_sha256": sha256_file(matrix_path),
    }
    if dict(runner) != expected_runner:
        raise CampaignEvidenceError(
            "heavy campaign runner drifted from the immutable fingerprint"
        )
    if effective.get("options") != heavy_v3_immutable_options(options):
        raise CampaignEvidenceError(
            "heavy campaign execution options drifted from the immutable fingerprint"
        )
    selection = effective.get("selection")
    if not isinstance(selection, Mapping) or not isinstance(
        selection.get("units"), list
    ):
        raise CampaignEvidenceError(
            "heavy campaign selected-unit fingerprint is malformed"
        )
    observed_live_inputs = _heavy_v3_live_input_fingerprints(
        options,
        unit_rows=selection["units"],
    )
    if effective.get("live_inputs") != observed_live_inputs:
        raise CampaignEvidenceError(
            "heavy campaign Wwise launcher or immutable source project drifted"
        )


def validate_heavy_v3_child_run(
    matrix_root: Path,
    *,
    expected_units: Sequence[Any],
    options: CampaignOptions,
    returncode: int,
) -> ChildValidation:
    """Validate incremental V3 matrix evidence and classify every completed case."""

    root = Path(matrix_root).resolve(strict=True)
    units = tuple(expected_units)
    if not units:
        raise CampaignEvidenceError("heavy child validation requires expected units")
    expected_rows = tuple(
        heavy_v3_unit_row(unit, sequence=index)
        for index, unit in enumerate(units, start=1)
    )
    expected_ids = tuple(str(row["scenario_id"]) for row in expected_rows)
    run_config = load_strict_regular_json(root / "run-config.json")
    summary = load_strict_regular_json(root / "summary.json")
    _validate_heavy_v3_run_config(
        run_config,
        expected_rows=expected_rows,
        options=options,
    )
    _validate_heavy_v3_summary(
        summary,
        expected_ids=expected_ids,
        returncode=returncode,
        expected_profile=options.profile,
        expected_rows=expected_rows,
    )
    _validate_heavy_v3_live_preflight(
        root,
        summary=summary,
        expected_profile=options.profile,
    )
    _validate_heavy_v3_progress(run_config["progress"], summary=summary)

    case_rows = summary["case_records"]
    attempted_ids = tuple(summary["attempted_unit_ids"])
    actual_scenario_dirs = _heavy_v3_scenario_directories(root)
    expected_scenario_names = {
        f"{index:03d}-{scenario_id}"
        for index, scenario_id in enumerate(attempted_ids, start=1)
    }
    if set(actual_scenario_dirs) != expected_scenario_names:
        raise CampaignEvidenceError(
            "heavy scenario directories differ from the completed matrix records: "
            f"expected={sorted(expected_scenario_names)} "
            f"actual={sorted(actual_scenario_dirs)}"
        )

    verdicts: list[PhaseVerdict] = []
    observations: list[dict[str, Any]] = []
    retry_categories: list[str] = []

    def append_blocked(scenario_id: str, reason: str) -> None:
        verdict = PhaseVerdict(
            session_id=scenario_id,
            phase=HEAVY_V3_PHASE,
            status="BLOCKED",
            reason=reason,
        )
        verdicts.append(verdict)
        observations.append(
            {
                "unit_id": scenario_id,
                "status": "BLOCKED",
                "phases": [verdict.phase_row()],
            }
        )

    for index, (summary_row, expected_row) in enumerate(
        zip(case_rows, expected_rows, strict=False),
        start=1,
    ):
        scenario_id = str(expected_row["scenario_id"])
        if index > len(attempted_ids):
            break
        scenario_root = actual_scenario_dirs[f"{index:03d}-{scenario_id}"]
        try:
            matrix_case = load_strict_regular_json(
                scenario_root / "matrix-case.json"
            )
            _validate_heavy_v3_matrix_case(
                matrix_case,
                expected_unit=units[index - 1],
                expected_row=expected_row,
                summary_row=summary_row,
                scenario_root=scenario_root,
                options=options,
            )
        except (CampaignEvidenceError, OSError) as exc:
            append_blocked(
                scenario_id,
                f"untrusted heavy case evidence: {exc}",
            )
            continue
        status = str(matrix_case["status"])
        try:
            retry_category = _heavy_v3_retryable_infrastructure_category(
                matrix_case,
                scenario_root=scenario_root,
                expected_unit=units[index - 1],
                options=options,
            )
        except (CampaignEvidenceError, OSError) as exc:
            append_blocked(
                scenario_id,
                f"untrusted heavy retry-classification evidence: {exc}",
            )
            continue
        campaign_status = "BLOCKED" if status == "INDETERMINATE" else status
        if retry_category is not None:
            campaign_status = "RETRYABLE"
            retry_categories.append(retry_category)
        reason = str(matrix_case.get("reason") or "")
        if not reason:
            reason = (
                "runner and independent business oracle passed"
                if campaign_status == "PASS"
                else f"matrix classified scenario as {campaign_status}"
            )
        verdict = PhaseVerdict(
            session_id=scenario_id,
            phase=HEAVY_V3_PHASE,
            status=campaign_status,
            reason=reason,
            retry_category=retry_category,
        )
        verdicts.append(verdict)
        observations.append(
            {
                "unit_id": scenario_id,
                "status": campaign_status,
                "phases": [verdict.phase_row()],
            }
        )

    pending_ids = list(summary["pending_unit_ids"])
    if not observations and returncode == 1 and summary["preflight"] == "blocked":
        first_id = expected_ids[0]
        reason = "; ".join(summary["run_errors"]) or "heavy matrix live preflight blocked"
        verdict = PhaseVerdict(
            session_id=first_id,
            phase=HEAVY_V3_PHASE,
            status="BLOCKED",
            reason=reason,
        )
        verdicts.append(verdict)
        observations.append(
            {
                "unit_id": first_id,
                "status": "BLOCKED",
                "phases": [verdict.phase_row()],
            }
        )
        pending_ids = [unit_id for unit_id in pending_ids if unit_id != first_id]

    return ChildValidation(
        observations=tuple(observations),
        phase_verdicts=tuple(verdicts),
        executed_session_ids=attempted_ids,
        pending_session_ids=tuple(pending_ids),
        retry_categories=tuple(retry_categories),
        summary=summary,
    )


def _validate_heavy_v3_run_config(
    value: Any,
    *,
    expected_rows: Sequence[Mapping[str, Any]],
    options: CampaignOptions,
) -> None:
    required_keys = {
        "contract",
        "started_at",
        "updated_at",
        "completed_at",
        "profile",
        "expected_unit_count",
        "selected_units",
        "case_ids",
        "versions",
        "pair_ids",
        "offline_only",
        "model",
        "reasoning_effort",
        "service_tier",
        "timeout_seconds",
        "wwise_readiness_timeout_seconds",
        "memory",
        "fresh_process_thread_and_task_per_scenario",
        "sequential_wwise_lifecycles",
        "semantic_fail_policy",
        "blocked_or_indeterminate_policy",
        "skill_source",
        "suite_path",
        "live_config",
        "progress",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required_keys
        or value.get("contract") != matrix.HEAVY_V3_RUN_CONFIG_CONTRACT
    ):
        raise CampaignEvidenceError("invalid heavy matrix run-config contract")
    expected_ids = [str(row["scenario_id"]) for row in expected_rows]
    expected = {
        "profile": options.profile,
        "expected_unit_count": len(expected_rows),
        "selected_units": [dict(row) for row in expected_rows],
        "case_ids": expected_ids,
        "versions": [],
        "pair_ids": [],
        "offline_only": options.offline_only,
        "model": options.model,
        "reasoning_effort": options.reasoning_effort,
        "service_tier": options.service_tier,
        "timeout_seconds": options.timeout_seconds,
        "wwise_readiness_timeout_seconds": (
            options.wwise_readiness_timeout_seconds
        ),
        "memory": "disabled",
        "fresh_process_thread_and_task_per_scenario": True,
        "sequential_wwise_lifecycles": True,
        "semantic_fail_policy": "continue",
        "blocked_or_indeterminate_policy": "stop",
        "skill_source": str(options.skill_source),
        "suite_path": str(options.suite_path),
        "live_config": str(options.live_config),
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise CampaignEvidenceError(
                f"heavy matrix run-config mismatch for {key}"
            )
    if not _valid_heavy_timestamp(value.get("started_at")) or not _valid_heavy_timestamp(
        value.get("updated_at")
    ):
        raise CampaignEvidenceError("heavy matrix run-config timestamps are invalid")
    if value.get("completed_at") is not None and not _valid_heavy_timestamp(
        value.get("completed_at")
    ):
        raise CampaignEvidenceError("heavy matrix completion timestamp is invalid")
    progress = value.get("progress")
    if not isinstance(progress, Mapping) or set(progress) != {
        "preflight",
        "attempted_unit_count",
        "attempted_unit_ids",
        "pending_unit_ids",
        "status_counts",
        "stop_reason",
        "run_error_count",
    }:
        raise CampaignEvidenceError("heavy matrix run-config progress is malformed")


def _validate_heavy_v3_summary(
    value: Any,
    *,
    expected_ids: Sequence[str],
    returncode: int,
    expected_profile: str = HEAVY_V3_PROFILE_ID,
    expected_rows: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    required_keys = {
        "contract",
        "started_at",
        "updated_at",
        "completed_at",
        "profile",
        "preflight",
        "selected_unit_count",
        "attempted_unit_count",
        "attempted_unit_ids",
        "status_counts",
        "passed_unit_ids",
        "failed_unit_ids",
        "blocked_unit_ids",
        "indeterminate_unit_ids",
        "pending_unit_ids",
        "stop_reason",
        "stopped_early",
        "all_selected_passed",
        "run_errors",
        "case_records",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required_keys
        or value.get("contract") != matrix.HEAVY_V3_SUMMARY_CONTRACT
        or value.get("profile") != expected_profile
    ):
        raise CampaignEvidenceError("invalid heavy matrix summary contract")
    if value.get("selected_unit_count") != len(expected_ids):
        raise CampaignEvidenceError("heavy matrix summary selection count mismatch")
    attempted = value.get("attempted_unit_ids")
    pending = value.get("pending_unit_ids")
    case_records = value.get("case_records")
    run_errors = value.get("run_errors")
    if not all(isinstance(item, list) for item in (attempted, pending, case_records, run_errors)):
        raise CampaignEvidenceError("heavy matrix summary arrays are malformed")
    if any(not isinstance(item, str) for item in (*attempted, *pending, *run_errors)):
        raise CampaignEvidenceError("heavy matrix summary string arrays are malformed")
    if attempted != list(expected_ids[: len(attempted)]):
        raise CampaignEvidenceError("heavy matrix attempted units are not an ordered prefix")
    if pending != list(expected_ids[len(attempted) :]):
        raise CampaignEvidenceError("heavy matrix pending units are not the remaining suffix")
    if value.get("attempted_unit_count") != len(attempted) or len(case_records) != len(attempted):
        raise CampaignEvidenceError("heavy matrix attempted counts disagree")
    statuses: list[str] = []
    for index, record in enumerate(case_records):
        required_record_keys = {
            "sequence",
            "scenario_id",
            "version",
            "api",
            "runner",
            "status",
            "reason",
            "scenario_root",
        }
        expected_row = (
            expected_rows[index]
            if expected_rows is not None and index < len(expected_rows)
            else None
        )
        if isinstance(expected_row, Mapping):
            required_record_keys.update(
                key
                for key in (
                    "base_scenario_id",
                    "policy_mode",
                    "project_modification_policy",
                    "repetition",
                    "expected_primary_dispatch_count",
                )
                if key in expected_row
            )
        if not isinstance(record, Mapping) or set(record) != required_record_keys:
            raise CampaignEvidenceError("heavy matrix summary case record is malformed")
        if record.get("sequence") != index + 1 or record.get("scenario_id") != attempted[index]:
            raise CampaignEvidenceError("heavy matrix summary case order drifted")
        if isinstance(expected_row, Mapping) and any(
            record.get(key) != value
            for key, value in expected_row.items()
        ):
            raise CampaignEvidenceError(
                "heavy matrix summary unit metadata drifted"
            )
        status = record.get("status")
        if status not in matrix.HEAVY_V3_STATUSES:
            raise CampaignEvidenceError("heavy matrix summary has an invalid status")
        statuses.append(str(status))
    expected_status_counts = {
        status: statuses.count(status)
        for status in ("PASS", "FAIL", "BLOCKED", "INDETERMINATE")
    }
    if value.get("status_counts") != expected_status_counts:
        raise CampaignEvidenceError("heavy matrix summary status counts disagree")
    status_lists = {
        "passed_unit_ids": "PASS",
        "failed_unit_ids": "FAIL",
        "blocked_unit_ids": "BLOCKED",
        "indeterminate_unit_ids": "INDETERMINATE",
    }
    for key, status in status_lists.items():
        expected = [
            attempted[index]
            for index, observed_status in enumerate(statuses)
            if observed_status == status
        ]
        if value.get(key) != expected:
            raise CampaignEvidenceError(f"heavy matrix summary {key} disagrees")
    stop_reason = value.get("stop_reason")
    if stop_reason is not None and (not isinstance(stop_reason, str) or not stop_reason):
        raise CampaignEvidenceError("heavy matrix stop reason is malformed")
    if value.get("stopped_early") is not bool(stop_reason):
        raise CampaignEvidenceError("heavy matrix stopped flag disagrees")
    all_pass = (
        len(attempted) == len(expected_ids)
        and bool(attempted)
        and statuses == ["PASS"] * len(attempted)
        and not run_errors
        and stop_reason is None
        and value.get("preflight") == "passed"
        and value.get("completed_at") is not None
    )
    if value.get("all_selected_passed") is not all_pass:
        raise CampaignEvidenceError("heavy matrix all-pass flag disagrees")
    if value.get("preflight") not in {"pending", "passed", "blocked"}:
        raise CampaignEvidenceError("heavy matrix preflight state is invalid")
    if not _valid_heavy_timestamp(value.get("started_at")) or not _valid_heavy_timestamp(
        value.get("updated_at")
    ):
        raise CampaignEvidenceError("heavy matrix summary timestamps are invalid")
    completed_at = value.get("completed_at")
    if completed_at is not None and not _valid_heavy_timestamp(completed_at):
        raise CampaignEvidenceError("heavy matrix summary completion timestamp is invalid")
    preflight = value.get("preflight")
    if returncode == 0:
        if not all_pass or completed_at is None:
            raise CampaignEvidenceError(
                "heavy matrix exited zero without one terminal all-pass summary"
            )
        return

    if returncode == 1:
        if completed_at is None:
            raise CampaignEvidenceError(
                "normally exited heavy matrix lacks terminal summary"
            )
        if preflight == "blocked":
            if (
                attempted
                or statuses
                or pending != list(expected_ids)
                or stop_reason != "live-dependency-preflight"
                or not run_errors
            ):
                raise CampaignEvidenceError(
                    "heavy matrix preflight block contradicts its terminal summary"
                )
            return
        if preflight != "passed":
            raise CampaignEvidenceError(
                "terminal heavy matrix has no passed or blocked live preflight"
            )
        blocking_statuses = {"BLOCKED", "INDETERMINATE"}
        if any(status in blocking_statuses for status in statuses):
            terminal_status = statuses[-1] if statuses else ""
            terminal_id = attempted[-1] if attempted else ""
            if (
                terminal_status not in blocking_statuses
                or stop_reason != f"{terminal_status.casefold()}:{terminal_id}"
                or not run_errors
                or not any(f"heavy-unit:{terminal_id}" in error for error in run_errors)
            ):
                raise CampaignEvidenceError(
                    "heavy matrix blocking status is not bound to its terminal error"
                )
            return
        if (
            "FAIL" not in statuses
            or len(attempted) != len(expected_ids)
            or pending
            or stop_reason is not None
            or run_errors
        ):
            raise CampaignEvidenceError(
                "heavy matrix exited one without a complete semantic failure or block"
            )
        return

    # The matrix persists one non-terminal prefix after every completed case.
    # Preserve that prefix only when at least one real suffix unit remains.  An
    # abnormal child must never turn a final non-terminal all-PASS snapshot into
    # completed campaign evidence.
    if (
        completed_at is not None
        or preflight != "passed"
        or not attempted
        or not pending
        or stop_reason is not None
        or run_errors
        or any(status in {"BLOCKED", "INDETERMINATE"} for status in statuses)
    ):
        raise CampaignEvidenceError(
            "abnormally exited heavy matrix lacks one trustworthy completed prefix "
            "with a real pending suffix"
        )


def _validate_heavy_v3_live_preflight(
    root: Path,
    *,
    summary: Mapping[str, Any],
    expected_profile: str,
) -> None:
    payload = load_strict_regular_json(root / "live-preflight.json")
    if not isinstance(payload, Mapping):
        raise CampaignEvidenceError("heavy matrix live preflight must be an object")
    state = summary.get("preflight")
    if state == "passed":
        if expected_profile in OFFLINE_BUSINESS_AGENT_PROFILE_IDS:
            descriptor = matrix.OFFLINE_BUSINESS_AGENT_PROFILES[expected_profile]
            expected = {
                "contract": descriptor.preflight_contract,
                "ok": True,
                "mode": "offline-production-gateway",
                "wwise_started": False,
                "production_gateway": True,
            }
            if dict(payload) != expected:
                raise CampaignEvidenceError(
                    "business Agent preflight evidence is malformed"
                )
            return
        required = {
            "contract",
            "ok",
            "dependency",
            "module",
            "required_symbols",
            "current_interpreter",
            "automatic_install_attempted",
        }
        if (
            set(payload) != required
            or payload.get("contract") != HEAVY_V3_LIVE_PREFLIGHT_CONTRACT
            or payload.get("ok") is not True
            or payload.get("dependency") != "waapi-client"
            or payload.get("module") != "waapi"
            or payload.get("required_symbols")
            != ["WaapiClient", "WaapiRequestFailed"]
            or payload.get("current_interpreter")
            != str(Path(sys.executable).expanduser().resolve(strict=False))
            or payload.get("automatic_install_attempted") is not False
        ):
            raise CampaignEvidenceError(
                "heavy matrix passing live-preflight evidence is malformed"
            )
        return
    if state == "blocked":
        if (
            payload.get("contract") != HEAVY_V3_LIVE_PREFLIGHT_CONTRACT
            or payload.get("ok") is not False
        ):
            raise CampaignEvidenceError(
                "heavy matrix blocked live-preflight evidence is malformed"
            )
        return
    raise CampaignEvidenceError(
        "heavy matrix child ended without terminal live-preflight evidence"
    )


def _validate_heavy_v3_progress(
    progress: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
) -> None:
    expected = {
        "preflight": summary["preflight"],
        "attempted_unit_count": summary["attempted_unit_count"],
        "attempted_unit_ids": summary["attempted_unit_ids"],
        "pending_unit_ids": summary["pending_unit_ids"],
        "status_counts": summary["status_counts"],
        "stop_reason": summary["stop_reason"],
        "run_error_count": len(summary["run_errors"]),
    }
    if dict(progress) != expected:
        raise CampaignEvidenceError(
            "heavy matrix run-config progress differs from summary"
        )


def _validate_heavy_v3_matrix_case(
    value: Any,
    *,
    expected_unit: Any,
    expected_row: Mapping[str, Any],
    summary_row: Mapping[str, Any],
    scenario_root: Path,
    options: CampaignOptions,
) -> None:
    required_keys = {
        "contract",
        "status",
        "reason",
        "scenario_root",
        "runner_outcome",
    } | set(expected_row)
    if (
        not isinstance(value, Mapping)
        or set(value) != required_keys
        or value.get("contract") != matrix.HEAVY_V3_CASE_RECORD_CONTRACT
    ):
        raise CampaignEvidenceError("invalid heavy matrix-case contract")
    for key, expected_value in expected_row.items():
        if value.get(key) != expected_value:
            raise CampaignEvidenceError(f"heavy matrix-case mismatch for {key}")
    if value.get("scenario_root") != str(scenario_root):
        raise CampaignEvidenceError("heavy matrix-case scenario root is misbound")
    expected_summary_keys = {
        *expected_row,
        "status",
        "reason",
        "scenario_root",
    }
    expected_summary = {
        key: value.get(key)
        for key in expected_summary_keys
    }
    if dict(summary_row) != expected_summary:
        raise CampaignEvidenceError("heavy matrix-case differs from summary record")
    status = value.get("status")
    if status not in matrix.HEAVY_V3_STATUSES or not isinstance(value.get("reason"), str):
        raise CampaignEvidenceError("heavy matrix-case status/reason is malformed")
    outcome_path = scenario_root / "outcome.json"
    runner_outcome = value.get("runner_outcome")
    if runner_outcome is None:
        if status != "BLOCKED" or outcome_path.exists():
            raise CampaignEvidenceError(
                "runner-less matrix-case must be BLOCKED with no outcome file"
            )
        return
    if not isinstance(runner_outcome, Mapping):
        raise CampaignEvidenceError("heavy matrix-case runner outcome is malformed")
    outcome = load_strict_regular_json(outcome_path)
    if outcome != runner_outcome:
        raise CampaignEvidenceError("heavy outcome file differs from matrix-case")
    if value.get("runner") == "agent":
        _validate_business_agent_outcome(
            outcome,
            matrix_case=value,
            expected_unit=expected_unit,
            scenario_root=scenario_root,
            options=options,
        )
        return
    expected_outcome_keys = {
        "contract",
        "scenario_id",
        "version",
        "status",
        "reason",
        "scenario_root",
        "task_root",
        "thread_id",
        "checks",
        "lifecycle",
    }
    if not isinstance(outcome, Mapping) or set(outcome) != expected_outcome_keys:
        raise CampaignEvidenceError("heavy runner outcome has an invalid shape")
    for key in ("scenario_id", "version", "status", "reason", "scenario_root"):
        if outcome.get(key) != value.get(key):
            raise CampaignEvidenceError(f"heavy runner outcome mismatch for {key}")
    expected_contract = _heavy_v3_outcome_contract(
        str(value["runner"]),
        profile=options.profile,
    )
    if outcome.get("contract") != expected_contract:
        raise CampaignEvidenceError("heavy runner outcome contract mismatch")
    if not isinstance(outcome.get("checks"), Mapping):
        raise CampaignEvidenceError("heavy runner outcome checks are malformed")
    task_root = outcome.get("task_root")
    if task_root is not None and not _path_is_within(Path(task_root), scenario_root):
        raise CampaignEvidenceError("heavy runner task root escapes the scenario root")
    if status == "PASS":
        _validate_heavy_v3_pass_outcome(
            outcome,
            expected_unit=expected_unit,
            expected_row=expected_row,
            scenario_root=scenario_root,
            options=options,
        )
    elif outcome["checks"].get("codex_infrastructure_failure") is None:
        # A semantic FAIL, ordinary BLOCKED result, or INDETERMINATE mutation
        # still has to prove which reviewed request and business contract were
        # frozen before Codex ran.  Do not accept a failure label as a way to
        # bypass prompt provenance or the family-specific typed plan parser.
        # A runner-owned setup failure is the one exception: when it blocks
        # before prompt provenance, a business plan, or a Codex task exists,
        # there is no prompt-plan chain to re-read.  Validate that negative
        # boundary explicitly instead of treating the expected absence as
        # corrupt model evidence.
        # Codex infrastructure failures keep their stronger, partial-task
        # validation in _heavy_v3_retryable_infrastructure_category(), which
        # applies to both retryable and permanently blocked categories.
        if not _validate_heavy_v3_pre_materialization_block(
            outcome,
            scenario_root=scenario_root,
        ):
            _validate_heavy_v3_failure_prompt_plan(
                outcome,
                expected_unit=expected_unit,
                scenario_root=scenario_root,
                options=options,
            )


def _validate_business_agent_outcome(
    outcome: Mapping[str, Any],
    *,
    matrix_case: Mapping[str, Any],
    expected_unit: Any,
    scenario_root: Path,
    options: CampaignOptions,
) -> None:
    expected_keys = {
        "contract",
        "scenario_id",
        "version",
        "status",
        "reason",
        "thread_id",
        "gates",
        "command_count",
        "transaction_count",
        "production_gateway",
        "wwise_started",
        "final_response",
    }
    if set(outcome) != expected_keys:
        raise CampaignEvidenceError(
            "business Agent outcome schema is not closed"
        )
    for key in ("scenario_id", "version", "status", "reason"):
        if outcome.get(key) != matrix_case.get(key):
            raise CampaignEvidenceError(
                f"business Agent outcome mismatch for {key}"
            )
    profile = options.profile
    gates = outcome.get("gates")
    transaction_count = getattr(expected_unit, "transaction_count", None)
    if (
        outcome.get("contract") != BUSINESS_AGENT_OUTCOME_CONTRACTS.get(profile)
        or not isinstance(gates, Mapping)
        or not gates
        or any(type(value) is not bool for value in gates.values())
        or type(outcome.get("command_count")) is not int
        or outcome["command_count"] < 1
        or type(outcome.get("transaction_count")) is not int
        or outcome.get("transaction_count") != transaction_count
        or outcome.get("production_gateway") is not True
        or outcome.get("wwise_started") is not False
        or not isinstance(outcome.get("final_response"), str)
    ):
        raise CampaignEvidenceError(
            "business Agent outcome facts are malformed"
        )
    if outcome.get("status") == "PASS" and (
        not isinstance(outcome.get("thread_id"), str)
        or not outcome["thread_id"]
        or not all(gates.values())
    ):
        raise CampaignEvidenceError(
            "business Agent PASS lacks a fresh thread or passing gates"
        )

    evidence_root = _require_real_directory(
        scenario_root / "evidence",
        label="business Agent evidence root",
    )
    nested_outcome = load_strict_regular_json(evidence_root / "outcome.json")
    reconciliation = load_strict_regular_json(
        evidence_root / "broker-reconciliation.json"
    )
    broker = load_strict_regular_json(evidence_root / "broker-evidence.json")
    load_strict_regular_json(evidence_root / "codex-result-facts.json")
    if nested_outcome != outcome:
        raise CampaignEvidenceError(
            "business Agent nested outcome differs from scenario outcome"
        )
    if outcome.get("status") == "PASS" and (
        reconciliation.get("passed") is not True
        or broker.get("passed") is not True
        or broker.get("complete") is not True
        or not isinstance(broker.get("records"), list)
        or outcome.get("command_count") != len(broker["records"])
    ):
        raise CampaignEvidenceError(
            "business Agent PASS lacks complete Broker reconciliation"
        )
    if outcome.get("status") == "PASS":
        if profile == AUDIO_IMPORT_BUSINESS_PROFILE_ID:
            _validate_audio_import_business_agent_protocol(
                broker,
                expected_unit=expected_unit,
                scenario_root=scenario_root,
                protocol_manifest_revision=options.protocol_manifest_revision,
            )
        else:
            _validate_bound_business_agent_protocol(
                broker,
                expected_unit=expected_unit,
                profile=profile,
                scenario_root=scenario_root,
            )


def _validate_audio_import_business_agent_outcome(
    outcome: Mapping[str, Any],
    *,
    matrix_case: Mapping[str, Any],
    expected_unit: Any,
    scenario_root: Path,
    options: CampaignOptions,
) -> None:
    """Compatibility name retained for focused audio-import evidence tests."""

    _validate_business_agent_outcome(
        outcome,
        matrix_case=matrix_case,
        expected_unit=expected_unit,
        scenario_root=scenario_root,
        options=options,
    )


def _validate_bound_business_agent_protocol(
    broker: Mapping[str, Any],
    *,
    expected_unit: Any,
    profile: str,
    scenario_root: Path | None = None,
) -> None:
    """Rebuild one non-import Business Agent protocol from frozen suite facts."""

    if profile == matrix.OBJECT_LIFECYCLE_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_object_lifecycle_business_agent_runner import (
            build_preview_only_lifecycle_steps,
        )

        arguments: dict[str, Any] = {
            "object": {"kind": "path", "value": str(expected_unit.object["path"])}
        }
        if expected_unit.value is not None:
            arguments["value"] = expected_unit.value
        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": expected_unit.version,
            "operation": expected_unit.operation,
            "arguments": arguments,
        }
        steps = build_preview_only_lifecycle_steps(request)
        preview_request = _bind_business_request_paths(
            steps[-1].expected_operation_request,
            objects=(expected_unit.object,),
        )
    elif profile == matrix.OBJECT_METADATA_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_object_metadata_business_transaction_steps,
        )

        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": expected_unit.version,
            "operation": expected_unit.operation,
            "arguments": {
                "object": {"kind": "id", "value": str(expected_unit.source["id"])},
                "reference": expected_unit.native_reference,
                "target": {"kind": "id", "value": str(expected_unit.target["id"])},
            },
        }
        steps = build_object_metadata_business_transaction_steps(
            request,
            label="tx01",
            field_meaning=expected_unit.field_meaning,
            object_selector={
                "kind": "path",
                "value": str(expected_unit.source["path"]),
            },
            target_selector={
                "kind": "path",
                "value": str(expected_unit.target["path"]),
            },
            discover_before_target=True,
        )
        preview_request = request
    elif profile == matrix.OBJECT_GRAPH_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_object_graph_business_transaction_steps,
        )
        from tests.semantic.support.codex_object_graph_business_agent_runner import (
            object_graph_business_request,
        )

        request = object_graph_business_request(expected_unit)
        steps = build_object_graph_business_transaction_steps(
            request,
            label="tx01",
            parent_selector={
                "kind": "path",
                "value": str(expected_unit.parent["path"]),
            },
        )
        preview_request = request
    elif profile == matrix.SWITCH_ASSIGNMENT_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_switch_assignment_business_transaction_steps,
        )

        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": expected_unit.version,
            "operation": expected_unit.operation,
            "arguments": {
                role: {
                    "kind": "path",
                    "value": str(expected_unit.objects[role]["path"]),
                }
                for role in (
                    "switch_container",
                    "child",
                    "state_or_switch",
                )
            },
        }
        steps = build_switch_assignment_business_transaction_steps(
            request,
            label="tx01",
        )
        preview_request = _bind_business_request_paths(
            steps[-1].expected_operation_request,
            objects=tuple(expected_unit.objects.values()),
        )
    elif profile == matrix.CORE_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_core_business_transaction_steps,
        )

        steps = build_core_business_transaction_steps(
            api=expected_unit.operation,
            version=expected_unit.version,
            label="tx01",
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_project_setting_business_transaction_steps,
        )
        from tests.semantic.support.codex_project_setting_business_profile import (
            OBJECT_ID,
            OBJECT_NAME,
        )

        steps = build_project_setting_business_transaction_steps(
            version=expected_unit.version,
            label="tx01",
            object_id=OBJECT_ID,
            object_name=OBJECT_NAME,
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_runtime_control_business_transaction_steps,
        )

        steps = build_runtime_control_business_transaction_steps(
            version=expected_unit.version,
            label="tx01",
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.SOUNDENGINE_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_soundengine_business_transaction_steps,
        )
        from tests.semantic.support.codex_soundengine_business_profile import (
            EVENT_ID,
            EVENT_NAME,
            GAME_OBJECT_NAME,
            LISTENER_HANDLE,
            LISTENER_ID,
            MONITOR_MESSAGE,
        )

        steps = build_soundengine_business_transaction_steps(
            version=expected_unit.version,
            label="tx01",
            operation=expected_unit.operation,
            monitor_message=MONITOR_MESSAGE,
            game_object_name=GAME_OBJECT_NAME,
            event_id=EVENT_ID,
            event_name=EVENT_NAME,
            listener_handle=LISTENER_HANDLE,
            listener_id=LISTENER_ID,
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_cli_console_business_profile import (
            OUTPUT_DIRECTORY,
        )
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_cli_console_business_transaction_steps,
        )

        if scenario_root is None:
            raise CampaignEvidenceError(
                "CLI/Console Business Agent audit lacks its scenario root"
            )
        project_file = (
            scenario_root
            / "evidence"
            / "codex-task"
            / "runtime"
            / "project"
            / "SemanticProject.wproj"
        ).resolve(strict=True)
        steps = build_cli_console_business_transaction_steps(
            api=expected_unit.operation,
            version=expected_unit.version,
            label="tx01",
            project_file=str(project_file),
            output_directory=OUTPUT_DIRECTORY,
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_host_ui_debug_business_transaction_steps,
        )

        if scenario_root is None:
            raise CampaignEvidenceError(
                "host/UI/Debug Business Agent audit lacks its scenario root"
            )
        output_file = (
            scenario_root
            / "evidence"
            / "codex-task"
            / "runtime"
            / "output"
            / "FreshAgentTone.wav"
        ).resolve(strict=False)
        steps = build_host_ui_debug_business_transaction_steps(
            version=expected_unit.version,
            label="tx01",
            output_file=str(output_file),
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_compound_undo_business_agent_runner import (
            compound_undo_business_child_expectations,
        )
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_compound_undo_business_transaction_steps,
        )

        steps = build_compound_undo_business_transaction_steps(
            compound_undo_business_child_expectations(expected_unit),
            display_name=expected_unit.display_name,
            label="tx03",
        )
        preview_request = steps[-1].expected_operation_request
    elif profile == matrix.AUTHORING_UI_BUSINESS_PROFILE_ID:
        from tests.semantic.support.codex_eval_protocol_v3 import (
            build_authoring_ui_business_transaction_steps,
        )

        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": expected_unit.version,
            "operation": expected_unit.operation,
            "arguments": dict(expected_unit.request_arguments),
        }
        steps = build_authoring_ui_business_transaction_steps(
            request,
            label="tx01",
        )
        preview_request = request
    else:
        raise CampaignEvidenceError("unknown bound Business Agent profile")

    expected_names = tuple(step.name for step in steps)
    audited_steps = tuple(steps)
    optional_discovery_labels = {
        matrix.COMPOUND_UNDO_BUSINESS_PROFILE_ID: "tx03",
        matrix.CORE_BUSINESS_PROFILE_ID: "tx01",
        matrix.PROJECT_SETTING_BUSINESS_PROFILE_ID: "tx01",
        matrix.RUNTIME_CONTROL_BUSINESS_PROFILE_ID: "tx01",
        matrix.SOUNDENGINE_BUSINESS_PROFILE_ID: "tx01",
        matrix.CLI_CONSOLE_BUSINESS_PROFILE_ID: "tx01",
        matrix.HOST_UI_DEBUG_BUSINESS_PROFILE_ID: "tx01",
    }
    if profile in optional_discovery_labels:
        label = optional_discovery_labels[profile]
        optional_discovery = ExpectedGatewayStep(
            name=f"{label}.operations",
            subcommand="operations",
        )
        raw_expected_names = broker.get("expected_step_names")
        observed_expected_names = (
            tuple(raw_expected_names)
            if isinstance(raw_expected_names, list)
            else ()
        )
        if observed_expected_names == (optional_discovery.name, *expected_names):
            audited_steps = (optional_discovery, *audited_steps)
            expected_names = observed_expected_names
        elif observed_expected_names != expected_names:
            raise CampaignEvidenceError(
                "Business Agent Broker used an unreviewed discovery prefix"
            )
    consumed_names = broker.get("consumed_step_names")
    records = broker.get("records")
    if (
        broker.get("expected_step_names") != list(expected_names)
        or consumed_names != list(expected_names)
        or not isinstance(records, list)
        or len(records) != len(expected_names)
    ):
        raise CampaignEvidenceError("bound Business Agent Broker topology drifted")
    by_name = {
        str(record.get("step_name")): record
        for record in records
        if isinstance(record, Mapping)
    }
    if len(by_name) != len(expected_names):
        raise CampaignEvidenceError("bound Business Agent Broker step identity drifted")
    for step in audited_steps:
        record = by_name.get(step.name)
        arguments = record.get("gateway_arguments") if isinstance(record, Mapping) else None
        if (
            not isinstance(record, Mapping)
            or record.get("accepted") is not True
            or record.get("authenticated") is not True
            or record.get("succeeded") is not True
            or record.get("exit_code") != 0
            or not isinstance(arguments, list)
            or arguments[:1] != [step.subcommand]
            or (step.subcommand == "operations" and arguments != ["operations"])
        ):
            raise CampaignEvidenceError("bound Business Agent Broker record is not successful")
        if step.subcommand == "preview-from-draft":
            payload = record.get("payload")
            agent_result = payload.get("agent_result") if isinstance(payload, Mapping) else None
            observed_request = (
                agent_result.get("request")
                if isinstance(agent_result, Mapping)
                else None
            )
            register_soundengine = (
                profile == matrix.SOUNDENGINE_BUSINESS_PROFILE_ID
                and expected_unit.operation == "ak.soundengine.registerGameObj"
            )
            register_arguments = (
                observed_request.get("arguments")
                if isinstance(observed_request, Mapping)
                else None
            )
            register_args = (
                register_arguments.get("args")
                if isinstance(register_arguments, Mapping)
                else None
            )
            register_request_matches = bool(
                register_soundengine
                and isinstance(observed_request, Mapping)
                and observed_request.get("contract")
                == "waapi-skill.operation-request/v1"
                and observed_request.get("version") == expected_unit.version
                and observed_request.get("operation") == "waapi.call"
                and isinstance(register_arguments, Mapping)
                and register_arguments.get("api")
                == "ak.soundengine.registerGameObj"
                and register_arguments.get("options") == {}
                and isinstance(register_args, Mapping)
                and register_args.get("name") == "Fresh Weather Listener"
                and isinstance(register_args.get("gameObject"), int)
                and not isinstance(register_args.get("gameObject"), bool)
            ) if register_soundengine else False
            if not register_request_matches and observed_request != preview_request:
                raise CampaignEvidenceError("bound Business Agent Preview request drifted")


def _bind_business_request_paths(
    value: Any,
    *,
    objects: Sequence[Mapping[str, Any]],
) -> Any:
    path_to_id = {
        str(row["path"]): str(row["id"])
        for row in objects
        if isinstance(row.get("path"), str) and isinstance(row.get("id"), str)
    }

    def visit(item: Any) -> Any:
        if isinstance(item, Mapping):
            if item.get("kind") == "path" and item.get("value") in path_to_id:
                return {"kind": "id", "value": path_to_id[str(item["value"])]}
            return {str(key): visit(child) for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child) for child in item]
        return item

    return visit(value)


def _validate_audio_import_business_agent_protocol(
    broker: Mapping[str, Any],
    *,
    expected_unit: Any,
    scenario_root: Path,
    protocol_manifest_revision: str | None,
) -> None:
    """Rebuild the reviewed protocol and check its sealed Broker witnesses."""

    from tests.semantic.support.codex_import_business_agent_runner import (
        build_preview_only_business_steps,
        reconstruct_import_business_requests,
    )

    task_root = scenario_root / "evidence" / "codex-task"
    try:
        requests = reconstruct_import_business_requests(
            expected_unit,
            task_root / "runtime",
            require_media_files=True,
        )
        if protocol_manifest_revision == AUDIO_IMPORT_DERIVED_SFX_PROTOCOL_REVISION:
            provenance = load_strict_regular_json(
                scenario_root / "evidence" / HEAVY_V3_PROMPT_PROVENANCE_FILE
            )
            raw_protocol = provenance.get("protocol")
            protocol_value = (
                raw_protocol.get("value")
                if isinstance(raw_protocol, Mapping)
                else None
            )
            if not isinstance(protocol_value, Mapping):
                raise PromptProvenanceError(
                    "legacy audio import evidence lacks its sealed protocol"
                )
            canonical = _canonicalize_legacy_protocol_manifest(
                protocol_value,
                protocol_manifest_revision=protocol_manifest_revision,
            )
            protocol = deserialize_protocol(canonical)
            steps = protocol.steps
        else:
            steps = build_preview_only_business_steps(requests)
            protocol = V3GatewayProtocol(
                steps=steps,
                turn_prefix_counts=(len(steps),),
            )
    except (OSError, TypeError, ValueError, V3ProtocolError) as exc:
        raise CampaignEvidenceError(
            "audio import business sealed protocol cannot be reconstructed"
        ) from exc
    except PromptProvenanceError as exc:
        raise CampaignEvidenceError(str(exc)) from exc

    if protocol_manifest_revision == AUDIO_IMPORT_DERIVED_SFX_PROTOCOL_REVISION:
        preview_steps = tuple(
            step
            for step in steps
            if step.subcommand == "preview-from-draft"
            and isinstance(step.expected_operation_request, Mapping)
            and step.expected_operation_request.get("operation") == "audio.import"
        )
        if len(preview_steps) != len(requests):
            raise CampaignEvidenceError(
                "legacy audio import protocol transaction count drifted"
            )
    elif protocol_manifest_revision != _CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION:
        raise CampaignEvidenceError(
            "audio import business protocol revision is unreviewed"
        )

    expected_names = tuple(step.name for step in steps)
    consumed_names = broker.get("consumed_step_names")
    if (
        broker.get("expected_step_names") != list(expected_names)
        or not isinstance(consumed_names, list)
        or len(consumed_names) != len(expected_names)
        or len(set(consumed_names)) != len(consumed_names)
        or set(consumed_names) != set(expected_names)
    ):
        raise CampaignEvidenceError(
            "audio import business sealed Broker topology is inconsistent"
        )
    records = broker.get("records")
    if not isinstance(records, list) or len(records) != len(expected_names):
        raise CampaignEvidenceError(
            "audio import business sealed Broker records are incomplete"
        )
    by_name: dict[str, Mapping[str, Any]] = {}
    for record in records:
        name = record.get("step_name") if isinstance(record, Mapping) else None
        if not isinstance(name, str) or name in by_name:
            raise CampaignEvidenceError(
                "audio import business sealed Broker step identity is invalid"
            )
        by_name[name] = record
    for step in steps:
        record = by_name.get(step.name)
        arguments = record.get("gateway_arguments") if record is not None else None
        if (
            record is None
            or record.get("accepted") is not True
            or record.get("authenticated") is not True
            or record.get("succeeded") is not True
            or record.get("exit_code") != 0
            or not isinstance(arguments, list)
            or not arguments
            or arguments[0] != step.subcommand
        ):
            raise CampaignEvidenceError(
                "audio import business sealed Broker record is not successful"
            )
        if step.subcommand in {"draft-declare-new", "draft-declare-existing"}:
            _validate_audio_import_business_declaration_language(step, arguments)
        if step.subcommand == "preview-from-draft":
            payload = record.get("payload")
            agent_result = (
                payload.get("agent_result")
                if isinstance(payload, Mapping)
                else None
            )
            request = (
                agent_result.get("request")
                if isinstance(agent_result, Mapping)
                else None
            )
            expected_request = _bind_audio_import_request_paths(
                step.expected_operation_request,
                objects=getattr(expected_unit, "objects", ()),
            )
            if request != expected_request:
                raise CampaignEvidenceError(
                    "audio import business sealed Preview request witness drifted"
                )


def _validate_audio_import_business_declaration_language(
    step: Any,
    arguments: Sequence[Any],
) -> None:
    values = tuple(str(value) for value in arguments)
    language_values = tuple(
        values[index + 2]
        for index, value in enumerate(values[:-2])
        if value == "--field" and values[index + 1] == "language"
    )
    if len(language_values) > 1 or any(
        value != "SFX" for value in language_values
    ):
        raise CampaignEvidenceError(
            "audio import business derived SFX declaration is contradictory"
        )
    if language_values and not step.allow_explicit_derived_sfx_language:
        raise CampaignEvidenceError(
            "audio import business declaration added an unreviewed SFX language"
        )


def _bind_audio_import_request_paths(
    value: Any,
    *,
    objects: Sequence[Any],
) -> Any:
    path_to_id = {
        str(row["path"]): str(row["id"])
        for row in objects
        if isinstance(row, Mapping)
        and isinstance(row.get("path"), str)
        and isinstance(row.get("id"), str)
    }

    def visit(item: Any) -> Any:
        if isinstance(item, Mapping):
            if (
                item.get("kind") == "path"
                and isinstance(item.get("value"), str)
                and item["value"] in path_to_id
            ):
                return {"kind": "id", "value": path_to_id[item["value"]]}
            return {str(key): visit(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [visit(nested) for nested in item]
        return item

    return visit(value)


def _validate_heavy_v3_pre_materialization_block(
    outcome: Mapping[str, Any],
    *,
    scenario_root: Path,
) -> bool:
    """Accept only a proven runner block that predates all prompt/model evidence."""

    if (
        outcome.get("status") != "BLOCKED"
        or outcome.get("task_root") is not None
        or outcome.get("thread_id") is not None
    ):
        return False
    checks = outcome.get("checks")
    reason = outcome.get("reason")
    if (
        not isinstance(checks, Mapping)
        or not isinstance(reason, str)
        or not reason
        or checks.get("exception") != reason
        or checks.get("failure_classification") != "BLOCKED"
    ):
        raise CampaignEvidenceError(
            "pre-materialization heavy block lacks its exact runner exception"
        )

    evidence_root = scenario_root / "evidence"
    _require_real_directory(
        evidence_root,
        label="pre-materialization heavy evidence root",
    )
    if any(
        os.path.lexists(path)
        for path in (
            evidence_root / "codex-task",
            evidence_root / HEAVY_V3_PROMPT_PROVENANCE_FILE,
            evidence_root / BUSINESS_ORACLE_PLAN_FILE,
        )
    ):
        raise CampaignEvidenceError(
            "pre-materialization heavy block contradicts prompt or plan evidence"
        )
    return True


def _validate_heavy_v3_failure_prompt_plan(
    outcome: Mapping[str, Any],
    *,
    expected_unit: Any,
    scenario_root: Path,
    options: CampaignOptions,
) -> HeavyV3PromptEvidence:
    """Re-read the immutable prompt/common/typed plan chain for a failed case."""

    task_root_value = outcome.get("task_root")
    if not isinstance(task_root_value, str) or not task_root_value:
        raise CampaignEvidenceError(
            "failed heavy outcome has no frozen prompt-plan task root"
        )
    task_root = Path(task_root_value)
    evidence_root = scenario_root / "evidence"
    expected_task_root = evidence_root / "codex-task"
    resolved_task_root = _require_real_directory(
        task_root,
        label="failed heavy prompt-plan task root",
    )
    resolved_expected_root = _require_real_directory(
        expected_task_root,
        label="failed heavy fixed evidence task root",
    )
    _require_real_directory(
        evidence_root,
        label="failed heavy evidence root",
    )
    if (
        not task_root.is_absolute()
        or resolved_task_root != resolved_expected_root
    ):
        raise CampaignEvidenceError(
            "failed heavy prompt-plan task root is not the fixed real evidence path"
        )

    receipt_path = task_root / HEAVY_V3_PROMPT_MATERIALIZATION_FILE
    raw_receipt = _load_strict_regular_text(receipt_path)
    receipt_sha256 = hashlib.sha256(raw_receipt.encode("utf-8")).hexdigest()
    return _validate_heavy_v3_prompt_materialization(
        task_root,
        scenario_root=scenario_root,
        expected_unit=expected_unit,
        expected_sha256=receipt_sha256,
        protocol_manifest_revision=options.protocol_manifest_revision,
    )


def _heavy_v3_retryable_infrastructure_category(
    matrix_case: Mapping[str, Any],
    *,
    scenario_root: Path,
    expected_unit: Any,
    options: CampaignOptions,
) -> str | None:
    """Return a proven pre-agent retry category from one blocked heavy case.

    The matrix/lifecycle layer continues to classify the stopped case as
    ``BLOCKED`` and quarantine its owned state.  Only this campaign evidence
    layer may reinterpret a closed, runner-authored Codex infrastructure record
    as ``RETRYABLE``.  Cleanup or source-project uncertainty always fails
    closed and never becomes resumable.
    """

    outcome = matrix_case.get("runner_outcome")
    if not isinstance(outcome, Mapping):
        return None
    checks = outcome.get("checks")
    if not isinstance(checks, Mapping):
        return None
    failure = checks.get("codex_infrastructure_failure")
    if failure is None:
        return None
    required_failure_keys = {
        "category",
        "turn_failed",
        "timed_out",
        "agent_item_event_count",
    }
    if not isinstance(failure, Mapping) or set(failure) != required_failure_keys:
        raise CampaignEvidenceError(
            "heavy Codex infrastructure evidence has an invalid shape"
        )
    category = failure.get("category")
    if (
        not isinstance(category, str)
        or category not in _HEAVY_V3_CODEX_INFRASTRUCTURE_CATEGORIES
    ):
        raise CampaignEvidenceError(
            "heavy Codex infrastructure evidence has an unknown category"
        )
    if (
        type(failure.get("turn_failed")) is not bool
        or type(failure.get("timed_out")) is not bool
        or type(failure.get("agent_item_event_count")) is not int
        or failure.get("agent_item_event_count") != 0
    ):
        raise CampaignEvidenceError(
            "heavy Codex infrastructure evidence does not prove pre-agent failure"
        )
    if (
        category == "timeout_before_agent_action"
        and failure.get("timed_out") is not True
    ) or (
        category == "turn_failed_before_agent_action"
        and (
            failure.get("turn_failed") is not True
            or failure.get("timed_out") is not False
        )
    ):
        raise CampaignEvidenceError(
            "heavy Codex infrastructure category contradicts its typed flags"
        )
    reason_prefix = (
        "CodexInfrastructureError: Codex CLI infrastructure failure "
        f"({category}):"
    )
    if (
        matrix_case.get("status") != "BLOCKED"
        or outcome.get("status") != "BLOCKED"
        or checks.get("failure_classification") != "BLOCKED"
        or outcome.get("thread_id") is not None
        or not isinstance(outcome.get("reason"), str)
        or not str(outcome.get("reason")).startswith(reason_prefix)
    ):
        raise CampaignEvidenceError(
            "heavy Codex infrastructure evidence contradicts the blocked outcome"
        )
    _validate_heavy_v3_retryable_task_failure(
        outcome,
        failure=failure,
        scenario_root=scenario_root,
        expected_unit=expected_unit,
        options=options,
    )
    if category in BLOCKED_INFRASTRUCTURE_CATEGORIES:
        return None
    _validate_heavy_v3_retryable_lifecycle(
        outcome,
        scenario_root=scenario_root,
        runner=str(matrix_case.get("runner")),
    )
    return category


def _validate_heavy_v3_retryable_task_failure(
    outcome: Mapping[str, Any],
    *,
    failure: Mapping[str, Any],
    scenario_root: Path,
    expected_unit: Any,
    options: CampaignOptions,
) -> None:
    """Validate the failed turn, every prior turn, and the stopped broker prefix."""

    task_root = scenario_root / "evidence" / "codex-task"
    if outcome.get("task_root") != str(task_root):
        raise CampaignEvidenceError(
            "retryable heavy Codex failure lacks its fixed task evidence root"
        )
    _require_real_directory(
        task_root,
        label="retryable heavy fixed task evidence root",
    )
    if os.path.lexists(task_root / "task-result.json"):
        raise CampaignEvidenceError(
            "retryable heavy task cannot coexist with a completed task result"
        )
    sidecar = load_strict_regular_json(task_root / "infrastructure-failure.json")
    sidecar_keys = {
        "contract",
        "scenario_id",
        "version",
        "failed_turn_index",
        "expected_turn_count",
        "prior_completed_turn_count",
        "previous_broker_prefix",
        "expected_failed_turn_prefix",
        "prior_thread_id",
        "prompt_sha256",
        "failure",
        "artifact_sha256",
    }
    expected_turn_count = getattr(expected_unit, "user_turn_count", None)
    failed_turn_index = sidecar.get("failed_turn_index") if isinstance(sidecar, Mapping) else None
    prior_turn_count = (
        sidecar.get("prior_completed_turn_count")
        if isinstance(sidecar, Mapping)
        else None
    )
    previous_prefix = (
        sidecar.get("previous_broker_prefix")
        if isinstance(sidecar, Mapping)
        else None
    )
    failed_prefix = (
        sidecar.get("expected_failed_turn_prefix")
        if isinstance(sidecar, Mapping)
        else None
    )
    prior_thread_id = sidecar.get("prior_thread_id") if isinstance(sidecar, Mapping) else None
    optional_policy_protocol = (
        getattr(expected_unit, "project_modification_policy", None)
        == "read_only"
    )
    if (
        not isinstance(sidecar, Mapping)
        or set(sidecar) != sidecar_keys
        or sidecar.get("contract")
        != HEAVY_V3_TASK_INFRASTRUCTURE_FAILURE_CONTRACT
        or sidecar.get("scenario_id")
        != _heavy_v3_base_scenario_id(expected_unit)
        or sidecar.get("version") != outcome.get("version")
        or sidecar.get("version") != getattr(expected_unit, "version", None)
        or type(expected_turn_count) is not int
        or expected_turn_count < 1
        or sidecar.get("expected_turn_count") != expected_turn_count
        or type(failed_turn_index) is not int
        or not 1 <= failed_turn_index <= expected_turn_count
        or type(prior_turn_count) is not int
        or prior_turn_count != failed_turn_index - 1
        or type(previous_prefix) is not int
        or previous_prefix < 0
        or type(failed_prefix) is not int
        or (
            failed_prefix < previous_prefix
            if optional_policy_protocol
            else failed_prefix <= previous_prefix
        )
        or sidecar.get("failure") != dict(failure)
        or not isinstance(sidecar.get("prompt_sha256"), str)
        or _SHA256_RE.fullmatch(str(sidecar.get("prompt_sha256"))) is None
        or (
            prior_turn_count == 0
            and prior_thread_id is not None
        )
        or (
            prior_turn_count > 0
            and (not isinstance(prior_thread_id, str) or not prior_thread_id)
        )
    ):
        raise CampaignEvidenceError(
            "retryable heavy task infrastructure sidecar is misbound"
        )

    failed_turn_root = task_root / "turns" / f"turn-{failed_turn_index:02d}"
    expected_artifacts = {
        HEAVY_V3_PROMPT_MATERIALIZATION_FILE,
        f"turns/turn-{failed_turn_index:02d}/prompt.txt",
        f"turns/turn-{failed_turn_index:02d}/events.jsonl",
        f"turns/turn-{failed_turn_index:02d}/stderr.txt",
        f"turns/turn-{failed_turn_index:02d}/final.txt",
        f"turns/turn-{failed_turn_index:02d}/codex-facts.json",
        "broker-evidence.json",
    }
    artifact_sha256 = sidecar.get("artifact_sha256")
    if (
        not isinstance(artifact_sha256, Mapping)
        or set(artifact_sha256) != expected_artifacts
    ):
        raise CampaignEvidenceError(
            "retryable heavy task artifact digest set is incomplete"
        )
    for relative, digest in artifact_sha256.items():
        artifact = task_root / str(relative)
        if (
            not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or hashlib.sha256(
                _load_strict_regular_text(artifact).encode("utf-8")
            ).hexdigest()
            != digest
        ):
            raise CampaignEvidenceError(
                "retryable heavy task artifact digest is invalid"
            )

    prompt_evidence = _validate_heavy_v3_prompt_materialization(
        task_root,
        scenario_root=scenario_root,
        expected_unit=expected_unit,
        expected_sha256=str(
            artifact_sha256[HEAVY_V3_PROMPT_MATERIALIZATION_FILE]
        ),
        protocol_manifest_revision=options.protocol_manifest_revision,
    )
    expected_prompts = prompt_evidence.prompts
    protocol = prompt_evidence.provenance.protocol
    expected_skill_reads = _heavy_v3_expected_skill_reads(expected_unit)

    prompt = _load_strict_regular_text(failed_turn_root / "prompt.txt")
    if (
        not prompt.endswith("\n")
        or not prompt[:-1]
        or hashlib.sha256(prompt[:-1].encode("utf-8")).hexdigest()
        != sidecar.get("prompt_sha256")
        or prompt[:-1] != expected_prompts[failed_turn_index - 1]
    ):
        raise CampaignEvidenceError(
            "retryable heavy failed-turn prompt digest is invalid"
        )
    if _load_strict_regular_text(failed_turn_root / "final.txt") != "\n":
        raise CampaignEvidenceError(
            "retryable heavy failed turn unexpectedly has a final response"
        )
    _load_strict_regular_text(failed_turn_root / "events.jsonl")
    _load_strict_regular_text(failed_turn_root / "stderr.txt")
    failed_facts = load_strict_regular_json(failed_turn_root / "codex-facts.json")
    _validate_heavy_v3_retryable_failed_facts(
        failed_facts,
        failure=failure,
        prior_thread_id=prior_thread_id,
        expected_prompt=expected_prompts[failed_turn_index - 1],
        turn_index=failed_turn_index,
        task_root=task_root,
        turn_root=failed_turn_root,
        options=options,
        expected_skill_read_schedule=expected_skill_reads,
    )

    turns_root = task_root / "turns"
    expected_turn_directories = {
        f"turn-{index:02d}" for index in range(1, failed_turn_index + 1)
    }
    if _strict_real_subdirectory_names(turns_root) != expected_turn_directories:
        raise CampaignEvidenceError(
            "retryable heavy partial task has unexpected turn directories"
        )
    prior_prefixes: list[int] = []
    prior_gateway_records: list[Mapping[str, Any]] = []
    previous_validated_prefix = 0
    for index in range(1, prior_turn_count + 1):
        turn_root = turns_root / f"turn-{index:02d}"
        grade = load_strict_regular_json(turn_root / "turn-grade.json")
        expected_prefix = (
            grade.get("broker_prefix_count")
            if protocol.allowed_turn_prefix_counts
            and isinstance(grade, Mapping)
            else protocol.turn_prefix_counts[index - 1]
        )
        if (
            type(expected_prefix) is not int
            or expected_prefix
            not in protocol.allowed_prefixes_for_turn(index)
            or expected_prefix < previous_validated_prefix
        ):
            raise CampaignEvidenceError(
                "retryable heavy prior turn has an invalid optional prefix"
            )
        turn_gateway_records = _validate_heavy_v3_turn_grade(
            grade,
            index=index,
            turn_root=turn_root,
            expected_thread_id=str(prior_thread_id),
            expected_prompt=expected_prompts[index - 1],
            task_root=task_root,
            options=options,
            previous_broker_prefix=previous_validated_prefix,
            expected_broker_prefix=expected_prefix,
            expected_steps=protocol.steps[previous_validated_prefix:expected_prefix],
            version=str(getattr(expected_unit, "version", "")),
            expected_skill_reads=expected_skill_reads[index - 1],
            expected_skill_read_schedule=expected_skill_reads,
            prompt_provenance=prompt_evidence.provenance,
        )
        prior_gateway_records.extend(turn_gateway_records)
        if len(prior_gateway_records) != expected_prefix:
            raise CampaignEvidenceError(
                "retryable heavy turn command allocation differs from its broker prefix"
            )
        previous_validated_prefix = expected_prefix
        prefix = grade.get("broker_prefix_count")
        if type(prefix) is not int:
            raise CampaignEvidenceError(
                "retryable heavy prior turn broker prefix is malformed"
            )
        prior_prefixes.append(prefix)
    if (
        (
            prior_prefixes != sorted(prior_prefixes)
            if protocol.allowed_turn_prefix_counts
            else prior_prefixes != sorted(set(prior_prefixes))
        )
        or (prior_prefixes[-1] if prior_prefixes else 0) != previous_prefix
    ):
        raise CampaignEvidenceError(
            "retryable heavy prior turns do not bind the stopped broker prefix"
        )

    broker = load_strict_regular_json(task_root / "broker-evidence.json")
    expected_previous_prefix = (
        0
        if failed_turn_index == 1
        else prior_prefixes[-1]
    )
    expected_failed_prefix = protocol.turn_prefix_counts[failed_turn_index - 1]
    if (
        previous_prefix != expected_previous_prefix
        or failed_prefix != expected_failed_prefix
    ):
        raise CampaignEvidenceError(
            "retryable heavy broker prefixes differ from sealed turn boundaries"
        )
    _validate_heavy_v3_retryable_partial_broker(
        broker,
        task_root=task_root,
        previous_prefix=previous_prefix,
        failed_prefix=failed_prefix,
        protocol=protocol,
        command_records=tuple(prior_gateway_records),
        options=options,
        version=str(getattr(expected_unit, "version", "")),
        expected_project_modification_policy=getattr(
            expected_unit,
            "project_modification_policy",
            None,
        ),
    )


def _validate_heavy_v3_retryable_failed_facts(
    value: Any,
    *,
    failure: Mapping[str, Any],
    prior_thread_id: Any,
    expected_prompt: str,
    turn_index: int,
    task_root: Path,
    turn_root: Path,
    options: CampaignOptions,
    expected_skill_read_schedule: Sequence[Sequence[str]],
) -> None:
    required_keys = {
        "command",
        "exit_status",
        "duration_seconds",
        "timed_out",
        "thread_id",
        "final_response",
        "usage",
        "event_count",
        "collab_call_count",
        "file_change_count",
        "prompt_audit",
        "isolation_audit",
        "session_audit",
        "command_facts",
        "created_files",
        "modified_files",
        "deleted_files",
        "created_source_files",
        "modified_source_files",
        "deleted_source_files",
        "skill_tree_sha256_before",
        "skill_tree_sha256_after",
        "skill_tree_unchanged",
    }
    if not isinstance(value, Mapping) or set(value) != required_keys:
        raise CampaignEvidenceError(
            "retryable heavy failed-turn Codex facts have an invalid shape"
        )
    events_path = turn_root / "events.jsonl"
    _validate_heavy_v3_events_against_facts(
        events_path,
        value,
        label="retryable heavy failed turn",
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    events_text = _load_strict_regular_text(events_path)
    stderr = _load_strict_regular_text(turn_root / "stderr.txt")
    reconstructed_failure = classify_codex_infrastructure_failure(
        parse_jsonl_events(events_text),
        stderr=stderr,
        timed_out=value.get("timed_out") is True,
    )
    reconstructed_failure_row = (
        {
            "category": reconstructed_failure.category,
            "turn_failed": reconstructed_failure.turn_failed,
            "timed_out": reconstructed_failure.timed_out,
            "agent_item_event_count": reconstructed_failure.agent_item_event_count,
        }
        if reconstructed_failure is not None
        else None
    )
    if reconstructed_failure_row != dict(failure):
        raise CampaignEvidenceError(
            "retryable heavy infrastructure category cannot be reconstructed "
            "from events.jsonl and stderr.txt"
        )
    prompt_audit = value.get("prompt_audit")
    isolation_audit = value.get("isolation_audit")
    session_audit = value.get("session_audit")
    command_facts = value.get("command_facts")
    thread_id = value.get("thread_id")
    if (
        type(value.get("exit_status")) is not int
        or value.get("exit_status") == 0
        or value.get("timed_out") is not failure.get("timed_out")
        or value.get("final_response") != ""
        or value.get("collab_call_count") != 0
        or value.get("file_change_count") != 0
        or value.get("skill_tree_unchanged") is not True
        or not isinstance(value.get("skill_tree_sha256_before"), str)
        or _SHA256_RE.fullmatch(str(value.get("skill_tree_sha256_before"))) is None
        or value.get("skill_tree_sha256_before")
        != value.get("skill_tree_sha256_after")
        or not isinstance(prompt_audit, Mapping)
        or prompt_audit.get("passed") is not True
        or prompt_audit.get("has_memory") is not False
        # prompt_audit hashes Codex's serialized prompt-input payload.  The
        # runner-owned materialization archive binds the raw prompt instead.
        or not isinstance(prompt_audit.get("prompt_sha256"), str)
        or _SHA256_RE.fullmatch(str(prompt_audit.get("prompt_sha256"))) is None
        or not isinstance(isolation_audit, Mapping)
        or isolation_audit.get("passed") is not True
        or not isinstance(session_audit, Mapping)
        or session_audit.get("collab_call_count") != 0
        or session_audit.get("file_change_count") != 0
        or session_audit.get("command_started_count") != 0
        or session_audit.get("command_completed_count") != 0
        or session_audit.get("incomplete_command_count") != 0
        or session_audit.get("unexpected_item_types") != []
        or session_audit.get("invalid_json_line_count") != 0
        or not isinstance(command_facts, Mapping)
        or command_facts.get("skill_read") is not False
        or command_facts.get("gateway_before_discovery") is not False
        or (
            thread_id not in {"", prior_thread_id}
            if prior_thread_id is not None
            else not isinstance(thread_id, str)
        )
    ):
        raise CampaignEvidenceError(
            "retryable heavy failed-turn facts do not prove no agent action"
        )
    config = CodexHarnessConfig(
        workspace=task_root / "agent-workspace",
        skill_source=options.skill_source,
        codex_binary=options.codex_binary,
        windows_powershell_core_host=options.windows_powershell_core_host,
        auth_json=options.auth_json,
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier,
        timeout_seconds=options.timeout_seconds,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        developer_instructions=(
            semantic_task_developer_instructions(
                options.skill_source / "scripts" / "run.py",
                task_skill_source=(
                    task_root
                    / "agent-workspace"
                    / ".agents"
                    / "skills"
                    / "waapi-skill"
                ),
                expected_skill_reads=expected_skill_read_schedule,
                base_developer_instructions=(
                    semantic_skill_bootstrap_developer_instructions(
                        options.skill_source / "scripts" / "run.py"
                    )
                ),
            )
            if options.profile in SEMANTIC_BOOTSTRAP_PROFILE_IDS
            else ""
        ),
    )
    expected_command = (
        build_task_exec_command(
            config,
            prompt=expected_prompt,
            writable_dir=turn_root,
        )
        if turn_index == 1
        else build_task_resume_command(
            config,
            thread_id=str(prior_thread_id),
            prompt=expected_prompt,
            writable_dir=turn_root,
        )
    )
    if value.get("command") != expected_command:
        raise CampaignEvidenceError(
            "retryable heavy failed turn used the wrong initial/resume argv"
        )
    for key in (
        "created_files",
        "modified_files",
        "deleted_files",
        "created_source_files",
        "modified_source_files",
        "deleted_source_files",
    ):
        if value.get(key) != []:
            raise CampaignEvidenceError(
                f"retryable heavy failed turn unexpectedly records {key}"
            )
    for key in (
        "commands",
        "inline_python_commands",
        "direct_waapi_client_commands",
        "write_like_commands",
        "gateway_commands",
        "discovery_commands",
        "command_records",
        "gateway_attempt_commands",
        "gateway_subcommands",
        "gateway_results",
        "gateway_evidence_apis",
        "allowed_read_commands",
        "skill_read_files",
        "unexpected_commands",
        "non_gateway_unexpected_commands",
    ):
        if command_facts.get(key) != []:
            raise CampaignEvidenceError(
                f"retryable heavy failed turn unexpectedly records command facts: {key}"
            )


def _steps_in_consumed_order(
    canonical_steps: Sequence[Any],
    consumed_names: Sequence[str],
) -> tuple[Any, ...]:
    """Resolve one validated linearization and rebind its revision chain."""

    by_name = {step.name: step for step in canonical_steps}
    if (
        len(by_name) != len(canonical_steps)
        or len(consumed_names) != len(canonical_steps)
        or any(name not in by_name for name in consumed_names)
    ):
        raise CampaignEvidenceError(
            "broker consumed names cannot linearize the sealed protocol"
        )
    ordered = [by_name[name] for name in consumed_names]
    latest_revision_step: str | None = None
    rebound: list[Any] = []
    for step in ordered:
        if step.subcommand == "draft-start":
            latest_revision_step = step.name
        elif step.subcommand == "draft-inspect":
            if latest_revision_step is None:
                raise CampaignEvidenceError(
                    "consumed Draft inspect precedes draft-start"
                )
            latest_revision_step = step.name
        elif step.subcommand in DRAFT_REVISION_SUBCOMMANDS:
            if latest_revision_step is None:
                raise CampaignEvidenceError(
                    "consumed Draft mutation precedes draft-start"
                )
            arguments = list(step.arguments)
            if (
                len(arguments) < 5
                or arguments[3] != "--expected-revision"
                or not isinstance(arguments[4], ResponseBinding)
            ):
                raise CampaignEvidenceError(
                    "consumed Draft step has no sealed revision binding"
                )
            arguments[4] = ResponseBinding(
                latest_revision_step,
                "/draft/revision",
            )
            step = replace(step, arguments=tuple(arguments))
            latest_revision_step = step.name
        rebound.append(step)
    return tuple(rebound)


def _build_heavy_v3_broker_replay(
    *,
    skill_source: Path,
    invocation_skill_source: Path,
    canonical_steps: Sequence[Any],
    execution_steps: Sequence[Any],
    commutative_read_only_step_groups: Sequence[Sequence[str]],
    commutative_composer_setup_step_groups: Sequence[Sequence[str]],
    expected_wwise_version: str,
    project_modification_policy: str,
    existing_state_directory: Path | None = None,
) -> CodexGatewayBroker:
    """Build an offline replay from canonical policy and observed order.

    The Broker validates protocol topology from the canonical order.  Archived
    payload and response bindings must instead replay in the one declared
    linearization that actually ran.  Keeping these two orders separate avoids
    treating dependency-safe Composer setup as an arbitrary Gateway
    interruption.
    """

    canonical = tuple(canonical_steps)
    execution = tuple(execution_steps)
    canonical_names = tuple(step.name for step in canonical)
    execution_names = tuple(step.name for step in execution)
    if not gateway_step_sequence_matches(
        canonical_names,
        execution_names,
        commutative_read_only_step_groups,
        commutative_composer_setup_step_groups,
    ):
        raise CampaignEvidenceError(
            "archived broker uses an undeclared protocol linearization"
        )

    present_names = set(canonical_names)
    replay_read_only_groups = tuple(
        tuple(group)
        for group in commutative_read_only_step_groups
        if all(name in present_names for name in group)
    )
    replay_setup_groups: list[tuple[str, ...]] = []
    for raw_group in commutative_composer_setup_step_groups:
        group = tuple(raw_group)
        present_prefix = tuple(name for name in group if name in present_names)
        if present_prefix != group[: len(present_prefix)]:
            raise CampaignEvidenceError(
                "archived broker Composer setup prefix is malformed"
            )
        if len(present_prefix) >= 2:
            replay_setup_groups.append(present_prefix)

    offline_replay_preview_requests: dict[str, Mapping[str, Any]] = {}
    for start_index, step in enumerate(execution):
        if (
            step.subcommand != "draft-start"
            or not step.arguments
            or step.arguments[0]
            not in {
                "audio.import",
                "lua.executeCliFile",
                "lua.executeCoreFile",
                "lua.executeCoreInline",
            }
        ):
            continue
        next_start_index = next(
            (
                index
                for index in range(start_index + 1, len(execution))
                if execution[index].subcommand == "draft-start"
            ),
            len(execution),
        )
        preview_index = next(
            (
                index
                for index in range(start_index + 1, next_start_index)
                if execution[index].subcommand == "preview-from-draft"
            ),
            None,
        )
        if preview_index is None:
            continue
        segment = V3GatewayProtocol(
            steps=execution[start_index : preview_index + 1],
            turn_prefix_counts=(preview_index - start_index + 1,),
        )
        for pointer, request in materialize_typed_transaction_protocol_requests(
            segment,
            version=expected_wwise_version,
            allow_cleaned_file_evidence=True,
        ):
            offline_replay_preview_requests[pointer.rsplit("/", 1)[-1]] = request

    replay = CodexGatewayBroker(
        skill_source=skill_source,
        invocation_skill_source=invocation_skill_source,
        expected_steps=canonical,
        commutative_read_only_step_groups=replay_read_only_groups,
        commutative_composer_setup_step_groups=tuple(replay_setup_groups),
        expected_wwise_version=expected_wwise_version,
        project_modification_policy=project_modification_policy,
        runner_environment={},
        existing_state_directory=existing_state_directory,
        offline_replay_preview_requests=offline_replay_preview_requests,
    )
    # Offline replay never starts the Broker.  Its Draft payload validator must
    # follow the archived dependency-valid order and its rebound revision chain.
    replay._execution_steps = list(execution)  # noqa: SLF001
    return replay


def _validate_heavy_v3_retryable_partial_broker(
    value: Any,
    *,
    task_root: Path,
    previous_prefix: int,
    failed_prefix: int,
    protocol: Any,
    command_records: Sequence[Mapping[str, Any]],
    options: CampaignOptions,
    version: str,
    expected_project_modification_policy: str | None = None,
) -> None:
    top_keys = {
        "expected_step_names",
        "consumed_step_names",
        "records",
        "state_directory",
        "evidence_directory",
        "runner_path",
        "terminal_state",
        "complete",
        "passed",
    }
    expected_groups = [
        list(group)
        for group in getattr(
            protocol,
            "commutative_read_only_step_groups",
            (),
        )
    ]
    if expected_groups:
        top_keys.add("commutative_read_only_step_groups")
    expected_setup_groups = [
        list(group)
        for group in getattr(
            protocol,
            "commutative_composer_setup_step_groups",
            (),
        )
    ]
    if expected_setup_groups:
        top_keys.add("commutative_composer_setup_step_groups")
    if not isinstance(value, Mapping) or set(value) != top_keys:
        raise CampaignEvidenceError(
            "retryable heavy partial broker evidence has an invalid shape"
        )
    expected_names = [step.name for step in protocol.steps]
    consumed_names = value.get("consumed_step_names")
    records = value.get("records")
    completed_before_failed_turn = (
        bool(getattr(protocol, "allowed_turn_prefix_counts", ()))
        and previous_prefix == len(expected_names)
        and failed_prefix == previous_prefix
    )
    if (
        value.get("terminal_state")
        != ("COMPLETE" if completed_before_failed_turn else "RUNNING")
        or value.get("complete") is not completed_before_failed_turn
        or value.get("passed") is not completed_before_failed_turn
        or not expected_names
        or len(expected_names) != len(set(expected_names))
        or failed_prefix > len(expected_names)
        or value.get("expected_step_names") != expected_names
        or not isinstance(consumed_names, list)
        or not gateway_step_sequence_matches(
            expected_names[:previous_prefix],
            consumed_names,
            expected_groups,
            expected_setup_groups,
        )
        or value.get("commutative_read_only_step_groups", [])
        != expected_groups
        or value.get("commutative_composer_setup_step_groups", [])
        != expected_setup_groups
        or not isinstance(records, list)
        or len(records) != previous_prefix
        or len(command_records) != previous_prefix
        or value.get("runner_path")
        != str(Path(os.path.abspath(os.fspath(options.skill_source / "scripts" / "run.py"))))
    ):
        raise CampaignEvidenceError(
            "retryable heavy broker did not stop at the prior proven prefix"
        )
    _validate_heavy_v3_broker_records(
        records,
        task_root=task_root,
        canonical_steps=protocol.steps[:previous_prefix],
        steps=_steps_in_consumed_order(
            protocol.steps[:previous_prefix],
            consumed_names,
        ),
        commutative_read_only_step_groups=getattr(
            protocol,
            "commutative_read_only_step_groups",
            (),
        ),
        commutative_composer_setup_step_groups=getattr(
            protocol,
            "commutative_composer_setup_step_groups",
            (),
        ),
        command_records=command_records,
        options=options,
        version=version,
        label="retryable heavy partial",
        expected_project_modification_policy=(
            expected_project_modification_policy
        ),
    )
    expected_directories = {
        "state_directory": task_root / "broker" / "state",
        "evidence_directory": task_root / "broker" / "evidence",
    }
    for key, expected in expected_directories.items():
        raw = value.get(key)
        if raw != str(expected):
            raise CampaignEvidenceError(
                f"retryable heavy partial broker {key} is misbound"
            )
        _require_real_directory(
            expected,
            label=f"retryable heavy partial broker {key}",
        )


def _validate_heavy_v3_retryable_lifecycle(
    outcome: Mapping[str, Any],
    *,
    scenario_root: Path,
    runner: str,
) -> None:
    lifecycle = outcome.get("lifecycle")
    if not isinstance(lifecycle, Mapping):
        raise CampaignEvidenceError(
            "retryable heavy infrastructure evidence lacks lifecycle proof"
        )
    evidence_root = scenario_root / "evidence"
    task_root = evidence_root / "codex-task"
    owned_root = scenario_root / "owned"
    if outcome.get("task_root") != str(task_root):
        raise CampaignEvidenceError(
            "retryable heavy infrastructure evidence lacks retained task/owned roots"
        )
    _require_real_directory(
        task_root,
        label="retryable heavy retained task root",
    )
    _require_real_directory(
        owned_root,
        label="retryable heavy retained owned root",
    )
    archived_lifecycle = load_strict_regular_json(evidence_root / "lifecycle.json")
    if archived_lifecycle != lifecycle:
        raise CampaignEvidenceError(
            "retryable heavy embedded lifecycle differs from its archived lifecycle"
        )
    expected_contract = (
        HEAVY_V3_CLI_LIFECYCLE_CONTRACT
        if runner == "cli"
        else HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT
    )
    common_keys = {
        "contract",
        "requested_status",
        "final_status",
        "source_hash_before",
        "source_hash_after",
        "source_mtime_before_ns",
        "source_mtime_after_ns",
        "errors",
        "quarantine_path",
    }
    runner_keys = (
        {"owned_state_retained", "phases"}
        if runner == "cli"
        else {"scenario_id", "version", "sandbox_retained"}
    )
    if set(lifecycle) != common_keys | runner_keys:
        raise CampaignEvidenceError(
            "retryable heavy infrastructure lifecycle has an invalid shape"
        )
    source_hash = lifecycle.get("source_hash_before")
    if (
        lifecycle.get("contract") != expected_contract
        or lifecycle.get("requested_status") != "BLOCKED"
        or lifecycle.get("final_status") != "BLOCKED"
        or not _valid_heavy_project_hash(source_hash)
        or source_hash != lifecycle.get("source_hash_after")
        or type(lifecycle.get("source_mtime_before_ns")) is not int
        or lifecycle.get("source_mtime_before_ns")
        != lifecycle.get("source_mtime_after_ns")
    ):
        raise CampaignEvidenceError(
            "retryable heavy infrastructure lifecycle did not preserve its source"
        )
    errors = lifecycle.get("errors")
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise CampaignEvidenceError(
            "retryable heavy infrastructure lifecycle errors are malformed"
        )
    if runner == "cli":
        clean = (
            lifecycle.get("owned_state_retained") is True
            and not errors
            and _heavy_v3_retryable_cli_phases_are_clean(
                lifecycle.get("phases"),
                owned_root=owned_root,
            )
        )
    elif runner == "project":
        checks = outcome.get("checks")
        reason = str(outcome.get("reason"))
        clean = (
            lifecycle.get("scenario_id") == outcome.get("scenario_id")
            and lifecycle.get("version") == outcome.get("version")
            and lifecycle.get("sandbox_retained") is True
            and errors == [f"scenario:{reason}"]
            and isinstance(checks, Mapping)
            and checks.get("direct_client_closed") is True
            and not any(
                key in checks
                for key in (
                    "direct_client_close_error",
                    "early_media_isolation_error",
                    "topic_publisher_teardown_error",
                )
            )
        )
    else:
        raise CampaignEvidenceError("retryable heavy outcome has an unknown runner")
    if not clean:
        raise CampaignEvidenceError(
            "retryable heavy infrastructure lifecycle contains cleanup uncertainty"
        )
    quarantine_value = lifecycle.get("quarantine_path")
    if not isinstance(quarantine_value, str) or not quarantine_value:
        raise CampaignEvidenceError(
            "retryable heavy infrastructure lifecycle lacks quarantine evidence"
        )
    quarantine = Path(quarantine_value)
    try:
        quarantine_metadata = quarantine.lstat()
    except OSError as exc:
        raise CampaignEvidenceError(
            "retryable heavy infrastructure quarantine is unavailable"
        ) from exc
    if (
        quarantine != evidence_root / "quarantine.json"
        or not quarantine.is_absolute()
        or not _path_is_within(quarantine, scenario_root)
        or path_is_link_or_reparse(
            quarantine,
            metadata=quarantine_metadata,
        )
        or not stat.S_ISREG(quarantine_metadata.st_mode)
    ):
        raise CampaignEvidenceError(
            "retryable heavy infrastructure quarantine is not scenario-owned"
        )
    quarantine_payload = load_strict_regular_json(quarantine)
    expected_quarantine_keys = (
        {
            "contract",
            "status",
            "owned_root",
            "owned_tree_sha256",
            "never_reuse",
        }
        if runner == "cli"
        else {
            "contract",
            "scenario_id",
            "version",
            "status",
            "sealed_at",
            "owned_root",
            "owned_tree_sha256",
            "never_reuse",
            "errors",
        }
    )
    if not isinstance(quarantine_payload, Mapping) or set(
        quarantine_payload
    ) != expected_quarantine_keys:
        raise CampaignEvidenceError(
            "retryable heavy infrastructure quarantine has an invalid shape"
        )
    expected_quarantine_contract = (
        HEAVY_V3_CLI_LIFECYCLE_CONTRACT
        if runner == "cli"
        else HEAVY_V3_PROJECT_QUARANTINE_CONTRACT
    )
    try:
        observed_owned_tree_sha256 = stable_tree_sha256(owned_root)
    except (OSError, ValueError) as exc:
        raise CampaignEvidenceError(
            f"cannot verify retryable heavy owned tree: {exc}"
        ) from exc
    if (
        quarantine_payload.get("contract") != expected_quarantine_contract
        or quarantine_payload.get("status") != "BLOCKED"
        or quarantine_payload.get("never_reuse") is not True
        or quarantine_payload.get("owned_root") != str(owned_root)
        or quarantine_payload.get("owned_tree_sha256")
        != observed_owned_tree_sha256
    ):
        raise CampaignEvidenceError(
            "retryable heavy quarantine does not seal the retained owned tree"
        )
    if runner == "project":
        if (
            quarantine_payload.get("scenario_id") != outcome.get("scenario_id")
            or quarantine_payload.get("version") != outcome.get("version")
            or not _valid_heavy_utc_timestamp(quarantine_payload.get("sealed_at"))
            or quarantine_payload.get("errors") != errors
        ):
            raise CampaignEvidenceError(
                "retryable heavy project quarantine identity is misbound"
            )
        _validate_heavy_v3_retryable_project_start(
            outcome,
            lifecycle=lifecycle,
            scenario_root=scenario_root,
            owned_root=owned_root,
        )


def _valid_heavy_project_hash(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "algorithm",
        "strategy",
        "digest",
        "file_count",
        "bytes_hashed",
    }:
        return False
    return (
        value.get("algorithm") == "sha256"
        and value.get("strategy") == "full"
        and isinstance(value.get("digest"), str)
        and _SHA256_RE.fullmatch(str(value.get("digest"))) is not None
        and type(value.get("file_count")) is int
        and value.get("file_count", -1) >= 1
        and type(value.get("bytes_hashed")) is int
        and value.get("bytes_hashed", -1) >= 1
    )


def _heavy_v3_retryable_cli_phases_are_clean(
    value: Any,
    *,
    owned_root: Path,
) -> bool:
    if not isinstance(value, list) or not value:
        return False
    try:
        expected_launch_cwd = _require_real_directory(
            owned_root / "case",
            label="retryable CLI case root",
        )
    except CampaignEvidenceError:
        return False
    roles: list[str] = []
    phase_keys = {
        "evidence",
        "stdout_sha256",
        "stderr_sha256",
        "log_overflow",
        "ready_version",
    }
    evidence_keys = {
        "role",
        "argv",
        "cwd",
        "shell",
        "started",
        "ready",
        "process_exited",
        "residual_pids",
        "shutdown_error",
        "open_project_path",
        "returncode",
        "natural_exit_before_shutdown",
        "runner_shutdown_requested",
    }
    for phase in value:
        if not isinstance(phase, Mapping) or set(phase) != phase_keys:
            return False
        evidence = phase.get("evidence")
        if not isinstance(evidence, Mapping) or set(evidence) != evidence_keys:
            return False
        role = evidence.get("role")
        if role not in {"setup", "business"} or role in roles:
            return False
        roles.append(str(role))
        argv = evidence.get("argv")
        cwd = evidence.get("cwd")
        open_project = evidence.get("open_project_path")
        returncode = evidence.get("returncode")
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(item, str) or not item for item in argv)
            or not isinstance(cwd, str)
            or not isinstance(open_project, str)
            or (returncode is not None and type(returncode) is not int)
            or evidence.get("shell") is not False
            or evidence.get("started") is not True
            or evidence.get("ready") is not True
            or evidence.get("process_exited") is not True
            or evidence.get("residual_pids") != []
            or evidence.get("shutdown_error") is not None
            or type(evidence.get("natural_exit_before_shutdown")) is not bool
            or type(evidence.get("runner_shutdown_requested")) is not bool
            or phase.get("log_overflow") is not False
            or phase.get("ready_version") != "2022.1"
            or not isinstance(phase.get("stdout_sha256"), str)
            or _SHA256_RE.fullmatch(str(phase.get("stdout_sha256"))) is None
            or not isinstance(phase.get("stderr_sha256"), str)
            or _SHA256_RE.fullmatch(str(phase.get("stderr_sha256"))) is None
        ):
            return False
        project = Path(open_project)
        working_directory = Path(cwd)
        try:
            project_metadata = project.lstat()
            validated_working_directory = _require_real_directory(
                working_directory,
                label="retryable CLI working directory",
            )
        except (OSError, CampaignEvidenceError):
            return False
        if (
            not project.is_absolute()
            or path_is_link_or_reparse(project, metadata=project_metadata)
            or not stat.S_ISREG(project_metadata.st_mode)
            or not _path_is_within(project, owned_root)
            or not working_directory.is_absolute()
            or validated_working_directory != expected_launch_cwd
            or not _path_is_within(project, expected_launch_cwd)
            or open_project not in argv
        ):
            return False
    return roles[-1] == "business" and roles.count("business") == 1


def _validate_heavy_v3_retryable_project_start(
    outcome: Mapping[str, Any],
    *,
    lifecycle: Mapping[str, Any],
    scenario_root: Path,
    owned_root: Path,
) -> None:
    start = load_strict_regular_json(scenario_root / "evidence" / "start.json")
    if not isinstance(start, Mapping) or set(start) != {
        "contract",
        "scenario_id",
        "version",
        "started_at",
        "source_hash_before",
        "source_mtime_before_ns",
        "sandbox_project",
        "launch_cwd",
        "endpoint",
        "isolated_launch_environment",
        "owned_wine_prefix",
    }:
        raise CampaignEvidenceError(
            "retryable heavy project start evidence has an invalid shape"
        )
    sandbox_project_value = start.get("sandbox_project")
    launch_cwd_value = start.get("launch_cwd")
    endpoint = start.get("endpoint")
    isolated_environment = start.get("isolated_launch_environment")
    if not isinstance(sandbox_project_value, str) or not isinstance(
        launch_cwd_value, str
    ):
        raise CampaignEvidenceError(
            "retryable heavy project start launch paths are malformed"
        )
    sandbox_project = Path(sandbox_project_value)
    launch_cwd = _require_real_directory(
        Path(launch_cwd_value),
        label="retryable Wwise launch cwd",
    )
    expected_launch_cwd = _require_real_directory(
        owned_root / "sandbox-root",
        label="retryable owned sandbox root",
    )
    try:
        sandbox_project_metadata = sandbox_project.lstat()
    except OSError as exc:
        raise CampaignEvidenceError(
            "retryable heavy project sandbox is unavailable"
        ) from exc
    if (
        start.get("contract") != HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT
        or start.get("scenario_id") != outcome.get("scenario_id")
        or start.get("version") != outcome.get("version")
        or not _valid_heavy_utc_timestamp(start.get("started_at"))
        or start.get("source_hash_before") != lifecycle.get("source_hash_before")
        or start.get("source_mtime_before_ns")
        != lifecycle.get("source_mtime_before_ns")
        or not sandbox_project.is_absolute()
        or path_is_link_or_reparse(
            sandbox_project,
            metadata=sandbox_project_metadata,
        )
        or not stat.S_ISREG(sandbox_project_metadata.st_mode)
        or not _path_is_within(sandbox_project, owned_root)
        or launch_cwd != expected_launch_cwd
        or not _path_is_within(sandbox_project, launch_cwd)
        or not isinstance(endpoint, Mapping)
        or set(endpoint) != {"host", "port"}
        or endpoint.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or type(endpoint.get("port")) is not int
        or not 1 <= endpoint.get("port", 0) <= 65535
        or not isinstance(isolated_environment, Mapping)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in isolated_environment.items()
        )
    ):
        raise CampaignEvidenceError(
            "retryable heavy project start evidence is not bound to its lifecycle"
        )


def _validate_heavy_v3_pass_outcome(
    outcome: Mapping[str, Any],
    *,
    expected_unit: Any,
    expected_row: Mapping[str, Any],
    scenario_root: Path,
    options: CampaignOptions,
) -> None:
    if outcome.get("reason") != "":
        raise CampaignEvidenceError("passing heavy outcome must have an empty reason")
    task_root_value = outcome.get("task_root")
    thread_id = outcome.get("thread_id")
    if not isinstance(task_root_value, str) or not task_root_value:
        raise CampaignEvidenceError("passing heavy outcome has no task root")
    if not isinstance(thread_id, str) or not thread_id:
        raise CampaignEvidenceError("passing heavy outcome has no thread identity")
    task_root = Path(task_root_value)
    expected_task_root = scenario_root / "evidence" / "codex-task"
    resolved_task_root = _require_real_directory(
        task_root,
        label="passing heavy task root",
    )
    resolved_expected_task_root = _require_real_directory(
        expected_task_root,
        label="passing heavy fixed task root",
    )
    if (
        not task_root.is_absolute()
        or resolved_task_root != resolved_expected_task_root
    ):
        raise CampaignEvidenceError(
            "passing heavy task root is not the exact real scenario evidence directory"
        )

    checks = outcome.get("checks")
    lifecycle = outcome.get("lifecycle")
    if not isinstance(checks, Mapping) or not isinstance(lifecycle, Mapping):
        raise CampaignEvidenceError(
            "passing heavy outcome lacks checks or lifecycle evidence"
        )
    prompt_evidence = _validate_heavy_v3_task_result(
        task_root,
        expected_unit=expected_unit,
        expected_thread_id=thread_id,
        scenario_root=scenario_root,
        options=options,
    )
    primary_count = _heavy_v3_primary_dispatch_count(expected_unit)
    audited_count = _heavy_v3_audited_dispatch_count(expected_unit)
    _validate_heavy_v3_pass_checks(
        checks,
        expected_unit=expected_unit,
        expected_row=expected_row,
        expected_thread_id=thread_id,
        primary_count=primary_count,
        audited_count=audited_count,
        task_root=task_root,
        prompt_evidence=prompt_evidence,
    )
    _validate_heavy_v3_pass_lifecycle(
        lifecycle,
        checks=checks,
        expected_row=expected_row,
        scenario_root=scenario_root,
        task_root=task_root,
    )


def _heavy_v3_primary_dispatch_count(expected_unit: Any) -> int:
    declared = getattr(
        expected_unit,
        "expected_primary_dispatch_count",
        None,
    )
    if declared is not None:
        if type(declared) is not int or declared < 0:
            raise CampaignEvidenceError(
                "policy unit has an invalid primary-dispatch count"
            )
        return declared
    scenario = getattr(expected_unit, "scenario", None)
    dispatch = getattr(scenario, "primary_dispatch", None)
    count = getattr(dispatch, "count", None)
    if type(count) is not int or count < 0:
        raise CampaignEvidenceError(
            "heavy scenario has no closed primary-dispatch count"
        )
    return count


def _heavy_v3_audited_dispatch_count(expected_unit: Any) -> int:
    declared = getattr(
        expected_unit,
        "expected_audited_dispatch_count",
        None,
    )
    if declared is None:
        return _heavy_v3_primary_dispatch_count(expected_unit)
    if type(declared) is not int or declared < 0:
        raise CampaignEvidenceError(
            "policy unit has an invalid audited-dispatch count"
        )
    return declared


def _heavy_v3_base_scenario_id(expected_unit: Any) -> str:
    value = getattr(expected_unit, "base_scenario_id", None)
    if value is None:
        value = getattr(expected_unit, "unit_id", None)
    if not isinstance(value, str) or not value:
        raise CampaignEvidenceError(
            "heavy unit has no closed base-scenario identity"
        )
    return value


def _heavy_v3_topic_publisher_request_count(
    prompt_evidence: HeavyV3PromptEvidence,
) -> int:
    """Return the sealed publisher-call count, not the resulting event count."""

    sections = prompt_evidence.typed_sections
    topic = (
        sections.live_binding.get("topic")
        if isinstance(sections, SoundBankBusinessPlanSections)
        else None
    )
    requests = topic.get("publisher_requests") if isinstance(topic, Mapping) else None
    if (
        not isinstance(requests, list)
        or not requests
        or any(not isinstance(request, Mapping) for request in requests)
    ):
        raise CampaignEvidenceError(
            "heavy topic plan has no closed runner-owned publisher request list"
        )
    return len(requests)


def _heavy_v3_required_reference(expected_unit: Any) -> str | None:
    if _heavy_v3_integration_workflow_id(
        expected_unit
    ) in _INTEGRATION_QUERY_FIRST_WORKFLOW_IDS:
        return "references/waapi-query.md"
    scenario = getattr(expected_unit, "scenario", None)
    api = getattr(scenario, "api", None)
    item_type = getattr(scenario, "item_type", None)
    if api == "ak.wwise.core.getInfo":
        return None
    if api in {
        "ak.wwise.core.object.get",
        "ak.wwise.core.mediaPool.get",
    } or item_type == "topic":
        return "references/waapi-query.md"
    if isinstance(api, str) and api:
        return "references/waapi-operate.md"
    raise CampaignEvidenceError("heavy scenario has no exact Skill reference lane")


def _heavy_v3_expected_skill_reads(
    expected_unit: Any,
) -> tuple[tuple[str, ...], ...]:
    """Derive the closed lane-reference schedule from reviewed unit identity."""

    turn_count = getattr(expected_unit, "user_turn_count", None)
    if type(turn_count) is not int or turn_count < 1:
        raise CampaignEvidenceError(
            "heavy unit has no closed reference-read turn topology"
        )
    required_reference = _heavy_v3_required_reference(expected_unit)
    workflow_id = _heavy_v3_integration_workflow_id(expected_unit)
    if workflow_id in _INTEGRATION_QUERY_FIRST_WORKFLOW_IDS:
        if turn_count != 3:
            raise CampaignEvidenceError(
                "query-first integration reference schedule requires exactly three turns"
            )
        lane_schedule = (
            ("references/waapi-query.md",),
            ("references/waapi-operate.md",),
            (),
        )
    else:
        lane_schedule = None
    return _normalize_turn_reference_schedule(
        prompt_count=turn_count,
        required_reference=required_reference,
        turn_reference_schedule=lane_schedule,
    )


_ALARM_REVIEWED_TURN_KINDS = (
    "diagnosis_request",
    "change_request",
    "confirmation",
)
_WEAPONS_V2_REVIEWED_TURN_KINDS = (
    "audit_request",
    "change_request",
    "confirmation",
)


def _heavy_v3_receipt_kind_for_reviewed_turn(
    expected_unit: Any,
    turn: Any,
    *,
    index: int,
) -> str:
    """Map one closed reviewed turn kind to its generic receipt kind."""

    receipt_kind = "request" if index == 1 else "confirmation"
    workflow_id = _heavy_v3_integration_workflow_id(expected_unit)
    if workflow_id == "alarm_diagnose_and_repair":
        reviewed_kind = (
            _ALARM_REVIEWED_TURN_KINDS[index - 1]
            if 1 <= index <= len(_ALARM_REVIEWED_TURN_KINDS)
            else None
        )
    elif workflow_id == "weapons_query_guided_batch_cleanup":
        reviewed_kind = (
            _WEAPONS_V2_REVIEWED_TURN_KINDS[index - 1]
            if 1 <= index <= len(_WEAPONS_V2_REVIEWED_TURN_KINDS)
            else None
        )
    else:
        reviewed_kind = receipt_kind
    if getattr(turn, "kind", None) != reviewed_kind:
        raise CampaignEvidenceError(
            "heavy reviewed turn plan has an invalid request/confirmation order"
        )
    return receipt_kind


def _heavy_v3_reviewed_prompts(
    expected_unit: Any,
    provenance: PromptProvenanceEvidence,
) -> tuple[str, ...]:
    """Rebuild the exact reviewed prompts from sealed visible inputs."""

    planned_turns = tuple(getattr(expected_unit, "turns", ()))
    workflow_id = _heavy_v3_integration_workflow_id(expected_unit)
    if workflow_id not in _INTEGRATION_V2_WORKFLOW_IDS:
        return (
            provenance.prompts[0],
            *(str(getattr(turn, "prompt", "")) for turn in planned_turns[1:]),
        )

    scenario = getattr(expected_unit, "scenario", None)
    declarations = tuple(getattr(scenario, "visible_inputs", ()))
    expected_names = tuple(getattr(item, "name", None) for item in declarations)
    values = dict(provenance.visible_values)
    if (
        any(not isinstance(name, str) or not name for name in expected_names)
        or len(expected_names) != len(set(expected_names))
        or set(values) != set(expected_names)
        or any(not isinstance(value, str) for value in values.values())
    ):
        raise CampaignEvidenceError(
            "heavy reviewed turn inputs differ from sealed provenance"
        )
    try:
        return tuple(
            str(getattr(turn, "prompt", "")).format_map(values)
            for turn in planned_turns
        )
    except (KeyError, ValueError) as exc:
        raise CampaignEvidenceError(
            "heavy reviewed turn prompt cannot be rendered from sealed provenance"
        ) from exc


def _validate_heavy_v3_prompt_materialization(
    task_root: Path,
    *,
    scenario_root: Path,
    expected_unit: Any,
    expected_sha256: str,
    protocol_manifest_revision: str | None = None,
) -> HeavyV3PromptEvidence:
    """Validate provenance -> receipt -> archived turn binding."""

    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise CampaignEvidenceError(
            "heavy prompt materialization digest is malformed"
        )
    receipt_path = task_root / HEAVY_V3_PROMPT_MATERIALIZATION_FILE
    raw = _load_strict_regular_text(receipt_path)
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != expected_sha256:
        raise CampaignEvidenceError(
            "heavy prompt materialization archive digest is invalid"
        )
    value = load_strict_regular_json(receipt_path)
    required_keys = {
        "contract",
        "scenario_id",
        "version",
        "provenance_path",
        "provenance_sha256",
        "protocol_sha256",
        "business_oracle_plan_path",
        "business_oracle_plan_sha256",
        "expected_turn_count",
        "turns",
    }
    scenario = getattr(expected_unit, "scenario", None)
    planned_turns = tuple(getattr(expected_unit, "turns", ()))
    expected_turn_count = getattr(expected_unit, "user_turn_count", None)
    if (
        not isinstance(value, Mapping)
        or set(value) != required_keys
        or value.get("contract") != HEAVY_V3_PROMPT_MATERIALIZATION_CONTRACT
        or value.get("scenario_id")
        != _heavy_v3_base_scenario_id(expected_unit)
        or value.get("version") != getattr(expected_unit, "version", None)
        or type(expected_turn_count) is not int
        or expected_turn_count < 1
        or value.get("expected_turn_count") != expected_turn_count
        or len(planned_turns) != expected_turn_count
    ):
        raise CampaignEvidenceError(
            "heavy prompt materialization identity or turn topology is invalid"
        )
    provenance_path = scenario_root / "evidence" / HEAVY_V3_PROMPT_PROVENANCE_FILE
    if value.get("provenance_path") != str(provenance_path):
        raise CampaignEvidenceError("heavy prompt receipt points outside fixed provenance")
    business_oracle_plan_path = (
        scenario_root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    )
    if value.get("business_oracle_plan_path") != str(business_oracle_plan_path):
        raise CampaignEvidenceError(
            "heavy prompt receipt points outside fixed business-oracle plan"
        )
    try:
        raw_provenance = load_strict_regular_json(provenance_path)
        raw_protocol = (
            raw_provenance.get("protocol", {}).get("value")
            if isinstance(raw_provenance, Mapping)
            and isinstance(raw_provenance.get("protocol"), Mapping)
            else None
        )
        if isinstance(raw_protocol, Mapping):
            # Lazy, verify-only import: the current campaign/provenance path
            # never imports or exposes the retired manifest grammar.
            from tests.semantic.support.codex_prompt_provenance_archive_v3 import (
                is_archived_prompt_protocol,
                read_archived_prompt_provenance,
            )

            archived_protocol = is_archived_prompt_protocol(raw_protocol)
        else:
            archived_protocol = False
        provenance = (
            read_archived_prompt_provenance(
                provenance_path,
                scenario=scenario,
                version=str(getattr(expected_unit, "version", "")),
                scenario_root=scenario_root,
                require_paths=False,
            )
            if archived_protocol
            else read_prompt_provenance(
                provenance_path,
                scenario=scenario,
                version=str(getattr(expected_unit, "version", "")),
                scenario_root=scenario_root,
                require_paths=False,
                protocol_manifest_revision=protocol_manifest_revision,
            )
        )
    except Exception as exc:
        raise CampaignEvidenceError(
            f"heavy prompt provenance is invalid: {exc}"
        ) from exc
    if (
        value.get("provenance_sha256") != provenance.sha256
        or value.get("protocol_sha256")
        != provenance.payload["protocol"]["sha256"]
    ):
        raise CampaignEvidenceError(
            "heavy prompt receipt is not bound to its provenance/protocol"
        )
    try:
        plan_value = load_strict_regular_json(business_oracle_plan_path)
        fixture_spec = _heavy_v3_business_plan_fixture_spec(
            plan_value,
            expected_unit=expected_unit,
        )
        api = str(getattr(scenario, "api", ""))
        family = business_family_for_api(api)
        runner = "cli" if family == "cli" else "project"
        business_oracle_plan = read_business_oracle_plan_envelope(
            business_oracle_plan_path,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            version=str(getattr(expected_unit, "version", "")),
            api=api,
            runner=runner,
            family=family,
            scenario_root=scenario_root,
            fixture_spec=fixture_spec,
            protocol_sha256=str(provenance.payload["protocol"]["sha256"]),
            provenance_sha256=provenance.sha256,
            primary_dispatch_count=_heavy_v3_primary_dispatch_count(expected_unit),
        )
        typed_sections = _validate_heavy_v3_typed_business_plan(
            plan_value,
            expected_unit=expected_unit,
            provenance=provenance,
        )
    except (
        AudioMediaBusinessPlanError,
        BusinessOraclePlanError,
        CampaignEvidenceError,
        CliBusinessPlanError,
        ImportBusinessPlanError,
        ObjectBusinessPlanError,
        DirectBusinessPlanError,
        ObjectHeavyRecipeError,
        SoundBankBusinessPlanError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise CampaignEvidenceError(
            f"heavy business-oracle plan is invalid: {exc}"
        ) from exc
    if value.get("business_oracle_plan_sha256") != business_oracle_plan.sha256:
        raise CampaignEvidenceError(
            "heavy prompt receipt is not bound to its business-oracle plan"
        )
    reviewed_prompts = _heavy_v3_reviewed_prompts(expected_unit, provenance)
    if len(reviewed_prompts) != len(planned_turns):
        raise CampaignEvidenceError(
            "heavy reviewed prompt count differs from the turn plan"
        )
    expected_rows: list[dict[str, Any]] = []
    for index, turn in enumerate(planned_turns, start=1):
        if getattr(turn, "index", None) != index:
            raise CampaignEvidenceError(
                "heavy reviewed turn plan has non-contiguous indices"
            )
        expected_kind = _heavy_v3_receipt_kind_for_reviewed_turn(
            expected_unit,
            turn,
            index=index,
        )
        prompt = provenance.prompts[index - 1]
        reviewed_prompt = reviewed_prompts[index - 1]
        if prompt != reviewed_prompt:
            raise CampaignEvidenceError(
                "heavy provenance prompt differs from the reviewed turn plan"
            )
        if not isinstance(prompt, str) or not prompt:
            raise CampaignEvidenceError("heavy reviewed turn has no exact prompt")
        expected_rows.append(
            {
                "index": index,
                "kind": expected_kind,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            }
        )
    if value.get("turns") != expected_rows:
        raise CampaignEvidenceError(
            "heavy prompt materialization turns differ from the reviewed turn plan"
        )
    return HeavyV3PromptEvidence(
        prompts=provenance.prompts,
        provenance=provenance,
        business_oracle_plan=business_oracle_plan,
        typed_sections=typed_sections,
    )


def _validate_heavy_v3_task_result(
    task_root: Path,
    *,
    expected_unit: Any,
    expected_thread_id: str,
    scenario_root: Path,
    options: CampaignOptions,
) -> HeavyV3PromptEvidence:
    value = load_strict_regular_json(task_root / "task-result.json")
    required_keys = {
        "contract",
        "scenario_id",
        "version",
        "thread_id",
        "turn_count",
        "passed",
        "prompt_materialization_sha256",
        "broker",
        "turn_grades",
    }
    optional_protocol_keys = {
        "protocol_terminal_passed",
        "accepted_terminal_prefixes",
    }
    provisionally_allowed_shapes = (
        required_keys,
        required_keys | {"composer_evidence"},
        required_keys | optional_protocol_keys,
        required_keys | optional_protocol_keys | {"composer_evidence"},
    )
    expected_turn_count = getattr(expected_unit, "user_turn_count", None)
    if (
        not isinstance(value, Mapping)
        or set(value) not in provisionally_allowed_shapes
        or value.get("contract") != HEAVY_V3_TASK_RESULT_CONTRACT
        or value.get("scenario_id")
        != _heavy_v3_base_scenario_id(expected_unit)
        or value.get("version") != getattr(expected_unit, "version", None)
        or value.get("thread_id") != expected_thread_id
        or type(expected_turn_count) is not int
        or expected_turn_count < 1
        or value.get("turn_count") != expected_turn_count
        or value.get("passed") is not True
        or not isinstance(value.get("prompt_materialization_sha256"), str)
        or _SHA256_RE.fullmatch(
            str(value.get("prompt_materialization_sha256"))
        )
        is None
    ):
        raise CampaignEvidenceError("passing heavy task-result contract is invalid")

    prompt_evidence = _validate_heavy_v3_prompt_materialization(
        task_root,
        scenario_root=scenario_root,
        expected_unit=expected_unit,
        expected_sha256=str(value["prompt_materialization_sha256"]),
        protocol_manifest_revision=options.protocol_manifest_revision,
    )
    protocol = prompt_evidence.provenance.protocol
    is_optional_protocol = bool(protocol.allowed_turn_prefix_counts)
    if is_optional_protocol:
        required_keys.update(optional_protocol_keys)
        if (
            value.get("protocol_terminal_passed") is not True
            or value.get("accepted_terminal_prefixes")
            != list(protocol.accepted_terminal_prefixes)
        ):
            raise CampaignEvidenceError(
                "passing heavy task-result optional protocol is invalid"
            )
    is_composer_protocol = any(
        step.subcommand.startswith("draft-")
        or step.subcommand == "preview-from-draft"
        for step in protocol.steps
    )
    if is_composer_protocol:
        required_keys.add("composer_evidence")
    if set(value) != required_keys:
        raise CampaignEvidenceError("passing heavy task-result contract is invalid")
    turn_grades = value.get("turn_grades")
    if not isinstance(turn_grades, list) or len(turn_grades) != expected_turn_count:
        raise CampaignEvidenceError("passing heavy task has invalid turn grades")
    turns_root = task_root / "turns"
    expected_names = {f"turn-{index:02d}" for index in range(1, expected_turn_count + 1)}
    actual_names = _strict_real_subdirectory_names(turns_root)
    if actual_names != expected_names:
        raise CampaignEvidenceError(
            "passing heavy task turn directories do not match its turn count"
        )
    gateway_records: list[Mapping[str, Any]] = []
    previous_prefix = 0
    expected_skill_reads = _heavy_v3_expected_skill_reads(expected_unit)
    broker_value = value.get("broker")
    selected_step_names = (
        broker_value.get("expected_step_names")
        if isinstance(broker_value, Mapping)
        else None
    )
    for index, grade in enumerate(turn_grades, start=1):
        turn_root = turns_root / f"turn-{index:02d}"
        expected_prefix = (
            grade.get("broker_prefix_count")
            if protocol.allowed_turn_prefix_counts
            and isinstance(grade, Mapping)
            else protocol.turn_prefix_counts[index - 1]
        )
        if (
            type(expected_prefix) is not int
            or expected_prefix
            not in protocol.allowed_prefixes_for_turn(index)
            or expected_prefix < previous_prefix
        ):
            raise CampaignEvidenceError(
                "passing heavy turn selected an invalid optional broker prefix"
            )
        consumed_protocol_steps = _consumed_heavy_v3_protocol_steps(
            protocol,
            expected_prefix,
            selected_step_names=selected_step_names,
        )
        turn_gateway_records = _validate_heavy_v3_turn_grade(
            grade,
            index=index,
            turn_root=turn_root,
            expected_thread_id=expected_thread_id,
            expected_prompt=prompt_evidence.prompts[index - 1],
            task_root=task_root,
            options=options,
            previous_broker_prefix=previous_prefix,
            expected_broker_prefix=expected_prefix,
            expected_steps=consumed_protocol_steps[
                previous_prefix:expected_prefix
            ],
            version=str(getattr(expected_unit, "version", "")),
            expected_skill_reads=expected_skill_reads[index - 1],
            expected_skill_read_schedule=expected_skill_reads,
            prompt_provenance=prompt_evidence.provenance,
        )
        gateway_records.extend(turn_gateway_records)
        if len(gateway_records) != expected_prefix:
            raise CampaignEvidenceError(
                "passing heavy turn command allocation differs from its broker prefix"
            )
        previous_prefix = expected_prefix
    _validate_heavy_v3_broker_result(
        value.get("broker"),
        task_root=task_root,
        protocol=prompt_evidence.provenance.protocol,
        command_records=tuple(gateway_records),
        options=options,
        version=str(getattr(expected_unit, "version", "")),
        expected_consumed_count=previous_prefix,
        expected_project_modification_policy=getattr(
            expected_unit,
            "project_modification_policy",
            None,
        ),
    )
    if is_composer_protocol:
        broker_value = value.get("broker")
        if not isinstance(broker_value, Mapping):
            raise CampaignEvidenceError("passing Composer task lacks Broker evidence")
        broker_records = broker_value.get("records")
        consumed_names = broker_value.get("consumed_step_names")
        if not isinstance(broker_records, list) or not isinstance(consumed_names, list):
            raise CampaignEvidenceError("passing Composer Broker evidence is malformed")
        sealed_composer = value.get("composer_evidence")
        is_current_typed_evidence = _is_current_draft_evidence(
            sealed_composer
        )
        try:
            validator_arguments = {
                "state_directory": task_root / "broker" / "state",
                "steps": _steps_in_consumed_order(
                    protocol.steps[: len(consumed_names)],
                    consumed_names,
                ),
                "broker_records": broker_records,
            }
            if is_current_typed_evidence:
                replayed_composer = validate_typed_draft_evidence(
                    **validator_arguments,
                    allow_cleaned_file_evidence=True,
                )
            else:
                # Historical grammar is imported only at the explicit
                # verify-only archive boundary. Normal campaign construction
                # and current evidence parsing never import or expose it.
                from tests.semantic.support.codex_operation_draft_archive_v3 import (
                    ComposerArchiveError,
                    validate_operation_draft_archive,
                )

                try:
                    replayed_composer = validate_operation_draft_archive(
                        **validator_arguments
                    )
                except ComposerArchiveError as exc:
                    raise TypedDraftEvidenceError(str(exc)) from exc
        except TypedDraftEvidenceError as exc:
            raise CampaignEvidenceError(
                f"passing Composer evidence cannot be replayed: {exc}"
            ) from exc
        if replayed_composer is None or sealed_composer != replayed_composer:
            raise CampaignEvidenceError(
                "passing Composer task-result evidence differs from offline replay"
            )
    return prompt_evidence


def _is_current_draft_evidence(value: Any) -> bool:
    """Recognize both current single-flow and multi-flow Draft archives."""

    return isinstance(value, Mapping) and value.get("contract") in {
        BUSINESS_DRAFT_EVIDENCE_CONTRACT,
        TYPED_DRAFT_EVIDENCE_CONTRACT,
    }


def _validate_heavy_v3_broker_result(
    value: Any,
    *,
    task_root: Path,
    protocol: Any,
    command_records: Sequence[Mapping[str, Any]],
    options: CampaignOptions,
    version: str,
    expected_consumed_count: int | None = None,
    expected_project_modification_policy: str | None = None,
) -> None:
    top_keys = {
        "expected_step_names",
        "consumed_step_names",
        "records",
        "state_directory",
        "evidence_directory",
        "runner_path",
        "terminal_state",
        "complete",
        "passed",
    }
    expected_groups = [
        list(group)
        for group in getattr(
            protocol,
            "commutative_read_only_step_groups",
            (),
        )
    ]
    if expected_groups:
        top_keys.add("commutative_read_only_step_groups")
    expected_setup_groups = [
        list(group)
        for group in getattr(
            protocol,
            "commutative_composer_setup_step_groups",
            (),
        )
    ]
    if expected_setup_groups:
        top_keys.add("commutative_composer_setup_step_groups")
    if not isinstance(value, Mapping) or set(value) != top_keys:
        raise CampaignEvidenceError("passing heavy task broker evidence is malformed")
    consumed_count = (
        len(protocol.steps)
        if expected_consumed_count is None
        else expected_consumed_count
    )
    protocol_steps = _consumed_heavy_v3_protocol_steps(
        protocol,
        consumed_count,
        selected_step_names=value.get("expected_step_names"),
    )
    expected_names = [step.name for step in protocol_steps]
    accepted_terminal = tuple(
        getattr(protocol, "accepted_terminal_prefixes", (len(expected_names),))
    )
    complete_expected = consumed_count == len(expected_names)
    consumed_names = value.get("consumed_step_names")
    records = value.get("records")
    if (
        consumed_count not in accepted_terminal
        or value.get("passed") is not complete_expected
        or value.get("complete") is not complete_expected
        or value.get("terminal_state")
        != ("COMPLETE" if complete_expected else "RUNNING")
        or not expected_names
        or value.get("expected_step_names") != expected_names
        or not isinstance(consumed_names, list)
        or not gateway_step_sequence_matches(
            expected_names[:consumed_count],
            consumed_names,
            expected_groups,
            expected_setup_groups,
        )
        or value.get("commutative_read_only_step_groups", [])
        != expected_groups
        or value.get("commutative_composer_setup_step_groups", [])
        != expected_setup_groups
        or len(expected_names) != len(set(expected_names))
        or not isinstance(records, list)
        or len(records) != consumed_count
        or len(command_records) != consumed_count
    ):
        raise CampaignEvidenceError(
            "passing heavy task broker did not consume one exact successful protocol"
        )
    expected_runner = Path(
        os.path.abspath(os.fspath(options.skill_source / "scripts" / "run.py"))
    )
    if value.get("runner_path") != str(expected_runner):
        raise CampaignEvidenceError("passing heavy broker runner path is misbound")
    _validate_heavy_v3_broker_records(
        records,
        task_root=task_root,
        canonical_steps=protocol_steps[:consumed_count],
        steps=_steps_in_consumed_order(
            protocol_steps[:consumed_count],
            consumed_names,
        ),
        commutative_read_only_step_groups=getattr(
            protocol,
            "commutative_read_only_step_groups",
            (),
        ),
        commutative_composer_setup_step_groups=getattr(
            protocol,
            "commutative_composer_setup_step_groups",
            (),
        ),
        command_records=command_records,
        options=options,
        version=version,
        label="passing heavy",
        expected_project_modification_policy=(
            expected_project_modification_policy
        ),
    )
    for key in ("state_directory", "evidence_directory"):
        raw = value.get(key)
        if not isinstance(raw, str) or not raw:
            raise CampaignEvidenceError(f"passing heavy broker lacks {key}")
        expected = task_root / "broker" / (
            "state" if key == "state_directory" else "evidence"
        )
        if raw != str(expected):
            raise CampaignEvidenceError(
                f"passing heavy broker {key} is outside its task evidence"
            )
        _require_real_directory(
            expected,
            label=f"passing heavy broker {key}",
        )


def _consumed_heavy_v3_protocol_steps(
    protocol: Any,
    consumed_count: int,
    *,
    selected_step_names: Any = None,
) -> tuple[Any, ...]:
    """Select the sealed command lane after reviewed optional disclosures."""

    steps = tuple(protocol.steps)
    optional_topic_groups = tuple(
        getattr(protocol, "optional_topic_schema_step_groups", ())
    )
    if optional_topic_groups:
        if (
            not isinstance(selected_step_names, list)
            or len(selected_step_names) != consumed_count
            or len(selected_step_names) != len(set(selected_step_names))
        ):
            return ()
        by_name = {step.name: step for step in steps}
        optional_names = {
            name for group in optional_topic_groups for name in group
        }
        if any(name not in by_name for name in selected_step_names):
            return ()
        mandatory_names = tuple(
            step.name for step in steps if step.name not in optional_names
        )
        selected_mandatory = tuple(
            name for name in selected_step_names if name not in optional_names
        )
        if selected_mandatory != mandatory_names:
            return ()
        return tuple(by_name[name] for name in selected_step_names)
    optional_query_names = tuple(
        getattr(protocol, "optional_query_schema_step_names", ())
    )
    if optional_query_names:
        if (
            not isinstance(selected_step_names, list)
            or len(selected_step_names) != consumed_count
            or len(selected_step_names) != len(set(selected_step_names))
        ):
            return ()
        by_name = {step.name: step for step in steps}
        if (
            not selected_step_names
            or selected_step_names[-1] != steps[-1].name
            or any(
                name not in optional_query_names
                for name in selected_step_names[:-1]
            )
        ):
            return ()
        return tuple(by_name[name] for name in selected_step_names)
    if (
        getattr(protocol, "optional_initial_query_schema", False)
        and consumed_count == len(steps) - 1
    ):
        return steps[1:]
    if (
        getattr(protocol, "optional_initial_operations_discovery", False)
        and consumed_count == len(steps) - 1
    ):
        return steps[1:]
    return steps


def _codex_command_exit_status_aligns(
    command_record: Mapping[str, Any],
    *,
    broker_exit_code: Any,
) -> bool:
    """Bind Codex's terminal command status to the broker-sealed exit code.

    Codex records a zero-exit shell command as ``completed`` and a non-zero
    shell command as ``failed``.  A reviewed gateway exit 2 is still a failed
    shell command even when its exact structured rejection is an expected
    protocol outcome.  Protocol admissibility is proved separately by the
    broker record and payload checks; this helper only rejects missing,
    unfinished, or exit/status-inconsistent Codex facts.
    """

    command_exit_code = command_record.get("exit_code")
    if (
        type(command_exit_code) is not int
        or type(broker_exit_code) is not int
        or command_exit_code != broker_exit_code
    ):
        return False
    expected_status = "completed" if broker_exit_code == 0 else "failed"
    return command_record.get("status") == expected_status


def _archived_draft_action(
    gateway_arguments: Sequence[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    """Recover historical grammar through its offline-only codec."""

    from tests.semantic.support.codex_operation_draft_archive_v3 import (
        ComposerArchiveError,
        decode_archived_draft_action,
    )

    try:
        return decode_archived_draft_action(gateway_arguments, label=label)
    except ComposerArchiveError as exc:
        raise CampaignEvidenceError(str(exc)) from exc


def _submitted_typed_draft_actions(
    gateway_arguments: Sequence[str],
    *,
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    """Recover one bounded current typed action batch without historical grammar."""

    if "--action-json" in gateway_arguments:
        raise CampaignEvidenceError(
            f"{label} current Draft action cannot contain action JSON"
        )
    indexes = [
        index
        for index, value in enumerate(gateway_arguments[:-1])
        if value == "--facts" and gateway_arguments[index + 1] == "--action"
    ]
    if len(indexes) != 1:
        raise CampaignEvidenceError(
            f"{label} Draft action argv does not contain one typed action batch"
        )
    try:
        return parse_typed_action_cli_argument_sequence(
            gateway_arguments[indexes[0] + 1 :]
        )
    except OperationComposerError as exc:
        raise CampaignEvidenceError(
            f"{label} Draft typed action argv is invalid"
        ) from exc


def _prepare_heavy_v3_replay_step(
    replay: CodexGatewayBroker,
    *,
    index: int,
    expected_step: ExpectedGatewayStep,
    actual_arguments: Sequence[str],
    label: str,
) -> ExpectedGatewayStep:
    """Apply the same deterministic pre-validation binding as live Broker."""

    replay._next_step = index  # noqa: SLF001
    replay_step = replay._execution_steps[index]  # noqa: SLF001
    if replay_step.name != expected_step.name:
        raise CampaignEvidenceError(
            f"{label} replay step order differs at {expected_step.name}"
        )
    replay_step = replay._bind_task_local_declaration_id(  # noqa: SLF001
        replay_step,
        actual_arguments,
    )
    replay._execution_steps[index] = replay_step  # noqa: SLF001
    return replay_step


def _validate_heavy_v3_broker_records(
    records: Sequence[Any],
    *,
    task_root: Path,
    steps: Sequence[Any],
    command_records: Sequence[Mapping[str, Any]],
    options: CampaignOptions,
    version: str,
    label: str,
    canonical_steps: Sequence[Any] | None = None,
    commutative_read_only_step_groups: Sequence[Sequence[str]] = (),
    commutative_composer_setup_step_groups: Sequence[Sequence[str]] = (),
    expected_project_modification_policy: str | None = None,
) -> None:
    """Replay one exact broker prefix and bind it to Codex JSONL commands."""

    if len(records) != len(steps) or len(command_records) != len(steps):
        raise CampaignEvidenceError(
            f"{label} broker record/command count differs from protocol"
        )
    # A first-turn infrastructure failure has a valid, cryptographically
    # sealed empty prior prefix.  There is nothing to replay in that case and
    # CodexGatewayBroker intentionally rejects an empty full protocol.
    if not steps:
        return
    continuation_errors = gateway_continuation_binding_errors(
        command_records,
        records,
        platform_name=(
            "nt" if options.windows_powershell_core_host is not None else "posix"
        ),
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    if continuation_errors:
        raise CampaignEvidenceError(
            f"{label} response-derived Gateway continuation binding is invalid"
        )
    expected_runner = Path(
        os.path.abspath(os.fspath(options.skill_source / "scripts" / "run.py"))
    )
    invocation_skill_source = workspace_skill_install_path(
        task_root / "agent-workspace"
    )
    replay = _build_heavy_v3_broker_replay(
        skill_source=options.skill_source,
        invocation_skill_source=invocation_skill_source,
        canonical_steps=(steps if canonical_steps is None else canonical_steps),
        execution_steps=steps,
        commutative_read_only_step_groups=(
            commutative_read_only_step_groups
        ),
        commutative_composer_setup_step_groups=(
            commutative_composer_setup_step_groups
        ),
        expected_wwise_version=version,
        project_modification_policy=(
            expected_project_modification_policy or "ask_before_changes"
        ),
        existing_state_directory=task_root / "broker" / "state",
    )
    record_keys = {
        "sequence",
        "step_name",
        "authenticated",
        "accepted",
        "rejection",
        "model_argv",
        "normalized_model_argv",
        "gateway_arguments",
        "raw_argv_sha256",
        "argv_sha256",
        "semantic_argv_sha256",
        "started_at_unix",
        "finished_at_unix",
        "duration_seconds",
        "exit_code",
        "runner_exit_code",
        "payload",
        "payload_sha256",
        "payload_error",
        "runner_command_sha256",
        "allowed_exit_codes",
        "started_at_unix_ns",
        "finished_at_unix_ns",
        "subscription_ack",
        "succeeded",
    }
    for index, (record, command_record, step) in enumerate(
        zip(records, command_records, steps, strict=True),
        start=1,
    ):
        if (
            not isinstance(record, Mapping)
            or set(record) != record_keys
            or record.get("sequence") != index
            or record.get("step_name") != step.name
            or record.get("authenticated") is not True
            or record.get("accepted") is not True
            or record.get("succeeded") is not True
            or record.get("rejection") != ""
            or record.get("payload_error") != ""
            or not isinstance(record.get("payload"), Mapping)
        ):
            raise CampaignEvidenceError(
                f"{label} task contains a malformed broker record"
            )
        model_argv = record.get("model_argv")
        if not isinstance(model_argv, list) or any(
            not isinstance(item, str) for item in model_argv
        ):
            raise CampaignEvidenceError(f"{label} broker model argv is malformed")
        try:
            resolved = resolve_gateway_invocation(
                model_argv,
                skill_source=options.skill_source,
                invocation_skill_source=invocation_skill_source,
                shim_directory=task_root / "broker" / "bin",
            )
            replay_step = _prepare_heavy_v3_replay_step(
                replay,
                index=index - 1,
                expected_step=step,
                actual_arguments=resolved.gateway_arguments,
                label=label,
            )
            try:
                semantic_sha, execution_arguments = replay._validate_step(  # noqa: SLF001
                    replay_step,
                    resolved.gateway_arguments,
                )
            except GatewayInvocationError:
                rebound = replay._match_dependency_ready_draft_batch(  # noqa: SLF001
                    resolved.gateway_arguments,
                )
                if rebound is None:
                    raise
                replay_step, semantic_sha, execution_arguments = rebound
            step = replay_step
        except Exception as exc:
            raise CampaignEvidenceError(
                f"{label} broker argv cannot replay protocol step {step.name}: {exc}"
            ) from exc
        submitted_draft_actions = (
            _submitted_typed_draft_actions(
                resolved.gateway_arguments,
                label=f"{label} protocol step {step.name}",
            )
            if step.subcommand == "draft-apply"
            else None
        )
        payload = record["payload"]
        _validate_heavy_v3_gateway_payload(
            payload,
            step=step,
            runner_exit_code=record.get("runner_exit_code"),
            expected_project_modification_policy=(
                expected_project_modification_policy
            ),
        )
        if step.subcommand == "transaction-show":
            try:
                validate_transaction_show_confirmation_against_store(
                    payload,
                    task_root / "broker" / "state",
                )
            except TransactionSealError as exc:
                raise CampaignEvidenceError(
                    "heavy transaction-show confirmation is not bound to the "
                    f"archived durable transaction: {exc}"
                ) from exc
        expected_runner_command = [
            os.path.abspath(sys.executable),
            str(expected_runner.resolve(strict=True)),
            "gateway.py",
            *execution_arguments,
        ]
        started = record.get("started_at_unix")
        finished = record.get("finished_at_unix")
        started_ns = record.get("started_at_unix_ns")
        finished_ns = record.get("finished_at_unix_ns")
        duration = record.get("duration_seconds")
        if (
            record.get("normalized_model_argv")
            != list(resolved.normalized_model_argv)
            or record.get("gateway_arguments") != list(resolved.gateway_arguments)
            or record.get("raw_argv_sha256") != _canonical_sha256(model_argv)
            or record.get("argv_sha256")
            != _canonical_sha256(list(resolved.normalized_model_argv))
            or record.get("semantic_argv_sha256") != semantic_sha
            or record.get("payload_sha256") != _canonical_sha256(payload)
            or record.get("runner_command_sha256")
            != _canonical_sha256(expected_runner_command)
            or record.get("allowed_exit_codes") != list(step.allowed_exit_codes)
            or record.get("exit_code") != record.get("runner_exit_code")
            or record.get("runner_exit_code") not in step.allowed_exit_codes
            or not isinstance(started, (int, float))
            or isinstance(started, bool)
            or not math.isfinite(float(started))
            or not isinstance(finished, (int, float))
            or isinstance(finished, bool)
            or not math.isfinite(float(finished))
            or finished < started
            or type(started_ns) is not int
            or started_ns <= 0
            or type(finished_ns) is not int
            or finished_ns < started_ns
            or abs(float(started) - started_ns / 1_000_000_000) > 1e-6
            or abs(float(finished) - finished_ns / 1_000_000_000) > 1e-6
            or not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(float(duration))
            or duration < 0
        ):
            raise CampaignEvidenceError(
                f"{label} broker hashes, exits, or timing are inconsistent"
            )
        expected_topic_ack = (
            step.subcommand in {"wait-topic", "stream-topic"}
            and bool(step.arguments)
            and step.arguments[0] == SOUNDBANK_TOPIC
        )
        if expected_topic_ack:
            _validate_heavy_v3_broker_subscription_ack_record(
                record.get("subscription_ack"),
                record=record,
                task_root=task_root,
                label=f"{label} broker subscription ACK",
                expected_step_name=step.name,
            )
        elif record.get("subscription_ack") is not None:
            raise CampaignEvidenceError(
                f"{label} non-topic broker record unexpectedly carries subscription ACK evidence"
            )
        if (
            not _codex_command_exit_status_aligns(
                command_record,
                broker_exit_code=record.get("exit_code"),
            )
            or command_record.get("has_shell_operators") is not False
            or command_record.get("parse_error") != ""
        ):
            raise CampaignEvidenceError(
                f"{label} broker record is not uniquely aligned to Codex facts"
            )
        command_argv = command_record.get("argv")
        if not isinstance(command_argv, list) or any(
            not isinstance(item, str) for item in command_argv
        ):
            raise CampaignEvidenceError(
                f"{label} Codex facts gateway argv is malformed"
            )
        try:
            command_resolved = resolve_gateway_invocation(
                command_argv,
                skill_source=options.skill_source,
                invocation_skill_source=invocation_skill_source,
                shim_directory=task_root / "broker" / "bin",
            )
        except GatewayInvocationError as exc:
            raise CampaignEvidenceError(
                f"{label} Codex facts gateway argv cannot resolve: {exc}"
            ) from exc
        if (
            command_resolved.normalized_model_argv
            != resolved.normalized_model_argv
            or command_resolved.argv_sha256 != resolved.argv_sha256
        ):
            raise CampaignEvidenceError(
                f"{label} broker record is not uniquely aligned to Codex facts"
            )
        try:
            if step.subcommand == "stream-topic":
                observed_payload = _extract_topic_stream_records(
                    str(command_record.get("aggregated_output", ""))
                )[-1]
            else:
                observed_payload = json.loads(
                    str(command_record.get("aggregated_output", "")).strip()
                )
        except (json.JSONDecodeError, GatewayInvocationError) as exc:
            raise CampaignEvidenceError(
                f"{label} Codex command output is not the broker JSON payload"
            ) from exc
        if observed_payload != payload:
            raise CampaignEvidenceError(
                f"{label} Codex command output differs from broker payload"
            )
        if "agent_result" in observed_payload and list(observed_payload)[-1] != "agent_result":
            raise CampaignEvidenceError(
                f"{label} Codex command output does not keep agent_result final"
            )
        if (
            step.subcommand.startswith("draft-")
            or step.subcommand == "preview-from-draft"
        ):
            try:
                replay._validate_operation_draft_payload(  # noqa: SLF001
                    step,
                    observed_payload,
                )
            except Exception as exc:
                raise CampaignEvidenceError(
                    f"{label} Draft response cannot replay protocol step "
                    f"{step.name}: {exc}"
                ) from exc
        if submitted_draft_actions is not None:
            replay._submitted_draft_actions_by_step[step.name] = (  # noqa: SLF001
                submitted_draft_actions
            )
        replay._payloads_by_step[step.name] = payload  # noqa: SLF001
        replay._next_step = index  # noqa: SLF001


def _validate_heavy_v3_broker_subscription_ack_record(
    value: Any,
    *,
    record: Mapping[str, Any],
    task_root: Path,
    label: str,
    expected_step_name: str,
) -> Mapping[str, Any]:
    """Validate the broker-owned ACK facts independently of runner checks."""

    keys = {
        "contract",
        "ack_contract",
        "step_name",
        "topic",
        "ack_path",
        "ack_file_sha256",
        "nonce_sha256",
        "runner_parent_process_id",
        "gateway_process_id",
        "subscribed_at_unix_ns",
        "subscribed_at_monotonic_ns",
        "step_started_at_unix_ns",
        "validated_at_unix_ns",
        "step_finished_at_unix_ns",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CampaignEvidenceError(f"{label} has an invalid closed shape")
    ack_path = value.get("ack_path")
    expected_directory = task_root / "broker" / "evidence"
    parent_process_id = value.get("runner_parent_process_id")
    child_process_id = value.get("gateway_process_id")
    subscribed = value.get("subscribed_at_unix_ns")
    subscribed_monotonic = value.get("subscribed_at_monotonic_ns")
    started = value.get("step_started_at_unix_ns")
    validated = value.get("validated_at_unix_ns")
    finished = value.get("step_finished_at_unix_ns")
    if (
        value.get("contract") != VALIDATED_SUBSCRIPTION_ACK_CONTRACT
        or value.get("ack_contract") != TOPIC_ACK_CONTRACT
        or value.get("step_name") != expected_step_name
        or value.get("topic") != SOUNDBANK_TOPIC
        or not isinstance(ack_path, str)
        or Path(ack_path).parent != expected_directory
        or not Path(ack_path).name.startswith("subscription-ack-")
        or not Path(ack_path).name.endswith(".json")
        or not _sha256_text_value(value.get("ack_file_sha256"))
        or not _sha256_text_value(value.get("nonce_sha256"))
        or type(parent_process_id) is not int
        or parent_process_id <= 0
        or type(child_process_id) is not int
        or child_process_id <= 0
        or child_process_id == parent_process_id
        or type(subscribed) is not int
        or subscribed <= 0
        or type(subscribed_monotonic) is not int
        or subscribed_monotonic <= 0
        or type(started) is not int
        or type(validated) is not int
        or type(finished) is not int
        or started != record.get("started_at_unix_ns")
        or finished != record.get("finished_at_unix_ns")
        or not started <= subscribed <= validated <= finished
    ):
        raise CampaignEvidenceError(
            f"{label} hash, PID, path, or exact wall-clock join is invalid"
        )
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validate_heavy_v3_gateway_payload(
    payload: Mapping[str, Any],
    *,
    step: Any,
    runner_exit_code: Any,
    expected_project_modification_policy: str | None = None,
) -> None:
    allowed_contracts = (
        frozenset({GATEWAY_RESULT_CONTRACT})
        if step.allowed_exit_codes == (2,)
        else gateway_payload_contracts(step.subcommand)
    )
    if payload.get("contract") not in allowed_contracts:
        raise CampaignEvidenceError("heavy broker payload contract is invalid")
    context = payload.get("session_context")
    introduction = (
        context.get("one_time_introduction")
        if isinstance(context, Mapping)
        else None
    )
    facts = (
        introduction.get("facts")
        if isinstance(introduction, Mapping)
        else None
    )
    if expected_project_modification_policy is not None and (
        not isinstance(context, Mapping)
        or context.get("project_modification_policy")
        != expected_project_modification_policy
        or context.get("available_project_modification_policies")
        != ["read_only", "ask_before_changes", "allow_changes"]
        or not isinstance(facts, Mapping)
        or facts.get("project_modification_policy")
        != expected_project_modification_policy
        or facts.get("available_project_modification_policies")
        != ["read_only", "ask_before_changes", "allow_changes"]
    ):
        raise CampaignEvidenceError(
            "heavy broker payload session policy is misbound"
        )
    if step.subcommand == "transaction-show":
        try:
            validate_transaction_show_confirmation_payload(payload)
        except GatewayInvocationError as exc:
            raise CampaignEvidenceError(
                f"heavy transaction-show confirmation binding is invalid: {exc}"
            ) from exc
    if step.terminal_execute:
        if payload.get("command") != "execute" or payload.get("automatic_retry") is not False:
            raise CampaignEvidenceError("terminal execute payload is invalid")
        if payload.get("ok") is True:
            valid = (
                payload.get("status") == "executed_unverified"
                and payload.get("state") == "executed_unverified"
                and payload.get("executed") is True
                and payload.get("verified") is False
                and runner_exit_code in {0, 2}
            )
        else:
            valid = (
                payload.get("ok") is False
                and payload.get("status") == "indeterminate"
                and payload.get("state") == "indeterminate"
                and runner_exit_code == 2
            )
        if not valid:
            raise CampaignEvidenceError("terminal execute payload state is invalid")
        return
    if step.allowed_exit_codes == (0, 2):
        successful = (
            runner_exit_code == 0
            and payload.get("ok") is True
            and payload.get("command") == "execute"
        )
        indeterminate = (
            runner_exit_code == 2
            and payload.get("ok") is False
            and payload.get("command") == "execute"
            and payload.get("status") == "indeterminate"
            and payload.get("state") == "indeterminate"
            and payload.get("automatic_retry") is False
        )
        if not (successful or indeterminate):
            raise CampaignEvidenceError(
                "branching execute payload state is invalid"
            )
        return
    if step.allowed_exit_codes == (0,):
        if payload.get("ok") is not True or payload.get("command") != step.subcommand:
            raise CampaignEvidenceError("successful gateway payload is invalid")
        return
    if (
        step.allowed_exit_codes != (2,)
        or payload.get("ok") is not False
        or payload.get("error_code") != step.expected_error_code
        or payload.get("command") != step.expected_result_command
    ):
        raise CampaignEvidenceError("structured-error gateway payload is invalid")


def _validate_heavy_v3_turn_grade(
    value: Any,
    *,
    index: int,
    turn_root: Path,
    expected_thread_id: str,
    expected_prompt: str,
    task_root: Path,
    options: CampaignOptions,
    previous_broker_prefix: int,
    expected_broker_prefix: int,
    expected_steps: Sequence[Any],
    version: str,
    expected_skill_reads: Sequence[str],
    expected_skill_read_schedule: Sequence[Sequence[str]],
    prompt_provenance: PromptProvenanceEvidence,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Mapping) or set(value) != {
        "index",
        "prompt_sha256",
        "broker_prefix_count",
        "reconciliation",
        "common_gates",
        "errors",
        "passed",
    }:
        raise CampaignEvidenceError("passing heavy turn grade is malformed")
    common_gates = value.get("common_gates")
    errors = value.get("errors")
    reconciliation = value.get("reconciliation")
    prompt_sha256 = value.get("prompt_sha256")
    if (
        value.get("index") != index
        or value.get("passed") is not True
        or not isinstance(prompt_sha256, str)
        or _SHA256_RE.fullmatch(prompt_sha256) is None
        or not isinstance(common_gates, Mapping)
        or not _HEAVY_V3_REQUIRED_COMMON_GATES.issubset(common_gates)
        or any(common_gates.get(key) is not True for key in common_gates)
        or errors != []
        or not isinstance(reconciliation, Mapping)
        or reconciliation.get("passed") is not True
        or reconciliation.get("errors") != []
        or value.get("broker_prefix_count") != expected_broker_prefix
        or set(reconciliation)
        != {"passed", "observed_command_count", "accepted_record_count", "errors"}
        or reconciliation.get("observed_command_count") != expected_broker_prefix
        or reconciliation.get("accepted_record_count") != expected_broker_prefix
    ):
        raise CampaignEvidenceError(
            "passing heavy turn lacks complete no-memory/no-bypass gates"
        )
    archived_grade = load_strict_regular_json(turn_root / "turn-grade.json")
    if archived_grade != value:
        raise CampaignEvidenceError(
            "passing heavy task-result turn grade differs from its archived grade"
        )
    prompt = _load_strict_regular_text(turn_root / "prompt.txt")
    if not prompt.endswith("\n") or not prompt[:-1]:
        raise CampaignEvidenceError("passing heavy turn prompt archive is malformed")
    if prompt[:-1] != expected_prompt:
        raise CampaignEvidenceError(
            "passing heavy turn prompt differs from its reviewed materialization"
        )
    if hashlib.sha256(prompt[:-1].encode("utf-8")).hexdigest() != prompt_sha256:
        raise CampaignEvidenceError("passing heavy turn prompt digest is invalid")
    final_response = _load_strict_regular_text(turn_root / "final.txt")
    if not final_response.strip():
        raise CampaignEvidenceError("passing heavy turn has an empty final response")
    _load_strict_regular_text(turn_root / "events.jsonl")
    _load_strict_regular_text(turn_root / "stderr.txt")
    facts = load_strict_regular_json(turn_root / "codex-facts.json")
    if (
        not isinstance(facts, Mapping)
        or final_response != str(facts.get("final_response", "")) + "\n"
    ):
        raise CampaignEvidenceError(
            "passing heavy final response differs from Codex facts"
        )
    gateway_records = _validate_heavy_v3_codex_facts(
        facts,
        expected_thread_id=expected_thread_id,
        expected_prompt=expected_prompt,
        turn_index=index,
        turn_root=turn_root,
        task_root=task_root,
        options=options,
        expected_steps=expected_steps,
        version=version,
        expected_skill_reads=expected_skill_reads,
        expected_skill_read_schedule=expected_skill_read_schedule,
        archived_common_gates=common_gates,
        prompt_provenance=prompt_provenance,
    )
    expected_delta = expected_broker_prefix - previous_broker_prefix
    if expected_delta < 0 or len(gateway_records) != expected_delta:
        raise CampaignEvidenceError(
            "passing heavy turn gateway command count differs from its sealed prefix delta"
        )
    return gateway_records


def _validate_heavy_v3_codex_facts(
    value: Any,
    *,
    expected_thread_id: str,
    expected_prompt: str,
    turn_index: int,
    turn_root: Path,
    task_root: Path,
    options: CampaignOptions,
    expected_steps: Sequence[Any],
    version: str,
    expected_skill_reads: Sequence[str],
    expected_skill_read_schedule: Sequence[Sequence[str]],
    archived_common_gates: Mapping[str, Any],
    prompt_provenance: PromptProvenanceEvidence,
) -> tuple[Mapping[str, Any], ...]:
    required_keys = {
        "command",
        "exit_status",
        "duration_seconds",
        "timed_out",
        "thread_id",
        "final_response",
        "usage",
        "event_count",
        "collab_call_count",
        "file_change_count",
        "prompt_audit",
        "isolation_audit",
        "session_audit",
        "command_facts",
        "created_files",
        "modified_files",
        "deleted_files",
        "created_source_files",
        "modified_source_files",
        "deleted_source_files",
        "skill_tree_sha256_before",
        "skill_tree_sha256_after",
        "skill_tree_unchanged",
    }
    if not isinstance(value, Mapping) or set(value) != required_keys:
        raise CampaignEvidenceError("passing heavy turn facts are malformed")
    command_records = _validate_heavy_v3_events_against_facts(
        turn_root / "events.jsonl",
        value,
        label="passing heavy turn",
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    prompt_audit = value.get("prompt_audit")
    isolation_audit = value.get("isolation_audit")
    session_audit = value.get("session_audit")
    command_facts = value.get("command_facts")
    if (
        value.get("exit_status") != 0
        or value.get("timed_out") is not False
        or value.get("thread_id") != expected_thread_id
        or value.get("collab_call_count") != 0
        or value.get("file_change_count") != 0
        or value.get("skill_tree_unchanged") is not True
        or value.get("skill_tree_sha256_before")
        != value.get("skill_tree_sha256_after")
        or not isinstance(prompt_audit, Mapping)
        or prompt_audit.get("passed") is not True
        or prompt_audit.get("has_memory") is not False
        # This digest covers Codex's serialized prompt-input payload, not the
        # raw user prompt archived above.  Keep both hash gates independent:
        # the grade is bound to prompt.txt, while this value must itself be a
        # well-formed SHA-256 digest from the prompt isolation audit.
        or not isinstance(prompt_audit.get("prompt_sha256"), str)
        or _SHA256_RE.fullmatch(str(prompt_audit.get("prompt_sha256"))) is None
        or not isinstance(isolation_audit, Mapping)
        or isolation_audit.get("passed") is not True
        or not isinstance(session_audit, Mapping)
        or session_audit.get("passed") is not True
        or not isinstance(command_facts, Mapping)
    ):
        raise CampaignEvidenceError(
            "passing heavy turn facts do not prove a clean memory-isolated task"
        )
    config = CodexHarnessConfig(
        workspace=task_root / "agent-workspace",
        skill_source=options.skill_source,
        codex_binary=options.codex_binary,
        windows_powershell_core_host=options.windows_powershell_core_host,
        auth_json=options.auth_json,
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier,
        timeout_seconds=options.timeout_seconds,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        developer_instructions=(
            semantic_task_developer_instructions(
                options.skill_source / "scripts" / "run.py",
                task_skill_source=(
                    task_root
                    / "agent-workspace"
                    / ".agents"
                    / "skills"
                    / "waapi-skill"
                ),
                expected_skill_reads=expected_skill_read_schedule,
                base_developer_instructions=(
                    semantic_skill_bootstrap_developer_instructions(
                        options.skill_source / "scripts" / "run.py"
                    )
                ),
            )
            if options.profile in SEMANTIC_BOOTSTRAP_PROFILE_IDS
            else ""
        ),
    )
    expected_command = (
        build_task_exec_command(
            config,
            prompt=expected_prompt,
            writable_dir=turn_root,
        )
        if turn_index == 1
        else build_task_resume_command(
            config,
            thread_id=expected_thread_id,
            prompt=expected_prompt,
            writable_dir=turn_root,
        )
    )
    if value.get("command") != expected_command:
        raise CampaignEvidenceError(
            "heavy Codex command differs from exact no-memory initial/resume argv"
        )
    for key in (
        "created_files",
        "modified_files",
        "deleted_files",
        "created_source_files",
        "modified_source_files",
        "deleted_source_files",
    ):
        if value.get(key) != []:
            raise CampaignEvidenceError(
                f"passing heavy turn unexpectedly records {key}"
            )
    expected_command_fact_keys = {
        "commands",
        "inline_python_commands",
        "direct_waapi_client_commands",
        "write_like_commands",
        "gateway_commands",
        "discovery_commands",
        "skill_read",
        "gateway_before_discovery",
        "command_records",
        "gateway_attempt_commands",
        "gateway_subcommands",
        "gateway_results",
        "gateway_evidence_apis",
        "allowed_read_commands",
        "skill_read_files",
        "unexpected_commands",
        "non_gateway_unexpected_commands",
    }
    if set(command_facts) != expected_command_fact_keys:
        raise CampaignEvidenceError("heavy command-facts schema is not closed")
    expected_gateway_errors = tuple(
        CodexGatewayErrorExpectation(
            command=step.expected_result_command,
            error_code=step.expected_error_code,
        )
        for step in expected_steps
        if step.allowed_exit_codes == (2,)
    )
    classified = classify_task_commands(
        command_records,
        workspace=task_root / "agent-workspace",
        skill_source=options.skill_source,
        expected_gateway_subcommands=tuple(
            dict.fromkeys(step.subcommand for step in expected_steps)
        ),
        expected_gateway_errors=expected_gateway_errors,
        expected_wwise_version=version,
    )
    expected_command_facts = _json_canonical_value(asdict(classified))
    if command_facts != expected_command_facts:
        raise CampaignEvidenceError(
            "heavy command facts differ from the classification of events.jsonl"
        )

    records = classified.command_records
    allowed_reads = tuple(classified.allowed_read_commands)
    read_files = tuple(classified.skill_read_files)
    expected_reads = tuple(expected_skill_reads)
    gateway_attempt_records = tuple(
        record
        for record in records
        if record.command in classified.gateway_attempt_commands
    )
    terminal_exit2_count = sum(
        step.terminal_execute and record.exit_code == 2
        for step, record in zip(
            expected_steps,
            gateway_attempt_records,
            strict=False,
        )
    )
    try:
        prompt_asset_reads = validated_prompt_asset_cat_commands(
            records,
            provenance=prompt_provenance,
            turn_index=turn_index,
        )
    except PromptAssetReadError as exc:
        raise CampaignEvidenceError(
            f"passing heavy prompt-asset read proof is invalid: {exc}"
        ) from exc
    terminal_unexpected = remove_validated_command_occurrences(
        classified.unexpected_commands,
        prompt_asset_reads,
    )
    non_gateway_unexpected = remove_validated_command_occurrences(
        classified.non_gateway_unexpected_commands,
        prompt_asset_reads,
    )
    expected_terminal_unexpected = (
        len(terminal_unexpected) == terminal_exit2_count
        and all(
            command in classified.gateway_attempt_commands
            for command in terminal_unexpected
        )
    )
    expected_common_gates = {
        "memory_isolated": (
            isolation_audit.get("passed") is True
            and prompt_audit.get("has_memory") is False
        ),
        "one_completed_turn": (
            value.get("exit_status") == 0
            and value.get("timed_out") is False
            and session_audit.get("passed") is True
            and value.get("file_change_count") == 0
        ),
        "one_target_skill": prompt_audit.get("passed") is True,
        "no_collaboration": value.get("collab_call_count") == 0,
        "skill_reads_exact": (
            read_files == expected_reads and len(allowed_reads) == len(read_files)
        ),
        "read_prefix_exact": (
            tuple(
                record.command
                for index, record in enumerate(records)
                if index
                not in recoverable_preprocess_attempt_indexes(records)
            )[: len(allowed_reads)]
            == allowed_reads
        ),
        "gateway_count_exact": (
            len(classified.gateway_attempt_commands) == len(expected_steps)
        ),
        "no_other_commands": (
            len(records)
            - len(
                recoverable_preprocess_attempt_indexes(records)
            )
            == len(allowed_reads)
            + len(prompt_asset_reads)
            + len(expected_steps)
        ),
        "no_discovery": not classified.discovery_commands,
        "no_direct_waapi": not classified.direct_waapi_client_commands,
        "no_write_like": not classified.write_like_commands,
        "no_unexpected_commands": (
            expected_terminal_unexpected
            and not non_gateway_unexpected
        ),
        "no_files_changed": (
            not value.get("created_files")
            and not value.get("modified_files")
            and not value.get("deleted_files")
            and not value.get("created_source_files")
            and not value.get("modified_source_files")
            and not value.get("deleted_source_files")
            and value.get("skill_tree_unchanged") is True
        ),
    }
    if (
        set(expected_common_gates) != _HEAVY_V3_REQUIRED_COMMON_GATES
        or archived_common_gates != expected_common_gates
        or not all(expected_common_gates.values())
    ):
        mismatched = {
            key: {
                "archived": archived_common_gates.get(key),
                "recomputed": expected_common_gates.get(key),
            }
            for key in sorted(expected_common_gates)
            if archived_common_gates.get(key) != expected_common_gates.get(key)
            or expected_common_gates.get(key) is not True
        }
        raise CampaignEvidenceError(
            "passing heavy turn common gates cannot be recomputed from raw evidence: "
            f"{mismatched}"
        )
    return tuple(
        _json_canonical_value(asdict(record))
        for record in records
        if record.command in classified.gateway_attempt_commands
    )


def _validate_heavy_v3_events_against_facts(
    events_path: Path,
    facts: Mapping[str, Any],
    *,
    label: str,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> tuple[Any, ...]:
    """Rebuild stable Codex facts from archived JSONL instead of trusting child JSON."""

    text = _load_strict_regular_text(events_path)
    invalid_count = count_invalid_jsonl_lines(text)
    events = parse_jsonl_events(text)
    started_command_ids: list[str] = []
    completed_command_ids: list[str] = []
    started_commands: dict[str, str | None] = {}
    completed_commands: dict[str, str | None] = {}
    for event in events:
        item = event.get("item")
        if not isinstance(item, Mapping) or item.get("type") != "command_execution":
            continue
        event_type = event.get("type")
        if event_type not in {"item.started", "item.completed"}:
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise CampaignEvidenceError(
                f"{label} command event has no stable item id"
            )
        if event_type == "item.started":
            started_command_ids.append(item_id)
            started_commands[item_id] = (
                item.get("command")
                if isinstance(item.get("command"), str)
                else None
            )
        else:
            completed_command_ids.append(item_id)
            completed_commands[item_id] = (
                item.get("command")
                if isinstance(item.get("command"), str)
                else None
            )
    if (
        len(started_command_ids) != len(set(started_command_ids))
        or len(completed_command_ids) != len(set(completed_command_ids))
        or set(started_command_ids) != set(completed_command_ids)
        or any(
            started_commands[item_id] is not None
            and completed_commands[item_id] is not None
            and started_commands[item_id] != completed_commands[item_id]
            for item_id in started_commands
        )
    ):
        raise CampaignEvidenceError(
            f"{label} command event item ids are duplicated or mispaired"
        )
    session = audit_session_events(
        events,
        invalid_json_line_count=invalid_count,
    )
    expected_session = asdict(session)
    expected_session["passed"] = session.passed
    command_records = completed_command_records(
        events,
        windows_powershell_core_host=windows_powershell_core_host,
    )
    expected_records = [asdict(item) for item in command_records]
    command_facts = facts.get("command_facts")
    expected_thread_id = session.thread_ids[0] if len(session.thread_ids) == 1 else ""
    if (
        invalid_count != 0
        or facts.get("event_count") != len(events)
        or facts.get("session_audit") != _json_canonical_value(expected_session)
        or not isinstance(command_facts, Mapping)
        or command_facts.get("command_records")
        != _json_canonical_value(expected_records)
        or command_facts.get("commands")
        != [item.command for item in command_records]
        or facts.get("final_response") != final_agent_message(events)
        or facts.get("usage") != turn_usage(events)
        or facts.get("thread_id") != expected_thread_id
        or facts.get("collab_call_count") != session.collab_call_count
        or facts.get("file_change_count") != session.file_change_count
    ):
        raise CampaignEvidenceError(
            f"{label} Codex facts cannot be reconstructed from events.jsonl"
        )
    return command_records


def _json_canonical_value(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _heavy_v3_business_plan_fixture_spec(
    plan_value: Any,
    *,
    expected_unit: Any,
) -> dict[str, str]:
    """Recompute the plan fixture digest from runner-independent source truth."""

    if not isinstance(plan_value, Mapping):
        raise CampaignEvidenceError("heavy business-oracle plan is not an object")
    fixture_spec = plan_value.get("fixture_spec")
    if not isinstance(fixture_spec, Mapping) or set(fixture_spec) != {
        "kind",
        "sha256",
    }:
        raise CampaignEvidenceError(
            "heavy business-oracle plan fixture specification is invalid"
        )
    kind = fixture_spec.get("kind")
    scenario = getattr(expected_unit, "scenario", None)
    api = getattr(scenario, "api", None)
    if _heavy_v3_integration_workflow_id(expected_unit) is not None:
        digest = fixture_spec.get("sha256")
        if (
            kind != WORKFLOW_FIXTURE_KIND
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
        ):
            raise CampaignEvidenceError(
                "integration workflow business-oracle fixture identity is invalid"
            )
        return {"kind": str(kind), "sha256": digest}
    typed_kinds = {
        "ak.wwise.core.object.get": "object_materialized_v1",
        "ak.wwise.core.object.create": "object_materialized_v1",
        "ak.wwise.core.object.set": "object_materialized_v1",
        "ak.wwise.core.audio.convert": "audio_conversion_materialized_v1",
        "ak.wwise.core.mediaPool.get": "media_pool_materialized_v1",
        "ak.wwise.core.getInfo": DIRECT_FIXTURE_KIND,
        "ak.wwise.core.executeLuaScript": DIRECT_FIXTURE_KIND,
    }
    import_apis = {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
    }
    soundbank_apis = {
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
        SOUNDBANK_TOPIC,
    }
    cli_apis = {
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        HEAVY_V3_MIGRATION_API,
    }
    if api in import_apis:
        static_expectation = plan_value.get("static_expectation")
        schema_version = (
            static_expectation.get("family_schema_version")
            if isinstance(static_expectation, Mapping)
            else None
        )
        if schema_version == IMPORT_BUSINESS_PLAN_SCHEMA:
            expected_kind = IMPORT_FIXTURE_KIND
        elif schema_version == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA:
            expected_kind = COMPOUND_IMPORT_FIXTURE_KIND
        else:
            raise CampaignEvidenceError(
                "heavy typed import business-oracle fixture identity is invalid"
            )
        typed_kinds[api] = expected_kind
    elif api in soundbank_apis:
        count = _heavy_v3_primary_dispatch_count(expected_unit)
        typed_kinds[api] = (
            "soundbank_topic_materialized_v1"
            if api == SOUNDBANK_TOPIC
            else "soundbank_refusal_materialized_v1"
            if count == 0
            else "soundbank_function_materialized_v1"
        )
    elif api in cli_apis:
        typed_kinds[api] = "cli_prepared_runtime_v1"
    if api in typed_kinds:
        digest = fixture_spec.get("sha256")
        if kind != typed_kinds[api] or not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise CampaignEvidenceError(
                "heavy typed business-oracle fixture identity is invalid"
            )
        # The common envelope only establishes the immutable receipt binding.
        # The family validator immediately below independently recomputes this
        # digest from the closed static/live sections.
        return {"kind": kind, "sha256": digest}
    if kind == "object_recipe":
        fixture_value = _heavy_v3_plan_json_value(
            build_object_heavy_v3_recipe(
                _heavy_v3_base_scenario_id(expected_unit),
                version=str(getattr(expected_unit, "version", "")),
            )
        )
    elif kind == "scenario_fixture":
        fixture_value = _heavy_v3_plan_json_value(
            getattr(scenario, "fixture", None)
        )
    else:
        raise CampaignEvidenceError(
            "heavy business-oracle plan fixture kind is unsupported"
        )
    return {"kind": kind, "sha256": _canonical_sha256(fixture_value)}


def _validate_heavy_v3_typed_business_plan(
    plan_value: Mapping[str, Any],
    *,
    expected_unit: Any,
    provenance: PromptProvenanceEvidence,
    direct_status_payload: Mapping[str, Any] | None = None,
    direct_sandbox_project: str | None = None,
) -> (
    ObjectBusinessPlanSections
    | ImportBusinessPlanSections
    | AudioMediaBusinessPlanSections
    | SoundBankBusinessPlanSections
    | CliBusinessPlanSections
    | WorkflowBusinessPlanSections
    | DirectBusinessPlanSections
    | None
    ):
    """Parse and independently validate one supported family plan archive."""

    scenario = getattr(expected_unit, "scenario", None)
    api = str(getattr(scenario, "api", ""))
    protocol = provenance.protocol
    sections: (
        ObjectBusinessPlanSections
        | ImportBusinessPlanSections
        | AudioMediaBusinessPlanSections
        | SoundBankBusinessPlanSections
        | CliBusinessPlanSections
        | WorkflowBusinessPlanSections
        | DirectBusinessPlanSections
        | None
    )
    workflow_id = _heavy_v3_integration_workflow_id(expected_unit)
    if workflow_id is not None:
        sections = parse_workflow_business_plan_sections(plan_value)
        _validate_integration_workflow_business_plan(
            sections,
            expected_unit=expected_unit,
            provenance=provenance,
        )
        return sections
    if api in {
        "ak.wwise.core.getInfo",
        "ak.wwise.core.executeLuaScript",
    }:
        sections = parse_direct_business_plan_sections(plan_value)
        validate_direct_business_plan_archive(
            sections,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            api=api,
            version=str(getattr(expected_unit, "version", "")),
            protocol_steps=tuple(
                {"name": step.name, "subcommand": step.subcommand}
                for step in protocol.steps
            ),
            status_payload=direct_status_payload,
            sandbox_project=direct_sandbox_project,
        )
        return sections
    if api in {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }:
        parsed = parse_object_business_plan_sections(plan_value)
        recipe = build_object_heavy_v3_recipe(
            _heavy_v3_base_scenario_id(expected_unit),
            version=str(getattr(expected_unit, "version", "")),
        )
        unit_id = getattr(expected_unit, "unit_id", None)
        if unit_id in {
            "TYP21-QUERY-OBJECT-GET",
            "TYP23-QUERY-OBJECT-GET",
        }:
            recipe = typed_input_business_query_recipe(
                recipe,
                unit_id=str(unit_id),
            )
        elif unit_id == (
            "TYP21-DEDICATED-OBJECT-CREATE"
        ):
            recipe = typed_input_merge_recipe(
                recipe,
                unit_id="TYP21-DEDICATED-OBJECT-CREATE",
            )
        elif unit_id == (
            TYPED_PROFILE_RENAME_UNIT_ID
        ):
            recipe = typed_input_rename_recipe(
                recipe,
                unit_id=TYPED_PROFILE_RENAME_UNIT_ID,
            )
        sections = validate_archived_object_business_plan(
            plan_value,
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
            verify_files=False,
            profile_unit_id=(
                str(getattr(expected_unit, "unit_id", ""))
                if getattr(expected_unit, "unit_id", None)
                in {
                    *TYPED_PROFILE_OBJECT_METADATA_UNITS,
                    TYPED_PROFILE_QUERY_REPAIR_UNIT_ID,
                    TYPED_PROFILE_RENAME_UNIT_ID,
                }
                else None
            ),
        )
        if parsed.writer_kwargs() != sections.writer_kwargs():
            raise CampaignEvidenceError(
                "heavy object typed-plan parse/archive projections differ"
            )
    elif api in {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
    }:
        parsed = parse_import_business_plan_sections(plan_value)
        sections = validate_import_business_plan_archive(
            parsed,
            scenario=scenario,
            protocol=protocol,
            verify_files=False,
        )
    elif api in {
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.mediaPool.get",
    }:
        sections = parse_audio_media_business_plan_sections(plan_value)
        validate_audio_media_business_plan_archive(
            sections,
            protocol,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            api=api,
            version=str(getattr(expected_unit, "version", "")),
            reviewed_scenario_fixture=getattr(scenario, "fixture", None),
        )
    elif api in {
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
        SOUNDBANK_TOPIC,
    }:
        sections = parse_soundbank_business_plan_sections(plan_value)
        validate_soundbank_business_plan_archive(
            sections,
            protocol,
            scenario={
                "scenario_id": _heavy_v3_base_scenario_id(expected_unit),
                "api": api,
                "version": str(getattr(expected_unit, "version", "")),
                "primary_dispatch_count": _heavy_v3_primary_dispatch_count(
                    expected_unit
                ),
                "fixture": getattr(scenario, "fixture", None),
            },
        )
        provenance_scenario_root = provenance.payload.get("scenario_root")
        provenance_owned_root = provenance.payload.get("owned_root")
        if (
            not isinstance(provenance_scenario_root, str)
            or not isinstance(provenance_owned_root, str)
        ):
            raise CampaignEvidenceError(
                "SoundBank typed plan lacks independent scenario authority"
            )
        expected_owned_root = str(
            (Path(provenance_scenario_root) / "owned").resolve(strict=False)
        )
        if (
            provenance_owned_root != expected_owned_root
            or sections.static_expectation.get("io_root") != expected_owned_root
        ):
            raise CampaignEvidenceError(
                "SoundBank typed plan io_root differs from scenario-owned authority"
            )
    elif api in {
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        HEAVY_V3_MIGRATION_API,
    }:
        parsed = parse_cli_business_plan_sections(plan_value)
        sections = validate_cli_business_plan_archive(
            parsed,
            scenario=scenario,
            version=str(getattr(expected_unit, "version", "")),
            protocol=protocol,
            verify_files=False,
        )
    else:
        return None

    static = sections.static_expectation
    expected_identity = {
        "scenario_id": _heavy_v3_base_scenario_id(expected_unit),
        "version": str(getattr(expected_unit, "version", "")),
        "api": api,
    }
    if any(static.get(key) != value for key, value in expected_identity.items()):
        raise CampaignEvidenceError(
            "heavy typed-plan static identity differs from its common envelope"
        )
    if (
        not isinstance(sections, SoundBankBusinessPlanSections)
        and static.get("family") != business_family_for_api(api)
    ):
        raise CampaignEvidenceError(
            "heavy typed-plan family differs from its common envelope"
        )
    expected_count = _heavy_v3_primary_dispatch_count(expected_unit)
    primary_steps = sections.payload_bindings.get("primary_steps")
    if isinstance(sections, SoundBankBusinessPlanSections) and api == SOUNDBANK_TOPIC:
        dispatch_invalid = (
            expected_count < 1
            or not isinstance(primary_steps, list)
            or len(primary_steps) != 1
            or primary_steps[0]
            not in {"soundbank.generated.wait", "soundbank.generated.stream"}
        )
    else:
        dispatch_invalid = (
            not isinstance(primary_steps, list)
            or (expected_count == 0 and primary_steps != [])
            or (expected_count > 0 and len(primary_steps) != expected_count)
        )
    if dispatch_invalid:
        raise CampaignEvidenceError(
            "heavy typed-plan dispatch partition differs from expected unit"
        )
    return sections


def _heavy_v3_plan_json_value(value: Any) -> Any:
    """Mirror the runner's strict JSON projection without trusting its plan."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _heavy_v3_plan_json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _heavy_v3_plan_json_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_heavy_v3_plan_json_value(nested) for nested in value]
    if isinstance(value, Path):
        return str(value)
    return repr(value)


def _heavy_v3_integration_workflow_id(expected_unit: Any) -> str | None:
    value = getattr(expected_unit, "workflow_id", None)
    if value in _INTEGRATION_WORKFLOW_IDS:
        return str(value)
    scenario = getattr(expected_unit, "scenario", None)
    value = getattr(scenario, "scenario_family", None)
    if value in _INTEGRATION_WORKFLOW_IDS:
        return str(value)
    return None


def _validate_integration_workflow_business_plan(
    sections: WorkflowBusinessPlanSections,
    *,
    expected_unit: Any,
    provenance: PromptProvenanceEvidence,
) -> None:
    """Rebind a workflow plan to frozen profile topology and protocol evidence."""

    workflow_id = _heavy_v3_integration_workflow_id(expected_unit)
    if workflow_id is None:
        raise CampaignEvidenceError(
            "workflow plan reached a non-integration expected unit"
        )
    static = sections.static_expectation
    live = sections.live_binding
    if (
        static.get("workflow_id") != workflow_id
        or live.get("workflow_id") != workflow_id
    ):
        raise CampaignEvidenceError(
            "integration workflow plan identity differs from the frozen unit"
        )
    transactions = static.get("transactions")
    expected_transactions = tuple(getattr(expected_unit, "transactions", ()))
    if (
        not isinstance(transactions, (list, tuple))
        or len(transactions) != len(expected_transactions)
    ):
        raise CampaignEvidenceError(
            "integration workflow transaction count differs from the frozen unit"
        )
    weather_phases = (
        "import_weather_assets",
        "configure_event_actions",
        "bind_rain_intensity_rtpc",
    )
    if (
        workflow_id == "interactive_weather_build"
        and len(expected_transactions) != len(weather_phases)
    ):
        raise CampaignEvidenceError(
            "interactive weather transaction phases differ from the frozen workflow"
        )
    expected_transaction_rows: list[dict[str, Any]] = []
    for index, (row, expected) in enumerate(
        zip(transactions, expected_transactions, strict=True),
        start=1,
    ):
        expected_row = {
            "transaction_id": f"tx{index:02d}",
            "api": getattr(expected, "api", None),
            "operation": getattr(expected, "operation", None),
            "phase": (
                weather_phases[index - 1]
                if workflow_id == "interactive_weather_build"
                else f"{workflow_id}.transaction_{index:02d}"
            ),
            "primary_step": f"tx{index:02d}.execute",
        }
        expected_transaction_rows.append(expected_row)
        if not isinstance(row, Mapping) or dict(row) != expected_row:
            raise CampaignEvidenceError(
                "integration workflow transaction topology drifted"
            )
    steps = static.get("workflow_steps")
    transaction_by_id = {
        row["transaction_id"]: row for row in expected_transaction_rows
    }
    transaction_step_kind = {
        "operation-schema": "operation_schema",
        "request-array-item": "operation_compose",
        "request-map-container": "operation_compose",
        "draft-start": "operation_compose",
        "draft-apply": "operation_compose",
        "draft-business-configure": "operation_compose",
        "draft-declare-import-batch": "operation_compose",
        "draft-bind-object": "operation_compose",
        "draft-bind-field": "operation_compose",
        "draft-discover-fields": "operation_compose",
        "query-object": "operation_compose",
        "draft-declare-field-change": "operation_compose",
        "draft-declare-switch-assignment": "operation_compose",
        "draft-declare-soundbank-plan": "operation_compose",
        "draft-declare-artifact-plan": "operation_compose",
        "draft-declare-ui-plan": "operation_compose",
        "draft-add-ui-command": "operation_compose",
        "draft-declare-new": "operation_compose",
        "draft-declare-existing": "operation_compose",
        "draft-revise-declaration": "operation_compose",
        "draft-remove-declaration": "operation_compose",
        "draft-check": "operation_compose_check",
        "preview": "preview",
        "preview-from-draft": "preview",
        "typed-operation": "preview",
        "transaction-show": "transaction_show",
        "confirm": "confirm",
        "execute": "execute",
        "verify": "verify",
    }
    expected_step_rows: list[dict[str, Any]] = []
    expected_diagnostic_rows: list[dict[str, Any]] = []
    for step in provenance.protocol.steps:
        transaction_id = (
            step.name.split(".", 1)[0]
            if step.name.startswith("tx")
            else None
        )
        transaction = transaction_by_id.get(transaction_id)
        if (
            transaction is not None
            and step.subcommand in transaction_step_kind
        ):
            expected_step_rows.append(
                {
                    "name": step.name,
                    "kind": transaction_step_kind[step.subcommand],
                    "phase": transaction["phase"],
                    "transaction_id": transaction_id,
                    "api": transaction["api"],
                }
            )
            continue
        is_diagnostic = (
            workflow_id in _INTEGRATION_QUERY_FIRST_WORKFLOW_IDS
            and transaction_id is None
            and step.subcommand == "query-object"
        )
        phase = (
            f"{workflow_id}.diagnosis"
            if is_diagnostic
            else (
                transaction["phase"]
                if (
                    workflow_id == "interactive_weather_build"
                    and transaction is not None
                )
                else f"{workflow_id}.checkpoint"
            )
        )
        expected_step_rows.append(
            {
                "name": step.name,
                "kind": "diagnostic" if is_diagnostic else "checkpoint",
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
            expectation = {
                "gateway_step": step.name,
                "bounded_live_read": True,
            }
            expected_diagnostic_rows.append(
                {
                    "evidence_id": f"{step.name}.bounded-read",
                    "step": step.name,
                    "api": "ak.wwise.core.object.get",
                    "phase": phase,
                    "expectation": expectation,
                    "expectation_sha256": hashlib.sha256(
                        canonical_json_bytes(expectation)
                    ).hexdigest(),
                }
            )
    expected_step_rows.append(
        {
            "name": "cleanup.success",
            "kind": "cleanup",
            "phase": (
                "cleanup"
                if workflow_id == "interactive_weather_build"
                else f"{workflow_id}.cleanup"
            ),
            "transaction_id": None,
            "api": None,
        }
    )
    if (
        not isinstance(steps, (list, tuple))
        or [dict(row) for row in steps if isinstance(row, Mapping)]
        != expected_step_rows
        or len(steps) != len(expected_step_rows)
    ):
        raise CampaignEvidenceError(
            "integration workflow plan steps differ from sealed broker protocol"
        )
    diagnostic_rows = static.get("diagnostic_evidence")
    if (
        not isinstance(diagnostic_rows, (list, tuple))
        or [
            dict(row)
            for row in diagnostic_rows
            if isinstance(row, Mapping)
        ]
        != expected_diagnostic_rows
        or len(diagnostic_rows) != len(expected_diagnostic_rows)
    ):
        raise CampaignEvidenceError(
            "integration diagnostic evidence differs from sealed broker protocol"
        )
    primary_steps = sections.payload_bindings.get("primary_steps")
    if not isinstance(primary_steps, (list, tuple)) or list(primary_steps) != [
        f"tx{index:02d}.execute"
        for index in range(1, len(expected_transactions) + 1)
    ]:
        raise CampaignEvidenceError(
            "integration workflow primary steps differ from its transactions"
        )
    bindings = live.get("bindings")
    if (
        not isinstance(bindings, Mapping)
        or bindings.get("version") != getattr(expected_unit, "version", None)
    ):
        raise CampaignEvidenceError(
            "integration workflow live binding has another Wwise version"
        )
    visible_values = dict(provenance.visible_values)
    if "visible_values" in bindings:
        expected_binding_keys = {"version", "visible_values"}
        if workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
            expected_binding_keys.add("baseline_manifest_sha256")
            manifest = getattr(expected_unit, "baseline_manifest", None)
            manifest_digest = getattr(manifest, "digest", None)
            if (
                getattr(manifest, "version", None)
                != getattr(expected_unit, "version", None)
                or not isinstance(manifest_digest, str)
                or _SHA256_RE.fullmatch(manifest_digest) is None
                or bindings.get("baseline_manifest_sha256")
                != manifest_digest
            ):
                raise CampaignEvidenceError(
                    "integration v2 workflow plan is not bound to its sealed baseline manifest"
                )
        if (
            set(bindings) != expected_binding_keys
            or bindings.get("visible_values") != visible_values
        ):
            raise CampaignEvidenceError(
                "integration workflow live values differ from sealed prompt provenance"
            )
    elif workflow_id == "interactive_weather_build":
        weather_root = bindings.get("weather_root")
        event_root = bindings.get("event_root")
        weather_bus = bindings.get("weather_bus")
        rain_parameter = bindings.get("rain_parameter")
        source_files = bindings.get("source_files")
        source_directory = visible_values.get("weather_source_directory")
        if (
            set(bindings)
            != {
                "version",
                "weather_root",
                "event_root",
                "weather_bus",
                "rain_parameter",
                "source_files",
                "metadata",
            }
            or not isinstance(weather_root, Mapping)
            or weather_root.get("path")
            != visible_values.get("weather_root_path")
            or not isinstance(event_root, Mapping)
            or event_root.get("path")
            != visible_values.get("weather_event_root_path")
            or not isinstance(weather_bus, Mapping)
            or weather_bus.get("path")
            != visible_values.get("weather_bus_path")
            or not isinstance(rain_parameter, Mapping)
            or rain_parameter.get("path")
            != visible_values.get("weather_game_parameter_path")
            or not isinstance(source_files, Mapping)
            or not isinstance(source_directory, str)
            or any(
                not isinstance(proof, Mapping)
                or Path(str(proof.get("path", ""))).parent
                != Path(source_directory)
                for proof in source_files.values()
            )
        ):
            raise CampaignEvidenceError(
                "interactive weather live values differ from sealed prompt provenance"
            )
    else:
        raise CampaignEvidenceError(
            "integration workflow live values omit sealed prompt provenance"
        )


def _revalidate_modification_policy_natural_behavior(
    *,
    expected_unit: Any,
    policy_mode: str,
    task_root: Path,
) -> None:
    """Recompute policy reply/notice gates from the sealed turn archives."""

    from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner

    if policy_mode not in {"read_only", "ask_before_changes", "allow_changes"}:
        raise CampaignEvidenceError("passing policy case has an invalid mode")
    scenario = getattr(expected_unit, "scenario", None)
    try:
        expected_terms = project_runner._policy_notice_change_terms(scenario)
    except Exception as exc:
        raise CampaignEvidenceError(
            f"passing policy case has no concrete notice terms: {exc}"
        ) from exc
    response_turns = (
        range(1, 3)
        if policy_mode == "read_only"
        else (1,)
        if policy_mode == "ask_before_changes"
        else ()
    )
    for turn_index in response_turns:
        final = _load_strict_regular_text(
            task_root / "turns" / f"turn-{turn_index:02d}" / "final.txt"
        )
        try:
            project_runner._require_policy_turn_response(
                SimpleNamespace(final_response=final.rstrip("\n")),
                policy=policy_mode,
                turn_index=turn_index,
                expected_change_terms=expected_terms,
            )
        except Exception as exc:
            raise CampaignEvidenceError(
                f"passing {policy_mode} turn {turn_index} natural response is invalid: {exc}"
            ) from exc
    if policy_mode != "allow_changes":
        return
    turn_root = task_root / "turns" / "turn-01"
    facts = load_strict_regular_json(turn_root / "codex-facts.json")
    command_facts = (
        facts.get("command_facts") if isinstance(facts, Mapping) else None
    )
    if not isinstance(command_facts, Mapping):
        raise CampaignEvidenceError(
            "passing allow_changes turn lacks archived command facts"
        )
    result = SimpleNamespace(
        stdout=_load_strict_regular_text(turn_root / "events.jsonl"),
        command_facts=SimpleNamespace(
            gateway_attempt_commands=tuple(
                command_facts.get("gateway_attempt_commands", ())
            ),
            gateway_subcommands=tuple(
                command_facts.get("gateway_subcommands", ())
            ),
        ),
    )
    if not project_runner._policy_notice_precedes_execute(
        result,
        expected_change_terms=expected_terms,
    ):
        raise CampaignEvidenceError(
            "passing allow_changes archive lacks a concrete notice after preview "
            "and before execute"
        )


def _validate_heavy_v3_pass_checks(
    checks: Mapping[str, Any],
    *,
    expected_unit: Any,
    expected_row: Mapping[str, Any],
    expected_thread_id: str,
    primary_count: int,
    audited_count: int,
    task_root: Path,
    prompt_evidence: HeavyV3PromptEvidence,
) -> None:
    api = str(expected_row["api"])
    runner = str(expected_row["runner"])
    scenario = getattr(expected_unit, "scenario", None)
    item_type = getattr(scenario, "item_type", None)
    primary = checks.get("primary_dispatch")
    if checks.get("task_passed") is not True or not isinstance(primary, Mapping):
        raise CampaignEvidenceError(
            "passing heavy checks lack task and primary-dispatch proof"
        )
    if runner == "cli":
        if (
            set(primary)
            != {"api", "count", "connection_lost", "connection_lost_after_dispatch"}
            or primary.get("api") != api
            or primary.get("count") != audited_count
            or not isinstance(primary.get("connection_lost"), bool)
            or not isinstance(primary.get("connection_lost_after_dispatch"), bool)
        ):
            raise CampaignEvidenceError("passing CLI primary-dispatch proof is invalid")
        connection_lost = bool(primary.get("connection_lost"))
        connection_lost_after_dispatch = bool(
            primary.get("connection_lost_after_dispatch")
        )
        # A migration may either complete before the runner shuts its control
        # server down or naturally close that server after dispatch.  Both are
        # proven runtime outcomes; only a pre-dispatch/mixed disconnect is
        # ambiguous.  Other reviewed CLI operations must stay connected.
        if (
            connection_lost != connection_lost_after_dispatch
            or (api != HEAVY_V3_MIGRATION_API and connection_lost)
            or checks.get("thread_id") != expected_thread_id
            or checks.get("first_use_intro") is not True
            or checks.get("source_template_unchanged") is not True
        ):
            raise CampaignEvidenceError(
                "passing CLI checks lack thread, intro, source, or disconnect proof"
            )
        turn_count = getattr(expected_unit, "user_turn_count", 0)
        if any(
            checks.get(f"turn_{index:02d}_response_nonempty") is not True
            for index in range(1, turn_count + 1)
        ):
            raise CampaignEvidenceError("passing CLI checks lack non-empty responses")
        _validate_heavy_v3_archived_verification(
            checks.get("business_verification"),
            api=api,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            version=str(expected_row["version"]),
            runner=runner,
            primary_count=primary_count,
            task_root=task_root,
            prompt_evidence=prompt_evidence,
            scenario_fixture=getattr(scenario, "fixture", {}),
            label="CLI business oracle",
        )
        return

    if checks.get("direct_client_closed") is not True:
        raise CampaignEvidenceError("passing project runner did not close its direct client")
    if checks.get("first_use_intro") is not True or checks.get(
        "final_response_nonempty"
    ) is not True:
        raise CampaignEvidenceError(
            "passing project checks lack intro or final-response proof"
        )
    policy_mode = getattr(
        expected_unit,
        "project_modification_policy",
        None,
    )
    if policy_mode is not None:
        _revalidate_modification_policy_natural_behavior(
            expected_unit=expected_unit,
            policy_mode=policy_mode,
            task_root=task_root,
        )
    if (
        policy_mode == "ask_before_changes"
        and (
            checks.get("policy_turn_01_project_unchanged") is not True
            or checks.get("policy_turn_01_response") is not True
        )
    ):
        raise CampaignEvidenceError(
            "passing ask_before_changes case lacks first-turn unchanged/response proof"
        )
    if (
        policy_mode == "allow_changes"
        and checks.get("allow_changes_notice_before_execute") is not True
    ):
        raise CampaignEvidenceError(
            "passing allow_changes case lacks pre-execute notice proof"
        )
    if item_type == "topic":
        publisher_count = _heavy_v3_topic_publisher_request_count(prompt_evidence)
        topic_lifecycle_steps = tuple(
            step
            for step in prompt_evidence.provenance.protocol.steps
            if step.subcommand in {"wait-topic", "stream-topic"}
        )
        expected_lifecycle = (
            topic_lifecycle_steps[0].subcommand
            if len(topic_lifecycle_steps) == 1
            else None
        )
        expected_dispatch_calls = 0 if expected_lifecycle == "stream-topic" else 1
        if (
            set(primary)
            != {
                "api",
                "gateway_dispatch_calls",
                "topic_lifecycle",
                "event_count",
            }
            or primary.get("api") != api
            or primary.get("gateway_dispatch_calls") != expected_dispatch_calls
            or primary.get("topic_lifecycle") != expected_lifecycle
            or primary.get("event_count") != audited_count
            or checks.get("topic_publisher_call_count") != publisher_count
            or type(checks.get("topic_publisher_direct_call_count")) is not int
            or checks.get("topic_publisher_direct_call_count", 0) < publisher_count
            or checks.get("topic_publisher_client_opened") is not True
            or checks.get("topic_publisher_client_closed") is not True
        ):
            raise CampaignEvidenceError("passing topic publisher/dispatch proof is invalid")
        ack_proof = checks.get("topic_subscription_ack")
        _validate_heavy_v3_topic_subscription_ack(
            ack_proof,
            api=api,
            publisher_count=publisher_count,
            task_root=task_root,
            prompt_evidence=prompt_evidence,
        )
        _validate_heavy_v3_topic_publisher_process(
            checks.get("topic_publisher_diagnostics"),
            api=api,
            publisher_count=publisher_count,
            ack_proof=ack_proof,
            prompt_evidence=prompt_evidence,
        )
        _validate_heavy_v3_archived_verification(
            checks.get("topic_verification"),
            api=api,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            version=str(expected_row["version"]),
            runner=runner,
            primary_count=primary_count,
            task_root=task_root,
            prompt_evidence=prompt_evidence,
            scenario_fixture=getattr(scenario, "fixture", {}),
            label="topic oracle",
        )
        return
    if api in {
        "ak.wwise.core.getInfo",
        "ak.wwise.core.executeLuaScript",
    }:
        expected_primary_keys = {"api", "dispatch_count"}
        if api == "ak.wwise.core.getInfo":
            expected_primary_keys.add("status_preflight_dispatch_count")
        if (
            set(primary) != expected_primary_keys
            or primary.get("api") != api
            or primary.get("dispatch_count") != audited_count
            or (
                api == "ak.wwise.core.getInfo"
                and primary.get("status_preflight_dispatch_count") != 0
            )
        ):
            raise CampaignEvidenceError(
                "passing direct primary-dispatch proof is invalid"
            )
        if api == "ak.wwise.core.executeLuaScript":
            _validate_heavy_v3_archived_verification(
                checks.get("turn_02_workflow"),
                api=api,
                scenario_id=_heavy_v3_base_scenario_id(expected_unit),
                version=str(expected_row["version"]),
                runner=runner,
                primary_count=primary_count,
                task_root=task_root,
                prompt_evidence=prompt_evidence,
                scenario_fixture=getattr(scenario, "fixture", {}),
                label="direct weak-verifier UX oracle",
            )
        _validate_heavy_v3_archived_verification(
            checks.get("business_verification"),
            api=api,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            version=str(expected_row["version"]),
            runner=runner,
            primary_count=primary_count,
            task_root=task_root,
            prompt_evidence=prompt_evidence,
            scenario_fixture=getattr(scenario, "fixture", {}),
            label="direct business oracle",
        )
        return
    if (
        set(primary) != {"api", "dispatch_count"}
        or primary.get("api") != api
        or primary.get("dispatch_count") != audited_count
    ):
        raise CampaignEvidenceError("passing project primary-dispatch proof is invalid")
    workflow_id = _heavy_v3_integration_workflow_id(expected_unit)
    if workflow_id is not None:
        expected_dispatches: dict[str, int] = {}
        for transaction in getattr(expected_unit, "transactions", ()):
            transaction_api = getattr(transaction, "api", None)
            if not isinstance(transaction_api, str):
                raise CampaignEvidenceError(
                    "integration workflow transaction has no API identity"
                )
            expected_dispatches[transaction_api] = (
                expected_dispatches.get(transaction_api, 0) + 1
            )
        workflow_dispatch = checks.get("workflow_dispatch")
        if (
            not isinstance(workflow_dispatch, Mapping)
            or set(workflow_dispatch)
            != {"expected", "observed", "total_expected_dispatches"}
            or workflow_dispatch.get("expected") != expected_dispatches
            or workflow_dispatch.get("observed") != expected_dispatches
            or workflow_dispatch.get("total_expected_dispatches")
            != sum(expected_dispatches.values())
        ):
            raise CampaignEvidenceError(
                "passing integration workflow lacks its exact mutation dispatch vector"
            )
        if workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
            required_turn_oracles = max(
                0,
                int(getattr(expected_unit, "user_turn_count", 0)) - 1,
            )
        else:
            required_turn_oracles = (
                int(getattr(expected_unit, "user_turn_count", 0))
                if workflow_id
                in {"interactive_weather_build", "alarm_diagnose_and_repair"}
                else 0
            )
        for turn_index in range(1, required_turn_oracles + 1):
            _validate_heavy_v3_archived_verification(
                checks.get(f"turn_{turn_index:02d}_workflow"),
                api=api,
                scenario_id=_heavy_v3_base_scenario_id(expected_unit),
                version=str(expected_row["version"]),
                runner=runner,
                primary_count=primary_count,
                task_root=task_root,
                prompt_evidence=prompt_evidence,
                scenario_fixture=getattr(scenario, "fixture", {}),
                label=f"integration turn {turn_index} oracle",
            )
        if "runtime_cleanup" not in checks:
            raise CampaignEvidenceError(
                "passing integration workflow lacks successful owned cleanup"
            )
        if workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
            _validate_integration_v2_cleanup(
                checks.get("runtime_cleanup"),
                workflow_id=workflow_id,
            )
        _validate_heavy_v3_archived_verification(
            checks.get("business_verification"),
            api=api,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            version=str(expected_row["version"]),
            runner=runner,
            primary_count=primary_count,
            task_root=task_root,
            prompt_evidence=prompt_evidence,
            scenario_fixture=getattr(scenario, "fixture", {}),
            label="integration workflow business oracle",
        )
        return
    if primary_count == 0:
        if (
            getattr(
                expected_unit,
                "project_modification_policy",
                None,
            )
            == "read_only"
        ):
            turn_count = int(getattr(expected_unit, "user_turn_count", 0))
            if (
                turn_count != 2
                or any(
                    checks.get(
                        f"policy_turn_{index:02d}_project_unchanged"
                    )
                    is not True
                    for index in range(1, turn_count + 1)
                )
                or any(
                    checks.get(f"policy_turn_{index:02d}_response")
                    is not True
                    for index in range(1, turn_count + 1)
                )
            ):
                raise CampaignEvidenceError(
                    "passing read_only policy case lacks per-turn unchanged/response proof"
                )
            _validate_heavy_v3_archived_verification(
                checks.get("policy_read_only_unchanged"),
                api=api,
                scenario_id=_heavy_v3_base_scenario_id(expected_unit),
                version=str(expected_row["version"]),
                runner=runner,
                primary_count=primary_count,
                task_root=task_root,
                prompt_evidence=prompt_evidence,
                scenario_fixture=getattr(scenario, "fixture", {}),
                label="read_only policy oracle",
            )
            return
        refusal_values = [
            value for key, value in checks.items() if str(key).endswith(".refusal")
        ]
        if len(refusal_values) != 1:
            raise CampaignEvidenceError(
                "passing zero-dispatch case lacks one exact refusal oracle"
            )
        _validate_heavy_v3_archived_verification(
            refusal_values[0],
            api=api,
            scenario_id=_heavy_v3_base_scenario_id(expected_unit),
            version=str(expected_row["version"]),
            runner=runner,
            primary_count=primary_count,
            task_root=task_root,
            prompt_evidence=prompt_evidence,
            scenario_fixture=getattr(scenario, "fixture", {}),
            label="zero-dispatch refusal oracle",
        )
        return
    _validate_heavy_v3_archived_verification(
        checks.get("business_verification"),
        api=api,
        scenario_id=_heavy_v3_base_scenario_id(expected_unit),
        version=str(expected_row["version"]),
        runner=runner,
        primary_count=primary_count,
        task_root=task_root,
        prompt_evidence=prompt_evidence,
        scenario_fixture=getattr(scenario, "fixture", {}),
        label="project business oracle",
    )


def _validate_heavy_v3_archived_verification(
    value: Any,
    *,
    api: str,
    scenario_id: str,
    version: str,
    runner: str,
    primary_count: int,
    task_root: Path,
    prompt_evidence: HeavyV3PromptEvidence,
    scenario_fixture: Any,
    label: str,
) -> None:
    """Dispatch a closed archive schema for every reviewed heavy API family."""

    envelope = _closed_oracle_mapping(
        value,
        {
            "contract",
            "scenario_id",
            "version",
            "api",
            "runner",
            "business_oracle_plan_sha256",
            "verification",
        },
        label=label,
    )
    if (
        envelope.get("contract") != HEAVY_V3_ORACLE_CONTRACT
        or envelope.get("scenario_id") != scenario_id
        or envelope.get("version") != version
        or envelope.get("api") != api
        or envelope.get("runner") != runner
        or envelope.get("business_oracle_plan_sha256")
        != prompt_evidence.business_oracle_plan.sha256
        or runner not in {"project", "cli"}
        or (api.startswith("ak.wwise.cli.") != (runner == "cli"))
    ):
        raise CampaignEvidenceError(f"{label} envelope identity is misbound")
    verification = envelope.get("verification")
    _validate_heavy_v3_typed_archived_verification(
        prompt_evidence.typed_sections,
        verification,
        api=api,
        primary_count=primary_count,
        task_root=task_root,
        label=label,
    )
    if (
        isinstance(prompt_evidence.typed_sections, DirectBusinessPlanSections)
        and api == "ak.wwise.core.getInfo"
    ):
        start = load_strict_regular_json(task_root.parent / "start.json")
        sandbox_project = (
            start.get("sandbox_project") if isinstance(start, Mapping) else None
        )
        try:
            validate_direct_status_archive_binding(
                prompt_evidence.typed_sections,
                status_payload=_heavy_v3_broker_step_payload(
                    task_root,
                    step_name="host.status",
                ),
                sandbox_project=(
                    sandbox_project if isinstance(sandbox_project, str) else None
                ),
            )
        except DirectBusinessPlanError as exc:
            raise CampaignEvidenceError(
                f"{label} getInfo status/lifecycle binding is invalid: {exc}"
            ) from exc
    if isinstance(
        prompt_evidence.typed_sections,
        (WorkflowBusinessPlanSections, DirectBusinessPlanSections),
    ):
        return

    if api in {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }:
        _validate_heavy_v3_object_oracle(
            verification,
            api=api,
            scenario_id=scenario_id,
            primary_count=primary_count,
            expected_final_response_sha256=_heavy_v3_final_response_sha256(task_root),
            final_response=_heavy_v3_final_response(task_root),
            gateway_payload=(
                _heavy_v3_broker_step_payload(task_root, step_name="query-object")
                if api == "ak.wwise.core.object.get"
                else None
            ),
            label=label,
        )
        return
    if api in {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
    }:
        legacy_verification = verification
        if (
            isinstance(prompt_evidence.typed_sections, ImportBusinessPlanSections)
            and prompt_evidence.typed_sections.static_expectation.get(
                "family_schema_version"
            )
            == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
        ):
            legacy_verification = _compound_import_legacy_verification(
                verification,
                label=label,
            )
        _validate_heavy_v3_import_oracle(
            legacy_verification,
            scenario_id=scenario_id,
            zero_dispatch=primary_count == 0,
            label=label,
        )
        return
    if api == "ak.wwise.core.audio.convert":
        operation_request = _heavy_v3_protocol_operation_request(prompt_evidence)
        _validate_heavy_v3_completed_transaction_protocol(
            prompt_evidence,
            expected_operation_request=operation_request,
        )
        _validate_heavy_v3_audio_conversion_oracle(
            verification,
            expected_operation_request=operation_request,
            expected_byte_change_paths=_heavy_v3_audio_byte_change_paths(
                scenario_fixture
            ),
            expected_verify_payload_sha256=(
                _heavy_v3_broker_step_payload_sha256(
                    task_root,
                    step_name="tx01.verify",
                )
            ),
            label=label,
        )
        return
    if api == "ak.wwise.core.mediaPool.get":
        _validate_heavy_v3_media_pool_oracle(
            verification,
            scenario_id=scenario_id,
            task_root=task_root,
            expected_final_response_sha256=_heavy_v3_final_response_sha256(task_root),
            final_response=_heavy_v3_final_response(task_root),
            expected_request=_heavy_v3_protocol_call_request(
                prompt_evidence,
                api="ak.wwise.core.mediaPool.get",
            ),
            label=label,
        )
        return
    if api == "ak.wwise.core.soundbank.generated":
        _validate_heavy_v3_soundbank_topic_oracle(
            verification,
            scenario_id=scenario_id,
            label=label,
        )
        return
    if api in {
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
    }:
        _validate_heavy_v3_soundbank_oracle(
            verification,
            api=api,
            scenario_id=scenario_id,
            expected_phase="zero_dispatch" if primary_count == 0 else "after_execution",
            label=label,
        )
        return
    if api in {
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.migrate",
    }:
        _validate_heavy_v3_cli_oracle(
            verification,
            api=api,
            scenario_id=scenario_id,
            label=label,
        )
        return
    raise CampaignEvidenceError(f"{label} has no closed validator for {api}")


def _validate_heavy_v3_typed_archived_verification(
    sections: (
        ObjectBusinessPlanSections
        | ImportBusinessPlanSections
        | AudioMediaBusinessPlanSections
        | SoundBankBusinessPlanSections
        | CliBusinessPlanSections
        | WorkflowBusinessPlanSections
        | DirectBusinessPlanSections
        | None
    ),
    verification: Any,
    *,
    api: str,
    primary_count: int,
    task_root: Path,
    label: str,
) -> None:
    """Join post-run evidence to the immutable typed plan before legacy checks."""

    try:
        if isinstance(sections, ObjectBusinessPlanSections):
            validate_object_archived_verification(sections, verification)
            return
        if isinstance(sections, ImportBusinessPlanSections):
            refusal_error_code = (
                _heavy_v3_broker_refusal_error_code(
                    task_root,
                    step_name="tx01.preview",
                )
                if primary_count == 0
                else None
            )
            validate_import_archived_verification(
                sections,
                verification,
                refusal_error_code=refusal_error_code,
            )
            return
        if isinstance(sections, AudioMediaBusinessPlanSections):
            if api == "ak.wwise.core.audio.convert":
                validate_audio_archived_verification(sections, verification)
                return
            if api == "ak.wwise.core.mediaPool.get":
                validate_media_archived_verification(sections, verification)
                return
            raise CampaignEvidenceError(
                f"{label} audio/media typed plan is cross-bound to {api}"
            )
        if isinstance(sections, SoundBankBusinessPlanSections):
            if sections.static_expectation.get("api") != api:
                raise CampaignEvidenceError(
                    f"{label} SoundBank typed plan is cross-bound to {api}"
                )
            refusal_error_code = sections.static_expectation.get(
                "zero_dispatch_error_code"
            )
            if refusal_error_code is not None:
                broker_error_code = _heavy_v3_broker_refusal_error_code(
                    task_root,
                    step_name="tx01.preview",
                )
                if (
                    refusal_error_code != PROCESS_REFUSAL_ERROR_CODE
                    or broker_error_code != refusal_error_code
                ):
                    raise CampaignEvidenceError(
                        f"{label} SoundBank refusal is not bound to the broker error"
                    )
            validate_soundbank_archived_verification(sections, verification)
            return
        if isinstance(sections, CliBusinessPlanSections):
            if sections.static_expectation.get("api") != api:
                raise CampaignEvidenceError(
                    f"{label} CLI typed plan is cross-bound to {api}"
                )
            validate_cli_archived_verification(sections, verification)
            return
        if isinstance(sections, WorkflowBusinessPlanSections):
            _validate_integration_workflow_verification(
                sections,
                verification,
                label=label,
            )
            return
        if isinstance(sections, DirectBusinessPlanSections):
            if sections.static_expectation.get("api") != api:
                raise CampaignEvidenceError(
                    f"{label} direct typed plan is cross-bound to {api}"
                )
            validate_direct_archived_verification(
                sections,
                verification,
                weak_report=label == "direct weak-verifier UX oracle",
            )
            return
        if api in {
            "ak.wwise.core.object.get",
            "ak.wwise.core.object.create",
            "ak.wwise.core.object.set",
            "ak.wwise.core.audio.import",
            "ak.wwise.core.audio.importTabDelimited",
            "ak.wwise.core.audio.convert",
            "ak.wwise.core.mediaPool.get",
            "ak.wwise.core.soundbank.generate",
            "ak.wwise.core.soundbank.processDefinitionFiles",
            "ak.wwise.core.soundbank.convertExternalSources",
            "ak.wwise.core.soundbank.setInclusions",
            SOUNDBANK_TOPIC,
            "ak.wwise.cli.generateSoundbank",
            "ak.wwise.cli.tabDelimitedImport",
            "ak.wwise.cli.convertExternalSource",
            HEAVY_V3_MIGRATION_API,
            "ak.wwise.core.getInfo",
            "ak.wwise.core.executeLuaScript",
        }:
            raise CampaignEvidenceError(
                f"{label} lacks required typed business-plan sections"
            )
    except (
        AudioMediaBusinessPlanError,
        CliBusinessPlanError,
        ImportBusinessPlanError,
        ObjectBusinessPlanError,
        DirectBusinessPlanError,
        SoundBankBusinessPlanError,
        WorkflowBusinessPlanError,
    ) as exc:
        raise CampaignEvidenceError(
            f"{label} typed plan/evidence binding is invalid: {exc}"
        ) from exc


def _validate_integration_workflow_verification(
    sections: WorkflowBusinessPlanSections,
    verification: Any,
    *,
    label: str,
) -> None:
    if not isinstance(verification, Mapping):
        raise CampaignEvidenceError(
            f"{label} integration verification is not an object"
        )
    workflow_id = sections.static_expectation.get("workflow_id")
    if workflow_id in _INTEGRATION_V2_WORKFLOW_IDS:
        _validate_integration_v2_verification(
            verification,
            workflow_id=str(workflow_id),
            version=str(
                sections.live_binding.get("bindings", {}).get("version", "")
            ),
            label=label,
        )
        return
    keys = set(verification)
    weather_keys = {
        "workflow_id",
        "phase",
        "passed",
        "failures",
        "evidence",
    }
    alarm_keys = {
        "phase",
        "passed",
        "failures",
        "before",
        "after",
        "changed_fields",
    }
    harbor_keys = {
        "phase",
        "passed",
        "failures",
        "before",
        "after",
        "evidence",
    }
    expected_keys = {
        "interactive_weather_build": weather_keys,
        "alarm_diagnose_and_repair": alarm_keys,
        "harbor_soundbank_release": harbor_keys,
    }.get(workflow_id)
    if expected_keys is None or keys != expected_keys:
        raise CampaignEvidenceError(
            f"{label} integration verification schema is not closed for "
            f"{workflow_id}"
        )
    phase = verification.get("phase")
    failures = verification.get("failures")
    if (
        not isinstance(phase, str)
        or not phase
        or verification.get("passed") is not True
        or not isinstance(failures, (list, tuple))
        or failures
    ):
        raise CampaignEvidenceError(
            f"{label} integration verification did not pass cleanly"
        )
    if workflow_id == "interactive_weather_build":
        if (
            verification.get("workflow_id") != workflow_id
            or phase
            not in {
                "turn_01_preview_only",
                "turn_02",
                "turn_03",
                "turn_04",
                "workflow_complete",
            }
            or not isinstance(verification.get("evidence"), Mapping)
            or not verification["evidence"]
        ):
            raise CampaignEvidenceError(
                f"{label} weather verification identity, phase, or evidence is invalid"
            )
        return
    before = verification.get("before")
    after = verification.get("after")
    if workflow_id == "alarm_diagnose_and_repair":
        changed = verification.get("changed_fields")
        if not isinstance(changed, (list, tuple)):
            raise CampaignEvidenceError(
                f"{label} Alarm changed-field evidence is invalid"
            )
        if phase in {"diagnosis_read_only", "preview_no_change"}:
            if changed:
                raise CampaignEvidenceError(
                    f"{label} Alarm read-only/preview phase changed state"
                )
        elif phase == "after_repair":
            if list(changed) != ["sound.details.output_bus_id"]:
                raise CampaignEvidenceError(
                    f"{label} Alarm repair delta is not OutputBus-only"
                )
        else:
            raise CampaignEvidenceError(
                f"{label} Alarm verification phase is unreviewed"
            )
    elif phase not in {"tx01.verify", "final"}:
        raise CampaignEvidenceError(
            f"{label} Harbor verification phase or evidence is invalid"
        )
    if (
        not isinstance(before, Mapping)
        or not before
        or not isinstance(after, Mapping)
        or not after
    ):
        raise CampaignEvidenceError(
            f"{label} integration before/after snapshots are unavailable"
        )
    if workflow_id == "alarm_diagnose_and_repair":
        if phase in {"diagnosis_read_only", "preview_no_change"}:
            if before != after:
                raise CampaignEvidenceError(
                    f"{label} Alarm read-only/preview phase changed state"
                )
        elif before == after:
                raise CampaignEvidenceError(
                    f"{label} Alarm repair delta is not OutputBus-only"
                )
        return
    if (
        not isinstance(verification.get("evidence"), Mapping)
        or not verification["evidence"]
        or before == after
    ):
        raise CampaignEvidenceError(
            f"{label} Harbor verification phase or evidence is invalid"
        )


_INTEGRATION_V2_PHASE_ASSERTIONS = {
    "rifle_safe_reimport": {
        "preview_no_change": ("preview_unchanged",),
        "after_import": INTEGRATION_V2_ASSERTION_IDS["rifle_safe_reimport"],
    },
    "footsteps_snow_assignment_maintenance": {
        "preview_one_no_change": ("preview_unchanged",),
        "after_snow_before_mud_removal": (
            "snow_hierarchy_created_once",
            "snow_media_hashes_match_inputs",
            "snow_assignment_present",
            "mud_objects_and_value_preserved",
            "metal_wood_assignments_unchanged",
            "footstep_event_chain_unchanged",
            "existing_footstep_content_unchanged",
            "footsteps_bus_unchanged",
            "source_project_unchanged",
        ),
        "after_mud_assignment_removal": INTEGRATION_V2_ASSERTION_IDS[
            "footsteps_snow_assignment_maintenance"
        ],
    },
    "weapons_query_guided_batch_cleanup": {
        "turn_1_no_change": (
            "snapshot_unchanged",
            "audit_query_valid",
        ),
        "turn_2_no_change": (
            "snapshot_unchanged",
            "audit_query_valid",
            "selected_ids_revalidated",
        ),
        "after_batch": INTEGRATION_V2_ASSERTION_IDS[
            "weapons_query_guided_batch_cleanup"
        ],
    },
}
_INTEGRATION_V2_NO_CHANGE_PHASES = frozenset(
    {
        "preview_no_change",
        "preview_one_no_change",
        "turn_1_no_change",
        "turn_2_no_change",
    }
)
_INTEGRATION_V2_FINAL_PHASES = {
    "rifle_safe_reimport": "after_import",
    "footsteps_snow_assignment_maintenance": "after_mud_assignment_removal",
    "weapons_query_guided_batch_cleanup": "after_batch",
}


def _validate_integration_v2_verification(
    value: Any,
    *,
    workflow_id: str,
    version: str,
    label: str,
) -> None:
    """Validate the exact JSON projection emitted by V2 runtime as_dict()."""

    verification = _closed_oracle_mapping(
        value,
        {"phase", "passed", "failures", "assertions", "before", "after"},
        label=label,
    )
    phase = verification.get("phase")
    expected_by_phase = _INTEGRATION_V2_PHASE_ASSERTIONS.get(workflow_id)
    expected_assertions = (
        expected_by_phase.get(phase)
        if isinstance(expected_by_phase, Mapping) and isinstance(phase, str)
        else None
    )
    assertions = verification.get("assertions")
    if (
        version not in {"2022.1", "2025.1"}
        or expected_assertions is None
        or verification.get("passed") is not True
        or verification.get("failures") != []
        or not isinstance(assertions, Mapping)
        or set(assertions) != set(expected_assertions)
        or any(value is not True for value in assertions.values())
    ):
        raise CampaignEvidenceError(
            f"{label} integration v2 verification is not an exact failure-free runtime result"
        )
    before = _validate_integration_v2_snapshot(
        verification.get("before"),
        workflow_id=workflow_id,
        version=version,
        label=f"{label}.before",
    )
    after = _validate_integration_v2_snapshot(
        verification.get("after"),
        workflow_id=workflow_id,
        version=version,
        label=f"{label}.after",
    )
    if before["source_project"] != after["source_project"]:
        raise CampaignEvidenceError(
            f"{label} integration v2 source-project proof changed"
        )
    if phase in _INTEGRATION_V2_NO_CHANGE_PHASES:
        if before != after:
            raise CampaignEvidenceError(
                f"{label} integration v2 no-change phase contains a delta"
            )
    elif phase == _INTEGRATION_V2_FINAL_PHASES[workflow_id] and before == after:
        raise CampaignEvidenceError(
            f"{label} integration v2 final phase contains no business delta"
        )


def _validate_integration_v2_snapshot(
    value: Any,
    *,
    workflow_id: str,
    version: str,
    label: str,
) -> Mapping[str, Any]:
    keys_by_workflow = {
        "rifle_safe_reimport": {
            "workflow_id",
            "version",
            "objects",
            "absent_roles",
            "media",
            "container_children",
            "input_files",
            "source_project",
            "digest",
        },
        "footsteps_snow_assignment_maintenance": {
            "workflow_id",
            "version",
            "objects",
            "absent_roles",
            "media",
            "children",
            "assignments",
            "input_files",
            "source_project",
            "digest",
        },
        "weapons_query_guided_batch_cleanup": {
            "workflow_id",
            "version",
            "objects",
            "media",
            "source_project",
            "digest",
        },
    }
    snapshot = _closed_oracle_mapping(
        value,
        keys_by_workflow[workflow_id],
        label=label,
    )
    if (
        snapshot.get("workflow_id") != workflow_id
        or snapshot.get("version") != version
        or not _sha256_text_value(snapshot.get("digest"))
        or _canonical_sha256(
            {key: nested for key, nested in snapshot.items() if key != "digest"}
        )
        != snapshot.get("digest")
    ):
        raise CampaignEvidenceError(
            f"{label} integration v2 snapshot identity or digest is invalid"
        )
    objects = snapshot.get("objects")
    media = snapshot.get("media")
    if (
        not isinstance(objects, list)
        or not objects
        or not isinstance(media, list)
        or not media
    ):
        raise CampaignEvidenceError(
            f"{label} integration v2 object/media evidence is unavailable"
        )
    object_roles: list[str] = []
    for index, raw in enumerate(objects):
        row = _closed_oracle_mapping(
            raw,
            {"role", "id", "name", "type", "path", "state"},
            label=f"{label}.objects[{index}]",
        )
        name = row.get("name")
        object_type = row.get("type")
        path = row.get("path")
        if (
            not _nonempty_text(row.get("role"))
            or _OBJECT_ANSWER_GUID_RE.fullmatch(str(row.get("id", ""))) is None
            or not _integration_v2_object_name_is_valid(
                name,
                object_type=object_type,
                path=path,
            )
            or not _nonempty_text(object_type)
            or not isinstance(path, str)
            or not path.startswith("\\")
            or not isinstance(row.get("state"), Mapping)
        ):
            raise CampaignEvidenceError(
                f"{label} integration v2 object row is invalid"
            )
        object_roles.append(str(row["role"]))
    if len(object_roles) != len(set(object_roles)):
        raise CampaignEvidenceError(
            f"{label} integration v2 object roles are duplicated"
        )
    media_roles: list[str] = []
    for index, raw in enumerate(media):
        row = _closed_oracle_mapping(
            raw,
            {
                "role",
                "sound_id",
                "active_source_id",
                "source_parent_id",
                "language",
                "original",
            },
            label=f"{label}.media[{index}]",
        )
        if (
            not _nonempty_text(row.get("role"))
            or any(
                _OBJECT_ANSWER_GUID_RE.fullmatch(str(row.get(key, ""))) is None
                for key in ("sound_id", "active_source_id", "source_parent_id")
            )
            or not _nonempty_text(row.get("language"))
        ):
            raise CampaignEvidenceError(
                f"{label} integration v2 media row is invalid"
            )
        _validate_integration_v2_file_proof(
            row.get("original"),
            label=f"{label}.media[{index}].original",
            allow_null_relative=False,
        )
        media_roles.append(str(row["role"]))
    if len(media_roles) != len(set(media_roles)) or not set(media_roles) <= set(
        object_roles
    ):
        raise CampaignEvidenceError(
            f"{label} integration v2 media roles are duplicated or unbound"
        )
    source = _closed_oracle_mapping(
        snapshot.get("source_project"),
        {"project_sha256", "tree_sha256", "project_mtime_ns"},
        label=f"{label}.source_project",
    )
    if (
        not _sha256_text_value(source.get("project_sha256"))
        or not _sha256_text_value(source.get("tree_sha256"))
        or not _plain_int(source.get("project_mtime_ns"), minimum=1)
    ):
        raise CampaignEvidenceError(
            f"{label} integration v2 source-project proof is invalid"
        )
    if "absent_roles" in snapshot:
        absent = snapshot.get("absent_roles")
        if (
            not isinstance(absent, list)
            or any(not _nonempty_text(role) for role in absent)
            or len(absent) != len(set(absent))
            or set(absent) & set(object_roles)
        ):
            raise CampaignEvidenceError(
                f"{label} integration v2 absent-role evidence is invalid"
            )
    input_files = snapshot.get("input_files")
    if input_files is not None:
        if not isinstance(input_files, list) or not input_files:
            raise CampaignEvidenceError(
                f"{label} integration v2 input-file evidence is unavailable"
            )
        input_keys: list[str] = []
        for index, raw in enumerate(input_files):
            row = _closed_oracle_mapping(
                raw,
                {"key", "path", "relative_path", "size", "sha256"},
                label=f"{label}.input_files[{index}]",
            )
            if not _nonempty_text(row.get("key")):
                raise CampaignEvidenceError(
                    f"{label} integration v2 input key is invalid"
                )
            _validate_integration_v2_file_proof(
                {key: row[key] for key in ("path", "relative_path", "size", "sha256")},
                label=f"{label}.input_files[{index}]",
                allow_null_relative=False,
            )
            input_keys.append(str(row["key"]))
        if len(input_keys) != len(set(input_keys)):
            raise CampaignEvidenceError(
                f"{label} integration v2 input keys are duplicated"
            )
    _validate_integration_v2_relationship_rows(
        snapshot,
        workflow_id=workflow_id,
        label=label,
    )
    return snapshot


def _integration_v2_object_name_is_valid(
    value: Any,
    *,
    object_type: Any,
    path: Any,
) -> bool:
    """Accept only Wwise's exact nameless Action display-path representation."""

    if _nonempty_text(value):
        return True
    if value != "" or object_type != "Action" or not isinstance(path, str):
        return False
    display_segment = path.rsplit("\\", 1)[-1]
    return (
        len(display_segment) > 2
        and display_segment.startswith("[")
        and display_segment.endswith("]")
    )


def _validate_integration_v2_file_proof(
    value: Any,
    *,
    label: str,
    allow_null_relative: bool,
) -> None:
    proof = _closed_oracle_mapping(
        value,
        {"path", "relative_path", "size", "sha256"},
        label=label,
    )
    relative = proof.get("relative_path")
    absolute = proof.get("path")
    _validated_archive_absolute_path(absolute, label=f"{label}.path")
    relative_identity = None
    if relative is not None:
        try:
            relative_identity = parse_archive_relative_path(relative)
        except ArchiveRelativePathError as exc:
            raise CampaignEvidenceError(
                f"{label} relative path is invalid"
            ) from exc
    if (
        not _plain_int(proof.get("size"), minimum=1)
        or not _sha256_text_value(proof.get("sha256"))
        or (
            relative is None
            if not allow_null_relative
            else relative is not None and not _nonempty_text(relative)
        )
        or (relative is not None and not _nonempty_text(relative))
        or (
            relative_identity is not None
            and (
                relative_identity.source_flavor != "posix"
                or relative_identity.canonical != relative
                or not archive_absolute_has_relative_suffix(
                    absolute,
                    relative_identity.canonical,
                )
            )
        )
    ):
        raise CampaignEvidenceError(f"{label} file proof is invalid")


def _validate_integration_v2_relationship_rows(
    snapshot: Mapping[str, Any],
    *,
    workflow_id: str,
    label: str,
) -> None:
    specs: tuple[tuple[str, set[str]], ...]
    if workflow_id == "rifle_safe_reimport":
        specs = (
            (
                "container_children",
                {"id", "name", "path", "type", "parent_id"},
            ),
        )
    elif workflow_id == "footsteps_snow_assignment_maintenance":
        specs = (
            (
                "children",
                {"owner_role", "id", "name", "path", "type", "parent_id"},
            ),
            ("assignments", {"child", "stateOrSwitch"}),
        )
    else:
        specs = ()
    for field, keys in specs:
        rows = snapshot.get(field)
        if not isinstance(rows, list):
            raise CampaignEvidenceError(
                f"{label}.{field} relationship evidence is invalid"
            )
        for index, raw in enumerate(rows):
            row = _closed_oracle_mapping(
                raw,
                keys,
                label=f"{label}.{field}[{index}]",
            )
            guid_fields = (
                ("child", "stateOrSwitch")
                if field == "assignments"
                else ("id", "parent_id")
            )
            if any(
                _OBJECT_ANSWER_GUID_RE.fullmatch(str(row.get(key, ""))) is None
                for key in guid_fields
            ):
                raise CampaignEvidenceError(
                    f"{label}.{field} relationship identity is invalid"
                )
            if field != "assignments" and (
                not isinstance(row.get("path"), str)
                or not str(row["path"]).startswith("\\")
                or not _integration_v2_object_name_is_valid(
                    row.get("name"),
                    object_type=row.get("type"),
                    path=row.get("path"),
                )
                or not _nonempty_text(row.get("type"))
                or ("owner_role" in row and not _nonempty_text(row.get("owner_role")))
            ):
                raise CampaignEvidenceError(
                    f"{label}.{field} relationship row is invalid"
                )


def _validate_integration_v2_cleanup(
    value: Any,
    *,
    workflow_id: str,
) -> None:
    keys = {
        "passed",
        "already_clean",
        "sandbox_untouched",
        "source_untouched",
        "failures",
    }
    if workflow_id != "weapons_query_guided_batch_cleanup":
        keys.add("removed_input_root")
    cleanup = _closed_oracle_mapping(
        value,
        keys,
        label=f"{workflow_id} runtime cleanup",
    )
    if (
        cleanup.get("passed") is not True
        or cleanup.get("already_clean") is not False
        or cleanup.get("sandbox_untouched") is not True
        or cleanup.get("source_untouched") is not True
        or cleanup.get("failures") != []
        or (
            "removed_input_root" in cleanup
            and (
                not isinstance(cleanup.get("removed_input_root"), str)
            )
        )
    ):
        raise CampaignEvidenceError(
            f"{workflow_id} runtime cleanup proof is not an exact clean pass"
        )
    if "removed_input_root" in cleanup:
        _validated_archive_absolute_path(
            cleanup["removed_input_root"],
            label=f"{workflow_id} runtime cleanup removed_input_root",
        )


def _heavy_v3_broker_refusal_error_code(
    task_root: Path,
    *,
    step_name: str,
) -> str:
    """Extract one already protocol-replayed structured refusal from the broker."""

    task_result = load_strict_regular_json(task_root / "task-result.json")
    broker = task_result.get("broker") if isinstance(task_result, Mapping) else None
    records = broker.get("records") if isinstance(broker, Mapping) else None
    matches = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("step_name") == step_name
    ] if isinstance(records, list) else []
    if len(matches) != 1:
        raise CampaignEvidenceError(
            f"heavy broker lacks one exact refusal record for {step_name}"
        )
    record = matches[0]
    payload = record.get("payload")
    if (
        record.get("authenticated") is not True
        or record.get("accepted") is not True
        or record.get("succeeded") is not True
        or record.get("runner_exit_code") != 2
        or not isinstance(payload, Mapping)
        or payload.get("contract") != "waapi-skill.gateway-result/v1"
        or payload.get("ok") is not False
        or payload.get("command") != "preview"
        or not isinstance(payload.get("error_code"), str)
        or not payload["error_code"]
    ):
        raise CampaignEvidenceError(
            f"heavy broker refusal record is invalid for {step_name}"
        )
    return str(payload["error_code"])


def _closed_oracle_mapping(
    value: Any,
    keys: set[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CampaignEvidenceError(f"{label} schema is not closed")
    return value


def _require_passing_oracle(value: Mapping[str, Any], *, label: str) -> None:
    if value.get("passed") is not True or value.get("failures") != []:
        raise CampaignEvidenceError(f"{label} is not an explicit failure-free pass")


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _optional_text(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _plain_int(value: Any, *, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _sha256_text_value(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _json_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, (str, bool))
        or (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    )


def _json_archive_value(value: Any) -> bool:
    if _json_scalar(value):
        return True
    if isinstance(value, list):
        return all(_json_archive_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _json_archive_value(item)
            for key, item in value.items()
        )
    return False


def _heavy_v3_final_response_sha256(task_root: Path) -> str:
    value = _heavy_v3_final_response(task_root)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _heavy_v3_final_response(task_root: Path) -> str:
    turns_root = task_root / "turns"
    names = sorted(_strict_real_subdirectory_names(turns_root))
    if not names:
        raise CampaignEvidenceError("heavy task has no final turn response")
    value = _load_strict_regular_text(turns_root / names[-1] / "final.txt")
    if not value.endswith("\n") or not value[:-1]:
        raise CampaignEvidenceError("heavy final response archive is malformed")
    return value[:-1]


def _heavy_v3_protocol_operation_request(
    evidence: HeavyV3PromptEvidence,
) -> Mapping[str, Any]:
    version = evidence.provenance.payload.get("version")
    if not isinstance(version, str):
        version = next(
            (
                str(argument.expected["version"])
                for step in evidence.provenance.protocol.steps
                for argument in step.arguments
                if isinstance(argument, InlineTypedOperationArgument)
                and isinstance(argument.expected.get("version"), str)
            ),
            None,
        )
    if version is None:
        version = next(
            (
                argument.contract.version
                for step in evidence.provenance.protocol.steps
                for argument in step.arguments
                if isinstance(argument, TypedRequestFactsArgument)
            ),
            None,
        )
    if not isinstance(version, str):
        raise CampaignEvidenceError("heavy typed protocol lacks one exact version")
    try:
        values = [
            request
            for _pointer, request in materialize_typed_transaction_protocol_requests(
                evidence.provenance.protocol,
                version=version,
            )
        ]
    except V3ProtocolError as exc:
        raise CampaignEvidenceError("heavy typed protocol cannot be materialized") from exc
    if len(values) != 1:
        raise CampaignEvidenceError(
            "heavy protocol does not contain one exact operation request"
        )
    return values[0]


def _validate_heavy_v3_completed_transaction_protocol(
    evidence: HeavyV3PromptEvidence,
    *,
    expected_operation_request: Mapping[str, Any],
) -> None:
    """Require the closed preview/confirm/execute/verify transaction topology."""

    protocol = evidence.provenance.protocol
    steps = protocol.steps
    operation = expected_operation_request.get("operation")
    preview_transaction_id = ResponseBinding(
        "tx01.preview",
        "/transaction_id",
    )
    shown_transaction_id = ResponseBinding(
        "tx01.transaction-show",
        "/transaction_id",
    )
    confirmation_token = ResponseBinding(
        "tx01.transaction-show",
        "/confirmation/token",
    )
    confirmed_transaction_id = ResponseBinding(
        "tx01.confirm",
        "/transaction_id",
    )
    executed_transaction_id = ResponseBinding(
        "tx01.execute",
        "/transaction_id",
    )
    preview_index = next(
        (index for index, step in enumerate(steps) if step.name == "tx01.preview"),
        None,
    )
    if preview_index is None:
        raise CampaignEvidenceError(
            "heavy audio transaction lacks exact preview/confirm/execute/verify binding"
        )
    tail = steps[preview_index:]
    try:
        materialized = _heavy_v3_protocol_operation_request(evidence)
    except CampaignEvidenceError:
        raise
    if (
        not _nonempty_text(operation)
        or materialized != expected_operation_request
        or protocol.turn_prefix_counts != (preview_index + 1, len(steps))
        or tuple(step.name for step in tail)
        != (
            "tx01.preview",
            "tx01.transaction-show",
            "tx01.confirm",
            "tx01.execute",
            "tx01.verify",
        )
        or tail[0].subcommand not in {
            "typed-call",
            "typed-operation",
            "preview-from-draft",
        }
        or tuple(step.subcommand for step in tail[1:])
        != ("transaction-show", "confirm", "execute", "verify")
        or tail[1].arguments != (preview_transaction_id, "--summary-only")
        or tail[2].arguments
        != (
            shown_transaction_id,
            "--confirmation-token",
            confirmation_token,
        )
        or tail[3].arguments != (confirmed_transaction_id,)
        or tail[4].arguments != (executed_transaction_id,)
        or any(
            step.allowed_exit_codes != ((0, 2) if index == 3 else (0,))
            for index, step in enumerate(tail)
        )
        or any(step.gateway_global_arguments for step in steps)
        or any(step.expected_error_code for step in steps)
        or any(step.expected_result_command for step in steps)
        or any(step.terminal_execute for step in steps)
    ):
        raise CampaignEvidenceError(
            "heavy audio transaction lacks exact preview/confirm/execute/verify binding"
        )


def _heavy_v3_broker_step_payload_sha256(
    task_root: Path,
    *,
    step_name: str,
) -> str:
    return _canonical_sha256(
        _heavy_v3_broker_step_payload(task_root, step_name=step_name)
    )


def _heavy_v3_broker_step_payload(
    task_root: Path,
    *,
    step_name: str,
) -> Mapping[str, Any]:
    task_result = load_strict_regular_json(task_root / "task-result.json")
    broker = task_result.get("broker") if isinstance(task_result, Mapping) else None
    records = broker.get("records") if isinstance(broker, Mapping) else None
    matches = [
        record.get("payload")
        for record in records
        if isinstance(record, Mapping) and record.get("step_name") == step_name
    ] if isinstance(records, list) else []
    if len(matches) != 1 or not isinstance(matches[0], Mapping):
        raise CampaignEvidenceError(
            f"heavy broker lacks one exact payload for {step_name}"
        )
    return matches[0]


def _heavy_v3_protocol_call_request(
    evidence: HeavyV3PromptEvidence,
    *,
    api: str,
) -> Mapping[str, Any]:
    payload = evidence.provenance.payload
    version = payload.get("version") if isinstance(payload, Mapping) else None
    if not isinstance(version, str):
        raise CampaignEvidenceError("heavy typed protocol version is unavailable")
    try:
        requests = materialize_typed_transaction_protocol_requests(
            evidence.provenance.protocol,
            version=version,
        )
    except V3ProtocolError as exc:
        raise CampaignEvidenceError(
            f"heavy protocol cannot materialize the typed request for {api}"
        ) from exc
    values: list[dict[str, Any]] = []
    for _pointer, request in requests:
        arguments = request.get("arguments")
        if (
            request.get("operation") != "waapi.call"
            or not isinstance(arguments, Mapping)
            or arguments.get("api") != api
            or not isinstance(arguments.get("args"), Mapping)
            or not isinstance(arguments.get("options"), Mapping)
        ):
            continue
        values.append(
            {
                "args": arguments["args"],
                "options": arguments["options"],
                "post_filter": None,
            }
        )
    check_steps = tuple(
        step
        for step in evidence.provenance.protocol.steps
        if step.subcommand == "draft-check"
        and len(step.arguments) == 9
        and step.arguments[5] == "--post-filter-value"
        and step.arguments[7] == "--post-filter-limit"
    )
    if len(values) == 1 and len(check_steps) == 1:
        check = check_steps[0]
        values[0]["post_filter"] = {
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": check.arguments[6],
            "limit": int(check.arguments[8]),
        }
    if len(values) != 1:
        raise CampaignEvidenceError(
            f"heavy protocol does not contain one exact call request for {api}"
        )
    return values[0]


def _heavy_v3_audio_byte_change_paths(fixture: Any) -> tuple[str, ...]:
    """Derive the byte-change subset from the reviewed scenario, not child evidence."""

    asset_spec = fixture.get("asset_spec") if isinstance(fixture, Mapping) else None
    delta_plan = asset_spec.get("delta_plan", []) if isinstance(asset_spec, Mapping) else []
    if not isinstance(delta_plan, list):
        raise CampaignEvidenceError("audio conversion delta plan is malformed")
    paths: list[str] = []
    for item in delta_plan:
        if not isinstance(item, Mapping):
            raise CampaignEvidenceError("audio conversion delta row is malformed")
        kind = item.get("kind")
        path = item.get("path")
        if kind in {"replace_source_bytes", "replace_effective_settings"}:
            if not _nonempty_text(path):
                raise CampaignEvidenceError("audio conversion replacement path is invalid")
            paths.append(str(path))
    if len(paths) != len(set(paths)):
        raise CampaignEvidenceError("audio conversion replacement paths are duplicated")
    return tuple(sorted(paths))


def _validate_heavy_v3_object_oracle(
    value: Any,
    *,
    api: str,
    scenario_id: str,
    primary_count: int,
    expected_final_response_sha256: str,
    final_response: str,
    gateway_payload: Mapping[str, Any] | None,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"phase", "passed", "failures", "evidence"},
        label=label,
    )
    _require_passing_oracle(row, label=label)
    evidence = row.get("evidence")
    if primary_count == 0 and api in {
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }:
        if row.get("phase") != "policy_read_only":
            raise CampaignEvidenceError(
                f"{label} object read-only phase is invalid"
            )
        proof = _closed_oracle_mapping(
            evidence,
            {"before", "after"},
            label=f"{label} read-only evidence",
        )
        _validate_object_snapshot(proof.get("before"), label=f"{label} before")
        _validate_object_snapshot(proof.get("after"), label=f"{label} after")
        if proof.get("before") != proof.get("after"):
            raise CampaignEvidenceError(
                f"{label} read-only object snapshot changed"
            )
        return
    if api == "ak.wwise.core.object.get":
        if row.get("phase") != "query":
            raise CampaignEvidenceError(f"{label} object.get phase is invalid")
        proof = _closed_oracle_mapping(
            evidence,
            {
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
            },
            label=f"{label} evidence",
        )
        _validate_object_snapshot(proof.get("before"), label=f"{label} before")
        _validate_object_snapshot(proof.get("after"), label=f"{label} after")
        observed = proof.get("observed_keys")
        expected = proof.get("expected_payload_keys")
        required = proof.get("required_keys")
        excluded = proof.get("excluded_keys")
        primary_policy = proof.get("primary_row_policy")
        raw_row_count = proof.get("raw_row_count")
        query_bound = proof.get("query_bound")
        bound_reached = proof.get("bound_reached")
        if (
            not isinstance(observed, list)
            or not isinstance(expected, list)
            or not isinstance(required, list)
            or not isinstance(excluded, list)
            or not expected
            or any(
                not _nonempty_text(item)
                for item in (*observed, *expected, *required, *excluded)
            )
            or len(expected) != len(set(expected))
            or len(required) != len(set(required))
            or len(excluded) != len(set(excluded))
            or primary_policy
            not in {
                "unique_identity_rows",
                "ancestor_identity_rows",
                "parent_projection_per_source_row",
            }
            or type(raw_row_count) is not int
            or raw_row_count < 0
            or not isinstance(query_bound, Mapping)
            or set(query_bound) != {"mode", "value"}
            or query_bound.get("mode") != "take"
            or type(query_bound.get("value")) is not int
            or bound_reached is not (raw_row_count == query_bound.get("value"))
            or not set(required).issubset(set(expected))
            or set(required) & set(excluded)
            or proof.get("before") != proof.get("after")
            or proof.get("final_response_sha256")
            != expected_final_response_sha256
        ):
            raise CampaignEvidenceError(f"{label} object.get identities are invalid")
        if primary_policy == "unique_identity_rows":
            if (
                len(observed) != len(expected)
                or len(observed) != len(set(observed))
                or set(observed) != set(expected)
            ):
                raise CampaignEvidenceError(
                    f"{label} object.get unique primary identities are invalid"
                )
        elif primary_policy == "ancestor_identity_rows":
            if (
                len(observed) != len(expected)
                or len(observed) != len(set(observed))
                or set(observed) != set(expected)
                or raw_row_count != len(expected)
                or bound_reached is not False
            ):
                raise CampaignEvidenceError(
                    f"{label} object.get ordered ancestor identities are invalid"
                )
        elif (
            set(observed) != set(expected)
            or len(observed) == len(set(observed))
            or len(observed) != query_bound.get("value")
            or raw_row_count != query_bound.get("value")
            or bound_reached is not True
        ):
            raise CampaignEvidenceError(
                f"{label} object.get parent-projection identities are invalid"
            )
        if gateway_payload is None:
            raise CampaignEvidenceError(f"{label} object.get broker payload is missing")
        _validate_object_query_gateway_payload(
            proof,
            gateway_payload=gateway_payload,
            label=label,
        )
        derived_policy = proof.get("derived_row_policy")
        derived_rows = proof.get("derived_rows")
        if derived_policy not in {"none", "active_audio_sources_for_sound_rows"} or not isinstance(
            derived_rows, list
        ):
            raise CampaignEvidenceError(f"{label} object.get derived policy is invalid")
        if derived_policy == "none" and derived_rows:
            raise CampaignEvidenceError(f"{label} object.get has unapproved derived rows")
        source_ids: list[str] = []
        source_parents: list[str] = []
        for item in derived_rows:
            source = _closed_oracle_mapping(
                item,
                {
                    "sound_key",
                    "sound_id",
                    "id",
                    "name",
                    "type",
                    "path",
                    "parent_id",
                    "language",
                },
                label=f"{label} activeSource row",
            )
            if (
                derived_policy != "active_audio_sources_for_sound_rows"
                or any(
                    not _nonempty_text(source.get(field))
                    for field in (
                        "sound_key",
                        "sound_id",
                        "id",
                        "name",
                        "path",
                        "parent_id",
                        "language",
                    )
                )
                or source.get("type") != "AudioFileSource"
                or source.get("sound_id") != source.get("parent_id")
                or not str(source.get("path")).endswith(
                    f"\\{source.get('name')}"
                )
            ):
                raise CampaignEvidenceError(f"{label} activeSource row is malformed")
            source_ids.append(str(source["id"]))
            source_parents.append(str(source["parent_id"]))
        if len(source_ids) != len(set(source_ids)) or len(source_parents) != len(
            set(source_parents)
        ):
            raise CampaignEvidenceError(f"{label} activeSource rows are duplicated")
        if raw_row_count != len(observed) + len(derived_rows):
            raise CampaignEvidenceError(
                f"{label} object.get raw count differs from primary/derived rows"
            )
        required_tokens = proof.get("required_identity_tokens")
        excluded_tokens = proof.get("excluded_identity_tokens")
        if (
            not isinstance(required_tokens, list)
            or not isinstance(excluded_tokens, list)
            or [item.get("key") for item in required_tokens if isinstance(item, Mapping)]
            != required
            or [item.get("key") for item in excluded_tokens if isinstance(item, Mapping)]
            != excluded
        ):
            raise CampaignEvidenceError(f"{label} object.get final token proof is invalid")
        answer_policy = proof.get("final_answer_policy")
        if answer_policy in {
            "name_and_id",
            "deduplicated_parent_summary",
            "ordered_ancestor_summary",
        }:
            if proof.get("paired_rows") != []:
                raise CampaignEvidenceError(f"{label} name/GUID answer has paired evidence")
            for item in required_tokens:
                token = _closed_oracle_mapping(
                    item,
                    {"key", "name", "id", "name_present", "id_present"},
                    label=f"{label} required identity token",
                )
                if (
                    not _nonempty_text(token.get("key"))
                    or not _nonempty_text(token.get("name"))
                    or not _nonempty_text(token.get("id"))
                    or token.get("name_present")
                    is not (str(token.get("name")).casefold() in final_response.casefold())
                    or token.get("id_present")
                    is not (str(token.get("id")).casefold() in final_response.casefold())
                    or token.get("name_present") is not True
                    or token.get("id_present") is not True
                ):
                    raise CampaignEvidenceError(f"{label} required identity token is invalid")
            for item in excluded_tokens:
                token = _closed_oracle_mapping(
                    item,
                    {"key", "id", "id_present"},
                    label=f"{label} excluded identity token",
                )
                if (
                    not _nonempty_text(token.get("key"))
                    or not _nonempty_text(token.get("id"))
                    or token.get("id_present")
                    is not (str(token.get("id")).casefold() in final_response.casefold())
                    or token.get("id_present") is not False
                ):
                    raise CampaignEvidenceError(f"{label} excluded identity token is invalid")
            if answer_policy == "name_and_id":
                if (
                    proof.get("deduplicated_parent_rows") != []
                    or proof.get("coverage_summary") is not None
                    or proof.get("observed_answer_order") != []
                ):
                    raise CampaignEvidenceError(
                        f"{label} name/GUID answer has parent-summary evidence"
                    )
            elif answer_policy == "deduplicated_parent_summary":
                if primary_policy != "parent_projection_per_source_row":
                    raise CampaignEvidenceError(
                        f"{label} parent summary lacks duplicate primary policy"
                    )
                _validate_archived_deduplicated_parent_answer(
                    proof,
                    final_response=final_response,
                    label=label,
                )
            else:
                if primary_policy != "ancestor_identity_rows":
                    raise CampaignEvidenceError(
                        f"{label} ancestor summary lacks ancestor primary policy"
                    )
                _validate_archived_ordered_ancestor_answer(
                    proof,
                    final_response=final_response,
                    label=label,
                )
        elif answer_policy == "paired_path_rows":
            if (
                proof.get("deduplicated_parent_rows") != []
                or proof.get("coverage_summary") is not None
            ):
                raise CampaignEvidenceError(
                    f"{label} paired answer has parent-summary evidence"
                )
            _validate_archived_paired_path_answer(
                proof,
                final_response=final_response,
                label=label,
            )
        else:
            raise CampaignEvidenceError(f"{label} object.get answer policy is invalid")
        return
    if row.get("phase") != "after":
        raise CampaignEvidenceError(f"{label} object mutation phase is invalid")
    mutation_evidence_keys = {
        "before",
        "after",
        "resolved",
        "expected_resolved_keys",
        "removed_keys",
        "removed_readback",
        "protected_keys",
        "protected_before",
        "protected_after",
    }
    if isinstance(evidence, Mapping) and "protected_comparisons" in evidence:
        mutation_evidence_keys.add("protected_comparisons")
    proof = _closed_oracle_mapping(
        evidence,
        mutation_evidence_keys,
        label=f"{label} evidence",
    )
    _validate_object_snapshot(proof.get("before"), label=f"{label} before")
    _validate_object_snapshot(proof.get("after"), label=f"{label} after")
    resolved = proof.get("resolved")
    expected_keys = proof.get("expected_resolved_keys")
    removed_keys = proof.get("removed_keys")
    removed_readback = proof.get("removed_readback")
    protected_keys = proof.get("protected_keys")
    protected_before = proof.get("protected_before")
    protected_after = proof.get("protected_after")
    if (
        not isinstance(resolved, Mapping)
        or not resolved
        or not isinstance(expected_keys, list)
        or not expected_keys
        or set(resolved) != set(expected_keys)
        or len(expected_keys) != len(set(expected_keys))
        or not isinstance(removed_keys, list)
        or len(removed_keys) != len(set(removed_keys))
        or not isinstance(removed_readback, Mapping)
        or set(removed_readback) != set(removed_keys)
        or any(value != [] for value in removed_readback.values())
        or not isinstance(protected_keys, list)
        or len(protected_keys) != len(set(protected_keys))
        or not isinstance(protected_before, Mapping)
        or not isinstance(protected_after, Mapping)
        or set(protected_before) != set(protected_keys)
        or set(protected_after) != set(protected_keys)
        or proof.get("before") == proof.get("after")
    ):
        raise CampaignEvidenceError(f"{label} object mutation business delta is invalid")
    comparisons = proof.get("protected_comparisons")
    if comparisons is None:
        if protected_before != protected_after:
            raise CampaignEvidenceError(
                f"{label} legacy protected object snapshot changed"
            )
    else:
        _validate_campaign_object_protected_comparisons(
            protected_before,
            protected_after,
            comparisons,
            scenario_id=scenario_id,
            before_snapshot=proof["before"],
            after_snapshot=proof["after"],
            resolved=resolved,
            label=label,
        )
    for key, item in resolved.items():
        if not _nonempty_text(key):
            raise CampaignEvidenceError(f"{label} resolved object key is invalid")
        materialized = _closed_oracle_mapping(
            item,
            {
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
            },
            label=f"{label} resolved object",
        )
        properties = materialized.get("properties")
        references = materialized.get("references")
        if (
            materialized.get("key") != key
            or any(
                not _nonempty_text(materialized.get(field))
                for field in ("id", "name", "type", "path")
            )
            or not _optional_text(materialized.get("parent_id"))
            or not _optional_text(materialized.get("notes"))
            or not _optional_text(materialized.get("source_language"))
            or materialized.get("is_included") not in {None, True, False}
            or not _plain_int(materialized.get("children_count"))
            or not isinstance(properties, list)
            or not isinstance(references, list)
        ):
            raise CampaignEvidenceError(f"{label} materialized object is malformed")
        for property_row in properties:
            prop = _closed_oracle_mapping(
                property_row,
                {"name", "value"},
                label=f"{label} object property",
            )
            if not _nonempty_text(prop.get("name")) or not _json_scalar(prop.get("value")):
                raise CampaignEvidenceError(f"{label} object property is malformed")
        for reference_row in references:
            reference = _closed_oracle_mapping(
                reference_row,
                {"name", "target_id"},
                label=f"{label} object reference",
            )
            if not _nonempty_text(reference.get("name")) or not _nonempty_text(
                reference.get("target_id")
            ):
                raise CampaignEvidenceError(f"{label} object reference is malformed")
        _validate_campaign_active_source_fields(
            materialized,
            label=f"{label} resolved object",
            require_for_language=False,
        )
    for collection in (protected_before, protected_after):
        for key, item in collection.items():
            _validate_materialized_object(item, expected_key=str(key), label=f"{label} protected object")


def _validate_campaign_object_protected_comparisons(
    protected_before: Mapping[str, Any],
    protected_after: Mapping[str, Any],
    comparisons: Any,
    *,
    scenario_id: str,
    before_snapshot: Mapping[str, Any],
    after_snapshot: Mapping[str, Any],
    resolved: Mapping[str, Any],
    label: str,
) -> None:
    if (
        not isinstance(comparisons, Mapping)
        or set(comparisons) != set(protected_before)
    ):
        raise CampaignEvidenceError(
            f"{label} protected intrinsic comparison keys are invalid"
        )
    before_overrides = _campaign_object_override_output_map(
        before_snapshot,
        required_keys=set(protected_before),
        label=f"{label} before",
    )
    after_overrides = _campaign_object_override_output_map(
        after_snapshot,
        required_keys=set(protected_before),
        label=f"{label} after",
    )
    comparison_keys = {
        "override_output_before",
        "override_output_after",
        "ignored_derived_fields",
        "before_projection",
        "after_projection",
        "passed",
    }
    override_types = {"ActorMixer", "RandomSequenceContainer", "Sound"}
    for key, before in protected_before.items():
        after = protected_after[key]
        comparison = comparisons[key]
        if not isinstance(comparison, Mapping) or set(comparison) != comparison_keys:
            raise CampaignEvidenceError(
                f"{label} protected intrinsic comparison schema is invalid"
            )
        before_override = comparison.get("override_output_before")
        after_override = comparison.get("override_output_after")
        if (
            before_overrides.get(key) != before_override
            or after_overrides.get(key) != after_override
        ):
            raise CampaignEvidenceError(
                f"{label} protected OverrideOutput differs from snapshots"
            )
        override_required = before.get("type") in override_types
        if override_required and (
            type(before_override) is not bool or type(after_override) is not bool
        ):
            raise CampaignEvidenceError(
                f"{label} protected OverrideOutput is not explicit"
            )
        if before_override != after_override:
            raise CampaignEvidenceError(
                f"{label} protected OverrideOutput changed"
            )
        ignored = list(
            _campaign_object_inherited_effective_fields(
                key,
                scenario_id=scenario_id,
                before=before,
                after=after,
                before_snapshot=before_snapshot,
                resolved=resolved,
                before_override=before_override,
                after_override=after_override,
            )
        )
        if comparison.get("ignored_derived_fields") != ignored:
            raise CampaignEvidenceError(
                f"{label} protected ignored fields are not exact inherited values"
            )
        before_projection = _campaign_object_intrinsic_projection(
            before,
            ignored_derived_fields=ignored,
        )
        after_projection = _campaign_object_intrinsic_projection(
            after,
            ignored_derived_fields=ignored,
        )
        if (
            comparison.get("before_projection") != before_projection
            or comparison.get("after_projection") != after_projection
            or comparison.get("passed") is not True
            or before_projection != after_projection
        ):
            raise CampaignEvidenceError(
                f"{label} protected intrinsic projection is invalid"
            )


def _campaign_object_override_output_map(
    snapshot: Mapping[str, Any],
    *,
    required_keys: set[str],
    label: str,
) -> dict[str, bool | None]:
    rows = snapshot.get("override_output_rows")
    if not isinstance(rows, list):
        raise CampaignEvidenceError(f"{label} OverrideOutput rows are missing")
    result: dict[str, bool | None] = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or row[0] in result
            or (row[1] is not None and type(row[1]) is not bool)
        ):
            raise CampaignEvidenceError(f"{label} OverrideOutput row is invalid")
        result[row[0]] = row[1]
    if not required_keys.issubset(result):
        raise CampaignEvidenceError(f"{label} OverrideOutput keys are incomplete")
    return result


def _campaign_object_intrinsic_projection(
    value: Mapping[str, Any],
    *,
    ignored_derived_fields: Sequence[str],
) -> dict[str, Any]:
    result = _heavy_v3_plan_json_value(value)
    if not isinstance(result, dict):
        raise CampaignEvidenceError("protected object projection source is invalid")
    ignored = set(ignored_derived_fields)
    if ignored.intersection({"@Volume", "@Pitch"}):
        properties = result.get("properties")
        if not isinstance(properties, list):
            raise CampaignEvidenceError("protected object properties are invalid")
        result["properties"] = [
            row
            for row in properties
            if isinstance(row, Mapping)
            and f"@{row.get('name')}" not in ignored
        ]
    if "OutputBus" in ignored:
        references = result.get("references")
        if not isinstance(references, list):
            raise CampaignEvidenceError("protected object references are invalid")
        result["references"] = [
            row
            for row in references
            if isinstance(row, Mapping) and row.get("name") != "OutputBus"
        ]
    return result


def _campaign_object_inherited_effective_fields(
    key: str,
    *,
    scenario_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    before_snapshot: Mapping[str, Any],
    resolved: Mapping[str, Any],
    before_override: bool | None,
    after_override: bool | None,
) -> tuple[str, ...]:
    """Recompute the narrow effective-value exception from archived rows.

    The typed object business plan separately proves that these fields have no
    local fixture override.  This campaign layer independently requires the
    protected row to remain under the same reviewed parent and to equal that
    parent's exact before/after values.
    """

    if (
        scenario_id != "OBJ22-F-SET-03"
        or before.get("key") != key
        or after.get("key") != key
    ):
        return ()
    before_objects = before_snapshot.get("objects")
    if not isinstance(before_objects, list):
        raise CampaignEvidenceError("protected before object graph is invalid")
    before_by_key = {
        str(row.get("key")): row
        for row in before_objects
        if isinstance(row, Mapping) and isinstance(row.get("key"), str)
    }
    parent = next(
        (
            row
            for row in resolved.values()
            if isinstance(row, Mapping)
            and row.get("id") == after.get("parent_id")
        ),
        None,
    )
    if parent is None or before.get("parent_id") != parent.get("id"):
        return ()
    before_parent = before_by_key.get(str(parent.get("key")))
    if before_parent is None or before_parent.get("id") != parent.get("id"):
        return ()

    ignored: list[str] = []
    for field in ("@Volume", "@Pitch"):
        before_value = _campaign_object_field(before, field)
        after_value = _campaign_object_field(after, field)
        if (
            before_value is not None
            and after_value is not None
            and before_value == _campaign_object_field(before_parent, field)
            and after_value == _campaign_object_field(parent, field)
        ):
            ignored.append(field)
    before_bus = _campaign_object_field(before, "OutputBus")
    after_bus = _campaign_object_field(after, "OutputBus")
    # The typed plan has already proved that this protected child has no local
    # fixture OutputBus.  Accept either stable explicit boolean representation
    # emitted by Wwise, while independently binding both bus identities to the
    # exact before/after parent rows.
    if (
        type(before_override) is bool
        and after_override == before_override
        and isinstance(before_bus, str)
        and isinstance(after_bus, str)
        and before_bus == _campaign_object_field(before_parent, "OutputBus")
        and after_bus == _campaign_object_field(parent, "OutputBus")
    ):
        ignored.append("OutputBus")
    return tuple(ignored)


def _campaign_object_field(value: Mapping[str, Any], name: str) -> Any:
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


def _validated_archive_absolute_path(
    value: Any,
    *,
    label: str,
) -> ArchiveAbsolutePath:
    if not isinstance(value, str):
        raise CampaignEvidenceError(f"{label} is not an absolute host path")
    try:
        return parse_archive_absolute_path(value)
    except ArchiveRelativePathError as exc:
        raise CampaignEvidenceError(
            f"{label} is not an absolute host path"
        ) from exc


def _validate_file_proof(
    value: Any,
    *,
    label: str,
    relative_optional: bool,
    has_mtime: bool,
) -> None:
    keys = {"path", "relative_path", "size", "sha256"}
    if has_mtime:
        keys.add("mtime_ns")
    row = _closed_oracle_mapping(value, keys, label=label)
    relative = row.get("relative_path")
    absolute = row.get("path")
    try:
        _validated_archive_absolute_path(absolute, label=f"{label}.path")
        relative_identity = (
            None
            if relative is None
            else parse_archive_relative_path(relative)
        )
        suffix_matches = (
            True
            if relative_identity is None
            else archive_absolute_has_relative_suffix(
                absolute,
                relative_identity.canonical,
            )
        )
    except ArchiveRelativePathError as exc:
        raise CampaignEvidenceError(f"{label} file proof is malformed") from exc
    if (
        not _nonempty_text(absolute)
        or not (relative is None if relative_optional and relative is None else _nonempty_text(relative))
        or (
            relative_identity is not None
            and (
                relative_identity.source_flavor != "posix"
                or relative_identity.canonical != relative
                or not suffix_matches
            )
        )
        or not _plain_int(row.get("size"))
        or not _sha256_text_value(row.get("sha256"))
        or (has_mtime and not _plain_int(row.get("mtime_ns"), minimum=1))
    ):
        raise CampaignEvidenceError(f"{label} file proof is malformed")


def _validate_materialized_object(
    value: Any,
    *,
    expected_key: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {
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
        },
        label=label,
    )
    if (
        row.get("key") != expected_key
        or any(not _nonempty_text(row.get(field)) for field in ("id", "name", "type", "path"))
        or not _optional_text(row.get("parent_id"))
        or not _optional_text(row.get("notes"))
        or not _optional_text(row.get("source_language"))
        or row.get("is_included") not in {None, True, False}
        or not _plain_int(row.get("children_count"))
        or not isinstance(row.get("properties"), list)
        or not isinstance(row.get("references"), list)
    ):
        raise CampaignEvidenceError(f"{label} materialized object is malformed")
    for item in row["properties"]:
        prop = _closed_oracle_mapping(item, {"name", "value"}, label=f"{label} property")
        if not _nonempty_text(prop.get("name")) or not _json_scalar(prop.get("value")):
            raise CampaignEvidenceError(f"{label} property is malformed")
    for item in row["references"]:
        reference = _closed_oracle_mapping(
            item,
            {"name", "target_id"},
            label=f"{label} reference",
        )
        if not _nonempty_text(reference.get("name")) or not _nonempty_text(reference.get("target_id")):
            raise CampaignEvidenceError(f"{label} reference is malformed")
    _validate_campaign_active_source_fields(
        row,
        label=label,
        require_for_language=row.get("source_language") is not None,
    )


def _validate_campaign_active_source_fields(
    row: Mapping[str, Any],
    *,
    label: str,
    require_for_language: bool,
) -> None:
    source_id = row.get("active_source_id")
    source_name = row.get("active_source_name")
    source_path = row.get("active_source_path")
    present = tuple(value is not None for value in (source_id, source_name, source_path))
    if (
        (any(present) and not all(present))
        or (require_for_language and not all(present))
        or (
            all(present)
            and (
                not _nonempty_text(source_id)
                or not _nonempty_text(source_name)
                or not _nonempty_text(source_path)
                or source_path != f"{row.get('path')}\\{source_name}"
                or row.get("type") != "Sound"
                or not _nonempty_text(row.get("source_language"))
            )
        )
    ):
        raise CampaignEvidenceError(f"{label} activeSource binding is malformed")


def _validate_object_snapshot(value: Any, *, label: str) -> None:
    snapshot_keys = {"objects", "absent_paths", "sibling_prefix_rows", "digest"}
    if isinstance(value, Mapping) and "override_output_rows" in value:
        snapshot_keys.add("override_output_rows")
    row = _closed_oracle_mapping(
        value,
        snapshot_keys,
        label=label,
    )
    objects = row.get("objects")
    absent = row.get("absent_paths")
    prefixes = row.get("sibling_prefix_rows")
    if (
        not isinstance(objects, list)
        or not isinstance(absent, list)
        or any(not _nonempty_text(item) for item in absent)
        or not isinstance(prefixes, list)
        or not _sha256_text_value(row.get("digest"))
    ):
        raise CampaignEvidenceError(f"{label} object snapshot is malformed")
    keys: list[str] = []
    for item in objects:
        key = item.get("key") if isinstance(item, Mapping) else None
        if not _nonempty_text(key):
            raise CampaignEvidenceError(f"{label} object snapshot key is invalid")
        keys.append(str(key))
        _validate_materialized_object(item, expected_key=str(key), label=f"{label} object")
    if len(keys) != len(set(keys)):
        raise CampaignEvidenceError(f"{label} object snapshot keys are duplicated")
    override_rows = row.get("override_output_rows")
    if override_rows is not None:
        overrides = _campaign_object_override_output_map(
            row,
            required_keys=set(keys),
            label=label,
        )
        if set(overrides) != set(keys):
            raise CampaignEvidenceError(
                f"{label} OverrideOutput keys differ from object keys"
            )
    for item in prefixes:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not _nonempty_text(item[0])
            or not isinstance(item[1], list)
            or any(
                not isinstance(child, list)
                or len(child) != 3
                or any(not _nonempty_text(field) for field in child)
                for child in item[1]
            )
        ):
            raise CampaignEvidenceError(f"{label} sibling-prefix proof is malformed")
    digest_payload = {
        "objects": objects,
        "absent_paths": absent,
        "sibling_prefix_rows": prefixes,
    }
    if override_rows is not None:
        digest_payload["override_output_rows"] = override_rows
    expected_digest = _canonical_sha256(digest_payload)
    if row.get("digest") != expected_digest:
        raise CampaignEvidenceError(f"{label} object snapshot digest is invalid")


def _validate_import_snapshot(
    value: Any,
    *,
    scenario_id: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {
            "scenario_id",
            "rows",
            "events",
            "project_xml_files",
            "originals_files",
            "input_files",
            "xml_identities",
        },
        label=label,
    )
    if row.get("scenario_id") != scenario_id:
        raise CampaignEvidenceError(f"{label} scenario identity is invalid")
    for collection in (
        "rows",
        "events",
        "project_xml_files",
        "originals_files",
        "input_files",
        "xml_identities",
    ):
        if not isinstance(row.get(collection), list):
            raise CampaignEvidenceError(f"{label} {collection} is not an array")
    for item in row["rows"]:
        state = _closed_oracle_mapping(
            item,
            {"row_key", "target_path", "language", "object"},
            label=f"{label} import row",
        )
        if any(
            not _nonempty_text(state.get(field))
            for field in ("row_key", "target_path", "language")
        ):
            raise CampaignEvidenceError(f"{label} import row identity is malformed")
        object_value = state.get("object")
        if object_value is None:
            continue
        object_row = _closed_oracle_mapping(
            object_value,
            {"id", "name", "type", "path", "parent_id", "notes", "audio_source"},
            label=f"{label} imported object",
        )
        if (
            any(not _nonempty_text(object_row.get(field)) for field in ("id", "name", "type", "path"))
            or not _optional_text(object_row.get("parent_id"))
            or not _optional_text(object_row.get("notes"))
        ):
            raise CampaignEvidenceError(f"{label} imported object is malformed")
        source = object_row.get("audio_source")
        if source is not None:
            source_row = _closed_oracle_mapping(
                source,
                {"id", "language", "notes", "original_file", "original_relative_path"},
                label=f"{label} audio source",
            )
            if (
                not _nonempty_text(source_row.get("id"))
                or not _nonempty_text(source_row.get("language"))
                or not _optional_text(source_row.get("notes"))
                or not _nonempty_text(source_row.get("original_relative_path"))
            ):
                raise CampaignEvidenceError(f"{label} audio source is malformed")
            _validate_file_proof(
                source_row.get("original_file"),
                label=f"{label} Original file",
                relative_optional=True,
                has_mtime=False,
            )
            _validate_import_original_path_binding(
                source_row.get("original_file"),
                original_relative_path=source_row.get("original_relative_path"),
                originals_files=row["originals_files"],
                label=f"{label} Original file",
            )
    for item in row["events"]:
        event = _closed_oracle_mapping(
            item,
            {"path", "id", "action_id", "action_type", "target", "child_count"},
            label=f"{label} event",
        )
        if (
            not _nonempty_text(event.get("path"))
            or not _optional_text(event.get("id"))
            or not _optional_text(event.get("action_id"))
            or not (
                event.get("action_type") is None
                or type(event.get("action_type")) is int
            )
            or not _json_archive_value(event.get("target"))
            or not _plain_int(event.get("child_count"))
        ):
            raise CampaignEvidenceError(f"{label} event is malformed")
    for collection in ("project_xml_files", "originals_files"):
        for item in row[collection]:
            _validate_file_proof(
                item,
                label=f"{label} {collection}",
                relative_optional=True,
                has_mtime=False,
            )
    for item in row["input_files"]:
        if (
            not isinstance(item, list)
            or len(item) != 4
            or not _nonempty_text(item[0])
            or type(item[1]) is not bool
            or not (item[2] is None or _plain_int(item[2]))
            or not _optional_text(item[3])
        ):
            raise CampaignEvidenceError(f"{label} input file state is malformed")
    for item in row["xml_identities"]:
        identity = _closed_oracle_mapping(
            item,
            {"guid", "relative_file", "element_tag", "name"},
            label=f"{label} XML identity",
        )
        if (
            not _nonempty_text(identity.get("guid"))
            or not _nonempty_text(identity.get("relative_file"))
            or not _nonempty_text(identity.get("element_tag"))
            or not _optional_text(identity.get("name"))
        ):
            raise CampaignEvidenceError(f"{label} XML identity is malformed")


def _validate_import_original_path_binding(
    proof: Any,
    *,
    original_relative_path: Any,
    originals_files: Any,
    label: str,
) -> None:
    try:
        requested_relative = parse_archive_relative_path(original_relative_path)
    except ArchiveRelativePathError as exc:
        raise CampaignEvidenceError(
            f"{label} relative path is not canonical"
        ) from exc
    if (
        requested_relative.source_flavor != "posix"
        or requested_relative.canonical != original_relative_path
    ):
        raise CampaignEvidenceError(
            f"{label} relative path is not canonical"
        )
    if not isinstance(proof, Mapping):
        raise CampaignEvidenceError(f"{label} proof is not an object")
    proof_relative = proof.get("relative_path")
    expected_relative = parse_archive_relative_path(
        f"Originals/{requested_relative.canonical}"
    )
    if (
        not isinstance(proof_relative, str)
        or proof_relative != expected_relative.canonical
    ):
        raise CampaignEvidenceError(
            f"{label} project-relative path is inconsistent"
        )
    absolute_path = proof.get("path")
    try:
        suffix_matches = archive_absolute_has_relative_suffix(
            absolute_path,
            expected_relative.canonical,
        )
    except (ArchiveRelativePathError, TypeError) as exc:
        raise CampaignEvidenceError(
            f"{label} absolute path is invalid"
        ) from exc
    if not suffix_matches:
        raise CampaignEvidenceError(
            f"{label} absolute/relative paths are inconsistent"
        )
    if not isinstance(originals_files, list) or not any(
        isinstance(item, Mapping) and dict(item) == dict(proof)
        for item in originals_files
    ):
        raise CampaignEvidenceError(
            f"{label} is absent from the sealed Originals tree"
        )


_OBJECT_ANSWER_NUMBER_RE = re.compile(
    r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])"
)
_OBJECT_ANSWER_CLAUSE_SPLIT_RE = re.compile(
    r"[，,、；;。.!！？?：:（）()\[\]\n]+|但(?:是)?|不过|然而|\bbut\b|\bhowever\b",
    re.IGNORECASE,
)
_OBJECT_ANSWER_GUID_RE = re.compile(
    r"\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}",
    re.IGNORECASE,
)


def _validate_object_query_gateway_payload(
    proof: Mapping[str, Any],
    *,
    gateway_payload: Mapping[str, Any],
    label: str,
) -> None:
    raw_rows = gateway_payload.get("objects")
    if (
        gateway_payload.get("contract") != "waapi-skill.gateway-result/v1"
        or gateway_payload.get("command") != "query-object"
        or not isinstance(raw_rows, list)
        or any(not isinstance(row, Mapping) for row in raw_rows)
        or gateway_payload.get("count") != len(raw_rows)
        or gateway_payload.get("count") != proof.get("raw_row_count")
        or gateway_payload.get("query_bound") != proof.get("query_bound")
    ):
        raise CampaignEvidenceError(f"{label} object.get broker rows are malformed")
    before = proof.get("before")
    before_rows = before.get("objects") if isinstance(before, Mapping) else None
    if not isinstance(before_rows, list):
        raise CampaignEvidenceError(f"{label} object.get before rows are unavailable")
    before_by_id = {
        str(row["id"]): str(row["key"])
        for row in before_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("id"))
    }
    before_by_key = {
        str(row["key"]): row
        for row in before_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("key"))
    }
    primary: list[str] = []
    derived: list[Mapping[str, Any]] = []
    raw_ids: list[str] = []
    for row in raw_rows:
        object_id = row.get("id")
        if not _nonempty_text(object_id):
            raise CampaignEvidenceError(f"{label} object.get broker row lacks identity")
        source_id = str(object_id)
        raw_ids.append(source_id)
        key = before_by_id.get(source_id)
        if key is None:
            derived.append(row)
        else:
            primary.append(key)
    observed_primary = proof.get("observed_keys")
    primary_policy = proof.get("primary_row_policy")
    if (
        not isinstance(observed_primary, list)
        or len(primary) != len(observed_primary)
        or primary != observed_primary
        or (
            primary_policy in {"unique_identity_rows", "ancestor_identity_rows"}
            and len(raw_ids) != len(set(raw_ids))
        )
        or primary_policy
        not in {
            "unique_identity_rows",
            "ancestor_identity_rows",
            "parent_projection_per_source_row",
        }
    ):
        raise CampaignEvidenceError(
            f"{label} object.get broker primary identities differ from oracle"
        )
    if primary_policy == "ancestor_identity_rows":
        expected_keys = proof.get("expected_payload_keys")
        primary_rows = [
            item
            for item in raw_rows
            if before_by_id.get(str(item.get("id"))) is not None
        ]
        if (
            not isinstance(expected_keys, list)
            or len(primary) != len(expected_keys)
            or set(primary) != set(expected_keys)
            or len(primary_rows) != len(expected_keys)
        ):
            raise CampaignEvidenceError(
                f"{label} object.get broker ancestor identity set differs from oracle"
            )
        for row, key in zip(primary_rows, primary, strict=True):
            sealed = before_by_key.get(str(key))
            if (
                sealed is None
                or row.get("id") != sealed.get("id")
                or row.get("name") != sealed.get("name")
                or row.get("type") != sealed.get("type")
                or row.get("path") != sealed.get("path")
                or row.get("childrenCount") != sealed.get("children_count")
                or row.get("notes") != sealed.get("notes")
            ):
                raise CampaignEvidenceError(
                    f"{label} object.get broker ancestor row differs from sealed fields"
                )
    elif primary_policy == "parent_projection_per_source_row":
        counts = Counter(primary)
        expected_keys = proof.get("expected_payload_keys")
        if not isinstance(expected_keys, list):
            raise CampaignEvidenceError(
                f"{label} object.get parent-projection keys are unavailable"
            )
        capacities = {
            key: sum(
                isinstance(row, Mapping)
                and row.get("type") == "Sound"
                and row.get("parent_id") == before_by_key[key].get("id")
                for row in before_rows
            )
            for key in expected_keys
        }
        if (
            set(primary) != set(expected_keys)
            or len(primary) == len(set(primary))
            or any(not 1 <= counts[key] <= capacities[key] for key in expected_keys)
            or sum(capacities.values()) != 12
        ):
            raise CampaignEvidenceError(
                f"{label} object.get broker parent multiplicities are invalid"
            )
        for row, key in zip(
            (item for item in raw_rows if before_by_id.get(str(item.get("id"))) is not None),
            primary,
            strict=True,
        ):
            sealed = before_by_key[key]
            references = sealed.get("references")
            bus_ids = [
                item.get("target_id")
                for item in references
                if isinstance(item, Mapping) and item.get("name") == "OutputBus"
            ] if isinstance(references, list) else []
            output_bus = row.get("OutputBus")
            output_bus_id = (
                str(output_bus.get("id"))
                if isinstance(output_bus, Mapping)
                and _nonempty_text(output_bus.get("id"))
                else str(output_bus)
                if _nonempty_text(output_bus)
                else None
            )
            if (
                len(bus_ids) != 1
                or row.get("id") != sealed.get("id")
                or row.get("name") != sealed.get("name")
                or row.get("type") != sealed.get("type")
                or row.get("path") != sealed.get("path")
                or row.get("childrenCount") != sealed.get("children_count")
                or row.get("notes") != sealed.get("notes")
                or output_bus_id != bus_ids[0]
            ):
                raise CampaignEvidenceError(
                    f"{label} object.get broker duplicate parent row differs from sealed fields"
                )
    expected_derived = proof.get("derived_rows")
    if not isinstance(expected_derived, list) or len(derived) != len(expected_derived):
        raise CampaignEvidenceError(
            f"{label} object.get broker derived count differs from oracle"
        )
    expected_by_id = {
        str(row["id"]): row
        for row in expected_derived
        if isinstance(row, Mapping) and _nonempty_text(row.get("id"))
    }
    normalized: dict[str, dict[str, Any]] = {}
    for row in derived:
        source_id = str(row["id"])
        expected = expected_by_id.get(source_id)
        if expected is None:
            raise CampaignEvidenceError(
                f"{label} object.get broker has an unknown derived identity"
            )
        language = _campaign_language_name(row.get("audioSource:language"))
        parent = row.get("parent")
        parent_id = (
            str(parent.get("id"))
            if isinstance(parent, Mapping) and _nonempty_text(parent.get("id"))
            else str(parent)
            if _nonempty_text(parent)
            else None
        )
        normalized[source_id] = {
            "sound_key": expected.get("sound_key"),
            "sound_id": expected.get("sound_id"),
            "id": source_id,
            "name": row.get("name"),
            "type": row.get("type"),
            "path": row.get("path"),
            "parent_id": parent_id,
            "language": language,
        }
    if [normalized.get(str(row["id"])) for row in expected_derived] != expected_derived:
        raise CampaignEvidenceError(
            f"{label} object.get broker derived rows differ from sealed oracle"
        )


def _campaign_language_name(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if not isinstance(value, Mapping):
        return None
    candidates = [
        value[key]
        for key in ("name", "displayName", "shortName")
        if key in value
    ]
    if (
        not candidates
        or any(not isinstance(item, str) or not item for item in candidates)
        or len(set(candidates)) != 1
    ):
        return None
    return str(candidates[0])


def _validate_archived_deduplicated_parent_answer(
    proof: Mapping[str, Any],
    *,
    final_response: str,
    label: str,
) -> None:
    before = proof.get("before")
    before_rows = before.get("objects") if isinstance(before, Mapping) else None
    required_keys = proof.get("required_keys")
    excluded_keys = proof.get("excluded_keys")
    parent_rows = proof.get("deduplicated_parent_rows")
    coverage = proof.get("coverage_summary")
    order = proof.get("observed_answer_order")
    if (
        not isinstance(before_rows, list)
        or not isinstance(required_keys, list)
        or not isinstance(excluded_keys, list)
        or not isinstance(parent_rows, list)
        or not isinstance(order, list)
        or not isinstance(coverage, Mapping)
    ):
        raise CampaignEvidenceError(f"{label} parent-summary arrays are invalid")
    before_by_key = {
        str(row["key"]): row
        for row in before_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("key"))
    }
    before_by_id = {
        str(row["id"]): row
        for row in before_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("id"))
    }
    if (
        len(required_keys) != 3
        or [row.get("key") for row in parent_rows if isinstance(row, Mapping)]
        != required_keys
        or order != required_keys
    ):
        raise CampaignEvidenceError(f"{label} parent-summary identity order is invalid")

    lines = final_response.splitlines()
    previous_line = -1
    expected_direct_child_count = 0
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
    for archived, key in zip(parent_rows, required_keys, strict=True):
        row = _closed_oracle_mapping(
            archived,
            row_keys,
            label=f"{label} deduplicated parent row",
        )
        sealed = before_by_key.get(str(key))
        if sealed is None:
            raise CampaignEvidenceError(f"{label} parent-summary key is not sealed")
        references = sealed.get("references")
        bus_ids = [
            item.get("target_id")
            for item in references
            if isinstance(item, Mapping) and item.get("name") == "OutputBus"
        ] if isinstance(references, list) else []
        bus = before_by_id.get(str(bus_ids[0])) if len(bus_ids) == 1 else None
        path = str(sealed.get("path") or "")
        matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in _campaign_path_token_offsets(line, path)
        ]
        line_index = matches[0][0] if len(matches) == 1 else None
        line = lines[line_index] if line_index is not None else ""
        children_count = sealed.get("children_count")
        notes = sealed.get("notes")
        numeric_source = line
        for token in (
            str(sealed.get("id") or ""),
            path,
            str(bus.get("id") or "") if bus is not None else "",
            str(bus.get("name") or "") if bus is not None else "",
        ):
            if token:
                numeric_source = numeric_source.replace(token, "")
        numbers = [
            float(value)
            for value in _OBJECT_ANSWER_NUMBER_RE.findall(numeric_source)
        ]
        if (
            bus is None
            or type(children_count) is not int
            or len(matches) != 1
            or line_index is None
            or line_index <= previous_line
            or row.get("key") != key
            or row.get("name") != sealed.get("name")
            or row.get("id") != sealed.get("id")
            or row.get("path") != path
            or row.get("children_count") != children_count
            or row.get("notes") != notes
            or row.get("output_bus_id") != bus.get("id")
            or row.get("output_bus_name") != bus.get("name")
            or row.get("line_index") != line_index
            or row.get("line_sha256")
            != hashlib.sha256(line.encode("utf-8")).hexdigest()
            or str(sealed.get("id")).casefold() not in line.casefold()
            or str(sealed.get("name")).casefold() not in line.casefold()
            or not isinstance(notes, str)
            or notes.casefold() not in line.casefold()
            or str(bus.get("name")).casefold() not in line.casefold()
            or numbers != [float(children_count)]
        ):
            raise CampaignEvidenceError(
                f"{label} parent-summary row differs from final/sealed fields"
            )
        previous_line = line_index
        expected_direct_child_count += children_count

    for key in excluded_keys:
        sealed = before_by_key.get(str(key))
        if sealed is None:
            raise CampaignEvidenceError(f"{label} excluded parent key is not sealed")
        if any(
            _campaign_path_token_offsets(line, str(sealed.get("path") or ""))
            for line in lines
        ):
            raise CampaignEvidenceError(
                f"{label} parent summary contains an excluded path"
            )

    summary_line_index: int | None = None
    for index, line in enumerate(lines):
        lowered = line.casefold()
        numbers = {
            int(float(value)) for value in _OBJECT_ANSWER_NUMBER_RE.findall(line)
        }
        if (
            ("父" in line or "container" in lowered)
            and "sound" in lowered
            and len(required_keys) in numbers
            and proof.get("raw_row_count") in numbers
        ):
            summary_line_index = index
            break
    raw_row_count = proof.get("raw_row_count")
    bound_disclosed, incomplete_disclosed = bounded_result_disclosure(
        final_response,
        take=raw_row_count if type(raw_row_count) is int else 0,
    )
    claims_twelve_sounds = _campaign_claims_twelve_confirmed_sounds(
        final_response
    )
    expected_coverage = {
        "unique_parent_count": len(required_keys),
        "confirmed_sound_count": proof.get("raw_row_count"),
        "direct_child_object_count": expected_direct_child_count,
        "summary_line_index": summary_line_index,
        "bound_disclosed": bound_disclosed,
        "incomplete_disclosed": incomplete_disclosed,
        "claims_twelve_sounds": claims_twelve_sounds,
    }
    if (
        proof.get("raw_row_count") != 10
        or expected_direct_child_count != 12
        or coverage != expected_coverage
        or summary_line_index is None
        or not bound_disclosed
        or not incomplete_disclosed
        or claims_twelve_sounds
    ):
        raise CampaignEvidenceError(
            f"{label} parent coverage summary differs from final/sealed counts"
        )


def _campaign_claims_twelve_confirmed_sounds(value: str) -> bool:
    """Independently reject positive 12-Sound coverage claims by clause."""

    negated_confirmation = (
        "不等同于已确认",
        "不等于已确认",
        "不代表已确认",
        "不是已确认",
        "并非已确认",
        "不能视为已确认",
        "不能算作已确认",
        "not confirmed",
        "does not mean confirmed",
        "doesn't mean confirmed",
        "does not represent confirmed",
        "is not confirmed",
    )
    for clause in _OBJECT_ANSWER_CLAUSE_SPLIT_RE.split(value):
        folded = clause.casefold().strip()
        if not folded:
            continue
        numbers = {
            int(float(token))
            for token in _OBJECT_ANSWER_NUMBER_RE.findall(clause)
        }
        if (
            12 not in numbers
            or "sound" not in folded
            or not any(
                token in folded
                for token in ("覆盖", "确认", "cover", "confirm")
            )
        ):
            continue
        if any(token in folded for token in negated_confirmation):
            continue
        return True
    return False


def _validate_archived_ordered_ancestor_answer(
    proof: Mapping[str, Any],
    *,
    final_response: str,
    label: str,
) -> None:
    """Rebuild GET-05's answer oracle from sealed rows and final.txt."""

    before = proof.get("before")
    before_rows = before.get("objects") if isinstance(before, Mapping) else None
    required_keys = proof.get("required_keys")
    excluded_keys = proof.get("excluded_keys")
    observed_keys = proof.get("observed_keys")
    expected_keys = proof.get("expected_payload_keys")
    ancestor_rows = proof.get("deduplicated_parent_rows")
    coverage = proof.get("coverage_summary")
    answer_order = proof.get("observed_answer_order")
    query_bound = proof.get("query_bound")
    if (
        not isinstance(before_rows, list)
        or not isinstance(required_keys, list)
        or not isinstance(excluded_keys, list)
        or not isinstance(observed_keys, list)
        or not isinstance(expected_keys, list)
        or not isinstance(ancestor_rows, list)
        or len(ancestor_rows) != len(required_keys)
        or not isinstance(coverage, Mapping)
        or not isinstance(answer_order, list)
        or len(required_keys) != 5
        or len(observed_keys) != len(expected_keys)
        or len(observed_keys) != len(set(observed_keys))
        or set(observed_keys) != set(expected_keys)
        or required_keys != expected_keys
        or answer_order != required_keys
        or proof.get("raw_row_count") != 5
        or query_bound != {"mode": "take", "value": 8}
        or proof.get("bound_reached") is not False
    ):
        raise CampaignEvidenceError(
            f"{label} ordered ancestor cardinality/order boundary is invalid"
        )
    before_by_key = {
        str(row["key"]): row
        for row in before_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("key"))
    }
    if any(key not in before_by_key for key in (*required_keys, *excluded_keys)):
        raise CampaignEvidenceError(
            f"{label} ordered ancestor proof references an unsealed key"
        )
    chain = [before_by_key[key] for key in required_keys]
    target = before_by_key.get("q5_target")
    if (
        target is None
        or not chain
        or target.get("parent_id") != chain[0].get("id")
        or any(
            child.get("parent_id") != parent.get("id")
            for child, parent in zip(chain, chain[1:])
        )
        or any(row.get("type") == "Project" for row in chain)
    ):
        raise CampaignEvidenceError(
            f"{label} sealed ancestors are not the target's near-to-far parent chain"
        )

    sealed_counts = {
        "random_sequence_container_count": sum(
            before_by_key[key].get("type") == "RandomSequenceContainer"
            for key in required_keys
        ),
        "actor_mixer_count": sum(
            before_by_key[key].get("type") == "ActorMixer"
            for key in required_keys
        ),
        "work_unit_count": sum(
            before_by_key[key].get("type") == "WorkUnit"
            for key in required_keys
        ),
        "default_work_unit_count": sum(
            before_by_key[key].get("name") == "Default Work Unit"
            for key in required_keys
        ),
    }
    if sealed_counts != {
        "random_sequence_container_count": 1,
        "actor_mixer_count": 2,
        "work_unit_count": 2,
        "default_work_unit_count": 1,
    }:
        raise CampaignEvidenceError(
            f"{label} sealed ordered ancestor type distribution is invalid"
        )

    lines = final_response.splitlines()
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
    recomputed_rows: list[dict[str, Any]] = []
    row_line_indexes: list[int] = []
    for ordinal, (archived, key) in enumerate(
        zip(ancestor_rows, required_keys, strict=True),
        start=1,
    ):
        row = _closed_oracle_mapping(
            archived,
            row_keys,
            label=f"{label} ordered ancestor row",
        )
        sealed = before_by_key[key]
        path = sealed.get("path")
        if not _nonempty_text(path):
            raise CampaignEvidenceError(
                f"{label} sealed ordered ancestor path is invalid"
            )
        matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in _campaign_path_token_offsets(line, str(path))
        ]
        line_index = matches[0][0] if len(matches) == 1 else None
        line = lines[line_index] if line_index is not None else ""
        numbers = _campaign_ancestor_numeric_values(line, sealed)
        ordinal_present = numbers == [
            float(ordinal),
            float(sealed.get("children_count")),
        ]
        notes_present = _campaign_ancestor_notes_present(
            line, sealed.get("notes")
        )
        recomputed = {
            "key": key,
            "name": sealed.get("name"),
            "id": sealed.get("id"),
            "type": sealed.get("type"),
            "path": path,
            "children_count": sealed.get("children_count"),
            "notes": sealed.get("notes"),
            "notes_present": notes_present,
            "ordinal": ordinal,
            "ordinal_present": ordinal_present,
            "numeric_values": numbers,
            "line_index": line_index,
            "line_sha256": (
                hashlib.sha256(line.encode("utf-8")).hexdigest()
                if line_index is not None
                else None
            ),
        }
        if (
            len(matches) != 1
            or row != recomputed
            or not _nonempty_text(sealed.get("name"))
            or not _nonempty_text(sealed.get("id"))
            or not _nonempty_text(sealed.get("type"))
            or str(sealed["name"]).casefold() not in line.casefold()
            or str(sealed["id"]).casefold() not in line.casefold()
            or str(sealed["type"]).casefold() not in line.casefold()
            or type(sealed.get("children_count")) is not int
            or numbers
            not in (
                [float(sealed["children_count"])],
                [float(ordinal), float(sealed["children_count"])],
            )
            or not notes_present
        ):
            raise CampaignEvidenceError(
                f"{label} ordered ancestor row differs from final/sealed fields"
            )
        recomputed_rows.append(recomputed)
        row_line_indexes.append(int(line_index))
    if (
        len(ancestor_rows) != len(required_keys)
        or row_line_indexes != sorted(row_line_indexes)
        or len(row_line_indexes) != len(set(row_line_indexes))
    ):
        raise CampaignEvidenceError(
            f"{label} ordered ancestor rows are not near-to-far"
        )

    folded = final_response.casefold()
    for key in excluded_keys:
        sealed = before_by_key[key]
        if (
            str(sealed.get("id") or "").casefold() in folded
            or any(
                _campaign_path_token_offsets(line, str(sealed.get("path") or ""))
                for line in lines
            )
        ):
            raise CampaignEvidenceError(
                f"{label} ordered ancestor answer contains a decoy identity"
            )
    row_line_set = set(row_line_indexes)
    if any(
        index not in row_line_set
        and "project" in line.casefold()
        and (
            _OBJECT_ANSWER_GUID_RE.search(line) is not None
            or (line.count("|") >= 3 and "\\" in line)
        )
        for index, line in enumerate(lines)
    ):
        raise CampaignEvidenceError(
            f"{label} ordered ancestor answer contains a Project row"
        )

    type_summary_lines: set[int] = set()
    for type_name, expected_count in (
        ("RandomSequenceContainer", 1),
        ("ActorMixer", 2),
        ("WorkUnit", 2),
    ):
        indexes = _campaign_exact_summary_count_lines(
            lines,
            type_name,
            expected_count,
            excluded_line_indexes=row_line_set,
        )
        if not indexes:
            raise CampaignEvidenceError(
                f"{label} ordered ancestor type summary differs for {type_name}"
            )
        type_summary_lines.update(indexes)
    truncation_claimed = _campaign_claims_ancestor_truncation(final_response)
    expected_coverage = {
        **sealed_counts,
        "raw_row_count": 5,
        "take": 8,
        "bound_reached": False,
        "summary_line_indexes": sorted(type_summary_lines),
        "truncation_claimed": truncation_claimed,
    }
    if coverage != expected_coverage or truncation_claimed:
        raise CampaignEvidenceError(
            f"{label} ordered ancestor summary differs from final/sealed chain"
        )


def _campaign_ancestor_notes_present(line: str, notes: Any) -> bool:
    cells = _campaign_markdown_row_cells(line)
    if cells is not None:
        note_cell = cells[-1].strip().strip("`").casefold()
        if isinstance(notes, str) and notes:
            return notes.casefold() in note_cell
        return note_cell in {
            "",
            "-",
            "—",
            "无",
            "无备注",
            "未设置",
            "none",
            "empty",
            "n/a",
            "null",
        }
    if isinstance(notes, str) and notes:
        return notes.casefold() in line.casefold()
    return re.search(
        r"(?:备注|notes?)\s*[:：]?\s*(?:无|无备注|未设置|none|empty|n/a|null|[-—])(?:\s|$)",
        line,
        re.IGNORECASE,
    ) is not None


def _campaign_markdown_row_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    cells = tuple(cell.strip() for cell in stripped.strip("|").split("|"))
    return cells if len(cells) >= 2 else None


def _campaign_ancestor_numeric_values(
    line: str,
    sealed: Mapping[str, Any],
) -> list[float]:
    numeric_source = line
    for token in (
        str(sealed.get("id") or ""),
        str(sealed.get("path") or ""),
        str(sealed.get("name") or ""),
        str(sealed.get("type") or ""),
        str(sealed.get("notes") or ""),
    ):
        if token:
            numeric_source = numeric_source.replace(token, "")
    return [
        float(value)
        for value in _OBJECT_ANSWER_NUMBER_RE.findall(numeric_source)
    ]


def _campaign_exact_summary_count_lines(
    lines: Sequence[str],
    type_name: str,
    expected_count: int,
    *,
    excluded_line_indexes: set[int],
) -> tuple[int, ...]:
    indexes: list[int] = []
    aliases = {
        "RandomSequenceContainer": (
            "randomsequencecontainer",
            "random container",
        ),
        "ActorMixer": ("actormixer", "actor mixer"),
        "WorkUnit": ("workunit", "work unit"),
    }.get(type_name, (type_name.casefold(),))
    for index, line in enumerate(lines):
        if index in excluded_line_indexes:
            continue
        matched = False
        for clause in _OBJECT_ANSWER_CLAUSE_SPLIT_RE.split(line):
            folded_clause = clause.casefold()
            if type_name == "WorkUnit" and "default work unit" in folded_clause:
                continue
            if not any(alias in folded_clause for alias in aliases):
                continue
            numbers = {
                int(float(value))
                for value in _OBJECT_ANSWER_NUMBER_RE.findall(clause)
            }
            if numbers and numbers != {expected_count}:
                return ()
            if numbers == {expected_count}:
                matched = True
        if matched:
            indexes.append(index)
    return tuple(indexes)


def _campaign_claims_ancestor_truncation(value: str) -> bool:
    negative = (
        "未截断",
        "没有截断",
        "并未截断",
        "未达到",
        "没有达到",
        "未触及",
        "not truncated",
        "did not reach",
        "not reach",
    )
    positive = (
        "截断",
        "触及上限",
        "达到上限",
        "上限已触及",
        "结果不完整",
        "truncated",
        "reached the limit",
        "incomplete",
    )
    for clause in _OBJECT_ANSWER_CLAUSE_SPLIT_RE.split(value):
        folded = clause.casefold()
        if any(token in folded for token in negative):
            continue
        if any(token in folded for token in positive):
            return True
    return False


def _validate_archived_paired_path_answer(
    proof: Mapping[str, Any],
    *,
    final_response: str,
    label: str,
) -> None:
    lines = final_response.splitlines()
    before = proof.get("before")
    before_rows = before.get("objects") if isinstance(before, Mapping) else None
    if not isinstance(before_rows, list):
        raise CampaignEvidenceError(f"{label} paired answer lacks sealed before rows")
    all_languages = {
        str(row["source_language"])
        for row in before_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("source_language"))
    }
    all_notes = {
        str(row["notes"]).casefold()
        for row in before_rows
        if (
            isinstance(row, Mapping)
            and row.get("type") == "Sound"
            and _nonempty_text(row.get("notes"))
        )
    }
    required = proof.get("required_identity_tokens")
    excluded = proof.get("excluded_identity_tokens")
    paired = proof.get("paired_rows")
    order = proof.get("observed_answer_order")
    if not all(isinstance(value, list) for value in (required, excluded, paired, order)):
        raise CampaignEvidenceError(f"{label} paired answer arrays are invalid")
    required_tokens = [
        _closed_oracle_mapping(
            item,
            {"key", "path", "occurrence_count", "first_line"},
            label=f"{label} required path token",
        )
        for item in required
    ]
    first_lines = [token.get("first_line") for token in required_tokens]
    paired_line_hashes = [
        row.get("line_sha256") if isinstance(row, Mapping) else None
        for row in paired
    ]
    if (
        not first_lines
        or any(type(index) is not int or index < 0 for index in first_lines)
        or not paired_line_hashes
        or any(not _sha256_text_value(value) for value in paired_line_hashes)
    ):
        raise CampaignEvidenceError(f"{label} required answer scope is invalid")
    paired_line_indexes = [
        index
        for line_hash in paired_line_hashes
        for index, line in enumerate(lines)
        if hashlib.sha256(line.encode("utf-8")).hexdigest() == line_hash
    ]
    if len(paired_line_indexes) != len(paired_line_hashes):
        raise CampaignEvidenceError(f"{label} paired path proof scope is invalid")
    answer_start = min(paired_line_indexes)
    answer_lines = tuple(enumerate(lines[answer_start:], start=answer_start))
    for token in required_tokens:
        path = token.get("path")
        if not _nonempty_text(path):
            raise CampaignEvidenceError(f"{label} required path is invalid")
        matches = [
            (index, offset)
            for index, line in answer_lines
            for offset in _campaign_path_token_offsets(line, str(path))
        ]
        if (
            token.get("occurrence_count") != len(matches)
            or token.get("first_line") != (matches[0][0] if matches else None)
            or not matches
        ):
            raise CampaignEvidenceError(
                f"{label} required standalone path proof differs from final.txt"
            )
    for item in excluded:
        token = _closed_oracle_mapping(
            item,
            {"key", "path", "occurrence_count"},
            label=f"{label} excluded path token",
        )
        path = token.get("path")
        if not _nonempty_text(path):
            raise CampaignEvidenceError(f"{label} excluded path is invalid")
        matches = [
            offset
            for _, line in answer_lines
            for offset in _campaign_path_token_offsets(line, str(path))
        ]
        if token.get("occurrence_count") != len(matches) or matches:
            raise CampaignEvidenceError(
                f"{label} excluded standalone path proof differs from final.txt"
            )
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
    observed_order: list[tuple[int, str]] = []
    for item in paired:
        row = _closed_oracle_mapping(
            item,
            pair_keys,
            label=f"{label} paired path row",
        )
        if any(
            not _nonempty_text(row.get(field))
            for field in (
                "child_key",
                "parent_key",
                "parent_path",
                "child_path",
                "language",
                "notes",
            )
        ) or isinstance(row.get("volume"), bool) or not isinstance(
            row.get("volume"), (int, float)
        ):
            raise CampaignEvidenceError(f"{label} paired path row values are invalid")
        child_matches = [
            (index, offset)
            for index, line in answer_lines
            for offset in _campaign_path_token_offsets(line, str(row["child_path"]))
        ]
        line_index = child_matches[0][0] if child_matches else None
        line = lines[line_index] if line_index is not None else ""
        numeric_values = [
            float(value) for value in _OBJECT_ANSWER_NUMBER_RE.findall(line)
        ]
        recomputed = {
            "line_index": line_index,
            "line_sha256": (
                hashlib.sha256(line.encode("utf-8")).hexdigest()
                if line_index is not None
                else None
            ),
            "parent_path_count": len(
                _campaign_path_token_offsets(line, str(row["parent_path"]))
            ),
            "child_path_count": len(
                _campaign_path_token_offsets(line, str(row["child_path"]))
            ),
            "language_present": str(row["language"]).casefold()
            in line.casefold(),
            "volume_values": numeric_values,
            "notes_present": str(row["notes"]).casefold() in line.casefold(),
            "unexpected_languages": sorted(
                language
                for language in all_languages
                if language != row["language"]
                and language.casefold() in line.casefold()
            ),
            "unexpected_notes": sorted(
                notes
                for notes in all_notes
                if notes != str(row["notes"]).casefold()
                and notes in line.casefold()
            ),
        }
        if (
            len(child_matches) != 1
            or any(row.get(key) != value for key, value in recomputed.items())
            or row.get("parent_path_count") != 1
            or row.get("child_path_count") != 1
            or row.get("language_present") is not True
            or row.get("volume_values") != [float(row["volume"])]
            or row.get("notes_present") is not True
            or row.get("unexpected_languages") != []
            or row.get("unexpected_notes") != []
        ):
            raise CampaignEvidenceError(
                f"{label} paired path proof differs from final.txt"
            )
        observed_order.append((int(line_index), str(row["child_key"])))
    if [key for _, key in sorted(observed_order)] != order:
        raise CampaignEvidenceError(f"{label} paired path order differs from final.txt")


def _campaign_path_token_offsets(value: str, path: str) -> tuple[int, ...]:
    offsets: list[int] = []
    start = 0
    while True:
        index = value.find(path, start)
        if index < 0:
            break
        end = index + len(path)
        before = value[index - 1] if index else ""
        after = value[end] if end < len(value) else ""
        if before != "\\" and after != "\\":
            offsets.append(index)
        start = index + 1
    return tuple(offsets)


def _validate_heavy_v3_import_oracle(
    value: Any,
    *,
    scenario_id: str,
    zero_dispatch: bool,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"scenario_id", "phase", "passed", "failures", "before", "after"},
        label=label,
    )
    _require_passing_oracle(row, label=label)
    expected_phase = "zero_dispatch" if zero_dispatch else "after_execution"
    if row.get("scenario_id") != scenario_id or row.get("phase") != expected_phase:
        raise CampaignEvidenceError(f"{label} import identity/phase is invalid")
    _validate_import_snapshot(row.get("before"), scenario_id=scenario_id, label=f"{label} before")
    _validate_import_snapshot(row.get("after"), scenario_id=scenario_id, label=f"{label} after")
    if zero_dispatch and row.get("before") != row.get("after"):
        raise CampaignEvidenceError(f"{label} zero-dispatch import state changed")
    if not zero_dispatch:
        before = row["before"]
        after = row["after"]
        before_row_keys = [item["row_key"] for item in before["rows"]]
        after_row_keys = [item["row_key"] for item in after["rows"]]
        if (
            before["input_files"] != after["input_files"]
            or before_row_keys != after_row_keys
            or not after["rows"]
            or any(item.get("object") is None for item in after["rows"])
            or not after["project_xml_files"]
            or not after["originals_files"]
            or before["project_xml_files"] == after["project_xml_files"]
            or before["originals_files"] == after["originals_files"]
            or before == after
        ):
            raise CampaignEvidenceError(f"{label} import business delta is invalid")
        if after["events"] and any(
            item.get("id") is None
            or item.get("action_id") is None
            or item.get("child_count", 0) < 1
            for item in after["events"]
        ):
            raise CampaignEvidenceError(f"{label} import Event/Action proof is invalid")


def _compound_import_legacy_verification(
    value: Any,
    *,
    label: str,
) -> Mapping[str, Any]:
    """Project an already typed-validated compound snapshot to its business view."""

    row = _closed_oracle_mapping(
        value,
        {"scenario_id", "phase", "passed", "failures", "before", "after"},
        label=label,
    )
    projected = dict(row)
    for phase in ("before", "after"):
        snapshot = _closed_oracle_mapping(
            row.get(phase),
            {
                "scenario_id",
                "business",
                "rows",
                "reference_fixtures",
                "main_bus",
            },
            label=f"{label} compound {phase}",
        )
        if snapshot.get("scenario_id") != row.get("scenario_id"):
            raise CampaignEvidenceError(
                f"{label} compound {phase} scenario identity is misbound"
            )
        projected[phase] = snapshot.get("business")
    return projected


def _validate_heavy_v3_audio_conversion_oracle(
    value: Any,
    *,
    expected_operation_request: Mapping[str, Any],
    expected_byte_change_paths: tuple[str, ...],
    expected_verify_payload_sha256: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"phase", "passed", "failures", "evidence"},
        label=label,
    )
    _require_passing_oracle(row, label=label)
    evidence = _closed_oracle_mapping(
        row.get("evidence"),
        {
            "before",
            "after",
            "target_slots",
            "observed_target_paths",
            "after_digest",
            "volatile_cache_files_before",
            "volatile_cache_files_after",
            "volatile_cache_changed_paths",
            "byte_change_required_paths",
            "operation_request",
            "operation_request_sha256",
            "verify_request_sha256",
            "verify_payload_sha256",
        },
        label=f"{label} evidence",
    )
    _validate_audio_conversion_snapshot(
        evidence.get("before"), label=f"{label} before"
    )
    _validate_audio_conversion_snapshot(
        evidence.get("after"), label=f"{label} after"
    )
    paths = evidence.get("observed_target_paths")
    byte_change_paths = evidence.get("byte_change_required_paths")
    slots = evidence.get("target_slots")
    operation_request = evidence.get("operation_request")
    if (
        row.get("phase") != "after"
        or not _plain_int(slots, minimum=1)
        or not isinstance(paths, list)
        or not paths
        or len(paths) > slots
        or any(not _nonempty_text(item) for item in paths)
        or not isinstance(byte_change_paths, list)
        or tuple(byte_change_paths) != expected_byte_change_paths
        or not _sha256_text_value(evidence.get("after_digest"))
        or evidence.get("after_digest")
        != evidence.get("after", {}).get("digest")
        or not isinstance(operation_request, Mapping)
        or operation_request != expected_operation_request
        or evidence.get("operation_request_sha256")
        != _canonical_sha256(operation_request)
        or evidence.get("verify_request_sha256")
        != evidence.get("operation_request_sha256")
        or evidence.get("verify_payload_sha256")
        != expected_verify_payload_sha256
    ):
        raise CampaignEvidenceError(f"{label} audio conversion evidence is invalid")
    path_identities = tuple(
        _validated_archive_absolute_path(
            path,
            label=f"{label} observed_target_paths[{index}]",
        )
        for index, path in enumerate(paths)
    )
    if len(path_identities) != len(set(path_identities)):
        raise CampaignEvidenceError(
            f"{label} audio conversion target paths are duplicated"
        )
    before = evidence["before"]
    after = evidence["after"]
    arguments = operation_request.get("arguments")
    request_args = arguments.get("args") if isinstance(arguments, Mapping) else None
    objects = request_args.get("objects") if isinstance(request_args, Mapping) else None
    platforms = request_args.get("platforms") if isinstance(request_args, Mapping) else None
    languages = request_args.get("languages") if isinstance(request_args, Mapping) else None
    io_root = arguments.get("io_root") if isinstance(arguments, Mapping) else None
    if (
        operation_request.get("operation") != "waapi.call"
        or not isinstance(arguments, Mapping)
        or arguments.get("api") != "ak.wwise.core.audio.convert"
        or arguments.get("options") != {}
        or not isinstance(objects, list)
        or not isinstance(platforms, list)
        or not isinstance(languages, list)
        or not all(objects) or not all(platforms) or not all(languages)
        or any(not _nonempty_text(item) for item in (*objects, *platforms, *languages))
        or not _nonempty_text(io_root)
        or before["input_files"] != after["input_files"]
        or before["originals_files"] != after["originals_files"]
        or before["authoring_files"] != after["authoring_files"]
        or before["conversion_xml"] != after["conversion_xml"]
        or before["baseline_artifact_paths"]
        != after["baseline_artifact_paths"]
    ):
        raise CampaignEvidenceError(f"{label} audio conversion request/control proof is invalid")
    _validated_archive_absolute_path(
        io_root,
        label=f"{label} io_root",
    )
    baseline_paths = before["baseline_artifact_paths"]
    try:
        baseline_identities = {
            _validated_archive_absolute_path(
                path,
                label=f"{label} baseline artifact",
            )
            for path in baseline_paths
        }
        for path in baseline_paths:
            archive_relative_from_absolute(path, io_root)
        output_tree_identities = {
            _validated_archive_absolute_path(
                item["path"],
                label=f"{label} output tree path",
            )
            for item in before["output_tree"]
        }
    except ArchiveRelativePathError as exc:
        raise CampaignEvidenceError(
            f"{label} baseline artifact escaped io_root"
        ) from exc
    if (
        len(baseline_paths) > len(before["artifacts"])
        or len(baseline_identities) != len(baseline_paths)
        or not output_tree_identities <= baseline_identities
    ):
        raise CampaignEvidenceError(
            f"{label} pre-preview stable output is not bound to baseline artifacts"
        )
    try:
        allowed_volatile_paths = audio_conversion_volatile_cache_paths(str(io_root))
    except AudioConversionRuntimeError as exc:
        raise CampaignEvidenceError(
            f"{label} audio conversion volatile cache allowlist is invalid"
        ) from exc
    before_volatile = before["volatile_cache_files"]
    after_volatile = after["volatile_cache_files"]
    changed_volatile_paths = [
        current["path"]
        for previous, current in zip(
            before_volatile,
            after_volatile,
            strict=True,
        )
        if previous != current
    ]
    if (
        tuple(item["path"] for item in before_volatile) != allowed_volatile_paths
        or tuple(item["path"] for item in after_volatile) != allowed_volatile_paths
        or evidence.get("volatile_cache_files_before") != before_volatile
        or evidence.get("volatile_cache_files_after") != after_volatile
        or evidence.get("volatile_cache_changed_paths") != changed_volatile_paths
    ):
        raise CampaignEvidenceError(
            f"{label} audio conversion volatile cache proof is invalid"
        )
    expected_slots = {
        (str(object_path), str(platform), str(language))
        for object_path in objects
        for platform in platforms
        for language in languages
    }
    if not set(byte_change_paths).issubset(set(objects)):
        raise CampaignEvidenceError(
            f"{label} byte-change paths escape the target object set"
        )
    before_slots = {
        (item["object_path"], item["platform"], item["language"]): item
        for item in before["artifacts"]
    }
    after_slots = {
        (item["object_path"], item["platform"], item["language"]): item
        for item in after["artifacts"]
    }
    if (
        len(expected_slots) != slots
        or set(before_slots) != set(after_slots)
        or not expected_slots.issubset(after_slots)
    ):
        raise CampaignEvidenceError(f"{label} audio conversion slot matrix is invalid")
    for slot, current in after_slots.items():
        previous = before_slots[slot]
        if slot not in expected_slots:
            if current != previous:
                raise CampaignEvidenceError(f"{label} changed a non-target conversion slot")
            continue
        current_path_identity = _validated_archive_absolute_path(
            current["converted_path"],
            label=f"{label} target converted_path",
        )
        current_file_identity = _validated_archive_absolute_path(
            current["file"].get("path"),
            label=f"{label} target file.path",
        )
        try:
            archive_relative_from_absolute(current["converted_path"], io_root)
        except ArchiveRelativePathError as exc:
            raise CampaignEvidenceError(
                f"{label} target conversion artifact escaped io_root"
            ) from exc
        if (
            (current["object_id"], current["source_id"], current["source_key"])
            != (
                previous["object_id"],
                previous["source_id"],
                previous["source_key"],
            )
            or current["original_path"] != previous["original_path"]
            or current["original_file"] != previous["original_file"]
            or current_path_identity not in path_identities
            or current_file_identity != current_path_identity
            or current["file"].get("present") is not True
            or not _plain_int(current["file"].get("size"), minimum=1)
            or not _sha256_text_value(current["file"].get("sha256"))
            or not _plain_int(current["file"].get("mtime_ns"), minimum=1)
        ):
            raise CampaignEvidenceError(f"{label} target conversion artifact is invalid")
        previous_file = previous["file"]
        if previous_file.get("present") is True:
            if current["file"].get("mtime_ns", 0) <= (
                previous_file.get("mtime_ns") or 0
            ):
                raise CampaignEvidenceError(
                    f"{label} target conversion artifact is stale"
                )
            if (
                slot[0] in byte_change_paths
                and current["file"].get("sha256")
                == previous_file.get("sha256")
            ):
                raise CampaignEvidenceError(
                    f"{label} target conversion bytes were not replaced"
                )
    observed_after_target_paths = {
        _validated_archive_absolute_path(
            item["converted_path"],
            label=f"{label} after target path",
        )
        for slot, item in after_slots.items()
        if slot in expected_slots
    }
    if observed_after_target_paths != set(path_identities):
        raise CampaignEvidenceError(
            f"{label} observed target path evidence is misbound"
        )
    before_target_paths = {
        _validated_archive_absolute_path(
            item["converted_path"],
            label=f"{label} before target path",
        )
        for slot, item in before_slots.items()
        if slot in expected_slots
    }
    after_target_paths = observed_after_target_paths
    before_non_target_paths = {
        _validated_archive_absolute_path(
            item["path"],
            label=f"{label} before non-target path",
        )
        for item in before["output_tree"]
        if _validated_archive_absolute_path(
            item["path"],
            label=f"{label} before output path",
        )
        not in before_target_paths
    }
    if (after_target_paths - before_target_paths) & before_non_target_paths:
        raise CampaignEvidenceError(
            f"{label} target path collides with pre-existing non-target output"
        )
    target_paths = before_target_paths | after_target_paths
    before_controls = {
        _validated_archive_absolute_path(
            item["path"],
            label=f"{label} before control path",
        ): item
        for item in before["output_tree"]
        if _validated_archive_absolute_path(
            item["path"],
            label=f"{label} before output path",
        )
        not in target_paths
    }
    after_controls = {
        _validated_archive_absolute_path(
            item["path"],
            label=f"{label} after control path",
        ): item
        for item in after["output_tree"]
        if _validated_archive_absolute_path(
            item["path"],
            label=f"{label} after output path",
        )
        not in target_paths
    }
    if before_controls != after_controls:
        raise CampaignEvidenceError(f"{label} changed non-target conversion output")


def _validate_audio_file_state(value: Any, *, label: str) -> None:
    row = _closed_oracle_mapping(
        value,
        {"path", "present", "size", "sha256", "mtime_ns"},
        label=label,
    )
    present = row.get("present")
    if (
        not _nonempty_text(row.get("path"))
        or type(present) is not bool
        or not (row.get("size") is None or _plain_int(row.get("size")))
        or not (row.get("sha256") is None or _sha256_text_value(row.get("sha256")))
        or not (row.get("mtime_ns") is None or _plain_int(row.get("mtime_ns"), minimum=1))
        or (
            present
            and (
                not _plain_int(row.get("size"), minimum=1)
                or not _sha256_text_value(row.get("sha256"))
                or not _plain_int(row.get("mtime_ns"), minimum=1)
            )
        )
    ):
        raise CampaignEvidenceError(f"{label} audio file state is malformed")


def _validate_audio_conversion_snapshot(value: Any, *, label: str) -> None:
    row = _closed_oracle_mapping(
        value,
        {
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
        },
        label=label,
    )
    for collection in (
        "artifacts",
        "baseline_artifacts",
        "input_files",
        "originals_files",
        "authoring_files",
        "output_tree",
        "volatile_cache_files",
    ):
        if not isinstance(row.get(collection), list):
            raise CampaignEvidenceError(f"{label} {collection} is not an array")
    for collection in (
        "input_files",
        "originals_files",
        "authoring_files",
        "output_tree",
    ):
        for item in row[collection]:
            _validate_audio_file_state(item, label=f"{label} {collection}")
    for item in row["volatile_cache_files"]:
        volatile = _closed_oracle_mapping(
            item,
            {"path", "present", "size"},
            label=f"{label} volatile cache file",
        )
        present = volatile.get("present")
        size = volatile.get("size")
        if (
            not _nonempty_text(volatile.get("path"))
            or type(present) is not bool
            or (
                present
                and (
                    not _plain_int(size)
                    or int(size) > 16 * 1024 * 1024 * 1024
                )
            )
            or (not present and size is not None)
        ):
            raise CampaignEvidenceError(
                f"{label} volatile cache metadata is malformed or unbounded"
            )
    baseline_paths = row.get("baseline_artifact_paths")
    if (
        not isinstance(baseline_paths, list)
        or not baseline_paths
        or baseline_paths != sorted(set(baseline_paths))
        or any(not _nonempty_text(path) for path in baseline_paths)
    ):
        raise CampaignEvidenceError(
            f"{label} baseline artifact path seal is invalid"
        )
    _validate_audio_file_state(row.get("conversion_xml"), label=f"{label} conversion XML")
    slot_matrices: dict[str, list[tuple[str, str, str]]] = {}
    for collection in ("artifacts", "baseline_artifacts"):
        slots: list[tuple[str, str, str]] = []
        for item in row[collection]:
            artifact = _closed_oracle_mapping(
                item,
                {
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
                },
                label=f"{label} {collection} converted artifact",
            )
            if (
                any(
                    not _nonempty_text(artifact.get(field))
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
                or not _optional_text(artifact.get("codec"))
                or not (
                    artifact.get("sample_rate") is None
                    or _plain_int(artifact.get("sample_rate"), minimum=1)
                )
            ):
                raise CampaignEvidenceError(
                    f"{label} {collection} converted artifact is malformed"
                )
            _validate_audio_file_state(
                artifact.get("original_file"), label=f"{label} {collection} original"
            )
            _validate_audio_file_state(
                artifact.get("file"), label=f"{label} {collection} converted file"
            )
            if collection == "baseline_artifacts" and (
                artifact["file"].get("present") is not True
                or artifact["file"].get("path") != artifact["converted_path"]
                or not _nonempty_text(artifact.get("codec"))
                or not _plain_int(artifact.get("sample_rate"), minimum=1)
            ):
                raise CampaignEvidenceError(
                    f"{label} sealed baseline artifact is incomplete"
                )
            slots.append(
                (
                    str(artifact["object_path"]),
                    str(artifact["platform"]),
                    str(artifact["language"]),
                )
            )
        if len(slots) != len(set(slots)):
            raise CampaignEvidenceError(
                f"{label} {collection} conversion slots are duplicated"
            )
        slot_matrices[collection] = slots
    if set(slot_matrices["artifacts"]) != set(slot_matrices["baseline_artifacts"]):
        raise CampaignEvidenceError(f"{label} baseline conversion slot matrix drifted")
    expected_digest = _canonical_sha256(
        {
            "artifacts": row["artifacts"],
            "baseline_artifacts": row["baseline_artifacts"],
            "inputs": row["input_files"],
            "originals": row["originals_files"],
            "authoring_files": row["authoring_files"],
            "conversion_xml": row["conversion_xml"],
            "output_tree": row["output_tree"],
            "baseline_artifact_paths": row["baseline_artifact_paths"],
        }
    )
    if row.get("digest") != expected_digest:
        raise CampaignEvidenceError(f"{label} conversion snapshot digest is invalid")


def _validate_heavy_v3_media_pool_oracle(
    value: Any,
    *,
    scenario_id: str,
    task_root: Path,
    expected_final_response_sha256: str,
    final_response: str,
    expected_request: Mapping[str, Any],
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"passed", "failures", "evidence"},
        label=label,
    )
    _require_passing_oracle(row, label=label)
    evidence = _closed_oracle_mapping(
        row.get("evidence"),
        {
            "sealed_oracle",
            "source_fingerprint_after",
            "staged_assets_after",
            "model_get_fields",
            "model_media_result",
            "model_reference_result",
            "reference_baseline",
            "project_digest_before",
            "project_digest_after",
            "supporting_association_read",
            "custom_baseline_ids",
            "custom_created_ids",
            "final_response_sha256",
            "cleanup_evidence_path",
        },
        label=f"{label} evidence",
    )
    oracle = _validate_media_pool_sealed_oracle(
        evidence.get("sealed_oracle"),
        scenario_id=scenario_id,
        label=f"{label} sealed oracle",
    )
    supporting = evidence.get("supporting_association_read")
    cleanup_path = task_root.parent / "media-pool-cleanup.json"
    _validate_media_tree_fingerprint(
        evidence.get("source_fingerprint_after"),
        label=f"{label} source after",
    )
    staged_assets = evidence.get("staged_assets_after")
    if (
        not isinstance(evidence.get("model_get_fields"), Mapping)
        or not isinstance(evidence.get("model_media_result"), Mapping)
        or type(supporting) is not bool
        or (supporting != (evidence.get("reference_baseline") is not None))
        or (supporting != (evidence.get("model_reference_result") is not None))
        or not _sha256_text_value(evidence.get("project_digest_before"))
        or evidence.get("project_digest_before")
        != evidence.get("project_digest_after")
        or evidence.get("final_response_sha256")
        != expected_final_response_sha256
        or evidence.get("cleanup_evidence_path") != str(cleanup_path)
        or evidence.get("source_fingerprint_after")
        != oracle.get("source_fingerprint")
        or not isinstance(staged_assets, list)
        or not isinstance(evidence.get("custom_baseline_ids"), list)
        or not isinstance(evidence.get("custom_created_ids"), Mapping)
        or any(
            not _nonempty_text(item)
            for item in evidence.get("custom_baseline_ids", [])
        )
        or any(
            not _nonempty_text(key) or not _nonempty_text(item)
            for key, item in evidence.get("custom_created_ids", {}).items()
        )
    ):
        raise CampaignEvidenceError(f"{label} Media Pool evidence is invalid")
    sealed_rows = {
        item["key"]: item
        for item in oracle.get("rows", [])
        if isinstance(item, Mapping) and _nonempty_text(item.get("key"))
    }
    observed_staged: dict[str, Mapping[str, Any]] = {}
    for item in staged_assets:
        state = _closed_oracle_mapping(
            item,
            {"key", "path", "size", "sha256"},
            label=f"{label} staged asset",
        )
        if (
            not _nonempty_text(state.get("key"))
            or not _nonempty_text(state.get("path"))
            or not _plain_int(state.get("size"), minimum=1)
            or not _sha256_text_value(state.get("sha256"))
            or state.get("key") in observed_staged
        ):
            raise CampaignEvidenceError(f"{label} staged asset is malformed")
        observed_staged[str(state["key"])] = state
    if set(observed_staged) != set(sealed_rows) or any(
        observed_staged[key]["path"] != sealed_rows[key]["host_path"]
        for key in observed_staged
    ):
        raise CampaignEvidenceError(f"{label} staged assets differ from sealed rows")
    expected_keys = oracle.get("expected_keys")
    sealed_request = oracle.get("request")
    if (
        not expected_keys
        or not isinstance(sealed_request, Mapping)
        or sealed_request.get("args") != expected_request.get("args")
        or sealed_request.get("options") != expected_request.get("options")
        or sealed_request.get("post_filter")
        != expected_request.get("post_filter")
    ):
        raise CampaignEvidenceError(f"{label} Media Pool oracle has no expected keys")
    binding = sealed_request.get("binding")
    available_fields = binding.get("available_fields") if isinstance(binding, Mapping) else None
    model_get_fields = evidence.get("model_get_fields")
    if (
        not isinstance(model_get_fields, Mapping)
        or model_get_fields.get("return") != available_fields
    ):
        raise CampaignEvidenceError(f"{label} getFields differs from sealed inventory")
    requested_fields = sealed_request.get("options", {}).get("return")
    model_result = evidence.get("model_media_result")
    raw_rows = model_result.get("return") if isinstance(model_result, Mapping) else None
    expected_by_id = {
        item["file_id"]: item
        for item in oracle.get("rows", [])
        if item.get("key") in expected_keys
    }
    actual_by_id: dict[str, Mapping[str, Any]] = {}
    if not isinstance(requested_fields, list) or not isinstance(raw_rows, list):
        raise CampaignEvidenceError(f"{label} Media Pool result is malformed")
    for item in raw_rows:
        if not isinstance(item, Mapping) or not _nonempty_text(item.get("FileId")):
            raise CampaignEvidenceError(f"{label} Media Pool result row is malformed")
        file_id = str(item["FileId"])
        if file_id in actual_by_id:
            raise CampaignEvidenceError(f"{label} Media Pool result duplicates FileId")
        actual_by_id[file_id] = item
    if set(actual_by_id) != set(expected_by_id):
        raise CampaignEvidenceError(f"{label} Media Pool FileId set is invalid")
    for file_id, item in actual_by_id.items():
        expected_row = expected_by_id[file_id]
        if set(item) != set(requested_fields) or any(
            not _same_media_value_v3(
                item.get(field), expected_row.get("values", {}).get(field)
            )
            for field in requested_fields
        ):
            raise CampaignEvidenceError(f"{label} Media Pool return fields/values drifted")
    if supporting:
        _validate_compact_media_reference_archive(
            evidence.get("model_reference_result"),
            reference_baseline=evidence.get("reference_baseline"),
            oracle=oracle,
            label=f"{label} Media Pool association proof",
        )
    _validate_media_final_response(
        final_response,
        oracle=oracle,
        label=label,
    )
    cleanup = load_strict_regular_json(cleanup_path)
    cleanup_row = _closed_oracle_mapping(
        cleanup,
        {
            "contract",
            "scenario_id",
            "baseline_user_database_ids",
            "created_database_ids",
            "final_user_database_ids",
            "global_user_state_before",
            "global_user_state_after",
            "wwise_process_stopped",
            "verification",
            "passed",
        },
        label=f"{label} cleanup",
    )
    if (
        cleanup_row.get("contract")
        != "waapi-skill.media-pool-cleanup-evidence/v1"
        or cleanup_row.get("scenario_id") != scenario_id
        or cleanup_row.get("passed") is not True
        or cleanup_row.get("wwise_process_stopped") is not True
        or cleanup_row.get("baseline_user_database_ids")
        != evidence.get("custom_baseline_ids")
        or cleanup_row.get("created_database_ids")
        != evidence.get("custom_created_ids")
        or cleanup_row.get("final_user_database_ids")
        != evidence.get("custom_baseline_ids")
    ):
        raise CampaignEvidenceError(f"{label} cleanup identities are invalid")
    verification = _closed_oracle_mapping(
        cleanup_row.get("verification"),
        {"ok", "code", "details"},
        label=f"{label} cleanup verification",
    )
    if (
        verification.get("ok") is not True
        or not _nonempty_text(verification.get("code"))
        or not isinstance(verification.get("details"), Mapping)
    ):
        raise CampaignEvidenceError(f"{label} cleanup verification failed")
    if evidence.get("custom_created_ids"):
        _validate_media_tree_fingerprint(
            cleanup_row.get("global_user_state_before"),
            label=f"{label} global before",
        )
        _validate_media_tree_fingerprint(
            cleanup_row.get("global_user_state_after"),
            label=f"{label} global after",
        )
        if cleanup_row.get("global_user_state_before") != cleanup_row.get(
            "global_user_state_after"
        ):
            raise CampaignEvidenceError(f"{label} changed global user state")
    elif (
        cleanup_row.get("global_user_state_before") is not None
        or cleanup_row.get("global_user_state_after") is not None
    ):
        raise CampaignEvidenceError(f"{label} unexpected global state proof")


def _validate_compact_media_reference_archive(
    value: Any,
    *,
    reference_baseline: Any,
    oracle: Mapping[str, Any],
    label: str,
) -> None:
    """Join compact model evidence to the sealed paths and trusted full scan."""

    result = _closed_oracle_mapping(
        value,
        {
            "contract",
            "candidates",
            "scanned_audio_source_count",
            "scan_limit",
            "scan_complete",
        },
        label=label,
    )
    baseline = _closed_oracle_mapping(
        reference_baseline,
        {"return"},
        label=f"{label} trusted baseline",
    )
    baseline_rows = baseline.get("return")
    scanned_count = result.get("scanned_audio_source_count")
    if (
        result.get("contract") != REFERENCE_MATCH_RESULT_CONTRACT
        or result.get("scan_limit") != REFERENCE_MATCH_SCAN_LIMIT
        or result.get("scan_complete") is not True
        or not isinstance(scanned_count, int)
        or isinstance(scanned_count, bool)
        or scanned_count < 0
        or scanned_count >= REFERENCE_MATCH_SCAN_LIMIT
        or not isinstance(baseline_rows, list)
        or scanned_count != len(baseline_rows)
    ):
        raise CampaignEvidenceError(f"{label} scan contract is invalid")

    expected_keys = oracle.get("expected_keys")
    oracle_rows = oracle.get("rows")
    answer = oracle.get("semantic_answer")
    if (
        not isinstance(expected_keys, list)
        or not isinstance(oracle_rows, list)
        or not isinstance(answer, Mapping)
    ):
        raise CampaignEvidenceError(f"{label} sealed oracle is malformed")
    row_by_key = {
        row.get("key"): row
        for row in oracle_rows
        if isinstance(row, Mapping) and _nonempty_text(row.get("key"))
    }
    expected_rows: list[Mapping[str, Any]] = []
    host_paths_by_key: dict[str, str] = {}
    path_to_key: dict[str, str] = {}
    path_identities: set[ArchiveAbsolutePath] = set()
    for key in expected_keys:
        row = row_by_key.get(key)
        if not isinstance(key, str) or not isinstance(row, Mapping):
            raise CampaignEvidenceError(f"{label} sealed candidate is missing")
        path = row.get("path")
        host_path = row.get("host_path")
        if not _nonempty_text(path) or not _nonempty_text(host_path):
            raise CampaignEvidenceError(f"{label} sealed candidate path is invalid")
        try:
            path_identity = parse_archive_absolute_path(str(path))
            host_identity = parse_archive_absolute_path(str(host_path))
            host_identity.name
        except ArchiveRelativePathError as exc:
            raise CampaignEvidenceError(
                f"{label} sealed candidate path is invalid"
            ) from exc
        if (
            path_identity in path_identities
            or any(
                archive_absolute_names_equal(str(host_path), existing)
                for existing in host_paths_by_key.values()
            )
        ):
            raise CampaignEvidenceError(
                f"{label} sealed candidate paths are not uniquely matchable"
            )
        host_paths_by_key[key] = str(host_path)
        path_to_key[str(path)] = key
        path_identities.add(path_identity)
        expected_rows.append(row)

    referenced = answer.get("referenced_keys")
    unreferenced = answer.get("unreferenced_keys")
    if (
        not isinstance(referenced, list)
        or not isinstance(unreferenced, list)
        or set(referenced) & set(unreferenced)
        or set(referenced) | set(unreferenced) != set(expected_keys)
    ):
        raise CampaignEvidenceError(
            f"{label} sealed reference classification is invalid"
        )
    referenced_keys = set(referenced)

    trusted_by_key: dict[str, list[tuple[str, str]]] = {
        key: [] for key in expected_keys
    }
    trusted_ids: set[str] = set()
    for raw_row in baseline_rows:
        if not isinstance(raw_row, Mapping):
            raise CampaignEvidenceError(f"{label} trusted baseline row is malformed")
        original = raw_row.get("originalFilePath")
        if not isinstance(original, str) or not original:
            continue
        try:
            original_identity = parse_archive_absolute_path(original)
            original_identity.name
            matching_keys = [
                key
                for key, host_path in host_paths_by_key.items()
                if archive_absolute_names_equal(original, host_path)
            ]
        except ArchiveRelativePathError as exc:
            raise CampaignEvidenceError(
                f"{label} trusted baseline path is invalid"
            ) from exc
        if len(matching_keys) > 1:
            raise CampaignEvidenceError(
                f"{label} trusted baseline path is ambiguous"
            )
        if not matching_keys:
            continue
        key = matching_keys[0]
        source_id = raw_row.get("id")
        object_path = raw_row.get("path")
        if (
            not _nonempty_text(source_id)
            or _OBJECT_ANSWER_GUID_RE.fullmatch(str(source_id)) is None
            or not _nonempty_text(object_path)
            or str(source_id).upper() in trusted_ids
        ):
            raise CampaignEvidenceError(
                f"{label} trusted candidate identity is malformed"
            )
        trusted_ids.add(str(source_id).upper())
        trusted_by_key[key].append((str(source_id), str(object_path)))

    candidates = result.get("candidates")
    expected_paths = tuple(sorted(path_to_key))
    if not isinstance(candidates, list) or len(candidates) != len(expected_paths):
        raise CampaignEvidenceError(f"{label} candidate set is invalid")
    observed_paths = tuple(
        candidate.get("originalFilePath")
        if isinstance(candidate, Mapping)
        else None
        for candidate in candidates
    )
    if observed_paths != expected_paths:
        raise CampaignEvidenceError(
            f"{label} candidates differ from sorted sealed paths"
        )

    observed_ids: set[str] = set()
    returned_reference_count = 0
    for candidate in candidates:
        row = _closed_oracle_mapping(
            candidate,
            {
                "originalFilePath",
                "classification",
                "reference_count",
                "references",
                "references_truncated",
            },
            label=f"{label} candidate",
        )
        original_path = str(row["originalFilePath"])
        key = path_to_key[original_path]
        trusted = tuple(sorted(trusted_by_key[key]))
        expected_classification = (
            "referenced" if key in referenced_keys else "unreferenced"
        )
        references = row.get("references")
        reference_count = row.get("reference_count")
        if (
            row.get("classification") != expected_classification
            or bool(trusted) != (key in referenced_keys)
            or not isinstance(references, list)
            or not isinstance(reference_count, int)
            or isinstance(reference_count, bool)
            or reference_count != len(references)
            or reference_count != len(trusted)
            or row.get("references_truncated") is not False
        ):
            raise CampaignEvidenceError(
                f"{label} candidate classification/count is invalid"
            )
        observed_references: list[tuple[str, str]] = []
        for reference in references:
            identity = _closed_oracle_mapping(
                reference,
                {"id", "path"},
                label=f"{label} candidate reference",
            )
            source_id = identity.get("id")
            object_path = identity.get("path")
            if (
                not _nonempty_text(source_id)
                or _OBJECT_ANSWER_GUID_RE.fullmatch(str(source_id)) is None
                or not _nonempty_text(object_path)
                or str(source_id).upper() in observed_ids
            ):
                raise CampaignEvidenceError(
                    f"{label} candidate reference identity is malformed"
                )
            observed_ids.add(str(source_id).upper())
            observed_references.append((str(source_id), str(object_path)))
        if tuple(sorted(observed_references)) != trusted:
            raise CampaignEvidenceError(
                f"{label} candidate references differ from trusted baseline"
            )
        returned_reference_count += reference_count
    if returned_reference_count > scanned_count:
        raise CampaignEvidenceError(
            f"{label} returned references exceed the trusted full scan"
        )


def _same_media_value_v3(actual: Any, expected: Any) -> bool:
    """Match the runtime Media Pool numeric tolerance exactly."""

    if isinstance(expected, float):
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isfinite(float(actual))
            and abs(float(actual) - expected) <= 1e-6
        )
    return actual == expected


def _validate_media_final_response(
    value: str,
    *,
    oracle: Mapping[str, Any],
    label: str,
) -> None:
    folded = value.casefold()
    rows = {item["key"]: item for item in oracle["rows"]}
    answer = oracle["semantic_answer"]
    positions: dict[str, int] = {}
    for key in oracle["expected_keys"]:
        filenames = _serialized_media_response_filenames(
            oracle,
            rows[key],
            label=label,
        )
        filename = filenames[-1]
        position = _first_serialized_media_filename_position(folded, filenames)
        if position < 0:
            raise CampaignEvidenceError(f"{label} final response omits {filename}")
        positions[key] = position
    if (
        media_answer_requires_order(str(oracle.get("scenario_id")))
        and tuple(sorted(positions, key=positions.__getitem__))
        != tuple(answer["ordered_keys"])
    ):
        raise CampaignEvidenceError(f"{label} final response order is invalid")
    if oracle.get("scenario_id") == MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID:
        report_rows: dict[str, MediaReportRowExpectation] = {}
        for key, row in rows.items():
            db = row.get("db")
            database = db.get("name") if isinstance(db, Mapping) else None
            path = row.get("path")
            if not _nonempty_text(database) or not _nonempty_text(path):
                raise CampaignEvidenceError(
                    f"{label} Media Pool row {key} lacks database/path identity"
                )
            report_rows[key] = MediaReportRowExpectation(
                key=key,
                filenames=_serialized_media_response_filenames(
                    oracle,
                    row,
                    label=label,
                ),
                database=str(database),
                path=str(path),
            )
        grouped_failures = media_grouped_report_failures(
            value,
            expected_groups=answer["expected_groups"],
            rows=report_rows,
            excluded_keys=answer["excluded_keys"],
        )
        if grouped_failures:
            raise CampaignEvidenceError(f"{label} {grouped_failures[0]}")
    else:
        for key in answer["excluded_keys"]:
            filenames = _serialized_media_response_filenames(
                oracle,
                rows[key],
                label=label,
            )
            filename = filenames[-1]
            if _first_serialized_media_filename_position(folded, filenames) >= 0:
                raise CampaignEvidenceError(
                    f"{label} final response includes excluded {filename}"
                )
        for group, keys in answer["expected_groups"].items():
            if str(group).casefold() not in folded:
                raise CampaignEvidenceError(
                    f"{label} final response omits group {group}"
                )
            for key in keys:
                filenames = _serialized_media_response_filenames(
                    oracle,
                    rows[key],
                    label=label,
                )
                filename = filenames[-1]
                if _first_serialized_media_filename_position(
                    folded,
                    filenames,
                ) < 0:
                    raise CampaignEvidenceError(
                        f"{label} group {group} omits {filename}"
                    )
    for key in answer["referenced_keys"]:
        filenames = _serialized_media_response_filenames(
            oracle,
            rows[key],
            label=label,
        )
        filename = filenames[-1]
        if not _media_near_classification(folded, filenames, referenced=True):
            raise CampaignEvidenceError(f"{label} does not classify {filename} as referenced")
    for key in answer["unreferenced_keys"]:
        filenames = _serialized_media_response_filenames(
            oracle,
            rows[key],
            label=label,
        )
        filename = filenames[-1]
        if not _media_near_classification(folded, filenames, referenced=False):
            raise CampaignEvidenceError(f"{label} does not classify {filename} as unreferenced")


def _serialized_media_response_filenames(
    oracle: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, ...]:
    request = oracle.get("request")
    binding = request.get("binding") if isinstance(request, Mapping) else None
    by_concept = (
        binding.get("by_concept") if isinstance(binding, Mapping) else None
    )
    filename_field = (
        by_concept.get("name") if isinstance(by_concept, Mapping) else None
    )
    values = row.get("values")
    live_filename = (
        values.get(filename_field)
        if isinstance(values, Mapping) and isinstance(filename_field, str)
        else None
    )
    host_path = row.get("host_path")
    if (
        not isinstance(live_filename, str)
        or not live_filename
        or not isinstance(host_path, str)
        or not host_path
    ):
        raise CampaignEvidenceError(
            f"{label} Media Pool row lacks bound Filename/host_path identity"
        )
    try:
        full_filename = parse_archive_absolute_path(host_path).name
    except ArchiveRelativePathError as exc:
        raise CampaignEvidenceError(
            f"{label} Media Pool row host_path has no basename"
        ) from exc
    return tuple(
        dict.fromkeys((live_filename.casefold(), full_filename.casefold()))
    )


def _first_serialized_media_filename_position(
    text: str,
    filenames: Sequence[str],
) -> int:
    positions = tuple(
        position
        for filename in filenames
        if (position := text.find(filename)) >= 0
    )
    return min(positions, default=-1)


def _media_near_classification(
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


def _validate_media_tree_fingerprint(value: Any, *, label: str) -> None:
    row = _closed_oracle_mapping(
        value,
        {"root", "exists", "sha256", "file_count", "byte_count"},
        label=label,
    )
    if (
        not _nonempty_text(row.get("root"))
        or type(row.get("exists")) is not bool
        or not _sha256_text_value(row.get("sha256"))
        or not _plain_int(row.get("file_count"))
        or not _plain_int(row.get("byte_count"))
    ):
        raise CampaignEvidenceError(f"{label} fingerprint is malformed")


def _validate_media_pool_sealed_oracle(
    value: Any,
    *,
    scenario_id: str,
    label: str,
) -> Mapping[str, Any]:
    row = _closed_oracle_mapping(
        value,
        {
            "scenario_id",
            "request",
            "rows",
            "candidate_keys",
            "expected_keys",
            "semantic_answer",
            "source_fingerprint",
            "staged_fingerprint",
        },
        label=label,
    )
    if row.get("scenario_id") != scenario_id:
        raise CampaignEvidenceError(f"{label} scenario identity is invalid")
    request = _closed_oracle_mapping(
        row.get("request"),
        {"scenario_id", "args", "options", "binding", "post_filter"},
        label=f"{label} request",
    )
    binding = _closed_oracle_mapping(
        request.get("binding"),
        {"available_fields", "by_concept"},
        label=f"{label} binding",
    )
    if (
        request.get("scenario_id") != scenario_id
        or not isinstance(request.get("args"), Mapping)
        or not isinstance(request.get("options"), Mapping)
        or not isinstance(binding.get("available_fields"), list)
        or not isinstance(binding.get("by_concept"), Mapping)
        or any(not _nonempty_text(item) for item in binding.get("available_fields", []))
        or any(
            not _nonempty_text(key) or not _nonempty_text(item)
            for key, item in binding.get("by_concept", {}).items()
        )
    ):
        raise CampaignEvidenceError(f"{label} request is malformed")
    post_filter = request.get("post_filter")
    if post_filter is not None:
        post_filter = _closed_oracle_mapping(
            post_filter,
            {"field", "operator", "value", "limit"},
            label=f"{label} post filter",
        )
        requested_fields = request.get("options", {}).get("return")
        request_args = request.get("args")
        server_filters = (
            request_args.get("filters")
            if isinstance(request_args, Mapping)
            else None
        )
        matching_candidate_filters = [
            item
            for item in server_filters or []
            if isinstance(item, Mapping)
            and item.get("type") == "field"
            and item.get("field") == post_filter.get("field")
            and item.get("operator") == "contains"
            and item.get("value") == post_filter.get("value")
        ]
        if (
            post_filter.get("field") != "Filename"
            or post_filter.get("operator") != "containsCaseSensitive"
            or not _nonempty_text(post_filter.get("value"))
            or not _plain_int(post_filter.get("limit"), minimum=1)
            or not isinstance(requested_fields, list)
            or post_filter.get("field") not in requested_fields
            or not isinstance(server_filters, list)
            or len(matching_candidate_filters) != 1
            or request_args.get("maxResults") != 200
            or int(post_filter.get("limit") or 0) > 200
        ):
            raise CampaignEvidenceError(f"{label} post filter is malformed")
    rows = row.get("rows")
    candidate_keys = row.get("candidate_keys")
    expected_keys = row.get("expected_keys")
    if (
        not isinstance(rows, list)
        or not isinstance(candidate_keys, list)
        or len(candidate_keys) != len(set(candidate_keys))
        or any(not _nonempty_text(item) for item in candidate_keys)
        or not isinstance(expected_keys, list)
        or len(expected_keys) != len(set(expected_keys))
        or any(not _nonempty_text(item) for item in expected_keys)
    ):
        raise CampaignEvidenceError(f"{label} rows/keys are malformed")
    row_keys: list[str] = []
    for item in rows:
        media = _closed_oracle_mapping(
            item,
            {"key", "path", "host_path", "file_id", "db", "values"},
            label=f"{label} row",
        )
        if (
            any(not _nonempty_text(media.get(field)) for field in ("key", "path", "host_path", "file_id"))
            or not isinstance(media.get("db"), Mapping)
            or not isinstance(media.get("values"), Mapping)
            or any(
                not _nonempty_text(key) or not _nonempty_text(item)
                for key, item in media.get("db", {}).items()
            )
            or not _json_archive_value(media.get("values"))
        ):
            raise CampaignEvidenceError(f"{label} row is malformed")
        row_keys.append(str(media["key"]))
    if (
        len(row_keys) != len(set(row_keys))
        or not set(candidate_keys).issubset(row_keys)
        or not set(expected_keys).issubset(candidate_keys)
        or (post_filter is None and candidate_keys != expected_keys)
    ):
        raise CampaignEvidenceError(f"{label} row identities are invalid")
    answer = _closed_oracle_mapping(
        row.get("semantic_answer"),
        {
            "ordered_keys",
            "expected_groups",
            "referenced_keys",
            "unreferenced_keys",
            "excluded_keys",
            "max_results",
        },
        label=f"{label} semantic answer",
    )
    for field in ("ordered_keys", "referenced_keys", "unreferenced_keys", "excluded_keys"):
        if not isinstance(answer.get(field), list) or any(
            not _nonempty_text(item) for item in answer.get(field, [])
        ):
            raise CampaignEvidenceError(f"{label} semantic answer {field} is invalid")
    ordered_keys = answer.get("ordered_keys", [])
    excluded_keys = answer.get("excluded_keys", [])
    referenced_keys = answer.get("referenced_keys", [])
    unreferenced_keys = answer.get("unreferenced_keys", [])
    groups = answer.get("expected_groups")
    grouped_keys = [
        item
        for items in groups.values()
        for item in items
    ] if isinstance(groups, Mapping) else []
    max_results = answer.get("max_results")
    if (
        len(ordered_keys) != len(set(ordered_keys))
        or set(ordered_keys) != set(expected_keys)
        or len(excluded_keys) != len(set(excluded_keys))
        or set(excluded_keys) != set(row_keys) - set(expected_keys)
        or len(referenced_keys) != len(set(referenced_keys))
        or len(unreferenced_keys) != len(set(unreferenced_keys))
        or set(referenced_keys) & set(unreferenced_keys)
        or not (set(referenced_keys) | set(unreferenced_keys)).issubset(
            expected_keys
        )
        or (
            (referenced_keys or unreferenced_keys)
            and set(referenced_keys) | set(unreferenced_keys)
            != set(expected_keys)
        )
        or not isinstance(groups, Mapping)
        or any(
            not _nonempty_text(key)
            or not isinstance(items, list)
            or any(not _nonempty_text(item) for item in items)
            or len(items) != len(set(items))
            for key, items in (groups or {}).items()
        )
        or len(grouped_keys) != len(set(grouped_keys))
        or not set(grouped_keys).issubset(expected_keys)
        or (grouped_keys and set(grouped_keys) != set(expected_keys))
        or not _plain_int(max_results, minimum=1)
        or max_results
        != (
            post_filter.get("limit")
            if isinstance(post_filter, Mapping)
            else request.get("args", {}).get("maxResults")
        )
        or len(expected_keys) > int(max_results or 0)
    ):
        raise CampaignEvidenceError(f"{label} semantic answer is malformed")
    _validate_media_tree_fingerprint(row.get("source_fingerprint"), label=f"{label} source")
    _validate_media_tree_fingerprint(row.get("staged_fingerprint"), label=f"{label} staged")
    return row


def _validate_soundbank_tree_entry(value: Any, *, label: str) -> None:
    row = _closed_oracle_mapping(
        value,
        {"relative_path", "size", "sha256", "mtime_ns"},
        label=label,
    )
    relative = row.get("relative_path")
    try:
        relative_identity = parse_archive_relative_path(relative)
    except ArchiveRelativePathError as exc:
        raise CampaignEvidenceError(f"{label} tree entry is malformed") from exc
    if (
        not _nonempty_text(relative)
        or relative_identity.source_flavor != "posix"
        or relative_identity.canonical != relative
        or not _plain_int(row.get("size"))
        or not _sha256_text_value(row.get("sha256"))
        or not _plain_int(row.get("mtime_ns"), minimum=1)
    ):
        raise CampaignEvidenceError(f"{label} tree entry is malformed")


def _validate_soundbank_snapshot(
    value: Any,
    *,
    scenario_id: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"scenario_id", "objects", "banks", "project_files", "input_files", "output_files"},
        label=label,
    )
    if row.get("scenario_id") != scenario_id:
        raise CampaignEvidenceError(f"{label} scenario identity is invalid")
    for collection in ("objects", "banks", "project_files", "input_files", "output_files"):
        if not isinstance(row.get(collection), list):
            raise CampaignEvidenceError(f"{label} {collection} is not an array")
    object_keys: list[str] = []
    for item in row["objects"]:
        object_row = _closed_oracle_mapping(
            item,
            {"key", "id", "path", "object_type"},
            label=f"{label} object",
        )
        if (
            not _nonempty_text(object_row.get("key"))
            or not _nonempty_text(object_row.get("path"))
            or not _optional_text(object_row.get("id"))
            or not _optional_text(object_row.get("object_type"))
        ):
            raise CampaignEvidenceError(f"{label} object is malformed")
        object_keys.append(str(object_row["key"]))
    if len(object_keys) != len(set(object_keys)):
        raise CampaignEvidenceError(f"{label} object keys are duplicated")
    bank_names: list[str] = []
    for item in row["banks"]:
        bank = _closed_oracle_mapping(
            item,
            {"name", "id", "inclusions"},
            label=f"{label} bank",
        )
        inclusions = bank.get("inclusions")
        if (
            not _nonempty_text(bank.get("name"))
            or not _optional_text(bank.get("id"))
            or not isinstance(inclusions, list)
            or any(
                not isinstance(inclusion, list)
                or len(inclusion) != 2
                or not _nonempty_text(inclusion[0])
                or not isinstance(inclusion[1], list)
                or any(not _nonempty_text(item) for item in inclusion[1])
                for inclusion in inclusions
            )
        ):
            raise CampaignEvidenceError(f"{label} bank is malformed")
        bank_names.append(str(bank["name"]))
    if len(bank_names) != len(set(bank_names)):
        raise CampaignEvidenceError(f"{label} bank names are duplicated")
    for item in row["project_files"]:
        _validate_soundbank_tree_entry(item, label=f"{label} project file")
    for item in row["output_files"]:
        _validate_soundbank_tree_entry(item, label=f"{label} output file")
    for item in row["input_files"]:
        _validate_file_proof(
            item,
            label=f"{label} input file",
            relative_optional=False,
            has_mtime=True,
        )


def _validate_heavy_v3_soundbank_oracle(
    value: Any,
    *,
    api: str,
    scenario_id: str,
    expected_phase: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"scenario_id", "phase", "passed", "failures", "before", "after"},
        label=label,
    )
    _require_passing_oracle(row, label=label)
    if row.get("scenario_id") != scenario_id or row.get("phase") != expected_phase:
        raise CampaignEvidenceError(f"{label} SoundBank identity/phase is invalid")
    _validate_soundbank_snapshot(row.get("before"), scenario_id=scenario_id, label=f"{label} before")
    _validate_soundbank_snapshot(row.get("after"), scenario_id=scenario_id, label=f"{label} after")
    if expected_phase == "zero_dispatch" and row.get("before") != row.get("after"):
        raise CampaignEvidenceError(f"{label} zero-dispatch SoundBank state changed")
    if expected_phase != "zero_dispatch":
        before = row["before"]
        after = row["after"]
        if before["input_files"] != after["input_files"] or before == after:
            raise CampaignEvidenceError(f"{label} SoundBank immutable input/delta proof is invalid")
        if api in {
            "ak.wwise.core.soundbank.generate",
            "ak.wwise.core.soundbank.convertExternalSources",
            "ak.wwise.core.soundbank.generated",
        }:
            if (
                before["project_files"] != after["project_files"]
                or before["output_files"] == after["output_files"]
            ):
                raise CampaignEvidenceError(f"{label} SoundBank output delta is invalid")
        elif api == "ak.wwise.core.soundbank.processDefinitionFiles":
            if (
                before["banks"] == after["banks"]
                and before["project_files"] == after["project_files"]
            ):
                raise CampaignEvidenceError(f"{label} definition processing delta is absent")
        elif api == "ak.wwise.core.soundbank.setInclusions":
            if (
                before["banks"] == after["banks"]
                and before["project_files"] == after["project_files"]
            ) or before["output_files"] != after["output_files"]:
                raise CampaignEvidenceError(f"{label} inclusion delta/control proof is invalid")


def _validate_heavy_v3_soundbank_topic_oracle(
    value: Any,
    *,
    scenario_id: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(value, {"topic", "artifacts"}, label=label)
    topic = _closed_oracle_mapping(
        row.get("topic"),
        {"scenario_id", "passed", "failures", "observed_keys", "expected_keys"},
        label=f"{label} topic",
    )
    _require_passing_oracle(topic, label=f"{label} topic")
    observed = topic.get("observed_keys")
    expected = topic.get("expected_keys")
    if (
        topic.get("scenario_id") != scenario_id
        or not isinstance(observed, list)
        or not isinstance(expected, list)
        or not expected
        or any(
            not isinstance(key, list)
            or len(key) != 3
            or not _nonempty_text(key[0])
            or not _nonempty_text(key[1])
            or not _optional_text(key[2])
            for key in [*expected, *observed]
        )
    ):
        raise CampaignEvidenceError(f"{label} topic identities are invalid")
    if Counter(tuple(key) for key in observed) != Counter(
        tuple(key) for key in expected
    ):
        raise CampaignEvidenceError(f"{label} topic identities are invalid")
    _validate_heavy_v3_soundbank_oracle(
        row.get("artifacts"),
        api="ak.wwise.core.soundbank.generated",
        scenario_id=scenario_id,
        expected_phase="topic_artifacts",
        label=f"{label} artifacts",
    )


def _validate_heavy_v3_topic_publisher_process(
    value: Any,
    *,
    api: str,
    publisher_count: int,
    ack_proof: Any,
    prompt_evidence: HeavyV3PromptEvidence,
) -> None:
    """Require the passing publisher to be one closed, reaped spawn child."""

    diagnostics = _closed_oracle_mapping(
        value,
        {
            "contract",
            "diagnostic_only",
            "abort_requested",
            "execution_mode",
            "ack",
            "publisher_started_at_monotonic_ns",
            "publisher_finished_at_monotonic_ns",
            "publisher_call_evidence",
            "result_count",
            "direct_call_count",
            "client_opened",
            "client_closed",
            "child_process",
            "error",
        },
        label="topic publisher process",
    )
    proof = _closed_oracle_mapping(
        ack_proof,
        {
            "contract",
            "business_oracle_plan_sha256",
            "requirement",
            "ack_path",
            "ack_file_sha256",
            "ack_payload",
            "ack_observed_at_monotonic_ns",
            "publisher_started_at_monotonic_ns",
            "publisher_call_started_at_monotonic_ns",
            "ack_before_publish",
        },
        label="topic publisher ACK join",
    )
    ack_payload = proof.get("ack_payload")
    if not isinstance(ack_payload, Mapping):
        raise CampaignEvidenceError("topic publisher process lacks its ACK payload join")
    ack = _closed_oracle_mapping(
        diagnostics.get("ack"),
        {
            "contract",
            "step_name",
            "topic",
            "path",
            "nonce_sha256",
            "observed",
            "file_sha256",
            "observed_at_monotonic_ns",
            "payload",
        },
        label="topic publisher diagnostic ACK",
    )
    child = _closed_oracle_mapping(
        diagnostics.get("child_process"),
        {
            "start_method",
            "coordinator_process_id",
            "pid",
            "parent_pid",
            "exit_code",
            "reaped",
            "terminate_requested",
            "kill_requested",
            "canonical_result_received",
            "child_started_at_monotonic_ns",
            "child_finished_at_monotonic_ns",
            "cleanup_error",
        },
        label="topic publisher child process",
    )
    started = diagnostics.get("publisher_started_at_monotonic_ns")
    finished = diagnostics.get("publisher_finished_at_monotonic_ns")
    call_rows = diagnostics.get("publisher_call_evidence")
    call_times = proof.get("publisher_call_started_at_monotonic_ns")
    expected_requests = (
        prompt_evidence.typed_sections.live_binding.get("topic", {}).get(
            "publisher_requests"
        )
        if isinstance(prompt_evidence.typed_sections, SoundBankBusinessPlanSections)
        else None
    )
    if (
        diagnostics.get("contract")
        != HEAVY_V3_TOPIC_PUBLISHER_DIAGNOSTICS_CONTRACT
        or diagnostics.get("diagnostic_only") is not True
        or diagnostics.get("abort_requested") is not False
        or diagnostics.get("execution_mode") != "spawn_process"
        or diagnostics.get("error") is not None
        or type(started) is not int
        or type(finished) is not int
        or started <= 0
        or finished < started
        or diagnostics.get("result_count") != publisher_count
        or type(diagnostics.get("direct_call_count")) is not int
        or diagnostics.get("direct_call_count", 0) < publisher_count
        or diagnostics.get("client_opened") is not True
        or diagnostics.get("client_closed") is not True
        or not isinstance(call_rows, list)
        or len(call_rows) != publisher_count
        or not isinstance(call_times, list)
        or len(call_times) != publisher_count
        or not isinstance(expected_requests, list)
        or len(expected_requests) != publisher_count
    ):
        raise CampaignEvidenceError(
            "passing topic publisher diagnostics are not one complete spawn execution"
        )

    nonce = ack_payload.get("nonce")
    diagnostic_ack_payload = {
        key: nested for key, nested in ack_payload.items() if key != "nonce"
    }
    proof_requirement = proof.get("requirement")
    expected_step_name = (
        proof_requirement.get("step_name")
        if isinstance(proof_requirement, Mapping)
        else None
    )
    if (
        api != SOUNDBANK_TOPIC
        or ack.get("contract") != TOPIC_ACK_CONTRACT
        or ack.get("step_name") != expected_step_name
        or ack.get("topic") != api
        or ack.get("path") != proof.get("ack_path")
        or ack.get("file_sha256") != proof.get("ack_file_sha256")
        or not isinstance(nonce, str)
        or ack.get("nonce_sha256")
        != hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        or ack.get("observed") is not True
        or ack.get("observed_at_monotonic_ns")
        != proof.get("ack_observed_at_monotonic_ns")
        or ack.get("payload") != diagnostic_ack_payload
        or started != proof.get("publisher_started_at_monotonic_ns")
    ):
        raise CampaignEvidenceError(
            "topic publisher diagnostics do not join the sealed ACK proof"
        )

    child_pid = child.get("pid")
    parent_pid = child.get("parent_pid")
    coordinator_pid = child.get("coordinator_process_id")
    child_started = child.get("child_started_at_monotonic_ns")
    child_finished = child.get("child_finished_at_monotonic_ns")
    if (
        child.get("start_method") != "spawn"
        or type(child_pid) is not int
        or child_pid <= 0
        or type(parent_pid) is not int
        or parent_pid <= 0
        or type(coordinator_pid) is not int
        or coordinator_pid <= 0
        or child_pid == parent_pid
        or parent_pid != coordinator_pid
        or coordinator_pid == ack_payload.get("runner_parent_process_id")
        or coordinator_pid == ack_payload.get("gateway_process_id")
        or child_pid == ack_payload.get("gateway_process_id")
        or child.get("exit_code") != 0
        or child.get("reaped") is not True
        or child.get("terminate_requested") is not False
        or child.get("kill_requested") is not False
        or child.get("canonical_result_received") is not True
        or type(child_started) is not int
        or type(child_finished) is not int
        or not started <= child_started <= child_finished <= finished
        or child.get("cleanup_error") is not None
    ):
        raise CampaignEvidenceError(
            "passing topic publisher lacks a clean, ACK-bound spawned child process"
        )

    expected_call_keys = {
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
    for index, (row_value, request_value, call_time) in enumerate(
        zip(call_rows, expected_requests, call_times, strict=True),
        start=1,
    ):
        row = _closed_oracle_mapping(
            row_value,
            expected_call_keys,
            label=f"topic publisher call {index}",
        )
        result_evidence = _closed_oracle_mapping(
            row.get("result"),
            {"sha256", "size_bytes", "included", "value"},
            label=f"topic publisher call {index} result",
        )
        try:
            result_bytes = canonical_json_bytes(result_evidence.get("value"))
        except CampaignEvidenceError:
            result_bytes = b""
        expected_request_sha256 = hashlib.sha256(
            canonical_json_bytes(request_value)
        ).hexdigest()
        call_started = row.get("started_at_monotonic_ns")
        call_finished = row.get("finished_at_monotonic_ns")
        if (
            row.get("index") != index
            or row.get("request_sha256") != expected_request_sha256
            or row.get("status") != "succeeded"
            or row.get("uri") != "ak.wwise.core.soundbank.generate"
            or not _sha256_text_value(row.get("args_sha256"))
            or not _sha256_text_value(row.get("options_sha256"))
            or type(call_started) is not int
            or type(call_finished) is not int
            or call_started != call_time
            or not child_started <= call_started <= call_finished <= child_finished
            or result_evidence.get("included") is not True
            or type(result_evidence.get("size_bytes")) is not int
            or result_evidence.get("size_bytes") != len(result_bytes)
            or not _sha256_text_value(result_evidence.get("sha256"))
            or result_evidence.get("sha256")
            != hashlib.sha256(result_bytes).hexdigest()
        ):
            raise CampaignEvidenceError(
                "topic publisher call evidence is not bound to its reviewed request"
            )


def _validate_heavy_v3_topic_subscription_ack(
    value: Any,
    *,
    api: str,
    publisher_count: int,
    task_root: Path,
    prompt_evidence: HeavyV3PromptEvidence,
) -> None:
    """Join the sealed topic plan to one exclusive ACK-before-publish proof."""

    keys = {
        "contract",
        "business_oracle_plan_sha256",
        "requirement",
        "ack_path",
        "ack_file_sha256",
        "ack_payload",
        "ack_observed_at_monotonic_ns",
        "publisher_started_at_monotonic_ns",
        "publisher_call_started_at_monotonic_ns",
        "ack_before_publish",
    }
    proof = _closed_oracle_mapping(value, keys, label="topic subscription ACK")
    sections = prompt_evidence.typed_sections
    topic_binding = (
        sections.live_binding.get("topic")
        if isinstance(sections, SoundBankBusinessPlanSections)
        else None
    )
    planned_requirement = (
        topic_binding.get("subscription_ack_requirement")
        if isinstance(topic_binding, Mapping)
        else None
    )
    expected_step_name = (
        planned_requirement.get("step_name")
        if isinstance(planned_requirement, Mapping)
        else None
    )
    expected_requirement = {
        "contract": TOPIC_ACK_REQUIREMENT_CONTRACT,
        "ack_contract": TOPIC_ACK_CONTRACT,
        "step_name": expected_step_name,
        "topic": api,
        "fresh_exclusive_path_required": True,
        "publisher_requires_valid_ack": True,
    }
    if (
        api != SOUNDBANK_TOPIC
        or planned_requirement != expected_requirement
        or proof.get("requirement") != expected_requirement
        or proof.get("contract") != TOPIC_ACK_PROOF_CONTRACT
        or proof.get("business_oracle_plan_sha256")
        != prompt_evidence.business_oracle_plan.sha256
        or proof.get("ack_before_publish") is not True
    ):
        raise CampaignEvidenceError(
            "topic subscription ACK proof is not bound to its typed business plan"
        )

    try:
        task_result = load_strict_regular_json(task_root / "task-result.json")
    except Exception as exc:
        raise CampaignEvidenceError(
            f"topic subscription ACK lacks sealed broker record evidence: {exc}"
        ) from exc
    broker = task_result.get("broker") if isinstance(task_result, Mapping) else None
    records = broker.get("records") if isinstance(broker, Mapping) else None
    matching_records = (
        [
            record
            for record in records
            if isinstance(record, Mapping)
            and record.get("step_name") == expected_step_name
        ]
        if isinstance(records, list)
        else []
    )
    if (
        len(matching_records) != 1
        or matching_records[0].get("authenticated") is not True
        or matching_records[0].get("accepted") is not True
        or matching_records[0].get("succeeded") is not True
        or matching_records[0].get("payload_error") != ""
    ):
        raise CampaignEvidenceError(
            "topic subscription ACK has no exact successful broker step record"
        )
    broker_record = matching_records[0]
    broker_ack = _validate_heavy_v3_broker_subscription_ack_record(
        broker_record.get("subscription_ack"),
        record=broker_record,
        task_root=task_root,
        label="topic subscription ACK broker record",
        expected_step_name=str(expected_step_name),
    )

    ack_path_value = proof.get("ack_path")
    if not isinstance(ack_path_value, str) or not ack_path_value:
        raise CampaignEvidenceError("topic subscription ACK path is invalid")
    ack_path = Path(ack_path_value)
    evidence_directory = task_root / "broker" / "evidence"
    try:
        real_parent = ack_path.parent.resolve(strict=True)
        real_evidence = evidence_directory.resolve(strict=True)
    except OSError as exc:
        raise CampaignEvidenceError(
            f"topic subscription ACK artifact is unavailable: {exc}"
        ) from exc
    if (
        not ack_path.is_absolute()
        or ack_path.parent != evidence_directory
        or real_parent != real_evidence
        or not ack_path.name.startswith("subscription-ack-")
        or not ack_path.name.endswith(".json")
    ):
        raise CampaignEvidenceError(
            "topic subscription ACK is not one private exclusive broker artifact"
        )
    try:
        snapshot = read_bounded_exclusive_regular_file(
            ack_path,
            max_bytes=4096,
        )
        raw = snapshot.raw
    except CodexFileSecurityError as exc:
        raise CampaignEvidenceError(
            "topic subscription ACK is not one private exclusive broker artifact: "
            f"{exc}"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != proof.get("ack_file_sha256"):
        raise CampaignEvidenceError("topic subscription ACK file proof drifted")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignEvidenceError(
            f"topic subscription ACK is not strict UTF-8 JSON: {exc}"
        ) from exc
    payload_keys = {
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
    ack_file_sha256 = hashlib.sha256(raw).hexdigest()
    if (
        not isinstance(payload, Mapping)
        or set(payload) != payload_keys
        or proof.get("ack_payload") != payload
        or payload.get("contract") != TOPIC_ACK_CONTRACT
        or payload.get("step_name") != expected_requirement["step_name"]
        or payload.get("topic") != api
        or not isinstance(nonce, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", nonce) is None
        or type(payload.get("runner_parent_process_id")) is not int
        or payload.get("runner_parent_process_id", 0) <= 0
        or type(payload.get("gateway_process_id")) is not int
        or payload.get("gateway_process_id", 0) <= 0
        or payload.get("gateway_process_id")
        == payload.get("runner_parent_process_id")
        or type(payload.get("subscribed_at_unix_ns")) is not int
        or type(payload.get("subscribed_at_monotonic_ns")) is not int
        or payload.get("subscribed_at_monotonic_ns", 0) <= 0
        or raw != canonical_json_bytes(payload) + b"\n"
    ):
        raise CampaignEvidenceError(
            "topic subscription ACK payload identity or canonical form is invalid"
        )
    if (
        broker_ack.get("ack_path") != str(ack_path)
        or broker_ack.get("ack_file_sha256") != ack_file_sha256
        or proof.get("ack_file_sha256") != ack_file_sha256
        or broker_ack.get("nonce_sha256") != nonce_sha256
        or broker_ack.get("runner_parent_process_id")
        != payload.get("runner_parent_process_id")
        or broker_ack.get("gateway_process_id")
        != payload.get("gateway_process_id")
        or broker_ack.get("subscribed_at_unix_ns")
        != payload.get("subscribed_at_unix_ns")
        or broker_ack.get("subscribed_at_monotonic_ns")
        != payload.get("subscribed_at_monotonic_ns")
    ):
        raise CampaignEvidenceError(
            "topic subscription ACK proof does not join its validated broker hash, PID, and time"
        )
    observed = proof.get("ack_observed_at_monotonic_ns")
    started = proof.get("publisher_started_at_monotonic_ns")
    call_times = proof.get("publisher_call_started_at_monotonic_ns")
    if (
        type(observed) is not int
        or type(started) is not int
        or not isinstance(call_times, list)
        or len(call_times) != publisher_count
        or any(type(item) is not int or item <= 0 for item in call_times)
        or not int(payload["subscribed_at_monotonic_ns"])
        <= observed
        <= started
        <= min(call_times)
    ):
        raise CampaignEvidenceError(
            "topic publisher timeline does not prove ACK before every publish"
        )


def _validate_cli_file_proof(value: Any, *, label: str) -> None:
    _validate_file_proof(
        value,
        label=label,
        relative_optional=False,
        has_mtime=True,
    )


def _validate_cli_tree_proof(value: Any, *, label: str) -> None:
    row = _closed_oracle_mapping(value, {"root", "files", "sha256"}, label=label)
    files = row.get("files")
    root = row.get("root")
    try:
        _validated_archive_absolute_path(root, label=f"{label} root")
    except CampaignEvidenceError as exc:
        raise CampaignEvidenceError(f"{label} tree proof is malformed") from exc
    if (
        not _nonempty_text(root)
        or not isinstance(files, list)
        or not _sha256_text_value(row.get("sha256"))
    ):
        raise CampaignEvidenceError(f"{label} tree proof is malformed")
    digest = hashlib.sha256()
    relatives: list[str] = []
    for item in files:
        _validate_cli_file_proof(item, label=f"{label} file")
        relative = str(item["relative_path"])
        try:
            parsed_relative = parse_archive_relative_path(relative)
            derived_relative = archive_relative_from_absolute(item["path"], root)
        except ArchiveRelativePathError as exc:
            raise CampaignEvidenceError(
                f"{label} file escaped its tree root"
            ) from exc
        if (
            parsed_relative.source_flavor != "posix"
            or parsed_relative.canonical != relative
            or derived_relative.canonical != relative
        ):
            raise CampaignEvidenceError(
                f"{label} file path is not its canonical tree identity"
            )
        relatives.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\0")
    if relatives != sorted(relatives) or len(relatives) != len(set(relatives)):
        raise CampaignEvidenceError(f"{label} file order/identity is invalid")
    if row.get("sha256") != digest.hexdigest():
        raise CampaignEvidenceError(f"{label} tree digest is invalid")


def _validate_cli_snapshot(value: Any, *, label: str) -> None:
    row = _closed_oracle_mapping(
        value,
        {
            "project_tree",
            "source_template_tree",
            "asset_tree",
            "output_tree",
            "objects",
            "events",
            "migration_inventory",
            "project_version",
        },
        label=label,
    )
    for field in ("project_tree", "source_template_tree", "asset_tree", "output_tree"):
        _validate_cli_tree_proof(row.get(field), label=f"{label} {field}")
    for collection in ("objects", "events", "migration_inventory"):
        if not isinstance(row.get(collection), list):
            raise CampaignEvidenceError(f"{label} {collection} is not an array")
    object_paths: list[str] = []
    for item in row["objects"]:
        object_row = _closed_oracle_mapping(
            item,
            {
                "path",
                "object_id",
                "object_type",
                "name",
                "parent_id",
                "language",
                "source_path",
                "source_sha256",
                "notes",
                "short_id",
            },
            label=f"{label} object",
        )
        if (
            any(not _nonempty_text(object_row.get(field)) for field in ("path", "object_id", "object_type", "name"))
            or not _optional_text(object_row.get("parent_id"))
            or not _optional_text(object_row.get("language"))
            or not _optional_text(object_row.get("source_path"))
            or not (
                object_row.get("source_sha256") is None
                or _sha256_text_value(object_row.get("source_sha256"))
            )
            or not _optional_text(object_row.get("notes"))
            or not (
                object_row.get("short_id") is None
                or _plain_int(object_row.get("short_id"))
            )
        ):
            raise CampaignEvidenceError(f"{label} object is malformed")
        object_paths.append(str(object_row["path"]))
    if len(object_paths) != len(set(object_paths)):
        raise CampaignEvidenceError(f"{label} object paths are duplicated")
    event_paths: list[str] = []
    for item in row["events"]:
        event = _closed_oracle_mapping(
            item,
            {"path", "object_id", "action_ids", "target_ids", "action_types"},
            label=f"{label} event",
        )
        if (
            not _nonempty_text(event.get("path"))
            or not _nonempty_text(event.get("object_id"))
            or any(
                not isinstance(event.get(field), list)
                for field in ("action_ids", "target_ids", "action_types")
            )
            or any(not _nonempty_text(item) for item in event.get("action_ids", []))
            or any(not _nonempty_text(item) for item in event.get("target_ids", []))
            or any(type(item) is not int for item in event.get("action_types", []))
        ):
            raise CampaignEvidenceError(f"{label} event is malformed")
        event_paths.append(str(event["path"]))
    if len(event_paths) != len(set(event_paths)):
        raise CampaignEvidenceError(f"{label} event paths are duplicated")
    inventory_keys: list[str] = []
    for item in row["migration_inventory"]:
        inventory = _closed_oracle_mapping(
            item,
            {"key", "identity", "semantic_rows", "reference_rows"},
            label=f"{label} migration inventory",
        )
        identity = inventory.get("identity")
        if (
            not _nonempty_text(inventory.get("key"))
            or not isinstance(identity, list)
            or len(identity) != 4
            or any(not _nonempty_text(field) for field in identity[:3])
            or not (
                identity[3] is None
                or (
                    isinstance(identity[3], list)
                    and len(identity[3]) == 3
                    and _nonempty_text(identity[3][0])
                    and all(isinstance(field, str) for field in identity[3][1:])
                )
            )
            or not isinstance(inventory.get("semantic_rows"), list)
            or not isinstance(inventory.get("reference_rows"), list)
            or any(not isinstance(value, list) or not _json_archive_value(value) for value in inventory.get("semantic_rows", []))
            or any(not isinstance(value, list) or not _json_archive_value(value) for value in inventory.get("reference_rows", []))
        ):
            raise CampaignEvidenceError(f"{label} migration inventory is malformed")
        inventory_keys.append(str(inventory["key"]))
    if len(inventory_keys) != len(set(inventory_keys)):
        raise CampaignEvidenceError(f"{label} migration inventory keys are duplicated")
    if not _optional_text(row.get("project_version")):
        raise CampaignEvidenceError(f"{label} project version is malformed")


def _validate_heavy_v3_cli_oracle(
    value: Any,
    *,
    api: str,
    scenario_id: str,
    label: str,
) -> None:
    row = _closed_oracle_mapping(
        value,
        {"scenario_id", "phase", "passed", "failures", "before", "after"},
        label=label,
    )
    _require_passing_oracle(row, label=label)
    if row.get("scenario_id") != scenario_id or row.get("phase") != "after":
        raise CampaignEvidenceError(f"{label} CLI identity/phase is invalid")
    _validate_cli_snapshot(row.get("before"), label=f"{label} before")
    _validate_cli_snapshot(row.get("after"), label=f"{label} after")
    before = row["before"]
    after = row["after"]
    if before["source_template_tree"] != after["source_template_tree"]:
        raise CampaignEvidenceError(f"{label} immutable CLI source/template changed")
    if api == "ak.wwise.cli.convertExternalSource":
        try:
            validate_cli_convert_archived_side_effects(before, after)
        except CliBusinessPlanError as exc:
            raise CampaignEvidenceError(
                f"{label} CLI convert side effects are invalid: {exc}"
            ) from exc
        if before["output_tree"] == after["output_tree"]:
            raise CampaignEvidenceError(f"{label} CLI output/project delta is invalid")
    elif api == "ak.wwise.cli.generateSoundbank":
        if before["asset_tree"] != after["asset_tree"]:
            raise CampaignEvidenceError(f"{label} immutable CLI input assets changed")
        if (
            authored_project_archive_projection(before["project_tree"])
            != authored_project_archive_projection(after["project_tree"])
            or before["output_tree"] == after["output_tree"]
        ):
            raise CampaignEvidenceError(f"{label} CLI output/project delta is invalid")
    elif api == "ak.wwise.cli.tabDelimitedImport":
        if before["asset_tree"] != after["asset_tree"]:
            raise CampaignEvidenceError(f"{label} immutable CLI input assets changed")
        if before["project_tree"] == after["project_tree"]:
            raise CampaignEvidenceError(f"{label} tab import did not change project proof")
    elif api == "ak.wwise.cli.migrate":
        if before["asset_tree"] != after["asset_tree"]:
            raise CampaignEvidenceError(f"{label} immutable CLI input assets changed")
        if (
            before["project_tree"] == after["project_tree"]
            or before["migration_inventory"] != after["migration_inventory"]
            or not str(after.get("project_version") or "").startswith("v2022.1")
        ):
            raise CampaignEvidenceError(f"{label} migration proof is invalid")


def _validate_heavy_v3_pass_lifecycle(
    lifecycle: Mapping[str, Any],
    *,
    checks: Mapping[str, Any],
    expected_row: Mapping[str, Any],
    scenario_root: Path,
    task_root: Path,
) -> None:
    runner = str(expected_row["runner"])
    scenario_id = str(expected_row["scenario_id"])
    version = str(expected_row["version"])
    lifecycle_path = task_root.parent / "lifecycle.json"
    archived = load_strict_regular_json(lifecycle_path)
    if archived != lifecycle:
        raise CampaignEvidenceError(
            "passing heavy outcome lifecycle differs from lifecycle.json"
        )
    owned_root = scenario_root / "owned"
    if owned_root.exists() or owned_root.is_symlink():
        raise CampaignEvidenceError("passing heavy scenario retained owned state")

    if runner == "project":
        required = {
            "contract",
            "scenario_id",
            "version",
            "requested_status",
            "final_status",
            "sandbox_retained",
            "source_hash_before",
            "source_hash_after",
            "source_mtime_before_ns",
            "source_mtime_after_ns",
            "errors",
            "quarantine_path",
        }
        if (
            set(lifecycle) != required
            or lifecycle.get("contract") != HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT
            or lifecycle.get("scenario_id") != scenario_id
            or lifecycle.get("version") != version
            or lifecycle.get("requested_status") != "PASS"
            or lifecycle.get("final_status") != "PASS"
            or lifecycle.get("sandbox_retained") is not False
            or lifecycle.get("errors") != []
            or lifecycle.get("quarantine_path") is not None
            or not isinstance(lifecycle.get("source_hash_before"), Mapping)
            or lifecycle.get("source_hash_before") != lifecycle.get("source_hash_after")
            or type(lifecycle.get("source_mtime_before_ns")) is not int
            or lifecycle.get("source_mtime_before_ns")
            != lifecycle.get("source_mtime_after_ns")
        ):
            raise CampaignEvidenceError("passing project lifecycle proof is invalid")
        start = load_strict_regular_json(task_root.parent / "start.json")
        expected_start_keys = {
            "contract",
            "scenario_id",
            "version",
            "started_at",
            "source_hash_before",
            "source_mtime_before_ns",
            "sandbox_project",
            "launch_cwd",
            "endpoint",
            "isolated_launch_environment",
            "owned_wine_prefix",
        }
        sandbox_project_value = start.get("sandbox_project") if isinstance(start, Mapping) else None
        launch_cwd_value = start.get("launch_cwd") if isinstance(start, Mapping) else None
        expected_launch_cwd = scenario_root.resolve(strict=True) / "owned" / "sandbox-root"
        sandbox_project = (
            Path(sandbox_project_value)
            if isinstance(sandbox_project_value, str)
            else None
        )
        launch_cwd = (
            Path(launch_cwd_value)
            if isinstance(launch_cwd_value, str)
            else None
        )
        if (
            not isinstance(start, Mapping)
            or set(start) != expected_start_keys
            or start.get("contract") != HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT
            or start.get("scenario_id") != scenario_id
            or start.get("version") != version
            or start.get("source_hash_before") != lifecycle.get("source_hash_before")
            or start.get("source_mtime_before_ns")
            != lifecycle.get("source_mtime_before_ns")
            or not _valid_heavy_utc_timestamp(start.get("started_at"))
            or not isinstance(start.get("endpoint"), Mapping)
            or start["endpoint"].get("host") not in {"127.0.0.1", "localhost", "::1"}
            or type(start["endpoint"].get("port")) is not int
            or sandbox_project is None
            or not sandbox_project.is_absolute()
            or not _path_is_within(sandbox_project, expected_launch_cwd)
            or launch_cwd is None
            or not launch_cwd.is_absolute()
            or launch_cwd != expected_launch_cwd
        ):
            raise CampaignEvidenceError("passing project start proof is invalid")
        return

    required = {
        "contract",
        "requested_status",
        "final_status",
        "owned_state_retained",
        "quarantine_path",
        "source_hash_before",
        "source_hash_after",
        "source_mtime_before_ns",
        "source_mtime_after_ns",
        "phases",
        "errors",
    }
    phases = lifecycle.get("phases")
    if (
        set(lifecycle) != required
        or lifecycle.get("contract") != HEAVY_V3_CLI_LIFECYCLE_CONTRACT
        or lifecycle.get("requested_status") != "PASS"
        or lifecycle.get("final_status") != "PASS"
        or lifecycle.get("owned_state_retained") is not False
        or lifecycle.get("quarantine_path") is not None
        or lifecycle.get("errors") != []
        or not isinstance(lifecycle.get("source_hash_before"), Mapping)
        or lifecycle.get("source_hash_before") != lifecycle.get("source_hash_after")
        or type(lifecycle.get("source_mtime_before_ns")) is not int
        or lifecycle.get("source_mtime_before_ns")
        != lifecycle.get("source_mtime_after_ns")
        or not isinstance(phases, list)
        or not phases
    ):
        raise CampaignEvidenceError("passing CLI lifecycle proof is invalid")
    phase_order = checks.get("phase_order")
    if not isinstance(phase_order, list) or len(phase_order) != len(phases):
        raise CampaignEvidenceError("passing CLI phase-order proof is invalid")
    observed_roles: list[str] = []
    expected_launch_cwd = scenario_root.resolve(strict=True) / "owned" / "case"
    for phase in phases:
        if not isinstance(phase, Mapping):
            raise CampaignEvidenceError("passing CLI phase proof is malformed")
        evidence = phase.get("evidence")
        role = evidence.get("role") if isinstance(evidence, Mapping) else None
        if (
            not isinstance(role, str)
            or not role
            or not isinstance(evidence, Mapping)
            or evidence.get("shell") is not False
            or evidence.get("started") is not True
            or evidence.get("ready") is not True
            or evidence.get("process_exited") is not True
            or evidence.get("residual_pids") != []
            or evidence.get("shutdown_error") is not None
            or phase.get("log_overflow") is not False
            or phase.get("ready_version") != version
            or _SHA256_RE.fullmatch(str(phase.get("stdout_sha256"))) is None
            or _SHA256_RE.fullmatch(str(phase.get("stderr_sha256"))) is None
        ):
            raise CampaignEvidenceError("passing CLI process phase is not clean")
        cwd = evidence.get("cwd")
        if (
            not isinstance(cwd, str)
            or not Path(cwd).is_absolute()
            or Path(cwd) != expected_launch_cwd
        ):
            raise CampaignEvidenceError(
                "passing CLI process cwd is not the exact case-owned root"
            )
        opened = evidence.get("open_project_path")
        if (
            not isinstance(opened, str)
            or not Path(opened).is_absolute()
            or not _path_is_within(Path(opened), expected_launch_cwd)
        ):
            raise CampaignEvidenceError(
                "passing CLI phase opened a project outside owned state"
            )
        observed_roles.append(role)
    if observed_roles != phase_order or len(observed_roles) != len(set(observed_roles)):
        raise CampaignEvidenceError("passing CLI lifecycle phase order drifted")


def _strict_real_subdirectory_names(root: Path) -> set[str]:
    directory = _require_real_directory(
        Path(root),
        label="evidence directory",
    )
    names: set[str] = set()
    for entry in os.scandir(directory):
        info = entry.stat(follow_symlinks=False)
        entry_path = Path(entry.path)
        if (
            not stat.S_ISDIR(info.st_mode)
            or path_is_link_or_reparse(entry_path, metadata=info)
        ):
            raise CampaignEvidenceError(
                f"evidence directory contains a non-directory entry: {entry.path}"
            )
        names.add(entry.name)
    return names


def _load_strict_regular_text(path: Path, *, limit_bytes: int = 8 * 1024 * 1024) -> str:
    source = Path(path)
    try:
        snapshot = read_bounded_exclusive_regular_file(
            source,
            max_bytes=limit_bytes,
            require_private_posix_mode=False,
            allow_empty=True,
        )
    except (CodexFileSecurityError, ValueError) as exc:
        raise CampaignEvidenceError(
            f"child text is not a bounded exclusive regular file: {source}: {exc}"
        ) from exc
    try:
        return snapshot.raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignEvidenceError(f"child text is not UTF-8: {source}") from exc


def _heavy_v3_outcome_contract(runner: str, *, profile: str | None = None) -> str:
    if runner == "project":
        return HEAVY_V3_PROJECT_OUTCOME_CONTRACT
    if runner == "cli":
        return HEAVY_V3_CLI_OUTCOME_CONTRACT
    if runner == "agent":
        contract = BUSINESS_AGENT_OUTCOME_CONTRACTS.get(str(profile))
        if contract is None:
            raise CampaignEvidenceError("unknown business Agent outcome contract")
        return contract
    raise CampaignEvidenceError(f"unknown heavy runner lane: {runner}")


def _heavy_v3_scenario_directories(root: Path) -> dict[str, Path]:
    scenarios_root = root / "scenarios"
    if not os.path.lexists(scenarios_root):
        return {}
    scenarios_root = _require_real_directory(
        scenarios_root,
        label="heavy scenarios root",
    )
    try:
        entries = tuple(os.scandir(scenarios_root))
    except OSError as exc:
        raise CampaignEvidenceError(
            f"cannot scan heavy scenario evidence: {exc}"
        ) from exc
    result: dict[str, Path] = {}
    for entry in entries:
        info = entry.stat(follow_symlinks=False)
        entry_path = Path(entry.path)
        if (
            not stat.S_ISDIR(info.st_mode)
            or path_is_link_or_reparse(entry_path, metadata=info)
        ):
            raise CampaignEvidenceError(
                f"heavy scenario evidence entry is not a real directory: {entry.path}"
            )
        result[entry.name] = _require_real_directory(
            entry_path,
            label="heavy scenario evidence entry",
        )
    return result


def _valid_heavy_timestamp(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.endswith("Z")


def _valid_heavy_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    offset = parsed.utcoffset()
    return offset is not None and offset.total_seconds() == 0


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def current_candidate_sha256(skill_source: Path, *, effective: Mapping[str, Any]) -> str:
    candidate = effective.get("candidate")
    if not isinstance(candidate, Mapping):
        raise CampaignEvidenceError("campaign candidate config is malformed")
    excludes = candidate.get("excluded_names")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise CampaignEvidenceError("campaign candidate exclusions are malformed")
    return stable_tree_sha256(skill_source, exclude_names=tuple(excludes))


def assert_candidate_frozen(skill_source: Path, *, effective: Mapping[str, Any]) -> None:
    candidate = effective.get("candidate")
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get("tree_sha256"), str):
        raise CampaignEvidenceError("campaign candidate config is malformed")
    expected = str(candidate["tree_sha256"])
    actual = current_candidate_sha256(skill_source, effective=effective)
    if actual != expected:
        raise CampaignEvidenceError(
            f"candidate Skill drifted from immutable campaign hash: expected={expected} actual={actual}"
        )


def assert_effective_inputs_frozen(
    options: CampaignOptions,
    *,
    effective: Mapping[str, Any],
) -> None:
    """Re-hash every executable/evidence input at each child boundary."""

    assert_candidate_frozen(options.skill_source, effective=effective)

    def require_section(name: str) -> Mapping[str, Any]:
        section = effective.get(name)
        if not isinstance(section, Mapping):
            raise CampaignEvidenceError(f"campaign {name} fingerprint is malformed")
        return section

    suite = require_section("suite")
    live_config = require_section("live_config")
    codex = require_section("codex")
    runtime = require_section("runtime")
    harness = require_section("harness")
    file_bindings = (
        ("suite", options.suite_path, suite),
        *(
            (("live config", options.live_config, live_config),)
            if not options.offline_only
            else ()
        ),
        ("Codex binary", options.codex_binary, codex),
    )
    for label, path, section in file_bindings:
        if section.get("path") != str(path) or section.get("sha256") != sha256_file(path):
            raise CampaignEvidenceError(f"{label} drifted from the immutable campaign fingerprint")
    if options.offline_only and live_config != {
        "path": str(options.live_config),
        "sha256": None,
        "used": False,
    }:
        raise CampaignEvidenceError(
            "offline campaign must seal live config as unused"
        )
    if codex.get("runtime_files", []) != _codex_runtime_fingerprints(options.codex_binary):
        raise CampaignEvidenceError(
            "Codex runtime helpers drifted from the immutable campaign fingerprint"
        )
    _assert_codex_shell_frozen(codex)

    interpreter = Path(sys.executable).resolve(strict=True)
    if (
        runtime.get("interpreter") != str(interpreter)
        or runtime.get("interpreter_sha256") != sha256_file(interpreter)
    ):
        raise CampaignEvidenceError("Python interpreter drifted from the immutable campaign fingerprint")
    excludes = harness.get("excluded_names")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise CampaignEvidenceError("campaign harness exclusions are malformed")
    excluded_names = tuple(excludes)
    semantic_hash = stable_tree_sha256(
        REPO_ROOT / "tests" / "semantic", exclude_names=excluded_names
    )
    destructive_hash = stable_tree_sha256(
        REPO_ROOT / "tests" / "destructive" / "support", exclude_names=excluded_names
    )
    if harness.get("semantic_tree_sha256") != semantic_hash:
        raise CampaignEvidenceError("semantic harness drifted from the immutable campaign fingerprint")
    if harness.get("destructive_support_tree_sha256") != destructive_hash:
        raise CampaignEvidenceError(
            "destructive support harness drifted from the immutable campaign fingerprint"
        )


def required_unit_map(sessions: Sequence[EvalSession]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for session in sessions:
        grouped.setdefault(session.pair_id, []).append(session.phase)
    return {pair_id: tuple(phases) for pair_id, phases in grouped.items()}


def build_child_groups(
    sessions: Sequence[EvalSession],
    *,
    scheduled_unit_ids: Sequence[str],
) -> tuple[ChildGroup, ...]:
    scheduled = frozenset(scheduled_unit_ids)
    selected = tuple(session for session in sessions if session.pair_id in scheduled)
    groups: list[ChildGroup] = []
    offline = tuple(session for session in selected if session.case.id in matrix.OFFLINE_CASE_IDS)
    if offline:
        groups.append(
            ChildGroup(
                group_id="offline",
                version=None,
                pair_ids=ordered_unique(session.pair_id for session in offline),
                sessions=offline,
            )
        )
    for version in SUPPORTED_VERSIONS:
        live = tuple(
            session
            for session in selected
            if session.case.id not in matrix.OFFLINE_CASE_IDS and session.version == version
        )
        if live:
            groups.append(
                ChildGroup(
                    group_id=f"live-{version.replace('.', '-')}",
                    version=version,
                    pair_ids=ordered_unique(session.pair_id for session in live),
                    sessions=live,
                )
            )
    grouped_ids = {session.session_id for group in groups for session in group.sessions}
    if grouped_ids != {session.session_id for session in selected}:
        raise CampaignEvidenceError("scheduled sessions did not map to exactly one child group")
    return tuple(groups)


def _require_standard_windows_path_budget(
    options: CampaignOptions,
    *,
    sessions: Sequence[EvalSession],
) -> WindowsCampaignPathBudget | None:
    """Project every ordinary matrix directory passed to ``CreateProcessW``."""

    groups = build_child_groups(
        sessions,
        scheduled_unit_ids=ordered_unique(session.pair_id for session in sessions),
    )
    projected: list[tuple[str, Path]] = []
    attempt = Path("attempts") / "attempt-999999" / "runs"
    for group in groups:
        matrix_root = attempt / group.group_id / "matrix"
        for session in group.sessions:
            workspace = (
                matrix_root
                / "sessions"
                / matrix.safe_session_name(session.session_id)
                / "agent-workspace"
            )
            projected.append(
                (f"Codex/pwsh cwd for {session.session_id}", workspace)
            )
        if group.version is not None:
            sandbox_cwd = (
                matrix_root
                / "versions"
                / group.version
                / "sandbox-root"
            )
            projected.append(
                (f"WwiseConsole cwd for {group.version}", sandbox_cwd)
            )
    return require_windows_campaign_path_budget(
        options.campaign_root,
        projected,
    )


def _require_heavy_windows_path_budget(
    options: CampaignOptions,
    *,
    units: Sequence[Any],
) -> WindowsCampaignPathBudget | None:
    """Project every heavy/integration process cwd before campaign creation."""

    projected: list[tuple[str, Path]] = []
    scenarios = (
        Path("attempts")
        / "attempt-999999"
        / "runs"
        / HEAVY_V3_GROUP_ID
        / "matrix"
        / "scenarios"
    )
    for sequence, unit in enumerate(units, start=1):
        unit_id = str(unit.unit_id)
        scenario = scenarios / f"{sequence:03d}-{matrix.safe_session_name(unit_id)}"
        projected.extend(
            (
                (
                    f"Codex/pwsh cwd for {unit_id}",
                    scenario / "evidence" / "codex-task" / "agent-workspace",
                ),
                (
                    f"WwiseConsole sandbox cwd for {unit_id}",
                    scenario / "owned" / "sandbox-root",
                ),
                (
                    f"WwiseConsole CLI case cwd for {unit_id}",
                    scenario / "owned" / "case",
                ),
            )
        )
    return require_windows_campaign_path_budget(
        options.campaign_root,
        projected,
    )


def _print_windows_path_budget(
    budget: WindowsCampaignPathBudget | None,
) -> None:
    if budget is None:
        return
    worst = budget.worst
    policy = (
        "enabled"
        if budget.long_paths_enabled is True
        else "disabled"
        if budget.long_paths_enabled is False
        else "unknown"
    )
    print(
        "[campaign-preflight] Windows process cwd budget "
        f"ok worst={worst.utf16_units}/{budget.limit_utf16_units} "
        f"max_campaign_root={budget.max_campaign_root_utf16_units} "
        f"LongPathsEnabled={policy} label={worst.label!r}",
        flush=True,
    )


def build_child_argv(
    options: CampaignOptions,
    *,
    group: ChildGroup,
    matrix_root: Path,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> list[str]:
    argv = [
        sys.executable,
        str(REPO_ROOT / "tests" / "semantic" / "run_codex_skill_matrix.py"),
        "--profile",
        options.profile,
        "--suite",
        str(options.suite_path),
        "--iteration-root",
        str(matrix_root),
        "--skill-source",
        str(options.skill_source),
        "--codex-binary",
        str(options.codex_binary),
        "--auth-json",
        str(options.auth_json),
        "--live-config",
        str(options.live_config),
        "--model",
        options.model,
        "--reasoning-effort",
        options.reasoning_effort,
        "--service-tier",
        options.service_tier,
        "--timeout",
        str(options.timeout_seconds),
        "--wwise-readiness-timeout",
        str(options.wwise_readiness_timeout_seconds),
    ]
    if windows_powershell_core_host is not None:
        argv.extend(
            (
                "--sealed-windows-powershell-core-host-json",
                _windows_powershell_core_host_cli_json(
                    windows_powershell_core_host
                ),
            )
        )
    if group.offline_only:
        argv.append("--offline-only")
    else:
        argv.extend(("--version", str(group.version)))
    for pair_id in group.pair_ids:
        argv.extend(("--pair-id", pair_id))
    return argv


def run_child(argv: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    process_group_options: dict[str, Any] = {}
    if os.name == "posix":
        process_group_options["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        process_group_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    child_environment = dict(os.environ)
    for name in tuple(child_environment):
        if (
            name.casefold() == "pythonioencoding"
            or is_evaluation_sensitive_environment_key(name)
        ):
            del child_environment[name]
    child_environment["PYTHONIOENCODING"] = "utf-8:strict"
    return subprocess.run(
        list(argv),
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=child_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **process_group_options,
    )


def blocked_child_validation(group: ChildGroup, *, reason: str) -> ChildValidation:
    first = group.sessions[0]
    verdict = {
        "unit_id": first.pair_id,
        "status": "BLOCKED",
        "phases": [{"phase": first.phase, "status": "BLOCKED"}],
    }
    phase_verdict = PhaseVerdict(
        session_id=first.session_id,
        phase=first.phase,
        status="BLOCKED",
        reason=reason,
    )
    return ChildValidation(
        observations=(verdict,),
        phase_verdicts=(phase_verdict,),
        executed_session_ids=(),
        pending_session_ids=tuple(session.session_id for session in group.sessions),
        retry_categories=(),
        summary={"validation_error": reason},
    )


def load_verified_attempts(root: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for attempt in list_campaign_attempts(root):
        if not (attempt / ATTEMPT_MANIFEST_FILE).is_file():
            raise CampaignEvidenceError(f"campaign contains an unsealed attempt: {attempt}")
        manifests.append(verify_attempt_seal(attempt))
    return manifests


def _validate_modification_policy_identity_history(
    campaign_root: Path,
    *,
    manifests: Sequence[Mapping[str, Any]],
    current_attempt_root: Path | None = None,
) -> None:
    """Require a fresh Codex task and thread for every policy attempt.

    A failed invocation may legitimately stop before Codex returns a thread
    identity.  Non-empty identities are nevertheless campaign-global: a retry
    must create a new task instead of resuming evidence from an earlier
    attempt.
    """

    root = _require_real_directory(
        Path(campaign_root),
        label="modification-policy campaign root",
    )
    attempts_root = root / "attempts"
    resolved_attempts_root = (
        _require_real_directory(
            attempts_root,
            label="modification-policy attempts root",
        )
        if manifests or current_attempt_root is not None
        else attempts_root
    )
    attempt_roots: list[tuple[str, Path]] = []
    seen_attempt_ids: set[str] = set()
    for manifest in manifests:
        attempt_id = manifest.get("attempt_id")
        if (
            not isinstance(attempt_id, str)
            or not attempt_id
            or attempt_id in seen_attempt_ids
        ):
            raise CampaignEvidenceError(
                "modification-policy identity audit received invalid attempts"
            )
        seen_attempt_ids.add(attempt_id)
        attempt_root = _require_real_directory(
            attempts_root / attempt_id,
            label=f"{attempt_id} modification-policy attempt root",
        )
        if attempt_root.parent != resolved_attempts_root:
            raise CampaignEvidenceError(
                f"{attempt_id} modification-policy attempt escapes its campaign"
            )
        attempt_roots.append((attempt_id, attempt_root))
    if current_attempt_root is not None:
        current = _require_real_directory(
            Path(current_attempt_root),
            label="current modification-policy attempt root",
        )
        if current.parent != resolved_attempts_root:
            raise CampaignEvidenceError(
                "current modification-policy attempt escapes the campaign"
            )
        if current.name in seen_attempt_ids:
            raise CampaignEvidenceError(
                "current modification-policy attempt is already sealed"
            )
        attempt_roots.append((current.name, current))

    seen_threads: dict[str, str] = {}
    for attempt_id, attempt_root in attempt_roots:
        matrix_root = attempt_root / "runs" / HEAVY_V3_GROUP_ID / "matrix"
        if not os.path.lexists(matrix_root):
            continue
        _require_real_directory(
            matrix_root,
            label=f"{attempt_id} modification-policy matrix root",
        )
        for scenario_name, scenario_root in sorted(
            _heavy_v3_scenario_directories(matrix_root).items()
        ):
            label = f"{attempt_id}/{scenario_name}"
            outcome_path = scenario_root / "outcome.json"
            outcome: Mapping[str, Any] | None = None
            if outcome_path.exists():
                loaded_outcome = load_strict_regular_json(outcome_path)
                if not isinstance(loaded_outcome, Mapping):
                    raise CampaignEvidenceError(
                        f"{label} policy outcome is malformed"
                    )
                outcome = loaded_outcome

            task_root = scenario_root / "evidence" / "codex-task"
            if not os.path.lexists(task_root):
                if outcome is not None and (
                    outcome.get("thread_id") is not None
                    or outcome.get("task_root") is not None
                ):
                    raise CampaignEvidenceError(
                        f"{label} outcome claims an absent policy task"
                )
                continue
            _require_real_directory(
                task_root,
                label=f"{label} policy task root",
            )
            if outcome is None or outcome.get("task_root") != str(task_root):
                raise CampaignEvidenceError(
                    f"{label} outcome is not bound to its raw policy task"
                )

            turns_root = task_root / "turns"
            if not turns_root.exists():
                if outcome.get("thread_id") is not None:
                    raise CampaignEvidenceError(
                        f"{label} claims a thread without raw turn evidence"
                    )
                continue
            thread_ids: list[str] = []
            for turn_name in sorted(_strict_real_subdirectory_names(turns_root)):
                if re.fullmatch(r"turn-\d{2}", turn_name) is None:
                    raise CampaignEvidenceError(
                        f"{label} has an invalid policy turn directory"
                    )
                events_text = _load_strict_regular_text(
                    turns_root / turn_name / "events.jsonl"
                )
                if count_invalid_jsonl_lines(events_text):
                    raise CampaignEvidenceError(
                        f"{label}/{turn_name} has invalid raw Codex events"
                    )
                for event in parse_jsonl_events(events_text):
                    if event.get("type") != "thread.started":
                        continue
                    thread_id = event.get("thread_id")
                    if not isinstance(thread_id, str) or not thread_id:
                        raise CampaignEvidenceError(
                            f"{label}/{turn_name} has a malformed raw thread identity"
                        )
                    thread_ids.append(thread_id)

            distinct_thread_ids = tuple(dict.fromkeys(thread_ids))
            if len(distinct_thread_ids) > 1:
                raise CampaignEvidenceError(
                    f"{label} raw turns disagree on policy thread identity"
                )
            raw_thread_id = (
                distinct_thread_ids[0] if distinct_thread_ids else None
            )
            outcome_thread_id = outcome.get("thread_id")
            retryable_missing_outcome_thread = (
                outcome_thread_id is None
                and raw_thread_id is not None
                and _policy_retryable_failure_binds_raw_thread(
                    outcome,
                    task_root=task_root,
                    raw_thread_id=raw_thread_id,
                )
            )
            if (
                outcome_thread_id != raw_thread_id
                and not retryable_missing_outcome_thread
            ):
                raise CampaignEvidenceError(
                    f"{label} outcome thread identity differs from raw events"
                )
            if raw_thread_id is None:
                continue
            previous = seen_threads.get(raw_thread_id)
            if previous is not None:
                raise CampaignEvidenceError(
                    f"{label} reused policy thread identity from {previous}"
                )
            seen_threads[raw_thread_id] = label


def _policy_retryable_failure_binds_raw_thread(
    outcome: Mapping[str, Any],
    *,
    task_root: Path,
    raw_thread_id: str,
) -> bool:
    """Recognize a pre-agent failed turn whose outcome cannot expose a task."""

    checks = outcome.get("checks")
    failure = (
        checks.get("codex_infrastructure_failure")
        if isinstance(checks, Mapping)
        else None
    )
    sidecar_path = task_root / "infrastructure-failure.json"
    if (
        outcome.get("status") != "BLOCKED"
        or not isinstance(checks, Mapping)
        or checks.get("failure_classification") != "BLOCKED"
        or not isinstance(failure, Mapping)
        or not sidecar_path.exists()
    ):
        return False
    sidecar = load_strict_regular_json(sidecar_path)
    required_keys = {
        "contract",
        "scenario_id",
        "version",
        "failed_turn_index",
        "expected_turn_count",
        "prior_completed_turn_count",
        "previous_broker_prefix",
        "expected_failed_turn_prefix",
        "prior_thread_id",
        "prompt_sha256",
        "failure",
        "artifact_sha256",
    }
    if (
        not isinstance(sidecar, Mapping)
        or set(sidecar) != required_keys
        or sidecar.get("contract")
        != HEAVY_V3_TASK_INFRASTRUCTURE_FAILURE_CONTRACT
        or sidecar.get("failure") != dict(failure)
        or sidecar.get("version") != outcome.get("version")
        or type(sidecar.get("failed_turn_index")) is not int
        or type(sidecar.get("prior_completed_turn_count")) is not int
        or sidecar.get("failed_turn_index")
        != sidecar.get("prior_completed_turn_count") + 1
        or not isinstance(sidecar.get("prompt_sha256"), str)
        or _SHA256_RE.fullmatch(str(sidecar.get("prompt_sha256"))) is None
        or not isinstance(sidecar.get("artifact_sha256"), Mapping)
    ):
        return False
    prior_thread_id = sidecar.get("prior_thread_id")
    prior_completed_turn_count = sidecar["prior_completed_turn_count"]
    if prior_completed_turn_count > 0:
        return prior_thread_id == raw_thread_id
    return prior_thread_id is None


def write_campaign_marker(root: Path, *, campaign_id: str) -> None:
    atomic_write_json_with_digest(
        root / CAMPAIGN_MARKER_FILE,
        {
            "contract": CAMPAIGN_MARKER_CONTRACT,
            "campaign_id": campaign_id,
            "campaign_root": str(root.resolve(strict=True)),
            "created_at": utc_now(),
        },
    )


def verify_campaign_marker(root: Path, *, campaign_id: Any) -> None:
    from tests.semantic.support.codex_campaign import load_verified_json

    marker = load_verified_json(root / CAMPAIGN_MARKER_FILE)
    if (
        not isinstance(marker, Mapping)
        or marker.get("contract") != CAMPAIGN_MARKER_CONTRACT
        or marker.get("campaign_id") != campaign_id
        or marker.get("campaign_root") != str(root.resolve(strict=True))
    ):
        raise CampaignEvidenceError("campaign root marker is invalid or misbound")


def write_consolidated(root: Path, consolidated: Mapping[str, Any]) -> None:
    atomic_write_json_with_digest(root / CONSOLIDATED_SUMMARY_FILE, dict(consolidated))


def consolidated_exit(consolidated: Mapping[str, Any]) -> int | None:
    if consolidated.get("blocked_unit_ids"):
        return EXIT_BLOCKED
    if consolidated.get("failed_unit_ids"):
        return EXIT_FAIL
    if consolidated.get("all_selected_passed") is True:
        return EXIT_PASS
    return None


def print_status(consolidated: Mapping[str, Any]) -> None:
    print(
        "[campaign] status "
        f"pass={len(consolidated['passed_unit_ids'])} "
        f"pending={len(consolidated['pending_unit_ids'])} "
        f"retryable={len(consolidated['retryable_unit_ids'])} "
        f"fail={len(consolidated['failed_unit_ids'])} "
        f"blocked={len(consolidated['blocked_unit_ids'])}",
        flush=True,
    )


def ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values))


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args(argv: Sequence[str] | None) -> CampaignOptions:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--profile",
        type=matrix.parse_profile_id,
        metavar="{" + ",".join(matrix.PUBLIC_PROFILE_HELP_IDS) + "}",
        default="screening",
    )
    parser.add_argument("--suite")
    parser.add_argument("--skill-source", default=str(matrix.SKILL_ROOT))
    parser.add_argument(
        "--codex-binary",
        default=matrix.DEFAULT_CODEX_BINARY,
        help="explicit Codex CLI path; otherwise discover the host-native executable",
    )
    parser.add_argument("--auth-json", default=str(matrix.DEFAULT_AUTH_JSON))
    parser.add_argument("--live-config", default=str(matrix.DEFAULT_LIVE_CONFIG))
    parser.add_argument("--model")
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh", "ultra"),
        default="medium",
    )
    parser.add_argument("--service-tier")
    parser.add_argument("--timeout", type=float)
    parser.add_argument(
        "--wwise-readiness-timeout",
        type=float,
        default=60.0,
    )
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--version", action="append", choices=SUPPORTED_VERSIONS, default=[])
    parser.add_argument("--pair-id", action="append", default=[])
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    parser.add_argument("--max-pre-action-retries", type=int)
    args = parser.parse_args(argv)
    is_executable_v3 = args.profile in EXECUTABLE_V3_PROFILE_IDS
    is_policy_v3 = args.profile == MODIFICATION_POLICY_V3_PROFILE_ID
    is_compound_v1 = args.profile == COMPOUND_HEAVY_V1_PROFILE_ID
    is_typed_input = args.profile == TYPED_INPUT_PROFILE_ID
    is_deep_interface_mvp = args.profile == DEEP_INTERFACE_MVP_PROFILE_ID
    business_agent_profile = matrix.OFFLINE_BUSINESS_AGENT_PROFILES.get(args.profile)
    is_integration_v1 = args.profile == INTEGRATION_WORKFLOWS_V1_PROFILE_ID
    is_integration_v2 = args.profile == INTEGRATION_WORKFLOWS_V2_PROFILE_ID
    is_integration = args.profile == INTEGRATION_PROFILE_ID
    timeout_seconds = (
        float(args.timeout)
        if args.timeout is not None
        else (
            matrix.INTEGRATION_CODEX_TIMEOUT_SECONDS
            if is_integration
            else matrix.TYPED_INPUT_CODEX_TIMEOUT_SECONDS
            if is_typed_input
            else matrix.DEFAULT_CODEX_TIMEOUT_SECONDS
        )
    )
    is_terra_v3 = args.profile in TERRA_LOCKED_V3_PROFILE_IDS
    if args.verify_only and not args.resume:
        parser.error("--verify-only requires --resume")
    if timeout_seconds <= 0 or args.lock_timeout <= 0:
        parser.error("--timeout and --lock-timeout must be greater than zero")
    if (
        not math.isfinite(args.wwise_readiness_timeout)
        or args.wwise_readiness_timeout <= 0
    ):
        parser.error("--wwise-readiness-timeout must be positive and finite")
    max_pre_action_retries = (
        0
        if args.max_pre_action_retries is None
        and (is_typed_input or business_agent_profile is not None)
        else 1
        if args.max_pre_action_retries is None
        else int(args.max_pre_action_retries)
    )
    if max_pre_action_retries < 0:
        parser.error("--max-pre-action-retries must be zero or greater")
    if (is_typed_input or business_agent_profile is not None) and max_pre_action_retries != 0:
        parser.error(
            f"{args.profile} forbids same-root pre-action retries"
        )
    for name, values in (
        ("--case-id", args.case_id),
        ("--version", args.version),
        ("--pair-id", args.pair_id),
    ):
        if len(set(values)) != len(values):
            parser.error(f"{name} values must be unique")
    try:
        case_ids = (
            matrix.canonicalize_integration_case_ids(args.case_id)
            if is_integration
            else tuple(str(value) for value in args.case_id)
        )
    except ValueError as exc:
        parser.error(str(exc))
    if is_executable_v3 and args.pair_id:
        parser.error(f"--pair-id is not supported by {args.profile}")
    if (
        is_executable_v3
        and args.offline_only
        and business_agent_profile is None
    ):
        parser.error(f"--offline-only is not supported by {args.profile}")
    if not is_executable_v3:
        unknown_case_ids = sorted(set(args.case_id) - set(CASE_IDS))
        if unknown_case_ids:
            parser.error(
                "unknown v2 --case-id values: " + ", ".join(unknown_case_ids)
            )
    if is_deep_interface_mvp and any(
        version not in {"2022.1", "2025.1"} for version in args.version
    ):
        parser.error(
            f"{args.profile} supports only "
            "--version 2022.1 and 2025.1"
        )
    if business_agent_profile is not None and any(
        version not in business_agent_profile.supported_versions
        for version in args.version
    ):
        parser.error(
            f"{args.profile} supports only --version "
            + " and ".join(sorted(business_agent_profile.supported_versions))
        )
    if (
        is_compound_v1
        or is_integration_v1
        or is_integration_v2
        or is_integration
    ) and any(
        version not in {"2022.1", "2025.1"} for version in args.version
    ):
        parser.error(
            f"{args.profile} supports only "
            "--version 2022.1 and 2025.1"
        )
    model = args.model or (
        "gpt-5.6-terra" if is_terra_v3 else "gpt-5.6-sol"
    )
    service_tier = args.service_tier or (
        "default" if is_terra_v3 else "priority"
    )
    if is_terra_v3 and (
        model != "gpt-5.6-terra"
        or args.reasoning_effort != "medium"
        or service_tier != "default"
    ):
        parser.error(
            f"{args.profile} requires "
            "gpt-5.6-terra / medium / default"
        )
    suite = args.suite or str(
        (
            matrix.DEFAULT_MODIFICATION_POLICY_V3_SUITE
            if is_policy_v3
            else matrix.DEFAULT_DEEP_INTERFACE_MVP_SUITE
            if is_deep_interface_mvp
            else business_agent_profile.suite_path
            if business_agent_profile is not None
            else matrix.DEFAULT_TYPED_INPUT_SUITE
            if is_typed_input
            else (
                matrix.DEFAULT_INTEGRATION_SUITE
                if is_integration
                else (
                    matrix.DEFAULT_INTEGRATION_WORKFLOWS_V2_SUITE
                    if is_integration_v2
                    else (
                        matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE
                        if is_integration_v1
                        else matrix.DEFAULT_COMPOUND_HEAVY_V1_SUITE
                    )
                )
            )
        )
        if is_terra_v3
        else (matrix.DEFAULT_V3_SUITE if is_executable_v3 else matrix.DEFAULT_SUITE)
    )
    try:
        suite_path = Path(suite).expanduser().resolve(strict=True)
        skill_source = Path(args.skill_source).expanduser().resolve(strict=True)
        codex_binary = matrix.resolve_codex_binary(args.codex_binary)
        windows_powershell_core_host = (
            discover_windows_powershell_core(platform_name="nt")
            if os.name == "nt"
            else None
        )
        auth_json = Path(args.auth_json).expanduser().resolve(strict=True)
        live_config = Path(args.live_config).expanduser().resolve(
            strict=not args.offline_only
        )
    except (OSError, matrix.CodexHarnessError) as exc:
        parser.error(str(exc))
    return CampaignOptions(
        campaign_root=Path(args.campaign_root).expanduser().resolve(strict=False),
        resume=bool(args.resume),
        verify_only=bool(args.verify_only),
        profile=str(args.profile),
        suite_path=suite_path,
        skill_source=skill_source,
        codex_binary=codex_binary,
        auth_json=auth_json,
        live_config=live_config,
        model=str(model),
        reasoning_effort=str(args.reasoning_effort),
        service_tier=str(service_tier),
        timeout_seconds=timeout_seconds,
        case_ids=case_ids,
        versions=tuple(str(value) for value in args.version),
        pair_ids=tuple(str(value) for value in args.pair_id),
        offline_only=bool(args.offline_only),
        lock_timeout_seconds=float(args.lock_timeout),
        max_pre_action_retries=max_pre_action_retries,
        wwise_readiness_timeout_seconds=float(
            args.wwise_readiness_timeout
        ),
        windows_powershell_core_host=windows_powershell_core_host,
    )


if __name__ == "__main__":
    raise SystemExit(main())
